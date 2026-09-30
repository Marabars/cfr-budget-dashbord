***REMOVED*** -*- coding: utf-8 -*-
"""Заводит учётные записи: финотдел и по одной на каждое активное ЦФО.

Логин и пароль руководителя выводятся из названия дирекции (`app/accounts.py`),
поэтому список воспроизводим: повторный запуск даёт те же пары и не плодит
учётки. Пароль финотдела задаётся отдельно — по умолчанию задаётся флагом.

    set BUDGET_DB=data\\budget.db
    python scripts/seed_users.py                 ***REMOVED*** показать, что будет сделано
    python scripts/seed_users.py --apply         ***REMOVED*** записать в базу
    python scripts/seed_users.py --apply --reset ***REMOVED*** и переписать пароли существующим

Осторожно: `--apply` включает вход в приложение — как только у кого-то появился
пароль, все, кто зайдёт без сессии, получат форму входа.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import accounts, auth, db  ***REMOVED*** noqa: E402

FIN_LOGIN_DEFAULT = "admin"
FIN_PASSWORD_DEFAULT = ""
FIN_NAME = "Финансовый отдел"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="записать в базу (без флага только показывает)")
    parser.add_argument("--reset", action="store_true",
                        help="переписать пароль и привязку у уже существующих учёток")
    parser.add_argument("--fin-login", default=FIN_LOGIN_DEFAULT)
    parser.add_argument("--fin-password", default=FIN_PASSWORD_DEFAULT)
    parser.add_argument("--salt", default=os.environ.get("SEED_SALT", ""),
                        help="(не используется) "
                             "у кого есть исходники")
    parser.add_argument("--out", default="",
                        help="файл, куда выписать список для раздачи (UTF-8)")
    return parser.parse_args()


def existing_logins() -> dict[str, dict]:
    return {r["login"]: dict(r) for r in db.query("SELECT * FROM app_user")}


def write_user(login: str, name: str, role: str, cfo_ids: str, password: str) -> None:
    db.execute(
        "INSERT INTO app_user(login, name, role, cfo_ids, password_hash, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1) "
        "ON CONFLICT(login) DO UPDATE SET name = excluded.name, role = excluded.role, "
        "cfo_ids = excluded.cfo_ids, password_hash = excluded.password_hash, is_active = 1",
        (login, name, role, cfo_ids, auth.hash_password(password)),
    )
    auth.drop_sessions_of(login)        ***REMOVED*** пароль сменился — старые сессии закрываем


def main() -> int:
    args = parse_args()
    if os.environ.get("BUDGET_DB"):
        db.set_db_path(os.environ["BUDGET_DB"])
    db.init_db()
    print("база:", db.get_db_path())
    print("режим:", "запись" if args.apply else "только показ (добавьте --apply)")
    if args.salt:
        print("соль: задана — без неё пароли из этого списка не повторить")
    print()

    taken = existing_logins()
    ***REMOVED*** Учётка, уже привязанная ровно к одному ЦФО, — это «своя» учётка дирекции:
    ***REMOVED*** при повторном запуске логин должен остаться за ней, а не уехать в `dup2`.
    owned = {}
    for login, row in taken.items():
        ids = auth.parse_ids(row["cfo_ids"])
        if row["role"] == auth.ROLE_CFO and len(ids) == 1:
            owned[login] = ids[0]

    cfo_rows = db.query("SELECT id, name FROM cfo WHERE active = 1 ORDER BY id")
    plan = accounts.accounts_for(cfo_rows, salt=args.salt,
                                 taken=set(taken) | {args.fin_login}, owned=owned)

    lines = []

    def record(what: str, login: str, password: str, who: str) -> None:
        lines.append(f"{what:9} {login:14} {password:20} {who}")

    ***REMOVED*** ---------- финотдел ----------
    if args.fin_login in taken and taken[args.fin_login]["password_hash"] and not args.reset:
        record("уже есть", args.fin_login, "(прежний)", FIN_NAME)
    else:
        if args.apply:
            write_user(args.fin_login, FIN_NAME, auth.ROLE_FIN, "", args.fin_password)
        record("финотдел", args.fin_login, args.fin_password, FIN_NAME)

    ***REMOVED*** ---------- руководители ЦФО ----------
    for item in plan:
        known = taken.get(item["login"])
        if known and known["password_hash"] and not args.reset:
            record("уже есть", item["login"], "(прежний)", item["cfo_name"])
            continue
        if args.apply:
            write_user(item["login"], item["cfo_name"], auth.ROLE_CFO,
                       str(item["cfo_id"]), item["password"])
        record("создан" if not known else "обновлён",
               item["login"], item["password"], item["cfo_name"])

    header = f"{'что':9} {'логин':14} {'пароль':20} кому"
    report = "\n".join([header, "-" * 100] + lines)
    print(report)
    print()
    if not cfo_rows:
        print("ЦФО в базе нет — заведены только учётки финотдела.")
    if args.apply:
        print("Готово. Вход в приложение теперь включён:",
              "без сессии любой запрос получает 401.")
    else:
        print("Ничего не записано. Повторите с --apply.")
    print("Пароли выданы временные — каждому стоит сменить свой кнопкой «Пароль» в шапке.")

    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")
        print("список выписан в", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
