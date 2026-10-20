"""Импорт плана из файлов дирекций.

Файлы приходят в разной раскладке: шапка может быть в любой из первых строк,
колонка «Договор» съезжает, встречаются персональные колонки с ФИО в заголовке —
это комментарий согласующего. Поэтому парсер терпимый: он предлагает
сопоставление колонок, а пользователь при необходимости правит его в интерфейсе.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.calc import MONTHS
from app.importers import xlsx

TOTAL_WORDS = ("итого", "всего", "total")
DEFAULT_BUDGET = "Основной бюджет"

# поля системы -> допустимые названия колонок в файле
ALIASES: dict[str, tuple[str, ...]] = {
    "article": ("статья оборотов", "статья", "статья затрат"),
    "cfo": ("цфо", "дирекция", "подразделение"),
    "counterparty": ("контрагент", "поставщик", "исполнитель"),
    "contract": ("договор", "№ договора"),
    "detail": ("детализация", "ссылка", "обоснование"),
    "comment": ("комментарий", "назначение", "описание"),
    "plan_year": ("итого", "итого за год", "сумма за год", "год"),
}
FIELD_TITLES = {
    "article": "Статья оборотов",
    "cfo": "ЦФО",
    "counterparty": "Контрагент",
    "contract": "Договор",
    "detail": "Детализация",
    "comment": "Комментарий",
    "approver_comment": "Комментарий согласующего",
    "plan_year": "Годовая сумма (проверочная)",
}
# колонка с ФИО в заголовке — комментарий согласующего
FIO_RE = re.compile(r"^[А-ЯЁ][а-яё]+\s+[А-ЯЁ]{1,2}\.?[А-ЯЁ]?\.?$")


def _guess_approver_column(header: list[Any], used: set[int]) -> int | None:
    for idx, cell in enumerate(header):
        if idx in used:
            continue
        value = xlsx.text(cell)
        if value and FIO_RE.match(value):
            return idx
    return None


def inspect(source: str | Path | bytes, sheet: str | None = None) -> dict:
    """Разбирает файл и возвращает предложенное сопоставление колонок с примерами.

    Результат отдаётся на экран «Сопоставление колонок файла» перед импортом.
    """
    rows, sheet_name, sheets = xlsx.load_rows(source, sheet)
    header_idx = xlsx.find_header(rows, ("статья",))
    if header_idx < 0:
        header_idx = xlsx.find_header(rows, ("цфо",))
    if header_idx < 0:
        raise ValueError("Не удалось найти шапку: нет колонки «Статья оборотов» или «ЦФО»")

    header = rows[header_idx]
    mapping = xlsx.map_columns(header, ALIASES)
    approver = _guess_approver_column(header, set(mapping.values()))
    if approver is not None:
        mapping["approver_comment"] = approver
    month_cols = xlsx.month_columns(header)

    columns = []
    for idx, cell in enumerate(header):
        title = xlsx.text(cell)
        month_no = next((m for m, c in month_cols.items() if c == idx), None)
        field = next((f for f, c in mapping.items() if c == idx), None)
        if not title and field is None and month_no is None:
            continue
        columns.append({
            "index": idx,
            "letter": _column_letter(idx),
            "title": title,
            "field": field or (f"month:{month_no}" if month_no else None),
            "field_title": FIELD_TITLES.get(field or "", f"{month_no} месяц" if month_no else ""),
            "samples": xlsx.sample_values(rows, header_idx, idx),
            "guessed": field == "approver_comment",
        })

    return {
        "sheet": sheet_name,
        "sheets": sheets,
        "header_row": header_idx + 1,
        "mapping": mapping,
        "month_columns": month_cols,
        "columns": columns,
        "months_found": len(month_cols),
        "needs_budget_name": True,   # названия бюджета в файлах дирекций нет
    }


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def parse(source: str | Path | bytes, sheet: str | None = None,
          mapping: dict[str, int] | None = None,
          month_columns: dict[int, int] | None = None,
          budget_name: str = DEFAULT_BUDGET,
          cfo_name: str = "") -> dict:
    """Читает строки плана. mapping/month_columns можно переопределить из интерфейса."""
    rows, sheet_name, _ = xlsx.load_rows(source, sheet)
    info = inspect(source, sheet)
    header_idx = info["header_row"] - 1
    cols = dict(info["mapping"])
    if mapping:
        cols.update({k: int(v) for k, v in mapping.items() if v is not None and str(v) != ""})
    mcols = {int(k): int(v) for k, v in (month_columns or info["month_columns"]).items()}

    def cell(row: list[Any], field: str) -> Any:
        idx = cols.get(field)
        return row[idx] if idx is not None and idx < len(row) else None

    out: list[dict] = []
    skipped_totals = 0
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        article = xlsx.text(cell(row, "article"))
        months = xlsx.read_months(row, mcols)
        year_sum = xlsx.num(cell(row, "plan_year"))

        if article.lower() in TOTAL_WORDS:
            skipped_totals += 1
            continue
        if not article and not any(months):
            continue

        plan_year = year_sum or sum(months)
        out.append({
            "cfo": xlsx.text(cell(row, "cfo")) or cfo_name,
            "budget": budget_name,
            "article": article,
            "counterparty": xlsx.text(cell(row, "counterparty")),
            "contract": xlsx.text(cell(row, "contract")),
            "detail": xlsx.text(cell(row, "detail")),
            "comment": xlsx.text(cell(row, "comment")),
            "approver_comment": xlsx.text(cell(row, "approver_comment")),
            "plan_year": plan_year,
            "months": months,
            "months_sum": sum(months),
            "year_sum_in_file": year_sum,
            "excel_row": i + 1,
        })

    return {
        "sheet": sheet_name,
        "header_row": header_idx + 1,
        "mapping": cols,
        "month_columns": mcols,
        "rows": out,
        "skipped_totals": skipped_totals,
    }


def check_totals(parsed: dict, tolerance: float = 1.0) -> list[dict]:
    """Строки, где годовая сумма в файле не совпадает с суммой месяцев."""
    bad = []
    for row in parsed["rows"]:
        declared = row["year_sum_in_file"]
        if declared and abs(declared - row["months_sum"]) > tolerance:
            bad.append({
                "excel_row": row["excel_row"],
                "article": row["article"],
                "declared": declared,
                "months_sum": row["months_sum"],
                "diff": declared - row["months_sum"],
            })
    return bad