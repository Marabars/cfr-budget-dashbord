"""Слой доступа к данным: CRUD над ЦФО, бюджетами, строками, заявками и фактом."""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Sequence

from app import db
from app.calc import MONTHS, month_of, normalize


***REMOVED*** ---------- ЦФО и бюджеты ----------

def _canonical(name: str) -> str:
    """Ключ для сопоставления вариантов написания ЦФО."""
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def list_cfo() -> list[dict]:
    return [dict(r) for r in db.query("SELECT * FROM cfo WHERE active = 1 ORDER BY name")]


def find_cfo(name: str) -> dict | None:
    """Ищет ЦФО по названию без учёта регистра и лишних пробелов.

    Сравнение в Python: SQLite `lower()` не работает с кириллицей.
    """
    key = _canonical(name)
    if not key:
        return None
    for row in db.query("SELECT * FROM cfo"):
        if _canonical(row["name"]) == key:
            return dict(row)
    alias = db.query_one(
        "SELECT c.* FROM cfo_alias a JOIN cfo c ON c.id = a.cfo_id WHERE a.alias = ?", (key,)
    )
    return dict(alias) if alias else None


def ensure_cfo(name: str) -> int:
    """Возвращает id ЦФО, создавая его при необходимости. Учитывает алиасы написания."""
    name = (name or "").strip() or "Не указано"
    found = find_cfo(name)
    if found:
        return int(found["id"])
    return db.execute("INSERT INTO cfo(name) VALUES (?)", (name,))


def add_alias(alias: str, cfo_id: int) -> None:
    db.execute(
        "INSERT INTO cfo_alias(alias, cfo_id) VALUES (?, ?) "
        "ON CONFLICT(alias) DO UPDATE SET cfo_id = excluded.cfo_id",
        (_canonical(alias), cfo_id),
    )


LAYER_MAIN = "main"          ***REMOVED*** исполнение: дашборд, сводка, карточка ЦФО
LAYER_OPERPLAN = "operplan"  ***REMOVED*** планирование: вкладка «Оперплан»


def ensure_budget(cfo_id: int, year: int, name: str, layer: str = LAYER_MAIN) -> int:
    name = (name or "").strip() or "Основной бюджет"
    row = db.query_one(
        "SELECT id FROM budget WHERE cfo_id = ? AND year = ? AND name = ? AND layer = ?",
        (cfo_id, year, name, layer),
    )
    if row:
        return int(row["id"])
    return db.execute(
        "INSERT INTO budget(cfo_id, year, name, layer) VALUES (?, ?, ?, ?)",
        (cfo_id, year, name, layer),
    )


def list_budgets(year: int, layer: str = LAYER_MAIN) -> list[dict]:
    rows = db.query(
        "SELECT b.id, b.name, b.year, b.layer, b.cfo_id, c.name AS cfo_name, c.detail_source "
        "FROM budget b JOIN cfo c ON c.id = b.cfo_id "
        "WHERE b.year = ? AND b.layer = ? ORDER BY c.name, b.name",
        (year, layer),
    )
    return [dict(r) for r in rows]


def delete_budgets(year: int, layer: str, cfo_ids: Sequence[int] | None = None) -> int:
    """Очищает слой за год — используется при повторной заливке плана.

    `cfo_ids` ограничивает очистку своими дирекциями: руководитель перезаливает
    бюджет своего ЦФО и не стирает чужие. `None` — весь слой за год.

    Возвращает число удалённых строк: именно его показывает отчёт о загрузке.
    """
    removed = 0
    sql = "SELECT id FROM budget WHERE year = ? AND layer = ?"
    params: list[Any] = [year, layer]
    if cfo_ids is not None:
        if not cfo_ids:
            return 0
        sql += f" AND cfo_id IN ({','.join('?' for _ in cfo_ids)})"
        params.extend(int(i) for i in cfo_ids)
    with db.tx() as conn:
        ids = [int(r["id"]) for r in conn.execute(sql, params)]
        for bid in ids:
            removed += int(conn.execute(
                "SELECT COUNT(*) c FROM budget_row WHERE budget_id = ?", (bid,)).fetchone()["c"])
            conn.execute(
                "DELETE FROM budget_row_month WHERE row_id IN "
                "(SELECT id FROM budget_row WHERE budget_id = ?)", (bid,))
            conn.execute("DELETE FROM budget_row WHERE budget_id = ?", (bid,))
            conn.execute("DELETE FROM budget WHERE id = ?", (bid,))
    return removed


***REMOVED*** ---------- строки бюджета ----------

CLASSIFIERS = ("МРГ", "МРК")
CLASSIFIER_DEFAULT = "МРГ"


def classifier_or_default(value) -> str:
    """Классификатор строки. Значений ровно два, всё прочее — МРГ.

    Чужое значение не роняет загрузку: файл из чужих рук может принести что
    угодно, а строка бюджета важнее опечатки в одной колонке.
    """
    text = str(value or "").strip().upper().replace("MP", "МР")   ***REMOVED*** латинские M и P
    return text if text in CLASSIFIERS else CLASSIFIER_DEFAULT

ROW_FIELDS = ("article", "classifier", "counterparty", "contract", "detail", "comment",
              "approver_comment", "plan_year", "carryover")


def list_rows(year: int, budget_id: int | None = None,
              layer: str = LAYER_MAIN) -> list[dict]:
    sql = (
        "SELECT r.*, b.name AS budget_name, b.layer, b.cfo_id, c.name AS cfo_name, "
        "c.detail_source "
        "FROM budget_row r JOIN budget b ON b.id = r.budget_id JOIN cfo c ON c.id = b.cfo_id "
        "WHERE b.year = ? AND b.layer = ? AND r.deleted_at IS NULL"
    )
    params: list[Any] = [year, layer]
    if budget_id:
        sql += " AND r.budget_id = ?"
        params.append(budget_id)
    sql += " ORDER BY c.name, b.name, COALESCE(r.row_no, 9999), r.id"
    return [dict(r) for r in db.query(sql, params)]


def get_row(row_id: int) -> dict | None:
    row = db.query_one(
        "SELECT r.*, b.name AS budget_name, b.year, b.layer, b.cfo_id, c.name AS cfo_name, "
        "c.detail_source "
        "FROM budget_row r JOIN budget b ON b.id = r.budget_id JOIN cfo c ON c.id = b.cfo_id "
        "WHERE r.id = ? AND r.deleted_at IS NULL",
        (row_id,),
    )
    return dict(row) if row else None


def _order_key(row: dict) -> tuple:
    """Порядок строк внутри бюджета: статья, контрагент, договор.

    Повторяет сортировку таблицы на вкладке, чтобы закреплённые номера совпали
    с тем, что человек видел на экране. «ё» приводим к «е»: по кодам символов
    она встала бы перед «а», а в русском алфавите идёт за «е» — иначе порядок
    в базе и на экране разошёлся бы.
    """
    def text(value: Any) -> str:
        return str(value or "").strip().lower().replace("ё", "е")

    article = text(row.get("article"))
    return (0 if not article else 1, article, text(row.get("counterparty")),
            text(row.get("contract")), int(row.get("row_no") or 0), int(row["id"]))


def renumber_rows(year: int, layer: str, cfo_ids: Sequence[int] | None = None) -> int:
    """Проставляет номера строк подряд внутри каждого бюджета года.

    Вызывается по кнопке «Сохранить»: до этого номера тянутся из исходного файла
    и в отсортированной по статьям таблице выглядят вперемешку. `cfo_ids`
    ограничивает перенумерацию своими дирекциями — руководитель не переставляет
    номера в чужих блоках. Возвращает число изменённых строк.
    """
    allowed = None if cfo_ids is None else {int(i) for i in cfo_ids}
    by_budget: dict[int, list[dict]] = {}
    for row in list_rows(year, layer=layer):
        if allowed is not None and int(row["cfo_id"]) not in allowed:
            continue
        by_budget.setdefault(int(row["budget_id"]), []).append(row)

    changed = 0
    with db.tx() as conn:
        for items in by_budget.values():
            for number, row in enumerate(sorted(items, key=_order_key), start=1):
                if int(row.get("row_no") or 0) == number:
                    continue
                conn.execute("UPDATE budget_row SET row_no = ? WHERE id = ?",
                             (number, int(row["id"])))
                changed += 1
    return changed


def next_row_no(budget_id: int) -> int:
    row = db.query_one(
        "SELECT COALESCE(MAX(row_no), 0) + 1 AS n FROM budget_row "
        "WHERE budget_id = ? AND deleted_at IS NULL",
        (budget_id,),
    )
    return int(row["n"]) if row else 1


def create_row(budget_id: int, data: dict, months: Sequence[float] | None = None,
               author: str = "", source: str = "manual", row_no: int | None = None) -> int:
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO budget_row(budget_id, row_no, article, classifier, counterparty, "
            "contract, detail, comment, approver_comment, plan_year, carryover, source, "
            "created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                budget_id,
                row_no,
                data.get("article", ""),
                classifier_or_default(data.get("classifier")),
                data.get("counterparty", ""),
                data.get("contract", ""),
                data.get("detail", ""),
                data.get("comment", ""),
                data.get("approver_comment", ""),
                float(data.get("plan_year") or 0),
                1 if data.get("carryover", True) else 0,
                source,
                author,
            ),
        )
        row_id = int(cur.lastrowid or 0)
        for m, amount in enumerate(normalize(months), start=1):
            if amount:
                conn.execute(
                    "INSERT INTO budget_row_month(row_id, month, amount) VALUES (?, ?, ?)",
                    (row_id, m, amount),
                )
    return row_id


def update_row(row_id: int, data: dict, months: Sequence[float] | None = None) -> None:
    fields = {k: v for k, v in data.items() if k in ROW_FIELDS}
    with db.tx() as conn:
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE budget_row SET {sets} WHERE id = ?",
                         (*fields.values(), row_id))
        if months is not None:
            conn.execute("DELETE FROM budget_row_month WHERE row_id = ?", (row_id,))
            for m, amount in enumerate(normalize(months), start=1):
                if amount:
                    conn.execute(
                        "INSERT INTO budget_row_month(row_id, month, amount) VALUES (?, ?, ?)",
                        (row_id, m, amount),
                    )


def set_row_fact(row_id: int, months) -> None:
    """Факт по строке плана: перезаписывает все двенадцать месяцев."""
    with db.tx() as conn:
        conn.execute("DELETE FROM budget_row_fact_month WHERE row_id = ?", (row_id,))
        for m, amount in enumerate(normalize(months), start=1):
            if amount:
                conn.execute(
                    "INSERT INTO budget_row_fact_month(row_id, month, amount) VALUES (?, ?, ?)",
                    (row_id, m, amount),
                )


def row_fact_months(year: int, layer: str = LAYER_MAIN) -> dict[int, list[float]]:
    """Факт слоя по месяцам: {row_id: [12 сумм]}."""
    rows = db.query(
        "SELECT m.row_id, m.month, m.amount FROM budget_row_fact_month m "
        "JOIN budget_row r ON r.id = m.row_id JOIN budget b ON b.id = r.budget_id "
        "WHERE b.year = ? AND b.layer = ? AND r.deleted_at IS NULL",
        (year, layer),
    )
    out: dict[int, list[float]] = {}
    for r in rows:
        out.setdefault(int(r["row_id"]), [0.0] * MONTHS)[int(r["month"]) - 1] = float(r["amount"])
    return out


def clear_layer_fact(year: int, layer: str, cfo_ids: Sequence[int] | None = None) -> int:
    """Стирает факт слоя за год перед повторной загрузкой.

    `cfo_ids` ограничивает очистку: загрузка факта по одной дирекции не должна
    гасить факт остальных. `None` — весь слой за год.
    """
    sql = ("SELECT r.id FROM budget_row r JOIN budget b ON b.id = r.budget_id "
           "WHERE b.year = ? AND b.layer = ?")
    params: list[Any] = [year, layer]
    if cfo_ids is not None:
        if not cfo_ids:
            return 0
        sql += f" AND b.cfo_id IN ({','.join('?' for _ in cfo_ids)})"
        params.extend(int(i) for i in cfo_ids)
    ids = [int(r["id"]) for r in db.query(sql, params)]
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    return db.execute(
        f"DELETE FROM budget_row_fact_month WHERE row_id IN ({marks})", ids)


def delete_row(row_id: int) -> None:
    db.execute("UPDATE budget_row SET deleted_at = datetime('now') WHERE id = ?", (row_id,))


def plan_months(year: int, layer: str = LAYER_MAIN) -> dict[int, list[float]]:
    """План по месяцам: {row_id: [12 сумм]}."""
    rows = db.query(
        "SELECT m.row_id, m.month, m.amount FROM budget_row_month m "
        "JOIN budget_row r ON r.id = m.row_id JOIN budget b ON b.id = r.budget_id "
        "WHERE b.year = ? AND b.layer = ? AND r.deleted_at IS NULL",
        (year, layer),
    )
    out: dict[int, list[float]] = {}
    for r in rows:
        out.setdefault(int(r["row_id"]), [0.0] * MONTHS)[int(r["month"]) - 1] = float(r["amount"])
    return out


def set_month_amount(row_id: int, month: int, amount: float) -> None:
    db.execute(
        "INSERT INTO budget_row_month(row_id, month, amount) VALUES (?, ?, ?) "
        "ON CONFLICT(row_id, month) DO UPDATE SET amount = excluded.amount",
        (row_id, month, amount),
    )


def month_amount(row_id: int, month: int) -> float:
    row = db.query_one(
        "SELECT amount FROM budget_row_month WHERE row_id = ? AND month = ?", (row_id, month)
    )
    return float(row["amount"]) if row else 0.0


***REMOVED*** ---------- факт ----------

def create_fact(data: dict, author: str = "") -> int:
    return db.execute(
        "INSERT INTO fact(row_id, cfo_id, layer, year, pay_date, amount, article, counterparty, "
        "contract, purpose, claim_number, out_of_budget, source, external_id, matched_by, matched_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
        "CASE WHEN ? IS NULL THEN NULL ELSE datetime('now') END)",
        (
            data.get("row_id"),
            data.get("cfo_id"),
            data.get("layer", LAYER_MAIN),
            int(data["year"]),
            data.get("pay_date", ""),
            float(data["amount"]),
            data.get("article", ""),
            data.get("counterparty", ""),
            data.get("contract", ""),
            data.get("purpose", ""),
            data.get("claim_number", ""),
            1 if data.get("out_of_budget") else 0,
            data.get("source", "manual"),
            data.get("external_id"),
            author if data.get("row_id") else "",
            data.get("row_id"),
        ),
    )


def fact_exists(external_id: str) -> bool:
    return bool(external_id) and db.query_one(
        "SELECT 1 FROM fact WHERE external_id = ?", (external_id,)
    ) is not None


def fact_months(year: int, layer: str = LAYER_MAIN) -> dict[int, list[float]]:
    """Факт по месяцам на строку: {row_id: [12]}."""
    rows = db.query(
        "SELECT row_id, pay_date, amount FROM fact "
        "WHERE year = ? AND layer = ? AND row_id IS NOT NULL AND out_of_budget = 0",
        (year, layer),
    )
    out: dict[int, list[float]] = {}
    for r in rows:
        month = month_of(r["pay_date"])
        if 1 <= month <= MONTHS:
            out.setdefault(int(r["row_id"]), [0.0] * MONTHS)[month - 1] += float(r["amount"])
    return out


def list_facts_by_row(row_id: int) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM fact WHERE row_id = ? ORDER BY pay_date, id", (row_id,)
    )]


def list_unmatched(year: int, limit: int = 200, layer: str = LAYER_MAIN) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT f.*, c.name AS cfo_name FROM fact f LEFT JOIN cfo c ON c.id = f.cfo_id "
        "WHERE f.year = ? AND f.layer = ? AND f.row_id IS NULL AND f.out_of_budget = 0 "
        "ORDER BY f.pay_date DESC, f.id DESC LIMIT ?",
        (year, layer, limit),
    )]


def list_out_of_budget(year: int, layer: str = LAYER_MAIN,
                       cfo_ids: Sequence[int] | None = None) -> list[dict]:
    sql = ("SELECT f.*, c.name AS cfo_name FROM fact f LEFT JOIN cfo c ON c.id = f.cfo_id "
           "WHERE f.year = ? AND f.layer = ? AND f.out_of_budget = 1")
    params: list[Any] = [year, layer]
    if cfo_ids is not None:
        if not cfo_ids:
            return []
        sql += f" AND f.cfo_id IN ({','.join('?' for _ in cfo_ids)})"
        params.extend(int(i) for i in cfo_ids)
    sql += " ORDER BY f.pay_date DESC, f.id DESC"
    return [dict(r) for r in db.query(sql, params)]


def layer_fact_rows(year: int, layer: str, cfo_ids: Sequence[int] | None = None) -> list[dict]:
    """Все записи факта слоя за год — и привязанные, и нет."""
    sql = "SELECT * FROM fact WHERE year = ? AND layer = ?"
    params: list[Any] = [year, layer]
    if cfo_ids is not None:
        if not cfo_ids:
            return []
        sql += f" AND cfo_id IN ({','.join('?' for _ in cfo_ids)})"
        params.extend(int(i) for i in cfo_ids)
    return [dict(r) for r in db.query(sql + " ORDER BY pay_date, id", params)]


def clear_layer_fact_rows(year: int, layer: str, cfo_ids: Sequence[int] | None = None) -> int:
    """Стирает записи факта слоя за год перед повторной загрузкой.

    Отдельно от `clear_layer_fact`: та чистит помесячный свод на строках
    (`budget_row_fact_month`), эта — расходы по контрагентам в таблице `fact`.
    Круг один и тот же, иначе свод и детализация разъедутся.
    """
    sql = "DELETE FROM fact WHERE year = ? AND layer = ?"
    params: list[Any] = [year, layer]
    if cfo_ids is not None:
        if not cfo_ids:
            return 0
        sql += f" AND cfo_id IN ({','.join('?' for _ in cfo_ids)})"
        params.extend(int(i) for i in cfo_ids)
    return db.execute(sql, params)


def get_fact(fact_id: int) -> dict | None:
    row = db.query_one("SELECT * FROM fact WHERE id = ?", (fact_id,))
    return dict(row) if row else None


def match_fact(fact_id: int, row_id: int, author: str) -> None:
    row = get_row(row_id)
    db.execute(
        "UPDATE fact SET row_id = ?, cfo_id = ?, out_of_budget = 0, "
        "matched_by = ?, matched_at = datetime('now') WHERE id = ?",
        (row_id, row["cfo_id"] if row else None, author, fact_id),
    )


def unmatch_fact(fact_id: int) -> None:
    db.execute("UPDATE fact SET row_id = NULL, matched_by = '', matched_at = NULL WHERE id = ?",
               (fact_id,))


def set_out_of_budget(fact_id: int, flag: bool, author: str) -> None:
    db.execute(
        "UPDATE fact SET out_of_budget = ?, row_id = CASE WHEN ? THEN NULL ELSE row_id END, "
        "matched_by = ? WHERE id = ?",
        (1 if flag else 0, 1 if flag else 0, author, fact_id),
    )


def delete_fact(fact_id: int) -> None:
    db.execute("DELETE FROM fact WHERE id = ?", (fact_id,))


***REMOVED*** ---------- заявки ----------

def create_claim(data: dict, author: str = "") -> int:
    return db.execute(
        "INSERT INTO claim(row_id, cfo_id, year, number_1c, pay_date, amount, counterparty, "
        "contract, detail, out_of_budget, over_limit, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data.get("row_id"),
            int(data["cfo_id"]),
            int(data["year"]),
            data.get("number_1c", ""),
            data.get("pay_date", ""),
            float(data["amount"]),
            data.get("counterparty", ""),
            data.get("contract", ""),
            data.get("detail", ""),
            1 if data.get("out_of_budget") else 0,
            1 if data.get("over_limit") else 0,
            author,
        ),
    )


def claim_months(year: int) -> dict[int, list[float]]:
    rows = db.query(
        "SELECT row_id, pay_date, amount FROM claim "
        "WHERE year = ? AND row_id IS NOT NULL AND status = 'planned'",
        (year,),
    )
    out: dict[int, list[float]] = {}
    for r in rows:
        month = month_of(r["pay_date"])
        if 1 <= month <= MONTHS:
            out.setdefault(int(r["row_id"]), [0.0] * MONTHS)[month - 1] += float(r["amount"])
    return out


def list_claims(year: int, cfo_ids: Iterable[int] | None = None) -> list[dict]:
    sql = (
        "SELECT cl.*, c.name AS cfo_name, r.article, r.row_no, b.name AS budget_name "
        "FROM claim cl JOIN cfo c ON c.id = cl.cfo_id "
        "LEFT JOIN budget_row r ON r.id = cl.row_id "
        "LEFT JOIN budget b ON b.id = r.budget_id "
        "WHERE cl.year = ? AND cl.status = 'planned'"
    )
    params: list[Any] = [year]
    ids = list(cfo_ids or [])
    if ids:
        sql += " AND cl.cfo_id IN (%s)" % ",".join("?" * len(ids))
        params.extend(ids)
    sql += " ORDER BY cl.pay_date, cl.id"
    return [dict(r) for r in db.query(sql, params)]


def delete_claim(claim_id: int) -> None:
    db.execute("DELETE FROM claim WHERE id = ?", (claim_id,))


def get_claim(claim_id: int) -> dict | None:
    row = db.query_one("SELECT * FROM claim WHERE id = ?", (claim_id,))
    return dict(row) if row else None


***REMOVED*** ---------- корректировки и журнал ----------

def create_adjustment(data: dict, author: str) -> int:
    return db.execute(
        "INSERT INTO adjustment(kind, year, cfo_id, from_row_id, to_row_id, from_month, "
        "to_month, amount, reason, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data["kind"], int(data["year"]), int(data["cfo_id"]),
            data.get("from_row_id"), data.get("to_row_id"),
            data.get("from_month"), data.get("to_month"),
            float(data["amount"]), data.get("reason", ""), author,
        ),
    )


def list_audit(limit: int = 100) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    )]


def list_imports(limit: int = 50) -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT * FROM import_batch ORDER BY id DESC LIMIT ?", (limit,)
    )]


def create_import(kind: str, filename: str, year: int, author: str,
                  rows_ok: int, rows_error: int, mapping: str = "", note: str = "") -> int:
    return db.execute(
        "INSERT INTO import_batch(kind, filename, year, author, rows_ok, rows_error, mapping, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, filename, year, author, rows_ok, rows_error, mapping, note),
    )


def last_fact_loads(year: int) -> dict[int, dict]:
    """Когда и каким файлом в последний раз грузили факт каждой дирекции.

    Нужно предпросмотру: загрузка заменяет факт дирекции целиком, и файл
    одной дирекции внутри файла другой (бюджеты стратегии и аналитики лежат
    в файле ИТ) способен молча затереть более свежую отдельную загрузку.
    Круг дирекций пишется в `mapping` при загрузке — по нему и ищем.
    """
    out: dict[int, dict] = {}
    rows = db.query(
        "SELECT filename, uploaded_at, mapping FROM import_batch "
        "WHERE kind = 'operplan_fact' AND year = ? ORDER BY id DESC", (year,))
    for row in rows:
        try:
            scope = json.loads(row["mapping"] or "{}").get("cfo_ids") or []
        except ValueError:
            continue
        for cfo_id in scope:
            ***REMOVED*** строки идут от свежих к старым, первая встреченная и есть последняя
            out.setdefault(int(cfo_id),
                           {"filename": row["filename"], "at": row["uploaded_at"]})
    return out


def save_column_mapping(cfo_id: int, mapping_json: str) -> None:
    db.execute(
        "INSERT INTO column_mapping(cfo_id, mapping) VALUES (?, ?) "
        "ON CONFLICT(cfo_id) DO UPDATE SET mapping = excluded.mapping",
        (cfo_id, mapping_json),
    )


def get_column_mapping(cfo_id: int) -> str:
    row = db.query_one("SELECT mapping FROM column_mapping WHERE cfo_id = ?", (cfo_id,))
    return row["mapping"] if row else ""

***REMOVED*** ---------- справочники для форм Оперплана ----------

def set_detail_source(cfo_id: int, source: str) -> None:
    """Откуда брать «Детализацию» в интерфейсе: 'detail' (из бюджета) или 'comment' (наш)."""
    db.execute("UPDATE cfo SET detail_source = ? WHERE id = ?",
               ("detail" if source == "detail" else "comment", cfo_id))


def set_article_refs(cfo_id: int, articles: Iterable[str]) -> int:
    """Перезаписывает утверждённый список статей ЦФО."""
    items = sorted({a.strip() for a in articles if a and a.strip()})
    with db.tx() as conn:
        conn.execute("DELETE FROM article_ref WHERE cfo_id = ?", (cfo_id,))
        conn.executemany("INSERT INTO article_ref(cfo_id, article) VALUES (?, ?)",
                         [(cfo_id, a) for a in items])
    return len(items)


def list_article_refs() -> list[dict]:
    return [dict(r) for r in db.query(
        "SELECT cfo_id, article FROM article_ref ORDER BY cfo_id, article")]


def used_values(year: int, layer: str = LAYER_MAIN) -> list[dict]:
    """Статьи, контрагенты, договоры и детализация, встречающиеся в строках слоя.

    Договор отдаётся вместе с контрагентом: в форме список договоров сужается
    по выбранному контрагенту. Детализация приезжает обоими полями вместе с
    `detail_source` дирекции — что из них видно в колонке, решает `_detail_text`.
    """
    return [dict(r) for r in db.query(
        "SELECT b.cfo_id, r.article, r.counterparty, r.contract, "
        "r.detail, r.comment, c.detail_source "
        "FROM budget_row r JOIN budget b ON b.id = r.budget_id "
        "JOIN cfo c ON c.id = b.cfo_id "
        "WHERE b.year = ? AND b.layer = ? AND r.deleted_at IS NULL",
        (year, layer),
    )]
