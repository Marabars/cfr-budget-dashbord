"""Изменение данных: строки бюджета, заявки, факт, сопоставление, корректировки."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app import auth, calc, db, operplan, repo, service
from app.models import ClaimIn, FactIn, MatchIn, RowIn, RowPatch, TransferIn

router = APIRouter(prefix="/api", tags=["edit"])


def user(request: Request) -> auth.User:
    return auth.current_user(request)


def _money(value: float) -> str:
    return f"{value:,.2f} ₽".replace(",", " ")


# ---------- строки бюджета ----------

@router.post("/rows", status_code=201)
def create_row(payload: RowIn, u: auth.User = Depends(user)) -> dict:
    budget_id = payload.budget_id
    if not budget_id:
        if not payload.cfo_id:
            raise HTTPException(422, "Укажите бюджет или ЦФО")
        cfg = service.settings()
        budget_id = repo.ensure_budget(payload.cfo_id, cfg["year"], payload.budget_name)

    budget = db.query_one("SELECT cfo_id FROM budget WHERE id = ?", (budget_id,))
    if not budget:
        raise HTTPException(404, "Бюджет не найден")
    if not u.can_edit_cfo(int(budget["cfo_id"])):
        raise HTTPException(403, "Нет доступа к этому ЦФО")

    row_id = repo.create_row(
        budget_id, payload.model_dump(), months=payload.month_plan(),
        author=u.name, source="manual", row_no=repo.next_row_no(budget_id),
    )
    row = repo.get_row(row_id)
    db.log(u.name, "Новая строка бюджета",
           f"{row['cfo_name']} · {row['budget_name']} · {row['article']}",
           _money(payload.plan_year), "Ручное добавление в карточке ЦФО")
    return {"id": row_id, "row": row}


FIELD_NAMES = {
    "article": "статья", "counterparty": "контрагент", "contract": "договор",
    "detail": "детализация", "comment": "комментарий", "approver_comment": "комм наш",
    "plan_year": "бюджет года", "carryover": "перенос остатка",
}


def _describe(row: dict, changes: dict, months: list[float] | None) -> str:
    """Человекочитаемое «было → стало» для журнала изменений."""
    parts = []
    for field, value in changes.items():
        before, after = row.get(field), value
        if field == "plan_year":
            before, after = _money(float(before or 0)), _money(float(after or 0))
        if str(before) == str(after):
            continue
        parts.append(f"{FIELD_NAMES.get(field, field)}: {before or '—'} → {after or '—'}")
    if months is not None:
        parts.append("помесячная разбивка изменена")
    return "; ".join(parts) or "без изменений"


@router.patch("/rows/{row_id}")
def update_row(row_id: int, payload: RowPatch, u: auth.User = Depends(user)) -> dict:
    """Точечная правка строки из режима редактирования таблицы.

    Работает и для карточки ЦФО, и для Оперплана — в слое планирования
    дополнительно проверяется замок «внесение изменений заблокировано».
    """
    row = repo.get_row(row_id)
    if not row:
        raise HTTPException(404, "Строка не найдена")
    if row.get("layer") == operplan.LAYER:
        try:
            operplan.require_plan_year(int(row["year"]))
            operplan.require_edit(u, int(row["year"]), int(row["cfo_id"]))
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc
    elif not u.can_edit_cfo(int(row["cfo_id"])):
        raise HTTPException(403, "Нет доступа к этому ЦФО")

    changes = payload.changes()
    if not changes and payload.months is None:
        return {"ok": True, "row": row}

    repo.update_row(row_id, changes, months=payload.months)
    db.log(u.name, "Изменение строки бюджета",
           f"{row['cfo_name']} · №{row.get('row_no') or '-'} · {row['article']}",
           _describe(row, changes, payload.months))
    return {"ok": True, "row": repo.get_row(row_id)}


@router.delete("/rows/{row_id}")
def delete_row(row_id: int, reason: str = "", u: auth.User = Depends(user)) -> dict:
    row = repo.get_row(row_id)
    if not row:
        raise HTTPException(404, "Строка не найдена")
    if row.get("layer") == operplan.LAYER:
        try:
            operplan.require_plan_year(int(row["year"]))
            operplan.require_edit(u, int(row["year"]), int(row["cfo_id"]))
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc
    elif not u.can_edit_cfo(int(row["cfo_id"])):
        raise HTTPException(403, "Нет доступа к этому ЦФО")
    repo.delete_row(row_id)
    db.log(u.name, "Удаление строки",
           f"{row['cfo_name']} · №{row['row_no'] or '-'} · {row['article']}",
           f"{_money(row['plan_year'])} → строка удалена",
           reason or "Ручная правка в карточке ЦФО")
    return {"ok": True}


# ---------- факт ----------

@router.post("/facts", status_code=201)
def create_fact(payload: FactIn, u: auth.User = Depends(user)) -> dict:
    cfg = service.settings()
    cfo_id = payload.cfo_id
    row = repo.get_row(payload.row_id) if payload.row_id else None
    if row:
        cfo_id = int(row["cfo_id"])
    if not u.can_edit_cfo(cfo_id):
        raise HTTPException(403, "Нет доступа к этому ЦФО")

    warning = None
    if row:
        check = service.limit_check(int(row["id"]), payload.amount)
        if check.get("over_limit"):
            warning = (f"Расход превышает свободный лимит строки на "
                       f"{_money(check['excess'])} — сохранён с пометкой «сверх лимита»")

    fact_id = repo.create_fact(
        {**payload.model_dump(), "year": cfg["year"], "cfo_id": cfo_id}, u.name
    )
    db.log(u.name, "Вне бюджета" if payload.out_of_budget else "Ручной расход",
           f"{row['article'] if row else ''} · {payload.counterparty}".strip(" ·"),
           _money(payload.amount) + (f" ({payload.pay_date})" if payload.pay_date else ""),
           "Ручное добавление в карточке ЦФО")
    return {"id": fact_id, "warning": warning}


@router.delete("/facts/{fact_id}")
def delete_fact(fact_id: int, u: auth.User = Depends(user)) -> dict:
    f = repo.get_fact(fact_id)
    if not f:
        raise HTTPException(404, "Платёж не найден")
    if not u.can_edit_cfo(f["cfo_id"]):
        raise HTTPException(403, "Нет доступа к этому ЦФО")
    repo.delete_fact(fact_id)
    db.log(u.name, "Удаление расхода", f["counterparty"], _money(float(f["amount"])))
    return {"ok": True}


@router.post("/facts/{fact_id}/match")
def match_fact(fact_id: int, payload: MatchIn, u: auth.User = Depends(user)) -> dict:
    if not u.is_fin:
        raise HTTPException(403, "Сопоставление платежей ведёт финансовый отдел")
    f = repo.get_fact(fact_id)
    row = repo.get_row(payload.row_id)
    if not f or not row:
        raise HTTPException(404, "Платёж или строка не найдены")
    check = service.limit_check(payload.row_id, float(f["amount"]))
    repo.match_fact(fact_id, payload.row_id, u.name)
    db.log(u.name, "Сопоставление платежа",
           f"{f['counterparty']} → №{row['row_no'] or '-'} · {row['article']}",
           _money(float(f["amount"])) + (" · сверх лимита" if check.get("over_limit") else ""))
    return {"ok": True, "over_limit": check.get("over_limit", False)}


@router.post("/facts/{fact_id}/out-of-budget")
def flag_out_of_budget(fact_id: int, flag: bool = True, u: auth.User = Depends(user)) -> dict:
    f = repo.get_fact(fact_id)
    if not f:
        raise HTTPException(404, "Платёж не найден")
    if not u.can_edit_cfo(f["cfo_id"]) and not u.is_fin:
        raise HTTPException(403, "Нет доступа к этому ЦФО")
    repo.set_out_of_budget(fact_id, flag, u.name)
    db.log(u.name, "Признак «вне бюджета»", f["counterparty"],
           f"{'— → вне бюджета' if flag else 'вне бюджета → снят'} · {_money(float(f['amount']))}")
    return {"ok": True}


# ---------- заявки ----------

@router.post("/claims", status_code=201)
def create_claim(payload: ClaimIn, u: auth.User = Depends(user)) -> dict:
    if not u.can_edit_cfo(payload.cfo_id):
        raise HTTPException(403, "Нет доступа к этому ЦФО")
    cfg = service.settings()

    over_limit = False
    warning = None
    if payload.row_id:
        check = service.limit_check(payload.row_id, payload.amount)
        if not check.get("ok"):
            raise HTTPException(404, "Строка бюджета не найдена")
        over_limit = bool(check["over_limit"])
        if over_limit:
            warning = (f"Свободный лимит строки — {_money(check['free_limit'])}. "
                       f"Превышение {_money(check['excess'])}: заявка сохранена "
                       f"с пометкой «сверх лимита»")

    claim_id = repo.create_claim(
        {**payload.model_dump(), "year": cfg["year"], "over_limit": over_limit}, u.name
    )
    row = repo.get_row(payload.row_id) if payload.row_id else None
    db.log(u.name, "Новая заявка",
           f"{row['article'] if row else 'без строки бюджета'} · {payload.counterparty}",
           _money(payload.amount) + (" · сверх лимита" if over_limit else ""),
           payload.detail)
    return {"id": claim_id, "over_limit": over_limit, "warning": warning}


@router.delete("/claims/{claim_id}")
def delete_claim(claim_id: int, u: auth.User = Depends(user)) -> dict:
    claim = repo.get_claim(claim_id)
    if not claim:
        raise HTTPException(404, "Заявка не найдена")
    if not u.can_edit_cfo(int(claim["cfo_id"])):
        raise HTTPException(403, "Нет доступа к этому ЦФО")
    repo.delete_claim(claim_id)
    db.log(u.name, "Удаление заявки", claim["counterparty"], _money(float(claim["amount"])))
    return {"ok": True}


# ---------- перенос лимита ----------

@router.post("/adjustments")
def transfer(payload: TransferIn, u: auth.User = Depends(user)) -> dict:
    row = repo.get_row(payload.from_row_id)
    if not row:
        raise HTTPException(404, "Строка-источник не найдена")
    if not u.can_edit_cfo(int(row["cfo_id"])):
        raise HTTPException(403, "Нет доступа к этому ЦФО")
    try:
        return service.transfer_limit(
            kind=payload.kind, amount=payload.amount, reason=payload.reason, author=u.name,
            from_row_id=payload.from_row_id, to_row_id=payload.to_row_id,
            from_month=payload.from_month, to_month=payload.to_month,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/facts/auto-match")
def auto_match(year: int | None = None, u: auth.User = Depends(user)) -> dict:
    if not u.is_fin:
        raise HTTPException(403, "Доступно финансовому отделу")
    cfg = service.settings()
    return service.auto_match(year or cfg["year"], u.name)