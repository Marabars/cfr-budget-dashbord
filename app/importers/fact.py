"""Импорт факта: выгрузка платежей из 1С или Excel.

Ожидаются строки-платежи с датой и суммой. Названия колонок в выгрузках 1С
различаются, поэтому сопоставление такое же терпимое, как для файлов дирекций.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.importers import xlsx

TOTAL_WORDS = ("итого", "всего", "total")

ALIASES: dict[str, tuple[str, ...]] = {
    "pay_date": ("дата платежа", "дата", "не позднее"),
    "amount": ("сумма",),
    "cfo": ("цфо", "дирекция", "подразделение"),
    "article": ("статья оборотов", "статья"),
    "counterparty": ("контрагент", "получатель"),
    "contract": ("договор",),
    "purpose": ("назначение платежа", "назначение", "комментарий"),
    "claim_number": ("номер", "№ заявки", "заявка"),
    "organization": ("организация", "юл", "плательщик"),
    "status": ("статус",),
}
FIELD_TITLES = {
    "pay_date": "Дата платежа",
    "amount": "Сумма",
    "cfo": "ЦФО",
    "article": "Статья оборотов",
    "counterparty": "Контрагент",
    "contract": "Договор",
    "purpose": "Назначение платежа",
    "claim_number": "№ заявки (1С)",
    "organization": "Организация (не используется)",
    "status": "Статус",
}


def inspect(source: str | Path | bytes, sheet: str | None = None) -> dict:
    rows, sheet_name, sheets = xlsx.load_rows(source, sheet)
    header_idx = xlsx.find_header(rows, ("сумма",))
    if header_idx < 0:
        raise ValueError("Не найдена шапка выгрузки: нет колонки «Сумма»")
    header = rows[header_idx]
    mapping = xlsx.map_columns(header, ALIASES)
    columns = []
    for idx, cell in enumerate(header):
        title = xlsx.text(cell)
        if not title:
            continue
        field = next((f for f, c in mapping.items() if c == idx), None)
        columns.append({
            "index": idx,
            "title": title,
            "field": field,
            "field_title": FIELD_TITLES.get(field or "", ""),
            "samples": xlsx.sample_values(rows, header_idx, idx),
        })
    return {
        "sheet": sheet_name,
        "sheets": sheets,
        "header_row": header_idx + 1,
        "mapping": mapping,
        "columns": columns,
    }


def external_id(filename: str, row: dict) -> str:
    """Стабильный ключ платежа — чтобы повторная загрузка не создавала дубли."""
    parts = [
        row.get("claim_number", ""),
        row.get("pay_date", ""),
        f"{row.get('amount', 0):.2f}",
        row.get("counterparty", ""),
        row.get("contract", ""),
        row.get("purpose", "")[:80],
    ]
    key = "|".join(str(p) for p in parts)
    if not row.get("claim_number"):
        key = f"{filename}|{key}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def parse(source: str | Path | bytes, sheet: str | None = None,
          mapping: dict[str, int] | None = None, filename: str = "") -> dict:
    rows, sheet_name, _ = xlsx.load_rows(source, sheet)
    info = inspect(source, sheet)
    header_idx = info["header_row"] - 1
    cols = dict(info["mapping"])
    if mapping:
        cols.update({k: int(v) for k, v in mapping.items() if v is not None and str(v) != ""})

    def cell(row: list[Any], field: str) -> Any:
        idx = cols.get(field)
        return row[idx] if idx is not None and idx < len(row) else None

    out: list[dict] = []
    skipped = 0
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        amount = xlsx.num(cell(row, "amount"))
        first = xlsx.text(row[0] if row else "")
        if first.lower() in TOTAL_WORDS or xlsx.text(cell(row, "article")).lower() in TOTAL_WORDS:
            skipped += 1
            continue
        if not amount:
            continue
        item = {
            "pay_date": xlsx.iso_date(cell(row, "pay_date")),
            "amount": amount,
            "cfo": xlsx.text(cell(row, "cfo")),
            "article": xlsx.text(cell(row, "article")),
            "counterparty": xlsx.text(cell(row, "counterparty")),
            "contract": xlsx.text(cell(row, "contract")),
            "purpose": xlsx.text(cell(row, "purpose")),
            "claim_number": xlsx.text(cell(row, "claim_number")),
            "excel_row": i + 1,
        }
        item["external_id"] = external_id(filename or sheet_name, item)
        out.append(item)

    return {
        "sheet": sheet_name,
        "header_row": header_idx + 1,
        "mapping": cols,
        "rows": out,
        "skipped_totals": skipped,
    }