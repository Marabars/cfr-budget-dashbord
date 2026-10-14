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


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _migrate(conn: sqlite3.Connection) -> None:
    """Догоняет схему на уже существующей базе.

    Новые колонки добавляются через ALTER, а вот `budget` приходится пересобирать:
    у неё меняется UNIQUE — в него добавился слой, иначе одноимённый бюджет ЦФО
    не может существовать одновременно в исполнении и в планировании.
    """
    if not _has_table(conn, "budget"):
        return                              ***REMOVED*** чистая база: всё создаст schema.sql

    if not _has_table(conn, "app_user"):
        conn.execute(
            "CREATE TABLE app_user (login TEXT PRIMARY KEY, name TEXT NOT NULL, "
            "role TEXT NOT NULL DEFAULT 'cfo', cfo_ids TEXT NOT NULL DEFAULT '')"
        )

    if "detail_source" not in _columns(conn, "cfo"):
        conn.execute("ALTER TABLE cfo ADD COLUMN detail_source TEXT NOT NULL DEFAULT 'comment'")

    ***REMOVED*** вход по паролю: на уже работающей базе колонок ещё нет, добавляем пустыми —
    ***REMOVED*** пока ни у кого нет пароля, приложение остаётся в режиме доверенной сети
    if "password_hash" not in _columns(conn, "app_user"):
        conn.execute("ALTER TABLE app_user ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
    if "is_active" not in _columns(conn, "app_user"):
        conn.execute("ALTER TABLE app_user ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    ***REMOVED*** классификатор МРГ/МРК: на работающей базе выбирать за старые строки
    ***REMOVED*** некому, поэтому всем проставляется МРГ — значением по умолчанию
    if _has_table(conn, "budget_row") and "classifier" not in _columns(conn, "budget_row"):
        conn.execute(
            "ALTER TABLE budget_row ADD COLUMN classifier TEXT NOT NULL DEFAULT 'МРГ'"
        )

    ***REMOVED*** слой платежа: весь прежний факт — исполнение, слоя планирования в нём
    ***REMOVED*** не было, поэтому умолчание 'main' верно для всех существующих записей
    if _has_table(conn, "fact") and "layer" not in _columns(conn, "fact"):
        conn.execute("ALTER TABLE fact ADD COLUMN layer TEXT NOT NULL DEFAULT 'main'")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_fact_layer ON fact(layer, year)")

    if "layer" not in _columns(conn, "budget"):
        conn.executescript("""
            CREATE TABLE budget_new (
              id     INTEGER PRIMARY KEY,
              cfo_id INTEGER NOT NULL REFERENCES cfo(id) ON DELETE CASCADE,
              year   INTEGER NOT NULL,
              name   TEXT NOT NULL,
              layer  TEXT NOT NULL DEFAULT 'main',
              UNIQUE (cfo_id, year, name, layer)
            );
            INSERT INTO budget_new(id, cfo_id, year, name, layer)
                SELECT id, cfo_id, year, name, 'main' FROM budget;
            DROP TABLE budget;
            ALTER TABLE budget_new RENAME TO budget;
        """)
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise RuntimeError(f"Миграция budget нарушила связи: {broken[:3]}")


def init_db() -> None:
    """Создаёт таблицы, догоняет схему на существующей базе и заполняет настройки."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = connect()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")   ***REMOVED*** пересборка budget роняет внешние ключи
        _migrate(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
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