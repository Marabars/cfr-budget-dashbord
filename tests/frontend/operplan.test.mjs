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
  base_plan_year: null, classifier: "МРК",
};

/* У каждой дирекции свой набор: сервер руководителю чужие статьи и не отдаёт,
   а финотделу они приезжают порознь и сводятся в «all» под галочку. */
/* Строка прошлого года: на вкладке она база для сравнения и правке не подлежит. */
const BASE = {
  id: 20, row_no: 1, budget_id: 2, budget_name: "Основной бюджет",
  cfo_id: 1, cfo_name: IT, article: "4411_Оборудование", counterparty: "Астра ООО",
  contract: "Договор №1", detail: "Серверы прошлого года", comment: "",
  approver_comment: "", detail_source: "detail", detail_text: "Серверы прошлого года",
  plan_year: 90000, months: [90000, ...Array(MONTHS - 1).fill(0)], source: "import",
  base_plan_year: null,
};

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

/** Поднимает вкладку в jsdom. Возвращает окно, журнал вызовов API и помощники.
    cfoList задаёт доступные дирекции: от их числа зависит, спросит ли кнопка,
    куда добавлять строку. */
async function mount(cfoList = [{ id: 1, name: IT }, { id: 2, name: HR }], extra = []) {
  let added = null;                       // строка, заведённая кнопкой «+ расход»
  const calls = [];

  const view = (year) => {
    const rows = year === 2027
      ? [FILLED, ...extra, ...(added ? [added] : [])] : [BASE];
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
        budget_id: year === 2027 ? 1 : 2,
        budget_name: "Основной бюджет", cfo_id: 1, cfo_name: IT,
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
    operplanRenumber: (year) => {
      calls.push({ kind: "renumber", year });
      return Promise.resolve({ year, renumbered: 3 });
    },
    download: (name, cfoId, params) => {
      calls.push({ kind: "download", name, params });
      return Promise.resolve();
    },
  };

  const dom = new JSDOM(asset("index.html"), {
    runScripts: "outside-only", pretendToBeVisual: true,
  });
  const { window } = dom;
  /* Настоящий css нужен не для красоты: позицию списка считает JS по координатам
     окна, и без position: fixed из стилей она применялась бы относительно ячейки —
     список уезжал бы за пределы видимой области. Проверяем это ниже. */
  const style = window.document.createElement("style");
  style.textContent = asset("css/app.css");
  window.document.head.appendChild(style);
  // jsdom не умеет прокрутку, а код уводит новую строку в видимую часть таблицы
  window.Element.prototype.scrollIntoView = function () {};
  window.API = API;
  ["js/util.js", "js/inline.js", "js/operplan.js"].forEach((f) => window.eval(asset(f)));

  window.Operplan.setCfoList(cfoList);
  window.Operplan.init();
  await window.Operplan.load();
  await settle(window);

  return {
    window, calls,
    $: (sel) => window.document.querySelector(sel),
    $$: (sel) => Array.from(window.document.querySelectorAll(sel)),
    click: (node) => node.dispatchEvent(new window.MouseEvent("click", { bubbles: true })),
    fire: (node, type) => node.dispatchEvent(new window.Event(type)),
    // в браузере фокус поднимает и focus, и всплывающий focusin — нужны оба
    focus: (node) => {
      node.dispatchEvent(new window.FocusEvent("focus"));
      node.dispatchEvent(new window.FocusEvent("focusin", { bubbles: true }));
    },
    /* Полный клик мышью по ячейке: mousedown, фокус, mouseup, click. Именно
       click, всплывая до document, гасил только что открытый список, поэтому
       проверять фокусом в одиночку недостаточно. */
    clickCell: (node) => {
      node.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true }));
      node.focus();
      node.dispatchEvent(new window.FocusEvent("focus"));
      node.dispatchEvent(new window.FocusEvent("focusin", { bubbles: true }));
      node.dispatchEvent(new window.MouseEvent("mouseup", { bubbles: true }));
      node.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
    },
    // обработчик висит на document в фазе перехвата, поэтому всплытие не нужно
    scrollTable: () => window.document.querySelector(".scroll.tall")
      .dispatchEvent(new window.Event("scroll")),
    styleOf: (node) => window.getComputedStyle(node),
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

  it("держит «+ расход» в шапке карточки, а не в заголовках блоков", () => {
    assert.equal(t.$$("***REMOVED***t-op tr.group .add-row").length, 0);
    const button = t.$("***REMOVED***op-add-row");
    assert.ok(button, "кнопка в шапке таблицы");
    assert.equal(button.previousElementSibling.id, "op-save",
      "порядок в шапке: «Свернуть все», карандаш, «Сохранить», «+ расход»");
  });

  it("по умолчанию только читается: ячейки закрыты", () => {
    const row = t.$('***REMOVED***t-op tbody tr[data-id="10"]');
    assert.ok(row, "строка плана нарисована");
    assert.equal(row.querySelectorAll("td[contenteditable]").length, 0,
      "любой клик по ячейке не должен начинать правку");
    assert.equal(t.$("***REMOVED***op-save").hidden, true, "сохранять нечего");
    assert.equal(t.$("***REMOVED***op-edit-note"), null, "плашки-инструкции на вкладке нет");
  });

  it("даёт карандаш, который открывает правку", () => {
    const pencil = t.$("***REMOVED***op-edit-mode");
    assert.equal(pencil.hidden, false);
    assert.equal(pencil.textContent, "✎", "правка закрыта — карандаш целый");

    t.click(pencil);
    const row = t.$('***REMOVED***t-op tbody tr[data-id="10"]');
    assert.ok(row.querySelector("td[contenteditable]"), "ячейки открылись");
    assert.equal(t.$("***REMOVED***op-save").hidden, false, "появилась кнопка сохранения");
    assert.equal(t.$("***REMOVED***op-edit-mode").textContent, "✎̸", "карандаш перечёркнут");
  });

  it("«Сохранить» закрепляет нумерацию и закрывает правку", async () => {
    assert.equal(t.$("***REMOVED***op-save").hidden, false, "мы всё ещё в правке");
    t.click(t.$("***REMOVED***op-save"));
    await settle(t.window, 150);
    const renumber = t.calls.find((c) => c.kind === "renumber");
    assert.ok(renumber, "номера строк проставляются по кнопке, а не замком");
    assert.equal(renumber.year, 2027, "нумеруется планируемый год");
    assert.equal(t.$('***REMOVED***t-op tbody tr[data-id="10"] td[contenteditable]'), null,
      "ячейки снова закрыты");
    assert.equal(t.$("***REMOVED***op-save").hidden, true);
  });

  it("замок финотдела — отдельная кнопка с висячим замком", () => {
    const lock = t.$("***REMOVED***op-lock");
    assert.equal(lock.hidden, false, "финотдел замок видит");
    assert.ok(lock.classList.contains("icon"));
    assert.equal(lock.textContent, "🔓", "план открыт");
    assert.match(lock.title, /для всех/, "замок общий, в отличие от карандаша");
  });
});

describe("вкладка «Бюджет»: порядок строк", () => {
  /* Строки одной статьи должны идти вместе, статьи — по алфавиту, внутри
     статьи — контрагенты. Заголовков у статей нет, речь только о порядке. */
  const row = (id, article, counterparty) => ({
    ...FILLED, id, row_no: id, article, counterparty, contract: "",
  });

  let t;
  before(async () => {
    t = await mount([{ id: 1, name: IT }], [
      row(31, "4430_Разработка", "Софт ООО"),
      row(32, "4411_Оборудование", "Барс ООО"),
      row(33, "4411_Оборудование", "Вектор ООО"),
    ]);
  });

  it("собирает статьи вместе и сортирует их по алфавиту", () => {
    const shown = t.$$("***REMOVED***t-op tbody tr[data-id]")
      .map((tr) => Number(tr.getAttribute("data-id")));
    // 10 и 32, 33 — «4411_Оборудование» (Астра, Барс, Вектор), затем 31 — «4430_Разработка»
    assert.deepEqual(shown, [10, 32, 33, 31]);
  });

  it("нумерует строки по порядку показа, а не по номеру из файла", () => {
    const shown = t.$$("***REMOVED***t-op tbody tr[data-id]").map((tr) => ({
      id: Number(tr.getAttribute("data-id")),
      no: tr.querySelector(".no-cell span").textContent,
    }));
    /* В строках лежат row_no 10, 31, 32, 33 — в отсортированной таблице они
       выглядели вперемешку, поэтому в колонке № стоит позиция. */
    assert.deepEqual(shown.map((r) => r.no), ["1", "2", "3", "4"]);
    assert.deepEqual(shown.map((r) => r.id), [10, 32, 33, 31]);
  });

  it("не меняет нумерацию от фильтра", () => {
    const chip = t.$$("***REMOVED***op-filters .fwrap")[1];        // фильтр «Статья оборотов»
    t.click(chip.querySelector(".fbtn"));
    const option = Array.from(chip.querySelectorAll(".fopt"))
      .find((label) => label.textContent.indexOf("4430_Разработка") >= 0);
    const box = option.querySelector("input");
    box.checked = true;
    t.fire(box, "change");

    const shown = t.$$("***REMOVED***t-op tbody tr[data-id]").map((tr) => ({
      id: Number(tr.getAttribute("data-id")),
      no: tr.querySelector(".no-cell span").textContent,
    }));
    assert.deepEqual(shown, [{ id: 31, no: "4" }],
      "строка сохраняет свой номер в блоке, а не получает первый");
    box.checked = false;
    t.fire(box, "change");
  });

  it("держит незаполненную строку сверху блока", async () => {
    t.click(t.$("***REMOVED***op-add-row"));
    await settle(t.window, 60);
    const first = t.$("***REMOVED***t-op tbody tr[data-id]");
    assert.equal(first.getAttribute("data-id"), "99",
      "новую строку ещё заполняют — по алфавиту ей уезжать некуда");
    assert.ok(first.classList.contains("is-new"));
  });
});

describe("вкладка «Бюджет»: прошлый год", () => {
  let t;
  before(async () => {
    t = await mount();
    t.click(t.$("***REMOVED***op-edit-mode"));                  // правка включена
    const base = t.$$("***REMOVED***t-op tr.year-row").find((tr) => tr.textContent.indexOf("2026") >= 0);
    t.click(base);                                  // раскрываем раздел базы
    await settle(t.window, 40);
  });

  it("показывает строки базы, но править их не даёт", () => {
    const row = t.$('***REMOVED***t-op tbody tr[data-id="20"]');
    assert.ok(row, "строка 2026 года нарисована");
    assert.ok(row.classList.contains("y-past"), "и помечена как прошлый год");
    assert.equal(row.querySelectorAll("td[contenteditable]").length, 0,
      "прошлый год — база для сравнения, сервер правку и не примет");
    assert.equal(row.querySelectorAll("input").length, 0);
  });

  it("не предлагает удалить строку прошлого года", () => {
    const row = t.$('***REMOVED***t-op tbody tr[data-id="20"]');
    assert.equal(row.querySelector("button.mini"), null, "крестика быть не должно");
  });
});

describe("вкладка «Бюджет»: выбор дирекции для новой строки", () => {
  it("с одной доступной дирекцией заводит строку сразу, без вопросов", async () => {
    const t = await mount([{ id: 1, name: IT }]);
    assert.equal(t.$("***REMOVED***op-save").hidden, true, "правка ещё закрыта");
    t.click(t.$("***REMOVED***op-add-row"));
    await settle(t.window, 60);
    assert.equal(t.$("***REMOVED***op-add-menu"), null, "спрашивать нечего — меню не открывалось");
    const created = t.calls.find((c) => c.kind === "create");
    assert.ok(created, "строка заведена");
    assert.equal(created.payload.cfo_id, 1);
    assert.equal(t.$("***REMOVED***op-save").hidden, false, "кнопка сама включила правку");
    // курсор уезжает в статью, и её список сразу раскрыт — печатать можно не целясь
    assert.ok(t.$(".fpop-fixed:not([hidden]) .copt"), "список статей раскрыт сразу");
  });

  it("с несколькими — предлагает список тех же блоков, что в таблице", async () => {
    const t = await mount();
    t.click(t.$("***REMOVED***op-add-row"));
    await settle(t.window, 30);
    const shown = t.$$("***REMOVED***op-add-menu .copt").map((n) => n.textContent);
    assert.deepEqual(shown, [IT, HR], "по алфавиту: с строками и пустая");
    assert.ok(!t.calls.length, "до выбора дирекции ничего не создаём");
  });

  it("фильтр по ЦФО снимает вопрос", async () => {
    const t = await mount();
    // фильтр «ЦФО» — первый чип в шапке; отмечаем в нём дирекцию, как это делают мышью
    const chip = t.$$("***REMOVED***op-filters .fwrap")[0];
    t.click(chip.querySelector(".fbtn"));
    const option = Array.from(chip.querySelectorAll(".fopt"))
      .find((label) => label.textContent.indexOf(IT) >= 0);
    assert.ok(option, "в фильтре есть дирекция со строками");
    const box = option.querySelector("input");
    box.checked = true;
    t.fire(box, "change");
    await settle(t.window, 30);

    t.click(t.$("***REMOVED***op-add-row"));
    await settle(t.window, 60);
    const created = t.calls.find((c) => c.kind === "create");
    assert.ok(created, "дирекция понятна из фильтра — список не нужен");
    assert.equal(created.payload.cfo_id, 1);
  });
});

describe("вкладка «Бюджет»: новая строка", () => {
  let t;
  before(async () => {
    t = await mount();
    t.click(t.$("***REMOVED***op-add-row"));
    await settle(t.window, 30);
    const hr = t.$$("***REMOVED***op-add-menu .copt").find((n) => n.textContent === HR);
    hr.dispatchEvent(new t.window.MouseEvent("mousedown", { bubbles: true }));
    await settle(t.window, 60);
  });

  it("заводит пустую строку в выбранном ЦФО", () => {
    const created = t.calls.find((c) => c.kind === "create");
    assert.ok(created, "запрос на создание ушёл");
    assert.equal(created.payload.article, "");
    assert.equal(created.payload.cfo_id, 2, "ЦФО — из выбора под кнопкой");
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
    t.focus(article);
    const pop = t.$(".fpop-fixed:not([hidden])");
    assert.ok(pop, "внутри .scroll абсолютный список обрезался бы контейнером");
    assert.equal(t.styleOf(pop).position, "fixed",
      "координаты считаются по окну — без fixed список уедет мимо экрана");
    const shown = Array.from(pop.querySelectorAll(".copt")).map((n) => n.textContent);
    // строку заводили в ДУП — в списке статьи ДУП, а не соседней дирекции
    assert.deepEqual(shown, ["4109_Обучение", "4110_Соцрасходы"]);
  });

  it("держит список вне таблицы, иначе его накрывают закреплённые колонки", () => {
    const article = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    t.focus(article);
    const pop = t.$(".fpop-fixed:not([hidden])");
    assert.ok(pop, "список раскрыт");
    /* Колонки «№» и «Статья» закреплены слева: position: sticky с z-index создаёт
       контекст наложения, и список внутри такой ячейки накрывают закреплённые
       ячейки строк ниже — видна полоска, клик по ней попадает в чужую ячейку. */
    assert.equal(pop.parentNode, t.window.document.body, "список должен лежать в body");
    assert.ok(!t.$("***REMOVED***t-op").contains(pop), "и не внутри таблицы");
  });

  it("выбрасывает списки от ячеек, которых больше нет", () => {
    const article = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    t.focus(article);
    assert.ok(t.$$(".fpop-fixed").length > 0, "список создан");
    t.click(t.$("***REMOVED***op-edit-mode"));           // правка закрылась — строку перерисовали
    t.click(t.$("***REMOVED***op-edit-mode"));           // и открылась: ещё одна перерисовка
    const orphans = t.$$(".fpop-fixed").filter(
      (pop) => pop.anchor && !t.window.document.contains(pop.anchor));
    assert.deepEqual(orphans, [], "списки мёртвых ячеек в body копиться не должны");
  });

  it("не захлопывает список при прокрутке таблицы", () => {
    const article = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    t.focus(article);
    assert.ok(t.$(".fpop-fixed:not([hidden])"), "список раскрыт");
    /* Клик по полю у нижнего края сам заставляет браузер подкрутить таблицу.
       Если гасить список на любую прокрутку, он захлопывается сразу после
       открытия — именно это и выглядело как «подсказки не показываются». */
    t.scrollTable();
    assert.ok(t.$(".fpop-fixed:not([hidden])"), "список остался и переложился");

    // прокрутка самого списка положение не пересчитывает и его не закрывает
    const list = t.$(".fpop-fixed:not([hidden]) .flist");
    list.dispatchEvent(new t.window.Event("scroll", { bubbles: false }));
    assert.ok(t.$(".fpop-fixed:not([hidden])"), "список прокручивается сам по себе");
  });

  it("закрывает список, когда поле ушло из окна", () => {
    const article = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    t.focus(article);
    assert.ok(t.$(".fpop-fixed:not([hidden])"));
    // уводим поле далеко выше окна: висеть списку в пустоте незачем
    article.getBoundingClientRect = () => ({
      top: -900, bottom: -880, left: 0, right: 200, width: 200, height: 20,
    });
    t.scrollTable();
    assert.equal(t.$(".fpop-fixed:not([hidden])"), null);
  });

  it("снова раскрывает список, когда возвращаются в ту же ячейку", () => {
    const article = t.$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    t.focus(article);
    assert.ok(t.$(".fpop-fixed:not([hidden])"), "список раскрыт");

    // уходим со строки: клик мимо гасит списки
    t.window.document.body.dispatchEvent(new t.window.MouseEvent("click", { bubbles: true }));
    assert.equal(t.$(".fpop-fixed:not([hidden])"), null, "ушли — список закрыт");

    // и возвращаемся: список должен раскрыться снова, а не молчать
    t.focus(article);
    const pop = t.$(".fpop-fixed:not([hidden])");
    assert.ok(pop, "вернулись — список снова раскрыт");
    assert.ok(pop.querySelectorAll(".copt").length > 0, "и в нём есть значения");
  });

  it("убирает чужой список, когда фокус уходит в ячейку без списка", () => {
    const inputs = t.$$('***REMOVED***t-op tbody tr[data-id="99"] td.cell-pick input');
    t.focus(inputs[2]);                                  // договор — список есть
    assert.ok(t.$(".fpop-fixed:not([hidden])"), "список договоров раскрыт");
    t.focus(inputs[3]);                                  // детализация — списка нет
    assert.equal(t.$(".fpop-fixed:not([hidden])"), null,
      "иначе список висел бы поверх таблицы");
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

describe("вкладка «Бюджет»: подсказки при правке ячейки", () => {
  let t, cell;

  before(async () => {
    t = await mount();
    t.click(t.$("***REMOVED***op-edit-mode"));
    cell = t.$('***REMOVED***t-op tbody tr[data-id="10"] td[data-f="counterparty"]');
  });

  it("предлагает значения своего ЦФО прямо в ячейке", () => {
    t.focus(cell);
    const pop = t.$(".cell-suggest:not([hidden])");
    assert.ok(pop, "список подставлен к ячейке");
    assert.deepEqual(Array.from(pop.querySelectorAll(".copt")).map((n) => n.textContent),
      REFS.by_cfo[1].counterparties);
  });

  it("не гаснет от клика, которым его открыли", () => {
    for (const field of ["article", "counterparty", "contract"]) {
      const target = t.$(`***REMOVED***t-op tbody tr[data-id="10"] td[data-f="${field}"]`);
      t.clickCell(target);
      const pop = t.$(".cell-suggest:not([hidden])");
      assert.ok(pop, `список у «${field}» должен остаться открытым после клика`);
      assert.ok(pop.querySelectorAll(".copt").length > 0, "и со значениями");
    }
  });

  it("переносится на другую ячейку, а не множится", () => {
    t.clickCell(t.$('***REMOVED***t-op tbody tr[data-id="10"] td[data-f="article"]'));
    t.clickCell(t.$('***REMOVED***t-op tbody tr[data-id="10"] td[data-f="contract"]'));
    assert.equal(t.$$(".cell-suggest:not([hidden])").length, 1, "подсказка одна");
    const shown = t.$$(".cell-suggest .copt").map((n) => n.textContent);
    assert.deepEqual(shown, REFS.by_cfo[1].contracts["Астра ООО"],
      "и показывает договоры этого контрагента");
  });

  it("закрывается принудительно при перерисовке таблицы", () => {
    t.clickCell(t.$('***REMOVED***t-op tbody tr[data-id="10"] td[data-f="counterparty"]'));
    assert.ok(t.$(".cell-suggest:not([hidden])"), "список открыт");
    t.window.U.closePopups();
    assert.equal(t.$(".cell-suggest:not([hidden])"), null,
      "принудительное закрытие должно работать и при курсоре в ячейке");
  });

  it("сужает список по набранному тексту", () => {
    cell = t.$('***REMOVED***t-op tbody tr[data-id="10"] td[data-f="counterparty"]');
    t.clickCell(cell);
    cell.textContent = "Софт";
    cell.dispatchEvent(new t.window.Event("input", { bubbles: true }));
    const shown = t.$$(".cell-suggest .copt").map((n) => n.textContent);
    assert.deepEqual(shown, ["Софт ООО"]);
  });

  it("по выбору подставляет значение и сохраняет ячейку", async () => {
    cell = t.$('***REMOVED***t-op tbody tr[data-id="10"] td[data-f="counterparty"]');
    t.clickCell(cell);
    const option = t.$$(".cell-suggest .copt").find((n) => n.textContent === "Астра ООО");
    option.dispatchEvent(new t.window.MouseEvent("mousedown", { bubbles: true }));
    await settle(t.window);
    assert.equal(cell.textContent, "Астра ООО");
  });

  it("в ячейке без справочника списка не показывает", () => {
    const detail = t.$('***REMOVED***t-op tbody tr[data-id="10"] td[data-f="detail_text"]');
    t.focus(detail);
    assert.equal(t.$(".cell-suggest:not([hidden])"), null,
      "детализация — свободный текст");
  });
});

describe("вкладка «Бюджет»: сумма за год", () => {
  let t, sum, spread;

  before(async () => {
    t = await mount([{ id: 1, name: IT }]);
    t.click(t.$("***REMOVED***op-add-row"));
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

  it("при «не раскладывать» сумму не спрашивает", async () => {
    const before = t.calls.length;
    spread.value = "none";
    t.fire(spread, "change");
    await settle(t.window, 20);
    assert.equal(sum.readOnly, true, "поле только показывает итог");
    assert.match(sum.placeholder, /по месяцам/, "подсказка объясняет, откуда возьмётся");
    assert.equal(t.calls.length, before, "выбор раскладки сам ничего не пишет");
  });

  it("складывает ИТОГО из месяцев, которые вписали руками", async () => {
    spread.value = "none";
    t.fire(spread, "change");
    // правим два месяца прямо в таблице, как это делают мышью и клавиатурой
    for (const [index, value] of [[0, "5 000"], [3, "7 500"]]) {
      const cell = t.$(`***REMOVED***t-op td[data-id="99"][data-f="m${index}"]`);
      cell.textContent = value;
      cell.dispatchEvent(new t.window.FocusEvent("focusout", { bubbles: true }));
      await settle(t.window);
    }
    const months = t.lastPatch("months").payload.months;
    assert.equal(months[0], 5000);
    assert.equal(months[3], 7500);
    // в строке уже были суммы от предыдущих проверок — ИТОГО обязано сойтись
    // с суммой всех двенадцати месяцев, какой бы она ни была
    const total = months.reduce((acc, v) => acc + v, 0);
    assert.equal(sum.value, t.window.U.fmt(total), "ИТОГО подтянулось само");
  });

  it("отбивает отрицательную сумму", async () => {
    const before = t.calls.length;
    sum.value = "-5 000";
    t.fire(sum, "change");
    await settle(t.window);
    assert.equal(t.calls.length, before, "на сервер ничего не ушло");
  });
});


/* ---------- классификатор МРГ/МРК ---------- */

describe("вкладка «Бюджет»: классификатор", () => {
  const cellOf = (t, row) => row.children[2];

  it("стоит третьей колонкой — как в выгрузке Excel", async () => {
    const t = await mount();
    const head = t.$$("***REMOVED***op-head th").map((th) => th.textContent);
    assert.deepEqual(head.slice(0, 4),
      ["№", "Статья оборотов", "Классификатор", "Контрагент"]);
  });

  it("вне правки показывает значение текстом, без списка", async () => {
    const t = await mount();
    const row = t.$('***REMOVED***t-op tbody tr[data-id="10"]');
    const cell = cellOf(t, row);
    assert.equal(cell.textContent, "МРК");
    assert.equal(cell.querySelector("select"), null, "читать — значит не править");
  });

  it("в правке становится списком ровно из двух значений", async () => {
    const t = await mount();
    t.click(t.$("***REMOVED***op-edit-mode"));
    const row = t.$('***REMOVED***t-op tbody tr[data-id="10"]');
    const select = cellOf(t, row).querySelector("select");
    assert.ok(select, "в правке — список");
    assert.deepEqual(Array.from(select.options).map((o) => o.value), ["МРГ", "МРК"],
      "значений ровно два");
    assert.equal(select.value, "МРК", "показывает то, что в строке");
  });

  it("строка, пришедшая без классификатора, читается как МРГ", async () => {
    // у строки прошлого года поля нет вовсе — так выглядят строки до миграции
    const t = await mount();
    const base = t.$$("***REMOVED***t-op tr.year-row").find((tr) => tr.textContent.indexOf("2026") >= 0);
    t.click(base);
    await settle(t.window, 40);
    const row = t.$('***REMOVED***t-op tbody tr[data-id="20"]');
    assert.ok(row, "строка базы нарисована");
    assert.equal(cellOf(t, row).textContent, "МРГ");
  });

  it("смена значения уходит на сервер", async () => {
    const t = await mount();
    t.click(t.$("***REMOVED***op-edit-mode"));
    const select = cellOf(t, t.$('***REMOVED***t-op tbody tr[data-id="10"]')).querySelector("select");
    select.value = "МРГ";
    t.fire(select, "change");
    await settle(t.window);

    const patch = t.calls.filter((c) => c.kind === "patch").pop();
    assert.deepEqual(JSON.parse(JSON.stringify(patch.payload)), { classifier: "МРГ" });
  });

  it("у прошлого года правке не подлежит", async () => {
    const t = await mount();
    t.click(t.$("***REMOVED***op-edit-mode"));
    const base = t.$$("***REMOVED***t-op tr.year-row").find((tr) => tr.textContent.indexOf("2026") >= 0);
    t.click(base);
    await settle(t.window, 40);
    const past = t.$('***REMOVED***t-op tbody tr[data-id="20"]');
    assert.ok(past, "строка базы нарисована");
    assert.equal(cellOf(t, past).querySelector("select"), null,
      "базовый год — справка, править его нельзя");
  });

  it("фильтруется наравне с остальными колонками", async () => {
    const other = { ...FILLED, id: 11, article: "4430_Разработка",
      counterparty: "Софт ООО", classifier: "МРГ" };
    const t = await mount(undefined, [other]);
    assert.equal(t.$$("***REMOVED***t-op tbody tr[data-id]").length, 2, "до фильтра видны обе строки");
    const titles = t.$$("***REMOVED***op-filters .fwrap .fbtn").map((b) => b.textContent);
    assert.ok(titles.some((title) => title.indexOf("Классификатор") >= 0),
      "у колонки должен быть свой фильтр");

    const chip = t.$$("***REMOVED***op-filters .fwrap")[2];      // ЦФО, Статья, Классификатор
    t.click(chip.querySelector(".fbtn"));
    const values = Array.from(chip.querySelectorAll(".fopt")).map((l) => l.textContent.trim());
    assert.ok(values.indexOf("МРК") >= 0, "в списке есть значение из строк");

    const box = Array.from(chip.querySelectorAll(".fopt"))
      .find((label) => label.textContent.trim() === "МРК").querySelector("input");
    box.checked = true;
    t.fire(box, "change");
    await settle(t.window, 30);
    const shown = t.$$("***REMOVED***t-op tbody tr[data-id]").map((tr) => tr.getAttribute("data-id"));
    assert.deepEqual(shown, ["10"], "остаётся только строка с МРК");
  });
});

describe("вкладка «Бюджет»: выгрузка", () => {
  /* Обе кнопки обязаны идти через API.download: роль передаётся заголовком
     X-User, а переход по ссылке его не несёт — руководителю приезжал бы
     шаблон со всеми дирекциями. */
  it("шаблон и план уходят запросом, а не переходом по ссылке", async () => {
    const t = await mount();
    const before = t.window.location.href;

    t.click(t.$("***REMOVED***op-template"));
    t.click(t.$("***REMOVED***op-export"));
    await settle(t.window);

    const downloads = t.calls.filter((c) => c.kind === "download");
    assert.deepEqual(downloads.map((c) => c.name), ["budget-template", "budget"]);
    assert.deepEqual(downloads.map((c) => c.params.year), [2027, 2027]);
    assert.equal(t.window.location.href, before, "страница никуда не уходит");
  });
});
