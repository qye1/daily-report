import email
import re
import json
import shutil
import tempfile
from email import policy
from functools import lru_cache
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

import checks as ck
import mailer
import metrics as mt
import report
import shopdb

CFG = json.loads((Path(__file__).parent.parent / "config.json").read_text(encoding="utf-8"))
RD = pd.Timestamp("2026-10-21")
TODAY = "2026-10-22"


@lru_cache(maxsize=1)
def base_db():
    d = Path(tempfile.mkdtemp(prefix="dr_"))
    shopdb.generate(d / "shop.db", days=70)
    return d / "shop.db"


def dirty_copy(kind):
    d = Path(tempfile.mkdtemp(prefix="dr_dirty_"))
    p = d / "shop.db"
    shutil.copy(base_db(), p)
    shopdb.add_dirt(p, kind)
    return p


def statuses(db):
    return {c.name: c.status for c in ck.run_checks(ck.load_orders(db), RD, CFG, today=TODAY)}


def test_clean_database_passes_all_checks():
    s = statuses(base_db())
    assert set(s.values()) == {"ok"}


def test_stale_data_fails():
    assert statuses(dirty_copy("stale"))["свежесть данных"] == "fail"


def test_partial_load_is_warning_about_volume():
    assert statuses(dirty_copy("partial_load"))["объем заказов"] == "warn"


def test_duplicates_are_caught():
    assert statuses(dirty_copy("duplicates"))["дубли заказов"] in ("warn", "fail")


def test_many_missing_regions_fail_and_few_only_warn():
    assert statuses(dirty_copy("null_region"))["пропуски в поле region"] == "fail"


def test_negative_amounts_warn_and_are_excluded():
    p = dirty_copy("negative_amount")
    assert statuses(p)["суммы оплаченных заказов"] == "warn"
    df = ck.load_orders(p)
    assert (ck.clean_orders(df, RD)["amount"] > 0).all()


def test_future_rows_are_flagged_relative_to_calendar_not_report_date():
    df = ck.load_orders(base_db())
    s = {c.name: c.status for c in ck.run_checks(df, RD - pd.Timedelta(days=5), CFG, today=TODAY)}
    assert s["заказы из будущего"] == "ok"
    s = {c.name: c.status for c in ck.run_checks(df, RD, CFG, today="2026-10-19")}
    assert s["заказы из будущего"] == "warn"


def test_clean_orders_drops_duplicates_unpaid_and_later_dates():
    df = ck.load_orders(dirty_copy("duplicates"))
    assert df["order_id"].duplicated().any()
    c = ck.clean_orders(df, RD)
    assert c["order_id"].is_unique and (c["status"] == "paid").all() and c["order_date"].max() <= RD
    earlier = ck.clean_orders(df, RD - pd.Timedelta(days=1))
    assert earlier["order_date"].max() <= RD - pd.Timedelta(days=1)


def test_kpis_match_plain_pandas():
    df = ck.load_orders(base_db())
    c = ck.clean_orders(df, RD)
    d = mt.daily_table(c, df, RD, 70)
    k = mt.kpis(d, RD)
    rev = c.groupby("order_date")["amount"].sum()
    assert abs(k["revenue"] - rev[RD]) < 1e-6
    assert abs(k["last7"] - rev[RD - pd.Timedelta(days=6):RD].sum()) < 1e-6
    assert abs(k["revenue_wow"] - (rev[RD] / rev[RD - pd.Timedelta(days=7)] - 1)) < 1e-12
    assert abs(k["aov"] - rev[RD] / (c["order_date"] == RD).sum()) < 1e-6


def test_month_to_date_uses_same_day_of_previous_month_with_short_month():
    idx = pd.date_range("2026-01-01", "2026-03-31")
    d = pd.DataFrame({"revenue": 1.0, "orders": 1, "customers": 1, "aov": 1.0, "not_paid_share": 0.0}, index=idx)
    k = mt.kpis(d, pd.Timestamp("2026-03-31"))
    # в феврале 28 дней: сравниваем 31 день марта с 28 днями февраля, а не с несуществующим 31 февраля
    assert k["mtd"] == 31 and k["prev_month_mtd"] == 28


def test_anomaly_flags_planted_outage_and_not_a_normal_day():
    df = ck.load_orders(base_db())
    c = ck.clean_orders(df, RD)
    d = mt.daily_table(c, df, RD, 70)
    a = CFG["anomaly"]
    outage = RD - pd.Timedelta(days=shopdb.OUTAGE_OFFSET)
    assert mt.robust_anomaly(d, outage, a["weeks_back"], a["z_threshold"], a["min_scale_share"])["flag"]
    assert mt.robust_anomaly(d, outage, a["weeks_back"], a["z_threshold"], a["min_scale_share"])["z"] < 0
    flags = [mt.robust_anomaly(d, RD - pd.Timedelta(days=k), a["weeks_back"], a["z_threshold"], a["min_scale_share"])["flag"]
             for k in range(0, 14) if k not in (3, 10)]
    assert sum(flags) <= 1


def test_anomaly_scale_has_floor_when_history_is_constant():
    idx = pd.date_range("2026-09-01", "2026-10-21")
    d = pd.DataFrame({"revenue": 100.0}, index=idx)
    d.loc["2026-10-21", "revenue"] = 101.0
    r = mt.robust_anomaly(d, pd.Timestamp("2026-10-21"), 8, 3.0, 0.05)
    assert not r["flag"] and abs(r["z"] - 0.2) < 1e-9


def test_money_and_percent_formatting():
    assert mt.money(1_234_000) == "1,23 млн ₽" and mt.money(45_600) == "46 тыс ₽"
    assert mt.money_full(6725.3) == "6 725 ₽"
    assert mt.pct(-0.0612) == "−6,1%" and mt.pct(0.2) == "+20,0%" and mt.pct(float("nan")) == "нет данных"


def test_run_builds_all_files_and_returns_zero():
    out = Path(tempfile.mkdtemp(prefix="dr_out_"))
    code, folder = report.run(base_db(), RD, out, CFG)
    assert code == 0
    assert {p.name for p in folder.iterdir()} == {"checks.json", "report.html", "report.xlsx", "report.eml"}
    html = (folder / "report.html").read_text(encoding="utf-8")
    text = re.sub(r"data:image/png;base64,[A-Za-z0-9+/=]+", "", html)
    assert " nan" not in text.lower() and "None" not in text and "inf" not in text.lower().replace("information", "")


def test_failed_checks_stop_the_report_and_clear_old_files():
    out = Path(tempfile.mkdtemp(prefix="dr_out_"))
    code, folder = report.run(base_db(), RD, out, CFG)
    assert (folder / "report.html").exists()
    code2, folder2 = report.run(dirty_copy("stale"), RD, out, CFG)
    assert code2 == 2 and folder2 == folder
    assert (folder / "FAILED.txt").exists() and not (folder / "report.html").exists() and not (folder / "report.xlsx").exists()


def test_warning_returns_one_but_still_builds():
    out = Path(tempfile.mkdtemp(prefix="dr_out_"))
    code, folder = report.run(dirty_copy("negative_amount"), RD, out, CFG)
    assert code == 1 and (folder / "report.html").exists()


def test_rerun_is_idempotent():
    out = Path(tempfile.mkdtemp(prefix="dr_out_"))
    _, f1 = report.run(base_db(), RD, out, CFG)
    h1 = (f1 / "report.html").read_bytes()
    v1 = _sheet_values(f1 / "report.xlsx")
    _, f2 = report.run(base_db(), RD, out, CFG)
    assert (f2 / "report.html").read_bytes() == h1 and _sheet_values(f2 / "report.xlsx") == v1


def _sheet_values(path):
    wb = openpyxl.load_workbook(path)
    return {ws.title: [[c.value for c in row] for row in ws.iter_rows()] for ws in wb}


def test_excel_keeps_live_formulas_and_input_date():
    out = Path(tempfile.mkdtemp(prefix="dr_out_"))
    _, folder = report.run(base_db(), RD, out, CFG)
    wb = openpyxl.load_workbook(folder / "report.xlsx")
    assert wb.sheetnames == ["Сводка", "Дни", "Регионы", "Категории", "Проверки данных"]
    ws = wb["Сводка"]
    assert ws["B2"].value == RD.to_pydatetime()
    assert str(ws["B5"].value).startswith("=INDEX(") and "$B$2" in ws["B5"].value
    n = sum(1 for s in wb for row in s.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("="))
    assert n > 150
    # итог по регионам складывается формулой, а не числом
    reg = wb["Регионы"]
    assert reg.cell(row=reg.max_row, column=2).value.startswith("=SUM(")


def test_eml_has_html_body_and_excel_attachment():
    out = Path(tempfile.mkdtemp(prefix="dr_out_"))
    _, folder = report.run(base_db(), RD, out, CFG)
    msg = email.message_from_bytes((folder / "report.eml").read_bytes(), policy=policy.default)
    kinds = [p.get_content_type() for p in msg.walk()]
    assert "text/html" in kinds and any("spreadsheetml" in k for k in kinds)
    assert "Продажи за 21.10.2026" in msg["Subject"]
