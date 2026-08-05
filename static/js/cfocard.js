/* Вкладка «Карточка ЦФО»: строки бюджета по месяцам, добавление и удаление строк. */
(function () {
  "use strict";

  var card = null;
  var cfoId = null;
  var addKind = "budget";

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
      U.el("td", { class: "wrap", text: row.article }),
      U.el("td", { class: "wrap", text: row.counterparty || "—" }),
      U.el("td", { class: "wrap", text: row.contract || "—" }),
      U.el("td", { class: "wrap" }, [U.el("div", {
        class: "clamp", title: row.detail || row.comment || "",
        text: row.detail || row.comment || "—"
      })]),
      U.tdn(row.plan_year, "n-plan"), U.tdn(row.operplan), U.tdn(row.fact, "n-fact"),
      U.tdn(row.cash_remain, row.cash_remain < 0 ? "neg" : ""),
      U.tdn(row.free_limit, row.free_limit < 0 ? "neg" : "pos")
    ];
    for (var i = 0; i < 12; i++) cells.push(monthCell(row, i, cfg));
    return cells;
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

    var hasRows = payload.budgets.some(function (b) { return b.rows.length; });
    if (!hasRows) {
      body.appendChild(U.empty(22,
        "В этом ЦФО пока нет строк бюджета. Добавьте строку кнопкой «+ Добавить строку»."));
    }

    payload.budgets.forEach(function (budget) {
      body.appendChild(U.el("tr", { class: "group" }, [
        U.el("td", { colspan: 22, text: budget.name })
      ]));
      budget.rows.forEach(function (row) {
        var tr = U.el("tr", { class: row.source === "manual" ? "manual" : "" }, rowCells(row, cfg));
        body.appendChild(tr);
        (row.facts || []).forEach(function (fact) {
          body.appendChild(factRow(fact, row.row_no));
        });
      });
    });

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
      document.getElementById("cfo-export").onclick = function () {
        API.download("cfo", cfoId).catch(function (e) { U.toast(e.message, "error"); });
      };
    }
  };
})();