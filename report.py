# ежедневный отчет одной командой
#   python report.py                      вчерашний день, база data/shop.db
#   python report.py --date ДАТА          конкретная дата в формате ISO, например 2026 10 21 через дефисы
# код возврата: 0 все хорошо, 1 отчет собран, но есть предупреждения, 2 данные плохие и отчета нет

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

import build_excel
import build_html
import checks as ck
import mailer
import metrics as mt
import shopdb

ROOT = Path(__file__).parent


def run(db, rd, out_dir, cfg, send=False, log=None):
    log = log or logging.getLogger("report")
    rd = pd.Timestamp(rd)
    day_dir = Path(out_dir) / f"{rd:%Y-%m-%d}"
    day_dir.mkdir(parents=True, exist_ok=True)
    df = ck.load_orders(db)
    results = ck.run_checks(df, rd, cfg)
    status = ck.overall(results)
    (day_dir / "checks.json").write_text(
        json.dumps([c.__dict__ for c in results], ensure_ascii=False, indent=2), encoding="utf-8")
    for c in results:
        log.info("проверка %s: %s, %s", c.name, c.status, c.detail)
    for stale in ["report.html", "report.xlsx", "report.eml", "FAILED.txt"]:
        (day_dir / stale).unlink(missing_ok=True)
    if status == ck.FAIL:
        text = "\n".join(f"{c.status.upper()}: {c.name}: {c.detail}" for c in results if c.status != ck.OK)
        (day_dir / "FAILED.txt").write_text("Отчет не собран, данные не прошли проверки.\n" + text, encoding="utf-8")
        log.error("отчет за %s не собран: данные не прошли проверки", f"{rd:%Y-%m-%d}")
        return 2, day_dir

    clean = ck.clean_orders(df, rd)
    daily_full = mt.daily_table(clean, df, rd, max(150, cfg["history_days_in_excel"]))
    k = mt.kpis(daily_full, rd)
    a = cfg["anomaly"]
    an = mt.robust_anomaly(daily_full, rd, a["weeks_back"], a["z_threshold"], a["min_scale_share"])
    # соседние дни графика подсвечиваем, если они тоже были аномальными
    shown = daily_full.tail(cfg["chart_days"]).index
    anomaly_days = [d for d in shown if d != rd and mt.robust_anomaly(daily_full, d, a["weeks_back"], a["z_threshold"], a["min_scale_share"])["flag"]]
    regions = mt.breakdown(clean, rd, "region")
    categories = mt.breakdown(clean, rd, "category")
    lines = mt.insights(k, an, regions, categories, rd, cfg["currency"])
    if status == ck.WARN:
        lines.append("Есть предупреждения проверок данных, цифры считались без проблемных строк, подробности ниже.")

    html = build_html.build_html(daily_full, regions, categories, results, lines, an, k, rd, cfg, anomaly_days)
    (day_dir / "report.html").write_text(html, encoding="utf-8")
    build_excel.build_workbook(day_dir / "report.xlsx", daily_full, regions, categories, results, lines, an, rd, cfg)
    subject = f"Продажи за {rd:%d.%m.%Y}: {mt.money(k['revenue'], cfg['currency'])}, {mt.pct(k['revenue_wow'])} к неделе"
    if an["flag"]:
        subject = "[аномалия] " + subject
    msg = mailer.build_message(html, day_dir / "report.xlsx", subject, cfg)
    mailer.save_eml(msg, day_dir / "report.eml")
    if send:
        mailer.send_smtp(msg)
        log.info("письмо отправлено")
    log.info("отчет за %s собран: %s", f"{rd:%Y-%m-%d}", subject)
    return (1 if status == ck.WARN else 0), day_dir


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "shop.db"))
    ap.add_argument("--date", default=None, help="отчетная дата, по умолчанию вчера")
    ap.add_argument("--out", default=str(ROOT / "reports"))
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--send", action="store_true", help="отправить письмо по SMTP, настройки в переменных окружения")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(out / "run.log", encoding="utf-8"), logging.StreamHandler()])
    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    if not Path(args.db).exists():
        logging.info("базы нет, создаю учебную")
        shopdb.generate(args.db)
    rd = args.date or (date.today() - timedelta(days=1)).isoformat()
    code, folder = run(args.db, rd, out, cfg, send=args.send)
    print("код возврата", code, "папка", folder)
    return code


if __name__ == "__main__":
    sys.exit(main())
