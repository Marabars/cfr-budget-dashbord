"""Только чтение: дашборд, сводка, карточка ЦФО, тепловая карта, журнал."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app import auth, db, repo, service
from app.models import SettingsIn

router = APIRouter(prefix="/api", tags=["views"])


def user(request: Request) -> auth.User:
    return auth.current_user(request)


@router.get("/me")
def me(u: auth.User = Depends(user)) -> dict:
    return {
        "login": u.login, "name": u.name, "role": u.role,
        "cfo_ids": u.cfo_ids, "is_fin": u.is_fin,
    }


@router.get("/settings")
def get_settings() -> dict:
    return service.settings()


@router.put("/settings")
def put_settings(payload: SettingsIn, u: auth.User = Depends(user)) -> dict:
    if not u.is_fin:
        raise HTTPException(403, "Настройки периода меняет финансовый отдел")
    for key in ("year", "closed_through", "as_of", "pace_warning_pp"):
        value = getattr(payload, key)
        if value is not None:
            db.set_setting(key, str(value))
    db.log(u.name, "Изменение настроек периода", "", str(payload.model_dump(exclude_none=True)))
    return service.settings()


@router.get("/dashboard")
def dashboard(year: int | None = None, u: auth.User = Depends(user)) -> dict:
    return service.dashboard(year, u.visible_cfo_ids())


@router.get("/cfo")
def cfo_list(u: auth.User = Depends(user)) -> list[dict]:
    allowed = u.visible_cfo_ids()
    items = repo.list_cfo()
    if allowed is not None:
        items = [c for c in items if int(c["id"]) in allowed]
    return items


@router.get("/cfo/{cfo_id}")
def cfo_card(cfo_id: int, year: int | None = None, u: auth.User = Depends(user)) -> dict:
    if not u.can_edit_cfo(cfo_id) and not u.is_fin:
        raise HTTPException(403, "Нет доступа к этому ЦФО")
    card = service.cfo_card(cfo_id, year)
    if not card["cfo"]:
        raise HTTPException(404, "ЦФО не найдено")
    return card


@router.get("/heatmap")
def heatmap(year: int | None = None, u: auth.User = Depends(user)) -> dict:
    return service.heatmap(year, u.visible_cfo_ids())


@router.get("/claims")
def claims(year: int | None = None, u: auth.User = Depends(user)) -> list[dict]:
    cfg = service.settings()
    return repo.list_claims(year or cfg["year"], u.visible_cfo_ids())


@router.get("/facts/unmatched")
def unmatched(year: int | None = None, u: auth.User = Depends(user)) -> list[dict]:
    if not u.is_fin:
        raise HTTPException(403, "Сопоставление платежей ведёт финансовый отдел")
    cfg = service.settings()
    return repo.list_unmatched(year or cfg["year"])


@router.get("/facts/{fact_id}/candidates")
def candidates(fact_id: int, u: auth.User = Depends(user)) -> list[dict]:
    if not u.is_fin:
        raise HTTPException(403, "Сопоставление платежей ведёт финансовый отдел")
    return service.match_candidates(fact_id)


@router.get("/out-of-budget")
def out_of_budget(year: int | None = None, u: auth.User = Depends(user)) -> list[dict]:
    cfg = service.settings()
    items = repo.list_out_of_budget(year or cfg["year"])
    allowed = u.visible_cfo_ids()
    if allowed is not None:
        items = [f for f in items if f["cfo_id"] and int(f["cfo_id"]) in allowed]
    return items


@router.get("/audit")
def audit(limit: int = 100) -> list[dict]:
    return repo.list_audit(limit)


@router.get("/imports")
def imports(limit: int = 50) -> list[dict]:
    return repo.list_imports(limit)


@router.get("/rows/{row_id}/limit")
def row_limit(row_id: int, amount: float = 0) -> dict:
    result = service.limit_check(row_id, amount)
    if not result.get("ok"):
        raise HTTPException(404, result.get("error", "Строка не найдена"))
    return result