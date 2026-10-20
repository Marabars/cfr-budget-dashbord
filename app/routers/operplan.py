"""Вкладка «Оперплан»: план следующего года, справочники, замок, повтор года."""
from __future__ import annotations

from typing import Sequence

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app import auth, db, operplan, repo
from app.exporters import excel
from app.models import (CopyYearIn, FactLinkIn, LockIn, OperplanRowIn,
                        RowsDeleteIn, YearIn)

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_UPLOAD_MB = 40
# Файлы факта приходят по одному на дирекцию, их дюжина; потолок
# с запасом, чтобы случайно выбранная папка не ушла целиком.
MAX_UPLOAD_FILES = 30

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


@router.post("/fact-link")
def fact_link(payload: FactLinkIn, u: auth.User = Depends(user)) -> dict:
    """«В бюджете, за счёт строки N» или «Вне бюджета» для расхода.

    Правит только финотдел — как и грузит факт (решение 12.10.2026):
    перенос расхода меняет план-факт чужой строки, и делать это должен тот,
    кто отвечает за бюджет целиком.
    """
    if not u.is_fin:
        raise HTTPException(403, "Наличие в бюджете меняет финансовый отдел")
    year = int(payload.year or operplan.base_year())
    try:
        return operplan.set_fact_link(
            year, int(payload.cfo_id),
            {"article": payload.article, "counterparty": payload.counterparty,
             "contract": payload.contract, "detail": payload.detail},
            payload.row_id, u.name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/copy-year")
def copy_year(payload: CopyYearIn, u: auth.User = Depends(user)) -> dict:
    """Перенос прошлого года в план — только по доступным пользователю ЦФО.

    Руководитель повторяет бюджет своей дирекции и не задевает чужие: круг ЦФО
    задаёт сервер, а не клиент.
    """
    year = int(payload.to_year or operplan.plan_year())
    allowed = u.visible_cfo_ids()
    if payload.cfo_id is not None:
        if allowed is not None and int(payload.cfo_id) not in allowed:
            raise HTTPException(403, "Нет доступа к этому ЦФО")
        allowed = [int(payload.cfo_id)]
    try:
        operplan.require_edit(u, year, payload.cfo_id)
        return operplan.copy_year(u.name, from_year=payload.from_year, to_year=payload.to_year,
                                  index_pct=payload.index_pct, cfo_ids=allowed,
                                  source=payload.source)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/renumber")
def renumber(payload: YearIn, u: auth.User = Depends(user)) -> dict:
    """Закрепить нумерацию строк — кнопка «Сохранить» на вкладке.

    Круг ЦФО задаёт сервер: руководитель переставит номера только в своих
    блоках, чужие останутся как были.
    """
    year = int(payload.year or operplan.plan_year())
    try:
        operplan.require_plan_year(year)
        operplan.require_edit(u, year)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    return operplan.renumber(year, u.name, u.visible_cfo_ids())


# ---------- Excel ----------

async def _upload(file: UploadFile, kind: str, year: int, u: auth.User) -> bytes:
    """Общие проверки загрузки: предпросмотр и запись должны сходиться в них."""
    content = await file.read()
    if not content:
        raise HTTPException(422, f"Файл пустой: {file.filename or ''}".strip())
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {MAX_UPLOAD_MB} МБ: {file.filename}")
    if not (file.filename or "").lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(422, f"Ожидается файл .xlsx: {file.filename}")
    if kind not in ("plan", "fact"):
        raise HTTPException(422, "Загружать можно бюджет или факт")
    # Кнопку руководителю не рисуют, но запрет держит сервер: роль приезжает
    # заголовком, и форму можно отправить мимо интерфейса.
    if kind == "fact" and not u.is_fin:
        raise HTTPException(403, "Факт загружает финансовый отдел")
    try:
        operplan.require_edit(u, int(year))
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc
    return content


async def _uploads(files: Sequence[UploadFile], kind: str, year: int,
                   u: auth.User) -> list[tuple[str, bytes]]:
    """Пачка файлов: проверяется каждый, иначе один битый уронил бы всю загрузку."""
    if not files:
        raise HTTPException(422, "Не выбран ни один файл")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(413, f"За раз можно загрузить не больше {MAX_UPLOAD_FILES} файлов")
    out = []
    for file in files:
        out.append(((file.filename or "budget.xlsx"),
                    await _upload(file, kind, year, u)))
    return out


def _chosen_cfo(cfo_ids: Sequence[int] | None, u: auth.User) -> list[int] | None:
    """Отмеченные галочками дирекции, если они доступны пользователю.

    Пустой список значит «как в файле»: круг берётся из самих файлов.
    """
    if not cfo_ids:
        return None
    chosen = []
    for cfo_id in cfo_ids:
        if not u.is_fin and not u.can_edit_cfo(int(cfo_id)):
            raise HTTPException(403, "Нет доступа к этому ЦФО")
        chosen.append(int(cfo_id))
    return chosen


@router.post("/import/preview")
async def import_preview(files: list[UploadFile] = File(...), year: int = Form(...),
                         kind: str = Form("fact"),
                         cfo_ids: list[int] = Form(default=[]),
                         u: auth.User = Depends(user)) -> dict:
    """Что сделает загрузка факта — до того, как она что-то сделает.

    Разбор здесь тот же самый, что и при записи, поэтому показанное на экране
    и записанное в базу разойтись не могут. Файлов может быть несколько: они
    приходят по одному на дирекцию.
    """
    if kind != "fact":
        raise HTTPException(422, "Предпросмотр есть только у загрузки факта")
    payload = await _uploads(files, kind, int(year), u)
    try:
        return operplan.preview_fact_files(payload, int(year), u.visible_cfo_ids(),
                                           _chosen_cfo(cfo_ids, u))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/import")
async def import_sheet(files: list[UploadFile] = File(...), year: int = Form(...),
                       kind: str = Form("plan"),
                       cfo_ids: list[int] = Form(default=[]),
                       u: auth.User = Depends(user)) -> dict:
    """Загрузка бюджета или факта года листом того же вида, что и выгрузка.

    Круг ЦФО задаёт сервер: руководитель перезальёт только свою дирекцию,
    чужие строки файла будут пропущены. Факт грузит только финансовый отдел —
    дирекция свой факт выгружает (`/api/export/budget-fact.xlsx`), но не правит.
    Факт можно сузить галочками до нескольких дирекций (`cfo_ids`) и залить
    пачкой файлов: они приходят по одному на дирекцию.
    """
    payload = await _uploads(files, kind, int(year), u)
    target = int(year)
    try:
        if kind == "fact":
            result = operplan.import_fact_files(payload, target, u.name,
                                                cfo_ids=u.visible_cfo_ids(),
                                                only_cfo_ids=_chosen_cfo(cfo_ids, u))
            return {**result, "kind": kind}
        if len(payload) > 1:
            raise HTTPException(422, "Бюджет загружается по одному файлу")
        result = operplan.import_budgets(payload[0][1], payload[0][0], target, u.name,
                                         cfo_ids=u.visible_cfo_ids())
        return {**result, "kind": kind, "unmatched": 0}
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


@router.post("/rows/delete")
def delete_rows(payload: RowsDeleteIn, u: auth.User = Depends(user)) -> dict:
    """Удалить пачку строк плана: отмеченные галочками и «Очистить всё».

    Строки приходят списком идентификаторов — ровно теми, что человек видел
    в таблице. Круг «весь год» сервер не достраивает: на экране мог стоять
    фильтр, и скрытые им строки удалять никто не просил.

    Право проверяется у каждой строки отдельно, до того как удалена первая:
    в списке финотдела лежат строки разных дирекций, и частично выполненная
    очистка хуже отказа. Строк, которых уже нет, в ответе считаем отдельно —
    это не ошибка: тот же список могли удалить из соседней вкладки.
    """
    year = int(payload.year or operplan.plan_year())
    try:
        operplan.require_plan_year(year)
        operplan.require_edit(u, year)
    except ValueError as exc:
        raise HTTPException(403, str(exc)) from exc

    rows, missing = [], 0
    for row_id in dict.fromkeys(int(i) for i in payload.ids):   # дубли не считаем дважды
        row = repo.get_row(row_id)
        if not row:
            missing += 1
            continue
        if row.get("layer") != operplan.LAYER or int(row["year"]) != year:
            raise HTTPException(422, f"Строка №{row_id} не из плана {year} года")
        try:
            operplan.require_edit(u, year, int(row["cfo_id"]))
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc
        rows.append(row)

    deleted = repo.delete_rows([int(r["id"]) for r in rows])
    total = round(sum(float(r["plan_year"] or 0) for r in rows), 2)
    if deleted:
        names = sorted({str(r["cfo_name"]) for r in rows})
        # одной записью, а не по строке на каждую: журнал читают глазами
        db.log(u.name, "Удаление строк плана",
               f"Оперплан {year} · " + ", ".join(names[:5])
               + (f" и ещё {len(names) - 5}" if len(names) > 5 else ""),
               f"удалено строк: {deleted} на {_money(total)}",
               "Массовое удаление на вкладке «Бюджет»")
    return {"deleted": deleted, "missing": missing, "total": total, "year": year}


@router.post("/rows", status_code=201)
def create_row(payload: OperplanRowIn, year: int | None = None,
               u: auth.User = Depends(user)) -> dict:
    target = int(year or operplan.plan_year())
    try:
        operplan.require_plan_year(target)
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

