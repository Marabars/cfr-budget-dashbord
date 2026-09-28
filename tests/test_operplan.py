"""Тесты вкладки «Оперплан»: импорт листа, слои, повтор года, замок, правка.

Файлы-фикстуры собираются на месте — тесты не зависят от рабочего файла
ликвидности на сетевом диске.
"""
from __future__ import annotations

import io

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app import db, operplan, repo
from app.importers import cfo_budgets
from app.main import app

MONTH_NAMES = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
               "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]

IT = "Первая дирекция"
HR = "Вторая дирекция"


***REMOVED*** ---------- фикстуры ----------

def make_budgets_sheet() -> bytes:
    """Лист «Бюджеты ЦФО» в раскладке рабочего файла: шапка в 3-й строке."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Бюджеты ЦФО"

    header = ["Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
              "Комментарий", "ИТОГО"] + MONTH_NAMES
    for col, value in enumerate(header, start=1):
        ws.cell(row=3, column=col, value=value)

    def put(row, values, months, total=None):
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)
        ws.cell(row=row, column=7, value=sum(months) if total is None else total)
        for m, amount in enumerate(months):
            ws.cell(row=row, column=8 + m, value=amount or None)

    ***REMOVED*** блок ИТ: два бюджета, детализация заполнена
    put(4, ["ИТОГО", IT, None, "Бюджет обязательных затрат"],
        [100_000, 50_000] + [0] * 10, total=150_000)
    put(5, ["4411_Оборудование", IT, "Астра ООО", "Договор №1", "ИТ инфраструктура",
            "Серверы"], [100_000] + [0] * 11)
    put(6, ["4411_Оборудование", IT, None, None, None, "Картриджи"],
        [0, 50_000] + [0] * 10)

    put(7, ["ИТОГО", IT, None, "Бюджет развития"], [0, 0, 200_000] + [0] * 9,
        total=200_000)
    put(8, ["4430_Разработка", IT, "Софт ООО", "Договор №2", "Платформа", "Доработки"],
        [0, 0, 200_000] + [0] * 9)

    ***REMOVED*** блок ДУП: детализации нет, только комментарий; одна строка с чужой подписью ЦФО
    put(9, ["ИТОГО", HR, None, None], [15_000] + [10_000] * 10 + [60_000], total=175_000)
    put(10, ["4109_Обучение", HR, None, None, None, "Английский"], [0] * 11 + [30_000])
    put(11, ["4109_Обучение", HR, None, None, None, "Библиотека"], [0] * 11 + [20_000])
    put(12, ["4110_Соцрасходы", HR, "Подрядчик ООО", "Договор №3", None, "Подарки"],
        [10_000] * 12)
    put(13, ["4110_Соцрасходы", "Эпсилон", None, None, None, "Через другое ЮЛ"],
        [5_000] + [0] * 11)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def make_articles_sheet() -> bytes:
    """Лист «ЦФО Статьи»: шапка смещена вправо и вниз, название ЦФО тянется по блоку."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ЦФО Статьи"
    ws.cell(row=2, column=2, value="Соответсвие статей ЦФО")
    ws.cell(row=4, column=2, value="ЦФО -Держатель бюджета ")
    ws.cell(row=4, column=3, value="Статьи управленческого учета, характерные для ЦФО")
    ws.cell(row=5, column=2, value=HR)
    ws.cell(row=5, column=3, value="4109_Обучение")
    ws.cell(row=6, column=3, value="4110_Соцрасходы")        ***REMOVED*** ЦФО тянется сверху
    ws.cell(row=7, column=3, value="4114_Командировочные")   ***REMOVED*** статьи нет в строках бюджета
    ws.cell(row=8, column=2, value="Бухгалтерия")            ***REMOVED*** такого ЦФО в бюджетах нет
    ws.cell(row=8, column=3, value="4106_Аудит")
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDGET_DB", str(tmp_path / "test.db"))
    db.set_db_path(tmp_path / "test.db")
    db.init_db()
    db.set_setting("year", "2026")
    db.set_setting("operplan_year", "2027")
    db.set_setting("operplan_base_year", "2026")
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def loaded(client):
    """Слой планирования с загруженным базовым 2026 годом."""
    result = operplan.import_budgets(make_budgets_sheet(), "бюджеты.xlsx", 2026, "Тест")
    assert result["rows"] == 7
    return result


***REMOVED*** ---------- разбор листа ----------

def test_держатель_бюджета_берётся_из_строки_итого(loaded):
    """Строка с подписью «Эпсилон» лежит внутри блока ДУП и остаётся за ДУП."""
    rows = repo.list_rows(2026, layer=operplan.LAYER)
    gasfor = [r for r in rows if r["comment"] == "Через другое ЮЛ"]
    assert len(gasfor) == 1
    assert gasfor[0]["cfo_name"] == HR
    ***REMOVED*** прежняя подпись не теряется
    assert "Эпсилон" in gasfor[0]["approver_comment"]


def test_бюджеты_ит_разложены_по_двум_блокам(loaded):
    budgets = {b["name"] for b in repo.list_budgets(2026, layer=operplan.LAYER)}
    assert "Бюджет обязательных затрат" in budgets
    assert "Бюджет развития" in budgets


def test_контрольная_сумма_блока_сверяется():
    parsed = cfo_budgets.parse(make_budgets_sheet())
    assert cfo_budgets.check_totals(parsed) == []


def test_расхождение_итого_попадает_в_отчёт():
    """ИТОГО блока занижено — импорт обязан об этом сказать, а не молча сойтись."""
    wb = openpyxl.load_workbook(io.BytesIO(make_budgets_sheet()))
    wb["Бюджеты ЦФО"].cell(row=9, column=7, value=1)   ***REMOVED*** ИТОГО блока ДУП
    buffer = io.BytesIO()
    wb.save(buffer)
    parsed = cfo_budgets.parse(buffer.getvalue())
    mismatches = cfo_budgets.check_totals(parsed)
    assert len(mismatches) == 1
    assert mismatches[0]["cfo"] == HR
    assert mismatches[0]["declared"] == 1


def test_детализация_у_ит_из_бюджета_у_остальных_комментарий(client, loaded):
    view = operplan.view(2026)
    blocks = {b["cfo_name"] + "|" + b["budget_name"]: b for b in view["blocks"]}

    it = blocks[IT + "|Бюджет обязательных затрат"]
    assert it["detail_source"] == "detail"
    server = next(r for r in it["rows"] if r["counterparty"] == "Астра ООО")
    assert server["detail_text"] == "ИТ инфраструктура"

    hr = blocks[HR + "|Основной бюджет"]
    assert hr["detail_source"] == "comment"
    english = next(r for r in hr["rows"] if r["comment"] == "Английский")
    assert english["detail_text"] == "Английский"


def test_у_ит_пустая_детализация_подменяется_комментарием(loaded):
    """Иначе у ИТ колонка была бы пустой там, где в файле заполнен только комментарий."""
    view = operplan.view(2026)
    it = next(b for b in view["blocks"] if b["budget_name"] == "Бюджет обязательных затрат")
    cartridges = next(r for r in it["rows"] if r["comment"] == "Картриджи")
    assert cartridges["detail"] == ""
    assert cartridges["detail_text"] == "Картриджи"


***REMOVED*** ---------- слои не смешиваются ----------

def test_слой_планирования_не_виден_дашборду(client, loaded):
    dashboard = client.get("/api/dashboard").json()
    assert dashboard["cards"] == []
    assert dashboard["totals"]["plan_year"] == 0
    assert operplan.view(2026)["totals"]["rows_count"] == 7


def test_строки_исполнения_не_видны_оперплану(client):
    cfo_id = repo.ensure_cfo(IT)
    client.post("/api/rows", json={"cfo_id": cfo_id, "article": "4420_ПО",
                                   "plan_year": 500_000, "spread": "even"})
    assert client.get("/api/dashboard").json()["totals"]["plan_year"] == 500_000
    assert client.get("/api/operplan?year=2026").json()["totals"]["rows_count"] == 0


def test_одноимённый_бюджет_живёт_в_обоих_слоях(client, loaded):
    """UNIQUE бюджета включает слой — иначе импорт упал бы на уже занятом имени."""
    cfo_id = repo.ensure_cfo(IT)
    main_id = repo.ensure_budget(cfo_id, 2026, "Бюджет обязательных затрат")
    plan_id = repo.ensure_budget(cfo_id, 2026, "Бюджет обязательных затрат",
                                 layer=operplan.LAYER)
    assert main_id != plan_id


***REMOVED*** ---------- повтор бюджета прошлого года ----------

def test_повтор_года_переносит_все_строки_с_разбивкой(client, loaded):
    base = operplan.view(2026)["totals"]
    result = operplan.copy_year("Тест", 2026, 2027)
    assert result["copied"] == 7 and result["skipped"] == 0

    plan = operplan.view(2027)["totals"]
    assert plan["rows_count"] == 7
    assert plan["plan_year"] == pytest.approx(base["plan_year"])
    assert plan["months"] == pytest.approx(base["months"])


def test_индексация_умножает_суммы(client, loaded):
    base = operplan.view(2026)["totals"]["plan_year"]
    operplan.copy_year("Тест", 2026, 2027, index_pct=10)
    assert operplan.view(2027)["totals"]["plan_year"] == pytest.approx(base * 1.1, rel=1e-6)


def test_повторный_запуск_ничего_не_задваивает(client, loaded):
    operplan.copy_year("Тест", 2026, 2027)
    again = operplan.copy_year("Тест", 2026, 2027)
    assert again["copied"] == 0
    assert again["skipped"] == 7
    assert operplan.view(2027)["totals"]["rows_count"] == 7


def test_строки_с_одинаковым_ключом_не_схлопываются(client, loaded):
    """У ДУП две строки одной статьи без контрагента и договора — обе обязаны переехать."""
    operplan.copy_year("Тест", 2026, 2027)
    rows = repo.list_rows(2027, layer=operplan.LAYER)
    training = [r for r in rows if r["article"] == "4109_Обучение"]
    assert len(training) == 2
    assert {r["comment"] for r in training} == {"Английский", "Библиотека"}


def test_индексация_за_пределами_разумного_отклоняется(client, loaded):
    response = client.post("/api/operplan/copy-year", json={"index_pct": -150})
    assert response.status_code == 422


def test_копирование_в_тот_же_год_отклоняется(client, loaded):
    with pytest.raises(ValueError):
        operplan.copy_year("Тест", 2026, 2026)


***REMOVED*** ---------- были в базовом году, нет в плане ----------

def test_пропавшие_строки_находятся_по_статье_контрагенту_договору(client, loaded):
    operplan.copy_year("Тест", 2026, 2027)
    assert operplan.missing_rows(2027)["count"] == 0

    rows = repo.list_rows(2027, layer=operplan.LAYER)
    victim = next(r for r in rows if r["article"] == "4430_Разработка")
    repo.delete_row(int(victim["id"]))

    missing = operplan.missing_rows(2027)
    assert missing["count"] == 1
    assert missing["items"][0]["article"] == "4430_Разработка"
    assert missing["total"] == pytest.approx(200_000)


def test_добавить_в_план_возвращает_строку(client, loaded):
    operplan.copy_year("Тест", 2026, 2027)
    rows = repo.list_rows(2027, layer=operplan.LAYER)
    repo.delete_row(int(next(r for r in rows if r["article"] == "4430_Разработка")["id"]))

    missing = operplan.missing_rows(2027)
    response = client.post(f"/api/operplan/missing/{missing['items'][0]['id']}/add?year=2027")
    assert response.status_code == 201
    assert operplan.missing_rows(2027)["count"] == 0

    restored = next(r for r in repo.list_rows(2027, layer=operplan.LAYER)
                    if r["article"] == "4430_Разработка")
    months = repo.plan_months(2027, layer=operplan.LAYER)[int(restored["id"])]
    assert months[2] == pytest.approx(200_000)


***REMOVED*** ---------- KPI ----------

def test_kpi_считает_оба_года_и_помнит_что_факта_нет(client, loaded):
    operplan.copy_year("Тест", 2026, 2027, index_pct=25)
    kpi = client.get("/api/operplan").json()["kpi"]
    assert kpi["plan_year"] == 2027 and kpi["base_year"] == 2026
    assert kpi["plan_total"] == pytest.approx(kpi["base_total"] * 1.25, rel=1e-6)
    assert kpi["base_ratio"] == pytest.approx(1 / 1.25, rel=1e-6)
    assert kpi["fact_loaded"] is False
    assert kpi["base_fact"] == 0


***REMOVED*** ---------- замок ----------

def test_замок_закрывает_правку_руководителю_но_не_финотделу(client, loaded):
    cfo_id = repo.ensure_cfo(HR)
    row_id = int(next(r for r in repo.list_rows(2026, layer=operplan.LAYER)
                      if r["cfo_id"] == cfo_id)["id"])

    assert client.post("/api/operplan/lock",
                       json={"year": 2026, "locked": True}).status_code == 200

    blocked = client.patch(f"/api/rows/{row_id}", json={"counterparty": "Нельзя"},
                           headers={"X-User": f"cfo:{cfo_id}"})
    assert blocked.status_code == 403
    assert "заблокировано" in blocked.json()["detail"]

    assert client.patch(f"/api/rows/{row_id}", json={"counterparty": "Можно"}).status_code == 200


def test_замок_ставит_только_финотдел(client, loaded):
    cfo_id = repo.ensure_cfo(HR)
    response = client.post("/api/operplan/lock", json={"year": 2026, "locked": True},
                           headers={"X-User": f"cfo:{cfo_id}"})
    assert response.status_code == 403


def test_замок_виден_в_ответе_вкладки(client, loaded):
    cfo_id = repo.ensure_cfo(HR)
    client.post("/api/operplan/lock", json={"year": 2026, "locked": True})
    view = client.get("/api/operplan?year=2026", headers={"X-User": f"cfo:{cfo_id}"}).json()
    assert view["locked"] is True
    assert view["can_edit"] is False
    assert client.get("/api/operplan?year=2026").json()["can_edit"] is True


def test_удаление_строки_при_замке_закрыто_руководителю(client, loaded):
    cfo_id = repo.ensure_cfo(HR)
    row_id = int(next(r for r in repo.list_rows(2026, layer=operplan.LAYER)
                      if r["cfo_id"] == cfo_id)["id"])
    client.post("/api/operplan/lock", json={"year": 2026, "locked": True})
    assert client.delete(f"/api/rows/{row_id}",
                         headers={"X-User": f"cfo:{cfo_id}"}).status_code == 403


def test_руководитель_правит_и_удаляет_свою_строку_залитого_бюджета(client, loaded):
    """Без замка руководитель ЦФО редактирует уже залитый бюджет своего ЦФО."""
    cfo_id = repo.ensure_cfo(HR)
    head = {"X-User": f"cfo:{cfo_id}"}
    rows = [r for r in repo.list_rows(2026, layer=operplan.LAYER) if r["cfo_id"] == cfo_id]
    row_id = int(rows[0]["id"])

    assert client.get("/api/operplan?year=2026", headers=head).json()["can_edit"] is True

    patched = client.patch(f"/api/rows/{row_id}", json={"counterparty": "Свой контрагент"},
                           headers=head)
    assert patched.status_code == 200
    assert patched.json()["row"]["counterparty"] == "Свой контрагент"

    assert client.delete(f"/api/rows/{row_id}", headers=head).status_code == 200
    assert repo.get_row(row_id) is None


def test_kpi_показывает_насколько_набран_план_от_базы(client, loaded):
    """Шкала первой плитки растёт по мере наполнения плана и не делится на ноль."""
    assert client.get("/api/operplan").json()["kpi"]["plan_ratio"] == 0.0
    operplan.copy_year("Тест", 2026, 2027, index_pct=25)
    assert client.get("/api/operplan").json()["kpi"]["plan_ratio"] == pytest.approx(1.25,
                                                                                    rel=1e-6)


def test_руководитель_не_правит_чужое_цфо(client, loaded):
    hr_id = repo.ensure_cfo(HR)
    it_row = int(next(r for r in repo.list_rows(2026, layer=operplan.LAYER)
                      if r["cfo_name"] == IT)["id"])
    response = client.patch(f"/api/rows/{it_row}", json={"counterparty": "Чужое"},
                            headers={"X-User": f"cfo:{hr_id}"})
    assert response.status_code == 403


***REMOVED*** ---------- правка строки ----------

def test_правка_месяцев_пересчитывает_годовую_сумму(client, loaded):
    row_id = int(repo.list_rows(2026, layer=operplan.LAYER)[0]["id"])
    months = [1000.0] * 12
    response = client.patch(f"/api/rows/{row_id}", json={"months": months})
    assert response.status_code == 200
    assert response.json()["row"]["plan_year"] == pytest.approx(12_000)


def test_правка_одного_поля_не_трогает_остальные(client, loaded):
    row = repo.list_rows(2026, layer=operplan.LAYER)[0]
    before = dict(row)
    client.patch(f"/api/rows/{row['id']}", json={"counterparty": "Новый контрагент"})
    after = repo.get_row(int(row["id"]))
    assert after["counterparty"] == "Новый контрагент"
    assert after["article"] == before["article"]
    assert after["plan_year"] == before["plan_year"]


def test_пустая_статья_при_правке_отклоняется(client, loaded):
    row_id = int(repo.list_rows(2026, layer=operplan.LAYER)[0]["id"])
    assert client.patch(f"/api/rows/{row_id}", json={"article": "  "}).status_code == 422


def test_отрицательный_месяц_отклоняется(client, loaded):
    row_id = int(repo.list_rows(2026, layer=operplan.LAYER)[0]["id"])
    months = [-1.0] + [0.0] * 11
    assert client.patch(f"/api/rows/{row_id}", json={"months": months}).status_code == 422


def test_неполный_список_месяцев_отклоняется(client, loaded):
    row_id = int(repo.list_rows(2026, layer=operplan.LAYER)[0]["id"])
    assert client.patch(f"/api/rows/{row_id}", json={"months": [1, 2, 3]}).status_code == 422


def test_правка_пишется_в_журнал(client, loaded):
    row_id = int(repo.list_rows(2026, layer=operplan.LAYER)[0]["id"])
    client.patch(f"/api/rows/{row_id}", json={"counterparty": "Журнальный"})
    audit = client.get("/api/audit").json()
    entry = next(a for a in audit if a["action"] == "Изменение строки бюджета")
    assert "Журнальный" in entry["change"]


def test_новая_строка_плана_попадает_в_нужный_слой_и_год(client, loaded):
    cfo_id = repo.ensure_cfo(HR)
    response = client.post("/api/operplan/rows?year=2027", json={
        "cfo_id": cfo_id, "budget_name": "Основной бюджет", "article": "4114_Командировочные",
        "counterparty": "Аэрофлот", "months": [1000.0] * 12,
    })
    assert response.status_code == 201
    view = client.get("/api/operplan?year=2027").json()
    assert view["totals"]["rows_count"] == 1
    assert view["totals"]["plan_year"] == pytest.approx(12_000)
    assert client.get("/api/dashboard").json()["totals"]["plan_year"] == 0


***REMOVED*** ---------- справочники ----------

def test_справочник_статей_объединяет_лист_и_строки(client, loaded):
    operplan.import_articles(make_articles_sheet(), "статьи.xlsx", "Тест")
    refs = client.get("/api/operplan/references?year=2026").json()
    hr_id = str(repo.ensure_cfo(HR))
    articles = refs["by_cfo"][hr_id]["articles"]
    assert "4109_Обучение" in articles          ***REMOVED*** есть и в листе, и в строках
    assert "4114_Командировочные" in articles   ***REMOVED*** только в листе-справочнике
    assert "4110_Соцрасходы" in articles


def test_неизвестное_цфо_справочника_не_теряется_молча(client, loaded):
    result = operplan.import_articles(make_articles_sheet(), "статьи.xlsx", "Тест")
    assert "Бухгалтерия" in result["unknown_cfo"]


def test_договоры_сгруппированы_по_контрагенту(client, loaded):
    refs = client.get("/api/operplan/references?year=2026").json()
    it_id = str(repo.ensure_cfo(IT))
    contracts = refs["by_cfo"][it_id]["contracts"]
    assert contracts["Астра ООО"] == ["Договор №1"]
    assert contracts["Софт ООО"] == ["Договор №2"]


def test_общий_список_собирает_все_цфо(client, loaded):
    refs = client.get("/api/operplan/references?year=2026").json()
    assert "4109_Обучение" in refs["all"]["articles"]
    assert "4411_Оборудование" in refs["all"]["articles"]
    assert "Астра ООО" in refs["all"]["counterparties"]


def test_руководителю_справочник_отдаёт_только_его_цфо(client, loaded):
    """«Показать все» — привилегия финотдела: чужие контрагенты не уезжают на клиент."""
    it_id = repo.ensure_cfo(IT)
    hr_id = repo.ensure_cfo(HR)
    refs = client.get("/api/operplan/references?year=2026",
                      headers={"X-User": f"cfo:{it_id}"}).json()

    assert set(refs["by_cfo"]) == {str(it_id)}
    assert str(hr_id) not in refs["by_cfo"]
    assert "4411_Оборудование" in refs["all"]["articles"]      ***REMOVED*** своё
    assert "4109_Обучение" not in refs["all"]["articles"]      ***REMOVED*** чужое
    assert "Астра ООО" in refs["all"]["counterparties"]

    у_финотдела = client.get("/api/operplan/references?year=2026").json()
    assert "4109_Обучение" in у_финотдела["all"]["articles"]


***REMOVED*** ---------- импорт через API ----------

def test_импорт_листа_через_api(client):
    response = client.post(
        "/api/import/cfo-budgets",
        files={"file": ("бюджеты.xlsx", make_budgets_sheet(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"year": "2026"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == 7
    assert client.get("/api/operplan?year=2026").json()["totals"]["rows_count"] == 7


def test_повторный_импорт_заменяет_слой_а_не_дополняет(client):
    payload = {
        "files": {"file": ("бюджеты.xlsx", make_budgets_sheet(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        "data": {"year": "2026"},
    }
    client.post("/api/import/cfo-budgets", **payload)
    second = client.post("/api/import/cfo-budgets", **payload)
    assert second.json()["removed"] == 7
    assert client.get("/api/operplan?year=2026").json()["totals"]["rows_count"] == 7


def test_импорт_доступен_только_финотделу(client):
    cfo_id = repo.ensure_cfo(HR)
    response = client.post(
        "/api/import/cfo-budgets",
        files={"file": ("бюджеты.xlsx", make_budgets_sheet(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"year": "2026"},
        headers={"X-User": f"cfo:{cfo_id}"},
    )
    assert response.status_code == 403


def test_предпросмотр_показывает_расхождения(client):
    wb = openpyxl.load_workbook(io.BytesIO(make_budgets_sheet()))
    wb["Бюджеты ЦФО"].cell(row=9, column=7, value=1)
    buffer = io.BytesIO()
    wb.save(buffer)
    response = client.post(
        "/api/import/inspect",
        files={"file": ("бюджеты.xlsx", buffer.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"kind": "cfo-budgets"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == 7
    assert len(body["mismatches"]) == 1


def test_лист_без_нужных_колонок_отклоняется(client):
    wb = openpyxl.Workbook()
    wb.active.cell(row=1, column=1, value="Чужой лист")
    buffer = io.BytesIO()
    wb.save(buffer)
    response = client.post(
        "/api/import/cfo-budgets",
        files={"file": ("чужой.xlsx", buffer.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"year": "2026"},
    )
    assert response.status_code == 422


***REMOVED*** ---------- миграция старой базы ----------

def test_миграция_добавляет_слой_и_не_трогает_данные(tmp_path, monkeypatch):
    """База, созданная до появления слоёв, должна открыться без потерь."""
    import sqlite3

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE cfo (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                          parent_id INTEGER, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE budget (id INTEGER PRIMARY KEY, cfo_id INTEGER NOT NULL REFERENCES cfo(id),
                             year INTEGER NOT NULL, name TEXT NOT NULL,
                             UNIQUE (cfo_id, year, name));
        CREATE TABLE budget_row (id INTEGER PRIMARY KEY,
                                 budget_id INTEGER NOT NULL REFERENCES budget(id),
                                 row_no INTEGER, article TEXT NOT NULL,
                                 counterparty TEXT NOT NULL DEFAULT '',
                                 contract TEXT NOT NULL DEFAULT '',
                                 detail TEXT NOT NULL DEFAULT '',
                                 comment TEXT NOT NULL DEFAULT '',
                                 approver_comment TEXT NOT NULL DEFAULT '',
                                 plan_year REAL NOT NULL DEFAULT 0,
                                 carryover INTEGER NOT NULL DEFAULT 1,
                                 source TEXT NOT NULL DEFAULT 'manual',
                                 created_by TEXT NOT NULL DEFAULT '',
                                 created_at TEXT NOT NULL DEFAULT (datetime('now')),
                                 deleted_at TEXT);
        INSERT INTO cfo(id, name) VALUES (1, 'Старое ЦФО');
        INSERT INTO budget(id, cfo_id, year, name) VALUES (7, 1, 2026, 'Основной бюджет');
        INSERT INTO budget_row(id, budget_id, article, plan_year)
            VALUES (42, 7, '4420_ПО', 999000);
    """)
    conn.commit()
    conn.close()

    monkeypatch.setenv("BUDGET_DB", str(path))
    db.set_db_path(path)
    db.init_db()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    budget = conn.execute("SELECT * FROM budget WHERE id = 7").fetchone()
    assert budget["layer"] == "main"
    assert budget["name"] == "Основной бюджет"
    row = conn.execute("SELECT * FROM budget_row WHERE id = 42").fetchone()
    assert row["plan_year"] == 999000
    assert row["budget_id"] == 7
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()

    ***REMOVED*** повторный запуск безвреден
    db.init_db()
    assert repo.list_rows(2026)[0]["plan_year"] == 999000


***REMOVED*** ---------- Excel: выгрузка, загрузка, факт ----------

def make_fact_sheet(hr_amount: float = 7_000, it_amount: float = 90_000,
                    extra: bool = False) -> bytes:
    """Факт в той же раскладке, что «Бюджеты ЦФО»: суммы — не план, а расход."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Бюджеты ЦФО"
    header = ["Статья оборотов", "ЦФО", "Контрагент", "Договор", "Детализация",
              "Комментарий", "ИТОГО"] + MONTH_NAMES
    for col, value in enumerate(header, start=1):
        ws.cell(row=3, column=col, value=value)

    def put(row, values, months):
        for col, value in enumerate(values, start=1):
            ws.cell(row=row, column=col, value=value)
        ws.cell(row=row, column=7, value=sum(months))
        for m, amount in enumerate(months):
            ws.cell(row=row, column=8 + m, value=amount or None)

    put(4, ["ИТОГО", IT, None, "Бюджет обязательных затрат"], [it_amount] + [0] * 11)
    put(5, ["4411_Оборудование", IT, "Астра ООО", "Договор №1", "ИТ инфраструктура",
            "Серверы"], [it_amount] + [0] * 11)
    put(6, ["ИТОГО", HR, None, None], [hr_amount] + [0] * 11)
    put(7, ["4110_Соцрасходы", HR, "Подрядчик ООО", "Договор №3", None, "Подарки"],
        [hr_amount] + [0] * 11)
    if extra:
        put(8, ["4999_Непредвиденное", HR, None, None, None, "Не было в бюджете"],
            [0, 3_000] + [0] * 10)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_выгрузка_бюджета_читается_импортёром_обратно(client, loaded):
    """Круг замкнут: что выгрузили, то и заливается без потери строк и сумм."""
    before = client.get("/api/operplan?year=2026").json()["totals"]
    data = client.get("/api/export/budget.xlsx?year=2026")
    assert data.status_code == 200
    assert data.headers["content-type"].startswith("application/vnd.openxml")

    again = operplan.import_budgets(data.content, "выгрузка.xlsx", 2026, "Тест")
    after = client.get("/api/operplan?year=2026").json()["totals"]
    assert again["rows"] == before["rows_count"]
    assert after["rows_count"] == before["rows_count"]
    assert after["plan_year"] == pytest.approx(before["plan_year"], rel=1e-9)


def test_руководитель_выгружает_только_свой_цфо(client, loaded):
    hr_id = repo.ensure_cfo(HR)
    content = client.get("/api/export/budget.xlsx?year=2026",
                         headers={"X-User": f"cfo:{hr_id}"}).content
    parsed = cfo_budgets.parse(content)
    assert {row["cfo"] for row in parsed["rows"]} == {HR}


def test_загрузка_факта_ложится_на_строки_плана(client, loaded):
    result = operplan.import_fact(make_fact_sheet(), "факт.xlsx", 2026, "Тест")
    assert result["matched"] == 2 and result["created"] == 0

    kpi = client.get("/api/operplan").json()["kpi"]
    assert kpi["fact_loaded"] is True
    assert kpi["base_fact"] == pytest.approx(97_000)


def test_факт_без_строки_в_плане_заводит_её_и_не_задваивает(client, loaded):
    first = operplan.import_fact(make_fact_sheet(extra=True), "факт.xlsx", 2026, "Тест")
    assert first["created"] == 1
    rows_after_first = len(repo.list_rows(2026, layer=operplan.LAYER))

    second = operplan.import_fact(make_fact_sheet(extra=True), "факт.xlsx", 2026, "Тест")
    assert second["created"] == 0 and second["matched"] == 3
    assert len(repo.list_rows(2026, layer=operplan.LAYER)) == rows_after_first


def test_повтор_факта_переносит_суммы_факта_а_не_бюджета(client, loaded):
    operplan.import_fact(make_fact_sheet(), "факт.xlsx", 2026, "Тест")
    result = client.post("/api/operplan/copy-year",
                         json={"from_year": 2026, "to_year": 2027, "source": "fact"}).json()
    assert result["copied"] == 2          ***REMOVED*** перенеслись только строки с фактом
    plan = client.get("/api/operplan?year=2027").json()
    assert plan["totals"]["plan_year"] == pytest.approx(97_000)


def test_повтор_факта_без_факта_отклоняется(client, loaded):
    response = client.post("/api/operplan/copy-year",
                           json={"from_year": 2026, "to_year": 2027, "source": "fact"})
    assert response.status_code == 422
    assert "не загружен" in response.json()["detail"]


def test_руководитель_повторяет_бюджет_только_своего_цфо(client, loaded):
    hr_id = repo.ensure_cfo(HR)
    response = client.post("/api/operplan/copy-year", json={"from_year": 2026, "to_year": 2027},
                           headers={"X-User": f"cfo:{hr_id}"})
    assert response.status_code == 200

    plan = repo.list_rows(2027, layer=operplan.LAYER)
    assert plan, "строки должны перенестись"
    assert {r["cfo_name"] for r in plan} == {HR}, "чужие ЦФО переноситься не должны"


def test_руководитель_заливает_бюджет_не_стирая_чужие_цфо(client, loaded):
    hr_id = repo.ensure_cfo(HR)
    it_before = [r for r in repo.list_rows(2026, layer=operplan.LAYER)
                 if r["cfo_name"] == IT]

    response = client.post(
        "/api/operplan/import",
        data={"year": "2026", "kind": "plan"},
        files={"file": ("бюджет.xlsx", make_budgets_sheet(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"X-User": f"cfo:{hr_id}"},
    )
    assert response.status_code == 200
    assert response.json()["foreign"] == 3       ***REMOVED*** три строки ИТ в файле пропущены

    it_after = [r for r in repo.list_rows(2026, layer=operplan.LAYER)
                if r["cfo_name"] == IT]
    assert len(it_after) == len(it_before), "чужие строки не должны стираться"
