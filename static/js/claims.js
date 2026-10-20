/* Вкладка «Заявки»: создание обязательств с проверкой свободного лимита. */
(function () {
  "use strict";

  var rowsByCfo = {};

  function renderList(items) {
    var body = document.querySelector("#t-claims tbody");
    var foot = document.querySelector("#t-claims tfoot");
    U.clear(body);
    U.clear(foot);
    if (!items.length) {
      body.appendChild(U.empty(8, "Заявок в работе нет."));
      return;
    }
    var total = 0;
    items.forEach(function (claim) {
      total += Number(claim.amount);
      var flag = claim.out_of_budget ? U.badge("serious", "вне бюджета")
        : claim.over_limit ? U.badge("warning", "сверх лимита")
          : U.badge("good", "в лимите");
      body.appendChild(U.el("tr", {}, [
        U.td(claim.number_1c || "—"),
        U.td(claim.pay_date),
        U.el("td", { class: "wrap", text: claim.cfo_name }),
        U.el("td", { class: "wrap", text: claim.article
          ? "№" + (claim.row_no || "-") + " · " + claim.article
          : "— (нет бюджетной строки)" }),
        U.el("td", { class: "wrap", text: claim.counterparty }),
        U.tdn(claim.amount),
        U.el("td", {}, [flag]),
        U.el("td", {}, [U.el("button", {
          class: "btn sm", text: "Удалить",
          on: { click: function () {
            API.deleteClaim(claim.id)
              .then(function () { U.toast("Заявка удалена"); App.reload(); })
              .catch(function (e) { U.toast(e.message, "error"); });
          } }
        })])
      ]));
    });
    foot.appendChild(U.el("tr", {}, [
      U.el("td", { text: "ИТОГО заявок" }), U.el("td"), U.el("td"), U.el("td"), U.el("td"),
      U.tdn(total), U.el("td"), U.el("td")
    ]));
  }

  function fillRows(cfoId) {
    var select = document.getElementById("c-row");
    var rows = rowsByCfo[cfoId] || [];
    if (!rows.length) {
      select.innerHTML = "";
      select.appendChild(U.el("option", { value: "", text: "нет строк бюджета в этом ЦФО" }));
      return;
    }
    U.fillSelect(select, rows.map(function (row) {
      return {
        id: row.id,
        text: "№" + (row.row_no || "-") + " · " + row.article +
          " · свободно " + U.fmt(row.free_limit) + " ₽"
      };
    }), "id", "text");
    checkLimit();
  }

  function checkLimit() {
    var rowId = Number(document.getElementById("c-row").value);
    var amount = U.parseSum(document.getElementById("c-sum").value);
    var box = document.getElementById("c-limit");
    if (!rowId || !amount) { box.hidden = true; return; }
    API.rowLimit(rowId, amount).then(function (check) {
      box.hidden = false;
      U.clear(box);
      if (check.over_limit) {
        box.appendChild(U.badge("warning", "сверх лимита"));
        box.appendChild(U.el("div", { text:
          "Свободный лимит строки — " + U.fmt(check.free_limit) + " ₽. Превышение " +
          U.fmt(check.excess) + " ₽: заявка будет сохранена с пометкой «сверх лимита»." }));
      } else {
        box.appendChild(U.badge("good", "в пределах лимита"));
        box.appendChild(U.el("div", { text:
          "Свободный лимит строки — " + U.fmt(check.free_limit) + " ₽, после заявки останется " +
          U.fmt(check.free_limit - amount) + " ₽." }));
      }
    }).catch(function () { box.hidden = true; });
  }

  function save() {
    var err = document.getElementById("c-err");
    err.style.color = "";
    err.textContent = "";
    var cfoId = Number(document.getElementById("c-cfo").value);
    var rowId = Number(document.getElementById("c-row").value) || null;
    var amount = U.parseSum(document.getElementById("c-sum").value);
    var payDate = document.getElementById("c-date").value;

    if (!cfoId) { err.textContent = "Выберите ЦФО"; return; }
    if (!payDate) { err.textContent = "Укажите дату платежа"; return; }
    if (amount <= 0) { err.textContent = "Укажите сумму больше нуля"; return; }

    API.createClaim({
      row_id: rowId, cfo_id: cfoId,
      number_1c: document.getElementById("c-no").value,
      pay_date: payDate, amount: amount,
      counterparty: document.getElementById("c-cp").value,
      contract: document.getElementById("c-contract").value,
      detail: document.getElementById("c-detail").value
    }).then(function (result) {
      if (result.warning) U.toast(result.warning, "error");
      else U.toast("Заявка сохранена");
      ["c-no", "c-cp", "c-contract", "c-sum", "c-detail"].forEach(function (id) {
        document.getElementById(id).value = "";
      });
      document.getElementById("c-limit").hidden = true;
      App.reload();
    }).catch(function (e) { err.textContent = e.message; });
  }

  window.Claims = {
    renderList: renderList,
    setRows: function (view) {
      rowsByCfo = {};
      view.cards.forEach(function (card) { rowsByCfo[card.cfo_id] = rowsByCfo[card.cfo_id] || []; });
    },
    setRowsFromCards: function (rowsMap) {
      rowsByCfo = rowsMap;
      var cfoId = Number(document.getElementById("c-cfo").value);
      if (cfoId) fillRows(cfoId);
    },
    init: function (cfoList) {
      U.fillSelect(document.getElementById("c-cfo"), cfoList, "id", "name");
      document.getElementById("c-date").value = new Date().toISOString().slice(0, 10);
      document.getElementById("c-cfo").onchange = function () {
        App.loadRowsFor(Number(this.value));
      };
      document.getElementById("c-row").onchange = checkLimit;
      document.getElementById("c-sum").oninput = checkLimit;
      document.getElementById("c-save").onclick = save;
    },
    fillRows: fillRows
  };
})();