"""Логины учётных записей из названия ЦФО и случайные пароли к ним.

Логин — инициалы значимых слов в латинице: «Первая дирекция» → `pd`, ровно так
дирекции и называют в компании. Названия из одного короткого слова инициалами
не описать, поэтому для них берётся слово целиком. Логин не секрет: он
предсказуем по названию и таким задуман.

**Пароль выдаётся случайным** — `secrets`, алфавит без похожих символов.
Из названия ЦФО, логина и чего-либо ещё он не выводится, в коде его нет.

Повторная раздача выдаёт другие пароли, поэтому напечатанный список нужно
сохранить: он печатается один раз. Выданный пароль временный, до первой
смены самим пользователем.
"""
from __future__ import annotations

import re
import secrets

# Слова, которые есть почти у каждой дирекции и потому не различают их.
STOP_WORDS = {"по", "и", "с", "со", "в", "во", "на", "для", "при", "о", "об"}

MIN_LOGIN = 2          # одна буква — не логин, берём слово целиком
MAX_LOGIN = 12
PASSWORD_DIGITS = 5    # с ними самый короткий пароль — 8 символов, как требует auth
# Без похожих друг на друга символов: пароль диктуют голосом и переписывают с листа.
PASSWORD_ALPHABET = "23456789abcdefghijkmnpqrstuvwxyz"

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def translit(text: str) -> str:
    """Кириллица в латиницу; всё, что не буква и не цифра, выбрасывается."""
    out = []
    for char in (text or "").lower():
        if char in _TRANSLIT:
            out.append(_TRANSLIT[char])
        elif char.isalnum() and char.isascii():
            out.append(char)
    return "".join(out)


def significant_words(name: str) -> list[str]:
    """Слова названия без предлогов и союзов — по ним и различаются дирекции."""
    words = [w for w in re.split(r"[^\w]+", (name or "").lower()) if w]
    kept = [w for w in words if w not in STOP_WORDS]
    return kept or words


def login_for(name: str, taken: set[str] | None = None) -> str:
    """Логин по названию ЦФО. `taken` — уже занятые: совпадение разводится цифрой."""
    words = significant_words(name)
    candidate = "".join((translit(w) or "x")[0] for w in words)
    if len(candidate) < MIN_LOGIN:
        candidate = translit(words[0]) if words else ""
    candidate = (candidate or "cfo")[:MAX_LOGIN]

    taken = taken or set()
    if candidate not in taken:
        return candidate
    for suffix in range(2, 100):
        variant = f"{candidate[:MAX_LOGIN - len(str(suffix))]}{suffix}"
        if variant not in taken:
            return variant
    raise ValueError(f"Не удалось подобрать логин для «{name}»")


def new_password() -> str:
    """Случайный пароль, восемь знаков и больше.

    Алфавит без похожих символов: пароль диктуют голосом и переписывают
    с листа, и «0» против «O» там дороже короткого алфавита.
    """
    head = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(4))
    tail = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_DIGITS))
    return f"{head}-{tail}"


def accounts_for(cfo_rows, taken: set[str] | None = None,
                 owned: dict[str, int] | None = None) -> list[dict]:
    """Готовые учётки по списку ЦФО: [{cfo_id, cfo_name, login, password}].

    Логины разводятся между собой и с занятыми (`taken`), но своя же учётка
    занятой не считается: `owned` — карта «логин → чей он ЦФО», и если логин уже
    принадлежит этой дирекции, он за ней и остаётся. Без этого повторный запуск
    плодил бы `dup2`, `dup3` вместо того, чтобы узнать `dup`.

    Порядок списка важен — ЦФО подаются в стабильном порядке (по id).
    """
    owned = owned or {}
    used = set(taken or set())
    out = []
    for row in cfo_rows:
        cfo_id = int(row["id"])
        name = row["name"]
        mine = {login for login, owner in owned.items() if owner == cfo_id}
        login = login_for(name, used - mine)
        used.add(login)
        out.append({
            "cfo_id": cfo_id, "cfo_name": name,
            "login": login, "password": new_password(),
        })
    return out
