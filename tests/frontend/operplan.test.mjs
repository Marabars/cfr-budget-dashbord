/* Вкладка «Бюджет» в настоящем DOM: pytest проверяет сервер, а внесение расхода
   живёт целиком на клиенте — списки в ячейках, подсветка новой строки, раскладка
   суммы по месяцам. Здесь index.html и js/* поднимаются в jsdom, сеть заменена
   заглушками window.API, а проверяется то, что делают руками: жмём «+ расход»,
   выбираем статью из списка, вписываем сумму.

   Запуск: npm install && npm test (нужен только jsdom). */
import { readFileSync } from "node:fs";
import { describe, it, before } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const asset = (rel) =>
  readFileSync(new URL(`../../static/${rel}`, import.meta.url), "utf8");

const IT = "Первая дирекция";
const HR = "Вторая дирекция";
const MONTHS = 12;

/* ---------- слепок ответов сервера ---------- */

function blankRow(id, cfoId, cfoName) {
  return {
    id, row_no: 2, budget_id: 1, budget_name: "Основной бюджет",
    cfo_id: cfoId, cfo_name: cfoName, article: "", counterparty: "", contract: "",
    detail: "", comment: "", approver_comment: "", detail_source: "detail",
    detail_text: "", plan_year: 0, months: Array(MONTHS).fill(0),
    source: "manual", base_plan_year: null,
  };
}

const FILLED = {
  id: 10, row_no: 1, budget_id: 1, budget_name: "Основной бюджет",
  cfo_id: 1, cfo_name: IT, article: "4411_Оборудование", counterparty: "Астра ООО",
  contract: "Договор №1", detail: "Серверы", comment: "", approver_comment: "",
  detail_source: "detail", detail_text: "Серверы", plan_year: 120000,
  months: [120000, ...Array(MONTHS - 1).fill(0)], source: "import",
  base_plan_year: null,
};

/* У каждой дирекции свой набор: сервер руководителю чужие статьи и не отдаёт,
   а финотделу они приезжают порознь и сводятся в «all» под галочку. */
const REFS = {
  by_cfo: {
    1: {
      articles: ["4411_Оборудование", "4430_Разработка"],
      counterparties: ["Астра ООО", "Софт ООО"],
      contracts: { "Астра ООО": ["Договор №1"] },
    },
    2: {
      articles: ["4109_Обучение", "4110_Соцрасходы"],
      counterparties: ["Подрядчик ООО"],
      contracts: { "Подрядчик ООО": ["Договор №3"] },
    },
  },
  all: {
    articles: ["4109_Обучение", "4110_Соцрасходы", "4411_Оборудование", "4430_Разработка"],
    counterparties: ["Астра ООО", "Подрядчик ООО", "Софт ООО"],
    contracts: ["Договор №1", "Договор №3"],
  },
};

/* ---------- стенд ---------- */

/** Поднимает вкладку в jsdom. Возвращает окно, журнал вызовов API и помощники. */
async function mount() {
  let added = null;                       // строка, заведённая кнопкой «+ расход»
  const calls = [];

  const view = (year) => {
    const rows = year === 2027 ? [FILLED, ...(added ? [added] : [])] : [];
    const total = rows.reduce((acc, r) => acc + r.plan_year, 0);
    return {
      year, plan_year_no: 2027, base_year_no: 2026, years: [2026, 2027],
      locked: false, can_edit: true, is_fin: true,
      kpi: {
        plan_year: 2027, base_year: 2026, plan_total: total, base_total: 0,
        base_ratio: 0, plan_ratio: 0, base_fact: 0, base_pct: 0,
        fact_loaded: false, plan_rows: rows.length, base_rows: 0,
      },
      totals: { plan_year: total, months: Array(MONTHS).fill(0), rows_count: rows.length },
      blocks: rows.length ? [{
        budget_id: 1, budget_name: "Основной бюджет", cfo_id: 1, cfo_name: IT,
        detail_source: "detail", rows, rows_count: rows.length,
        plan_year: total, months: Array(MONTHS).fill(0),
      }] : [],
    };
  };

  const API = {
    operplan: (year) => Promise.resolve(view(Number(year) || 2027)),
    operplanMissing: () => Promise.resolve({
      count: 0, items: [], total: 0, base_year: 2026, plan_year: 2027,
    }),
    operplanRefs: () => Promise.resolve(REFS),
    createOperplanRow: (payload, year) => {
      calls.push({ kind: "create", payload, year });
      added = blankRow(99, payload.cfo_id, payload.cfo_id === 1 ? IT : HR);
      return Promise.resolve({ id: 99, row: added });
    },
    patchRow: (id, payload) => {
      calls.push({ kind: "patch", id, payload });
      Object.assign(added, payload);
      if (payload.months) {
        added.plan_year = payload.months.reduce((acc, v) => acc + v, 0);
      }
      return Promise.resolve({ ok: true, row: { ...added } });
    },
    deleteRow: (id) => {
      calls.push({ kind: "delete", id });
      added = null;
      return Promise.resolve({ ok: true });
    },
  };

  const dom = new JSDOM(asset("index.html"), {
    runScripts: "outside-only", pretendToBeVisual: true,
  });
  const { window } = dom;
  // jsdom не умеет прокрутку, а код уводит новую строку в видимую часть таблицы
  window.Element.prototype.scrollIntoView = function () {};
  window.API = API;
  ["js/util.js", "js/inline.js", "js/operplan.js"].forEach((f) => window.eval(asset(f)));

  window.Operplan.setCfoList([{ id: 1, name: IT }, { id: 2, name: HR }]);
  window.Operplan.init();
  await window.Operplan.load();
  await settle(window);

  return {
    window, calls,
    $: (sel) => window.document.querySelector(sel),
    $$: (sel) => Array.from(window.document.querySelectorAll(sel)),
    click: (node) => node.dispatchEvent(new window.MouseEvent("click", { bubbles: true })),
    fire: (node, type) => node.dispatchEvent(new window.Event(type)),
    lastPatch: (field) => calls.filter(
      (c) => c.kind === "patch" && c.payload[field] !== undefined).pop(),
  };
}

/** Даёт промисам обработчиков доиграть: правка уходит через API и then(). */
function settle(window, ms = 40) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/* ---------- проверки ---------- */

describe("вкладка «Бюджет»: таблица", () => {
  let t;
  before(async () => { t = await mount(); });

  it("рисует блок с строками и заголовок дирекции без них", () => {
    assert.equal(t.$$("***REMOVED***t-op tr.group").length, 2);
    assert.equal(t.$$("***REMOVED***t-op tr.group.is-empty").length, 1,
      "у ДУП строк нет — должен быть заголовок-заготовка");
  });

  it("ставит «+ расход» в каждый заголовок, включая пустой", () => {
    assert.equal(t.$$("***REMOVED***t-op tr.group .add-row").length, 2);
  });

  it("заполненную строку правит текстом, без полей ввода", () => {
    const row = t.$('***REMOVED***t-op tbody tr[data-id="10"]');
    assert.ok(row, "строка плана нарисована");
    assert.equal(row.querySelectorAll("input").length, 0);
    assert.ok(row.querySelector("td[contenteditable]"), "ячейки правятся на месте");
  });
});

describe("вкладка «Бюджет»: новая строка", () => {
  let t;
  before(async () => {
    t = await mount();
    t.click(t.$("***REMOVED***t-op tr.group.is-empty .add-row"));
    await settle(t.window, 60);
  });

  it("заводит пустую строку в том ЦФО, чей заголовок нажали", () => {
    const created = t.calls.find((c) => c.kind === "create");
    assert.ok(created, "запрос на создание ушёл");
    assert.equal(created.payload.article, "");
    assert.equal(created.payload.cfo_id, 2, "ЦФО берётся из заголовка блока");
    assert.equal(created.payload.budget_name, "Основной бюджет");
    assert.equal(created.year, 2027);
  });

  it("подсвечивает её и даёт списки в ячейках", () => {
    const row = t.$('***REMOVED***t-op tbody tr[data-id="99"]');
    assert.ok(row, "новая строка нарисована");
    assert.ok(row.classList.contains("is-new"), "строка подсвечена");
    assert.equal(row.querySelectorAll("td.cell-pick input").length, 4,
      "статья, контрагент, договор и детализация");
    assert.equal(row.querySelectorAll("td.cell-pick .combo-caret").length, 3,
      "у детализации списка нет — это свободный текст");
  });

  it("предлагает раскладку суммы на 14 вариантов", () => {
    const spread = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-sum .spread-in');
    assert.ok(spread, "выбор раскладки стоит в колонке ИТОГО");
    assert.equal(spread.options.length, MONTHS + 2, "равномерно, не раскладывать и 12 месяцев");
  });

  it("раскрывает список статей по координатам окна, а не внутри ячейки", () => {
    const article = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    article.dispatchEvent(new t.window.FocusEvent("focus"));
    const pop = t.$(".fpop-fixed:not([hidden])");
    assert.ok(pop, "внутри .scroll абсолютный список обрезался бы контейнером");
    const shown = Array.from(pop.querySelectorAll(".copt")).map((n) => n.textContent);
    // строку заводили в ДУП — в списке статьи ДУП, а не соседней дирекции
    assert.deepEqual(shown, ["4109_Обучение", "4110_Соцрасходы"]);
  });

  it("сохраняет выбранную статью", async () => {
    const article = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    article.value = "4110_Соцрасходы";
    t.fire(article, "change");
    await settle(t.window);
    assert.equal(t.lastPatch("article").payload.article, "4110_Соцрасходы");
  });

  it("галочкой «все статьи» показывает справочник по всем ЦФО", async () => {
    t.$("***REMOVED***op-a-all").checked = true;
    t.fire(t.$("***REMOVED***op-a-all"), "change");      // перерисовка: списки собираются заново
    await settle(t.window);
    const article = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    article.dispatchEvent(new t.window.FocusEvent("focus"));
    const shown = Array.from(t.$(".fpop-fixed:not([hidden])").querySelectorAll(".copt"))
      .map((n) => n.textContent);
    assert.deepEqual(shown, REFS.all.articles);
    t.$("***REMOVED***op-a-all").checked = false;
  });
});

describe("вкладка «Бюджет»: сумма за год", () => {
  let t, sum, spread;

  before(async () => {
    t = await mount();
    t.click(t.$("***REMOVED***t-op tr.group .add-row"));
    await settle(t.window, 60);
    sum = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-sum .sum-in');
    spread = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-sum .spread-in');
  });

  it("раскладывает годовую сумму равномерно", async () => {
    spread.value = "even";
    sum.value = "120 000";
    t.fire(sum, "change");
    await settle(t.window);
    const months = t.lastPatch("months").payload.months;
    assert.equal(months.length, MONTHS);
    assert.ok(months.every((v) => v === 10000), "по 10 000 в каждом месяце");
  });

  it("перерисовывает месяцы на месте, не теряя ввод", () => {
    const january = t.$('***REMOVED***t-op td[data-id="99"][data-f="m0"]');
    assert.match(january.textContent, /^10\s?000/);
    assert.ok(t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-sum .sum-in'),
      "поле суммы осталось полем, а не превратилось в текст");
  });

  it("кладёт всю сумму в выбранный месяц", async () => {
    spread.value = "2";
    sum.value = "60 000";
    t.fire(sum, "change");
    await settle(t.window);
    const months = t.lastPatch("months").payload.months;
    assert.equal(months[2], 60000);
    assert.equal(months.filter((v) => v).length, 1, "остальные месяцы пустые");
  });

  it("не раскладывает, когда выбрано «не раскладывать»", async () => {
    spread.value = "none";
    sum.value = "90 000";
    t.fire(sum, "change");
    await settle(t.window);
    const months = t.lastPatch("months").payload.months;
    assert.ok(months.every((v) => v === 0), "суммы вписывают по месяцам руками");
  });

  it("отбивает отрицательную сумму", async () => {
    const before = t.calls.length;
    sum.value = "-5 000";
    t.fire(sum, "change");
    await settle(t.window);
    assert.equal(t.calls.length, before, "на сервер ничего не ушло");
  });
});
