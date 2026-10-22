# HTML письмо: все стили внутри, картинка вшита, читается и на телефоне

import base64
import io
from html import escape

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import metrics as mt

STATUS = {"ok": ("#2f855a", "в порядке"), "warn": ("#b7791f", "внимание"), "fail": ("#c53030", "ошибка")}


def chart_png(daily, rd, anomaly_days, days):
    d = daily.tail(days)
    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=110)
    ax.bar(d.index, d["revenue"] / 1e6, color="#bee3f8", width=0.8, label="выручка за день")
    ax.plot(d.index, d["revenue"].rolling(7, min_periods=7).mean() / 1e6, color="#2b6cb0", lw=2, label="среднее за 7 дней")
    for day in anomaly_days:
        if day in d.index:
            ax.bar([day], [d.loc[day, "revenue"] / 1e6], color="#dd6b20", width=0.8)
    ax.bar([rd], [d.loc[rd, "revenue"] / 1e6], color="#2b6cb0", width=0.8, label="отчетный день")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_ylabel("млн ₽")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left")
    ax.margins(y=0.15)
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _card(title, value, change):
    color = "#718096" if change is None or np.isnan(change) else ("#2f855a" if change >= 0 else "#c53030")
    ch = mt.pct(change) if change is not None else ""
    return (f'<div style="flex:1 1 150px;padding:12px;border:1px solid #e2e8f0;border-radius:8px;text-align:center">'
            f'<div style="font-size:12px;color:#718096">{escape(title)}</div>'
            f'<div style="font-size:20px;font-weight:bold">{escape(value)}</div>'
            f'<div style="font-size:12px;color:{color}">{escape(ch)} к неделе</div></div>')


def _table(t, cur):
    rows = ""
    for name, r in t.iterrows():
        change = r["change"]
        color = "#2f855a" if change >= 0 else "#c53030"
        rows += (f'<tr><td style="padding:4px 8px">{escape(str(name))}</td>'
                 f'<td style="padding:4px 8px;text-align:right">{mt.money(r["today"], cur)}</td>'
                 f'<td style="padding:4px 8px;text-align:right;color:{color}">{mt.money(change, cur).replace("-", "−")}</td></tr>')
    return rows


def build_html(daily, regions, categories, checks, lines, anomaly, k, rd, cfg, anomaly_days):
    cur = cfg["currency"]
    img = chart_png(daily, rd, anomaly_days, cfg["chart_days"])
    cards = "".join([
        _card("Выручка", mt.money(k["revenue"], cur), k["revenue_wow"]),
        _card("Заказы", f"{k['orders']:.0f}", k["orders"] / k["orders_week_ago"] - 1 if k["orders_week_ago"] else None),
        _card("Средний чек", mt.money_full(k["aov"], cur), k["aov"] / k["aov_week_ago"] - 1 if k["aov_week_ago"] else None),
        _card("С начала месяца", mt.money(k["mtd"], cur) if not np.isnan(k["mtd"]) else "нет данных", k["mtd_change"]),
    ])
    li = "".join(f"<li style='margin:4px 0'>{escape(x)}</li>" for x in lines)
    ck = ""
    for c in checks:
        color, label = STATUS[c.status]
        ck += (f'<tr><td style="padding:4px 8px">{escape(c.name)}</td>'
               f'<td style="padding:4px 8px;color:{color};font-weight:bold">{label}</td>'
               f'<td style="padding:4px 8px;color:#4a5568">{escape(c.detail)}</td></tr>')
    banner = ""
    if anomaly["flag"]:
        banner = ('<div style="background:#fffaf0;border-left:4px solid #dd6b20;padding:10px 14px;margin:14px 0">'
                  f'<b>Аномалия.</b> Выручка отличается от обычной для этого дня недели на {str(round(abs(anomaly["z"]), 1)).replace(".", ",")} робастных сигм.</div>')
    th = 'style="padding:4px 8px;text-align:{a};border-bottom:2px solid #2b6cb0"'
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Отчет по продажам за {rd:%d.%m.%Y}</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;color:#1a202c;max-width:760px;margin:0 auto;padding:16px">
<h2 style="margin-bottom:2px">Отчет по продажам за {rd:%d.%m.%Y}</h2>
<div style="color:#718096;font-size:13px">данные магазина, только оплаченные заказы</div>
{banner}
<div style="display:flex;flex-wrap:wrap;gap:8px;margin:12px 0">{cards}</div>
<ul style="padding-left:18px">{li}</ul>
<img alt="График выручки" style="width:100%;max-width:740px" src="data:image/png;base64,{img}">
<div style="display:flex;flex-wrap:wrap;gap:24px;margin-top:14px">
<div style="flex:1;min-width:280px"><h3>Регионы</h3><table style="width:100%;border-collapse:collapse;font-size:14px">
<tr><th {th.format(a='left')}>регион</th><th {th.format(a='right')}>сегодня</th><th {th.format(a='right')}>к неделе</th></tr>{_table(regions, cur)}</table></div>
<div style="flex:1;min-width:280px"><h3>Категории</h3><table style="width:100%;border-collapse:collapse;font-size:14px">
<tr><th {th.format(a='left')}>категория</th><th {th.format(a='right')}>сегодня</th><th {th.format(a='right')}>к неделе</th></tr>{_table(categories, cur)}</table></div></div>
<h3>Проверки данных</h3>
<table style="width:100%;border-collapse:collapse;font-size:13px">{ck}</table>
<p style="color:#a0aec0;font-size:11px;margin-top:20px">Собрано автоматически. Подробности и формулы в приложенном файле Excel.</p>
</body></html>"""
