"""Вкладка «Оперплан»: план следующего года, справочники, замок, повтор года."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app import auth, db, operplan, repo
from app.models import CopyYearIn, LockIn, OperplanRowIn

router = APIRouter(prefix="/api/operplan", tags=["operplan"])


def user(request: Request) -> auth.User:
    return auth.current_user(request)


def _money(value: float) -> str:
    return f"{value:,.2f} ₽".replace(",", " ")


@router.get("")
def overview(year: int | None = None, u: auth.User = Depends(user)) -> dict:
    data = operplan.view(year, u.visible_cfo_ids())
    data["can_edit"] = operplan.can_edit(u, data["year"])
    data["is_fin"] = u.is_fin
    return data


@router.get("/missing")
def missing(year: int | None = None, u: auth.User = Depends(user)) -> dict:
    return operplan.missing_rows(year, u.visible_cfo_ids())


@router.get("/references")
def references(year: int | None = None, u: auth.User = Depends(user)) -> dict:
    return operplan.references(year, u.visible_cfo_ids())


@router.post("/lock")
def lock(payload: LockIn, u: auth.User = Depends(user)) -> dict:
    if not u.is_fin:
        raise HTTPException(403, "Блокировку снимает и ставит финансовый отдел")
    return operplan.set_lock(int(payload.year or operplan.plan_year()), payload.locked, u.name)


@router.post("/copy-year")
def copy_year(payload: CopyYearIn, u: auth.User = Depends(user)) -> dict:
    year = int(payload.to_year or operplan.plan_year())
    try:
        operplan.require_edit(u, year, payload.cfo_id)
        return operplan.copy_year(u.name, from_year=payload.from_year, to_year=payload.to_year,
                                  index_pct=payload.index_pct, cfo_id=payload.cfo_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/missing/{row_id}/add", status_code=201)
def add_missing(row_id: int, year: int | None = None, u: auth.User = Depends(user)) -> dict:
    row = repo.get_row(row_id)
    if not row:
        raise HTTPException(404, "Строка не найдена")
    target = int(year or operplan.plan_year())
    try:
        operplan.require_edit(u, target, int(row["cfo_id"]))
        return operplan.add_missing(row_id, u.name, target)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/rows", status_code=201)
def create_row(payload: OperplanRowIn, year: int | None = None,
               u: auth.User = Depends(user)) -> dict:
    target = int(year or operplan.plan_year())
    try:
        operplan.require_edit(u, target, payload.cfo_id)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc

    months = payload.month_plan()
    plan = round(sum(months), 2) if any(months) else float(payload.plan_year)
    budget_id = repo.ensure_budget(payload.cfo_id, target, payload.budget_name,
                                   layer=operplan.LAYER)
    row_id = repo.create_row(
        budget_id,
        {**payload.model_dump(), "plan_year": plan},
        months=months,
        author=u.name,
        source="manual",
        row_no=repo.next_row_no(budget_id),
    )
    row = repo.get_row(row_id)
    db.log(u.name, "Новая строка плана",
           f"{row['cfo_name']} · {row['budget_name']} · {payload.article}",
           _money(plan), f"Оперплан {target}")
    return {"id": row_id}
