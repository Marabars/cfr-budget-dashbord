"""Вкладка «Оперплан»: планирование бюджета на следующий год.

Слой планирования (layer = 'operplan') живёт отдельно от слоя исполнения:
дашборд, сводка и карточка ЦФО его не видят и не меняются. В слой попадает
лист «Бюджеты ЦФО» файла ликвидности как база прошлого года, поверх которой
набирается план следующего.

Два ключа сравнения строк разных лет:
    MATCH — статья + контрагент + договор       «была в прошлом году, нет в новом»
    FULL  — то же плюс детализация               защита от дублей при копировании года
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Sequence

from app import calc, db, repo
from app.importers import cfo_budgets

LAYER = repo.LAYER_OPERPLAN
DEFAULT_PLAN_YEAR = 2027
DEFAULT_BASE_YEAR = 2026
IT_MARKER = "ИТ-направлению"    ***REMOVED*** у ИТ «Детализация» берётся из бюджета


***REMOVED*** ---------- параметры вкладки ----------

def plan_year() -> int:
    return int(db.get_setting("operplan_year", str(DEFAULT_PLAN_YEAR)))


def base_year() -> int:
    return int(db.get_setting("operplan_base_year", str(DEFAULT_BASE_YEAR)))


def is_locked(year: int) -> bool:
    return db.get_setting(f"operplan_lock:{year}", "0") == "1"


def set_lock(year: int, locked: bool, author: str) -> dict:
    db.set_setting(f"operplan_lock:{year}", "1" if locked else "0")
    db.log(author, "Блокировка внесения изменений", f"Оперплан {year}",
           "внесение изменений заблокировано" if locked else "внесение изменений разрешено")
    return {"year": year, "locked": locked}


def renumber(year: int, author: str, cfo_ids: Iterable[int] | None = None) -> dict:
    """Закрепляет нумерацию строк — вызывается кнопкой «Сохранить».

    Пока правку не закончили, в колонке № показывается позиция строки: таблица
    отсортирована по статьям, а номера тянутся из исходного файла и идут
    вперемешку. По «Сохранить» номера проставляются подряд в том же порядке,
    в каком строки стоят в таблице, — дальше номер строки уже что-то значит.
    """
    changed = repo.renumber_rows(year, LAYER,
                                 None if cfo_ids is None else list(cfo_ids))
    if changed:
        db.log(author, "Нумерация строк плана", f"Оперплан {year}",
               f"проставлено номеров: {changed}")
    return {"year": year, "renumbered": changed}


def can_edit(user, year: int, cfo_id: int | None = None) -> bool:
    """Финотдел правит всегда, руководитель ЦФО — только свой ЦФО и только без замка."""
    if user.is_fin:
        return True
    if is_locked(year):
        return False
    return user.can_edit_cfo(cfo_id) if cfo_id is not None else True


def require_edit(user, year: int, cfo_id: int | None = None) -> None:
    if user.is_fin:
        return
    if is_locked(year):
        raise ValueError(f"Внесение изменений в {year} год заблокировано финансовым отделом")
    if cfo_id is not None and not user.can_edit_cfo(cfo_id):
        raise ValueError("Нет доступа к этому ЦФО")


def require_plan_year(year: int) -> None:
    """Правится только год, который планируют.

    Прошлый год лежит на вкладке базой для сравнения: его суммы пришли из
    закрытого бюджета, и правка по ячейке сделала бы базу не базой. Ограничение
    общее, включая финотдел — «случайно поправить прошлый год» не должно быть
    возможным ни у кого. Перезалить прошлый год целиком загрузкой Excel или
    залить в него факт по-прежнему можно: это осознанные действия.
    """
    if int(year) != plan_year():
        raise ValueError(f"{year} год — база для сравнения, правке не подлежит")


***REMOVED*** ---------- ключи сравнения строк ----------

def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _detail_text(row: dict) -> str:
    """Что показывать в колонке «Детализация».

    У ИТ это детализация из бюджета, у остальных дирекций — наш комментарий
    (колонка «Комментарий» листа). Управляется полем cfo.detail_source.
    """
    detail = (row.get("detail") or "").strip()
    comment = (row.get("comment") or "").strip()
    if (row.get("detail_source") or "comment") == "detail":
        return detail or comment      ***REMOVED*** у ИТ детализация местами пустая — тогда комментарий
    return comment


def match_key(row: dict) -> tuple:
    """Ключ «та же строка расхода»: статья + контрагент + договор."""
    return (_norm(row.get("article", "")), _norm(row.get("counterparty", "")),
            _norm(row.get("contract", "")))


def full_key(row: dict) -> tuple:
    """Ключ для защиты от дублей при копировании года: плюс детализация.

    Берём ту детализацию, которая видна в таблице: у ИТ это колонка бюджета,
    у остальных — комментарий. Иначе строки одной статьи без контрагента
    и договора (а таких в файле много) схлопнулись бы в одну.
    """
    return match_key(row) + (_norm(_detail_text(row)),)


***REMOVED*** ---------- представление ----------

def _empty_months() -> list[float]:
    return [0.0] * calc.MONTHS


def _sum_months(items: Iterable[Sequence[float]]) -> list[float]:
    out = _empty_months()
    for months in items:
        for m in range(calc.MONTHS):
            out[m] += months[m]
    return out


def _row_view(row: dict, months: list[float], base: dict | None) -> dict:
    return {
        "id": int(row["id"]),
        "row_no": row.get("row_no"),
        "budget_id": int(row["budget_id"]),
        "budget_name": row.get("budget_name", ""),
        "cfo_id": int(row["cfo_id"]),
        "cfo_name": row.get("cfo_name", ""),
        "article": row["article"],
        "classifier": row.get("classifier") or repo.CLASSIFIER_DEFAULT,
        "counterparty": row["counterparty"],
        "contract": row["contract"],
        "detail": row["detail"],
        "comment": row["comment"],
        "approver_comment": row["approver_comment"],
        "detail_source": row.get("detail_source") or "comment",
        "detail_text": _detail_text(row),
        "plan_year": float(row["plan_year"]),
        "months": months,
        "source": row.get("source", ""),
        "base_plan_year": float(base["plan_year"]) if base else None,
    }


def _year_rows(year: int, cfo_ids: Iterable[int] | None = None) -> list[dict]:
    rows = repo.list_rows(year, layer=LAYER)
    if cfo_ids is not None:
        allowed = set(int(i) for i in cfo_ids)
        rows = [r for r in rows if int(r["cfo_id"]) in allowed]
    return rows


def fact_months_by_row(year: int, cfo_ids: Iterable[int] | None = None,
                       row_ids: Iterable[int] | None = None) -> dict[int, list[float]]:
    """Факт года на строки слоя планирования: `{row_id: [12 сумм]}`.

    Факт, загруженный Excel'ем прямо в слой планирования, точнее привязки
    платежей 1С к строкам: берём его, а на пустом слое падаем на привязку.
    Источник один и у плитки план-факт, и у выгрузки факта — иначе выгрузка
    отдавала бы нули там, где плитка показывает сумму.

    `row_ids` — готовый круг строк года, когда вызывающий их уже прочитал.
    """
    ids = ({int(i) for i in row_ids} if row_ids is not None
           else {int(r["id"]) for r in _year_rows(year, cfo_ids)})
    layer = {k: v for k, v in repo.row_fact_months(year, LAYER).items() if k in ids}
    if any(sum(v) for v in layer.values()):
        return layer
    return {k: v for k, v in repo.fact_months(year).items() if k in ids}


def kpi(cfo_ids: Iterable[int] | None = None) -> dict:
    """Три показателя вкладки: бюджет нового года, бюджет базового и его план-факт."""
    py, by = plan_year(), base_year()
    plan_rows = _year_rows(py, cfo_ids)
    base_rows = _year_rows(by, cfo_ids)

    plan_total = sum(float(r["plan_year"]) for r in plan_rows)
    base_total = sum(float(r["plan_year"]) for r in base_rows)

    base_ids = {int(r["id"]) for r in base_rows}
    base_fact = sum(sum(v) for v in fact_months_by_row(by, row_ids=base_ids).values())

    return {
        "plan_year": py,
        "base_year": by,
        "plan_total": plan_total,
        "base_total": base_total,
        ***REMOVED*** доля прошлогоднего бюджета от нового: 100% = план не изменился
        "base_ratio": (base_total / plan_total) if plan_total else 0.0,
        ***REMOVED*** набранный план в долях прошлогоднего бюджета: растёт по мере наполнения,
        ***REMOVED*** 100% = план повторил прошлый год, больше 100% = бюджет вырос
        "plan_ratio": (plan_total / base_total) if base_total else 0.0,
        "base_fact": base_fact,
        "base_pct": (base_fact / base_total) if base_total else 0.0,
        "fact_loaded": base_fact > 0,
        "plan_rows": len(plan_rows),
        "base_rows": len(base_rows),
    }


def view(year: int | None = None, cfo_ids: Iterable[int] | None = None) -> dict:
    """Таблица вкладки: блоки ЦФО со строками, итог по году и KPI."""
    py, by = plan_year(), base_year()
    year = int(year or py)

    rows = _year_rows(year, cfo_ids)
    months_all = repo.plan_months(year, layer=LAYER)

    ***REMOVED*** строки базового года — чтобы показать рядом прошлогоднюю сумму
    base_by_key: dict[tuple, dict] = {}
    if year != by:
        for r in _year_rows(by, cfo_ids):
            base_by_key.setdefault(full_key(r), dict(r))

    allowed = None if cfo_ids is None else set(int(i) for i in cfo_ids)
    blocks: dict[int, dict] = {}
    for b in repo.list_budgets(year, layer=LAYER):
        if allowed is not None and int(b["cfo_id"]) not in allowed:
            continue
        blocks[int(b["id"])] = {
            "budget_id": int(b["id"]),
            "budget_name": b["name"],
            "cfo_id": int(b["cfo_id"]),
            "cfo_name": b["cfo_name"],
            "detail_source": b.get("detail_source") or "comment",
            "rows": [],
        }

    for row in rows:
        block = blocks.get(int(row["budget_id"]))
        if block is None:
            continue
        rid = int(row["id"])
        block["rows"].append(
            _row_view(row, months_all.get(rid, _empty_months()), base_by_key.get(full_key(row)))
        )

    out_blocks = []
    for b in blocks.values():
        out_blocks.append({
            **{k: v for k, v in b.items() if k != "rows"},
            "rows": b["rows"],
            "rows_count": len(b["rows"]),
            "plan_year": sum(r["plan_year"] for r in b["rows"]),
            "months": _sum_months([r["months"] for r in b["rows"]]),
        })
    out_blocks.sort(key=lambda x: (x["cfo_name"], x["budget_name"]))

    all_rows = [r for b in out_blocks for r in b["rows"]]
    years = {py, by} | {int(r["year"]) for r in db.query(
        "SELECT DISTINCT year FROM budget WHERE layer = ?", (LAYER,))}
    return {
        "year": year,
        "plan_year_no": py,
        "base_year_no": by,
        "years": sorted(years),
        "locked": is_locked(year),
        "kpi": kpi(cfo_ids),
        "totals": {
            "plan_year": sum(r["plan_year"] for r in all_rows),
            "months": _sum_months([r["months"] for r in all_rows]),
            "rows_count": len(all_rows),
        },
        "blocks": out_blocks,
    }


***REMOVED*** ---------- строки, которые были в базовом году и пропали в новом ----------

def missing_rows(year: int | None = None, cfo_ids: Iterable[int] | None = None) -> dict:
    """Расходы базового года, которых нет в плане нового (ключ: статья+контрагент+договор)."""
    py, by = int(year or plan_year()), base_year()
    plan_keys = {match_key(r) for r in _year_rows(py, cfo_ids)}
    months_all = repo.plan_months(by, layer=LAYER)

    items = []
    for row in _year_rows(by, cfo_ids):
        if match_key(row) in plan_keys:
            continue
        rid = int(row["id"])
        items.append({
            "id": rid,
            "cfo_id": int(row["cfo_id"]),
            "cfo_name": row.get("cfo_name", ""),
            "budget_name": row.get("budget_name", ""),
            "article": row["article"],
            "counterparty": row["counterparty"],
            "contract": row["contract"],
            "detail_text": _detail_text(row),
            "plan_year": float(row["plan_year"]),
            "months": months_all.get(rid, _empty_months()),
        })
    items.sort(key=lambda x: (-x["plan_year"], x["cfo_name"]))
    return {
        "base_year": by, "plan_year": py,
        "count": len(items),
        "total": sum(i["plan_year"] for i in items),
        "items": items,
    }


def _copy_row(row: dict, months: list[float], to_year: int, factor: float, author: str) -> int:
    """Переносит строку в другой год слоя с коэффициентом индексации."""
    budget_id = repo.ensure_budget(int(row["cfo_id"]), to_year, row["budget_name"], layer=LAYER)
    new_months = [round(m * factor, 2) for m in months]
    plan = sum(new_months) if any(new_months) else round(float(row["plan_year"]) * factor, 2)
    return repo.create_row(
        budget_id,
        {
            "article": row["article"],
            "classifier": row["classifier"],
            "counterparty": row["counterparty"],
            "contract": row["contract"],
            "detail": row["detail"],
            "comment": row["comment"],
            "approver_comment": row["approver_comment"],
            "plan_year": plan,
            "carryover": bool(row.get("carryover", 1)),
        },
        months=new_months,
        author=author,
        source="copy",
        row_no=repo.next_row_no(budget_id),
    )


def add_missing(row_id: int, author: str, to_year: int | None = None) -> dict:
    """Кнопка «Добавить в план» у строки из списка пропавших."""
    to_year = int(to_year or plan_year())
    row = repo.get_row(row_id)
    if not row or row.get("layer") != LAYER:
        raise ValueError("Строка не найдена в слое планирования")
    months = repo.plan_months(int(row["year"]), layer=LAYER).get(row_id, _empty_months())
    new_id = _copy_row(dict(row), months, to_year, 1.0, author)
    amount = f"{float(row['plan_year']):,.2f}".replace(",", " ")
    db.log(author, "Строка перенесена в план",
           f"{row['cfo_name']} · {row['article']}",
           f"{row['year']} → {to_year} · {amount} ₽",
           "Была в базовом году, не было в плане")
    return {"id": new_id}


***REMOVED*** ---------- повтор бюджета прошлого года ----------

def copy_year(author: str, from_year: int | None = None, to_year: int | None = None,
              index_pct: float = 0.0, cfo_ids: Iterable[int] | None = None,
              source: str = "plan") -> dict:
    """Копирует строки прошлого года в новый: помесячно 1:1, дубли пропускаются.

    index_pct — индексация в процентах (7 = +7%), применяется к суммам месяцев.
    Строка считается дублем, если в целевом году уже есть такая же по ключу
    статья + контрагент + договор + детализация.

    `cfo_ids` ограничивает перенос доступными дирекциями: руководитель повторяет
    бюджет только своего ЦФО и не задевает чужие. `None` — без ограничения.

    `source`: "plan" — суммы берутся из бюджета прошлого года, "fact" — из факта,
    загруженного в слой. Факт бывает точнее бюджета, и ЦФО вправе взять его за базу.
    """
    from_year = int(from_year or base_year())
    to_year = int(to_year or plan_year())
    if from_year == to_year:
        raise ValueError("Год-источник и год-приёмник совпадают")
    if source not in ("plan", "fact"):
        raise ValueError("Источник переноса — либо бюджет, либо факт")

    factor = 1.0 + (float(index_pct) / 100.0)
    if factor <= 0:
        raise ValueError("Индексация не может обнулить бюджет")

    ids = None if cfo_ids is None else list(cfo_ids)
    source_rows = _year_rows(from_year, ids)
    if not source_rows:
        raise ValueError(f"В {from_year} году нет доступных вам строк для копирования")

    months_all = (repo.row_fact_months(from_year, LAYER) if source == "fact"
                  else repo.plan_months(from_year, layer=LAYER))
    if source == "fact" and not months_all:
        raise ValueError(f"Факт за {from_year} год не загружен — переносить нечего")

    ***REMOVED*** Дубли считаем по кратности, а не по множеству: в году легально лежат несколько
    ***REMOVED*** строк с одинаковым ключом (одна статья без контрагента, разные назначения).
    ***REMOVED*** Каждая строка целевого года «гасит» одну исходную — повторный запуск ничего не добавит.
    ***REMOVED*** Круг ЦФО тот же, что у источника, иначе чужая строка съедала бы чужую квоту.
    quota = Counter(full_key(r) for r in _year_rows(to_year, ids))

    copied = skipped = empty = 0
    total = 0.0
    for row in source_rows:
        key = full_key(row)
        if quota[key] > 0:
            quota[key] -= 1
            skipped += 1
            continue
        rid = int(row["id"])
        months = months_all.get(rid, _empty_months())
        if source == "fact" and not any(months):
            empty += 1           ***REMOVED*** по строке не было расхода — в план её не тянем
            continue
        row_data = dict(row)
        if source == "fact":
            row_data["plan_year"] = sum(months)
        _copy_row(row_data, months, to_year, factor, author)
        copied += 1
        total += sum(months) * factor if source == "fact" else float(row["plan_year"]) * factor

    what = "факта" if source == "fact" else "бюджета"
    note = f"скопировано строк: {copied}, пропущено дублей: {skipped}"
    if empty:
        note += f", без сумм: {empty}"
    if index_pct:
        note += f", индексация {index_pct:+.1f}%"
    amount = f"{total:,.2f}".replace(",", " ")
    db.log(author, f"Повтор {what} прошлого года", f"{from_year} → {to_year}", note,
           f"Сумма после переноса: {amount} ₽")
    return {"copied": copied, "skipped": skipped, "empty": empty, "total": total,
            "from_year": from_year, "to_year": to_year, "index_pct": index_pct,
            "source": source}


***REMOVED*** ---------- справочники для форм ----------

def references(year: int | None = None, cfo_ids: list[int] | None = None) -> dict:
    """Статьи, контрагенты, договоры и детализация для выпадающих списков.

    Для каждого ЦФО отдаём свой набор, плюс общий список — его показывает галочка
    «показать все». Договоры сгруппированы по контрагенту, чтобы список сужался
    после его выбора.

    Детализация — список только у дирекций, где колонка своя (`detail_source` =
    `detail`, это ИТ): у остальных в ней живёт комментарий к строке, и прошлые
    формулировки там не повторяются. В общий список детализация не сводится —
    чужие расшифровки дирекции не подсказка, а шум.

    `cfo_ids` ограничивает выдачу: руководителю не уезжают контрагенты и договоры
    чужих дирекций, поэтому и «показать все» у него не шире собственного ЦФО.
    `None` — без ограничения, то есть финотдел.
    """
    year = int(year or plan_year())
    allowed = None if cfo_ids is None else {int(i) for i in cfo_ids}
    by_cfo: dict[int, dict[str, Any]] = {}

    def bucket(cfo_id: int) -> dict | None:
        if allowed is not None and int(cfo_id) not in allowed:
            return None
        return by_cfo.setdefault(int(cfo_id), {
            "articles": set(), "counterparties": set(), "contracts": {},
            "details": set(),
        })

    for ref in repo.list_article_refs():
        own = bucket(ref["cfo_id"])
        if own is not None:
            own["articles"].add(ref["article"])

    for source_year in {year, base_year()}:
        for row in repo.used_values(source_year, layer=LAYER):
            b = bucket(row["cfo_id"])
            if b is None:
                continue
            if row["article"]:
                b["articles"].add(row["article"])
            if row["counterparty"]:
                b["counterparties"].add(row["counterparty"])
            if row["contract"]:
                b["contracts"].setdefault(row["counterparty"] or "", set()).add(row["contract"])
            ***REMOVED*** Берём то, что видно в колонке «Детализация», — у ИТ при пустой
            ***REMOVED*** детализации там стоит комментарий, и список должен совпадать с
            ***REMOVED*** тем, что дирекция читает в таблице.
            if (row.get("detail_source") or "comment") == "detail":
                detail = _detail_text(row)
                if detail:
                    b["details"].add(detail)

    out: dict[str, Any] = {
        "by_cfo": {},
        "all": {"articles": set(), "counterparties": set(), "contracts": set()},
    }
    for cfo_id, b in by_cfo.items():
        out["by_cfo"][str(cfo_id)] = {
            "articles": sorted(b["articles"]),
            "counterparties": sorted(b["counterparties"]),
            "contracts": {cp: sorted(items) for cp, items in b["contracts"].items()},
            "details": sorted(b["details"]),
        }
        out["all"]["articles"] |= b["articles"]
        out["all"]["counterparties"] |= b["counterparties"]
        for items in b["contracts"].values():
            out["all"]["contracts"] |= items

    out["all"] = {k: sorted(v) for k, v in out["all"].items()}
    return out


***REMOVED*** ---------- импорт листа «Бюджеты ЦФО» ----------

def _plan_or_months(row: dict) -> float:
    """ИТОГО строки: из файла, а при пустой колонке — сумма месяцев.

    В шаблоне ИТОГО часто оставляют пустым и заполняют только месяцы. Без этого
    строка легла бы в план с нулём, хотя разбивка по месяцам заполнена.
    """
    plan = float(row.get("plan_year") or 0)
    return plan if plan else round(sum(row.get("months") or []), 2)


def import_budgets(content: bytes, filename: str, year: int, author: str,
                   replace: bool = True, cfo_ids: Iterable[int] | None = None) -> dict:
    """Заливает лист «Бюджеты ЦФО» в слой планирования за указанный год.

    `cfo_ids` ограничивает заливку доступными дирекциями: руководитель
    перезаливает только свой бюджет, чужие строки файла пропускаются, чужие
    бюджеты при замене не стираются.
    """
    parsed = cfo_budgets.parse(content)
    mismatches = cfo_budgets.check_totals(parsed)
    allowed = None if cfo_ids is None else {int(i) for i in cfo_ids}

    rows = [(repo.ensure_cfo(row["cfo"]), row) for row in parsed["rows"]]
    ***REMOVED*** Замена — только по тем ЦФО, чьи строки есть в файле. Файл одной дирекции
    ***REMOVED*** не должен стирать план остальных, даже когда его грузит финотдел. Пустой
    ***REMOVED*** файл не удаляет ничего: сносить план целиком — отдельное действие.
    scope = {cfo_id for cfo_id, _ in rows if allowed is None or cfo_id in allowed}
    removed = repo.delete_budgets(year, LAYER, sorted(scope)) if replace else 0

    created = 0
    other_label = 0
    foreign = 0
    total = 0.0
    for cfo_id, row in rows:
        if allowed is not None and cfo_id not in allowed:
            foreign += 1
            continue
        if IT_MARKER in row["cfo"].lower():
            repo.set_detail_source(cfo_id, "detail")
        plan = _plan_or_months(row)
        budget_id = repo.ensure_budget(cfo_id, year, row["budget"], layer=LAYER)
        repo.create_row(budget_id, {**row, "plan_year": plan},
                        months=row["months"], author=author,
                        source="import", row_no=repo.next_row_no(budget_id))
        created += 1
        total += plan
        if row.get("approver_comment"):
            other_label += 1

    repo.create_import("cfo_budgets", filename, year, author, created, len(mismatches),
                       note=f"строк: {created}, блоков: {len(parsed['blocks'])}, "
                            f"удалено прежних: {removed}")
    db.log(author, "Импорт листа «Бюджеты ЦФО»", filename,
           f"строк: {created}, расхождений с ИТОГО: {len(mismatches)}",
           f"Слой планирования, {year} год")
    return {
        "year": year, "rows": created, "blocks": len(parsed["blocks"]),
        "removed": removed, "replaced_cfo": len(scope),
        "other_cfo_label": other_label, "foreign": foreign,
        ***REMOVED*** ровно то, что легло в базу: у строки с пустым ИТОГО сумма собирается
        ***REMOVED*** из месяцев, а чужие ЦФО в отчёт не попадают — их и не записали
        "total": round(total, 2),
        "mismatches": mismatches,
    }


***REMOVED*** ---------- факт слоя планирования ----------

def _detail_source_of(cfo_id: int) -> str:
    row = db.query_one("SELECT detail_source FROM cfo WHERE id = ?", (cfo_id,))
    return (row["detail_source"] if row else "comment") or "comment"


def import_fact(content: bytes, filename: str, year: int, author: str,
                cfo_ids: Iterable[int] | None = None) -> dict:
    """Заливает факт года из листа того же вида, что и «Бюджеты ЦФО».

    Суммы ложатся на строки плана этого года: ищем строку по ключу
    статья + контрагент + договор + детализация внутри того же ЦФО. Чего в плане
    не было — заводим строкой с нулевым бюджетом, иначе расход просто исчез бы;
    повторная загрузка такую строку уже находит и не задваивает.
    """
    parsed = cfo_budgets.parse(content)
    allowed = None if cfo_ids is None else {int(i) for i in cfo_ids}

    ***REMOVED*** многоключевой индекс: строк с одинаковым ключом в году легально несколько
    index: dict[tuple, list[int]] = {}
    for row in _year_rows(year, None if allowed is None else sorted(allowed)):
        index.setdefault((int(row["cfo_id"]),) + full_key(row), []).append(int(row["id"]))

    ***REMOVED*** Нулевые строки для факта смысла не имеют, а строку в плане завели бы
    ***REMOVED*** пустую: расход, которого не было, — это не расход.
    items = [(repo.ensure_cfo(item["cfo"]), item) for item in parsed["rows"]
             if item["plan_year"] or any(item["months"])]
    ***REMOVED*** Прежний факт гасим тем же кругом ЦФО, что и в файле: иначе загрузка по
    ***REMOVED*** одной дирекции обнуляла бы факт остальных, а повторная загрузка своей —
    ***REMOVED*** оставляла бы старые суммы на строках, выпавших из файла.
    scope = {cfo_id for cfo_id, _ in items if allowed is None or cfo_id in allowed}
    cleared = repo.clear_layer_fact(year, LAYER, sorted(scope))
    matched = created = foreign = 0
    total = 0.0
    for cfo_id, item in items:
        if allowed is not None and cfo_id not in allowed:
            foreign += 1
            continue
        keyed = dict(item, detail_source=_detail_source_of(cfo_id))
        key = (cfo_id,) + full_key(keyed)
        ids = index.get(key)
        if ids:
            row_id = ids.pop(0)
            matched += 1
        else:
            budget_id = repo.ensure_budget(cfo_id, year, item["budget"], layer=LAYER)
            row_id = repo.create_row(
                budget_id,
                {**item, "plan_year": 0.0,
                 "approver_comment": "Строка заведена загрузкой факта"},
                months=_empty_months(), author=author, source="fact",
                row_no=repo.next_row_no(budget_id),
            )
            created += 1
        repo.set_row_fact(row_id, item["months"])
        total += sum(item["months"])

    repo.create_import("operplan_fact", filename, year, author, matched + created, 0,
                       note=f"строк: {matched + created}, заведено новых: {created}")
    db.log(author, "Загрузка факта в слой планирования", filename,
           f"строк: {matched + created}, заведено новых: {created}",
           f"{year} год, сумма факта: {total:,.2f} ₽".replace(",", " "))
    return {"year": year, "rows": matched + created, "matched": matched,
            "created": created, "foreign": foreign, "cleared": cleared, "total": total}


def import_articles(content: bytes, filename: str, author: str) -> dict:
    """Заливает справочник «ЦФО Статьи»: какие статьи закреплены за дирекцией."""
    parsed = cfo_budgets.parse_articles(content)
    by_cfo: dict[int, set[str]] = {}
    unknown: list[str] = []
    for pair in parsed["pairs"]:
        found = repo.find_cfo(pair["cfo"])
        if not found:
            if pair["cfo"] not in unknown:
                unknown.append(pair["cfo"])
            continue
        by_cfo.setdefault(int(found["id"]), set()).add(pair["article"])

    saved = 0
    for cfo_id, articles in by_cfo.items():
        saved += repo.set_article_refs(cfo_id, articles)

    db.log(author, "Импорт справочника «ЦФО Статьи»", filename,
           f"дирекций: {len(by_cfo)}, статей: {saved}",
           f"не найдено в справочнике ЦФО: {', '.join(unknown)}" if unknown else "")
    return {"cfo": len(by_cfo), "articles": saved, "pairs": len(parsed["pairs"]),
            "unknown_cfo": unknown}
