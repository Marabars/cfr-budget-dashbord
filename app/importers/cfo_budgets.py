"""Импорт листа «Бюджеты ЦФО» из файла Ликвидность — исходник вкладки «Оперплан».

Раскладка листа (выверено на «Ликвидность 21.09.26.xlsx»):
  * шапка на 3-й строке: Статья оборотов | ЦФО | Контрагент | Договор |
    Детализация | Комментарий | ИТОГО | Январь…Декабрь;
  * выше шапки — служебные строки с датами начала и конца месяцев;
  * блок ЦФО открывается строкой, где в колонке «Статья оборотов» стоит ИТОГО;
    там же название ЦФО, а в колонке «Договор» — название бюджета
    (заполнено только у ИТ, у остальных бюджет один и называется «Основной бюджет»);
  * строка блока ИТОГО — контрольная сумма, в строки бюджета не попадает;
  * держатель бюджета — ЦФО блока, а не колонка ЦФО в самой строке: внутри блока
    встречаются строки с другой подписью («Эпсилон» в блоке правовой дирекции,
    «Двенадцатая дирекция» в накладных расходах), и контрольная сумма блока их включает.
    Отличающаяся подпись сохраняется в «Комм наш», чтобы не потерять её при переносе.

Наша выгрузка добавляет к этой раскладке колонку «Классификатор» (МРГ или МРК)
сразу за «ЦФО». В исходном файле её нет — тогда строка читается как МРГ,
поэтому старые файлы заливаются как раньше.

Лист «ЦФО Статьи» того же файла разбирается отдельно: это справочник
«какие статьи закреплены за дирекцией» для выпадающего списка при добавлении.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app import repo
from app.calc import MONTHS
from app.importers import xlsx

SHEET_NAME = "Бюджеты ЦФО"
ARTICLES_SHEET = "ЦФО Статьи"
TOTAL_MARK = "ИТОГО"
GRAND_TOTAL_WORDS = ("ВСЕГО", "TOTAL")      ***REMOVED*** итог по всему листу, не блок
OUT_OF_BUDGET_MARK = "ВНЕ БЮДЖЕТА"          ***REMOVED*** заголовок блока факта без строки бюджета
DEFAULT_BUDGET = "Основной бюджет"

ALIASES = {
    "article": ("статья оборотов", "статья"),
    "cfo": ("цфо",),
    "classifier": ("классификатор", "мрг/мрк", "юрлицо"),
    "counterparty": ("контрагент",),
    "contract": ("договор",),
    "detail": ("детализация",),
    "comment": ("комментарий",),
    "plan_year": ("итого", "бюджет"),
}


def parse(source: str | Path | bytes, sheet: str | None = SHEET_NAME) -> dict:
    """Разбирает лист «Бюджеты ЦФО». Возвращает блоки-контрольные суммы и строки."""
    rows, sheet_name, sheets = xlsx.load_rows(source, sheet)
    header_idx = xlsx.find_header(rows, ("статья оборотов", "цфо"))
    if header_idx < 0:
        raise ValueError("Не найдена шапка листа: нет колонок «Статья оборотов» и «ЦФО»")

    header = rows[header_idx]
    cols = xlsx.map_columns(header, ALIASES)
    for field in ("article", "cfo"):
        if field not in cols:
            raise ValueError(f"В шапке листа нет колонки «{field}»")
    month_cols = xlsx.month_columns(header)
    if len(month_cols) != MONTHS:
        raise ValueError(f"Найдено колонок месяцев: {len(month_cols)} из {MONTHS}")

    def cell(row: list[Any], field: str) -> Any:
        idx = cols.get(field)
        return row[idx] if idx is not None and idx < len(row) else None

    blocks: list[dict] = []
    out_rows: list[dict] = []
    skipped_service: list[dict] = []
    current: dict | None = None

    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        article = xlsx.text(cell(row, "article"))
        if not article:
            continue
        months = xlsx.read_months(row, month_cols)
        cfo = xlsx.text(cell(row, "cfo"))
        upper = article.upper()

        if upper in GRAND_TOTAL_WORDS or OUT_OF_BUDGET_MARK in upper:
            ***REMOVED*** Итог по всему листу и блок «вне бюджета» приходят в файлах
            ***REMOVED*** дирекций. Как строка расхода «ВСЕГО» удваивала весь файл,
            ***REMOVED*** а ЦФО у неё пустой — заводилась дирекция «Не указано».
            skipped_service.append({"excel_row": i + 1, "article": article})
            continue

        if upper == TOTAL_MARK:
            current = {
                "cfo": cfo,
                "budget": xlsx.text(cell(row, "contract")) or DEFAULT_BUDGET,
                "plan_year": xlsx.num(cell(row, "plan_year")),
                "months": months,
                "excel_row": i + 1,
                "rows": 0,
            }
            blocks.append(current)
            continue

        plan_year = xlsx.num(cell(row, "plan_year"))
        ***REMOVED*** Нулевую строку со статьёй не отбрасываем: в бюджете это законная
        ***REMOVED*** строка — расход заведён, сумму ещё не проставили. Строки вовсе без
        ***REMOVED*** статьи отсеяны выше, так что «пустая техническая» сюда не доходит.
        ***REMOVED*** Факту нули не нужны — их отсекает import_fact у себя.

        holder = (current or {}).get("cfo", "") or cfo
        out_rows.append({
            "cfo": holder,
            "row_cfo": cfo,
            "budget": (current or {}).get("budget", DEFAULT_BUDGET),
            "article": article,
            ***REMOVED*** колонки может не быть вовсе: старые выгрузки и исходный файл
            ***REMOVED*** ликвидности её не знают — тогда строка считается МРГ
            "classifier": repo.classifier_or_default(cell(row, "classifier")),
            "counterparty": xlsx.text(cell(row, "counterparty")),
            "contract": xlsx.text(cell(row, "contract")),
            "detail": xlsx.text(cell(row, "detail")),
            "comment": xlsx.text(cell(row, "comment")),
            "approver_comment": f"ЦФО в файле: {cfo}" if cfo and cfo != holder else "",
            "plan_year": plan_year,
            "months": months,
            "excel_row": i + 1,
        })
        if current:
            current["rows"] += 1

    ***REMOVED*** Блок без единой строки — след разметки: в файлах дирекций «ИТОГО» идёт
    ***REMOVED*** дважды, сначала без названия бюджета, потом с ним. Пустой блок удваивал
    ***REMOVED*** контрольную сумму файла и заводил лишний бюджет.
    blocks = [b for b in blocks if b["rows"]]

    return {
        "sheet": sheet_name,
        "sheets": sheets,
        "header_row": header_idx + 1,
        "columns": cols,
        "month_columns": month_cols,
        "blocks": blocks,
        "rows": out_rows,
        "skipped_service": skipped_service,
    }


def check_totals(parsed: dict, tolerance: float = 1.0) -> list[dict]:
    """Сверяет контрольную строку ИТОГО каждого блока с суммой его строк."""
    sums: dict[tuple[str, str], float] = {}
    for row in parsed["rows"]:
        key = (row["cfo"], row["budget"])
        sums[key] = sums.get(key, 0.0) + row["plan_year"]
    out = []
    for block in parsed["blocks"]:
        key = (block["cfo"], block["budget"])
        actual = sums.get(key, 0.0)
        if abs(actual - block["plan_year"]) > tolerance:
            out.append({
                "cfo": block["cfo"], "budget": block["budget"],
                "declared": block["plan_year"], "actual": actual,
                "diff": actual - block["plan_year"], "excel_row": block["excel_row"],
            })
    return out


def parse_articles(source: str | Path | bytes, sheet: str | None = ARTICLES_SHEET) -> dict:
    """Лист «ЦФО Статьи»: соответствие дирекция → статья управленческого учёта.

    Шапка на листе смещена и вправо, и вниз, поэтому ищем её по словам,
    а не по фиксированным координатам.
    """
    rows, sheet_name, sheets = xlsx.load_rows(source, sheet)
    header_idx = xlsx.find_header(rows, ("цфо", "стать"))
    if header_idx < 0:
        raise ValueError("Не найдена шапка листа «ЦФО Статьи»")

    cols = xlsx.map_columns(rows[header_idx], {
        "cfo": ("цфо -держатель бюджета", "цфо-держатель бюджета", "цфо"),
        "article": ("статьи управленческого учета", "статьи", "статья"),
    })
    if "cfo" not in cols or "article" not in cols:
        raise ValueError("В шапке листа «ЦФО Статьи» нет колонок ЦФО и статей")

    pairs: list[dict] = []
    cfo = ""
    for row in rows[header_idx + 1:]:
        name = xlsx.text(row[cols["cfo"]]) if cols["cfo"] < len(row) else ""
        article = xlsx.text(row[cols["article"]]) if cols["article"] < len(row) else ""
        if name:
            cfo = name                      ***REMOVED*** название ЦФО тянется вниз по блоку
        if cfo and article:
            pairs.append({"cfo": cfo, "article": article})

    return {"sheet": sheet_name, "sheets": sheets, "header_row": header_idx + 1,
            "pairs": pairs}
