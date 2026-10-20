# -*- coding: utf-8 -*-
"""Первичная загрузка года из листа «Оперплан ЦФО».

Путь к файлу — аргументом или через переменную окружения OPERPLAN_FILE,
чтобы внутренние пути не попадали в исходный код.

    set BUDGET_DB=data\\budget.db
    python scripts/seed_operplan.py "<путь к файлу>" 2026
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, service  # noqa: E402


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OPERPLAN_FILE", "")
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    if not path:
        print("Укажите путь к файлу: аргументом или в OPERPLAN_FILE")
        return 2

    if os.environ.get("BUDGET_DB"):
        db.set_db_path(os.environ["BUDGET_DB"])
    db.init_db()
    print("база:", db.get_db_path())

    content = Path(path).read_bytes()
    result = service.import_operplan(content, Path(path).name, year, "Первичная загрузка")
    print("загружено:", result)

    dash = service.dashboard()
    t = dash["totals"]
    print(f"\nбюджетов: {len(dash['cards'])}")
    print(f"план: {t['plan_year']:,.2f} ₽")
    print(f"факт: {t['fact']:,.2f} ₽")
    print(f"заявки: {t['claims']:,.2f} ₽")
    print(f"свободный лимит: {t['free_limit']:,.2f} ₽")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())