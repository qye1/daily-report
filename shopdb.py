# учебная база продаж интернет магазина: заказы за 150 дней с заложенными событиями
# заложено: провал выручки за три дня до конца, акция в категории за десять дней до конца

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

REGIONS = ["Москва", "Санкт Петербург", "Поволжье", "Урал", "Сибирь", "Юг"]
REGION_P = [0.30, 0.15, 0.15, 0.10, 0.12, 0.18]
CATEGORIES = ["электроника", "дом", "одежда", "красота"]
CATEGORY_P = [0.25, 0.30, 0.30, 0.15]
CATEGORY_PRICE = [9000, 2800, 2200, 1500]
WEEKDAY = [0.90, 0.95, 1.00, 1.00, 1.10, 1.25, 1.15]      # понедельник ... воскресенье

OUTAGE_OFFSET = 3             # во сколько дней до конца данных был провал
PROMO_OFFSET = 10


def generate(path, end="2026-10-21", days=150, seed=3):
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(end)
    rows = []
    oid = 1
    for i in range(days):
        day = end - pd.Timedelta(days=days - 1 - i)
        lam = 230 * WEEKDAY[day.weekday()] * (1 + 0.0012 * i)
        lam *= 0.55 if (end - day).days == OUTAGE_OFFSET else 1.0
        n = int(rng.poisson(lam))
        secs = rng.choice(86400, size=n, p=_hour_p())
        region = rng.choice(REGIONS, size=n, p=REGION_P)
        cat_idx = rng.choice(len(CATEGORIES), size=n, p=CATEGORY_P)
        if (end - day).days == PROMO_OFFSET:
            # акция в одной категории тянет заказы в нее
            extra = int(n * 0.35)
            cat_idx = np.r_[cat_idx, np.full(extra, 2)]
            secs = np.r_[secs, rng.choice(86400, size=extra, p=_hour_p())]
            region = np.r_[region, rng.choice(REGIONS, size=extra, p=REGION_P)]
            n += extra
        qty = rng.choice([1, 1, 1, 2, 3], size=n)
        price = rng.lognormal(0, 0.35, size=n) * np.array(CATEGORY_PRICE)[cat_idx]
        status = rng.choice(["paid", "cancelled", "refunded"], size=n, p=[0.92, 0.06, 0.02])
        for j in range(n):
            ts = day + pd.Timedelta(seconds=int(secs[j]))
            rows.append((oid, ts.strftime("%Y-%m-%d %H:%M:%S"), ts.strftime("%Y-%m-%d"), int(rng.integers(1, 20000)),
                         str(region[j]), CATEGORIES[cat_idx[j]], int(qty[j]), round(float(price[j] * qty[j]), 2), str(status[j])))
            oid += 1
    df = pd.DataFrame(rows, columns=["order_id", "order_ts", "order_date", "customer_id", "region", "category", "qty", "amount", "status"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    df.to_sql("orders", conn, index=False)
    conn.execute("CREATE INDEX ix_orders_date ON orders(order_date)")
    conn.commit()
    conn.close()
    return df


def _hour_p():
    h = np.array([1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 9, 10, 11, 11, 10, 9, 9, 9, 10, 11, 12, 11, 7, 3], float)
    p = np.repeat(h, 3600)
    return p / p.sum()


def add_dirt(path, kind):
    # порча базы для проверки защитных проверок: каждый вид ломает одно свойство данных
    conn = sqlite3.connect(path)
    last = conn.execute("SELECT MAX(order_date) FROM orders").fetchone()[0]
    if kind == "stale":
        conn.execute("DELETE FROM orders WHERE order_date = ?", (last,))
    elif kind == "partial_load":
        conn.execute("DELETE FROM orders WHERE order_date = ? AND order_id % 10 <> 0", (last,))
    elif kind == "duplicates":
        conn.execute("INSERT INTO orders SELECT * FROM orders WHERE order_date = ? AND order_id % 20 = 0", (last,))
    elif kind == "null_region":
        conn.execute("UPDATE orders SET region = NULL WHERE order_date = ? AND order_id % 4 = 0", (last,))
    elif kind == "negative_amount":
        conn.execute("UPDATE orders SET amount = -amount WHERE order_date = ? AND order_id % 50 = 0", (last,))
    else:
        raise ValueError(kind)
    conn.commit()
    conn.close()
