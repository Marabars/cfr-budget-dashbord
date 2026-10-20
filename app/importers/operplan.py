"""Импорт листа «Оперплан ЦФО» из файла Ликвидность.

Особенности листа (выверено на файле «Ликвидность 01.07.26.xlsx»):
  * шапка не в первой строке (обычно 5-я), выше — даты месяцев и метки ФАКТ / ПРОГНОЗ;
  * блок открывается строкой со словом ИТОГО в колонке «Статья оборотов»:
    там же ЦФО и название бюджета (в колонке «Договор»);
  * строки без номера — фактические платежи, привязанные к бюджетной строке
    пометкой «Из строки N бюджет» в колонке «Комм наш».
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.calc import MONTHS
from app.importers import xlsx

SHEET_NAME = "Оперплан ЦФО"
TOTAL_MARK = "ИТОГО"
DEFAULT_BUDGET = "Основной бюджет"
PARENT_RE = re.compile(r"строк[аи]\s*№?\s*(\d+)", re.IGNORECASE)

ALIASES = {
    "row_no": ("№", "no", "номер"),
    "article": ("статья оборотов", "статья"),
    "cfo": ("цфо",),
    "counterparty": ("контрагент",),
    "contract": ("договор",),
    "detail": ("детализация",),
    "comment": ("комментарий",),
    "approver_comment": ("комм наш",),
    "plan_year": ("бюджет",),
    "operplan": ("итого опер план",),
    "fact": ("факт",),
}


def _fact_flags(rows: list[list[Any]], header_idx: int, month_cols: dict[int, int]) -> dict[int, str]:
    """Метки ФАКТ / ПРОГНОЗ по месяцам из строк над шапкой."""
    flags: dict[int, str] = {}
    for row in rows[:header_idx]:
        joined = " ".join(xlsx.text(c).upper() for c in row if c is not None)
        if "ФАКТ" not in joined and "ПРОГНОЗ" not in joined:
            continue
        for month, col in month_cols.items():
            if col < len(row):
                value = xlsx.text(row[col]).upper()
                if value in ("ФАКТ", "ПРОГНОЗ"):
                    flags[month] = value
        if flags:
            break
    return flags


def _guess_row_no_column(rows: list[list[Any]], header_idx: int, article_col: int) -> int | None:
    """В рабочем файле номера строк лежат левее «Статья оборотов» и без заголовка.

    Принимаем колонку, только если там действительно встречаются целые числа.
    """
    col = article_col - 1
    if col < 0:
        return None
    numbers = 0
    for row in rows[header_idx + 1:header_idx + 60]:
        if col >= len(row):
            continue
        value = row[col]
        if isinstance(value, (int, float)) and float(value).is_integer() and value > 0:
            numbers += 1
    return col if numbers >= 3 else None


def closed_through(flags: dict[int, str]) -> int:
    """Последний месяц, помеченный как ФАКТ (подряд с начала года)."""
    closed = 0
    for month in range(1, MONTHS + 1):
        if flags.get(month) == "ФАКТ":
            closed = month
        else:
            break
    return closed


def parse(source: str | Path | bytes, sheet: str | None = SHEET_NAME) -> dict:
    """Разбирает лист. Возвращает блоки (ЦФО+бюджет) и строки."""
    rows, sheet_name, sheets = xlsx.load_rows(source, sheet)
    header_idx = xlsx.find_header(rows, ("статья оборотов", "цфо"))
    if header_idx < 0:
        raise ValueError("Не найдена шапка листа: нет колонок «Статья оборотов» и «ЦФО»")

    header = rows[header_idx]
    cols = xlsx.map_columns(header, ALIASES)
    if "row_no" not in cols:
        guess = _guess_row_no_column(rows, header_idx, cols.get("article", 0))
        if guess is not None:
            cols["row_no"] = guess
    month_cols = xlsx.month_columns(header)
    if len(month_cols) != MONTHS:
        raise ValueError(f"Найдено колонок месяцев: {len(month_cols)} из {MONTHS}")
    flags = _fact_flags(rows, header_idx, month_cols)

    def cell(row: list[Any], field: str) -> Any:
        idx = cols.get(field)
        return row[idx] if idx is not None and idx < len(row) else None

    blocks: list[dict] = []
    out_rows: list[dict] = []
    current: dict | None = None

    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        article = xlsx.text(cell(row, "article"))
        if not article:
            continue

        months = xlsx.read_months(row, month_cols)
        cfo = xlsx.text(cell(row, "cfo"))

        if article.upper() == TOTAL_MARK:
            current = {
                "cfo": cfo,
                "budget": xlsx.text(cell(row, "contract")) or DEFAULT_BUDGET,
                "plan_year": xlsx.num(cell(row, "plan_year")),
                "operplan": xlsx.num(cell(row, "operplan")),
                "fact": xlsx.num(cell(row, "fact")),
                "months": months,
                "excel_row": i + 1,
            }
            blocks.append(current)
            continue

        approver = xlsx.text(cell(row, "approver_comment"))
        parent = PARENT_RE.search(approver)
        row_no_raw = xlsx.text(cell(row, "row_no"))
        plan_year = xlsx.num(cell(row, "plan_year"))

        # строка без номера с пометкой «Из строки N» — фактический платёж по лимиту N
        is_child = not row_no_raw
        if is_child and not any(months) and not plan_year:
            continue    # техническая пустая строка

        out_rows.append({
            "cfo": cfo or (current or {}).get("cfo", ""),
            "budget": (current or {}).get("budget", DEFAULT_BUDGET),
            "row_no": int(xlsx.num(row_no_raw)) if row_no_raw else None,
            "article": article,
            "counterparty": xlsx.text(cell(row, "counterparty")),
            "contract": xlsx.text(cell(row, "contract")),
            "detail": xlsx.text(cell(row, "detail")),
            "comment": xlsx.text(cell(row, "comment")),
            "approver_comment": approver,
            "plan_year": plan_year,
            "operplan": xlsx.num(cell(row, "operplan")),
            "fact": xlsx.num(cell(row, "fact")),
            "months": months,
            "parent_no": int(parent.group(1)) if parent else None,
            "is_child": is_child,
            "excel_row": i + 1,
        })

    return {
        "sheet": sheet_name,
        "sheets": sheets,
        "header_row": header_idx + 1,
        "columns": cols,
        "month_columns": month_cols,
        "fact_flags": flags,
        "closed_through": closed_through(flags),
        "blocks": blocks,
        "rows": out_rows,
    }