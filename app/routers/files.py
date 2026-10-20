"""Импорт файлов Excel и экспорт отчётов."""
from __future__ import annotations

import json
from datetime import date
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app import auth, operplan, repo, service
from app.exporters import excel
from app.importers import (cfo_budgets, directorate, fact as fact_importer,
                           operplan as operplan_importer)

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


# ---------- предпросмотр перед импортом ----------

@router.post("/import/inspect")
async def inspect(kind: str = Form("plan"), file: UploadFile = File(...),
                  u: auth.User = Depends(user)) -> dict:
    """Разбирает файл и возвращает предложенное сопоставление колонок."""
    _require_fin(u)
    content = await _read(file)
    try:
        if kind == "fact":
            return {"kind": kind, "filename": file.filename, **fact_importer.inspect(content)}
        if kind == "cfo-budgets":
            parsed = cfo_budgets.parse(content)
            return {
                "kind": kind, "filename": file.filename, "sheet": parsed["sheet"],
                "sheets": parsed["sheets"], "header_row": parsed["header_row"],
                "columns": parsed["columns"], "blocks": len(parsed["blocks"]),
                "rows": len(parsed["rows"]),
                "total": sum(r["plan_year"] for r in parsed["rows"]),
                "mismatches": cfo_budgets.check_totals(parsed),
            }
        if kind == "cfo-articles":
            parsed = cfo_budgets.parse_articles(content)
            return {
                "kind": kind, "filename": file.filename, "sheet": parsed["sheet"],
                "sheets": parsed["sheets"], "header_row": parsed["header_row"],
                "pairs": len(parsed["pairs"]),
                "cfo": len({pair["cfo"] for pair in parsed["pairs"]}),
            }
        if kind == "operplan":
            parsed = operplan_importer.parse(content)
            return {
                "kind": kind, "filename": file.filename, "sheet": parsed["sheet"],
                "sheets": parsed["sheets"], "header_row": parsed["header_row"],
                "columns": parsed["columns"], "closed_through": parsed["closed_through"],
                "blocks": len(parsed["blocks"]), "rows": len(parsed["rows"]),
            }
        return {"kind": kind, "filename": file.filename, **directorate.inspect(content)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


# ---------- импорт ----------

@router.post("/import/operplan")
async def import_operplan(file: UploadFile = File(...), year: int = Form(...),
                          u: auth.User = Depends(user)) -> dict:
    _require_fin(u)
    content = await _read(file)
    try:
        return service.import_operplan(content, file.filename or "operplan.xlsx", year, u.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/import/cfo-budgets")
async def import_cfo_budgets(file: UploadFile = File(...), year: int = Form(...),
                             replace: bool = Form(True),
                             u: auth.User = Depends(user)) -> dict:
    """Лист «Бюджеты ЦФО» файла ликвидности → слой планирования вкладки «Оперплан».

    Слой исполнения (дашборд, сводка, карточка ЦФО, факт из 1С) не затрагивается.
    """
    _require_fin(u)
    content = await _read(file)
    try:
        return operplan.import_budgets(content, file.filename or "budgets.xlsx", year, u.name,
                                       replace=replace)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/import/cfo-articles")
async def import_cfo_articles(file: UploadFile = File(...),
                              u: auth.User = Depends(user)) -> dict:
    """Лист «ЦФО Статьи» — справочник статей для выпадающих списков."""
    _require_fin(u)
    content = await _read(file)
    try:
        return operplan.import_articles(content, file.filename or "articles.xlsx", u.name)
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


# ---------- экспорт ----------

@router.get("/export/operplan.xlsx")
def export_operplan(year: int | None = None, u: auth.User = Depends(user)) -> Response:
    cfg = service.settings()
    data = excel.operplan(year or cfg["year"], u.visible_cfo_ids())
    return _xlsx(data, f"Оперплан ЦФО {year or cfg['year']}.xlsx")


def _scope(cfo: str | None, u: auth.User) -> list[int] | None:
    """Круг дирекций выгрузки: отмеченные галочками, пересечённые с доступными.

    `cfo` — список id через запятую, как его шлёт форма. Пустой параметр значит
    «все доступные»: так выгрузка работала до появления галочек. Чужой id
    молча не отдаётся — пересечение, а не ошибка: круг и так режет сервер.
    """
    allowed = u.visible_cfo_ids()
    if not cfo:
        return allowed
    try:
        chosen = {int(part) for part in cfo.split(",") if part.strip()}
    except ValueError as exc:
        raise HTTPException(422, "Список дирекций — это id через запятую") from exc
    if not chosen:
        return allowed
    if allowed is None:
        return sorted(chosen)
    return sorted(chosen & set(allowed))


@router.get("/export/budget.xlsx")
def export_budget(year: int | None = None, cfo: str | None = None,
                  u: auth.User = Depends(user)) -> Response:
    """Бюджет слоя планирования листом «Бюджеты ЦФО» — тем же, каким его заливали.

    Руководителю выгружается только его дирекция. Файл можно поправить в Excel
    и вернуть обратно кнопкой «Загрузить из Excel». `cfo` сужает выгрузку до
    отмеченных галочками дирекций.
    """
    target = int(year or operplan.plan_year())
    data = excel.budget_sheet(target, _scope(cfo, u))
    return _xlsx(data, f"Бюджеты ЦФО {target}.xlsx")


@router.get("/export/budget-fact.xlsx")
def export_budget_fact(year: int | None = None, cfo: str | None = None,
                       u: auth.User = Depends(user)) -> Response:
    """Факт года листом «Бюджеты ЦФО» — выгрузка доступна и руководителю ЦФО.

    Смотреть свой факт вправе каждый, а загружать его — только финансовый
    отдел (`/api/operplan/import`, kind=fact). По умолчанию выгружается базовый
    год: план будущего года фактом ещё не наполняется.
    """
    target = int(year or operplan.base_year())
    data = excel.fact_sheet(target, _scope(cfo, u))
    return _xlsx(data, f"Факт ЦФО {target}.xlsx")


@router.get("/export/budget-template.xlsx")
def export_budget_template(year: int | None = None, cfo: str | None = None,
                           u: auth.User = Depends(user)) -> Response:
    """Пустой лист «Бюджеты ЦФО» под заполнение руками.

    Тот же вид, что у выгрузки плана, поэтому заполненный шаблон принимает та же
    загрузка. Руководителю в шаблон попадают только его дирекции, а галочками
    круг сужается дальше — чтобы не рассылать дирекции чужие блоки.
    """
    target = int(year or operplan.plan_year())
    data = excel.budget_template(target, _scope(cfo, u))
    return _xlsx(data, f"Бюджеты ЦФО {target} — шаблон.xlsx")


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