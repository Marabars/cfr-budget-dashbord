"""Бизнес-логика: сборка представлений, проверка лимитов, перенос лимита, импорт."""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Iterable, Sequence

from app import calc, db, repo
from app.importers import directorate, fact as fact_importer, operplan


***REMOVED*** ---------- параметры периода ----------

def settings() -> dict:
    year = int(db.get_setting("year", "2026"))
    closed = int(db.get_setting("closed_through", "0"))
    as_of_raw = db.get_setting("as_of", "")
    as_of = as_of_raw or date.today().isoformat()
    warning_pp = float(db.get_setting("pace_warning_pp", "15")) / 100
    day_share = 0.0
    current_month = 0
    try:
        as_of_date = date.fromisoformat(as_of)
        if as_of_date.year == year:
            current_month = as_of_date.month
            day_share = calc.day_share_of(as_of_date)
    except ValueError:
        pass
    return {
        "year": year,
        "closed_through": closed,
        "as_of": as_of,
        "current_month": current_month,
        "day_share": day_share,
        "pace": calc.pace(closed, day_share if current_month == closed + 1 else 0.0),
        "warning_pp": warning_pp,
    }


***REMOVED*** ---------- сборка представлений ----------

def _row_view(row: dict, plan_m: list[float], fact_m: list[float], claim_m: list[float]) -> dict:
    t = calc.totals(row["plan_year"], fact_m, claim_m)
    spent = [fact_m[i] + claim_m[i] for i in range(calc.MONTHS)]
    limits = calc.monthly_limits(plan_m, spent, carryover=bool(row.get("carryover", 1)))
    return {
        "id": row["id"],
        "row_no": row.get("row_no"),
        "budget_id": row["budget_id"],
        "budget_name": row.get("budget_name", ""),
        "cfo_id": row.get("cfo_id"),
        "cfo_name": row.get("cfo_name", ""),
        "article": row["article"],
        "counterparty": row["counterparty"],
        "contract": row["contract"],
        "detail": row["detail"],
        "comment": row["comment"],
        "approver_comment": row["approver_comment"],
        "source": row.get("source", ""),
        "carryover": bool(row.get("carryover", 1)),
        "plan_year": t["plan_year"],
        "plan_months": plan_m,
        "fact": t["fact"],
        "fact_months": fact_m,
        "claims": t["claims"],
        "claim_months": claim_m,
        "operplan": t["operplan"],
        "cash_remain": t["cash_remain"],
        "free_limit": t["free_limit"],
        "pct": t["pct"],
        "limit_months": limits["limit"],
        "over_months": limits["over"],
        "carry_months": limits["carry"],
    }


def year_view(year: int | None = None, cfo_ids: Iterable[int] | None = None) -> dict:
    """Полное представление года: бюджеты с итогами и строки с расчётами."""
    cfg = settings()
    year = year or cfg["year"]
    allowed = set(int(i) for i in (cfo_ids or []))

    rows = repo.list_rows(year)
    plan_all = repo.plan_months(year)
    fact_all = repo.fact_months(year)
    claim_all = repo.claim_months(year)

    budgets: dict[int, dict] = {}
    for b in repo.list_budgets(year):
        if allowed and int(b["cfo_id"]) not in allowed:
            continue
        budgets[int(b["id"])] = {
            "id": int(b["id"]),
            "name": b["name"],
            "cfo_id": int(b["cfo_id"]),
            "cfo_name": b["cfo_name"],
            "rows": [],
        }

    for row in rows:
        bid = int(row["budget_id"])
        if bid not in budgets:
            continue
        rid = int(row["id"])
        view = _row_view(
            row,
            plan_all.get(rid, [0.0] * calc.MONTHS),
            fact_all.get(rid, [0.0] * calc.MONTHS),
            claim_all.get(rid, [0.0] * calc.MONTHS),
        )
        budgets[bid]["rows"].append(view)

    oob = repo.list_out_of_budget(year)
    oob_by_cfo: dict[int, float] = {}
    for f in oob:
        if f["cfo_id"]:
            oob_by_cfo[int(f["cfo_id"])] = oob_by_cfo.get(int(f["cfo_id"]), 0.0) + float(f["amount"])

    blocks = []
    for b in budgets.values():
        totals = calc.aggregate(b["rows"]) if b["rows"] else calc.totals(0, [], [])
        status = calc.status(totals, cfg["pace"], cfg["warning_pp"])
        blocks.append({
            **{k: v for k, v in b.items() if k != "rows"},
            "rows_count": len(b["rows"]),
            "totals": totals,
            "status": status[0],
            "status_text": status[1],
            "out_of_budget": oob_by_cfo.get(b["cfo_id"], 0.0),
        })

    return {
        "settings": cfg,
        "blocks": sorted(blocks, key=lambda x: -x["totals"]["plan_year"]),
        "budgets": budgets,
        "out_of_budget_total": sum(float(f["amount"]) for f in oob),
        "out_of_budget_count": len(oob),
    }


def dashboard(year: int | None = None, cfo_ids: Iterable[int] | None = None) -> dict:
    """Карточки ЦФО и ключевые показатели."""
    view = year_view(year, cfo_ids)
    blocks = view["blocks"]
    total = {
        "plan_year": sum(b["totals"]["plan_year"] for b in blocks),
        "fact": sum(b["totals"]["fact"] for b in blocks),
        "claims": sum(b["totals"]["claims"] for b in blocks),
    }
    total["operplan"] = total["fact"] + total["claims"]
    total["free_limit"] = total["plan_year"] - total["operplan"]
    total["cash_remain"] = total["plan_year"] - total["fact"]
    total["pct"] = (total["fact"] / total["plan_year"]) if total["plan_year"] else 0.0
    return {
        "settings": view["settings"],
        "cards": blocks,
        "totals": total,
        "out_of_budget_total": view["out_of_budget_total"],
        "out_of_budget_count": view["out_of_budget_count"],
        "over_count": sum(1 for b in blocks if b["status"] in ("critical", "serious")),
        "unmatched_count": len(repo.list_unmatched(view["settings"]["year"], limit=1000)),
    }


def cfo_card(cfo_id: int, year: int | None = None) -> dict:
    """Карточка ЦФО: бюджеты, строки и привязанные к ним платежи."""
    view = year_view(year, [cfo_id])
    budgets = [b for b in view["budgets"].values() if b["cfo_id"] == cfo_id]
    for b in budgets:
        for row in b["rows"]:
            row["facts"] = repo.list_facts_by_row(row["id"])
        b["totals"] = calc.aggregate(b["rows"]) if b["rows"] else calc.totals(0, [], [])
    cfo = next((c for c in repo.list_cfo() if int(c["id"]) == cfo_id), None)
    return {
        "settings": view["settings"],
        "cfo": cfo,
        "budgets": budgets,
        "totals": calc.aggregate([r for b in budgets for r in b["rows"]])
        if any(b["rows"] for b in budgets) else calc.totals(0, [], []),
    }


def heatmap(year: int | None = None, cfo_ids: Iterable[int] | None = None) -> dict:
    """Отклонение факта от плана по месяцам для каждого бюджета."""
    view = year_view(year, cfo_ids)
    cfg = view["settings"]
    rows = []
    for b in view["blocks"]:
        budget = view["budgets"][b["id"]]
        plan_m = [0.0] * calc.MONTHS
        fact_m = [0.0] * calc.MONTHS
        for row in budget["rows"]:
            for m in range(calc.MONTHS):
                plan_m[m] += row["plan_months"][m]
                fact_m[m] += row["fact_months"][m]
        cells = []
        for m in range(calc.MONTHS):
            closed = (m + 1) <= cfg["closed_through"]
            dev = ((fact_m[m] - plan_m[m]) / plan_m[m]) if plan_m[m] else None
            cells.append({
                "month": m + 1, "closed": closed,
                "plan": plan_m[m], "fact": fact_m[m],
                "deviation": dev if closed else None,
            })
        rows.append({
            "budget_id": b["id"], "cfo_name": b["cfo_name"], "budget_name": b["name"],
            "cells": cells,
        })
    return {"settings": cfg, "rows": rows}


***REMOVED*** ---------- проверка лимита ----------

def limit_check(row_id: int, amount: float) -> dict:
    """Свободный лимит строки и не превышает ли его новая сумма.

    Лимиты жёсткие по смыслу, но система предупреждает и пропускает —
    заявка сохраняется с признаком «сверх лимита».
    """
    cfg = settings()
    row = repo.get_row(row_id)
    if not row:
        return {"ok": False, "error": "Строка бюджета не найдена"}
    year = int(row["year"])
    fact_m = repo.fact_months(year).get(row_id, [0.0] * calc.MONTHS)
    claim_m = repo.claim_months(year).get(row_id, [0.0] * calc.MONTHS)
    t = calc.totals(row["plan_year"], fact_m, claim_m)
    free = t["free_limit"]
    return {
        "ok": True,
        "row_id": row_id,
        "plan_year": t["plan_year"],
        "fact": t["fact"],
        "claims": t["claims"],
        "free_limit": free,
        "over_limit": amount > free,
        "excess": max(0.0, amount - free),
    }


***REMOVED*** ---------- перенос лимита ----------

def transfer_limit(kind: str, amount: float, reason: str, author: str,
                   from_row_id: int, to_row_id: int | None = None,
                   from_month: int | None = None, to_month: int | None = None) -> dict:
    """Перенос лимита: между месяцами внутри строки или между строками одного ЦФО."""
    if amount <= 0:
        raise ValueError("Сумма переноса должна быть больше нуля")
    if not reason.strip():
        raise ValueError("Обоснование обязательно")

    src = repo.get_row(from_row_id)
    if not src:
        raise ValueError("Строка-источник не найдена")

    if kind == "month":
        if not from_month or not to_month or from_month == to_month:
            raise ValueError("Укажите разные месяцы")
        available = repo.month_amount(from_row_id, from_month)
        if amount > available:
            raise ValueError(f"В месяце {from_month} запланировано только {available:.2f} ₽")
        repo.set_month_amount(from_row_id, from_month, available - amount)
        repo.set_month_amount(from_row_id, to_month,
                              repo.month_amount(from_row_id, to_month) + amount)
        change = (f"{calc.MONTH_NAMES[from_month - 1]} −{amount:.2f} → "
                  f"{calc.MONTH_NAMES[to_month - 1]} +{amount:.2f}")
        obj = f"{src['cfo_name']} · №{src.get('row_no') or '-'} · {src['article']}"
    elif kind == "row":
        dst = repo.get_row(to_row_id) if to_row_id else None
        if not dst:
            raise ValueError("Строка-получатель не найдена")
        if dst["cfo_id"] != src["cfo_id"]:
            raise ValueError("Перенос между разными ЦФО запрещён")
        if amount > src["plan_year"]:
            raise ValueError("Сумма больше годового лимита строки-источника")
        repo.update_row(from_row_id, {"plan_year": src["plan_year"] - amount})
        repo.update_row(to_row_id, {"plan_year": dst["plan_year"] + amount})
        change = (f"№{src.get('row_no') or '-'} −{amount:.2f} → "
                  f"№{dst.get('row_no') or '-'} +{amount:.2f}")
        obj = f"{src['cfo_name']} · {src['article']} → {dst['article']}"
    else:
        raise ValueError("Неизвестный вид корректировки")

    repo.create_adjustment({
        "kind": kind, "year": src["year"], "cfo_id": src["cfo_id"],
        "from_row_id": from_row_id, "to_row_id": to_row_id,
        "from_month": from_month, "to_month": to_month,
        "amount": amount, "reason": reason,
    }, author)
    db.log(author, "Перенос лимита" if kind == "month" else "Перенос между строками",
           obj, change, reason)
    return {"ok": True, "change": change}


***REMOVED*** ---------- сопоставление факта ----------

def match_candidates(fact_id: int, limit: int = 8) -> list[dict]:
    """Кандидаты для привязки платежа: по договору, статье и контрагенту."""
    f = repo.get_fact(fact_id)
    if not f:
        return []
    year = int(f["year"])
    rows = repo.list_rows(year)
    fact_m = repo.fact_months(year)
    claim_m = repo.claim_months(year)

    def score(row: dict) -> tuple[int, list[str]]:
        points, why = 0, []
        if f["contract"] and row["contract"] and f["contract"].lower() in row["contract"].lower():
            points += 4
            why.append("договор")
        if f["article"] and row["article"] and _article_key(f["article"]) == _article_key(row["article"]):
            points += 3
            why.append("статья")
        if f["counterparty"] and row["counterparty"] and \
                f["counterparty"].lower()[:12] == row["counterparty"].lower()[:12]:
            points += 2
            why.append("контрагент")
        if f["cfo_id"] and row["cfo_id"] == f["cfo_id"]:
            points += 1
            why.append("ЦФО")
        return points, why

    scored = []
    for row in rows:
        points, why = score(row)
        if points <= 0:
            continue
        rid = int(row["id"])
        t = calc.totals(row["plan_year"], fact_m.get(rid, []), claim_m.get(rid, []))
        scored.append({
            "row_id": rid,
            "row_no": row.get("row_no"),
            "article": row["article"],
            "detail": row["detail"],
            "cfo_name": row["cfo_name"],
            "budget_name": row["budget_name"],
            "free_limit": t["free_limit"],
            "enough": t["free_limit"] >= float(f["amount"]),
            "score": points,
            "matched_by": " + ".join(why),
        })
    scored.sort(key=lambda x: (-x["score"], -x["free_limit"]))
    return scored[:limit]


def _article_key(article: str) -> str:
    """Код статьи до подчёркивания: «4420_Расходы на ПО» -> «4420»."""
    return (article or "").split("_", 1)[0].strip().lower()


def auto_match(year: int, author: str = "auto") -> dict:
    """Автопривязка платежей: по номеру заявки, затем по договору + статье."""
    matched = 0
    for f in repo.list_unmatched(year, limit=1000):
        row_id = None
        if f["claim_number"]:
            claim = db.query_one(
                "SELECT row_id FROM claim WHERE year = ? AND number_1c = ? AND row_id IS NOT NULL",
                (year, f["claim_number"]),
            )
            if claim:
                row_id = int(claim["row_id"])
        if row_id is None:
            candidates = match_candidates(int(f["id"]), limit=2)
            if candidates and candidates[0]["score"] >= 7:
                row_id = candidates[0]["row_id"]
        if row_id:
            repo.match_fact(int(f["id"]), row_id, author)
            matched += 1
    return {"matched": matched}


***REMOVED*** ---------- импорт ----------

def import_operplan(content: bytes, filename: str, year: int, author: str,
                    set_closed_through: bool = True) -> dict:
    """Первичная загрузка листа «Оперплан ЦФО»: план, факт и заявки за год."""
    parsed = operplan.parse(content)
    closed = parsed["closed_through"]
    cfg = settings()
    current_month = cfg["current_month"]

    created_rows = created_facts = created_claims = 0
    row_index: dict[tuple[int, int], int] = {}   ***REMOVED*** (budget_id, row_no) -> row_id

    for row in parsed["rows"]:
        cfo_id = repo.ensure_cfo(row["cfo"])
        budget_id = repo.ensure_budget(cfo_id, year, row["budget"])
        months = row["months"]
        fact_m, claim_m = calc.split_fact_and_claims(
            months, closed, current_month, fact_share=cfg["day_share"]
        )

        if not row["is_child"]:
            row_id = repo.create_row(
                budget_id,
                {
                    "article": row["article"],
                    "counterparty": row["counterparty"],
                    "contract": row["contract"],
                    "detail": row["detail"],
                    "comment": row["comment"],
                    "approver_comment": row["approver_comment"],
                    "plan_year": row["plan_year"],
                },
                months=months,          ***REMOVED*** месяцы листа = план по месяцам
                author=author,
                source="import",
                row_no=row["row_no"],
            )
            created_rows += 1
            if row["row_no"]:
                row_index[(budget_id, int(row["row_no"]))] = row_id
        else:
            parent = row_index.get((budget_id, int(row["parent_no"] or 0)))
            row_id = parent

        for m in range(calc.MONTHS):
            if fact_m[m]:
                repo.create_fact({
                    "row_id": row_id, "cfo_id": cfo_id, "year": year,
                    "pay_date": f"{year}-{m + 1:02d}-15",
                    "amount": fact_m[m], "article": row["article"],
                    "counterparty": row["counterparty"], "contract": row["contract"],
                    "purpose": row["detail"] or row["comment"], "source": "operplan",
                    "external_id": f"op:{filename}:{row['excel_row']}:f{m + 1}",
                }, author)
                created_facts += 1
            if claim_m[m] and row_id:
                repo.create_claim({
                    "row_id": row_id, "cfo_id": cfo_id, "year": year,
                    "pay_date": f"{year}-{m + 1:02d}-15", "amount": claim_m[m],
                    "counterparty": row["counterparty"], "contract": row["contract"],
                    "detail": row["detail"] or row["comment"],
                }, author)
                created_claims += 1

    if set_closed_through and closed:
        db.set_setting("closed_through", str(closed))
    db.set_setting("year", str(year))

    repo.create_import("operplan", filename, year, author, created_rows, 0,
                       note=f"строк: {created_rows}, факт: {created_facts}, заявки: {created_claims}")
    db.log(author, "Импорт «Оперплан ЦФО»", filename,
           f"строк: {created_rows}, платежей: {created_facts}, заявок: {created_claims}",
           "Первичная загрузка года")
    return {
        "rows": created_rows, "facts": created_facts, "claims": created_claims,
        "closed_through": closed, "blocks": len(parsed["blocks"]),
    }


def import_plan(content: bytes, filename: str, year: int, author: str,
                cfo_name: str = "", budget_name: str = "Основной бюджет",
                mapping: dict | None = None, replace: bool = False) -> dict:
    """Загрузка плана из файла дирекции."""
    parsed = directorate.parse(content, mapping=mapping, budget_name=budget_name, cfo_name=cfo_name)
    mismatches = directorate.check_totals(parsed)
    created = 0
    for row in parsed["rows"]:
        cfo_id = repo.ensure_cfo(row["cfo"] or cfo_name)
        budget_id = repo.ensure_budget(cfo_id, year, row["budget"])
        repo.create_row(budget_id, row, months=row["months"], author=author,
                        source="import", row_no=repo.next_row_no(budget_id))
        created += 1
    if mapping:
        cfo_id = repo.ensure_cfo(cfo_name) if cfo_name else None
        if cfo_id:
            repo.save_column_mapping(cfo_id, json.dumps(mapping, ensure_ascii=False))
    repo.create_import("plan", filename, year, author, created, len(mismatches),
                       mapping=json.dumps(parsed["mapping"], ensure_ascii=False))
    db.log(author, "Импорт плана дирекции", filename,
           f"строк: {created}", f"{cfo_name} · {budget_name}")
    return {"rows": created, "mismatches": mismatches, "mapping": parsed["mapping"]}


def import_fact(content: bytes, filename: str, year: int, author: str,
                mapping: dict | None = None, auto: bool = True) -> dict:
    """Загрузка выгрузки платежей: дубли по ключу пропускаются."""
    parsed = fact_importer.parse(content, mapping=mapping, filename=filename)
    created = skipped = 0
    for row in parsed["rows"]:
        if repo.fact_exists(row["external_id"]):
            skipped += 1
            continue
        cfo_id = repo.ensure_cfo(row["cfo"]) if row["cfo"] else None
        repo.create_fact({**row, "year": year, "cfo_id": cfo_id, "source": "1c"}, author)
        created += 1
    result = {"created": created, "skipped": skipped}
    if auto:
        result.update(auto_match(year, author))
    repo.create_import("fact", filename, year, author, created, 0,
                       note=f"пропущено дублей: {skipped}")
    db.log(author, "Импорт факта", filename,
           f"платежей: {created}, дублей: {skipped}, "
           f"сопоставлено автоматически: {result.get('matched', 0)}", "")
    return result