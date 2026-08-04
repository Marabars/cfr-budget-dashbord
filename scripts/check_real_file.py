***REMOVED*** -*- coding: utf-8 -*-
"""Проверка импортёра на рабочем файле Ликвидность.

Путь передаётся аргументом или переменной окружения OPERPLAN_FILE —
чтобы внутренние пути не попадали в исходный код.

    python scripts/check_real_file.py "<путь к файлу ликвидности.xlsx>"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.importers import operplan  ***REMOVED*** noqa: E402


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OPERPLAN_FILE", "")
    if not path:
        print("Укажите путь к файлу: аргументом или в OPERPLAN_FILE")
        return 2

    parsed = operplan.parse(path)
    print("лист:", parsed["sheet"])
    print("шапка в строке:", parsed["header_row"])
    print("колонок месяцев:", len(parsed["month_columns"]))
    print("факт закрыт по месяц:", parsed["closed_through"])
    print("колонки:", {k: v for k, v in sorted(parsed["columns"].items(), key=lambda kv: kv[1])})

    blocks = parsed["blocks"]
    rows = parsed["rows"]
    cfos = sorted({b["cfo"] for b in blocks})
    children = [r for r in rows if r["is_child"]]
    print(f"\nблоков: {len(blocks)}, ЦФО: {len(cfos)}, строк: {len(rows)} "
          f"(из них дочерних: {len(children)})")

    print("\nсверка сумм блоков (plan / operplan / fact / сумма месяцев):")
    bad = 0
    for b in blocks:
        months_sum = sum(b["months"])
        ok = abs(months_sum - b["operplan"]) < 1.0
        if not ok:
            bad += 1
        print("  %-52s %15.2f %15.2f %15.2f %15.2f %s" % (
            b["cfo"][:52], b["plan_year"], b["operplan"], b["fact"], months_sum,
            "" if ok else "<-- сумма месяцев != Итого опер план"))

    print(f"\nблоков с расхождением месяцев и оперплана: {bad}")

    ***REMOVED*** проверка формул листа на строках
    checked = wrong_remain = wrong_free = 0
    for r in rows:
        if r["is_child"] or not r["plan_year"]:
            continue
        checked += 1
        if abs((r["plan_year"] - r["fact"]) - (r["plan_year"] - r["fact"])) > 0.01:
            wrong_remain += 1
        if abs(sum(r["months"]) - r["operplan"]) > 1.0:
            wrong_free += 1
    print(f"бюджетных строк с планом: {checked}, "
          f"расхождений «сумма месяцев = Итого опер план»: {wrong_free}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())