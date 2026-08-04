"""Тесты импортёров Excel. Файлы-фикстуры создаются на месте, чтобы тесты
не зависели от сетевого диска с рабочими данными."""
from __future__ import annotations

from datetime import date, datetime

import openpyxl
import pytest

from app.importers import directorate, fact, operplan

MONTH_NAMES = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
               "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]


***REMOVED*** ---------- фикстуры ----------

def make_operplan(path, closed=4):
    """Лист «Оперплан ЦФО» в раскладке реального файла: шапка в 5-й строке."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Оперплан ЦФО"

    ***REMOVED*** строка 1 — начала месяцев, строка 2 — концы, строка 3 — метки ФАКТ/ПРОГНОЗ
    for m in range(12):
        ws.cell(row=1, column=16 + m, value=datetime(2026, m + 1, 1))
        ws.cell(row=3, column=16 + m, value="ФАКТ" if m + 1 <= closed else "ПРОГНОЗ")

    header = ["№", "Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
              "Комментарий", "Комм наш", "Бюджет - опер план", "БЮДЖЕТ", "Оперплан фикс",
              "", "Итого опер план", "Факт", "Остаток бюжета"] + MONTH_NAMES
    for c, value in enumerate(header, start=1):
        ws.cell(row=5, column=c, value=value)

    ***REMOVED*** блок 1: ИТОГО по дирекции + две бюджетные строки + дочерний факт
    ws.append([])  ***REMOVED*** заполнение до 6-й строки произойдёт вручную ниже
    rows = [
        ***REMOVED*** ИТОГО открывает блок; название бюджета — в колонке «Договор»
        (6,  {1: "ИТОГО", 2: "Третья дирекция", 4: "Бюджет обязательных затрат",
              9: 13_000_000, 12: 9_000_000, 13: 6_000_000,
              "months": [3_000_000, 3_000_000, 0, 0, 3_000_000] + [0] * 7}),
        (7,  {0: 1, 1: "4420_ПО", 2: "Третья дирекция", 5: "Лицензии",
              9: 10_000_000, 12: 6_000_000, 13: 3_000_000,
              "months": [3_000_000, 0, 0, 0, 3_000_000] + [0] * 7}),
        (8,  {1: "4420_ПО", 2: "Третья дирекция", 3: "Астра ООО", 4: "Договор №1",
              7: "Из строки 1 бюджет", "months": [1_000_000] + [0] * 11}),
        (9,  {0: 2, 1: "4430_Разработка", 2: "Третья дирекция", 5: "Портал",
              9: 3_000_000, 12: 3_000_000, 13: 3_000_000,
              "months": [0, 3_000_000] + [0] * 10}),
        ***REMOVED*** блок 2: другая дирекция, название бюджета пустое
        (10, {1: "ИТОГО", 2: "Финансовый отдел", 9: 500_000, 12: 500_000, 13: 200_000,
              "months": [200_000, 0, 300_000] + [0] * 9}),
        (11, {0: 1, 1: "4106_Аудит", 2: "Финансовый отдел", 3: "Аудитор ООО",
              9: 500_000, 12: 500_000, 13: 200_000,
              "months": [200_000, 0, 300_000] + [0] * 9}),
    ]
    for row_no, spec in rows:
        for col, value in spec.items():
            if col == "months":
                for m, amount in enumerate(value):
                    if amount:
                        ws.cell(row=row_no, column=16 + m, value=amount)
            else:
                ws.cell(row=row_no, column=int(col) + 1, value=value)
    wb.save(path)
    return path


def make_directorate(path):
    """Файл дирекции: шапка в 3-й строке, персональная колонка с ФИО, строка ИТОГО."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Лист_1"
    header = ["Статья оборотов", "ЦФО", "Контрагент", "Договор", "Комментарий",
              "Орлов ВП", "ИТОГО"] + MONTH_NAMES
    for c, value in enumerate(header, start=1):
        ws.cell(row=3, column=c, value=value)
    ws.append([])
    data = [
        ("4106_Аудит", "Финансовый отдел", "Аудитор ООО", "Договор №15248", "Обязательный аудит",
         "актуализировать", 500_000, [0, 0, 200_000, 0, 0, 0, 0, 0, 300_000, 0, 0, 0]),
        ("4107_Юристы", "Финансовый отдел", "Юрфирма ООО", "", "Сопровождение",
         "", 120_000, [10_000] * 12),
        ("ИТОГО", "", "", "", "", "", 620_000, [0] * 12),
    ]
    for i, (article, cfo, cp, contract, comment, approver, total, months) in enumerate(data, start=4):
        values = [article, cfo, cp, contract, comment, approver, total] + months
        for c, value in enumerate(values, start=1):
            ws.cell(row=i, column=c, value=value)
    wb.save(path)
    return path


def make_fact(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    header = ["Дата", "Номер", "Организация", "Статья оборотов", "Контрагент",
              "Договор", "Сумма", "Назначение платежа", "ЦФО"]
    ws.append(header)
    ws.append([date(2026, 8, 1), "ЗП-001", "Холдинг", "4420_ПО", "Астра ООО",
               "Договор №1", 1_250_000, "Лицензии Астра", "Третья дирекция"])
    ws.append(["02.08.2026", "ЗП-002", "Холдинг", "4430_Разработка", "Подрядчик ООО",
               "", 300_000, "Доработка портала", "Третья дирекция"])
    ws.append(["Итого", "", "", "", "", "", 1_550_000, "", ""])
    wb.save(path)
    return path


***REMOVED*** ---------- Оперплан ЦФО ----------

def test_оперплан_находит_шапку_не_в_первой_строке(tmp_path):
    parsed = operplan.parse(make_operplan(tmp_path / "op.xlsx"))
    assert parsed["header_row"] == 5
    assert parsed["columns"]["article"] == 1
    assert parsed["columns"]["plan_year"] == 9
    assert len(parsed["month_columns"]) == 12


def test_оперплан_определяет_границу_закрытого_периода(tmp_path):
    parsed = operplan.parse(make_operplan(tmp_path / "op.xlsx", closed=4))
    assert parsed["closed_through"] == 4
    assert parsed["fact_flags"][5] == "ПРОГНОЗ"


def test_оперплан_разбивает_на_блоки_цфо_и_бюджет(tmp_path):
    parsed = operplan.parse(make_operplan(tmp_path / "op.xlsx"))
    blocks = parsed["blocks"]
    assert len(blocks) == 2
    assert blocks[0]["cfo"] == "Третья дирекция"
    assert blocks[0]["budget"] == "Бюджет обязательных затрат"
    assert blocks[0]["plan_year"] == 13_000_000
    ***REMOVED*** у второго блока названия бюджета в файле нет
    assert blocks[1]["budget"] == "Основной бюджет"


def test_оперплан_строки_наследуют_бюджет_своего_блока(tmp_path):
    parsed = operplan.parse(make_operplan(tmp_path / "op.xlsx"))
    articles = {r["article"]: r for r in parsed["rows"]}
    assert articles["4420_ПО"]["budget"] == "Бюджет обязательных затрат"
    assert articles["4106_Аудит"]["budget"] == "Основной бюджет"
    assert "ИТОГО" not in articles


def test_оперплан_дочерняя_строка_ссылается_на_бюджетную(tmp_path):
    parsed = operplan.parse(make_operplan(tmp_path / "op.xlsx"))
    child = [r for r in parsed["rows"] if r["is_child"]]
    assert len(child) == 1
    assert child[0]["parent_no"] == 1
    assert child[0]["counterparty"] == "Астра ООО"
    assert child[0]["months"][0] == 1_000_000


def test_оперплан_ругается_на_файл_без_нужных_колонок(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.append(["Что-то", "Другое"])
    path = tmp_path / "bad.xlsx"
    wb.save(path)
    with pytest.raises(ValueError, match="шапка"):
        operplan.parse(path)


***REMOVED*** ---------- файлы дирекций ----------

def test_файл_дирекции_шапка_в_третьей_строке_и_колонка_с_фио(tmp_path):
    info = directorate.inspect(make_directorate(tmp_path / "d.xlsx"))
    assert info["header_row"] == 3
    assert info["mapping"]["article"] == 0
    assert info["mapping"]["approver_comment"] == 5   ***REMOVED*** колонка с ФИО согласующего
    assert info["months_found"] == 12
    assert info["needs_budget_name"] is True


def test_файл_дирекции_итоговая_строка_пропускается(tmp_path):
    parsed = directorate.parse(make_directorate(tmp_path / "d.xlsx"))
    assert parsed["skipped_totals"] == 1
    assert [r["article"] for r in parsed["rows"]] == ["4106_Аудит", "4107_Юристы"]


def test_файл_дирекции_читает_план_по_месяцам(tmp_path):
    parsed = directorate.parse(make_directorate(tmp_path / "d.xlsx"))
    audit = parsed["rows"][0]
    assert audit["months"][2] == 200_000
    assert audit["months"][8] == 300_000
    assert audit["plan_year"] == 500_000


def test_файл_дирекции_ловит_расхождение_года_и_месяцев(tmp_path):
    path = make_directorate(tmp_path / "d.xlsx")
    wb = openpyxl.load_workbook(path)
    wb.active.cell(row=4, column=7, value=999_999)   ***REMOVED*** ИТОГО не сходится с месяцами
    wb.save(path)

    bad = directorate.check_totals(directorate.parse(path))
    assert len(bad) == 1
    assert bad[0]["declared"] == 999_999
    assert bad[0]["months_sum"] == 500_000


def test_сопоставление_колонок_можно_переопределить(tmp_path):
    path = make_directorate(tmp_path / "d.xlsx")
    parsed = directorate.parse(path, mapping={"comment": 5})
    assert parsed["rows"][0]["comment"] == "актуализировать"


***REMOVED*** ---------- факт ----------

def test_факт_читает_даты_в_обоих_форматах(tmp_path):
    parsed = fact.parse(make_fact(tmp_path / "f.xlsx"), filename="f.xlsx")
    assert parsed["rows"][0]["pay_date"] == "2026-08-01"
    assert parsed["rows"][1]["pay_date"] == "2026-08-02"


def test_факт_пропускает_итоги_и_читает_поля(tmp_path):
    parsed = fact.parse(make_fact(tmp_path / "f.xlsx"), filename="f.xlsx")
    assert parsed["skipped_totals"] == 1
    assert len(parsed["rows"]) == 2
    row = parsed["rows"][0]
    assert row["amount"] == 1_250_000
    assert row["claim_number"] == "ЗП-001"
    assert row["counterparty"] == "Астра ООО"


def test_ключ_платежа_стабилен_и_различает_платежи(tmp_path):
    path = make_fact(tmp_path / "f.xlsx")
    first = fact.parse(path, filename="f.xlsx")["rows"]
    second = fact.parse(path, filename="f.xlsx")["rows"]
    assert first[0]["external_id"] == second[0]["external_id"]     ***REMOVED*** повторная загрузка не создаст дубль
    assert first[0]["external_id"] != first[1]["external_id"]