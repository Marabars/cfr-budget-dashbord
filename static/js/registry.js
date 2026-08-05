/* Вкладка «Справочник ЦФО»: сведение дублей, переименование, алиасы. */
(function () {
  "use strict";

  var data = null;
  var pending = null;   // пара, ожидающая подтверждения

  function confidenceBadge(level) {
    if (level >= 3) return U.badge("critical", "почти наверняка дубль");
    if (level === 2) return U.badge("warning", "похоже на дубль");
    return U.badge("serious", "возможно дубль");
  }

  function sideBlock(item, title) {
    return U.el("div", {}, [
      U.el("div", { class: "mono-s", text: title }),
      U.el("div", { class: "cc-title", text: item.name }),
      U.el("div", { class: "cc-sub", text:
        item.rows_count + " строк · план " + U.fmtShort(item.plan_year) +
        " ₽ · факт " + U.fmtShort(item.fact) + " ₽" })
    ]);
  }

  /* Подтверждение сведения: показываем, что именно произойдёт. */
  function askMerge(sourceId, targetId) {
    API.mergePreview(sourceId, targetId).then(function (preview) {
      pending = { source_id: sourceId, target_id: targetId };
      var host = document.getElementById("merge-confirm");
      host.hidden = false;
      U.clear(host);

      var lines = [
        "Все данные «" + preview.source.name + "» перейдут в «" + preview.target.name + "».",
        "После сведения: строк " + preview.totals_after.rows_count +
          ", план " + U.fmt(preview.totals_after.plan_year) + " ₽" +
          ", факт " + U.fmt(preview.totals_after.fact) + " ₽" +
          ", заявки " + U.fmt(preview.totals_after.claims) + " ₽."
      ];
      if (preview.merged_budgets.length) {
        lines.push("Одноимённые бюджеты будут объединены: " +
          preview.merged_budgets.join(", ") + " (строки перенумеруются).");
      }
      lines.push("Написание «" + preview.source.name +
        "» запомнится как алиас — следующий импорт дубль не создаст.");
      lines.push("Действие необратимо: обратно разделить данные нельзя.");

      host.appendChild(U.el("div", { class: "alert crit" }, [
        U.badge("critical", "подтвердите сведение"),
        U.el("div", {}, lines.map(function (line) { return U.el("div", { text: line }); }))
      ]));
      host.appendChild(U.el("div", { class: "row-btns" }, [
        U.el("button", { class: "btn primary", text: "Свести", on: { click: doMerge } }),
        U.el("button", { class: "btn", text: "Отмена", on: { click: function () {
          host.hidden = true;
          pending = null;
        } } })
      ]));
      host.scrollIntoView({ block: "center" });
    }).catch(function (e) { U.toast(e.message, "error"); });
  }

  function doMerge() {
    if (!pending) return;
    API.merge(pending.source_id, pending.target_id).then(function (result) {
      U.toast("Сведено в «" + result.target_name + "»: объединено бюджетов " +
        result.merged_budgets + ", перенесено строк " + result.moved_rows +
        ", добавлен алиас «" + result.alias_added + "»");
      document.getElementById("merge-confirm").hidden = true;
      pending = null;
      App.reload();
      load();
    }).catch(function (e) { U.toast(e.message, "error"); });
  }

  function renderSuggestions(items) {
    var host = document.getElementById("dup-list");
    U.clear(host);
    document.getElementById("dup-count").textContent = items.length
      ? "найдено пар: " + items.length
      : "похожих названий не найдено";

    if (!items.length) {
      host.appendChild(U.el("div", { class: "dim",
        text: "Дублей не обнаружено — справочник в порядке." }));
      return;
    }

    items.forEach(function (pair) {
      host.appendChild(U.el("div", { class: "dup-card" }, [
        U.el("div", { class: "dup-head" }, [
          confidenceBadge(pair.confidence),
          U.el("span", { class: "mono-s", text: pair.reason })
        ]),
        U.el("div", { class: "dup-pair" }, [
          sideBlock(pair.target, "оставить"),
          U.el("div", { class: "dup-arrow", text: "←" }),
          sideBlock(pair.source, "присоединить")
        ]),
        U.el("div", { class: "row-btns" }, [
          U.el("button", { class: "btn primary sm", text: "Свести",
            on: { click: function () { askMerge(pair.source.id, pair.target.id); } } }),
          U.el("button", { class: "btn sm", text: "Наоборот",
            on: { click: function () { askMerge(pair.target.id, pair.source.id); } } })
        ])
      ]));
    });
  }

  function aliasChips(item) {
    var host = U.el("div", { class: "chips" });
    item.alias_list.forEach(function (alias) {
      host.appendChild(U.el("span", { class: "chip", title: "Удалить написание" }, [
        alias,
        U.el("button", { class: "mini", text: "✕", on: { click: function () {
          API.deleteAlias(alias).then(function () {
            U.toast("Написание «" + alias + "» удалено");
            load();
          }).catch(function (e) { U.toast(e.message, "error"); });
        } } })
      ]));
    });
    host.appendChild(U.el("button", { class: "btn sm", text: "+ написание",
      on: { click: function () {
        var alias = window.prompt("Ещё одно написание для «" + item.name + "»:");
        if (!alias) return;
        API.addAlias(item.id, alias).then(function () {
          U.toast("Написание добавлено");
          load();
        }).catch(function (e) { U.toast(e.message, "error"); });
      } } }));
    return host;
  }

  function renderList(items) {
    var body = document.querySelector("***REMOVED***t-registry tbody");
    U.clear(body);
    if (!items.length) {
      body.appendChild(U.empty(7, "Справочник пуст — загрузите бюджеты."));
      return;
    }
    items.forEach(function (item) {
      var actions = U.el("div", { class: "row-actions" }, [
        U.el("button", { class: "btn sm", text: "Переименовать", on: { click: function () {
          var name = window.prompt("Новое название ЦФО:", item.name);
          if (!name || name === item.name) return;
          API.renameCfo(item.id, name).then(function () {
            U.toast("Переименовано, прежнее написание сохранено как алиас");
            App.reload();
            load();
          }).catch(function (e) { U.toast(e.message, "error"); });
        } } })
      ]);
      if (item.empty) {
        actions.appendChild(U.el("button", { class: "btn sm", text: "Удалить",
          on: { click: function () {
            API.deleteCfo(item.id).then(function () {
              U.toast("Пустая запись удалена");
              load();
            }).catch(function (e) { U.toast(e.message, "error"); });
          } } }));
      }

      body.appendChild(U.el("tr", { class: item.empty ? "dim" : "" }, [
        U.el("td", { class: "wrap" }, [
          U.el("div", { class: "cfo-name", text: item.name }),
          U.el("div", { class: "mono-s", text: item.budget_names.join(" · ") || "нет бюджетов" })
        ]),
        U.tdn(item.rows_count),
        U.tdn(item.plan_year),
        U.tdn(item.fact, "acc"),
        U.tdn(item.claims, "warm"),
        U.el("td", { class: "wrap" }, [aliasChips(item)]),
        U.el("td", {}, [actions])
      ]));
    });
  }

  /* Ручное сведение: эвристика находит не все случаи. */
  function fillManual(items) {
    var options = items.map(function (item) {
      return {
        id: item.id,
        text: item.name + " · " + item.rows_count + " строк · " + U.fmtShort(item.plan_year) + " ₽"
      };
    });
    ["mm-source", "mm-target"].forEach(function (id) {
      var select = document.getElementById(id);
      if (select) U.fillSelect(select, options, "id", "text");
    });
  }

  function load() {
    return API.registry().then(function (payload) {
      data = payload;
      renderSuggestions(payload.suggestions);
      fillManual(payload.items);
      renderList(payload.items);
      document.getElementById("reg-sub").textContent =
        payload.items.length + " записей в справочнике за " + payload.year;
    }).catch(function (e) {
      var host = document.getElementById("dup-list");
      U.clear(host);
      host.appendChild(U.el("div", { class: "dim", text:
        e.message.indexOf("финансовый") >= 0
          ? "Справочник ЦФО доступен финансовому отделу."
          : "Не удалось загрузить справочник: " + e.message }));
      U.clear(document.querySelector("***REMOVED***t-registry tbody"));
    });
  }

  function initManual() {
    var button = document.getElementById("mm-go");
    if (!button) return;
    button.onclick = function () {
      var err = document.getElementById("mm-err");
      err.textContent = "";
      var source = Number(document.getElementById("mm-source").value);
      var target = Number(document.getElementById("mm-target").value);
      if (!source || !target) { err.textContent = "Выберите оба ЦФО"; return; }
      if (source === target) { err.textContent = "Выбран один и тот же ЦФО"; return; }
      askMerge(source, target);
    };
  }

  window.Registry = { load: load, init: initManual };
})();