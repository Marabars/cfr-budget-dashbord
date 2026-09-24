/* Вкладка «Карточка ЦФО»: строки бюджета по месяцам, добавление и удаление строк. */
(function () {
  "use strict";

  var card = null;
  var cfoId = null;
  var addKind = "budget";
  var editing = false;
  var filters = null;
  var rowsById = {};

  var FILTER_FIELDS = [
    { key: "article", title: "Статья оборотов" },
    { key: "counterparty", title: "Контрагент" },
    { key: "contract", title: "Договор" },
    { key: "detail_text", title: "Детализация" }
  ];

  /* Детализация строки: своё поле, иначе комментарий из файла. */
  function detailText(row) {
    return row.detail || row.comment || "";
  }

  function fieldValue(row, key) {
    return String((key === "detail_text" ? detailText(row) : row[key]) || "");
  }

  function allRows() {
    if (!card) return [];
    return card.budgets.reduce(function (acc, b) { return acc.concat(b.rows); }, []);
  }

  function initFilters() {
    if (filters) return;
    var host = document.getElementById("cfo-filters");
    filters = {};
    FILTER_FIELDS.forEach(function (f) {
      var filter = U.multiFilter(f.title, function () { if (card) render(card); });
      filters[f.key] = filter;
      host.appendChild(filter.node);
    });
  }

  function refreshFilterOptions() {
    var seen = {};
    Object.keys(filters).forEach(function (key) { seen[key] = {}; });
    allRows().forEach(function (row) {
      Object.keys(seen).forEach(function (key) { seen[key][fieldValue(row, key)] = true; });
    });
    Object.keys(filters).forEach(function (key) {
      filters[key].setOptions(Object.keys(seen[key]));
    });
  }

  function passes(row) {
    return Object.keys(filters).every(function (key) {
      var chosen = filters[key].selected();
      return !chosen.length || chosen.indexOf(fieldValue(row, key)) >= 0;
    });
  }

  function head(cfg) {
    var row = document.getElementById("cfo-head");
    U.clear(row);
    ["№", "Статья оборотов", "Контрагент", "Договор", "Детализация"].forEach(function (title) {
      row.appendChild(U.th(title, title === "№" ? "" : "wrap"));
    });
    ["Бюджет", "Итого&nbsp;опер&nbsp;план", "Факт", "Остаток бюджета", "Свободный лимит"]
      .forEach(function (title) { row.appendChild(U.th(title, "num")); });
    U.MONTHS_SHORT.forEach(function (name, i) {
      var closed = (i + 1) <= cfg.closed_through;
      // в две строки: месяц сверху, вид суммы снизу
      row.appendChild(U.th(name + "<br><span class='th-kind'>" +
        (closed ? "факт" : "план") + "</span>", "num month-col"));
    });
  }

  function monthCell(row, index, cfg) {
    var fact = row.fact_months[index];
    var claim = row.claim_months[index];
    var plan = row.plan_months[index];
    var closed = (index + 1) <= cfg.closed_through;

    if (fact && claim) {
      return U.el("td", { class: "num", html:
        "<b>" + U.fmt(fact) + "</b><br><i class='dim'>" + U.fmt(claim) + "</i>" });
    }
    if (fact) return U.el("td", { class: "num", html: "<b>" + U.fmt(fact) + "</b>" });
    if (claim) return U.el("td", { class: "num dim", html: "<i>" + U.fmt(claim) + "</i>" });
    if (plan && !closed) return U.el("td", { class: "num dim", html: "<i>" + U.fmt(plan) + "</i>" });
    return U.el("td", { class: "num dim", text: "—" });
  }

  function rowCells(row, cfg) {
    var del = U.el("button", { class: "mini", title: "Удалить строку", text: "✕" });
    del.onclick = function (event) {
      event.stopPropagation();
      API.deleteRow(row.id)
        .then(function () { U.toast("Строка удалена"); App.reload(); })
        .catch(function (e) { U.toast(e.message, "error"); });
    };
    var cells = [
      U.el("td", {}, [U.el("div", { class: "no-cell" }, [
        U.el("span", { text: row.row_no || "•" }), del])]),
      Inline.cell(row.id, "article", row.article, "wrap", editing),
      Inline.cell(row.id, "counterparty", row.counterparty || (editing ? "" : "—"), "wrap", editing),
      Inline.cell(row.id, "contract", row.contract || (editing ? "" : "—"), "wrap", editing),
      editing
        ? Inline.cell(row.id, "detail_text", detailText(row), "wrap", true)
        : U.el("td", { class: "wrap" }, [U.el("div", {
            class: "clamp", title: detailText(row), text: detailText(row) || "—" })]),
      Inline.cell(row.id, "plan_year", U.fmt(row.plan_year), "num n-plan", editing),
      U.tdn(row.operplan), U.tdn(row.fact, "n-fact"),
      U.tdn(row.cash_remain, row.cash_remain < 0 ? "neg" : ""),
      U.tdn(row.free_limit, row.free_limit < 0 ? "neg" : "pos")
    ];
    for (var i = 0; i < 12; i++) cells.push(monthCell(row, i, cfg));
    return cells;
  }

  /* ---------- правка ячеек ---------- */

  function paint(td, row, field) {
    if (field === "plan_year") td.textContent = U.fmt(row.plan_year);
    else if (field === "detail_text") td.textContent = detailText(row);
    else td.textContent = row[field] || (editing ? "" : "—");
  }

  /* Что уходит на сервер при правке ячейки. null — значение не изменилось. */
  function payloadFor(field, text, row) {
    if (field === "plan_year") {
      var value = U.parseSum(text);
      if (value === row.plan_year) return null;
      if (value < 0) throw new Error("Годовая сумма не может быть отрицательной");
      return { plan_year: value };
    }
    if (field === "detail_text") {
      if (text === detailText(row)) return null;
      return { detail: text };
    }
    var current = row[field] || "";
    if (text === current || (text === "—" && !current)) return null;
    if (field === "article" && !text) throw new Error("Статья оборотов не может быть пустой");
    var payload = {};
    payload[field] = text;
    return payload;
  }

  function applied(row, saved) {
    ["article", "counterparty", "contract", "detail", "comment"].forEach(function (key) {
      if (key in saved) row[key] = saved[key];
    });
    row.plan_year = Number(saved.plan_year);
    row.cash_remain = row.plan_year - row.fact;
    row.free_limit = row.plan_year - row.operplan;
  }

  /* Пересчитанные числа строки обновляем на месте: перерисовка всей таблицы
     отобрала бы фокус у ячейки, в которую пользователь уже перешёл. */
  function repaintRow(row) {
    var tr = document.querySelector('***REMOVED***t-cfo tr[data-row="' + row.id + '"]');
    if (!tr) return;
    var cells = tr.children;
    if (cells.length < 10) return;
    cells[5].textContent = U.fmt(row.plan_year);
    cells[8].textContent = U.fmt(row.cash_remain);
    cells[8].className = "num " + (row.cash_remain < 0 ? "neg" : "");
    cells[9].textContent = U.fmt(row.free_limit);
    cells[9].className = "num " + (row.free_limit < 0 ? "neg" : "pos");
  }

  function factRow(fact, parentNo) {
    var cells = [
      U.el("td", { class: "dim", text: "↳ №" + (parentNo || "-") }),
      U.el("td", { class: "wrap", text: fact.article || "" }),
      U.el("td", { class: "wrap", text: fact.counterparty || "—" }),
      U.el("td", { class: "wrap", text: fact.contract || "—" }),
      U.el("td", { class: "wrap" }, [U.el("div", { class: "clamp", text: fact.purpose || "—" })]),
      U.el("td", { class: "num dim", text: "—" }),
      U.tdn(fact.amount), U.tdn(fact.amount, "n-fact"),
      U.el("td", { class: "num dim", text: "—" }),
      U.el("td", { class: "num dim", text: "—" })
    ];
    var month = Number((fact.pay_date || "").slice(5, 7));
    for (var i = 1; i <= 12; i++) {
      cells.push(i === month
        ? U.el("td", { class: "num", html: "<b>" + U.fmt(fact.amount) + "</b>" })
        : U.el("td", { class: "num dim", text: "—" }));
    }
    return U.el("tr", { class: "child" }, cells);
  }

  function render(payload) {
    card = payload;
    var cfg = payload.settings;
    var totals = payload.totals;

    U.kpi(document.getElementById("cfo-kpis"), [
      { label: "Бюджет года", value: U.fmtShort(totals.plan_year) + " ₽",
        sub: payload.budgets.length + " бюджет(а) в ЦФО", tone: "k-accent" },
      { label: "Факт — оплачено", value: U.fmtShort(totals.fact) + " ₽",
        sub: (totals.plan_year ? (totals.pct * 100).toFixed(1) : 0) + "% освоено", tone: "k-good" },
      { label: "Заявки в работе", value: U.fmtShort(totals.claims) + " ₽",
        sub: "поданы, ещё не оплачены", tone: "k-warm" },
      { label: "Остаток бюджета", value: U.fmtShort(totals.cash_remain) + " ₽",
        sub: "бюджет − факт: ещё не оплачено", tone: "k-accent" },
      { label: "Свободный лимит", value: U.fmtShort(totals.free_limit) + " ₽",
        sub: "остаток − заявки", subClass: totals.free_limit < 0 ? "neg" : "pos",
        tone: totals.free_limit < 0 ? "k-crit" : "k-good" }
    ]);

    head(cfg);
    var body = document.querySelector("***REMOVED***t-cfo tbody");
    U.clear(body);

    initFilters();
    rowsById = {};
    allRows().forEach(function (row) { rowsById[row.id] = row; });

    var hasRows = payload.budgets.some(function (b) { return b.rows.length; });
    if (!hasRows) {
      body.appendChild(U.empty(22,
        "В этом ЦФО пока нет строк бюджета. Добавьте строку кнопкой «+ Добавить строку»."));
    }

    var shown = 0;
    payload.budgets.forEach(function (budget) {
      var rows = budget.rows.filter(passes);
      if (!rows.length) return;
      shown += rows.length;
      body.appendChild(U.el("tr", { class: "group" }, [
        U.el("td", { colspan: 22, text: budget.name })
      ]));
      rows.forEach(function (row) {
        var tr = U.el("tr", { class: row.source === "manual" ? "manual" : "",
          "data-row": row.id }, rowCells(row, cfg));
        body.appendChild(tr);
        // в режиме правки вложенные платежи прячем: они не редактируются и мешают попадать по ячейкам
        if (!editing) {
          (row.facts || []).forEach(function (fact) {
            body.appendChild(factRow(fact, row.row_no));
          });
        }
      });
    });
    if (hasRows && !shown) {
      body.appendChild(U.empty(22, "Под фильтр ничего не подошло — снимите часть условий."));
    }
    document.getElementById("cfo-count").textContent = shown + " из " + allRows().length + " строк";
    document.querySelector("***REMOVED***t-cfo").classList.toggle("editing", editing);
    refreshFilterOptions();

    document.getElementById("cfo-block-title").textContent =
      payload.budgets.length > 1
        ? "Строки бюджета — " + payload.budgets.length + " бюджета"
        : "Строки бюджета";
    refreshFormOptions();
  }

  /* ---------- форма добавления ---------- */

  function refreshFormOptions() {
    if (!card) return;
    U.fillSelect(document.getElementById("a-budget"),
      card.budgets.map(function (b) { return { id: b.id, name: b.name }; }), "name", "name");

    var parents = [];
    card.budgets.forEach(function (b) {
      b.rows.forEach(function (row) {
        parents.push({
          id: row.id,
          text: "№" + (row.row_no || "-") + " · " + row.article +
            " · свободно " + U.fmt(row.free_limit) + " ₽"
        });
      });
    });
    var select = document.getElementById("a-parent");
    if (parents.length) {
      U.fillSelect(select, parents, "id", "text");
    } else {
      select.innerHTML = "";
      select.appendChild(U.el("option", { value: "", text: "нет строк бюджета — сначала создайте лимит" }));
    }

    var articles = document.getElementById("dl-articles");
    U.clear(articles);
    var seen = {};
    card.budgets.forEach(function (b) {
      b.rows.forEach(function (row) {
        if (row.article && !seen[row.article]) {
          seen[row.article] = true;
          articles.appendChild(U.el("option", { value: row.article }));
        }
      });
    });
  }

  function syncForm() {
    var isFact = addKind === "fact";
    document.getElementById("add-title").textContent = isFact
      ? "Фактический расход — привязать к лимиту существующей строки"
      : "Новая строка бюджета";
    document.getElementById("w-parent").hidden = !isFact;
    document.getElementById("w-spread").hidden = isFact;
    document.getElementById("a-save").textContent = isFact ? "Добавить расход" : "Добавить строку";
    document.getElementById("w-month").hidden =
      !isFact && document.getElementById("a-spread").value !== "one";
  }

  function value(id) { return document.getElementById(id).value; }

  function save() {
    var err = document.getElementById("a-err");
    err.style.color = "";
    err.textContent = "";

    var article = value("a-article").replace(/^\s+|\s+$/g, "");
    var amount = U.parseSum(value("a-sum"));
    var isFact = addKind === "fact";
    var month = Number(value("a-month")) + 1;

    if (!article) { err.textContent = "Укажите статью оборотов"; return; }
    if (amount <= 0) { err.textContent = "Укажите сумму больше нуля"; return; }

    var request;
    if (isFact) {
      var rowId = Number(value("a-parent"));
      if (!rowId) { err.textContent = "Нет строки бюджета для привязки"; return; }
      request = API.createFact({
        row_id: rowId,
        pay_date: card.settings.year + "-" + ("0" + month).slice(-2) + "-15",
        amount: amount, article: article,
        counterparty: value("a-cp"), contract: value("a-contract"),
        purpose: value("a-detail"), out_of_budget: document.getElementById("a-oob").checked
      });
    } else {
      request = API.createRow({
        cfo_id: cfoId, budget_name: value("a-budget") || "Основной бюджет",
        article: article, counterparty: value("a-cp"), contract: value("a-contract"),
        detail: value("a-detail"), plan_year: amount,
        spread: value("a-spread"), month: month
      });
    }

    request.then(function (result) {
      ["a-article", "a-cp", "a-contract", "a-detail", "a-sum"].forEach(function (id) {
        document.getElementById(id).value = "";
      });
      document.getElementById("a-oob").checked = false;
      if (result && result.warning) U.toast(result.warning, "error");
      err.style.color = "var(--good)";
      err.textContent = isFact ? "Расход добавлен" : "Строка добавлена";
      window.setTimeout(function () { err.textContent = ""; err.style.color = ""; }, 2500);
      App.reload();
    }).catch(function (e) { err.textContent = e.message; });
  }

  window.CfoCard = {
    render: render,
    setCfo: function (id) { cfoId = id; },
    load: function (id) {
      cfoId = id;
      return API.cfoCard(id).then(render);
    },
    init: function () {
      var monthSelect = document.getElementById("a-month");
      U.fillSelect(monthSelect, U.MONTHS_FULL.map(function (name, i) {
        return { value: String(i), text: name };
      }), "value", "text");
      monthSelect.value = String(new Date().getMonth());

      U.chips(document.getElementById("add-kind"), "data-kind", function (kind) {
        addKind = kind;
        syncForm();
      });
      document.getElementById("a-spread").onchange = syncForm;
      document.getElementById("a-cancel").onclick = function () {
        document.getElementById("add-form").hidden = true;
      };
      document.getElementById("a-save").onclick = save;
      document.getElementById("add-row-btn").onclick = function () {
        var form = document.getElementById("add-form");
        form.hidden = !form.hidden;
        if (!form.hidden) {
          refreshFormOptions();
          syncForm();
          document.getElementById("a-article").focus();
        }
      };
      Inline.bind(document.getElementById("t-cfo"), {
        row: function (id) { return rowsById[id]; },
        payload: payloadFor,
        applied: applied,
        paint: paint,
        after: repaintRow
      });
      document.getElementById("cfo-edit").onclick = function () {
        editing = !editing;
        this.classList.toggle("primary", editing);
        this.textContent = editing ? "✓ Готово" : "✎ Редактировать";
        document.getElementById("cfo-edit-note").hidden = !editing;
        if (card) render(card);
      };
      document.getElementById("cfo-reset").onclick = function () {
        Object.keys(filters || {}).forEach(function (key) { filters[key].clear(); });
        if (card) render(card);
      };
      document.getElementById("cfo-export").onclick = function () {
        API.download("cfo", cfoId).catch(function (e) { U.toast(e.message, "error"); });
      };
    }
  };
})();