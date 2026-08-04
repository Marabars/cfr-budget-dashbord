"""Роли и текущий пользователь.

Способ входа определяет ИТ-отдел (планируется домен AD). До этого решения
приложение работает в режиме доверенной сети: пользователь берётся из заголовка
или cookie, по умолчанию — финансовый отдел. Пароли здесь не хранятся и не
проверяются: когда появится AD, достаточно заменить `current_user`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Request

from app import db, repo

ROLE_FIN = "fin"      ***REMOVED*** финансовый отдел — видит все ЦФО
ROLE_CFO = "cfo"      ***REMOVED*** руководитель ЦФО — только свои


@dataclass
class User:
    login: str
    name: str
    role: str
    cfo_ids: list[int] = field(default_factory=list)

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


def _parse_ids(raw: str) -> list[int]:
    out = []
    for part in (raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def current_user(request: Request) -> User:
    """Пользователь запроса: заголовок X-User, затем cookie, иначе финотдел."""
    login = (request.headers.get("X-User") or request.cookies.get("user") or "").strip()
    if not login:
        return FIN_USER

    ***REMOVED*** режим просмотра «как руководитель ЦФО»: cfo:<id>
    if login.startswith("cfo:"):
        raw_id = login.split(":", 1)[1]
        if raw_id.isdigit():
            cfo_id = int(raw_id)
            cfo = next((c for c in repo.list_cfo() if int(c["id"]) == cfo_id), None)
            name = cfo["name"] if cfo else f"ЦФО {cfo_id}"
            return User(login=login, name=f"Руководитель · {name}", role=ROLE_CFO, cfo_ids=[cfo_id])

    row = db.query_one("SELECT * FROM app_user WHERE login = ?", (login,))
    if not row:
        return FIN_USER
    return User(
        login=row["login"], name=row["name"], role=row["role"],
        cfo_ids=_parse_ids(row["cfo_ids"]),
    )