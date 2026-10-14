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

import json
import re
from collections import Counter
from typing import Any, Iterable, Sequence

from app import calc, db, repo
from app.importers import cfo_budgets, planfact, xlsx

LAYER = repo.LAYER_OPERPLAN
DEFAULT_PLAN_YEAR = 2027
DEFAULT_BASE_YEAR = 2026
***REMOVED*** Откуда дирекция берёт колонку «Детализация» — свойство самой дирекции
***REMOVED*** (`cfo.detail_source`), а не догадка по её названию: имя меняется, подстрока
***REMOVED*** устаревает молча. Признак ставится руками в реестре ЦФО, заливка плана его
***REMOVED*** не трогает.


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
    """Четыре показателя вкладки: план нового года, бюджет базового, план-факт и вне бюджета."""
    py, by = plan_year(), base_year()
    plan_rows = _year_rows(py, cfo_ids)
    base_rows = _year_rows(by, cfo_ids)

    plan_total = sum(float(r["plan_year"]) for r in plan_rows)
    base_total = sum(float(r["plan_year"]) for r in base_rows)

    base_ids = {int(r["id"]) for r in base_rows}
    base_fact = sum(sum(v) for v in fact_months_by_row(by, row_ids=base_ids).values())

    ***REMOVED*** Вне бюджета — факт без строки плана: и объявленный дирекцией в блоке
    ***REMOVED*** «ВНЕ БЮДЖЕТА», и тот, которому строки не нашлось. Считается по тому же
    ***REMOVED*** кругу ЦФО, что и остальные плитки, поэтому при фильтре по дирекции
    ***REMOVED*** показывает её одну, а без фильтра — сумму по всем доступным.
    outside = unlinked_fact(by, cfo_ids)
    outside_total = sum(item["total"] for item in outside)

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
        "outside_total": outside_total,
        "outside_rows": len(outside),
        "outside_cfo": len({item["cfo_id"] for item in outside}),
        ***REMOVED*** доля перерасхода от бюджета базового года
        "outside_pct": (outside_total / base_total) if base_total else 0.0,
    }


def row_spends(year: int, cfo_ids: Iterable[int] | None = None) -> dict[int, list[dict]]:
    """Расходы по контрагентам под строками плана: `{row_id: [контрагенты]}`.

    Из чего сложился факт строки: контрагент, договор и двенадцать месяцев.
    Отдельные платежи сюда не разворачиваются намеренно — у дирекции вроде
    Сервисного обслуживания их сотни, и таблица стала бы нечитаемой; в файле
    дирекции расход тоже сгруппирован по контрагенту.
    """
    allowed = None if cfo_ids is None else [int(i) for i in cfo_ids]
    grouped: dict[int, dict[tuple, dict]] = {}
    for item in repo.layer_fact_rows(year, LAYER, allowed):
        row_id = item["row_id"]
        if not row_id:
            continue
        key = (item["counterparty"], item["contract"], item["purpose"])
        slot = grouped.setdefault(int(row_id), {}).get(key)
        if slot is None:
            slot = grouped[int(row_id)][key] = {
                "counterparty": item["counterparty"], "contract": item["contract"],
                "detail": item["purpose"], "months": _empty_months(),
            }
        month = calc.month_of(item["pay_date"])
        if 1 <= month <= calc.MONTHS:
            slot["months"][month - 1] += float(item["amount"])
    out: dict[int, list[dict]] = {}
    for row_id, slots in grouped.items():
        items = list(slots.values())
        for slot in items:
            slot["total"] = sum(slot["months"])
        out[row_id] = sorted(items, key=lambda s: -s["total"])
    return out


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

    spends = row_spends(year, cfo_ids)
    for row in rows:
        block = blocks.get(int(row["budget_id"]))
        if block is None:
            continue
        rid = int(row["id"])
        item = _row_view(row, months_all.get(rid, _empty_months()),
                         base_by_key.get(full_key(row)))
        ***REMOVED*** расходы по контрагентам под строкой: раскрытие на вкладке
        item["spends"] = spends.get(rid, [])
        block["rows"].append(item)

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
        ***REMOVED*** факт без строки бюджета: показывается блоком внизу вкладки и плиткой
        "outside": unlinked_fact(by, cfo_ids),
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


def unlinked_fact(year: int, cfo_ids: Iterable[int] | None = None) -> list[dict]:
    """Факт слоя планирования, которому не досталось строки бюджета.

    Две причины и обе сюда: дирекция сама отнесла расход в блок «ВНЕ БЮДЖЕТА»
    (`out_of_budget`), либо строка файла не нашла пары среди наших. Для
    читателя разница в пометке, а не в месте: и то и другое — потраченное
    мимо плана.
    """
    allowed = None if cfo_ids is None else [int(i) for i in cfo_ids]
    grouped: dict[tuple, dict] = {}
    for item in repo.layer_fact_rows(year, LAYER, allowed):
        if item["row_id"]:
            continue
        key = (item["cfo_id"], item["article"], item["counterparty"],
               item["contract"], item["purpose"], int(item["out_of_budget"]))
        slot = grouped.get(key)
        if slot is None:
            slot = grouped[key] = {
                "cfo_id": item["cfo_id"], "article": item["article"],
                "counterparty": item["counterparty"], "contract": item["contract"],
                "detail": item["purpose"],
                "out_of_budget": bool(item["out_of_budget"]),
                "months": _empty_months(),
            }
        month = calc.month_of(item["pay_date"])
        if 1 <= month <= calc.MONTHS:
            slot["months"][month - 1] += float(item["amount"])
    out = list(grouped.values())
    for slot in out:
        slot["total"] = sum(slot["months"])
    names = {int(c["id"]): c["name"] for c in repo.list_cfo()}
    for slot in out:
        slot["cfo_name"] = names.get(int(slot["cfo_id"] or 0), "")
    return sorted(out, key=lambda s: (s["cfo_name"], s["article"], s["counterparty"]))


def _find_cfo_id(name: str) -> int | None:
    """Ищет ЦФО по названию, но не заводит.

    Загрузка факта справочники не правит: пустая колонка ЦФО у строки «ВСЕГО»
    однажды завела бы дирекцию «Не указано», а опечатка в названии — дубль
    настоящей дирекции.
    """
    found = repo.find_cfo(name or "")
    return int(found["id"]) if found else None


def _items_from_planfact(parsed: dict) -> list[dict]:
    """Строки файла дирекции в общем виде: плановая строка плюс расходы под ней."""
    items = []
    for plan in parsed["plans"]:
        items.append({
            "cfo": plan["cfo"], "budget": plan["budget"], "article": plan["article"],
            "counterparty": plan["counterparty"], "contract": plan["contract"],
            "detail": plan["detail"], "comment": plan["comment"],
            "plan_year": plan["plan_year"], "excel_row": plan["excel_row"],
            "fact_months": planfact.plan_fact_months(plan),
            "parts": [{
                "counterparty": p["counterparty"], "contract": p["contract"],
                "detail": p["detail"], "comment": p["comment"],
                "article": p["article"] or plan["article"],
                "months": p["fact_months"], "excel_row": p["excel_row"],
            } for p in plan["parts"]],
        })
    return items


def _items_from_budgets(parsed: dict) -> tuple[list[dict], list[dict]]:
    """Строки нашей выгрузки «Бюджеты ЦФО»: факт лежит прямо в месяцах строки."""
    items, errors = [], []
    for row in parsed["rows"]:
        if row["plan_year"] and not any(row["months"]):
            ***REMOVED*** Факт складывается из месяцев, колонка ИТОГО для него не читается.
            ***REMOVED*** Раньше такая строка молча записывала нули и гасила прежний факт.
            errors.append({"excel_row": row["excel_row"], "article": row["article"],
                           "problem": "заполнено ИТОГО, но не заполнен ни один месяц"})
            continue
        if not any(row["months"]):
            continue
        items.append({
            "cfo": row["cfo"], "budget": row["budget"], "article": row["article"],
            "counterparty": row["counterparty"], "contract": row["contract"],
            "detail": row["detail"], "comment": row["comment"],
            "plan_year": row["plan_year"], "excel_row": row["excel_row"],
            "fact_months": list(row["months"]), "parts": [],
        })
    return items, errors


def _link_keys(item: dict, detail_source: str) -> list[tuple]:
    """Признаки связи строки файла с нашей строкой, от строгого к мягкому.

    Ключ «статья + контрагент + договор + детализация» на файлах дирекций даёт
    от половины до трёх четвертей: у плановой строки контрагент часто пуст,
    он живёт на расходах под ней. Сумма годового бюджета вместе с текстом
    детализации разводит строки надёжнее — на проверенных файлах каскад
    закрывает от 97 до 100 процентов наших строк.
    """
    keyed = dict(item, detail_source=detail_source)
    detail = _norm(_detail_text(keyed))
    article = _norm(item.get("article", ""))
    plan = round(float(item.get("plan_year") or 0), 2)
    keys = [("k1",) + full_key(keyed)]
    if detail and plan:
        keys.append(("k2", article, detail, plan))
        keys.append(("k3", detail, plan))
    return keys


def _link_rows(items: list[dict], rows: list[dict]) -> dict[int, dict]:
    """Связывает строки файла с нашими строками. Возвращает {excel_row: наша строка}.

    Наша строка занимается один раз: иначе две одинаковые строки файла легли бы
    обе на одну и ту же и факт задвоился бы.

    Блок бюджета участвует в привязке только там, где бюджетов у дирекции
    больше одного — сегодня это один ИТ. У остальных сравнивать нечего и
    вредно: свой единственный блок дирекции называют в файлах «Бюджет
    дирекции», у нас он «Основной бюджет», а блоки стратегии и аналитики
    внутри файла ИТ — это их собственные основные бюджеты.
    """
    by_cfo: dict[int, list[dict]] = {}
    budgets_of: dict[int, set[str]] = {}
    for row in rows:
        by_cfo.setdefault(int(row["cfo_id"]), []).append(row)
        budgets_of.setdefault(int(row["cfo_id"]), set()).add(row["budget_name"])
    multi = {cfo_id for cfo_id, names in budgets_of.items() if len(names) > 1}

    taken: dict[int, dict] = {}
    used: set[int] = set()
    for depth in range(3):
        index: dict[tuple, list[dict]] = {}
        for cfo_id, cfo_rows in by_cfo.items():
            source = _detail_source_of(cfo_id)
            for row in cfo_rows:
                if int(row["id"]) in used:
                    continue
                keys = _link_keys(row, source)
                if depth < len(keys):
                    index.setdefault((cfo_id,) + keys[depth], []).append(row)
        for item in items:
            if item["excel_row"] in taken or not item.get("cfo_id"):
                continue
            keys = _link_keys(item, _detail_source_of(item["cfo_id"]))
            if depth >= len(keys):
                continue
            found = index.get((item["cfo_id"],) + keys[depth]) or []
            fresh = [r for r in found if int(r["id"]) not in used]
            ***REMOVED*** у дирекции с несколькими бюджетами блок разводит одинаковые
            ***REMOVED*** ключи: у ИТ таких строк восемь десятков в двух блоках
            if len(fresh) > 1 and item["cfo_id"] in multi:
                same = [r for r in fresh
                        if _norm(r["budget_name"]) == _norm(item.get("budget", ""))]
                if len(same) == 1:
                    fresh = same
            ***REMOVED*** неоднозначный признак привязкой не считаем: пусть лучше строка
            ***REMOVED*** уйдёт в непривязанное, чем факт ляжет не туда
            if len(fresh) == 1:
                taken[item["excel_row"]] = fresh[0]
                used.add(int(fresh[0]["id"]))
    return taken


def _link_spends(items: list[dict], rows: list[dict], busy: set[int]) -> list[dict]:
    """Второй проход: пристроить расходы строк, которым пары не нашлось.

    Плановая строка файла могла не найтись, а расход под ней — найтись: у него
    есть свой контрагент и договор, и ключ у него строгий, тот же самый
    «статья + контрагент + договор». Берём только однозначное совпадение со
    свободной строкой.

    Проход по каноничной пометке «бюджет из строки N» сюда не добавлен
    намеренно: замер на двенадцати файлах дал ноль. Пометка на 99% совпадает
    с группировкой, поэтому у непривязанной строки она указывает на неё же.
    Проход «по статье, если свободная строка одна» не добавлен тоже — он
    вернул бы 35 млн, но из них 33,6 млн это «Платежи, перешедшие с 2025 года»
    с нулевым бюджетом, которым плановой строки не положено вовсе.
    """
    free: dict[tuple, list[dict]] = {}
    for row in rows:
        if int(row["id"]) in busy:
            continue
        free.setdefault((int(row["cfo_id"]),) + match_key(row), []).append(row)

    placed: list[dict] = []
    for item in items:
        for part in item.get("parts") or []:
            if not any(part["months"]):
                continue
            found = [r for r in free.get((item["cfo_id"],) + match_key(part), [])
                     if int(r["id"]) not in busy]
            if len(found) != 1:
                continue
            busy.add(int(found[0]["id"]))
            placed.append({"row": found[0], "part": part, "item": item,
                           "cfo_id": item["cfo_id"],
                           "article": part.get("article") or item["article"],
                           "months": list(part["months"])})
    return placed


def plan_fact(content: bytes, year: int, cfo_ids: Iterable[int] | None = None,
              only_cfo_ids: Iterable[int] | None = None) -> dict:
    """Разбирает файл и раскладывает его по нашим строкам — без единой записи.

    Один и тот же разбор обслуживает предпросмотр и саму загрузку, поэтому
    показанное на экране и записанное в базу не могут разойтись.
    """
    sheets = xlsx.load_rows(content)[2]
    if planfact.looks_like_planfact(sheets):
        parsed = planfact.parse(content)
        items = _items_from_planfact(parsed)
        errors: list[dict] = []
        out_of_budget = [{
            "cfo": x["cfo"], "article": x["article"], "counterparty": x["counterparty"],
            "contract": x["contract"], "detail": x["detail"], "comment": x["comment"],
            "months": x["fact_months"], "excel_row": x["excel_row"],
        } for x in parsed["out_of_budget"] if any(x["fact_months"])]
        fmt, skipped = "planfact", parsed["skipped_service"]
        conflicts = parsed["conflicts"]
    else:
        parsed = cfo_budgets.parse(content)
        items, errors = _items_from_budgets(parsed)
        out_of_budget, fmt = [], "budgets"
        skipped, conflicts = parsed.get("skipped_service", []), []

    allowed = None if cfo_ids is None else {int(i) for i in cfo_ids}
    ***REMOVED*** отмеченные галочками дирекции: что не отмечено, то и не тронется
    chosen = None if only_cfo_ids is None else {int(i) for i in only_cfo_ids}
    if chosen is not None and not chosen:
        chosen = None
    unknown: list[str] = []
    foreign = 0
    mine: list[dict] = []
    for item in items:
        cfo_id = _find_cfo_id(item["cfo"])
        if cfo_id is None:
            if item["cfo"] and item["cfo"] not in unknown:
                unknown.append(item["cfo"])
            continue
        if allowed is not None and cfo_id not in allowed:
            foreign += 1
            continue
        if chosen is not None and cfo_id not in chosen:
            foreign += 1
            continue
        item["cfo_id"] = cfo_id
        mine.append(item)

    for x in out_of_budget:
        x["cfo_id"] = _find_cfo_id(x["cfo"])
    out_of_budget = [x for x in out_of_budget if x["cfo_id"] is not None
                     and (allowed is None or x["cfo_id"] in allowed)
                     and (chosen is None or x["cfo_id"] in chosen)]

    scope = sorted({item["cfo_id"] for item in mine} |
                   {x["cfo_id"] for x in out_of_budget})
    rows = _year_rows(year, scope) if scope else []
    linked = _link_rows(mine, rows)

    matched = [item for item in mine if item["excel_row"] in linked]
    unlinked = [item for item in mine if item["excel_row"] not in linked
                and any(item["fact_months"])]
    for item in matched:
        item["row"] = linked[item["excel_row"]]

    ***REMOVED*** Второй проход: расходы непривязанных строк могут найтись поодиночке.
    busy = {int(item["row"]["id"]) for item in matched}
    spends = _link_spends(unlinked, rows, busy)
    ***REMOVED*** то, что пристроено, из непривязанного вычитается — иначе задвоится
    placed_by_item: dict[int, list[dict]] = {}
    for p in spends:
        placed_by_item.setdefault(p["item"]["excel_row"], []).append(p)
    for item in unlinked:
        for p in placed_by_item.get(item["excel_row"], []):
            item["fact_months"] = [a - b for a, b in
                                   zip(item["fact_months"], p["months"])]
    unlinked = [item for item in unlinked if any(round(m, 2) for m in item["fact_months"])]

    ***REMOVED*** Строка легла в другой блок бюджета, чем в файле. Молчать об этом нельзя:
    ***REMOVED*** значит план у нас и у дирекции разошёлся блоками, и либо она переложила
    ***REMOVED*** расход, либо наша база устарела.
    ***REMOVED***
    ***REMOVED*** Считаем только тогда, когда названный в файле блок у этой дирекции
    ***REMOVED*** действительно есть. Иначе сравнивать нечего: свой единственный блок
    ***REMOVED*** дирекции называют «Бюджет дирекции», у нас он «Основной бюджет», —
    ***REMOVED*** пометить этим всю дирекцию значило бы соврать.
    known: dict[int, set[str]] = {}
    for row in rows:
        known.setdefault(int(row["cfo_id"]), set()).add(_norm(row["budget_name"]))
    moved = [{"excel_row": item["excel_row"], "article": item["article"],
              "detail": item["detail"] or item["comment"],
              "from": item.get("budget", ""), "to": item["row"]["budget_name"],
              "total": sum(item["fact_months"])}
             for item in matched
             if _norm(item.get("budget", "")) in known.get(item["cfo_id"], set())
             and _norm(item["row"]["budget_name"]) != _norm(item.get("budget", ""))]

    was = repo.row_fact_months(year, LAYER)
    before = sum(sum(v) for r in rows for v in [was.get(int(r["id"]), [])])
    before_by_cfo: dict[int, float] = {}
    for r in rows:
        before_by_cfo[int(r["cfo_id"])] = (before_by_cfo.get(int(r["cfo_id"]), 0.0)
                                           + sum(was.get(int(r["id"]), [])))
    loads = repo.last_fact_loads(year)
    return {
        "format": fmt, "year": year, "scope": scope,
        ***REMOVED*** по каждой дирекции круга: сколько факта заменится и чем он был залит.
        ***REMOVED*** Файл ИТ несёт ещё стратегию и аналитику, и без этой строки старый
        ***REMOVED*** файл молча затирал бы более свежую отдельную загрузку.
        "cfo": [{"id": int(c["id"]), "name": c["name"],
                 "before": before_by_cfo.get(int(c["id"]), 0.0),
                 "last_file": (loads.get(int(c["id"])) or {}).get("filename", ""),
                 "last_at": (loads.get(int(c["id"])) or {}).get("at", "")}
                for c in repo.list_cfo() if int(c["id"]) in scope],
        "matched": matched, "unlinked": unlinked, "out_of_budget": out_of_budget,
        "spends": spends, "block_moved": moved,
        "rows_total": len(rows), "foreign": foreign, "unknown_cfo": unknown,
        "errors": errors, "skipped_service": skipped, "conflicts": conflicts,
        "total": (sum(sum(item["fact_months"]) for item in matched)
                  + sum(sum(p["months"]) for p in spends)),
        "spends_total": sum(sum(p["months"]) for p in spends),
        "unlinked_total": sum(sum(item["fact_months"]) for item in unlinked),
        "out_of_budget_total": sum(sum(x["months"]) for x in out_of_budget),
        "before_total": before,
    }


def import_fact(content: bytes, filename: str, year: int, author: str,
                cfo_ids: Iterable[int] | None = None,
                only_cfo_ids: Iterable[int] | None = None) -> dict:
    """Заливает факт года: нашу выгрузку «Бюджеты ЦФО» или файл дирекции.

    **План не трогается ни при каких условиях** — ни строки, ни бюджеты, ни
    справочник ЦФО. Прежде загрузка заводила недостающие строки с нулевым
    бюджетом, и файл дирекции добавил бы Административному отделу двенадцать
    строк к восьми. Расход, которому не нашлось строки плана, виден списком
    непривязанного и в плитке «Вне бюджета», но плана не меняет.

    Факт заменяется целиком по тем дирекциям, что попали в круг: иначе
    повторная загрузка оставила бы прежние суммы на строках, выпавших из файла.
    """
    plan = plan_fact(content, year, cfo_ids, only_cfo_ids)
    scope = plan["scope"]
    cleared = repo.clear_layer_fact(year, LAYER, scope)
    cleared += repo.clear_layer_fact_rows(year, LAYER, scope)

    def spend(cfo_id: int, row_id: int | None, part: dict, out_of_budget: bool,
              article: str, tag: str) -> None:
        """Расход по контрагенту — помесячно, одной записью на месяц."""
        for m, amount in enumerate(part["months"], start=1):
            if not amount:
                continue
            repo.create_fact({
                "row_id": row_id, "cfo_id": cfo_id, "layer": LAYER, "year": year,
                "pay_date": f"{year}-{m:02d}-15", "amount": amount,
                "article": article, "counterparty": part.get("counterparty", ""),
                "contract": part.get("contract", ""),
                "purpose": part.get("detail") or part.get("comment", ""),
                "out_of_budget": out_of_budget, "source": "planfact",
                ***REMOVED*** ЦФО в ключе обязателен: файлы разных дирекций нумеруются
                ***REMOVED*** с единицы, и без него десятая строка одного файла
                ***REMOVED*** сталкивалась с десятой строкой другого.
                "external_id": f"pf:{year}:{cfo_id}:{tag}:{part['excel_row']}:m{m}",
            }, author)

    total = 0.0
    for item in plan["matched"]:
        row = item["row"]
        row_id = int(row["id"])
        months = item["fact_months"]
        repo.set_row_fact(row_id, months)
        total += sum(months)
        parts = item["parts"] or [{
            ***REMOVED*** у строки без расшифровки контрагент берётся с неё самой, иначе
            ***REMOVED*** раскрытие строки на вкладке осталось бы пустым
            "counterparty": item["counterparty"], "contract": item["contract"],
            "detail": item["detail"], "comment": item["comment"],
            "months": months, "excel_row": item["excel_row"],
        }]
        for part in parts:
            spend(int(item["cfo_id"]), row_id, part, False,
                  part.get("article") or item["article"], "row")

    for p in plan["spends"]:
        row_id = int(p["row"]["id"])
        repo.set_row_fact(row_id, p["months"])
        total += sum(p["months"])
        spend(int(p["cfo_id"]), row_id, p["part"], False, p["article"], "part")

    for item in plan["unlinked"]:
        spend(int(item["cfo_id"]), None, {
            "counterparty": item["counterparty"], "contract": item["contract"],
            "detail": item["detail"], "comment": item["comment"],
            "months": item["fact_months"], "excel_row": item["excel_row"],
        }, False, item["article"], "free")

    for x in plan["out_of_budget"]:
        spend(int(x["cfo_id"]), None, x, True, x["article"], "oob")

    note = (f"строк: {len(plan['matched'])}, без строки плана: {len(plan['unlinked'])}, "
            f"вне бюджета: {len(plan['out_of_budget'])}"
            + (f", в другой блок: {len(plan['block_moved'])}"
               if plan["block_moved"] else ""))
    ***REMOVED*** круг дирекций сохраняем: по нему предпросмотр следующей загрузки скажет,
    ***REMOVED*** что именно он собирается заменить и насколько оно свежее
    repo.create_import("operplan_fact", filename, year, author,
                       len(plan["matched"]), len(plan["unlinked"]), note=note,
                       mapping=json.dumps({"cfo_ids": scope}, ensure_ascii=False))
    db.log(author, "Загрузка факта в слой планирования", filename, note,
           f"{year} год, формат: {plan['format']}, сумма факта: {total:,.2f} ₽"
           .replace(",", " "))
    return {
        "year": year, "format": plan["format"], "rows": len(plan["matched"]),
        "matched": len(plan["matched"]), "created": 0,
        "unlinked": len(plan["unlinked"]), "unlinked_total": plan["unlinked_total"],
        "out_of_budget": len(plan["out_of_budget"]),
        "out_of_budget_total": plan["out_of_budget_total"],
        "foreign": plan["foreign"], "unknown_cfo": plan["unknown_cfo"],
        "block_moved": len(plan["block_moved"]),
        "spends": len(plan["spends"]), "spends_total": plan["spends_total"],
        "errors": plan["errors"], "cleared": cleared, "total": total,
    }


def preview_fact_files(files: Sequence[tuple[str, bytes]], year: int,
                       cfo_ids: Iterable[int] | None = None,
                       only_cfo_ids: Iterable[int] | None = None) -> dict:
    """Предпросмотр пачки файлов: что сделает загрузка, ничего не записывая.

    Дирекции сводятся по всем файлам: одна дирекция может прийти и своим
    файлом, и внутри чужого (бюджеты стратегии и аналитики лежат в файле ИТ),
    и тогда важно показать её один раз, а не дважды.
    """
    per_file, cfo_rows, errors, unknown = [], {}, [], []
    totals = {"matched": 0, "total": 0.0, "unlinked": 0, "unlinked_total": 0.0,
              "out_of_budget": 0, "out_of_budget_total": 0.0, "foreign": 0,
              "block_moved": 0}
    moved = []
    for filename, content in files:
        try:
            plan = plan_fact(content, year, cfo_ids, only_cfo_ids)
        except ValueError as exc:
            per_file.append({"filename": filename, "error": str(exc)})
            errors.append({"filename": filename, "problem": str(exc)})
            continue
        per_file.append({
            "filename": filename, "format": plan["format"],
            "cfo": [c["name"] for c in plan["cfo"]],
            "matched": len(plan["matched"]), "total": plan["total"],
            "unlinked": len(plan["unlinked"]),
            "out_of_budget": len(plan["out_of_budget"]),
            "foreign": plan["foreign"], "errors": len(plan["errors"]),
        })
        for key in totals:
            totals[key] += (len(plan[key]) if isinstance(plan.get(key), list)
                            else plan.get(key, 0))
        for c in plan["cfo"]:
            cfo_rows.setdefault(c["id"], c)
        errors.extend({**e, "filename": filename} for e in plan["errors"])
        unknown.extend(n for n in plan["unknown_cfo"] if n not in unknown)
        moved.extend({**m, "filename": filename} for m in plan["block_moved"])
    return {"year": year, "files": per_file, "cfo": list(cfo_rows.values()),
            "errors": errors[:20], "errors_count": len(errors),
            "moved": moved[:10], "unknown_cfo": unknown, **totals}


def import_fact_files(files: Sequence[tuple[str, bytes]], year: int, author: str,
                      cfo_ids: Iterable[int] | None = None,
                      only_cfo_ids: Iterable[int] | None = None) -> dict:
    """Заливает пачку файлов факта подряд, каждый своей загрузкой.

    Файлы приходят по одному на дирекцию, и грузить их по одному вручную —
    двенадцать заходов. Разбор у каждого свой: круг замены берётся из файла,
    поэтому порядок значения не имеет, а падение одного файла не отменяет
    остальные — он называется в ответе отдельно.
    """
    done, failed = [], []
    totals = {"matched": 0, "total": 0.0, "unlinked": 0, "unlinked_total": 0.0,
              "out_of_budget": 0, "out_of_budget_total": 0.0, "foreign": 0,
              "cleared": 0}
    for filename, content in files:
        try:
            result = import_fact(content, filename, year, author, cfo_ids, only_cfo_ids)
        except ValueError as exc:
            failed.append({"filename": filename, "error": str(exc)})
            continue
        done.append({"filename": filename, "matched": result["matched"],
                     "total": result["total"], "unlinked": result["unlinked"],
                     "out_of_budget": result["out_of_budget"]})
        for key in totals:
            totals[key] += result.get(key, 0)
    return {"year": year, "files": done, "failed": failed,
            "rows": totals["matched"], "unmatched": totals["unlinked"], **totals}


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
