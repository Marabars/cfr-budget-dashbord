"""Доступ к SQLite: подключение, инициализация схемы, вспомогательные запросы."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "schema.sql"
DEFAULT_DB_PATH = BASE_DIR.parent / "data" / "budget.db"

_db_path: Path = DEFAULT_DB_PATH

DEFAULT_SETTINGS = {
    "year": "2026",
    "closed_through": "7",       ***REMOVED*** факт закрыт по этот месяц включительно
    "as_of": "",                 ***REMOVED*** пусто = текущая дата
    "pace_warning_pp": "15",     ***REMOVED*** опережение темпа освоения, п.п.
}


def set_db_path(path: str | Path) -> None:
    """Переопределяет путь к базе (используется в тестах)."""
    global _db_path
    _db_path = Path(path)


def get_db_path() -> Path:
    return _db_path


def connect() -> sqlite3.Connection:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Транзакция: коммит при успехе, откат при исключении."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт таблицы и заполняет настройки по умолчанию."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with tx() as conn:
        conn.executescript(schema)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT INTO setting(key, value) VALUES (?, ?) ON CONFLICT(key) DO NOTHING",
                (key, value),
            )
        conn.execute(
            "INSERT INTO app_user(login, name, role, cfo_ids) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(login) DO NOTHING",
            ("fin", "Финансовый отдел", "fin", ""),
        )


***REMOVED*** ---------- короткие обёртки ----------

def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    conn = connect()
    try:
        return conn.execute(sql, tuple(params)).fetchall()
    finally:
        conn.close()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    conn = connect()
    try:
        return conn.execute(sql, tuple(params)).fetchone()
    finally:
        conn.close()


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    """Выполняет запрос и возвращает lastrowid."""
    with tx() as conn:
        cur = conn.execute(sql, tuple(params))
        return int(cur.lastrowid or 0)


def get_setting(key: str, default: str = "") -> str:
    row = query_one("SELECT value FROM setting WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO setting(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def log(author: str, action: str, obj: str = "", change: str = "", reason: str = "") -> None:
    """Записывает изменение в журнал."""
    execute(
        "INSERT INTO audit_log(author, action, object, change, reason) VALUES (?, ?, ?, ?, ?)",
        (author, action, obj, change, reason),
    )