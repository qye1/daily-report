# показатели отчета: день, неделя, месяц, регионы, категории, аномалия и текстовые выводы

import numpy as np
import pandas as pd


def daily_table(clean, all_orders, end, days):
    rng = pd.date_range(end - pd.Timedelta(days=days - 1), end)
    g = clean.groupby("order_date")
    t = pd.DataFrame({"revenue": g["amount"].sum(), "orders": g.size(), "customers": g["customer_id"].nunique()})
    t = t.reindex(rng).fillna(0)
    t["aov"] = np.where(t["orders"] > 0, t["revenue"] / t["orders"].replace(0, np.nan), 0)
    t.index.name = "date"
    allg = all_orders.groupby("order_date")
    cancelled = allg["status"].apply(lambda s: (s != "paid").mean()).reindex(rng)
    t["not_paid_share"] = cancelled.fillna(0)
    return t


def robust_anomaly(daily_full, rd, weeks_back, z_threshold, min_scale_share):
    # ожидаемое значение дня это медиана тех же дней недели за прошлые недели, масштаб это MAD с нижней границей
    hist = np.array([daily_full["revenue"].get(rd - pd.Timedelta(days=7 * k), np.nan) for k in range(1, weeks_back + 1)])
    hist = hist[~np.isnan(hist)]
    if len(hist) < 4:
        return {"expected": np.nan, "z": np.nan, "flag": False}
    med = float(np.median(hist))
    mad = float(np.median(np.abs(hist - med))) * 1.4826
    scale = max(mad, min_scale_share * med)
    x = float(daily_full["revenue"].get(rd, np.nan))
    z = (x - med) / scale
    return {"expected": med, "z": z, "flag": bool(abs(z) > z_threshold), "value": x}


def breakdown(clean, rd, col):
    d0 = clean[clean["order_date"] == rd].groupby(col)["amount"].sum()
    d7 = clean[clean["order_date"] == rd - pd.Timedelta(days=7)].groupby(col)["amount"].sum()
    t = pd.DataFrame({"today": d0, "week_ago": d7}).fillna(0)
    t["change"] = t["today"] - t["week_ago"]
    return t.sort_values("today", ascending=False)


def kpis(daily, rd):
    def val(d, col):
        return float(daily[col].get(d, np.nan))
    d7 = rd - pd.Timedelta(days=7)
    out = {"revenue": val(rd, "revenue"), "orders": val(rd, "orders"), "aov": val(rd, "aov"), "customers": val(rd, "customers"),
           "revenue_week_ago": val(d7, "revenue"), "orders_week_ago": val(d7, "orders"), "aov_week_ago": val(d7, "aov")}
    out["revenue_wow"] = out["revenue"] / out["revenue_week_ago"] - 1 if out["revenue_week_ago"] else np.nan
    last7 = daily.loc[rd - pd.Timedelta(days=6): rd, "revenue"].sum()
    prev7 = daily.loc[rd - pd.Timedelta(days=13): rd - pd.Timedelta(days=7), "revenue"].sum()
    out["last7"], out["prev7"] = float(last7), float(prev7)
    out["last7_change"] = last7 / prev7 - 1 if prev7 else np.nan
    # с начала месяца против того же числа прошлого месяца
    m0 = rd.replace(day=1)
    pm_end = m0 - pd.Timedelta(days=1)
    pm0 = pm_end.replace(day=1)
    pm_same = min(pm0 + pd.Timedelta(days=rd.day - 1), pm_end)
    mtd = daily.loc[m0:rd, "revenue"].sum() if m0 >= daily.index.min() else np.nan
    pm = daily.loc[pm0:pm_same, "revenue"].sum() if pm0 >= daily.index.min() else np.nan
    out["mtd"], out["prev_month_mtd"] = mtd, pm
    out["mtd_change"] = mtd / pm - 1 if pm and not np.isnan(pm) else np.nan
    return out


def money(x, cur="₽"):
    if abs(x) >= 1e6:
        return f"{x / 1e6:.2f} млн {cur}".replace(".", ",")
    if abs(x) >= 1e3:
        return f"{x / 1e3:.0f} тыс {cur}"
    return f"{x:.0f} {cur}"


def money_full(x, cur="₽"):
    return f"{x:,.0f}".replace(",", " ") + f" {cur}"


def pct(x, signed=True):
    if x is None or np.isnan(x):
        return "нет данных"
    s = f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"
    return s.replace(".", ",").replace("-", "−")


def insights(k, anomaly, regions, categories, rd, cur="₽"):
    lines = []
    lines.append(f"Выручка за {rd:%d.%m.%Y}: {money(k['revenue'], cur)}, {pct(k['revenue_wow'])} к такому же дню неделей раньше.")
    if anomaly["flag"]:
        direction = "ниже" if anomaly["z"] < 0 else "выше"
        lines.append(f"Значение заметно {direction} обычного для этого дня недели: ожидалось около {money(anomaly['expected'], cur)}, "
                     f"отклонение {str(round(abs(anomaly['z']), 1)).replace('.', ',')} робастных сигм.")
    else:
        lines.append(f"В пределах обычного для этого дня недели (ожидалось около {money(anomaly['expected'], cur)}).")
    for name, verb, t in [("регион", "дал", regions), ("категория", "дала", categories)]:
        if len(t) and abs(t["change"]).max() > 0:
            top = t["change"].abs().idxmax()
            lines.append(f"Главный вклад в изменение к прошлой неделе {verb} {name} «{top}»: {money(t.loc[top, 'change'], cur).replace('-', '−')}.")
    lines.append(f"За последние 7 дней выручка {pct(k['last7_change'])} к предыдущим семи дням.")
    return lines
