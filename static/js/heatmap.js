/* Вкладка «Тепловая карта»: отклонение факта от плана по месяцам. */
(function () {
  "use strict";

  var STEPS = [0.05, 0.15, 0.30, 0.60];

  function color(deviation) {
    var abs = Math.abs(deviation);
    var step = 0;
    for (var i = 0; i < STEPS.length; i++) if (abs >= STEPS[i]) step = i + 1;
    if (step === 0) return { bg: "var(--hm-0)", ink: "var(--ink2)" };
    var arm = deviation < 0 ? "b" : "r";
    return { bg: "var(--hm-" + arm + step + ")", ink: step >= 3 ? "var(--hm-ink-deep)" : "var(--ink)" };
  }

  function render(payload) {
    var head = document.querySelector("#t-heat thead");
    var body = document.querySelector("#t-heat tbody");
    U.clear(head);
    U.clear(body);

    var headRow = U.el("tr", {}, [U.th("", "rowh")]);
    U.MONTHS_SHORT.forEach(function (name) { headRow.appendChild(U.th(name)); });
    head.appendChild(headRow);

    if (!payload.rows.length) {
      body.appendChild(U.empty(13, "Нет данных для карты."));
      return;
    }

    payload.rows.forEach(function (row) {
      var tr = U.el("tr", {}, [U.el("th", { class: "rowh" }, [
        U.el("div", { text: row.cfo_name }),
        U.el("div", { class: "mono-s", text: row.budget_name })
      ])]);
      row.cells.forEach(function (cell) {
        if (!cell.closed) {
          tr.appendChild(U.el("td", { class: "fc", text: "·",
            title: U.MONTHS_FULL[cell.month - 1] + " — не закрыт" }));
          return;
        }
        if (cell.deviation === null || cell.deviation === undefined) {
          tr.appendChild(U.el("td", { class: "dim", text: "—",
            title: "План на " + U.MONTHS_FULL[cell.month - 1] + " не задан" }));
          return;
        }
        var percent = Math.round(Math.abs(cell.deviation) * 100);
        var label = percent === 0 ? "0%"
          : (cell.deviation > 0 ? "+" : "−") + Math.min(percent, 999) + "%";
        var paint = color(cell.deviation);
        var td = U.el("td", { text: label });
        td.style.background = paint.bg;
        td.style.color = paint.ink;
        td.title = row.cfo_name + " · " + U.MONTHS_FULL[cell.month - 1] +
          "\nфакт " + U.fmt(cell.fact) + " ₽ · план " + U.fmt(cell.plan) + " ₽";
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });

    var legend = document.getElementById("hm-legend");
    U.clear(legend);
    legend.appendChild(U.el("span", { text: "ниже плана" }));
    ["b4", "b3", "b2", "b1", "0", "r1", "r2", "r3", "r4"].forEach(function (step) {
      var box = U.el("i");
      box.style.background = "var(--hm-" + step + ")";
      legend.appendChild(box);
    });
    legend.appendChild(U.el("span", { text: "выше плана" }));
    legend.appendChild(U.el("span", { class: "mono-s", text: "· −60% … 0 … +60%" }));
  }

  window.Heat = { render: render };
})();