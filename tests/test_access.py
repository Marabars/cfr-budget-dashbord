"""Вход в приложение: режим доверенной сети, сессии, учётные записи.

Пароли считаются PBKDF2 с 240 000 итераций, поэтому в тестах их задаём
по необходимости, а не в каждой фикстуре.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import accounts, auth, db, repo
from app.main import app

FIN_PASSWORD = "test-fin-pass"
CFO_PASSWORD = "test-cfo-pass"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Клиент со свежей базой: входа ещё нет, работает доверенная сеть."""
    monkeypatch.setenv("BUDGET_DB", str(tmp_path / "test.db"))
    db.set_db_path(tmp_path / "test.db")
    db.init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def guest(client):
    """Второй клиент к той же базе — тот, кто ещё не вошёл."""
    with TestClient(app) as c:
        yield c


def setup_login(client) -> None:
    response = client.post("/api/auth/setup", json={"password": FIN_PASSWORD})
    assert response.status_code == 200, response.text


def make_cfo_user(client, cfo_id: int, login: str = "ivanov") -> dict:
    response = client.post("/api/users", json={
        "login": login, "name": "Иванов И.", "role": "cfo",
        "cfo_ids": [cfo_id], "password": CFO_PASSWORD,
    })
    assert response.status_code == 201, response.text
    return response.json()


***REMOVED*** ---------- пока пароля нет ----------

def test_без_настройки_приложение_открыто(client):
    state = client.get("/api/auth/state").json()
    assert state["authenticated"] is True
    assert state["setup_required"] is True
    assert state["user"]["is_fin"] is True
    assert client.get("/api/me").status_code == 200


def test_первый_пароль_включает_вход(client, guest):
    setup_login(client)
    state = client.get("/api/auth/state").json()
    assert state["setup_required"] is False
    assert state["user"]["login"] == "fin"
    ***REMOVED*** тот, у кого сессии нет, теперь внутрь не попадает
    assert guest.get("/api/auth/state").json() == {
        "authenticated": False, "setup_required": False, "user": None,
    }
    assert guest.get("/api/me").status_code == 401


def test_короткий_пароль_не_принимается(client):
    response = client.post("/api/auth/setup", json={"password": "1234"})
    assert response.status_code == 422
    assert "не короче" in response.json()["detail"]
    assert client.get("/api/auth/state").json()["setup_required"] is True


def test_повторная_настройка_отклоняется(client):
    setup_login(client)
    response = client.post("/api/auth/setup", json={"password": "another-pass"})
    assert response.status_code == 409


***REMOVED*** ---------- вход и выход ----------

def test_вход_по_паролю(client, guest):
    setup_login(client)
    assert guest.post("/api/auth/login",
                      json={"login": "fin", "password": "неверный"}).status_code == 401
    response = guest.post("/api/auth/login", json={"login": "FIN", "password": FIN_PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["is_fin"] is True
    assert guest.get("/api/me").json()["login"] == "fin"


def test_выход_закрывает_сессию(client):
    setup_login(client)
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_истёкшая_сессия_не_пускает(client):
    setup_login(client)
    db.execute("UPDATE session SET expires_at = ?", ("2000-01-01T00:00:00",))
    assert client.get("/api/me").status_code == 401
    assert db.query_one("SELECT 1 FROM session") is None      ***REMOVED*** заодно подчищается


***REMOVED*** ---------- учётные записи ----------

def test_руководитель_видит_только_свои_цфо(client, guest):
    setup_login(client)
    mine = repo.ensure_cfo("Первая дирекция")
    repo.ensure_cfo("Первый отдел")
    make_cfo_user(client, mine)

    guest.post("/api/auth/login", json={"login": "ivanov", "password": CFO_PASSWORD})
    me = guest.get("/api/me").json()
    assert me["is_fin"] is False and me["cfo_ids"] == [mine]
    assert [c["id"] for c in guest.get("/api/cfo").json()] == [mine]
    assert guest.get("/api/users").status_code == 403          ***REMOVED*** учётками ведает финотдел


def test_руководителю_нужно_хотя_бы_одно_цфо(client):
    setup_login(client)
    response = client.post("/api/users", json={
        "login": "pustoy", "name": "Без ЦФО", "role": "cfo",
        "cfo_ids": [], "password": CFO_PASSWORD,
    })
    assert response.status_code == 422


def test_логин_занимать_дважды_нельзя(client):
    setup_login(client)
    cfo_id = repo.ensure_cfo("Первая дирекция")
    make_cfo_user(client, cfo_id)
    response = client.post("/api/users", json={
        "login": "ivanov", "name": "Другой", "role": "cfo",
        "cfo_ids": [cfo_id], "password": CFO_PASSWORD,
    })
    assert response.status_code == 409


def test_отключение_учётки_выбрасывает_её_сессию(client, guest):
    setup_login(client)
    cfo_id = repo.ensure_cfo("Первая дирекция")
    make_cfo_user(client, cfo_id)
    guest.post("/api/auth/login", json={"login": "ivanov", "password": CFO_PASSWORD})
    assert guest.get("/api/me").status_code == 200

    assert client.put("/api/users/ivanov", json={"is_active": False}).status_code == 200
    assert guest.get("/api/me").status_code == 401
    assert guest.post("/api/auth/login",
                      json={"login": "ivanov", "password": CFO_PASSWORD}).status_code == 401


def test_смена_цфо_требует_войти_заново(client, guest):
    setup_login(client)
    first = repo.ensure_cfo("Первая дирекция")
    second = repo.ensure_cfo("Первый отдел")
    make_cfo_user(client, first)
    guest.post("/api/auth/login", json={"login": "ivanov", "password": CFO_PASSWORD})

    assert client.put("/api/users/ivanov", json={"cfo_ids": [second]}).status_code == 200
    assert guest.get("/api/me").status_code == 401
    guest.post("/api/auth/login", json={"login": "ivanov", "password": CFO_PASSWORD})
    assert guest.get("/api/me").json()["cfo_ids"] == [second]


def test_последняя_учётка_финотдела_не_закрывается(client):
    setup_login(client)
    cfo_id = repo.ensure_cfo("Первая дирекция")
    assert client.put("/api/users/fin", json={"role": "cfo", "cfo_ids": [cfo_id]}).status_code == 422
    assert client.put("/api/users/fin", json={"is_active": False}).status_code == 422
    assert client.delete("/api/users/fin").status_code == 422


def test_себя_удалить_нельзя_а_второго_финансиста_можно(client):
    setup_login(client)
    assert client.post("/api/users", json={
        "login": "petrova", "name": "Петрова", "role": "fin", "password": FIN_PASSWORD,
    }).status_code == 201
    assert client.delete("/api/users/fin").status_code == 422   ***REMOVED*** под ней вошли
    assert client.delete("/api/users/petrova").status_code == 204


***REMOVED*** ---------- пароли ----------

def test_смена_своего_пароля(client, guest):
    setup_login(client)
    assert client.post("/api/auth/password", json={
        "current": "не тот", "password": "new-password",
    }).status_code == 403
    assert client.post("/api/auth/password", json={
        "current": FIN_PASSWORD, "password": "new-password",
    }).status_code == 200
    assert client.get("/api/me").status_code == 200             ***REMOVED*** свою сессию сохранили
    assert guest.post("/api/auth/login",
                      json={"login": "fin", "password": FIN_PASSWORD}).status_code == 401
    assert guest.post("/api/auth/login",
                      json={"login": "fin", "password": "new-password"}).status_code == 200


def test_сброс_пароля_финотделом(client, guest):
    setup_login(client)
    cfo_id = repo.ensure_cfo("Первая дирекция")
    make_cfo_user(client, cfo_id)
    guest.post("/api/auth/login", json={"login": "ivanov", "password": CFO_PASSWORD})

    assert client.post("/api/users/ivanov/password",
                       json={"password": "vydannyy-parol"}).status_code == 200
    assert guest.get("/api/me").status_code == 401              ***REMOVED*** сессия закрыта
    assert guest.post("/api/auth/login",
                      json={"login": "ivanov", "password": "vydannyy-parol"}).status_code == 200


def test_руководитель_не_меняет_чужие_пароли(client, guest):
    setup_login(client)
    cfo_id = repo.ensure_cfo("Первая дирекция")
    make_cfo_user(client, cfo_id)
    guest.post("/api/auth/login", json={"login": "ivanov", "password": CFO_PASSWORD})
    assert guest.post("/api/users/fin/password",
                      json={"password": "chuzhoy-parol"}).status_code == 403


***REMOVED*** ---------- просмотр глазами руководителя ----------

def test_финотдел_смотрит_глазами_руководителя(client):
    setup_login(client)
    cfo_id = repo.ensure_cfo("Первая дирекция")
    repo.ensure_cfo("Первый отдел")
    me = client.get("/api/me", headers={"X-User": f"cfo:{cfo_id}"}).json()
    assert me["is_fin"] is False and me["cfo_ids"] == [cfo_id]


def test_руководитель_не_притворяется_финотделом(client, guest):
    setup_login(client)
    mine = repo.ensure_cfo("Первая дирекция")
    other = repo.ensure_cfo("Первый отдел")
    make_cfo_user(client, mine)
    guest.post("/api/auth/login", json={"login": "ivanov", "password": CFO_PASSWORD})

    me = guest.get("/api/me", headers={"X-User": "fin"}).json()
    assert me["login"] == "ivanov" and me["is_fin"] is False
    assert [c["id"] for c in guest.get("/api/cfo", headers={"X-User": f"cfo:{other}"}).json()] \
        == [mine]


***REMOVED*** ---------- миграция уже работающей базы ----------

def test_миграция_добавляет_пароли_не_трогая_учётки(tmp_path, monkeypatch):
    """На рабочей базе колонок входа ещё нет — их доливает ALTER, данные целы."""
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE cfo (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                          parent_id INTEGER, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE budget (id INTEGER PRIMARY KEY, cfo_id INTEGER NOT NULL REFERENCES cfo(id),
                             year INTEGER NOT NULL, name TEXT NOT NULL, layer TEXT NOT NULL,
                             UNIQUE (cfo_id, year, name, layer));
        CREATE TABLE app_user (login TEXT PRIMARY KEY, name TEXT NOT NULL,
                               role TEXT NOT NULL DEFAULT 'cfo',
                               cfo_ids TEXT NOT NULL DEFAULT '');
        INSERT INTO cfo(id, name) VALUES (1, 'Старое ЦФО');
        INSERT INTO app_user(login, name, role, cfo_ids) VALUES ('ivanov', 'Иванов', 'cfo', '1');
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("BUDGET_DB", str(path))
    db.set_db_path(path)
    db.init_db()

    row = db.query_one("SELECT * FROM app_user WHERE login = 'ivanov'")
    assert row["cfo_ids"] == "1"
    assert row["password_hash"] == ""      ***REMOVED*** пароля нет — войти под ней нельзя
    assert row["is_active"] == 1
    assert db.query_one("SELECT 1 FROM sqlite_master WHERE name = 'session'") is not None

    ***REMOVED*** пока ни у кого нет пароля, приложение остаётся открытым
    with TestClient(app) as client:
        assert client.get("/api/auth/state").json()["setup_required"] is True
        setup_login(client)
        assert client.post("/api/auth/login",
                           json={"login": "ivanov", "password": "любой"}).status_code == 401

    db.init_db()                            ***REMOVED*** повторный запуск безвреден
    assert db.query_one("SELECT 1 FROM app_user WHERE login = 'ivanov'") is not None


***REMOVED*** ---------- логины и пароли по названию ЦФО ----------

def test_логин_собирается_из_инициалов_значимых_слов():
    assert accounts.login_for("Вторая дирекция") == "dup"
    assert accounts.login_for("Восьмая дирекция") == "dmp"
    assert accounts.login_for("Первый отдел") == "ao"
    assert accounts.login_for("Седьмая дирекция") == "deb"


def test_короткое_название_берётся_словом_целиком():
    """«Эпсилон» — одно слово: инициал «g» логином быть не может."""
    assert accounts.login_for("Эпсилон") == "gasfor"
    assert accounts.login_for("Ёлка") == "elka"


def test_совпавшие_логины_разводятся_цифрой():
    taken = {"dup"}
    assert accounts.login_for("Вторая дирекция", taken) == "dup2"
    assert accounts.login_for("Вторая дирекция", taken | {"dup2"}) == "dup3"


def test_пароль_воспроизводим_и_не_короче_минимума():
    name = "Десятая дирекция"
    first = accounts.password_for("da", name)
    assert first == accounts.password_for("da", name)
    assert first.startswith("da-")
    assert len(first) >= auth.MIN_PASSWORD
    assert accounts.password_for("da", name, salt="соль") != first


def test_набор_учёток_не_повторяет_логины():
    rows = [
        {"id": 1, "name": "Первая дирекция"},
        {"id": 2, "name": "Первая дирекция технически"},
        {"id": 3, "name": "Двенадцатая дирекция"},
        {"id": 4, "name": "Девятая дирекция"},
    ]
    plan = accounts.accounts_for(rows, taken={"admin", "dit"})
    logins = [item["login"] for item in plan]
    assert len(set(logins)) == len(logins)
    assert "admin" not in logins
    assert logins[0] == "dit2"          ***REMOVED*** «dit» занят — развели цифрой
    assert [item["cfo_id"] for item in plan] == [1, 2, 3, 4]


def test_выданной_парой_можно_войти(client, guest):
    """Сквозная проверка: пароль из алгоритма проходит правила и пускает внутрь."""
    setup_login(client)
    cfo_id = repo.ensure_cfo("Вторая дирекция")
    rows = db.query("SELECT id, name FROM cfo WHERE id = ?", (cfo_id,))
    item = accounts.accounts_for(rows)[0]
    assert item["login"] == "dup"

    assert client.post("/api/users", json={
        "login": item["login"], "name": item["cfo_name"], "role": "cfo",
        "cfo_ids": [item["cfo_id"]], "password": item["password"],
    }).status_code == 201
    assert guest.post("/api/auth/login", json={
        "login": item["login"], "password": item["password"],
    }).status_code == 200
    assert guest.get("/api/me").json()["cfo_ids"] == [cfo_id]


def test_повторный_расчёт_узнаёт_свои_учётки():
    """Логин, уже привязанный к этому ЦФО, за ним и остаётся — без «dup2»."""
    rows = [{"id": 11, "name": "Вторая дирекция"},
            {"id": 12, "name": "Двенадцатая дирекция"}]
    first = accounts.accounts_for(rows, taken={"admin"})
    owned = {item["login"]: item["cfo_id"] for item in first}

    again = accounts.accounts_for(rows, taken={"admin"} | set(owned), owned=owned)
    assert [item["login"] for item in again] == [item["login"] for item in first]
    assert [item["password"] for item in again] == [item["password"] for item in first]


def test_чужой_логин_всё_равно_разводится():
    """Тот же логин, но за другим ЦФО — занят, и его подбирать заново нельзя."""
    rows = [{"id": 11, "name": "Вторая дирекция"}]
    plan = accounts.accounts_for(rows, taken={"dup"}, owned={"dup": 99})
    assert plan[0]["login"] == "dup2"
