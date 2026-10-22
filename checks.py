# проверки данных перед сборкой отчета: если данные плохие, лучше не отправлять отчет, чем отправить неверные цифры

import sqlite3
from dataclasses import dataclass

import pandas as pd

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str


def load_orders(db_path):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM orders", conn)
    conn.close()
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


def run_checks(df, report_date, cfg, today=None):
    c = cfg["checks"]
    rd = pd.Timestamp(report_date)
    out = []
    day = df[df["order_date"] == rd]

    # свежесть: за отчетную дату должны быть строки
    if day.empty:
        out.append(Check("свежесть данных", FAIL, f"за {rd:%d.%m.%Y} нет ни одного заказа, последняя дата в базе {df['order_date'].max():%d.%m.%Y}"))
    else:
        out.append(Check("свежесть данных", OK, f"за {rd:%d.%m.%Y} найдено {len(day)} заказов"))

    # объем: сравниваем с тем же днем недели за четыре прошлые недели, сильное падение может быть неполной загрузкой
    prev = [len(df[df["order_date"] == rd - pd.Timedelta(days=7 * k)]) for k in range(1, 5)]
    typical = float(pd.Series(prev).median()) if prev else 0.0
    if typical > 0 and not day.empty:
        share = len(day) / typical
        if share < c["min_volume_share_warn"]:
            out.append(Check("объем заказов", WARN, f"заказов {len(day)} при обычных {typical:.0f} ({share:.0%}): либо сбой на сайте, либо неполная загрузка"))
        else:
            out.append(Check("объем заказов", OK, f"{len(day)} заказов при обычных {typical:.0f} ({share:.0%})"))

    # дубли по номеру заказа
    dup = int(day["order_id"].duplicated().sum()) if not day.empty else 0
    share = dup / max(len(day), 1)
    if dup == 0:
        out.append(Check("дубли заказов", OK, "дублей нет"))
    else:
        st = WARN if share <= c["max_duplicate_share_warn"] else FAIL
        out.append(Check("дубли заказов", st, f"{dup} дублей номера заказа ({share:.1%}), в расчете убираются"))

    # пропуски в справочных полях
    for col in ["region", "category"]:
        if day.empty:
            continue
        miss = float(day[col].isna().mean())
        if miss == 0:
            out.append(Check(f"пропуски в поле {col}", OK, "пропусков нет"))
        else:
            st = FAIL if miss > c["max_missing_share_fail"] else (WARN if miss > c["max_missing_share_warn"] else OK)
            out.append(Check(f"пропуски в поле {col}", st, f"пусто в {miss:.1%} строк"))

    # суммы
    if not day.empty:
        bad = int(((day["amount"] <= 0) & (day["status"] == "paid")).sum())
        out.append(Check("суммы оплаченных заказов", WARN if bad else OK,
                         f"{bad} оплаченных заказов с неположительной суммой, в расчете не учитываются" if bad else "все суммы положительные"))
    # будущим считаем дату позже сегодняшней по календарю: так повторная сборка старого отчета не пугает
    today = pd.Timestamp(today if today is not None else pd.Timestamp.today().normalize())
    future = int((df["order_date"] > today).sum())
    later = int((df["order_date"] > rd).sum())
    detail = "нет" if not future else f"{future} строк с датой позже сегодняшней, в расчет не попадают"
    if not future and later:
        detail = f"нет (строк позже отчетной даты {later}, это повторная сборка за прошлый день, они не учитываются)"
    out.append(Check("заказы из будущего", WARN if future else OK, detail))
    return out


def overall(checks):
    if any(x.status == FAIL for x in checks):
        return FAIL
    if any(x.status == WARN for x in checks):
        return WARN
    return OK


def clean_orders(df, report_date):
    # то, что проверки назвали проблемой, убираем, и считаем только оплаченные заказы до отчетной даты включительно
    rd = pd.Timestamp(report_date)
    d = df[df["order_date"] <= rd].drop_duplicates("order_id")
    d = d[(d["status"] == "paid") & (d["amount"] > 0)]
    return d
