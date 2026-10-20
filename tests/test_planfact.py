"""Загрузка факта из файла дирекции «План-факт».

Файл приходит из стрима «План-факт по дирекциям»: лист «Оперплан ЦФО» с
группировкой строк (уровень 1 — план, уровень 2 — расход по контрагенту),
служебные строки «ВСЕГО» и «ВНЕ БЮДЖЕТА» на уровне 0, метки ФАКТ / ПРОГНОЗ
над шапкой.
"""
from __future__ import annotations

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import db, operplan, repo
from app.calc import MONTH_NAMES
from app.exporters import excel
from app.importers import planfact
from app.main import app

IT = "Первая дирекция"
HR = "Вторая дирекция"

PF_HEADER = ["№", "Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
             "Комментарий", "Комм наш", "Бюджет - опер план", "БЮДЖЕТ",
             "Оперплан с учетом факта", "Факт", "Остаток бюджета"] + MONTH_NAMES
PF_COL = {title: i + 1 for i, title in enumerate(PF_HEADER)}
PF_MONTH = PF_COL["Январь"]


def make_planfact_sheet(closed_through: int = 2, with_out_of_budget: bool = True,
                        with_orphan: bool = False, with_hr: bool = False,
                        budget: str = "Бюджет дирекции") -> bytes:
    """Файл дирекции: два плановых расхода с расшифровкой и один без неё.

    Январь и февраль помечены ФАКТом, март — прогнозом: прогноз в факт попасть
    не должен, хотя лежит в тех же колонках месяцев.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Оперплан ЦФО"

    for month in range(1, 13):
        ws.cell(row=3, column=PF_MONTH + month - 1,
                value="ФАКТ" if month <= closed_through else "ПРОГНОЗ")
    for col, value in enumerate(PF_HEADER, start=1):
        ws.cell(row=5, column=col, value=value)

    def put(row, level, values, months=None, budget=None, no=None):
        ws.row_dimensions[row].outline_level = level
        if no is not None:
            ws.cell(row=row, column=PF_COL["№"], value=no)
        for title, value in values.items():
            ws.cell(row=row, column=PF_COL[title], value=value)
        if budget is not None:
            ws.cell(row=row, column=PF_COL["БЮДЖЕТ"], value=budget)
        for m, amount in enumerate(months or []):
            if amount:
                ws.cell(row=row, column=PF_MONTH + m, value=amount)

    # «ВСЕГО» — итог по листу; как строка расхода он удваивал весь файл
    put(6, 0, {"Статья оборотов": "ВСЕГО"}, [300, 700, 1000])
    put(7, 0, {"Статья оборотов": "ИТОГО", "ЦФО": IT})          # пустой блок-дубль
    put(8, 0, {"Статья оборотов": "ИТОГО", "ЦФО": IT, "Договор": budget})

    # строка №1: контрагента нет, он на расходах под ней
    put(9, 1, {"Статья оборотов": "4411_Оборудование", "ЦФО": IT,
               "Детализация": "ИТ инфраструктура"}, [300, 700, 1000], budget=100_000, no=1)
    put(10, 2, {"Статья оборотов": "4411_Оборудование", "ЦФО": IT,
                "Контрагент": "Астра ООО", "Договор": "Договор №1",
                "Детализация": "ИТ инфраструктура", "Комм наш": "бюджет из строки 1"},
        [200, 500, 600])
    # у расхода пометки «из строки N» нет — его держит только группировка
    put(11, 2, {"Статья оборотов": "4411_Оборудование", "ЦФО": IT,
                "Контрагент": "Байт ООО", "Договор": "Договор №2",
                "Детализация": "ИТ инфраструктура"}, [100, 200, 400])

    # строка №2: расшифровки нет, факт лежит на ней самой
    put(12, 1, {"Статья оборотов": "4430_Разработка", "ЦФО": IT,
                "Контрагент": "Софт ООО", "Договор": "Договор №3",
                "Детализация": "Платформа"}, [50, 90, 70], budget=200_000, no=2)

    # плановая строка, которой у нас нет вовсе: ни по ключу, ни по сумме.
    # Её факт плана не создаёт — он уходит в непривязанное.
    # Вторая дирекция внутри файла первой: так приходит файл ИТ, который несёт
    # ещё бюджеты стратегии и аналитики. Блок открывается своим ИТОГО.
    if with_hr:
        put(20, 0, {"Статья оборотов": "ИТОГО", "ЦФО": HR,
                    "Договор": "Бюджет Дирекции по персоналу"})
        put(21, 1, {"Статья оборотов": "4109_Обучение", "ЦФО": HR,
                    "Комментарий": "Английский"}, [500, 300, 900], budget=50_000, no=1)

    # Порядок строк важен: всё, что стоит ниже заголовка «ВНЕ БЮДЖЕТА»,
    # разбирается как расход вне бюджета, поэтому сирота идёт выше него.
    if with_orphan:
        put(13, 1, {"Статья оборотов": "4777_Неизвестное", "ЦФО": IT,
                    "Контрагент": "Пришлая ООО", "Договор": "Договор №7",
                    "Детализация": "чего у нас нет"}, [40, 60, 900], budget=12_345, no=3)
        # расход под сиротой: сама строка пары не найдёт, а он может
        put(14, 2, {"Статья оборотов": "4777_Неизвестное", "ЦФО": IT,
                    "Контрагент": "Своя ООО", "Договор": "Договор №8",
                    "Детализация": "чего у нас нет"}, [40, 60, 900])

    if with_out_of_budget:
        put(15, 0, {"Статья оборотов": "ВНЕ БЮДЖЕТА",
                    "Комментарий": "факт, не сопоставленный ни с одной строкой бюджета"})
        put(16, 1, {"Статья оборотов": "4999_Прочее", "ЦФО": IT,
                    "Контрагент": "Омега ООО", "Договор": "Договор №9"},
            [0, 1_500, 400])

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def make_payments_sheet() -> bytes:
    """Лист «ФАКТ»: выгрузка платежей 1С, расход отрицательный, приход — нет."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ФАКТ"
    header = ["Период", "Проект", "Статья оборотов", "Организация", "Контрагент",
              "Договор контрагента", "Банковский счет", "НазначениеПлатежа",
              "Проект корр", "ЦФО", "Приход в рублях", "Расход в рублях", "Сумма УПР"]
    for col, value in enumerate(header, start=2):
        ws.cell(row=3, column=col, value=value)

    def put(row, day, article, counterparty, income, outcome, purpose=""):
        ws.cell(row=row, column=2, value=f"2026-{day}")
        ws.cell(row=row, column=4, value=article)
        ws.cell(row=row, column=6, value=counterparty)
        ws.cell(row=row, column=9, value=purpose)
        ws.cell(row=row, column=11, value=IT)
        ws.cell(row=row, column=12, value=income or None)
        ws.cell(row=row, column=13, value=outcome or None)
        ws.cell(row=row, column=14, value=income + outcome)

    put(4, "01-15", "4411_Оборудование", "Астра ООО", 0, -100_000, "Оплата счёта")
    put(5, "02-20", "4411_Оборудование", "Байт ООО", 0, -40_000, "Оплата счёта")
    # возврат: приход уменьшает расход, а не добавляет его
    put(6, "03-05", "1305_Прочий приход", "Депозит ООО", 25_000, 0,
        "Возврат депозита в связи с расторжением договора аренды")
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def make_our_budget_sheet() -> bytes:
    """Наша выгрузка «Бюджеты ЦФО»: факт лежит прямо в месяцах строки."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Бюджеты ЦФО"
    header = ["Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
              "Комментарий", "ИТОГО"] + MONTH_NAMES
    for col, value in enumerate(header, start=1):
        ws.cell(row=3, column=col, value=value)

    def put(row, values, months, total=None):
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)
        ws.cell(row=row, column=7, value=sum(months) if total is None else total)
        for m, amount in enumerate(months):
            if amount:
                ws.cell(row=row, column=8 + m, value=amount)

    put(4, ["ИТОГО", IT, None, "Бюджет обязательных затрат"], [800] + [0] * 11)
    put(5, ["4411_Оборудование", IT, "Астра ООО", "Договор №1", "ИТ инфраструктура",
            "Серверы"], [800] + [0] * 11)
    # ИТОГО заполнено, месяцы пусты — факт из такой строки не собрать
    put(6, ["4430_Разработка", IT, "Софт ООО", "Договор №3", "Платформа", "Доработки"],
        [0] * 12, total=5_000)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def make_plan_sheet() -> bytes:
    """План базового года: те строки, на которые должен лечь факт."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Бюджеты ЦФО"
    header = ["Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
              "Комментарий", "ИТОГО"] + MONTH_NAMES
    for col, value in enumerate(header, start=1):
        ws.cell(row=3, column=col, value=value)

    def put(row, values, total):
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)
        ws.cell(row=row, column=7, value=total)

    put(4, ["ИТОГО", IT, None, "Бюджет обязательных затрат"], 300_000)
    # у нашей строки контрагент есть, а у плановой строки файла — нет:
    # строгий ключ её не найдёт, каскад обязан дотянуться комментарием и суммой
    put(5, ["4411_Оборудование", IT, "Астра ООО", "Договор №1", "ИТ инфраструктура",
            "Серверы"], 100_000)
    put(6, ["4430_Разработка", IT, "Софт ООО", "Договор №3", "Платформа",
            "Доработки"], 200_000)
    put(7, ["ИТОГО", HR, None, None], 50_000)
    put(8, ["4109_Обучение", HR, None, None, None, "Английский"], 50_000)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDGET_DB", str(tmp_path / "test.db"))
    db.set_db_path(tmp_path / "test.db")
    db.init_db()
    db.set_setting("year", "2026")
    db.set_setting("operplan_year", "2027")
    db.set_setting("operplan_base_year", "2026")
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def planned(client):
    """Слой планирования с планом 2026 года — базой под факт."""
    operplan.import_budgets(make_plan_sheet(), "план.xlsx", 2026, "Тест")
    # детализация ИТ берётся из колонки бюджета, как на проде
    it = repo.find_cfo(IT)
    db.execute("UPDATE cfo SET detail_source = 'detail' WHERE id = ?", (int(it["id"]),))
    return it


# ---------- разбор ----------

def test_уровни_группировки_делят_план_и_расход():
    parsed = planfact.parse(make_planfact_sheet())
    assert [p["row_no"] for p in parsed["plans"]] == [1, 2]
    assert [p["counterparty"] for p in parsed["plans"][0]["parts"]] == ["Астра ООО", "Байт ООО"]
    assert parsed["plans"][1]["parts"] == []


def test_строка_всего_не_попадает_в_расходы():
    parsed = planfact.parse(make_planfact_sheet())
    assert [s["article"] for s in parsed["skipped_service"]] == ["ВСЕГО"]
    assert all(p["article"] != "ВСЕГО" for p in parsed["plans"])


def test_пустой_блок_итого_не_считается_блоком():
    parsed = planfact.parse(make_planfact_sheet())
    assert [b["budget"] for b in parsed["blocks"]] == ["Бюджет дирекции"]


def test_прогнозные_месяцы_в_факт_не_идут():
    parsed = planfact.parse(make_planfact_sheet())
    plan = parsed["plans"][0]
    assert sum(plan["months"]) == 2000           # январь + февраль + март
    assert sum(planfact.plan_fact_months(plan)) == 1000   # только январь и февраль


def test_факт_родителя_равен_сумме_расходов_под_ним():
    parsed = planfact.parse(make_planfact_sheet())
    plan = parsed["plans"][0]
    parts = sum(sum(p["fact_months"]) for p in plan["parts"])
    assert sum(planfact.plan_fact_months(plan)) == parts == 1000


def test_расход_без_пометки_держится_группировкой():
    """«Байт ООО» не пишет «из строки 1» — его относит только уровень."""
    parsed = planfact.parse(make_planfact_sheet())
    parts = parsed["plans"][0]["parts"]
    assert [p["approver_comment"] for p in parts] == ["бюджет из строки 1", ""]
    assert len(parts) == 2


def test_возврат_уменьшает_расход_а_не_увеличивает():
    """Приход в выгрузке 1С — это возврат, он расход гасит.

    Разбор однажды вычитал приход вместо сложения, и один возврат депозита
    давал расхождение ровно вдвое больше себя самого. «Сумма УПР» в выгрузке
    равна приход + расход, а расход со знаком «плюс = потрачено» получается
    из неё переменой знака.
    """
    parsed = planfact.parse_payments(make_payments_sheet())
    amounts = {p["counterparty"]: p["amount"] for p in parsed["payments"]}
    assert amounts["Астра ООО"] == 100_000
    assert amounts["Депозит ООО"] == -25_000, "возврат обязан быть отрицательным"
    assert parsed["total"] == 115_000           # 100 000 + 40 000 − 25 000


def test_лист_фактов_необязателен():
    """Часть файлов дирекций приходит без выгрузки платежей."""
    parsed = planfact.parse_payments(make_planfact_sheet())
    assert parsed["payments"] == [] and parsed["total"] == 0


def test_свободный_текст_финотдела_пометкой_не_считается():
    """В «Комм наш» рядом с пометкой генератора живёт текст из Оперплана.

    Генератор пишет каноничное «бюджет из строки N» в нумерации своего файла.
    Финотдел оставляет там же «из строки 33», «за счет строки 47» — это номера
    сквозной нумерации Оперплана по всем ЦФО, которая считает и строки ИТОГО,
    и указателем на строку нашего файла быть не может. Замерено на 12 файлах:
    каноничная пометка спорит с группировкой в 1% случаев, свободный текст —
    в 29%. Поэтому подтверждающим признаком берём только каноничную.
    """
    wb = openpyxl.load_workbook(io.BytesIO(make_planfact_sheet()))
    ws = wb["Оперплан ЦФО"]
    ws.cell(row=10, column=PF_COL["Комм наш"], value="за счет строки 7")
    buffer = io.BytesIO()
    wb.save(buffer)

    parsed = planfact.parse(buffer.getvalue())
    parts = parsed["plans"][0]["parts"]
    assert parts[0]["approver_comment"] == "за счет строки 7", "текст сохраняется как есть"
    assert parts[0]["parent_hint"] is None, "но указателем он не считается"
    assert parsed["conflicts"] == [], "и спором с группировкой тоже"
    # расход всё равно привязан — группировкой
    assert parts[0]["counterparty"] == "Астра ООО"


def test_каноничная_пометка_спорящая_с_группировкой_попадает_в_конфликты():
    wb = openpyxl.load_workbook(io.BytesIO(make_planfact_sheet()))
    ws = wb["Оперплан ЦФО"]
    ws.cell(row=10, column=PF_COL["Комм наш"], value="бюджет из строки 2")
    buffer = io.BytesIO()
    wb.save(buffer)
    parsed = planfact.parse(buffer.getvalue())
    assert parsed["conflicts"] == [{"excel_row": 10, "hint": 2, "group": 1}]


def test_вне_бюджета_разбирается_отдельным_блоком():
    parsed = planfact.parse(make_planfact_sheet())
    assert [x["counterparty"] for x in parsed["out_of_budget"]] == ["Омега ООО"]
    assert sum(parsed["out_of_budget"][0]["fact_months"]) == 1_500    # март — прогноз


# ---------- загрузка ----------

def test_загрузка_факта_не_трогает_план(planned):
    before = [(r["id"], r["article"], r["plan_year"])
              for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)]
    cfo_before = len(repo.list_cfo())
    budgets_before = len(repo.list_budgets(2026, layer=repo.LAYER_OPERPLAN))

    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")

    after = [(r["id"], r["article"], r["plan_year"])
             for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)]
    assert after == before
    assert len(repo.list_cfo()) == cfo_before
    assert len(repo.list_budgets(2026, layer=repo.LAYER_OPERPLAN)) == budgets_before


def test_каскад_находит_строку_по_комментарию_и_сумме(planned):
    """У плановой строки файла контрагента нет — строгий ключ её не свяжет."""
    plan = operplan.plan_fact(make_planfact_sheet(), 2026)
    linked = {item["row"]["article"]: sum(item["fact_months"]) for item in plan["matched"]}
    assert linked == {"4411_Оборудование": 1000, "4430_Разработка": 140}
    assert plan["unlinked"] == []


def test_факт_раскрывается_контрагентами(planned):
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    row = next(r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
               if r["article"] == "4411_Оборудование")
    spends = operplan.row_spends(2026)[int(row["id"])]
    assert [(s["counterparty"], s["total"]) for s in spends] == [
        ("Астра ООО", 700), ("Байт ООО", 300)]


def test_строка_без_расшифровки_показывает_своего_контрагента(planned):
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    row = next(r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
               if r["article"] == "4430_Разработка")
    spends = operplan.row_spends(2026)[int(row["id"])]
    assert [(s["counterparty"], s["total"]) for s in spends] == [("Софт ООО", 140)]


def test_вне_бюджета_видно_списком_и_плиткой(planned):
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    outside = operplan.unlinked_fact(2026)
    assert [(x["counterparty"], x["total"], x["out_of_budget"]) for x in outside] == [
        ("Омега ООО", 1_500, True)]
    assert operplan.kpi()["outside_total"] == 1_500
    assert operplan.kpi()["outside_cfo"] == 1


def test_у_расхода_детализация_и_комментарий_порознь(planned):
    """У расхода два текста, как и у строки плана (16.10.2026).

    До этого в базе под них было одно поле, и комментарий расхода не был
    виден нигде. Проверяется на расходе под строкой: в файле у него
    заполнена детализация, а комментарий пуст.
    """
    operplan.import_fact(make_planfact_sheet(with_hr=True), "план-факт.xlsx", 2026, "Тест")

    # у расхода первой дирекции заполнена детализация, комментарий пуст
    it_row = next(r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
                  if r["article"] == "4411_Оборудование")
    astra = next(s for s in operplan.row_spends(2026)[int(it_row["id"])]
                 if s["counterparty"] == "Астра ООО")
    assert (astra["detail"], astra["comment"]) == ("ИТ инфраструктура", "")

    # у расхода второй — наоборот: комментарий есть, детализации нет.
    # Прежде он уехал бы в то же единственное поле и выглядел детализацией.
    hr_row = next(r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
                  if int(r["cfo_id"]) == int(repo.find_cfo(HR)["id"]))
    hr_spend = operplan.row_spends(2026)[int(hr_row["id"])][0]
    assert (hr_spend["detail"], hr_spend["comment"]) == ("", "Английский")


def test_повторная_загрузка_не_задваивает(planned):
    first = operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    second = operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    assert first["total"] == second["total"] == 1140
    assert sum(sum(v) for v in repo.row_fact_months(2026, repo.LAYER_OPERPLAN).values()) == 1140
    assert len(operplan.unlinked_fact(2026)) == 1


def test_загрузка_по_одной_дирекции_не_трогает_соседнюю(planned):
    hr = repo.find_cfo(HR)
    row = next(r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
               if int(r["cfo_id"]) == int(hr["id"]))
    repo.set_row_fact(int(row["id"]), [7_000] + [0] * 11)

    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест",
                         only_cfo_ids=[int(repo.find_cfo(IT)["id"])])

    months = repo.row_fact_months(2026, repo.LAYER_OPERPLAN)
    assert sum(months[int(row["id"])]) == 7_000


def test_чужая_дирекция_в_файле_пропускается(planned):
    plan = operplan.plan_fact(make_planfact_sheet(), 2026,
                              only_cfo_ids=[int(repo.find_cfo(HR)["id"])])
    assert plan["matched"] == []
    assert plan["foreign"] == 2


def test_неизвестное_цфо_не_заводится(client):
    """ЦФО, которого нет в справочнике, не создаётся — только называется."""
    before = len(repo.list_cfo())
    plan = operplan.plan_fact(make_planfact_sheet(), 2026)
    assert plan["unknown_cfo"] == [IT]
    assert len(repo.list_cfo()) == before


def test_итого_без_месяцев_это_ошибка_а_не_нули(planned):
    """В нашем формате факт собирается из месяцев; ИТОГО для него не читается."""
    plan = operplan.plan_fact(make_our_budget_sheet(), 2026)
    assert [e["excel_row"] for e in plan["errors"]] == [6]
    assert len(plan["matched"]) == 1
    assert plan["total"] == 800


def test_ошибочная_строка_не_гасит_прежний_факт(planned):
    row = next(r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
               if r["article"] == "4430_Разработка")
    operplan.import_fact(make_our_budget_sheet(), "наш.xlsx", 2026, "Тест")
    # строка 6 отвергнута, её прежний факт не заменён нулями и не выдуман
    assert int(row["id"]) not in repo.row_fact_months(2026, repo.LAYER_OPERPLAN)


# ---------- состав дирекций в файле меняется ----------

def test_блок_бюджета_разводит_одинаковые_ключи(planned):
    """У дирекции с двумя бюджетами блок — единственное, что их различает.

    У ИТ восемь десятков строк с неуникальным ключом в двух блоках: без блока
    такая пара либо уходит в непривязанное, либо факт ложится не в тот бюджет.
    """
    it = int(repo.find_cfo(IT)["id"])
    # две строки с буквально одинаковым ключом в разных блоках
    pair = {}
    for name, plan_year in (("Бюджет обязательных затрат", 100_000),
                            ("Бюджет развития", 777_000)):
        budget_id = repo.ensure_budget(it, 2026, name, layer=repo.LAYER_OPERPLAN)
        pair[name] = repo.create_row(budget_id, {
            "article": "4411_Оборудование", "counterparty": "", "contract": "",
            "detail": "ИТ инфраструктура", "comment": "", "plan_year": plan_year,
        }, months=[0] * 12, author="Тест", row_no=90)

    plan = operplan.plan_fact(make_planfact_sheet(budget="Бюджет развития"), 2026)
    hit = next(i for i in plan["matched"] if i["article"] == "4411_Оборудование")
    assert int(hit["row"]["id"]) == pair["Бюджет развития"], \
        "файл назвал блок развития — в него и должно лечь"
    # вторая строка образца объявлена тем же блоком и честно считается переездом,
    # а наша — нет: её блок совпал
    assert all(m["article"] != "4411_Оборудование" for m in plan["block_moved"])


def test_уехавший_блок_виден_в_предпросмотре(planned):
    """Если строка всё же легла в другой блок, об этом говорят, а не молчат."""
    it = int(repo.find_cfo(IT)["id"])
    rows = [r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
            if int(r["cfo_id"]) == it and r["article"] == "4411_Оборудование"]
    # переносим единственную подходящую строку в другой блок
    other = repo.ensure_budget(it, 2026, "Бюджет развития", layer=repo.LAYER_OPERPLAN)
    db.execute("UPDATE budget_row SET budget_id = ? WHERE id = ?",
               (other, int(rows[0]["id"])))

    plan = operplan.plan_fact(
        make_planfact_sheet(budget="Бюджет обязательных затрат"), 2026)
    moved = plan["block_moved"]
    assert [m["from"] for m in moved] == ["Бюджет обязательных затрат"]
    assert [m["to"] for m in moved] == ["Бюджет развития"]
    assert moved[0]["total"] == 1000


def test_неизвестное_имя_блока_переездом_не_считается(planned):
    """Свой единственный блок дирекции зовут «Бюджет дирекции», у нас он
    «Основной бюджет»: это разные имена одного и того же, а не переезд."""
    plan = operplan.plan_fact(make_planfact_sheet(budget="Бюджет дирекции"), 2026)
    assert plan["matched"], "строки всё равно сошлись"
    assert plan["block_moved"] == []


def test_расход_непривязанной_строки_пристраивается_вторым_проходом(planned):
    """Плановая строка файла не нашлась, а расход под ней — нашёлся.

    У расхода свой контрагент и договор, ключ у него такой же строгий.
    Берётся только однозначное совпадение со свободной строкой.
    """
    it = int(repo.find_cfo(IT)["id"])
    budget_id = repo.ensure_budget(it, 2026, "Бюджет обязательных затрат",
                                   layer=repo.LAYER_OPERPLAN)
    # у нас есть строка под расход «Своя ООО», но нет под его плановую строку
    target = repo.create_row(budget_id, {
        "article": "4777_Неизвестное", "counterparty": "Своя ООО",
        "contract": "Договор №8", "detail": "подписки", "comment": "",
        "plan_year": 123_456,
    }, months=[0] * 12, author="Тест", row_no=91)

    plan = operplan.plan_fact(make_planfact_sheet(with_orphan=True), 2026)
    placed = [p for p in plan["spends"] if int(p["row"]["id"]) == target]
    assert len(placed) == 1, "расход «Своя ООО» должен лечь на свою строку"
    assert sum(placed[0]["months"]) == 100          # март — прогноз
    assert plan["spends_total"] == 100
    # весь факт сироты был этим расходом, поэтому из непривязанного она ушла
    assert all(i["counterparty"] != "Пришлая ООО" for i in plan["unlinked"])


def test_второй_проход_не_хватает_неоднозначное(planned):
    """Две свободные строки с тем же ключом — расход остаётся непривязанным."""
    it = int(repo.find_cfo(IT)["id"])
    for no, name in ((92, "Бюджет обязательных затрат"), (93, "Бюджет развития")):
        budget_id = repo.ensure_budget(it, 2026, name, layer=repo.LAYER_OPERPLAN)
        repo.create_row(budget_id, {
            "article": "4777_Неизвестное", "counterparty": "Своя ООО",
            "contract": "Договор №8", "detail": "подписки", "comment": "",
            "plan_year": 1000,
        }, months=[0] * 12, author="Тест", row_no=no)

    plan = operplan.plan_fact(make_planfact_sheet(with_orphan=True), 2026)
    assert plan["spends"] == [], "неоднозначное привязкой не считаем"


def test_круг_берётся_из_файла_а_не_из_прошлой_загрузки(planned):
    """Дирекция ушла из файла — её факт остаётся, а не обнуляется.

    Файл ИТ сегодня несёт ещё стратегию и аналитику, но завтра они могут
    прийти своими файлами. Заменяется факт только тех дирекций, чьи строки
    в файле есть.
    """
    operplan.import_fact(make_planfact_sheet(with_hr=True), "обе.xlsx", 2026, "Тест")
    hr = int(repo.find_cfo(HR)["id"])
    months = repo.row_fact_months(2026, repo.LAYER_OPERPLAN)
    hr_rows = [r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
               if int(r["cfo_id"]) == hr]
    before = sum(sum(months.get(int(r["id"]), [])) for r in hr_rows)
    assert before == 800                      # март — прогноз, в факт не идёт

    # тот же файл, но дирекции персонала в нём больше нет
    operplan.import_fact(make_planfact_sheet(), "только ИТ.xlsx", 2026, "Тест")
    months = repo.row_fact_months(2026, repo.LAYER_OPERPLAN)
    after = sum(sum(months.get(int(r["id"]), [])) for r in hr_rows)
    assert after == before, "факт дирекции, которой в файле нет, трогать нельзя"


def test_загрузка_запоминает_какие_дирекции_заменила(planned):
    operplan.import_fact(make_planfact_sheet(with_hr=True), "обе.xlsx", 2026, "Тест")
    loads = repo.last_fact_loads(2026)
    assert set(loads) == {int(repo.find_cfo(IT)["id"]), int(repo.find_cfo(HR)["id"])}
    assert all(v["filename"] == "обе.xlsx" for v in loads.values())


def test_предпросмотр_называет_прежнюю_загрузку_каждой_дирекции(planned):
    """Иначе старый общий файл молча затирает свежую отдельную загрузку."""
    operplan.import_fact(make_planfact_sheet(with_hr=True), "персонал на 14.10.xlsx",
                         2026, "Тест",
                         only_cfo_ids=[int(repo.find_cfo(HR)["id"])])
    plan = operplan.plan_fact(make_planfact_sheet(with_hr=True), 2026)
    by_name = {c["name"]: c for c in plan["cfo"]}
    assert by_name[HR]["before"] == 800
    assert by_name[HR]["last_file"] == "персонал на 14.10.xlsx"
    assert by_name[HR]["last_at"]
    # у ИТ факта ещё нет — заменять нечего, и прошлой загрузки тоже нет
    assert by_name[IT]["before"] == 0
    assert by_name[IT]["last_file"] == ""


# ---------- слои не смешиваются ----------

def test_факт_планирования_не_виден_сопоставлению(planned, client):
    """Файл берём с сиротой: иначе непривязанного факта в базе нет вовсе и
    проверка проходит на любом коде, хоть с фильтром слоя, хоть без него."""
    operplan.import_fact(make_planfact_sheet(with_orphan=True), "план-факт.xlsx",
                         2026, "Тест")
    # список упорядочен по дирекции и статье: 4777 идёт раньше 4999
    assert [x["counterparty"] for x in operplan.unlinked_fact(2026)] == [
        "Пришлая ООО", "Омега ООО"]
    assert repo.list_unmatched(2026) == []
    assert repo.list_out_of_budget(2026) == []
    assert repo.fact_months(2026) == {}
    # а в своём слое он есть
    assert repo.list_unmatched(2026, layer=repo.LAYER_OPERPLAN)
    assert repo.list_out_of_budget(2026, layer=repo.LAYER_OPERPLAN)


def test_строка_без_пары_не_меняет_план_а_уходит_в_непривязанное(planned):
    before = len(repo.list_rows(2026, layer=repo.LAYER_OPERPLAN))
    result = operplan.import_fact(make_planfact_sheet(with_orphan=True),
                                  "план-факт.xlsx", 2026, "Тест")
    assert result["unlinked"] == 1
    assert result["unlinked_total"] == 100        # март — прогноз, в факт не идёт
    assert len(repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)) == before
    orphan = next(x for x in operplan.unlinked_fact(2026)
                  if x["counterparty"] == "Пришлая ООО")
    assert orphan["out_of_budget"] is False       # это не «вне бюджета», а промах привязки
    assert operplan.kpi()["outside_total"] == 1_600


# ---------- Excel ----------

def test_выгрузка_факта_несёт_блок_вне_бюджета(planned):
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    ws = openpyxl.load_workbook(io.BytesIO(excel.fact_sheet(2026))).active
    marks = [r for r in range(1, ws.max_row + 1)
             if str(ws.cell(row=r, column=1).value or "").upper() == "ВНЕ БЮДЖЕТА"]
    assert len(marks) == 1
    names = [ws.cell(row=r, column=excel.COL["Контрагент"]).value
             for r in range(marks[0] + 1, ws.max_row + 1)]
    assert "Омега ООО" in names


def test_шаблон_несёт_пустой_блок_вне_бюджета(planned):
    ws = openpyxl.load_workbook(io.BytesIO(excel.budget_template(2026)))["Бюджеты ЦФО"]
    marks = [r for r in range(1, ws.max_row + 1)
             if str(ws.cell(row=r, column=1).value or "").upper() == "ВНЕ БЮДЖЕТА"]
    assert len(marks) == 1
    assert marks[0] < ws.max_row       # под заголовком есть куда вписывать


# ---------- ручки ----------

def test_предпросмотр_совпадает_с_загрузкой(planned, client):
    data = make_planfact_sheet()
    files = {"files": ("план-факт.xlsx", data,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    preview = client.post("/api/operplan/import/preview",
                          files=files, data={"year": 2026, "kind": "fact"})
    assert preview.status_code == 200
    shown = preview.json()

    files = {"files": ("план-факт.xlsx", data,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    done = client.post("/api/operplan/import",
                       files=files, data={"year": 2026, "kind": "fact"})
    assert done.status_code == 200
    written = done.json()
    assert shown["matched"] == written["matched"]
    assert shown["total"] == written["total"]
    assert shown["out_of_budget"] == written["out_of_budget"]


def test_предпросмотр_факта_закрыт_руководителю(planned, client):
    files = {"files": ("план-факт.xlsx", make_planfact_sheet(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    response = client.post("/api/operplan/import/preview", files=files,
                           data={"year": 2026, "kind": "fact"},
                           headers={"X-User": "cfo:1"})
    assert response.status_code == 403


def test_загрузка_больше_не_заводит_строк_через_ручку(planned, client):
    before = len(repo.list_rows(2026, layer=repo.LAYER_OPERPLAN))
    files = {"files": ("план-факт.xlsx", make_planfact_sheet(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    response = client.post("/api/operplan/import", files=files,
                           data={"year": 2026, "kind": "fact"})
    assert response.status_code == 200, response.text
    assert len(repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)) == before


# ---------- «Наличие в бюджете» ----------

def _target_row(article: str = "4430_Разработка") -> dict:
    return next(r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
                if r["article"] == article)


def _row_fact(row_id: int) -> float:
    return sum(repo.row_fact_months(2026, repo.LAYER_OPERPLAN).get(int(row_id), [0.0] * 12))


def test_расход_вне_бюджета_переносится_на_строку_плана(planned):
    """«В бюджете, за счёт строки N»: расход уходит со своего места на строку.

    Свод строки при этом обязан вырасти ровно на сумму расхода — иначе
    плитка, таблица факта и выгрузка показали бы разное.
    """
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    target = _target_row()
    before = _row_fact(target["id"])
    item = operplan.unlinked_fact(2026)[0]
    assert item["counterparty"] == "Омега ООО" and item["total"] == 1_500

    operplan.set_fact_link(2026, int(planned["id"]), item, int(target["id"]), "Тест")

    assert operplan.unlinked_fact(2026) == [], "расход больше не вне бюджета"
    assert _row_fact(target["id"]) == before + 1_500
    assert operplan.kpi()["outside_total"] == 0


def test_решение_переживает_перезаливку_факта(planned):
    """Главное в задаче: факт заменяется целиком, решение — нет."""
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    target = _target_row()
    before = _row_fact(target["id"])
    operplan.set_fact_link(2026, int(planned["id"]), operplan.unlinked_fact(2026)[0],
                           int(target["id"]), "Тест")

    again = operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")

    assert again["relinked"], "загрузка должна сама вернуть расход на выбранную строку"
    assert operplan.unlinked_fact(2026) == []
    assert _row_fact(target["id"]) == before + 1_500


def test_расход_со_строки_уводится_вне_бюджета(planned):
    """Обратное направление: привязанное разрывается и уходит вне бюджета."""
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    row = _target_row("4411_Оборудование")
    before = _row_fact(row["id"])
    spend = next(s for s in operplan.row_spends(2026)[int(row["id"])]
                 if s["counterparty"] == "Астра ООО")

    operplan.set_fact_link(2026, int(planned["id"]), spend, None, "Тест")

    assert _row_fact(row["id"]) == before - spend["total"]
    outside = [x for x in operplan.unlinked_fact(2026) if x["counterparty"] == "Астра ООО"]
    assert len(outside) == 1 and outside[0]["total"] == spend["total"]
    assert outside[0]["out_of_budget"] is True


def test_строку_чужой_дирекции_расходу_не_отдают(planned):
    """Иначе расход одной дирекции испортил бы план-факт другой."""
    operplan.import_fact(make_planfact_sheet(with_hr=True), "план-факт.xlsx", 2026, "Тест")
    hr_row = next(r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
                  if int(r["cfo_id"]) == int(repo.find_cfo(HR)["id"]))
    item = operplan.unlinked_fact(2026)[0]
    with pytest.raises(ValueError, match="другой дирекции"):
        operplan.set_fact_link(2026, int(planned["id"]), item, int(hr_row["id"]), "Тест")


def test_наличие_в_бюджете_меняет_только_финотдел(planned, client):
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    item = operplan.unlinked_fact(2026)[0]
    body = {"year": 2026, "cfo_id": int(planned["id"]), "article": item["article"],
            "counterparty": item["counterparty"], "contract": item["contract"],
            "detail": item["detail"], "row_id": int(_target_row()["id"])}

    denied = client.post("/api/operplan/fact-link", json=body,
                         headers={"X-User": f"cfo:{int(planned['id'])}"})
    assert denied.status_code == 403

    allowed = client.post("/api/operplan/fact-link", json=body)
    assert allowed.status_code == 200, allowed.text
    assert operplan.unlinked_fact(2026) == []


def test_круг_excel_правка_наличия_в_бюджете_возвращается_заливкой(planned, client):
    """Выгрузил факт → вписал «бюджет из строки N» → залил обратно.

    Так дирекции размечают связь у себя в «Комм наш», и так же её можно
    поправить пачкой, не трогая экран. Номер — строка того же листа.
    """
    operplan.import_fact(make_planfact_sheet(), "план-факт.xlsx", 2026, "Тест")
    target = _target_row()
    before = _row_fact(target["id"])
    assert operplan.unlinked_fact(2026)[0]["counterparty"] == "Омега ООО"

    sheet = client.get("/api/export/budget-fact.xlsx?year=2026")
    assert sheet.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(sheet.content))
    ws = wb["Бюджеты ЦФО"]
    link_col = next(c for c in range(1, ws.max_column + 1)
                    if ws.cell(row=3, column=c).value == "Наличие в бюджете")

    # строка выгрузки, на которую отнесём расход, и сам расход вне бюджета
    plan_at = next(r for r in range(4, ws.max_row + 1)
                   if ws.cell(row=r, column=1).value == target["article"])
    spend_at = next(r for r in range(4, ws.max_row + 1)
                    if ws.cell(row=r, column=5).value == "Омега ООО")
    assert ws.cell(row=spend_at, column=link_col).value == "вне бюджета"
    ws.cell(row=spend_at, column=link_col).value = f"бюджет из строки {plan_at}"

    buffer = io.BytesIO()
    wb.save(buffer)
    operplan.import_fact(buffer.getvalue(), "факт правленый.xlsx", 2026, "Тест")

    assert operplan.unlinked_fact(2026) == [], "расход перестал быть вне бюджета"
    assert _row_fact(target["id"]) == before + 1_500


# ---------- пачка файлов и галочки ----------

def _file(name: str, data: bytes) -> tuple:
    return ("files", (name, data,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))


def test_пачка_файлов_грузится_за_раз(planned, client):
    """Файлы приходят по одному на дирекцию, а их дюжина."""
    files = [_file("ИТ.xlsx", make_planfact_sheet()),
             _file("персонал.xlsx", make_planfact_sheet(with_hr=True,
                                                        with_out_of_budget=False))]
    response = client.post("/api/operplan/import", files=files,
                           data={"year": 2026, "kind": "fact"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["files"]) == 2 and body["failed"] == []
    assert [f["filename"] for f in body["files"]] == ["ИТ.xlsx", "персонал.xlsx"]
    months = repo.row_fact_months(2026, repo.LAYER_OPERPLAN)
    assert sum(sum(v) for v in months.values()) == 1140 + 800


def test_битый_файл_не_отменяет_остальные(planned, client):
    """Иначе одна опечатка в имени листа роняет всю пачку из двенадцати."""
    broken = io.BytesIO()
    wb = openpyxl.Workbook()
    wb.active.title = "Не тот лист"
    wb.save(broken)
    files = [_file("хороший.xlsx", make_planfact_sheet()),
             _file("битый.xlsx", broken.getvalue())]
    body = client.post("/api/operplan/import", files=files,
                       data={"year": 2026, "kind": "fact"}).json()
    assert [f["filename"] for f in body["files"]] == ["хороший.xlsx"]
    assert [f["filename"] for f in body["failed"]] == ["битый.xlsx"]
    assert body["total"] == 1140


def test_галочки_режут_круг_дирекций(planned, client):
    """Что не отмечено, то и не тронется — даже если лежит в том же файле."""
    hr = int(repo.find_cfo(HR)["id"])
    files = [_file("обе.xlsx", make_planfact_sheet(with_hr=True))]
    body = client.post("/api/operplan/import", files=files,
                       data={"year": 2026, "kind": "fact", "cfo_ids": [str(hr)]}).json()
    assert body["total"] == 800, "залит только персонал"
    assert body["foreign"] >= 2, "строки ИТ пропущены как чужие"

    it_rows = [r for r in repo.list_rows(2026, layer=repo.LAYER_OPERPLAN)
               if int(r["cfo_id"]) == int(repo.find_cfo(IT)["id"])]
    months = repo.row_fact_months(2026, repo.LAYER_OPERPLAN)
    assert not any(sum(months.get(int(r["id"]), [])) for r in it_rows)


def test_без_галочек_круг_берётся_из_файлов(planned, client):
    files = [_file("обе.xlsx", make_planfact_sheet(with_hr=True))]
    body = client.post("/api/operplan/import", files=files,
                       data={"year": 2026, "kind": "fact"}).json()
    assert body["total"] == 1140 + 800
    assert body["foreign"] == 0


def test_предпросмотр_пачки_сводит_дирекции_без_повторов(planned, client):
    """Одна дирекция может прийти и своим файлом, и внутри чужого."""
    files = [_file("обе.xlsx", make_planfact_sheet(with_hr=True)),
             _file("только ИТ.xlsx", make_planfact_sheet())]
    body = client.post("/api/operplan/import/preview", files=files,
                       data={"year": 2026, "kind": "fact"}).json()
    names = sorted(c["name"] for c in body["cfo"])
    assert names == sorted({IT, HR}), "дирекция названа один раз"
    assert len(body["files"]) == 2


def test_бюджет_пачкой_не_грузится(planned, client):
    """План заменяет строки — грузить его веером файлов слишком опасно."""
    files = [_file("a.xlsx", make_plan_sheet()), _file("b.xlsx", make_plan_sheet())]
    response = client.post("/api/operplan/import", files=files,
                           data={"year": 2027, "kind": "plan"})
    assert response.status_code == 422
    assert "по одному файлу" in response.json()["detail"]


def test_выгрузки_сужаются_теми_же_галочками(planned, client):
    hr = int(repo.find_cfo(HR)["id"])
    for name in ("budget-template", "budget", "budget-fact"):
        response = client.get(f"/api/export/{name}.xlsx?year=2026&cfo={hr}")
        assert response.status_code == 200, name
        ws = openpyxl.load_workbook(io.BytesIO(response.content))["Бюджеты ЦФО"]
        blocks = {ws.cell(row=r, column=2).value
                  for r in range(1, ws.max_row + 1)
                  if ws.cell(row=r, column=1).value == "ИТОГО"}
        assert blocks == {HR}, f"{name}: в листе чужие дирекции — {blocks}"
