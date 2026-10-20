# -*- coding: utf-8 -*-
"""Готовит обезличенные данные для HTML-макета (docs/mock-data.demo.js).

Реальные названия дирекций, контрагентов, договоров и суммы в публичный
репозиторий не попадают. Скрипт генерирует правдоподобный, но вымышленный набор:
структура та же (блоки «ЦФО × бюджет», строки, месяцы), содержимое — синтетика.

    python scripts/make_demo_mock.py
"""
from __future__ import annotations

import io
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "mock-data.demo.js"

CFOS = [
    ("Первая дирекция", ["Бюджет обязательных затрат", "Бюджет развития"], 640_000_000),
    ("Восемнадцатая дирекция", ["Основной бюджет"], 400_000_000),
    ("Пятнадцатая дирекция", ["Основной бюджет"], 390_000_000),
    ("Одиннадцатая дирекция", ["Основной бюджет"], 138_000_000),
    ("Финансовый отдел", ["Основной бюджет"], 78_000_000),
    ("Шестнадцатая дирекция", ["Основной бюджет"], 68_000_000),
    ("Семнадцатая дирекция", ["Основной бюджет"], 34_000_000),
    ("Четвёртая дирекция", ["Основной бюджет"], 14_700_000),
    ("Девятая дирекция", ["Основной бюджет"], 12_500_000),
    ("Дирекция внешних коммуникаций", ["Основной бюджет"], 10_800_000),
    ("Тринадцатая дирекция", ["Основной бюджет"], 8_600_000),
    ("Первый отдел", ["Основной бюджет"], 7_100_000),
    ("Четырнадцатая дирекция", ["Основной бюджет"], 5_500_000),
    ("Прочие расходы", ["Основной бюджет"], 2_400_000),
    ("Служба безопасности", ["Основной бюджет"], 300_000),
]

ARTICLES = [
    "4101_Аренда и обслуживание помещений", "4102_Хозяйственные расходы",
    "4106_Аудит и консалтинг", "4107_Юридические услуги",
    "4109.2_Обучение персонала", "4110_Социальные расходы",
    "4307.4_Мероприятия, выставки и конференции",
    "4411.1_Приобретение офисного оборудования",
    "4411.2_Содержание офисного оборудования",
    "4411.3_Аренда оборудования для IT",
    "4412.2_Услуги телефонной связи", "4420_Расходы на приобретение ПО",
    "4430_Сопровождение и разработка IT систем",
    "4440_Аутсорсинговые услуги в сфере IT", "4602_Эксплуатационные расходы",
]
VENDORS = ["Альфа Технолоджис ООО", "Бета Софт ООО", "Гамма Сервис АО",
           "Дельта Интеграция ООО", "Эпсилон Групп ООО", "Дзета Консалтинг ООО",
           "Исполнитель не определён", "Текущие подрядчики"]
DETAILS = ["ИТ инфраструктура", "Лицензии и подписки", "Сопровождение систем",
           "Расходные материалы", "Обучение сотрудников", "Мероприятия",
           "Каналы связи", "Аренда оборудования"]


def spread(total: float, rnd: random.Random) -> list[float]:
    """Распределяет сумму по 12 месяцам неравномерно, как в реальных бюджетах."""
    weights = [rnd.random() ** 2 + 0.1 for _ in range(12)]
    if rnd.random() < 0.3:                     # часть строк — разовые платежи
        weights = [0.0] * 12
        for _ in range(rnd.randint(1, 3)):
            weights[rnd.randrange(12)] = 1.0
    total_weight = sum(weights) or 1.0
    return [round(total * w / total_weight, 2) for w in weights]


def main() -> int:
    rnd = random.Random(20260804)
    blocks, detail_first, detail_second = [], [], []

    for index, (cfo, budgets, plan) in enumerate(CFOS):
        per_budget = plan / len(budgets)
        for budget_index, budget in enumerate(budgets):
            months = spread(per_budget * rnd.uniform(0.95, 1.1), rnd)
            blocks.append({
                "id": f"b{len(blocks) + 1}",
                "cfo": cfo,
                "budget": budget,
                "plan": round(per_budget, 2),
                "months": months,
                "rowFrom": 0,
                "rowTo": 0,
            })

    def make_rows(count: int, budget_plan: float) -> list[dict]:
        rows = []
        for no in range(1, count + 1):
            plan = round(budget_plan / count * rnd.uniform(0.4, 1.6), 2)
            rows.append({
                "no": str(no),
                "article": rnd.choice(ARTICLES),
                "counterparty": rnd.choice(VENDORS),
                "contract": rnd.choice(["", f"Договор №{rnd.randint(100, 9999)} от "
                                            f"{rnd.randint(1, 28):02d}.{rnd.randint(1, 12):02d}.25",
                                        "Без договора"]),
                "detail": rnd.choice(DETAILS),
                "comment": "",
                "ourComment": "",
                "plan": plan,
                "months": spread(plan, rnd),
            })
            if rnd.random() < 0.2:            # дочерняя строка — платёж по лимиту
                child_plan = round(plan * rnd.uniform(0.05, 0.4), 2)
                child_months = [0.0] * 12
                child_months[rnd.randrange(7)] = child_plan
                rows.append({
                    "no": "",
                    "article": rows[-1]["article"],
                    "counterparty": rnd.choice(VENDORS),
                    "contract": f"Договор №{rnd.randint(100, 9999)}",
                    "detail": rows[-1]["detail"],
                    "comment": "",
                    "ourComment": f"Из строки {no} бюджет",
                    "plan": 0,
                    "months": child_months,
                })
        return rows

    detail_first = make_rows(24, blocks[0]["plan"])
    detail_second = make_rows(7, blocks[len(CFOS) - 10]["plan"])

    data = {
        "source": "обезличенные демонстрационные данные (scripts/make_demo_mock.py)",
        "blocks": blocks,
        "detailITD": detail_first,
        "detailFin": detail_second,
    }
    with io.open(OUT, "w", encoding="utf-8") as fh:
        fh.write("// Обезличенные данные для макета. Сгенерировано "
                 "scripts/make_demo_mock.py — не править вручную.\n")
        fh.write("window.MOCK = ")
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write(";\n")
    print("записано:", OUT)
    print("блоков:", len(blocks), "строк в первом ЦФО:", len(detail_first))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())