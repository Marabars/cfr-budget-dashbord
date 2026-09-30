"""Роли, пароли и сессии.

Домена AD пока нет, поэтому пользователь опознаётся сессионной cookie, которую
выдаёт `/api/auth/login`. Пароли хранятся только как PBKDF2-хеш.

Вход включается сам, когда финансовый отдел задаёт первый пароль
(`/api/auth/setup`). Пока пароля нет, приложение работает как раньше — в режиме
доверенной сети: пользователь берётся из заголовка `X-User` или cookie, по
умолчанию финотдел. Так свежая база остаётся рабочей, а на настроенной базе
любой запрос без сессии получает 401.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import HTTPException, Request

from app import db, repo

ROLE_FIN = "fin"      ***REMOVED*** финансовый отдел — видит все ЦФО
ROLE_CFO = "cfo"      ***REMOVED*** руководитель ЦФО — только свои

SESSION_COOKIE = "budget_session"
SESSION_HOURS = 12            ***REMOVED*** сессия продлевается, когда прошла половина срока
MIN_PASSWORD = 8
_PBKDF2_ROUNDS = 240_000


@dataclass
class User:
    login: str
    name: str
    role: str
    cfo_ids: list[int] = field(default_factory=list)
    viewing_as: bool = False      ***REMOVED*** финотдел смотрит глазами руководителя

    @property
    def is_fin(self) -> bool:
        return self.role == ROLE_FIN

    def visible_cfo_ids(self) -> list[int] | None:
        """None = все ЦФО."""
        return None if self.is_fin else list(self.cfo_ids)

    def can_edit_cfo(self, cfo_id: int | None) -> bool:
        if self.is_fin:
            return True
        return cfo_id is not None and int(cfo_id) in self.cfo_ids


FIN_USER = User(login="fin", name="Финансовый отдел", role=ROLE_FIN)


***REMOVED*** ---------- пароли ----------

def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256; соль своя у каждого пароля."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or not password:
        return False
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def check_password_rules(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD} символов")


def auth_enabled() -> bool:
    """Вход включён, когда есть хотя бы один активный пользователь с паролем."""
    row = db.query_one(
        "SELECT 1 FROM app_user WHERE is_active = 1 AND password_hash <> '' LIMIT 1"
    )
    return row is not None


***REMOVED*** ---------- сессии ----------

def _now() -> datetime:
    return datetime.now()


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def create_session(login: str) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    db.execute(
        "INSERT INTO session(token, login, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, login, _stamp(now), _stamp(now + timedelta(hours=SESSION_HOURS))),
    )
    return token


def drop_session(token: str) -> None:
    if token:
        db.execute("DELETE FROM session WHERE token = ?", (token,))


def drop_sessions_of(login: str) -> None:
    """Смена пароля, отключение или удаление учётки закрывает её сессии."""
    db.execute("DELETE FROM session WHERE login = ?", (login,))


def purge_expired_sessions() -> None:
    db.execute("DELETE FROM session WHERE expires_at < ?", (_stamp(_now()),))


def session_user(token: str) -> User | None:
    """Пользователь по токену; заодно продлевает сессию."""
    if not token:
        return None
    row = db.query_one(
        "SELECT s.token, s.expires_at, u.login, u.name, u.role, u.cfo_ids, u.is_active "
        "FROM session s JOIN app_user u ON u.login = s.login WHERE s.token = ?",
        (token,),
    )
    if not row:
        return None
    now = _now()
    if row["expires_at"] < _stamp(now):
        drop_session(token)
        return None
    if not row["is_active"]:
        drop_sessions_of(row["login"])
        return None
    ***REMOVED*** Продлеваем не на каждый запрос, а когда прошла половина срока: иначе любое
    ***REMOVED*** чтение дашборда писало бы в базу.
    if row["expires_at"] < _stamp(now + timedelta(hours=SESSION_HOURS / 2)):
        db.execute(
            "UPDATE session SET expires_at = ? WHERE token = ?",
            (_stamp(now + timedelta(hours=SESSION_HOURS)), token),
        )
    return User(login=row["login"], name=row["name"], role=row["role"],
                cfo_ids=parse_ids(row["cfo_ids"]))


***REMOVED*** ---------- определение пользователя запроса ----------

def parse_ids(raw: str) -> list[int]:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def _as_cfo(raw: str) -> User | None:
    """Режим просмотра «как руководитель ЦФО»: cfo:<id>."""
    raw_id = raw.split(":", 1)[1]
    if not raw_id.isdigit():
        return None
    cfo_id = int(raw_id)
    cfo = next((c for c in repo.list_cfo() if int(c["id"]) == cfo_id), None)
    name = cfo["name"] if cfo else f"ЦФО {cfo_id}"
    return User(login=raw, name=f"Руководитель · {name}", role=ROLE_CFO,
                cfo_ids=[cfo_id], viewing_as=True)


def _trusted_network_user(request: Request) -> User:
    """Поведение до включения входа: заголовок X-User, затем cookie, иначе финотдел."""
    login = (request.headers.get("X-User") or request.cookies.get("user") or "").strip()
    if not login:
        return FIN_USER
    if login.startswith("cfo:"):
        user = _as_cfo(login)
        if user:
            return user
    row = db.query_one("SELECT * FROM app_user WHERE login = ?", (login,))
    if not row:
        return FIN_USER
    return User(login=row["login"], name=row["name"], role=row["role"],
                cfo_ids=parse_ids(row["cfo_ids"]))


def current_user(request: Request) -> User:
    """Пользователь запроса: сессия, а до настройки входа — доверенная сеть."""
    user = session_user(request.cookies.get(SESSION_COOKIE, ""))
    if user is not None:
        raw = (request.headers.get("X-User") or "").strip()
        if user.is_fin and raw.startswith("cfo:"):
            return _as_cfo(raw) or user      ***REMOVED*** финотдел смотрит глазами руководителя
        return user
    if auth_enabled():
        raise HTTPException(401, "Нужно войти в приложение")
    return _trusted_network_user(request)
