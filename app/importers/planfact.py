"""Разбор файла дирекции «План-факт <дирекция> 2026.xlsx».

Файл живёт в рабочем процессе дирекций (стрим «План-факт по дирекциям») и
приходит к нам как источник факта. Два листа: «Оперплан ЦФО» с группировкой
строк и «ФАКТ» с выгрузкой платежей из 1С.

Главный признак разбора — **уровень группировки** строки, тот самый «плюсик»
слева в Excel:

  0 — служебное: «ВСЕГО», «ИТОГО» блока, заголовок «ВНЕ БЮДЖЕТА»;
  1 — плановая строка: лимит года лежит в колонке «БЮДЖЕТ»;
  2 — фактический расход по контрагенту; относится к ближайшей строке
      уровня 1 выше.

Почему не по тексту. В колонке «Комм наш» дирекции пишут «бюджет из строки 6»,
и там, где написали, это почти всегда совпадает с группировкой. Но пишут не
всегда — треть расходов приходит вовсе без пометки, — и в ту же колонку
попадает свободный текст вроде «Разница за счет непредвиденных». Поэтому
уровень группировки основной признак, «Комм наш» подтверждающий, и
расхождения между ними возвращаются вызывающему.

Месяцы листа — смесь факта и прогноза: над шапкой стоят метки ФАКТ / ПРОГНОЗ
по месяцам. Фактом считаются только помеченные ФАКТ; без меток — все 12.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.calc import MONTHS
from app.importers import xlsx

SHEET_PLAN = "Оперплан ЦФО"
SHEET_FACT = "ФАКТ"
TOTAL_MARK = "ИТОГО"
GRAND_TOTAL_WORDS = ("ВСЕГО", "TOTAL")
OUT_OF_BUDGET_MARK = "ВНЕ БЮДЖЕТА"
DEFAULT_BUDGET = "Основной бюджет"
# Каноничную пометку «бюджет из строки N» пишет генератор файлов дирекций, и
# номер в ней — из колонки «№» того же файла. Рядом в той же колонке живёт
# унаследованный из Оперплана свободный текст финотдела («из строки 33»,
# «за счет строки 47», «Разницу списываем со строчки 122»): его номера — из
# сквозной нумерации Оперплана по всем ЦФО, она считает и строки ИТОГО, и
# указателем на строку нашего файла быть не может. Замерено на 12 файлах:
# каноничная пометка расходится с группировкой в 1% случаев, свободный
# текст — в 29%. Поэтому подтверждающим признаком считаем только каноничную.
PARENT_RE = re.compile(r"^\s*бюджет\s+из\s+строки\s+(\d+)\s*$", re.IGNORECASE)

LEVEL_SERVICE = 0
LEVEL_PLAN = 1
LEVEL_SPEND = 2

ALIASES = {
    "row_no": ("№", "no", "номер"),
    "article": ("статья оборотов", "статья"),
    "cfo": ("цфо",),
    "classifier": ("классификатор",),
    "counterparty": ("контрагент",),
    "contract": ("договор",),
    "detail": ("детализация",),
    "comment": ("комментарий",),
    "approver_comment": ("комм наш",),
    "plan_year": ("бюджет",),
    "fact_year": ("факт",),
}

# лист «ФАКТ»: выгрузка платежей 1С
FACT_ALIASES = {
    "pay_date": ("период", "дата платежа", "дата"),
    "article": ("статья оборотов", "статья"),
    "cfo": ("цфо",),
    "counterparty": ("контрагент",),
    "contract": ("договор контрагента", "договор"),
    "purpose": ("назначение платежа", "назначение"),
    "organization": ("организация",),
    "outcome": ("расход в рублях", "расход"),
    "income": ("приход в рублях", "приход"),
}


def _fact_flags(rows: list[list[Any]], header_idx: int,
                month_cols: dict[int, int]) -> dict[int, str]:
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


def fact_only(months: list[float], flags: dict[int, str]) -> list[float]:
    """Оставляет суммы помеченных ФАКТ месяцев, прочие гасит.

    Без меток файл считается фактическим целиком: так приходят выгрузки,
    где прогноза нет вовсе.
    """
    if not flags:
        return list(months)
    return [months[m - 1] if flags.get(m) == "ФАКТ" else 0.0 for m in range(1, MONTHS + 1)]


def _levels_from_numbering(rows: list[list[Any]], header_idx: int,
                           article_col: int, row_no_col: int | None) -> list[int]:
    """Запасные уровни, когда группировки в файле нет.

    Служебные строки узнаются по статье, плановые — по заполненному №,
    расходы — по его отсутствию. Так разбирались файлы до того, как дирекции
    стали группировать строки, и пара таких файлов в папке ещё лежит.
    """
    levels = [0] * len(rows)
    for i in range(header_idx + 1, len(rows)):
        article = xlsx.text(rows[i][article_col] if article_col < len(rows[i]) else None)
        if not article:
            continue
        upper = article.upper()
        if upper == TOTAL_MARK or upper in GRAND_TOTAL_WORDS or OUT_OF_BUDGET_MARK in upper:
            levels[i] = LEVEL_SERVICE
            continue
        has_no = row_no_col is not None and xlsx.text(
            rows[i][row_no_col] if row_no_col < len(rows[i]) else None)
        levels[i] = LEVEL_PLAN if has_no else LEVEL_SPEND
    return levels


def _guess_row_no_column(rows: list[list[Any]], header_idx: int, article_col: int) -> int | None:
    """Номера строк бывают левее «Статьи оборотов» и без заголовка."""
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


def parse(source: str | Path | bytes) -> dict:
    """Разбирает лист «Оперплан ЦФО» по уровням группировки."""
    rows, sheet_name, sheets, levels = xlsx.load_rows_levels(source, SHEET_PLAN)
    header_idx = xlsx.find_header(rows, ("статья оборотов", "цфо"))
    if header_idx < 0:
        raise ValueError("Не найдена шапка листа: нет колонок «Статья оборотов» и «ЦФО»")

    header = rows[header_idx]
    cols = xlsx.map_columns(header, ALIASES)
    if "article" not in cols:
        raise ValueError("В шапке листа нет колонки «Статья оборотов»")
    if "row_no" not in cols:
        guess = _guess_row_no_column(rows, header_idx, cols["article"])
        if guess is not None:
            cols["row_no"] = guess

    month_cols = xlsx.month_columns(header)
    if len(month_cols) != MONTHS:
        raise ValueError(f"Найдено колонок месяцев: {len(month_cols)} из {MONTHS}")

    flags = _fact_flags(rows, header_idx, month_cols)
    grouped = any(lv for lv in levels[header_idx + 1:])
    if not grouped:
        levels = _levels_from_numbering(rows, header_idx, cols["article"], cols.get("row_no"))

    def cell(row: list[Any], field: str) -> Any:
        idx = cols.get(field)
        return row[idx] if idx is not None and idx < len(row) else None

    blocks: list[dict] = []
    plans: list[dict] = []
    out_of_budget: list[dict] = []
    conflicts: list[dict] = []
    skipped_service: list[dict] = []

    block: dict | None = None
    plan: dict | None = None
    in_out_of_budget = False

    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        article = xlsx.text(cell(row, "article"))
        if not article:
            continue
        upper = article.upper()
        level = levels[i] if i < len(levels) else 0
        months = xlsx.read_months(row, month_cols)
        cfo = xlsx.text(cell(row, "cfo"))
        excel_row = i + 1

        if upper in GRAND_TOTAL_WORDS:
            # «ВСЕГО» — итог по всему листу. Разбирался как расход и удваивал файл.
            skipped_service.append({"excel_row": excel_row, "article": article})
            continue

        if upper == TOTAL_MARK:
            block = {
                "cfo": cfo,
                "budget": xlsx.text(cell(row, "contract")) or DEFAULT_BUDGET,
                "plan_year": xlsx.num(cell(row, "plan_year")),
                "fact_year": xlsx.num(cell(row, "fact_year")),
                "months": months,
                "excel_row": excel_row,
                "rows": 0,
            }
            blocks.append(block)
            plan = None
            in_out_of_budget = False
            continue

        if OUT_OF_BUDGET_MARK in upper:
            # Заголовок блока «вне бюджета»: дальше идёт факт, которому дирекция
            # не нашла строки бюджета. Заканчивается следующим ИТОГО.
            in_out_of_budget = True
            plan = None
            continue

        item = {
            "cfo": cfo or (block or {}).get("cfo", ""),
            "budget": (block or {}).get("budget", DEFAULT_BUDGET),
            "row_no": int(xlsx.num(cell(row, "row_no"))) if xlsx.text(cell(row, "row_no")) else None,
            "article": article,
            "classifier": xlsx.text(cell(row, "classifier")),
            "counterparty": xlsx.text(cell(row, "counterparty")),
            "contract": xlsx.text(cell(row, "contract")),
            "detail": xlsx.text(cell(row, "detail")),
            "comment": xlsx.text(cell(row, "comment")),
            "approver_comment": xlsx.text(cell(row, "approver_comment")),
            "plan_year": xlsx.num(cell(row, "plan_year")),
            "fact_year": xlsx.num(cell(row, "fact_year")),
            "months": months,
            "fact_months": fact_only(months, flags),
            "level": level,
            "excel_row": excel_row,
        }

        if in_out_of_budget:
            out_of_budget.append(item)
            continue

        if level >= LEVEL_SPEND and plan is not None:
            hint = PARENT_RE.match(item["approver_comment"])
            item["parent_hint"] = int(hint.group(1)) if hint else None
            if item["parent_hint"] and plan["row_no"] and item["parent_hint"] != plan["row_no"]:
                conflicts.append({"excel_row": excel_row, "hint": item["parent_hint"],
                                  "group": plan["row_no"]})
            plan["parts"].append(item)
            continue

        # уровень 1 (или 2 без плановой строки выше — считаем самостоятельным)
        item["parts"] = []
        plans.append(item)
        plan = item
        if block:
            block["rows"] += 1

    # Блок без единой строки — след разметки: в файлах дирекций строка «ИТОГО»
    # идёт дважды, сначала без названия бюджета, потом с ним, и все строки
    # лежат под второй. Пустой блок удваивал контрольную сумму файла.
    blocks = [b for b in blocks if b["rows"]]

    return {
        "sheet": sheet_name,
        "sheets": sheets,
        "header_row": header_idx + 1,
        "columns": cols,
        "month_columns": month_cols,
        "fact_flags": flags,
        "grouped": grouped,
        "blocks": blocks,
        "plans": plans,
        "out_of_budget": out_of_budget,
        "conflicts": conflicts,
        "skipped_service": skipped_service,
    }


def plan_fact_months(plan: dict) -> list[float]:
    """Факт плановой строки: сумма расходов под ней, а при их отсутствии — свой.

    Родительская строка в файле — это сумма своих детей, поэтому складывать
    её с ними нельзя: получится двойной счёт. Там, где детей нет (строка сама
    по себе расход с контрагентом), факт лежит прямо на ней.
    """
    parts = plan.get("parts") or []
    if not parts:
        return list(plan["fact_months"])
    out = [0.0] * MONTHS
    for part in parts:
        for m in range(MONTHS):
            out[m] += part["fact_months"][m]
    return out


def parse_payments(source: str | Path | bytes) -> dict:
    """Разбирает лист «ФАКТ» — выгрузку платежей 1С.

    Лист необязательный: часть файлов приходит без него. Расход в выгрузке
    записан отрицательным числом, возвращаем положительные суммы.
    """
    rows, sheet_name, sheets = xlsx.load_rows(source, SHEET_FACT)
    if sheet_name != SHEET_FACT:
        return {"sheet": "", "sheets": sheets, "payments": [], "total": 0.0}

    header_idx = xlsx.find_header(rows, ("контрагент",))
    if header_idx < 0:
        return {"sheet": sheet_name, "sheets": sheets, "payments": [], "total": 0.0}
    cols = xlsx.map_columns(rows[header_idx], FACT_ALIASES)

    def cell(row: list[Any], field: str) -> Any:
        idx = cols.get(field)
        return row[idx] if idx is not None and idx < len(row) else None

    payments: list[dict] = []
    for i in range(header_idx + 1, len(rows)):
        row = rows[i]
        # Расход в выгрузке записан отрицательным, приход — положительным, и
        # «Сумма УПР» равна их сумме (проверено построчно на 659 платежах
        # сервиса). Возврат депозита поэтому обязан уменьшать расход, а не
        # увеличивать его: приход вычитался вместо сложения, и один возврат
        # на 9,2 млн давал расхождение в 18,4 млн — вдвое больше себя.
        amount = -(xlsx.num(cell(row, "outcome")) + xlsx.num(cell(row, "income")))
        if not amount:
            continue
        payments.append({
            "pay_date": xlsx.iso_date(cell(row, "pay_date")),
            "article": xlsx.text(cell(row, "article")),
            "cfo": xlsx.text(cell(row, "cfo")),
            "counterparty": xlsx.text(cell(row, "counterparty")),
            "contract": xlsx.text(cell(row, "contract")),
            "purpose": xlsx.text(cell(row, "purpose")),
            "amount": amount,
            "excel_row": i + 1,
        })
    return {"sheet": sheet_name, "sheets": sheets, "payments": payments,
            "total": sum(p["amount"] for p in payments)}


def looks_like_planfact(sheets: list[str]) -> bool:
    """Файл дирекции узнаётся по имени листа, а не по шапке.

    Наша выгрузка кладёт данные на лист «Бюджеты ЦФО», файл дирекции — на
    «Оперплан ЦФО». Шапки у них похожи настолько, что по ней не развести.
    """
    return any(xlsx.text(s).lower() == SHEET_PLAN.lower() for s in sheets)
