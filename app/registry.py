"""Справочник ЦФО: статистика, поиск дублей, сведение и переименование.

В выгрузках название дирекции пишут по-разному («…технологиям технически»,
сокращения, опечатки), из-за чего один ЦФО распадается на несколько. Сведение
переносит все данные на каноничный ЦФО и запоминает написание как алиас —
следующий импорт уже не создаст дубль.
"""
from __future__ import annotations

import re

from app import calc, db, repo

SUGGEST_LIMIT = 40


***REMOVED*** ---------- статистика ----------

def stats(year: int) -> list[dict]:
    """По каждому ЦФО: сколько бюджетов, строк, план, факт, заявки, алиасы."""
    rows = db.query(
        """
        SELECT c.id, c.name,
               (SELECT COUNT(*) FROM budget b WHERE b.cfo_id = c.id AND b.year = ?) AS budgets,
               (SELECT COUNT(*) FROM budget_row r JOIN budget b ON b.id = r.budget_id
                 WHERE b.cfo_id = c.id AND b.year = ? AND r.deleted_at IS NULL) AS rows_count,
               (SELECT COALESCE(SUM(r.plan_year), 0) FROM budget_row r
                 JOIN budget b ON b.id = r.budget_id
                 WHERE b.cfo_id = c.id AND b.year = ? AND r.deleted_at IS NULL) AS plan_year,
               (SELECT COALESCE(SUM(f.amount), 0) FROM fact f
                 WHERE f.cfo_id = c.id AND f.year = ? AND f.out_of_budget = 0) AS fact,
               (SELECT COALESCE(SUM(cl.amount), 0) FROM claim cl
                 WHERE cl.cfo_id = c.id AND cl.year = ? AND cl.status = 'planned') AS claims,
               (SELECT COUNT(*) FROM cfo_alias a WHERE a.cfo_id = c.id) AS aliases
        FROM cfo c
        ORDER BY plan_year DESC, c.name
        """,
        (year, year, year, year, year),
    )
    out = []
    for row in rows:
        item = dict(row)
        item["budget_names"] = [
            r["name"] for r in db.query(
                "SELECT name FROM budget WHERE cfo_id = ? AND year = ? ORDER BY name",
                (item["id"], year),
            )
        ]
        item["alias_list"] = [
            r["alias"] for r in db.query(
                "SELECT alias FROM cfo_alias WHERE cfo_id = ? ORDER BY alias", (item["id"],)
            )
        ]
        item["empty"] = not (item["rows_count"] or item["fact"] or item["claims"])
        out.append(item)
    return out


***REMOVED*** ---------- поиск дублей ----------

def _key(name: str) -> str:
    """Ключ сравнения: без регистра, пробелов, дефисов и кавычек."""
    return re.sub(r"[\s\-–—«»\"'.,()]+", "", (name or "").lower())


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[\s\-–—.,()]+", (name or "").lower()) if len(w) > 2]


def _distance(a: str, b: str) -> int:
    """Расстояние Левенштейна (нужно для опечаток в названиях)."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _similarity(a: str, b: str) -> tuple[int, str] | None:
    """Оценка похожести пары названий: (уверенность 1..3, причина)."""
    ka, kb = _key(a), _key(b)
    if not ka or not kb or ka == kb:
        return (3, "совпадают без учёта регистра и пробелов") if ka == kb else None

    if len(ka) >= 12 and (ka.startswith(kb) or kb.startswith(ka)):
        return 3, "одно название — начало другого"
    if len(ka) >= 10 and (ka in kb or kb in ka):
        return 3, "одно название входит в другое"

    distance = _distance(ka, kb)
    if distance <= 2 and min(len(ka), len(kb)) >= 8:
        return 3, f"отличаются на {distance} символ(а) — похоже на опечатку"
    if distance <= 4 and min(len(ka), len(kb)) >= 14:
        return 2, f"отличаются на {distance} символа"

    words_a, words_b = set(_words(a)), set(_words(b))
    common = words_a & words_b
    meaningful = {w for w in common if w not in ("дирекция", "отдел", "служба", "департамент",
                                                 "управление", "группа", "центр", "по")}
    if meaningful and len(meaningful) >= max(1, min(len(words_a), len(words_b)) - 1):
        return 2, "совпадают значимые слова: " + ", ".join(sorted(meaningful))
    if len(meaningful) >= 2:
        return 1, "частично совпадают слова: " + ", ".join(sorted(meaningful))
    return None


def suggestions(year: int) -> list[dict]:
    """Пары похожих ЦФО. Основным предлагается тот, где больше данных."""
    items = stats(year)
    pairs = []
    for i, first in enumerate(items):
        for second in items[i + 1:]:
            verdict = _similarity(first["name"], second["name"])
            if not verdict:
                continue
            confidence, reason = verdict
            ***REMOVED*** основной — где больше строк, при равенстве — больше плана
            main, extra = first, second
            if (second["rows_count"], second["plan_year"]) > (first["rows_count"], first["plan_year"]):
                main, extra = second, first
            pairs.append({
                "confidence": confidence,
                "reason": reason,
                "target": {k: main[k] for k in ("id", "name", "rows_count", "plan_year", "fact")},
                "source": {k: extra[k] for k in ("id", "name", "rows_count", "plan_year", "fact")},
            })
    pairs.sort(key=lambda p: (-p["confidence"], -p["target"]["plan_year"]))
    return pairs[:SUGGEST_LIMIT]


***REMOVED*** ---------- изменение справочника ----------

def rename(cfo_id: int, new_name: str, author: str) -> dict:
    """Переименование с сохранением прежнего написания как алиаса."""
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("Название не может быть пустым")
    current = db.query_one("SELECT name FROM cfo WHERE id = ?", (cfo_id,))
    if not current:
        raise ValueError("ЦФО не найдено")
    clash = repo.find_cfo(new_name)
    if clash and int(clash["id"]) != cfo_id:
        raise ValueError(f"Название занято другим ЦФО: {clash['name']}")

    old_name = current["name"]
    db.execute("UPDATE cfo SET name = ? WHERE id = ?", (new_name, cfo_id))
    repo.add_alias(old_name, cfo_id)
    db.log(author, "Переименование ЦФО", new_name, f"{old_name} → {new_name}",
           "Прежнее написание сохранено как алиас")
    return {"ok": True, "id": cfo_id, "name": new_name}


def add_alias(cfo_id: int, alias: str, author: str) -> dict:
    """Добавляет вариант написания, который впредь будет попадать в этот ЦФО."""
    alias = (alias or "").strip()
    if not alias:
        raise ValueError("Укажите написание")
    target = db.query_one("SELECT name FROM cfo WHERE id = ?", (cfo_id,))
    if not target:
        raise ValueError("ЦФО не найдено")
    existing = repo.find_cfo(alias)
    if existing and int(existing["id"]) != cfo_id:
        raise ValueError(f"Это написание уже относится к ЦФО «{existing['name']}» — "
                         f"сведите их, а не добавляйте алиас")
    repo.add_alias(alias, cfo_id)
    db.log(author, "Алиас ЦФО", target["name"], f"+ «{alias}»", "Ручное добавление написания")
    return {"ok": True}


def delete_alias(alias: str, author: str) -> dict:
    row = db.query_one(
        "SELECT a.alias, c.name FROM cfo_alias a JOIN cfo c ON c.id = a.cfo_id WHERE a.alias = ?",
        (alias,),
    )
    if not row:
        raise ValueError("Алиас не найден")
    db.execute("DELETE FROM cfo_alias WHERE alias = ?", (alias,))
    db.log(author, "Алиас ЦФО", row["name"], f"− «{alias}»", "Удалено вручную")
    return {"ok": True}


def merge_preview(source_id: int, target_id: int, year: int) -> dict:
    """Что произойдёт при сведении — показывается до подтверждения."""
    if source_id == target_id:
        raise ValueError("Выбраны одинаковые ЦФО")
    items = {int(i["id"]): i for i in stats(year)}
    source, target = items.get(source_id), items.get(target_id)
    if not source or not target:
        raise ValueError("ЦФО не найдено")

    shared = sorted(set(source["budget_names"]) & set(target["budget_names"]))
    return {
        "source": source,
        "target": target,
        "merged_budgets": shared,
        "totals_after": {
            "rows_count": source["rows_count"] + target["rows_count"],
            "plan_year": source["plan_year"] + target["plan_year"],
            "fact": source["fact"] + target["fact"],
            "claims": source["claims"] + target["claims"],
        },
        "aliases_moved": source["alias_list"] + [source["name"]],
    }


def merge(source_id: int, target_id: int, author: str) -> dict:
    """Переносит все данные source в target и удаляет source.

    Бюджеты с одинаковым названием объединяются в один, строки переносятся
    со сквозной перенумерацией. Прежнее название становится алиасом.
    """
    if source_id == target_id:
        raise ValueError("Выбраны одинаковые ЦФО")
    source = db.query_one("SELECT * FROM cfo WHERE id = ?", (source_id,))
    target = db.query_one("SELECT * FROM cfo WHERE id = ?", (target_id,))
    if not source or not target:
        raise ValueError("ЦФО не найдено")

    moved_rows = merged_budgets = 0
    with db.tx() as conn:
        for budget in conn.execute("SELECT * FROM budget WHERE cfo_id = ?", (source_id,)).fetchall():
            same = conn.execute(
                "SELECT id FROM budget WHERE cfo_id = ? AND year = ? AND name = ?",
                (target_id, budget["year"], budget["name"]),
            ).fetchone()
            if same:
                ***REMOVED*** объединяем: строки переезжают, номера продолжают нумерацию получателя
                next_no = conn.execute(
                    "SELECT COALESCE(MAX(row_no), 0) FROM budget_row WHERE budget_id = ?",
                    (same["id"],),
                ).fetchone()[0] or 0
                rows = conn.execute(
                    "SELECT id FROM budget_row WHERE budget_id = ? ORDER BY COALESCE(row_no, 9999), id",
                    (budget["id"],),
                ).fetchall()
                for row in rows:
                    next_no += 1
                    conn.execute("UPDATE budget_row SET budget_id = ?, row_no = ? WHERE id = ?",
                                 (same["id"], next_no, row["id"]))
                    moved_rows += 1
                conn.execute("DELETE FROM budget WHERE id = ?", (budget["id"],))
                merged_budgets += 1
            else:
                conn.execute("UPDATE budget SET cfo_id = ? WHERE id = ?", (target_id, budget["id"]))

        conn.execute("UPDATE fact SET cfo_id = ? WHERE cfo_id = ?", (target_id, source_id))
        conn.execute("UPDATE claim SET cfo_id = ? WHERE cfo_id = ?", (target_id, source_id))
        conn.execute("UPDATE adjustment SET cfo_id = ? WHERE cfo_id = ?", (target_id, source_id))
        conn.execute("UPDATE cfo_alias SET cfo_id = ? WHERE cfo_id = ?", (target_id, source_id))
        conn.execute("UPDATE cfo SET parent_id = ? WHERE parent_id = ?", (target_id, source_id))
        conn.execute("DELETE FROM column_mapping WHERE cfo_id = ?", (source_id,))
        conn.execute("DELETE FROM cfo WHERE id = ?", (source_id,))

    repo.add_alias(source["name"], target_id)
    db.log(author, "Сведение ЦФО", target["name"],
           f"«{source['name']}» → «{target['name']}»",
           f"объединено бюджетов: {merged_budgets}, перенесено строк: {moved_rows}")
    return {
        "ok": True, "target_id": target_id, "target_name": target["name"],
        "merged_budgets": merged_budgets, "moved_rows": moved_rows,
        "alias_added": source["name"],
    }


def delete_empty(cfo_id: int, author: str) -> dict:
    """Удаляет ЦФО, у которого нет данных (появляются из опечаток в выгрузках)."""
    year = int(db.get_setting("year", str(calc.MONTHS and 2026)))
    item = next((i for i in stats(year) if int(i["id"]) == cfo_id), None)
    if not item:
        raise ValueError("ЦФО не найдено")
    if not item["empty"]:
        raise ValueError("У этого ЦФО есть данные — используйте сведение, а не удаление")
    db.execute("DELETE FROM cfo WHERE id = ?", (cfo_id,))
    db.log(author, "Удаление пустого ЦФО", item["name"], "запись удалена", "Нет связанных данных")
    return {"ok": True}