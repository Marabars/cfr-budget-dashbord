"""Расчётное ядро бюджетов ЦФО.

Формулы повторяют лист «Оперплан ЦФО» файла Ликвидность:
    Итого опер план  = Факт + неоплаченные заявки
    Остаток бюджета  = БЮДЖЕТ − Факт                  (остаток по кассе)
    Бюджет-опер план = БЮДЖЕТ − Итого опер план        (свободный лимит)
"""
from __future__ import annotations

from datetime import date
from typing import Sequence

MONTHS = 12
MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
MONTH_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
               "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]

STATUS_GOOD = ("good", "в графике")
STATUS_WARNING = ("warning", "опережает темп")
STATUS_SERIOUS = ("serious", "заявки сверх лимита")
STATUS_CRITICAL = ("critical", "перерасход")


def zeros() -> list[float]:
    return [0.0] * MONTHS


def normalize(values: Sequence[float] | None) -> list[float]:
    """Приводит список к 12 элементам с числами."""
    out = zeros()
    for i, v in enumerate(values or []):
        if i >= MONTHS:
            break
        out[i] = float(v or 0)
    return out


def month_of(iso_date: str) -> int:
    """Номер месяца (1..12) из даты YYYY-MM-DD; 0 если дата пустая или неверная."""
    if not iso_date or len(iso_date) < 7:
        return 0
    try:
        return int(iso_date[5:7])
    except ValueError:
        return 0


def totals(plan_year: float, fact_months: Sequence[float], claim_months: Sequence[float]) -> dict:
    """Сводные величины по строке или бюджету."""
    fact_m = normalize(fact_months)
    claim_m = normalize(claim_months)
    plan = float(plan_year or 0)
    fact = sum(fact_m)
    claims = sum(claim_m)
    operplan = fact + claims
    return {
        "plan_year": plan,
        "fact": fact,
        "claims": claims,
        "operplan": operplan,
        "cash_remain": plan - fact,
        "free_limit": plan - operplan,
        "pct": (fact / plan) if plan else 0.0,
        "fact_months": fact_m,
        "claim_months": claim_m,
    }


def monthly_limits(plan_months: Sequence[float], spent_months: Sequence[float],
                   carryover: bool = True) -> dict:
    """Лимиты по месяцам с переносом неиспользованного остатка внутри строки.

    Возвращает списки на 12 месяцев:
        limit — доступно в месяце (план + перенос из предыдущего)
        spent — израсходовано (факт + заявки этого месяца)
        carry — что уходит в следующий месяц
        over  — превышение лимита месяца
    """
    plan = normalize(plan_months)
    spent = normalize(spent_months)
    limit, carry, over = zeros(), zeros(), zeros()
    brought = 0.0
    for m in range(MONTHS):
        limit[m] = plan[m] + (brought if carryover else 0.0)
        rest = limit[m] - spent[m]
        carry[m] = max(0.0, rest) if carryover else 0.0
        over[m] = max(0.0, -rest)
        brought = carry[m]
    return {"plan": plan, "limit": limit, "spent": spent, "carry": carry, "over": over}


def year_end_carry(limits: dict) -> float:
    """Остаток, переходящий на следующий год: всегда 0 — в конце года обнуляется."""
    return 0.0


def pace(closed_through: int, day_share: float = 0.0) -> float:
    """Ожидаемая доля освоения к отчётной дате.

    closed_through — последний закрытый месяц, day_share — пройденная часть текущего месяца.
    """
    closed = max(0, min(MONTHS, int(closed_through)))
    share = 0.0 if closed >= MONTHS else max(0.0, min(1.0, float(day_share)))
    return (closed + share) / MONTHS


def day_share_of(as_of: date) -> float:
    """Какая часть месяца отчётной даты уже прошла."""
    import calendar

    days = calendar.monthrange(as_of.year, as_of.month)[1]
    return as_of.day / days


def status(t: dict, pace_value: float = 0.0, warning_pp: float = 0.15,
           pace: float | None = None) -> tuple[str, str]:
    """Статус строки или бюджета. `pace` — синоним pace_value для краткости вызова."""
    expected = pace if pace is not None else pace_value
    if t["fact"] > t["plan_year"]:
        return STATUS_CRITICAL
    if t["free_limit"] < 0:
        return STATUS_SERIOUS
    if t["pct"] > expected + warning_pp:
        return STATUS_WARNING
    return STATUS_GOOD


def split_fact_and_claims(months_total: Sequence[float], closed_through: int,
                          current_month: int, fact_share: float = 1.0) -> tuple[list[float], list[float]]:
    """Делит суммы по месяцам на факт и заявки по границе закрытого периода.

    Используется при импорте листа «Оперплан ЦФО», где факт и прогноз лежат в одних колонках.
    """
    total = normalize(months_total)
    fact, claims = zeros(), zeros()
    for m in range(MONTHS):
        month_no = m + 1
        if month_no <= closed_through:
            fact[m] = total[m]
        elif month_no == current_month:
            fact[m] = total[m] * fact_share
            claims[m] = total[m] - fact[m]
        else:
            claims[m] = total[m]
    return fact, claims


def aggregate(items: list[dict]) -> dict:
    """Складывает итоги нескольких строк или бюджетов."""
    plan = sum(i["plan_year"] for i in items)
    fact_m, claim_m = zeros(), zeros()
    for i in items:
        for m in range(MONTHS):
            fact_m[m] += i["fact_months"][m]
            claim_m[m] += i["claim_months"][m]
    return totals(plan, fact_m, claim_m)