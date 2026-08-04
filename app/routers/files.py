"""Импорт файлов Excel и экспорт отчётов."""
from __future__ import annotations

import json
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app import auth, repo, service
from app.exporters import excel
from app.importers import directorate, fact as fact_importer, operplan

router = APIRouter(prefix="/api", tags=["files"])

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_UPLOAD_MB = 40


def user(request: Request) -> auth.User:
    return auth.current_user(request)


def _require_fin(u: auth.User) -> None:
    if not u.is_fin:
        raise HTTPException(403, "Загрузка и выгрузка файлов доступна финансовому отделу")


async def _read(file: UploadFile) -> bytes:
    content = await file.read()
    if not content:
        raise HTTPException(422, "Файл пустой")
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {MAX_UPLOAD_MB} МБ")
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(422, "Ожидается файл .xlsx")
    return content


def _xlsx(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


***REMOVED*** ---------- предпросмотр перед импортом ----------

@router.post("/import/inspect")
async def inspect(kind: str = Form("plan"), file: UploadFile = File(...),
                  u: auth.User = Depends(user)) -> dict:
    """Разбирает файл и возвращает предложенное сопоставление колонок."""
    _require_fin(u)
    content = await _read(file)
    try:
        if kind == "fact":
            return {"kind": kind, "filename": file.filename, **fact_importer.inspect(content)}
        if kind == "operplan":
            parsed = operplan.parse(content)
            return {
                "kind": kind, "filename": file.filename, "sheet": parsed["sheet"],
                "sheets": parsed["sheets"], "header_row": parsed["header_row"],
                "columns": parsed["columns"], "closed_through": parsed["closed_through"],
                "blocks": len(parsed["blocks"]), "rows": len(parsed["rows"]),
            }
        return {"kind": kind, "filename": file.filename, **directorate.inspect(content)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


***REMOVED*** ---------- импорт ----------

@router.post("/import/operplan")
async def import_operplan(file: UploadFile = File(...), year: int = Form(...),
                          u: auth.User = Depends(user)) -> dict:
    _require_fin(u)
    content = await _read(file)
    try:
        return service.import_operplan(content, file.filename or "operplan.xlsx", year, u.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/import/plan")
async def import_plan(file: UploadFile = File(...), year: int = Form(...),
                      cfo_name: str = Form(""), budget_name: str = Form("Основной бюджет"),
                      mapping: str = Form(""), u: auth.User = Depends(user)) -> dict:
    _require_fin(u)
    content = await _read(file)
    try:
        parsed_mapping = json.loads(mapping) if mapping else None
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Неверный формат сопоставления колонок") from exc
    try:
        return service.import_plan(content, file.filename or "plan.xlsx", year, u.name,
                                   cfo_name=cfo_name, budget_name=budget_name,
                                   mapping=parsed_mapping)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/import/fact")
async def import_fact(file: UploadFile = File(...), year: int = Form(...),
                      mapping: str = Form(""), auto: bool = Form(True),
                      u: auth.User = Depends(user)) -> dict:
    _require_fin(u)
    content = await _read(file)
    try:
        parsed_mapping = json.loads(mapping) if mapping else None
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "Неверный формат сопоставления колонок") from exc
    try:
        return service.import_fact(content, file.filename or "fact.xlsx", year, u.name,
                                   mapping=parsed_mapping, auto=auto)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


***REMOVED*** ---------- экспорт ----------

@router.get("/export/operplan.xlsx")
def export_operplan(year: int | None = None, u: auth.User = Depends(user)) -> Response:
    cfg = service.settings()
    data = excel.operplan(year or cfg["year"], u.visible_cfo_ids())
    return _xlsx(data, f"Оперплан ЦФО {year or cfg['year']}.xlsx")


@router.get("/export/summary.xlsx")
def export_summary(year: int | None = None, u: auth.User = Depends(user)) -> Response:
    cfg = service.settings()
    data = excel.summary(year or cfg["year"], u.visible_cfo_ids())
    return _xlsx(data, f"Сводка по ЦФО {year or cfg['year']}.xlsx")


@router.get("/export/cfo/{cfo_id}.xlsx")
def export_cfo(cfo_id: int, year: int | None = None, u: auth.User = Depends(user)) -> Response:
    if not u.is_fin and not u.can_edit_cfo(cfo_id):
        raise HTTPException(403, "Нет доступа к этому ЦФО")
    cfg = service.settings()
    cfo = next((c for c in repo.list_cfo() if int(c["id"]) == cfo_id), None)
    if not cfo:
        raise HTTPException(404, "ЦФО не найдено")
    data = excel.cfo_card(cfo_id, year or cfg["year"])
    return _xlsx(data, f"{cfo['name']} {year or cfg['year']}.xlsx")


@router.get("/export/out-of-budget.xlsx")
def export_out_of_budget(year: int | None = None, u: auth.User = Depends(user)) -> Response:
    _require_fin(u)
    cfg = service.settings()
    data = excel.out_of_budget(year or cfg["year"])
    return _xlsx(data, f"Вне бюджета {year or cfg['year']}.xlsx")