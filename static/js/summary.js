/* Вкладка «Сводка»: таблица по ЦФО и реестр «вне бюджета». */
(function () {
  "use strict";

  var filter = "all";
  var data = null;

  function passes(item, pace) {
    var t = item.totals;
    if (filter === "over") return t.fact > t.plan_year;
    if (filter === "risk") {
      return t.fact > t.plan_year || t.free_limit < 0 || t.pct > pace + 0.15;
    }
    return true;
  }

  function renderTable() {
    if (!data) return;
    var body = document.querySelector("#t-sum tbody");
    var foot = document.querySelector("#t-sum tfoot");
    U.clear(body);
    U.clear(foot);

    var pace = data.settings.pace;
    var rows = data.cards.filter(function (item) { return passes(item, pace); })
      .sort(function (a, b) { return b.totals.plan_year - a.totals.plan_year; });
    var sum = { plan: 0, fact: 0, claims: 0, operplan: 0, cash: 0, free: 0 };

    if (!rows.length) {
      body.appendChild(U.empty(9, "Нет бюджетов, подходящих под фильтр."));
    }

    rows.forEach(function (item) {
      var t = item.totals;
      var tr = U.el("tr", { title: "Открыть карточку ЦФО", style: "cursor:pointer" }, [
        U.el("td", { class: "wrap" }, [
          U.el("div", { class: "cfo-name", text: item.cfo_name }),
          U.el("div", { class: "mono-s", text: item.name })
        ]),
        U.tdn(t.plan_year, "n-plan"), U.tdn(t.fact, "n-fact"), U.tdn(t.claims, "n-claim"),
        U.tdn(t.operplan),
        U.tdn(t.cash_remain, t.cash_remain < 0 ? "neg" : ""),
        U.tdn(t.free_limit, t.free_limit < 0 ? "neg" : "pos"),
        U.el("td", {}, [U.meter(t.pct, pace, item.status)]),
        U.el("td", {}, [U.badge(item.status, item.status_text)])
      ]);
      tr.onclick = function () { App.openCfo(item.cfo_id); };
      body.appendChild(tr);

      sum.plan += t.plan_year; sum.fact += t.fact; sum.claims += t.claims;
      sum.operplan += t.operplan; sum.cash += t.cash_remain; sum.free += t.free_limit;
    });

    if (rows.length) {
      foot.appendChild(U.el("tr", {}, [
        U.el("td", { text: "ИТОГО по показанным" }),
        U.tdn(sum.plan), U.tdn(sum.fact), U.tdn(sum.claims), U.tdn(sum.operplan),
        U.tdn(sum.cash), U.tdn(sum.free, sum.free < 0 ? "neg" : ""),
        U.el("td"), U.el("td")
      ]));
    }

    document.getElementById("sum-sub").textContent =
      "на " + data.settings.as_of + " · ожидаемый темп освоения " + (pace * 100).toFixed(0) + "%";
  }

  function renderOutOfBudget(items) {
    var body = document.querySelector("#t-oob tbody");
    var foot = document.querySelector("#t-oob tfoot");
    U.clear(body);
    U.clear(foot);
    if (!items.length) {
      body.appendChild(U.empty(7, "Расходов вне бюджета нет."));
      return;
    }
    var total = 0;
    items.forEach(function (f) {
      total += Number(f.amount);
      body.appendChild(U.el("tr", {}, [
        U.td(f.pay_date),
        U.el("td", { class: "wrap", text: f.cfo_name || "—" }),
        U.el("td", { class: "wrap", text: f.counterparty }),
        U.el("td", { class: "wrap", text: f.purpose }),
        U.tdn(f.amount, "neg"),
        U.el("td", { class: "dim", text: f.matched_by || "—" }),
        U.el("td", {}, [U.el("button", {
          class: "btn sm", text: "Снять признак",
          on: { click: function () {
            API.flagOutOfBudget(f.id, false)
              .then(function () { U.toast("Признак «вне бюджета» снят"); App.reload(); })
              .catch(function (e) { U.toast(e.message, "error"); });
          } }
        })])
      ]));
    });
    foot.appendChild(U.el("tr", {}, [
      U.el("td", { text: "ИТОГО вне бюджета" }), U.el("td"), U.el("td"), U.el("td"),
      U.tdn(total, "neg"), U.el("td"), U.el("td")
    ]));
  }

  window.Sum = {
    render: function (payload) { data = payload; renderTable(); },
    renderOutOfBudget: renderOutOfBudget,
    init: function () {
      U.chips(document.getElementById("sum-filter"), "data-f", function (value) {
        filter = value;
        renderTable();
      });
    }
  };
})();