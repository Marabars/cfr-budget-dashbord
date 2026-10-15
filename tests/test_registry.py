"""Тесты справочника ЦФО: поиск дублей, сведение, алиасы, переименование."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db, registry, repo, service
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDGET_DB", str(tmp_path / "reg.db"))
    db.set_db_path(tmp_path / "reg.db")
    db.init_db()
    db.set_setting("year", "2026")
    db.set_setting("closed_through", "7")
    db.set_setting("as_of", "2026-08-04")
    with TestClient(app) as c:
        yield c


def make_cfo(client, name: str, budget: str, article: str, plan: float) -> dict:
    """ЦФО с одной строкой бюджета."""
    cfo_id = repo.ensure_cfo(name)
    response = client.post("/api/rows", json={
        "cfo_id": cfo_id, "budget_name": budget, "article": article,
        "plan_year": plan, "spread": "even",
    })
    assert response.status_code == 201, response.text
    return {"cfo_id": cfo_id, "row_id": response.json()["id"]}


***REMOVED*** ---------- поиск дублей ----------

def test_находит_дубль_с_приписанным_словом(client):
    make_cfo(client, "Первая дирекция", "Основной бюджет", "4420_ПО", 1_000_000)
    make_cfo(client, "Первая дирекция технически", "Основной бюджет",
             "4420_ПО", 50_000)

    pairs = registry.suggestions(2026)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["confidence"] == 3
    ***REMOVED*** основным предлагается тот, где больше данных
    assert pair["target"]["name"] == "Первая дирекция"
    assert pair["source"]["name"].endswith("технически")


def test_находит_опечатку_в_названии(client):
    make_cfo(client, "Финансовый отдел", "Основной бюджет", "4106_Аудит", 500_000)
    make_cfo(client, "Финансовый отедл", "Основной бюджет", "4106_Аудит", 100_000)
    pairs = registry.suggestions(2026)
    assert pairs and pairs[0]["confidence"] == 3
    assert pairs[0]["target"]["name"] == "Финансовый отдел"    ***REMOVED*** где данных больше


def test_не_считает_дублями_разные_дирекции(client):
    make_cfo(client, "Двадцатая дирекция", "Основной бюджет", "4307.3_PR", 100_000)
    make_cfo(client, "Девятая дирекция", "Основной бюджет", "4107_Юристы", 100_000)
    assert registry.suggestions(2026) == []


def test_статистика_считает_строки_и_суммы(client):
    made = make_cfo(client, "Семнадцатая дирекция", "Основной бюджет", "4301_Анализ", 900_000)
    client.post("/api/facts", json={"row_id": made["row_id"], "pay_date": "2026-03-10",
                                    "amount": 200_000})
    item = next(i for i in registry.stats(2026) if i["id"] == made["cfo_id"])
    assert item["rows_count"] == 1
    assert item["plan_year"] == 900_000
    assert item["fact"] == 200_000
    assert item["empty"] is False


***REMOVED*** ---------- сведение ----------

def test_сведение_сохраняет_суммы_и_переносит_данные(client):
    main = make_cfo(client, "Третья дирекция", "Бюджет обязательных затрат", "4420_ПО", 1_000_000)
    dup = make_cfo(client, "Третья дирекция технически", "Бюджет развития", "4430_Разработка", 400_000)
    client.post("/api/facts", json={"row_id": dup["row_id"], "pay_date": "2026-02-10",
                                    "amount": 150_000})
    client.post("/api/claims", json={"row_id": dup["row_id"], "cfo_id": dup["cfo_id"],
                                     "pay_date": "2026-09-10", "amount": 90_000})

    before = client.get("/api/dashboard").json()["totals"]

    result = client.post("/api/registry/merge", json={
        "source_id": dup["cfo_id"], "target_id": main["cfo_id"],
    })
    assert result.status_code == 200, result.text

    after = client.get("/api/dashboard").json()["totals"]
    assert after["plan_year"] == before["plan_year"]      ***REMOVED*** суммы не потерялись
    assert after["fact"] == before["fact"]
    assert after["claims"] == before["claims"]

    ***REMOVED*** остался один ЦФО с двумя бюджетами
    items = registry.stats(2026)
    assert len(items) == 1
    assert items[0]["budgets"] == 2
    assert items[0]["rows_count"] == 2


def test_сведение_объединяет_одноимённые_бюджеты_и_перенумеровывает_строки(client):
    main = make_cfo(client, "Девятнадцатая дирекция", "Основной бюджет", "4602_Эксплуатация", 800_000)
    dup = make_cfo(client, "Девятнадцатая дирекция технически", "Основной бюджет", "4102_Хозрасходы", 200_000)

    client.post("/api/registry/merge", json={"source_id": dup["cfo_id"],
                                            "target_id": main["cfo_id"]})

    items = registry.stats(2026)
    assert len(items) == 1
    assert items[0]["budgets"] == 1                       ***REMOVED*** бюджеты объединены
    assert items[0]["rows_count"] == 2

    card = client.get(f"/api/cfo/{main['cfo_id']}").json()
    numbers = sorted(r["row_no"] for r in card["budgets"][0]["rows"])
    assert numbers == [1, 2]                              ***REMOVED*** номера не дублируются


def test_после_сведения_прежнее_название_становится_алиасом(client):
    main = make_cfo(client, "Тринадцатая дирекция", "Основной бюджет", "4307.2_Дизайн", 500_000)
    dup = make_cfo(client, "Тринадцатая дирекция расширенная", "Основной бюджет", "4307.2_Дизайн", 100_000)
    old_name = "Тринадцатая дирекция расширенная"

    client.post("/api/registry/merge", json={"source_id": dup["cfo_id"],
                                            "target_id": main["cfo_id"]})

    ***REMOVED*** повторный импорт со старым написанием попадёт в основной ЦФО, а не создаст дубль
    assert repo.ensure_cfo(old_name) == main["cfo_id"]
    assert len(registry.stats(2026)) == 1


def test_предпросмотр_показывает_что_будет_объединено(client):
    main = make_cfo(client, "Шестнадцатая дирекция", "Основной бюджет", "4301_Анализ", 700_000)
    dup = make_cfo(client, "Шестнадцатая дирекция расширенная", "Основной бюджет", "4306.8_Спецпроекты", 300_000)

    preview = client.get("/api/registry/merge-preview", params={
        "source_id": dup["cfo_id"], "target_id": main["cfo_id"],
    }).json()
    assert preview["merged_budgets"] == ["Основной бюджет"]
    assert preview["totals_after"]["plan_year"] == 1_000_000
    assert preview["totals_after"]["rows_count"] == 2


def test_нельзя_свести_цфо_с_самим_собой(client):
    main = make_cfo(client, "Первый отдел", "Основной бюджет", "4102_Хозрасходы", 100_000)
    response = client.post("/api/registry/merge", json={
        "source_id": main["cfo_id"], "target_id": main["cfo_id"],
    })
    assert response.status_code == 422


***REMOVED*** ---------- переименование и алиасы ----------

def test_переименование_сохраняет_старое_написание_как_алиас(client):
    made = make_cfo(client, "Четырнадцатая дирекция", "Основной бюджет", "4307.3_PR", 200_000)
    response = client.patch(f"/api/registry/cfo/{made['cfo_id']}",
                            json={"name": "Дирекция внешних коммуникаций"})
    assert response.status_code == 200
    assert repo.ensure_cfo("Четырнадцатая дирекция") == made["cfo_id"]      ***REMOVED*** старое имя ведёт туда же


def test_переименование_в_занятое_имя_отклоняется(client):
    first = make_cfo(client, "Дирекция А", "Основной бюджет", "4102_Хозрасходы", 100_000)
    make_cfo(client, "Дирекция Б", "Основной бюджет", "4102_Хозрасходы", 100_000)
    response = client.patch(f"/api/registry/cfo/{first['cfo_id']}", json={"name": "Дирекция Б"})
    assert response.status_code == 422
    assert "занято" in response.json()["detail"]


def test_алиас_нельзя_повесить_на_чужой_цфо(client):
    first = make_cfo(client, "Дирекция В", "Основной бюджет", "4102_Хозрасходы", 100_000)
    make_cfo(client, "Дирекция Г", "Основной бюджет", "4102_Хозрасходы", 100_000)
    response = client.post(f"/api/registry/cfo/{first['cfo_id']}/alias",
                           json={"alias": "Дирекция Г"})
    assert response.status_code == 422
    assert "сведите" in response.json()["detail"]


def test_пустой_цфо_можно_удалить_а_с_данными_нельзя(client):
    empty_id = repo.ensure_cfo("Опечатка в выгрузке")
    assert client.delete(f"/api/registry/cfo/{empty_id}").status_code == 200

    made = make_cfo(client, "Дирекция Д", "Основной бюджет", "4102_Хозрасходы", 100_000)
    response = client.delete(f"/api/registry/cfo/{made['cfo_id']}")
    assert response.status_code == 422
    assert "сведение" in response.json()["detail"]


***REMOVED*** ---------- права ----------

def test_руководителю_цфо_справочник_недоступен(client):
    made = make_cfo(client, "Дирекция Е", "Основной бюджет", "4102_Хозрасходы", 100_000)
    headers = {"X-User": f"cfo:{made['cfo_id']}"}
    assert client.get("/api/registry/cfo", headers=headers).status_code == 403
    assert client.post("/api/registry/merge", json={"source_id": 1, "target_id": 2},
                       headers=headers).status_code == 403


***REMOVED*** ---------- журнал ----------

def test_сведение_попадает_в_журнал_изменений(client):
    main = make_cfo(client, "Дирекция Ж", "Основной бюджет", "4102_Хозрасходы", 100_000)
    dup = make_cfo(client, "Дирекция Ж дополнительно", "Основной бюджет", "4102_Хозрасходы", 50_000)
    client.post("/api/registry/merge", json={"source_id": dup["cfo_id"],
                                             "target_id": main["cfo_id"]})
    actions = [entry["action"] for entry in client.get("/api/audit").json()]
    assert "Сведение ЦФО" in actions

def test_написания_отличающиеся_пробелами_и_регистром_сразу_один_цфо(client):
    """Такие варианты не доходят до справочника — их сводит уже импорт."""
    first = repo.ensure_cfo("Вторая дирекция")
    assert repo.ensure_cfo("  вторая   Дирекция ") == first
    assert len([i for i in registry.stats(2026) if i["id"] == first]) == 1


***REMOVED*** ---------- источник «Детализации» ----------

def test_источник_детализации_ставится_в_реестре(client):
    """Это свойство ЦФО, а не догадка по названию: имя меняется, догадка — нет."""
    make_cfo(client, "Первая дирекция", "Основной бюджет", "4420_ПО", 100_000)
    cfo_id = repo.find_cfo("Первая дирекция")["id"]
    assert repo.get_cfo_detail_source(cfo_id) == "comment", "по умолчанию — комментарий"

    assert client.patch(f"/api/registry/cfo/{cfo_id}",
                        json={"detail_source": "detail"}).status_code == 200
    assert repo.get_cfo_detail_source(cfo_id) == "detail"

    assert client.patch(f"/api/registry/cfo/{cfo_id}",
                        json={"detail_source": "comment"}).status_code == 200
    assert repo.get_cfo_detail_source(cfo_id) == "comment"


def test_заливка_плана_источник_детализации_не_трогает(client):
    """Самое важное: признак переживает перезаливку бюджета из Excel."""
    from app import operplan
    from tests.test_operplan import IT, make_budgets_sheet

    operplan.import_budgets(make_budgets_sheet(), "бюджеты.xlsx", 2026, "Тест")
    cfo_id = repo.find_cfo(IT)["id"]
    assert repo.get_cfo_detail_source(cfo_id) == "comment", \
        "заливка не должна угадывать признак по названию"

    client.patch(f"/api/registry/cfo/{cfo_id}", json={"detail_source": "detail"})
    operplan.import_budgets(make_budgets_sheet(), "бюджеты.xlsx", 2026, "Тест")
    assert repo.get_cfo_detail_source(cfo_id) == "detail", \
        "перезаливка сбросила признак — колонка у дирекции пропадёт"


def test_реестр_показывает_источник_детализации(client):
    make_cfo(client, "Первая дирекция", "Основной бюджет", "4420_ПО", 100_000)
    cfo_id = repo.find_cfo("Первая дирекция")["id"]
    client.patch(f"/api/registry/cfo/{cfo_id}", json={"detail_source": "detail"})
    items = client.get("/api/registry/cfo").json()["items"]
    наш = next(i for i in items if i["id"] == cfo_id)
    assert наш["detail_source"] == "detail"


def test_пустая_правка_цфо_отклоняется(client):
    make_cfo(client, "Первая дирекция", "Основной бюджет", "4420_ПО", 100_000)
    cfo_id = repo.find_cfo("Первая дирекция")["id"]
    assert client.patch(f"/api/registry/cfo/{cfo_id}", json={}).status_code == 422


def test_чужое_значение_источника_не_принимается(client):
    make_cfo(client, "Первая дирекция", "Основной бюджет", "4420_ПО", 100_000)
    cfo_id = repo.find_cfo("Первая дирекция")["id"]
    assert client.patch(f"/api/registry/cfo/{cfo_id}",
                        json={"detail_source": "что-нибудь"}).status_code == 422


def test_финотдел_заводит_цфо_без_бюджета(client):
    """Дирекция, которая бюджет ещё не подала, заводится руками.

    До этого ЦФО появлялось только из импорта — вместе с первыми строками,
    а значит новой дирекции негде было взять блок в шаблоне.
    """
    response = client.post("/api/registry/cfo", json={"name": "Пятая дирекция"})
    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "Пятая дирекция"

    names = [item["name"] for item in client.get("/api/registry/cfo").json()["items"]]
    assert "Пятая дирекция" in names


def test_новое_цфо_получает_блок_в_шаблоне(client):
    """Ради этого всё и заводится: дирекции нужно место под бюджет.

    Шаблон перечисляет активные ЦФО справочника, поэтому заведённая вручную
    дирекция получает свой блок — и ей есть куда вписать первый бюджет.
    """
    import openpyxl, io as _io

    def cfo_names(content: bytes) -> set[str]:
        ws = openpyxl.load_workbook(_io.BytesIO(content), data_only=True)["Бюджеты ЦФО"]
        return {str(c.value).strip() for row in ws.iter_rows() for c in row
                if isinstance(c.value, str)}

    before = cfo_names(client.get("/api/export/budget-template.xlsx?year=2026").content)
    client.post("/api/registry/cfo", json={"name": "Пятая дирекция"})
    after = cfo_names(client.get("/api/export/budget-template.xlsx?year=2026").content)

    assert "Пятая дирекция" not in before
    assert "Пятая дирекция" in after


def test_дубль_цфо_не_заводится(client):
    client.post("/api/registry/cfo", json={"name": "Пятая дирекция"})
    again = client.post("/api/registry/cfo", json={"name": "пятая дирекция "})
    assert again.status_code == 422
    assert "уже есть" in again.json()["detail"]


def test_руководителю_завести_цфо_нельзя(client):
    cfo_id = repo.ensure_cfo("Дирекция А")
    response = client.post("/api/registry/cfo", json={"name": "Пятая дирекция"},
                           headers={"X-User": f"cfo:{cfo_id}"})
    assert response.status_code == 403
