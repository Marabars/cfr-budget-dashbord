/* Вкладка «Корректировки»: перенос лимита и журнал изменений. */
(function () {
  "use strict";

  var kind = "month";
  var rowsByCfo = {};

  function fillRows(cfoId) {
    var rows = rowsByCfo[cfoId] || [];
    var options = rows.map(function (row) {
      return {
        id: row.id,
        text: "№" + (row.row_no || "-") + " · " + row.article +
          " · лимит " + U.fmt(row.plan_year) + " ₽"
      };
    });
    ["j-from-row", "j-to-row"].forEach(function (id) {
      var select = document.getElementById(id);
      if (!options.length) {
        select.innerHTML = "";
        select.appendChild(U.el("option", { value: "", text: "нет строк бюджета" }));
      } else {
        U.fillSelect(select, options, "id", "text");
      }
    });
    fillMonths();
  }

  function fillMonths() {
    var rowId = Number(document.getElementById("j-from-row").value);
    var cfoId = Number(document.getElementById("j-cfo").value);
    var row = (rowsByCfo[cfoId] || []).filter(function (r) { return r.id === rowId; })[0];
    var from = document.getElementById("j-from-month");
    var to = document.getElementById("j-to-month");

    var fromOptions = U.MONTHS_FULL.map(function (name, i) {
      var planned = row ? row.plan_months[i] : 0;
      return { value: String(i + 1), text: name + " — запланировано " + U.fmt(planned) + " ₽" };
    });
    U.fillSelect(from, fromOptions, "value", "text");
    U.fillSelect(to, U.MONTHS_FULL.map(function (name, i) {
      return { value: String(i + 1), text: name };
    }), "value", "text");
  }

  function syncKind() {
    var isRow = kind === "row";
    document.getElementById("w-j-from-month").hidden = isRow;
    document.getElementById("w-j-to-month").hidden = isRow;
    document.getElementById("w-j-to-row").hidden = !isRow;
  }

  function save() {
    var err = document.getElementById("j-err");
    err.style.color = "";
    err.textContent = "";
    var payload = {
      kind: kind,
      from_row_id: Number(document.getElementById("j-from-row").value),
      amount: U.parseSum(document.getElementById("j-sum").value),
      reason: document.getElementById("j-reason").value
    };
    if (kind === "month") {
      payload.from_month = Number(document.getElementById("j-from-month").value);
      payload.to_month = Number(document.getElementById("j-to-month").value);
    } else {
      payload.to_row_id = Number(document.getElementById("j-to-row").value);
    }
    if (!payload.from_row_id) { err.textContent = "Выберите строку-источник"; return; }
    if (payload.amount <= 0) { err.textContent = "Укажите сумму больше нуля"; return; }
    if (payload.reason.trim().length < 3) { err.textContent = "Заполните обоснование"; return; }

    API.transfer(payload).then(function (result) {
      U.toast("Корректировка проведена: " + result.change);
      document.getElementById("j-sum").value = "";
      document.getElementById("j-reason").value = "";
      App.reload();
    }).catch(function (e) { err.textContent = e.message; });
  }

  function renderLog(items) {
    var body = document.querySelector("***REMOVED***t-log tbody");
    U.clear(body);
    if (!items.length) {
      body.appendChild(U.empty(6, "Журнал пуст."));
      return;
    }
    items.forEach(function (entry) {
      body.appendChild(U.el("tr", {}, [
        U.td(entry.ts),
        U.el("td", { class: "dim", text: entry.author || "—" }),
        U.td(entry.action),
        U.el("td", { class: "wrap", text: entry.object }),
        U.el("td", { class: "wrap", text: entry.change }),
        U.el("td", { class: "wrap dim", text: entry.reason })
      ]));
    });
  }

  window.Adjust = {
    renderLog: renderLog,
    setRows: function (rowsMap) {
      rowsByCfo = rowsMap;
      var cfoId = Number(document.getElementById("j-cfo").value);
      if (cfoId) fillRows(cfoId);
    },
    init: function (cfoList) {
      U.fillSelect(document.getElementById("j-cfo"), cfoList, "id", "name");
      U.chips(document.getElementById("adj-kind"), "data-k", function (value) {
        kind = value;
        syncKind();
      });
      document.getElementById("j-cfo").onchange = function () {
        App.loadRowsFor(Number(this.value));
      };
      document.getElementById("j-from-row").onchange = fillMonths;
      document.getElementById("j-save").onclick = save;
      syncKind();
      fillMonths();
    },
    fillRows: fillRows
  };
})();