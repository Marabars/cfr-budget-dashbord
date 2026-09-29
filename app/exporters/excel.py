"""Экспорт в Excel. Суммы отдаются точными, с копейками."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app import calc, service

MONEY = "***REMOVED*** ***REMOVED******REMOVED***0.00"
HEAD_FILL = PatternFill("solid", fgColor="EDEBF7")
TOTAL_FILL = PatternFill("solid", fgColor="F6F4FC")
THIN = Side(style="thin", color="C6C0DE")
BORDER = Border(bottom=THIN)


def _style_header(ws, row: int, last_col: int) -> None:
    for col in range(1, last_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, size=10)
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = BORDER
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _autosize(ws, widths: dict[int, int]) -> None:
    for col, width in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width


def _to_bytes(wb: Workbook) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def budget_sheet(year: int, cfo_ids=None) -> bytes:
    """Лист «Бюджеты ЦФО» слоя планирования — тот же вид, что у исходного файла.

    Раскладка один в один повторяет то, что читает importers.cfo_budgets:
    блок ЦФО открывается строкой «ИТОГО» с контрольной суммой, под ней строки.
    Поэтому выгруженный файл можно поправить в Excel и залить обратно.
    """
    from app import operplan as operplan_service

    view = operplan_service.view(year, cfo_ids)
    wb = Workbook()
    ws = wb.active
    ws.title = cfo_budgets_sheet_name()

    header = ["Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
              "Комментарий", "ИТОГО"] + calc.MONTH_NAMES
    ws.cell(row=1, column=1, value=f"Бюджеты ЦФО, {view['year']} год")
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    for col, title in enumerate(header, start=1):
        ws.cell(row=3, column=col, value=title)
    _style_header(ws, 3, len(header))

    def money(r: int, c: int, value: float, bold: bool = False) -> None:
        cell = ws.cell(row=r, column=c, value=round(float(value or 0), 2))
        cell.number_format = MONEY
        if bold:
            cell.font = Font(bold=True)

    idx = 4
    for block in view["blocks"]:
        ws.cell(row=idx, column=1, value="ИТОГО").font = Font(bold=True)
        ws.cell(row=idx, column=2, value=block["cfo_name"]).font = Font(bold=True)
        ws.cell(row=idx, column=4, value=block["budget_name"])
        money(idx, 7, block["plan_year"], bold=True)
        for m, amount in enumerate(block["months"]):
            money(idx, 8 + m, amount, bold=True)
        for col in range(1, len(header) + 1):
            ws.cell(row=idx, column=col).fill = TOTAL_FILL
        idx += 1

        for row in block["rows"]:
            ws.cell(row=idx, column=1, value=row["article"])
            ws.cell(row=idx, column=2, value=block["cfo_name"])
            ws.cell(row=idx, column=3, value=row["counterparty"])
            ws.cell(row=idx, column=4, value=row["contract"])
            ws.cell(row=idx, column=5, value=row["detail"])
            ws.cell(row=idx, column=6, value=row["comment"])
            money(idx, 7, row["plan_year"])
            for m, amount in enumerate(row["months"]):
                money(idx, 8 + m, amount)
            idx += 1

    _autosize(ws, {1: 38, 2: 30, 3: 28, 4: 26, 5: 34, 6: 30, 7: 16})
    for m in range(calc.MONTHS):
        ws.column_dimensions[get_column_letter(8 + m)].width = 14
    return _to_bytes(wb)


def cfo_budgets_sheet_name() -> str:
    from app.importers import cfo_budgets
    return cfo_budgets.SHEET_NAME


TEMPLATE_ROWS = 12          ***REMOVED*** пустых строк на блок — хватает на один ЦФО без вставок
HINT_FILL = PatternFill("solid", fgColor="FFF6E8")


def budget_template(year: int, cfo_ids=None) -> bytes:
    """Пустой лист «Бюджеты ЦФО» под заполнение руками.

    Раскладка та же, что у `budget_sheet`, поэтому заполненный шаблон принимает
    та же загрузка. Блок каждого ЦФО открыт строкой «ИТОГО» — держателем бюджета
    считается блок, а не колонка «ЦФО» в самой строке, так что строки достаточно
    вписывать под нужным заголовком.

    Пустые строки при загрузке пропускаются: лишние заготовки можно не удалять.
    """
    from app import operplan as operplan_service, repo

    allowed = None if cfo_ids is None else {int(i) for i in cfo_ids}
    cfo_list = [c for c in repo.list_cfo()
                if allowed is None or int(c["id"]) in allowed]
    budgets_by_cfo: dict[int, list[str]] = {}
    for block in operplan_service.view(year, cfo_ids)["blocks"]:
        budgets_by_cfo.setdefault(int(block["cfo_id"]), []).append(block["budget_name"])

    wb = Workbook()
    ws = wb.active
    ws.title = cfo_budgets_sheet_name()

    header = ["Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
              "Комментарий", "ИТОГО"] + calc.MONTH_NAMES
    ws.cell(row=1, column=1, value=f"Бюджеты ЦФО, {year} год — шаблон для заполнения")
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    hint = ws.cell(row=2, column=1, value=(
        "Как заполнять — на листе «Как заполнять». Формулы не пишите: "
        "загрузка читает значения."))
    hint.font = Font(size=10, italic=True)
    hint.fill = HINT_FILL
    for col, title in enumerate(header, start=1):
        ws.cell(row=3, column=col, value=title)
    _style_header(ws, 3, len(header))

    idx = 4
    for cfo in cfo_list:
        names = budgets_by_cfo.get(int(cfo["id"])) or ["Основной бюджет"]
        for budget_name in names:
            ws.cell(row=idx, column=1, value="ИТОГО").font = Font(bold=True)
            ws.cell(row=idx, column=2, value=cfo["name"]).font = Font(bold=True)
            ws.cell(row=idx, column=4, value=budget_name)
            for col in range(1, len(header) + 1):
                ws.cell(row=idx, column=col).fill = TOTAL_FILL
            idx += 1
            for _ in range(TEMPLATE_ROWS):
                cell = ws.cell(row=idx, column=7)
                cell.number_format = MONEY
                for m in range(calc.MONTHS):
                    ws.cell(row=idx, column=8 + m).number_format = MONEY
                idx += 1

    _autosize(ws, {1: 38, 2: 30, 3: 28, 4: 26, 5: 34, 6: 30, 7: 16})
    for m in range(calc.MONTHS):
        ws.column_dimensions[get_column_letter(8 + m)].width = 14

    _template_hints(wb, year)
    _template_refs(wb, year, cfo_ids)
    return _to_bytes(wb)


HOW_TO = [
    "Лист «Бюджеты ЦФО» — то, что читает загрузка. Не переименовывайте его "
    "и не меняйте порядок колонок.",
    "Расходы вписывайте строками под серым заголовком своей дирекции: "
    "держателем бюджета считается заголовок блока, а не подпись в самой строке.",
    "Обязательна первая колонка — название расходной статьи. Пишите его так же, "
    "как на листе «Справочник»: название с опечаткой заведёт в плане отдельную строку.",
    "Суммы — в колонку ИТОГО и по месяцам. Если заполнены только месяцы, "
    "ИТОГО будет посчитано как их сумма.",
    "Формулы загрузка не видит — вписывайте числа. Excel-файл со формулами "
    "сначала сохраните как значения.",
    "Серые строки «ИТОГО» и пустые заготовки при загрузке пропускаются — "
    "лишние строки удалять не нужно, а недостающие можно вставить.",
    "Загрузка бюджета заменяет план года по вашим дирекциям целиком: "
    "в файле должно быть всё, что нужно в плане, а не только новое.",
]


def _template_hints(wb: Workbook, year: int) -> None:
    """Инструкция отдельным листом.

    На самом листе «Бюджеты ЦФО» её держать нельзя: разборщик ищет шапку как
    первую строку, где встречаются слова «статья оборотов» и «ЦФО», и длинная
    подсказка с этими словами перебивала бы настоящую шапку.
    """
    ws = wb.create_sheet("Как заполнять")
    title = ws.cell(row=1, column=1, value=f"Как заполнить бюджет на {year} год")
    title.font = Font(bold=True, size=12)
    for i, line in enumerate(HOW_TO):
        cell = ws.cell(row=3 + i * 2, column=1, value=f"{i + 1}. {line}")
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.fill = HINT_FILL
    _autosize(ws, {1: 118})


def _template_refs(wb: Workbook, year: int, cfo_ids=None) -> None:
    """Лист-справочник: какие статьи и контрагенты уже встречались у ЦФО.

    Нужен, чтобы в шаблоне писали существующие названия, а не новые варианты
    написания того же: статья с опечаткой заведёт в плане отдельную строку.
    """
    from app import operplan as operplan_service, repo

    refs = operplan_service.references(year, None if cfo_ids is None else list(cfo_ids))
    names = {int(c["id"]): c["name"] for c in repo.list_cfo()}
    ws = wb.create_sheet("Справочник")
    for col, title in enumerate(["ЦФО", "Статьи оборотов", "Контрагенты"], start=1):
        ws.cell(row=1, column=col, value=title)
    _style_header(ws, 1, 3)

    idx = 2
    for cfo_id, bucket in sorted(refs["by_cfo"].items(),
                                 key=lambda kv: names.get(int(kv[0]), "")):
        articles = bucket["articles"] or [""]
        counterparties = bucket["counterparties"] or [""]
        ws.cell(row=idx, column=1, value=names.get(int(cfo_id), "")).font = Font(bold=True)
        for offset in range(max(len(articles), len(counterparties))):
            if offset < len(articles):
                ws.cell(row=idx + offset, column=2, value=articles[offset])
            if offset < len(counterparties):
                ws.cell(row=idx + offset, column=3, value=counterparties[offset])
        idx += max(len(articles), len(counterparties)) + 1
    _autosize(ws, {1: 30, 2: 44, 3: 34})


def operplan(year: int | None = None, cfo_ids=None) -> bytes:
    """Лист «Оперплан ЦФО» в раскладке исходного файла — для вставки в «Ликвидность».

    Порядок колонок и служебные строки повторяют источник: строка с метками
    ФАКТ / ПРОГНОЗ, шапка, затем блоки «ИТОГО» с их строками.
    """
    view = service.year_view(year, cfo_ids)
    cfg = view["settings"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Оперплан ЦФО"

    first_month_col = 16
    for m in range(calc.MONTHS):
        ws.cell(row=1, column=first_month_col + m,
                value=f"{cfg['year']}-{m + 1:02d}-01")
        ws.cell(row=3, column=first_month_col + m,
                value="ФАКТ" if m + 1 <= cfg["closed_through"] else "ПРОГНОЗ").font = Font(bold=True)

    header = ["№", "Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
              "Комментарий", "Комм наш", "Бюджет - опер план", "БЮДЖЕТ", "Оперплан фикс",
              "", "Итого опер план", "Факт", "Остаток бюджета"] + calc.MONTH_NAMES
    for col, title in enumerate(header, start=1):
        ws.cell(row=5, column=col, value=title)
    _style_header(ws, 5, len(header))

    row_idx = 6
    for block in view["blocks"]:
        budget = view["budgets"][block["id"]]
        t = block["totals"]
        ws.cell(row=row_idx, column=2, value="ИТОГО").font = Font(bold=True)
        ws.cell(row=row_idx, column=3, value=block["cfo_name"]).font = Font(bold=True)
        ws.cell(row=row_idx, column=5, value=block["name"])
        for col, value in ((9, t["free_limit"]), (10, t["plan_year"]),
                           (13, t["operplan"]), (14, t["fact"]), (15, t["cash_remain"])):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.number_format = MONEY
            cell.font = Font(bold=True)
        for m in range(calc.MONTHS):
            total_m = sum(r["fact_months"][m] + r["claim_months"][m] for r in budget["rows"])
            cell = ws.cell(row=row_idx, column=first_month_col + m, value=total_m)
            cell.number_format = MONEY
            cell.font = Font(bold=True)
        for col in range(1, len(header) + 1):
            ws.cell(row=row_idx, column=col).fill = TOTAL_FILL
        row_idx += 1

        for r in budget["rows"]:
            values = [
                r["row_no"], r["article"], block["cfo_name"], r["counterparty"], r["contract"],
                r["detail"], r["comment"], r["approver_comment"],
                r["free_limit"], r["plan_year"], r["plan_year"], None,
                r["operplan"], r["fact"], r["cash_remain"],
            ]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col, value=value)
                if col >= 9 and isinstance(value, (int, float)):
                    cell.number_format = MONEY
            for m in range(calc.MONTHS):
                cell = ws.cell(row=row_idx, column=first_month_col + m,
                               value=r["fact_months"][m] + r["claim_months"][m])
                cell.number_format = MONEY
            row_idx += 1

    _autosize(ws, {1: 6, 2: 38, 3: 34, 4: 26, 5: 26, 6: 26, 7: 26, 8: 20,
                   9: 18, 10: 18, 11: 16, 12: 3, 13: 18, 14: 16, 15: 18})
    for m in range(calc.MONTHS):
        ws.column_dimensions[get_column_letter(first_month_col + m)].width = 15
    return _to_bytes(wb)


def summary(year: int | None = None, cfo_ids=None) -> bytes:
    """Сводка по ЦФО: план / факт / заявки / остаток / статус."""
    view = service.year_view(year, cfo_ids)
    cfg = view["settings"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Сводка по ЦФО"

    ws.cell(row=1, column=1, value=f"Бюджеты ЦФО {cfg['year']} · на {cfg['as_of']} · "
                                   f"факт закрыт по {calc.MONTH_NAMES[cfg['closed_through'] - 1] if cfg['closed_through'] else '—'}")
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)

    header = ["ЦФО", "Бюджет", "Бюджет год", "Факт", "Заявки", "Итого опер план",
              "Остаток бюджета", "Свободный лимит", "Освоение, %", "Статус", "Вне бюджета"]
    for col, title in enumerate(header, start=1):
        ws.cell(row=3, column=col, value=title)
    _style_header(ws, 3, len(header))

    row_idx = 4
    for b in view["blocks"]:
        t = b["totals"]
        values = [b["cfo_name"], b["name"], t["plan_year"], t["fact"], t["claims"],
                  t["operplan"], t["cash_remain"], t["free_limit"], t["pct"],
                  b["status_text"], b["out_of_budget"]]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            if col in (3, 4, 5, 6, 7, 8, 11):
                cell.number_format = MONEY
            if col == 9:
                cell.number_format = "0.0%"
        row_idx += 1

    totals_row = row_idx
    ws.cell(row=totals_row, column=1, value="ИТОГО").font = Font(bold=True)
    for col in (3, 4, 5, 6, 7, 8, 11):
        letter = get_column_letter(col)
        cell = ws.cell(row=totals_row, column=col,
                       value=f"=SUM({letter}4:{letter}{row_idx - 1})")
        cell.number_format = MONEY
        cell.font = Font(bold=True)

    _autosize(ws, {1: 46, 2: 28, 3: 18, 4: 18, 5: 16, 6: 18, 7: 18, 8: 18, 9: 12, 10: 22, 11: 16})
    return _to_bytes(wb)


def cfo_card(cfo_id: int, year: int | None = None) -> bytes:
    """Карточка одного ЦФО: строки с месяцами."""
    card = service.cfo_card(cfo_id, year)
    wb = Workbook()
    ws = wb.active
    ws.title = (card["cfo"]["name"] if card["cfo"] else "ЦФО")[:31]

    header = ["№", "Статья оборотов", "Контрагент", "Договор", "Детализация",
              "Бюджет", "Итого опер план", "Факт", "Остаток бюджета",
              "Свободный лимит"] + calc.MONTH_NAMES
    for col, title in enumerate(header, start=1):
        ws.cell(row=1, column=col, value=title)
    _style_header(ws, 1, len(header))

    row_idx = 2
    for budget in card["budgets"]:
        ws.cell(row=row_idx, column=1, value=budget["name"]).font = Font(bold=True)
        for col in range(1, len(header) + 1):
            ws.cell(row=row_idx, column=col).fill = TOTAL_FILL
        row_idx += 1
        for r in budget["rows"]:
            values = [r["row_no"], r["article"], r["counterparty"], r["contract"], r["detail"],
                      r["plan_year"], r["operplan"], r["fact"], r["cash_remain"], r["free_limit"]]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col, value=value)
                if col >= 6:
                    cell.number_format = MONEY
            for m in range(calc.MONTHS):
                cell = ws.cell(row=row_idx, column=11 + m,
                               value=r["fact_months"][m] + r["claim_months"][m])
                cell.number_format = MONEY
            row_idx += 1

    _autosize(ws, {1: 6, 2: 38, 3: 26, 4: 26, 5: 30, 6: 16, 7: 18, 8: 16, 9: 18, 10: 18})
    return _to_bytes(wb)


def out_of_budget(year: int | None = None) -> bytes:
    """Реестр расходов вне бюджета."""
    from app import repo

    cfg = service.settings()
    items = repo.list_out_of_budget(year or cfg["year"])
    wb = Workbook()
    ws = wb.active
    ws.title = "Вне бюджета"
    header = ["Дата", "ЦФО", "Контрагент", "Договор", "Назначение", "Сумма", "Кто пометил"]
    for col, title in enumerate(header, start=1):
        ws.cell(row=1, column=col, value=title)
    _style_header(ws, 1, len(header))
    for i, f in enumerate(items, start=2):
        values = [f["pay_date"], f["cfo_name"] or "", f["counterparty"], f["contract"],
                  f["purpose"], float(f["amount"]), f["matched_by"]]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=i, column=col, value=value)
            if col == 6:
                cell.number_format = MONEY
    _autosize(ws, {1: 12, 2: 40, 3: 30, 4: 26, 5: 40, 6: 16, 7: 24})
    return _to_bytes(wb)