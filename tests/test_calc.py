"""Тесты расчётного ядра: формулы, перенос остатка, статусы."""
import pytest

from app import calc


def months(*values: float) -> list[float]:
    """Дополняет список до 12 месяцев нулями."""
    out = list(values) + [0.0] * (12 - len(values))
    return out[:12]


# ---------- базовые формулы ----------

def test_totals_повторяют_формулы_листа_оперплан():
    # Arrange — строка «Аренда VM (Мастертел)» из реального файла
    plan_year = 8_600_000.0
    fact = months(0, 650_000, 650_000, 650_000)          # закрыто по апрель
    claims = months(0, 0, 0, 0, 650_000)                  # заявка на май

    # Act
    t = calc.totals(plan_year=plan_year, fact_months=fact, claim_months=claims)

    # Assert
    assert t["fact"] == 1_950_000
    assert t["claims"] == 650_000
    assert t["operplan"] == 2_600_000          # Итого опер план = факт + заявки
    assert t["cash_remain"] == 6_650_000       # Остаток бюджета = БЮДЖЕТ − Факт
    assert t["free_limit"] == 6_000_000        # Бюджет-опер план = БЮДЖЕТ − Итого опер план


def test_освоение_в_процентах_и_нулевой_план():
    assert calc.totals(1000.0, months(250), months())["pct"] == pytest.approx(0.25)
    assert calc.totals(0.0, months(500), months())["pct"] == 0.0


def test_перерасход_даёт_отрицательный_остаток():
    t = calc.totals(300_000.0, months(739_983.2), months())
    assert t["cash_remain"] == pytest.approx(-439_983.2)
    assert t["free_limit"] == pytest.approx(-439_983.2)


# ---------- перенос неиспользованного остатка ----------

def test_неиспользованный_остаток_переходит_на_следующий_месяц():
    # Arrange — план по 100 в январе и феврале, в январе потратили 40
    plan = months(100, 100)
    spent = months(40, 0)

    # Act
    res = calc.monthly_limits(plan, spent, carryover=True)

    # Assert
    assert res["limit"][0] == 100
    assert res["carry"][0] == 60          # 60 не использовано
    assert res["limit"][1] == 160         # февраль получил перенос


def test_перенос_накапливается_за_несколько_месяцев():
    res = calc.monthly_limits(months(100, 100, 100), months(0, 0, 0), carryover=True)
    assert res["limit"][2] == 300


def test_без_флага_переноса_лимит_месяца_не_растёт():
    res = calc.monthly_limits(months(100, 100), months(0, 0), carryover=False)
    assert res["limit"][1] == 100
    assert res["carry"][0] == 0


def test_превышение_лимита_месяца_не_уходит_в_минус_переноса():
    # Arrange — в январе потратили больше лимита
    res = calc.monthly_limits(months(100, 100), months(150, 0), carryover=True)

    # Assert — перенос не отрицательный, зафиксировано превышение
    assert res["carry"][0] == 0
    assert res["over"][0] == 50
    assert res["limit"][1] == 100


def test_перенос_обнуляется_в_конце_года():
    res = calc.monthly_limits(months(*([100] * 12)), months(), carryover=True)
    assert res["carry"][11] == 1200
    assert calc.year_end_carry(res) == 0    # в новый год остаток не переходит


# ---------- статусы ----------

def test_статус_перерасход_когда_факт_больше_бюджета():
    t = calc.totals(300_000.0, months(400_000), months())
    assert calc.status(t, pace=0.6)[0] == "critical"


def test_статус_заявки_сверх_лимита():
    t = calc.totals(1_000_000.0, months(500_000), months(0, 0, 0, 0, 0, 700_000))
    assert calc.status(t, pace=0.6)[0] == "serious"


def test_статус_опережение_темпа():
    t = calc.totals(1_000_000.0, months(900_000), months())
    assert calc.status(t, pace=0.6)[0] == "warning"


def test_статус_в_графике():
    t = calc.totals(1_000_000.0, months(600_000), months())
    assert calc.status(t, pace=0.6)[0] == "good"


# ---------- вспомогательное ----------

def test_ожидаемый_темп_освоения_по_отчётной_дате():
    assert calc.pace(closed_through=6, day_share=0.5) == pytest.approx(6.5 / 12)
    assert calc.pace(closed_through=12, day_share=0.0) == pytest.approx(1.0)


def test_месяц_платежа_из_даты():
    assert calc.month_of("2026-08-04") == 8
    assert calc.month_of("") == 0