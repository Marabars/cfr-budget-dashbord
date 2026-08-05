/* Вкладка «Дашборд»: ключевые показатели и карточки ЦФО с батарейками. */
(function () {
  "use strict";

  var sort = "plan";
  var data = null;

  function kpis(d) {
    var t = d.totals;
    var items = [
      { label: "Бюджет " + d.settings.year, value: U.fmtShort(t.plan_year) + " ₽",
        sub: d.cards.length + " бюджетов", tone: "k-accent", hero: true },
      { label: "Факт — оплачено", value: U.fmtShort(t.fact) + " ₽",
        sub: (t.plan_year ? (t.fact / t.plan_year * 100).toFixed(1) : 0) + "% годового бюджета",
        tone: "k-good" },
      { label: "Заявки в работе", value: U.fmtShort(t.claims) + " ₽",
        sub: "обязательства, ещё не оплачены", tone: "k-warm" },
      { label: "Свободный лимит", value: U.fmtShort(t.free_limit) + " ₽",
        sub: "бюджет − факт − заявки",
        subClass: t.free_limit < 0 ? "neg" : "pos",
        tone: t.free_limit < 0 ? "k-crit" : "k-good" },
      { label: "Вне бюджета", value: U.fmtShort(d.out_of_budget_total) + " ₽",
        sub: d.out_of_budget_count + " записей за год", subClass: "neg",
        tone: d.out_of_budget_count ? "k-crit" : "" },
      { label: "ЦФО с превышением", value: String(d.over_count),
        sub: "перерасход или заявки сверх лимита",
        subClass: d.over_count ? "neg" : "pos",
        tone: d.over_count ? "k-crit" : "k-good" }
    ];
    U.kpi(document.getElementById("dash-kpis"), items);
    U.kpi(document.getElementById("sum-kpis"), items);
  }

  /* Одна величина — одна строка: название слева, сумма справа. */
  function line(label, hint, value, opts) {
    var settings = opts || {};
    return U.el("div", { class: "cc-line" + (settings.major ? " major" : "") }, [
      U.el("div", { class: "k" }, [label, hint ? U.el("small", { text: hint }) : null]),
      U.el("div", { class: "v " + (settings.tone || ""), text: U.fmt(value) + " ₽" })
    ]);
  }

  function card(item, pace) {
    var t = item.totals;
    var node = U.el("div", { class: "cfo-card st-" + item.status, title: "Открыть карточку ЦФО" }, [
      U.el("div", { class: "cc-head" }, [
        U.el("div", {}, [
          U.el("div", { class: "cc-title", text: item.cfo_name }),
          U.el("div", { class: "cc-sub", text: item.name })
        ]),
        U.badge(item.status, item.status_text)
      ]),
      U.el("div", { class: "cc-lines" }, [
        line("Бюджет на год", "", t.plan_year, { tone: "n-plan" }),
        line("Факт", "оплачено", t.fact, { tone: "n-fact" }),
        line("Заявки", "в работе, не оплачены", t.claims, { tone: "n-claim" })
      ]),
      U.battery(t.pct, pace),
      U.el("div", { class: "cc-lines cc-derived" }, [
        line("Остаток бюджета", "бюджет − факт", t.cash_remain,
             { tone: t.cash_remain < 0 ? "neg" : "" }),
        line("Свободный лимит", "остаток − заявки", t.free_limit,
             { tone: t.free_limit < 0 ? "neg" : "pos" })
      ])
    ]);
    if (item.out_of_budget) {
      node.appendChild(U.el("div", { class: "cc-oob",
        text: "вне бюджета: " + U.fmt(item.out_of_budget) + " ₽" }));
    }
    node.onclick = function () { App.openCfo(item.cfo_id); };
    return node;
  }

  function renderCards() {
    if (!data) return;
    var host = document.getElementById("dash-grid");
    U.clear(host);
    var cards = data.cards.slice();
    if (sort === "pct") cards.sort(function (a, b) { return b.totals.pct - a.totals.pct; });
    else if (sort === "risk") cards.sort(function (a, b) {
      var ka = a.totals.plan_year ? a.totals.free_limit / a.totals.plan_year : 0;
      var kb = b.totals.plan_year ? b.totals.free_limit / b.totals.plan_year : 0;
      return ka - kb;
    });
    else cards.sort(function (a, b) { return b.totals.plan_year - a.totals.plan_year; });

    if (!cards.length) {
      host.appendChild(U.el("div", { class: "dim",
        text: "Данных за год нет. Загрузите бюджеты на вкладке «Импорт / экспорт»." }));
    }
    cards.forEach(function (item) { host.appendChild(card(item, data.settings.pace)); });

    document.getElementById("dash-sub").textContent =
      cards.length + " бюджетов · ожидаемый темп освоения " +
      (data.settings.pace * 100).toFixed(0) + "%";
    document.getElementById("dash-asof").textContent =
      "на " + data.settings.as_of + " · факт закрыт по " +
      (data.settings.closed_through ? U.MONTHS_FULL[data.settings.closed_through - 1] : "—");
  }

  window.Dash = {
    render: function (payload) {
      data = payload;
      kpis(payload);
      renderCards();
    },
    init: function () {
      U.chips(document.getElementById("dash-sort"), "data-s", function (value) {
        sort = value;
        renderCards();
      });
    }
  };
})();