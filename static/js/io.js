/* Вкладка «Импорт / экспорт»: загрузка файлов с сопоставлением колонок. */
(function () {
  "use strict";

  var kind = "plan";
  var pending = null;      // выбранный файл
  var inspected = null;    // результат разбора

  var OPERPLAN_KINDS = { "cfo-budgets": true, "cfo-articles": true };

  function syncKind() {
    var isPlan = kind === "plan";
    document.getElementById("w-io-cfo").hidden = !isPlan;
    document.getElementById("w-io-budget").hidden = !isPlan;
    document.getElementById("w-io-year").hidden = kind !== "cfo-budgets";
    document.getElementById("io-layer-note").hidden = !OPERPLAN_KINDS[kind];
    var year = document.getElementById("io-year");
    if (kind === "cfo-budgets" && !year.value) year.value = String(App.year());
  }

  function renderMapping(info) {
    var card = document.getElementById("mapping-card");
    var body = document.querySelector("#t-map tbody");
    U.clear(body);
    card.hidden = false;

    document.getElementById("mapping-sub").textContent =
      "файл: " + info.filename + " · лист «" + info.sheet + "»" +
      (info.header_row ? " · шапка в строке " + info.header_row : "");

    if (kind === "cfo-budgets") {
      var lines = ["Лист «" + info.sheet + "» распознан: блоков " + info.blocks +
        ", строк " + info.rows + ", сумма " + U.fmt(info.total) + " ₽."];
      if (info.mismatches && info.mismatches.length) {
        info.mismatches.forEach(function (m) {
          lines.push("ИТОГО блока «" + m.cfo + "» в файле " + U.fmt(m.declared) +
            " ₽, сумма строк " + U.fmt(m.actual) + " ₽ (расхождение " +
            U.fmt(m.diff) + " ₽, строка Excel " + m.excel_row + ")");
        });
      }
      body.appendChild(U.el("tr", {}, [
        U.el("td", { colspan: 4, class: "wrap" }, lines.map(function (text, i) {
          return U.el("div", { class: i ? "mono-s" : "", text: text });
        }))
      ]));
      return;
    }

    if (kind === "cfo-articles") {
      body.appendChild(U.el("tr", {}, [
        U.el("td", { colspan: 4, class: "wrap" }, [
          U.el("div", { text: "Лист «" + info.sheet + "»: " + info.pairs +
            " пар ЦФО — статья по " + info.cfo + " дирекциям." }),
          U.el("div", { class: "mono-s", text:
            "Справочник используется в выпадающих списках при добавлении строки плана." })
        ])
      ]));
      return;
    }

    if (kind === "operplan") {
      body.appendChild(U.el("tr", {}, [
        U.el("td", { colspan: 4, class: "wrap" }, [
          U.el("div", { text: "Лист «Оперплан ЦФО» распознан: блоков " + info.blocks +
            ", строк " + info.rows + ", факт закрыт по месяц " + info.closed_through + "." }),
          U.el("div", { class: "mono-s", text:
            "Колонки этого листа фиксированы, сопоставление не требуется." })
        ])
      ]));
      return;
    }

    (info.columns || []).forEach(function (column) {
      var status = column.field
        ? (column.guessed ? U.badge("warning", "предположение") : U.badge("good", "распознано"))
        : U.badge("serious", "не используется");
      body.appendChild(U.el("tr", {}, [
        U.td(column.letter || String(column.index + 1)),
        U.el("td", { class: "wrap" }, [
          U.el("div", { text: column.title || "—" }),
          U.el("div", { class: "mono-s", text: (column.samples || []).join(" · ") })
        ]),
        U.el("td", { text: column.field_title || (column.field || "—") }),
        U.el("td", {}, [status])
      ]));
    });
  }

  function inspect(file) {
    pending = file;
    U.toast("Разбираю файл «" + file.name + "»…");
    API.inspect(kind, file).then(function (info) {
      inspected = info;
      info.filename = file.name;
      renderMapping(info);
      U.toast("Файл разобран. Проверьте сопоставление и нажмите «Загрузить».");
    }).catch(function (e) {
      document.getElementById("mapping-card").hidden = true;
      U.toast(e.message, "error");
    });
  }

  function doImport() {
    if (!pending) { U.toast("Сначала выберите файл", "error"); return; }
    var params = { year: App.year() };
    if (kind === "plan") {
      params.cfo_name = document.getElementById("io-cfo").value;
      params.budget_name = document.getElementById("io-budget").value || "Основной бюджет";
    } else if (kind === "cfo-budgets") {
      params.year = Number(document.getElementById("io-year").value) || App.year();
    } else if (kind === "cfo-articles") {
      params = {};
    }
    var result = document.getElementById("io-result");
    U.clear(result);
    result.appendChild(U.el("div", { class: "dim", text: "Загружаю…" }));

    API.importFile(kind, pending, params).then(function (data) {
      U.clear(result);
      var lines = [];
      if (data.rows !== undefined) lines.push("строк бюджета: " + data.rows);
      if (data.facts !== undefined) lines.push("платежей: " + data.facts);
      if (data.claims !== undefined) lines.push("заявок: " + data.claims);
      if (data.created !== undefined) lines.push("новых платежей: " + data.created);
      if (data.skipped !== undefined) lines.push("пропущено дублей: " + data.skipped);
      if (data.matched !== undefined) lines.push("сопоставлено автоматически: " + data.matched);
      if (data.closed_through) lines.push("факт закрыт по месяц: " + data.closed_through);
      if (data.removed) lines.push("заменено прежних строк слоя: " + data.removed);
      if (data.articles !== undefined) lines.push("статей в справочнике: " + data.articles);
      if (data.cfo !== undefined) lines.push("дирекций: " + data.cfo);
      if (data.total) lines.push("сумма: " + U.fmt(data.total) + " ₽");

      result.appendChild(U.el("div", { class: "alert" }, [
        U.badge("good", "загружено"), U.el("div", { text: lines.join(" · ") })
      ]));

      if (data.mismatches && data.mismatches.length) {
        var detail = data.mismatches.map(function (m) {
          return m.cfo
            ? m.cfo + ": ИТОГО в файле " + U.fmt(m.declared) + " ₽, сумма строк " +
              U.fmt(m.actual) + " ₽"
            : null;
        }).filter(Boolean);
        result.appendChild(U.el("div", { class: "alert", style: "margin-top:8px" }, [
          U.badge("warning", "проверьте суммы"),
          U.el("div", { text: "Расхождений с контрольной суммой: " + data.mismatches.length }),
          detail.length ? U.el("div", { class: "mono-s wrap", text: detail.join(" · ") }) : null
        ]));
      }
      document.getElementById("mapping-card").hidden = true;
      pending = null;
      App.reload();
      if (OPERPLAN_KINDS[kind]) Operplan.load();
    }).catch(function (e) {
      U.clear(result);
      result.appendChild(U.el("div", { class: "alert crit" }, [
        U.badge("critical", "ошибка"), U.el("div", { text: e.message })
      ]));
    });
  }

  function renderImports(items) {
    var body = document.querySelector("#t-imports tbody");
    U.clear(body);
    if (!items.length) {
      body.appendChild(U.empty(6, "Загрузок ещё не было."));
      return;
    }
    var titles = { operplan: "Оперплан ЦФО", plan: "План дирекции", fact: "Факт",
      cfo_budgets: "Бюджеты ЦФО (вкладка «Бюджет»)" };
    items.forEach(function (item) {
      body.appendChild(U.el("tr", {}, [
        U.td(item.uploaded_at),
        U.td(titles[item.kind] || item.kind),
        U.el("td", { class: "wrap", text: item.filename }),
        U.el("td", { class: "dim", text: item.author || "—" }),
        U.tdn(item.rows_ok),
        U.el("td", { class: "wrap dim", text: item.note })
      ]));
    });
  }

  window.IO = {
    renderImports: renderImports,
    init: function () {
      U.chips(document.getElementById("io-kind"), "data-k", function (value) {
        kind = value;
        syncKind();
        document.getElementById("mapping-card").hidden = true;
        pending = null;
      });
      syncKind();

      var input = document.getElementById("file");
      document.getElementById("pick-file").onclick = function () { input.click(); };
      input.onchange = function () { if (input.files[0]) inspect(input.files[0]); };

      var drop = document.getElementById("drop");
      ["dragenter", "dragover"].forEach(function (event) {
        drop.addEventListener(event, function (e) {
          e.preventDefault();
          drop.style.borderColor = "var(--accent)";
        });
      });
      ["dragleave", "drop"].forEach(function (event) {
        drop.addEventListener(event, function (e) {
          e.preventDefault();
          drop.style.borderColor = "";
        });
      });
      drop.addEventListener("drop", function (e) {
        if (e.dataTransfer.files[0]) inspect(e.dataTransfer.files[0]);
      });

      document.getElementById("do-import").onclick = doImport;

      Array.prototype.forEach.call(document.querySelectorAll("[data-export]"), function (button) {
        button.onclick = function () {
          API.download(button.getAttribute("data-export"))
            .catch(function (e) { U.toast(e.message, "error"); });
        };
      });
    }
  };
})();