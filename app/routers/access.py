"""Вход в приложение и учётные записи.

Пока финотдел не задал первый пароль, `/api/auth/state` отдаёт `setup_required`,
и приложение остаётся открытым (режим доверенной сети). После настройки любой
запрос без сессии получает 401.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app import auth, db
from app.models import LoginIn, PasswordChangeIn, SetupIn, UserIn, UserPasswordIn, UserPatch

router = APIRouter(prefix="/api", tags=["access"])

FIN_LOGIN = "fin"


def user(request: Request) -> auth.User:
    return auth.current_user(request)


def only_fin(u: auth.User) -> None:
    if not u.is_fin:
        raise HTTPException(403, "Учётными записями управляет финансовый отдел")


def _public(row) -> dict:
    return {
        "login": row["login"],
        "name": row["name"],
        "role": row["role"],
        "cfo_ids": auth.parse_ids(row["cfo_ids"]),
        "is_active": bool(row["is_active"]),
        "has_password": bool(row["password_hash"]),
    }


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE, token, max_age=auth.SESSION_HOURS * 3600,
        httponly=True, samesite="lax", path="/",
    )


def _fin_left(exclude_login: str) -> int:
    """Сколько останется рабочих учёток финотдела, если убрать указанную."""
    rows = db.query(
        "SELECT login FROM app_user "
        "WHERE role = 'fin' AND is_active = 1 AND password_hash <> '' AND login <> ?",
        (exclude_login,),
    )
    return len(rows)


def _ids_text(ids) -> str:
    return ",".join(str(int(i)) for i in ids)


# ---------- вход ----------

@router.get("/auth/state")
def state(request: Request) -> dict:
    """Что показывать фронту: форму настройки, форму входа или само приложение."""
    enabled = auth.auth_enabled()
    try:
        u = auth.current_user(request)
    except HTTPException:
        return {"authenticated": False, "setup_required": False, "user": None}
    return {
        "authenticated": True,
        "setup_required": not enabled,
        "user": {"login": u.login, "name": u.name, "role": u.role,
                 "cfo_ids": u.cfo_ids, "is_fin": u.is_fin,
                 "viewing_as": u.viewing_as},
    }


@router.post("/auth/setup")
def setup(payload: SetupIn, response: Response) -> dict:
    """Первый пароль финотдела. Доступно ровно один раз — пока входа нет."""
    if auth.auth_enabled():
        raise HTTPException(409, "Вход уже настроен")
    auth.check_password_rules(payload.password)
    db.execute(
        "INSERT INTO app_user(login, name, role, cfo_ids, password_hash, is_active) "
        "VALUES (?, ?, 'fin', '', ?, 1) "
        "ON CONFLICT(login) DO UPDATE SET name = excluded.name, role = 'fin', "
        "password_hash = excluded.password_hash, is_active = 1",
        (FIN_LOGIN, payload.name.strip() or "Финансовый отдел",
         auth.hash_password(payload.password)),
    )
    db.log(payload.name, "Настроен вход в приложение", FIN_LOGIN)
    _set_cookie(response, auth.create_session(FIN_LOGIN))
    return {"ok": True, "login": FIN_LOGIN}


@router.post("/auth/login")
def login(payload: LoginIn, response: Response) -> dict:
    row = db.query_one("SELECT * FROM app_user WHERE login = ?",
                       (payload.login.strip().lower(),))
    if not row or not row["is_active"] or not auth.verify_password(
        payload.password, row["password_hash"]
    ):
        raise HTTPException(401, "Неверный логин или пароль")
    auth.purge_expired_sessions()
    _set_cookie(response, auth.create_session(row["login"]))
    return {"login": row["login"], "name": row["name"], "role": row["role"],
            "cfo_ids": auth.parse_ids(row["cfo_ids"]), "is_fin": row["role"] == auth.ROLE_FIN}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    auth.drop_session(request.cookies.get(auth.SESSION_COOKIE, ""))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.post("/auth/password")
def change_password(payload: PasswordChangeIn, response: Response,
                    u: auth.User = Depends(user)) -> dict:
    """Смена своего пароля: старый проверяем, все прочие сессии закрываем."""
    row = db.query_one("SELECT * FROM app_user WHERE login = ?", (u.login,))
    if not row:
        raise HTTPException(404, "Учётная запись не найдена")
    if row["password_hash"] and not auth.verify_password(payload.current, row["password_hash"]):
        raise HTTPException(403, "Текущий пароль указан неверно")
    auth.check_password_rules(payload.password)
    db.execute("UPDATE app_user SET password_hash = ? WHERE login = ?",
               (auth.hash_password(payload.password), u.login))
    auth.drop_sessions_of(u.login)
    _set_cookie(response, auth.create_session(u.login))
    db.log(u.name, "Смена пароля", u.login)
    return {"ok": True}


# ---------- учётные записи ----------

@router.get("/users")
def list_users(u: auth.User = Depends(user)) -> list[dict]:
    only_fin(u)
    rows = db.query("SELECT * FROM app_user ORDER BY role, login")
    return [_public(r) for r in rows]


@router.post("/users", status_code=201)
def create_user(payload: UserIn, u: auth.User = Depends(user)) -> dict:
    only_fin(u)
    if db.query_one("SELECT 1 FROM app_user WHERE login = ?", (payload.login,)):
        raise HTTPException(409, "Логин «" + payload.login + "» уже занят")
    if payload.role == auth.ROLE_CFO and not payload.cfo_ids:
        raise HTTPException(422, "Руководителю нужно назначить хотя бы одно ЦФО")
    auth.check_password_rules(payload.password)
    db.execute(
        "INSERT INTO app_user(login, name, role, cfo_ids, password_hash, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (payload.login, payload.name.strip(), payload.role,
         _ids_text(payload.cfo_ids), auth.hash_password(payload.password)),
    )
    db.log(u.name, "Создана учётная запись", payload.login, "роль " + payload.role)
    return _public(db.query_one("SELECT * FROM app_user WHERE login = ?", (payload.login,)))


@router.put("/users/{login}")
def update_user(login: str, payload: UserPatch, u: auth.User = Depends(user)) -> dict:
    only_fin(u)
    row = db.query_one("SELECT * FROM app_user WHERE login = ?", (login,))
    if not row:
        raise HTTPException(404, "Учётная запись не найдена")

    role = payload.role or row["role"]
    active = row["is_active"] if payload.is_active is None else int(payload.is_active)
    losing_fin = row["role"] == auth.ROLE_FIN and (role != auth.ROLE_FIN or not active)
    if losing_fin and _fin_left(login) == 0:
        raise HTTPException(422, "Это последняя учётная запись финотдела — её нельзя закрыть")

    cfo_ids = row["cfo_ids"] if payload.cfo_ids is None else _ids_text(payload.cfo_ids)
    if role == auth.ROLE_CFO and not cfo_ids:
        raise HTTPException(422, "Руководителю нужно назначить хотя бы одно ЦФО")

    db.execute(
        "UPDATE app_user SET name = ?, role = ?, cfo_ids = ?, is_active = ? WHERE login = ?",
        (payload.name.strip() if payload.name else row["name"], role, cfo_ids, active, login),
    )
    if not active or role != row["role"] or cfo_ids != row["cfo_ids"]:
        auth.drop_sessions_of(login)         # права изменились — пусть зайдёт заново
    db.log(u.name, "Изменена учётная запись", login, "роль " + role)
    return _public(db.query_one("SELECT * FROM app_user WHERE login = ?", (login,)))


@router.post("/users/{login}/password")
def reset_password(login: str, payload: UserPasswordIn, u: auth.User = Depends(user)) -> dict:
    only_fin(u)
    if not db.query_one("SELECT 1 FROM app_user WHERE login = ?", (login,)):
        raise HTTPException(404, "Учётная запись не найдена")
    auth.check_password_rules(payload.password)
    db.execute("UPDATE app_user SET password_hash = ? WHERE login = ?",
               (auth.hash_password(payload.password), login))
    auth.drop_sessions_of(login)
    db.log(u.name, "Сброшен пароль", login)
    return {"ok": True}


@router.delete("/users/{login}", status_code=204)
def delete_user(login: str, u: auth.User = Depends(user)) -> Response:
    only_fin(u)
    row = db.query_one("SELECT * FROM app_user WHERE login = ?", (login,))
    if not row:
        raise HTTPException(404, "Учётная запись не найдена")
    if login == u.login:
        raise HTTPException(422, "Нельзя удалить учётную запись, под которой вы вошли")
    if row["role"] == auth.ROLE_FIN and _fin_left(login) == 0:
        raise HTTPException(422, "Это последняя учётная запись финотдела — её нельзя удалить")
    auth.drop_sessions_of(login)
    db.execute("DELETE FROM app_user WHERE login = ?", (login,))
    db.log(u.name, "Удалена учётная запись", login)
    return Response(status_code=204)
