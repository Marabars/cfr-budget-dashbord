"""Справочник ЦФО: сведение дублей, переименование, алиасы. Только финотдел."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app import auth, registry, service
from app.models import AliasIn, MergeIn, RenameIn

router = APIRouter(prefix="/api/registry", tags=["registry"])


def user(request: Request) -> auth.User:
    return auth.current_user(request)


def require_fin(u: auth.User) -> None:
    if not u.is_fin:
        raise HTTPException(403, "Справочник ЦФО ведёт финансовый отдел")


@router.get("/cfo")
def cfo_registry(year: int | None = None, u: auth.User = Depends(user)) -> dict:
    require_fin(u)
    cfg = service.settings()
    target_year = year or cfg["year"]
    return {
        "year": target_year,
        "items": registry.stats(target_year),
        "suggestions": registry.suggestions(target_year),
    }


@router.get("/merge-preview")
def merge_preview(source_id: int, target_id: int, year: int | None = None,
                  u: auth.User = Depends(user)) -> dict:
    require_fin(u)
    cfg = service.settings()
    try:
        return registry.merge_preview(source_id, target_id, year or cfg["year"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/merge")
def merge(payload: MergeIn, u: auth.User = Depends(user)) -> dict:
    require_fin(u)
    try:
        return registry.merge(payload.source_id, payload.target_id, u.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/cfo/{cfo_id}")
def rename(cfo_id: int, payload: RenameIn, u: auth.User = Depends(user)) -> dict:
    require_fin(u)
    try:
        return registry.rename(cfo_id, payload.name, u.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/cfo/{cfo_id}/alias")
def add_alias(cfo_id: int, payload: AliasIn, u: auth.User = Depends(user)) -> dict:
    require_fin(u)
    try:
        return registry.add_alias(cfo_id, payload.alias, u.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/alias")
def delete_alias(alias: str, u: auth.User = Depends(user)) -> dict:
    require_fin(u)
    try:
        return registry.delete_alias(alias, u.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/cfo/{cfo_id}")
def delete_empty(cfo_id: int, u: auth.User = Depends(user)) -> dict:
    require_fin(u)
    try:
        return registry.delete_empty(cfo_id, u.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
