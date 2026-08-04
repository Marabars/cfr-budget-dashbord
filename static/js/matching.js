/* Вкладка «Сопоставление»: привязка неразобранных платежей к строкам бюджета. */
(function () {
  "use strict";

  function renderCandidates(fact, candidates) {
    document.getElementById("match-sel").textContent =
      fact.counterparty + " · " + U.fmt(fact.amount) + " ₽ · " + fact.pay_date;
    var host = document.getElementById("match-body");
    U.clear(host);
    host.className = "";

    if (!candidates.length) {
      host.appendChild(U.el("div", { class: "dim",
        text: "Подходящих строк не найдено. Пометьте платёж как «вне бюджета» или создайте строку в карточке ЦФО." }));
    } else {
      var body = U.el("tbody");
      candidates.forEach(function (item, index) {
        body.appendChild(U.el("tr", {}, [
          U.el("td", { class: "wrap" }, [
            U.el("div", { text: "№" + (item.row_no || "-") + " · " + item.article +
              (item.detail ? " · " + item.detail : "") }),
            U.el("div", { class: "mono-s", text: item.cfo_name + " / " + item.budget_name })
          ]),
          U.tdn(item.free_limit, item.enough ? "pos" : "neg"),
          U.el("td", { class: "dim", text: item.matched_by }),
          U.el("td", {}, [U.el("button", {
            class: "btn sm" + (index === 0 ? " primary" : ""), text: "Привязать",
            on: { click: function () {
              API.matchFact(fact.id, item.row_id).then(function (result) {
                U.toast(result.over_limit
                  ? "Платёж привязан, строка получила признак «сверх лимита»"
                  : "Платёж привязан к строке бюджета");
                App.reload();
              }).catch(function (e) { U.toast(e.message, "error"); });
            } }
          })])
        ]));
      });
      host.appendChild(U.el("table", {}, [
        U.el("thead", {}, [U.el("tr", {}, [
          U.th("Строка бюджета", "wrap"), U.th("Свободный лимит", "num"),
          U.th("Совпадение"), U.th("")
        ])]),
        body
      ]));
      if (!candidates[0].enough) {
        host.appendChild(U.el("div", { class: "alert", style: "margin-top:12px" }, [
          U.badge("warning", "сверх лимита"),
          U.el("div", { text: "Сумма платежа больше свободного лимита. Привязка возможна — " +
            "строка получит признак «сверх лимита»." })
        ]));
      }
    }

    host.appendChild(U.el("div", { style: "margin-top:12px;display:flex;gap:8px;flex-wrap:wrap" }, [
      U.el("button", { class: "btn", text: "Пометить «вне бюджета»",
        on: { click: function () {
          API.flagOutOfBudget(fact.id, true).then(function () {
            U.toast("Платёж помечен как «вне бюджета»");
            App.reload();
          }).catch(function (e) { U.toast(e.message, "error"); });
        } } })
    ]));
  }

  function render(items) {
    var body = document.querySelector("***REMOVED***t-unmatched tbody");
    U.clear(body);
    document.getElementById("match-count").textContent = items.length
      ? items.length + " платежей ждут разбора" : "всё разобрано";

    var alertBox = document.getElementById("match-alert");
    if (items.length) {
      alertBox.hidden = false;
      U.clear(alertBox);
      alertBox.appendChild(U.badge("critical", items.length + " платежей не разобрано"));
      alertBox.appendChild(U.el("div", { text:
        "Пока платёж не привязан к строке бюджета, он не попадает в факт ЦФО." }));
    } else {
      alertBox.hidden = true;
    }

    if (!items.length) {
      body.appendChild(U.empty(4, "Неразобранных платежей нет."));
      document.getElementById("match-sel").textContent = "выберите платёж слева";
      var host = document.getElementById("match-body");
      U.clear(host);
      host.className = "dim";
      host.textContent = "Кандидаты подбираются по статье, ЦФО, контрагенту и договору.";
      return;
    }

    items.forEach(function (fact, index) {
      var tr = U.el("tr", { class: "pick", "aria-selected": "false" }, [
        U.td(fact.pay_date),
        U.el("td", { class: "wrap", text: fact.counterparty }),
        U.el("td", { class: "wrap", text: (fact.article || "без статьи") +
          (fact.purpose ? " · " + fact.purpose : "") }),
        U.tdn(fact.amount)
      ]);
      tr.onclick = function () {
        Array.prototype.forEach.call(body.children, function (row) {
          row.setAttribute("aria-selected", "false");
        });
        tr.setAttribute("aria-selected", "true");
        API.candidates(fact.id)
          .then(function (candidates) { renderCandidates(fact, candidates); })
          .catch(function (e) { U.toast(e.message, "error"); });
      };
      body.appendChild(tr);
      if (index === 0) window.setTimeout(function () { tr.click(); }, 0);
    });
  }

  window.Matching = {
    render: render,
    init: function () {
      document.getElementById("auto-match").onclick = function () {
        API.autoMatch().then(function (result) {
          U.toast("Автоматически сопоставлено платежей: " + result.matched);
          App.reload();
        }).catch(function (e) { U.toast(e.message, "error"); });
      };
    }
  };
})();