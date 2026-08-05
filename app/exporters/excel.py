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