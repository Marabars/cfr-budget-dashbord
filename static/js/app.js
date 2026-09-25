/* Связка модулей: шапка, вкладки, загрузка данных. */
(function () {
  "use strict";

  var state = { cfg: null, cfoList: [], rowsByCfo: {}, currentCfo: null, me: null };

  /* Руководителю ЦФО доступны только эти вкладки; остальное ведёт финотдел. */
  var CFO_TABS = ["op", "cfo"];

  function tabNodes() {
    return Array.prototype.slice.call(document.querySelectorAll(".tab"));
  }

  function showTab(name) {
    tabNodes().forEach(function (tab) {
      tab.setAttribute("aria-selected", tab.getAttribute("data-p") === name ? "true" : "false");
    });
    Array.prototype.forEach.call(document.querySelectorAll(".panel"), function (panel) {
      panel.classList.toggle("on", panel.id === "p-" + name);
    });
    window.scrollTo(0, 0);
  }

  function activeTab() {
    var tab = document.querySelector('.tab[aria-selected="true"]');
    return tab ? tab.getAttribute("data-p") : "";
  }

  /* Справочник и бюджет грузим по открытию вкладки, а не при каждой перерисовке. */
  function loadTabData(name) {
    if (name === "reg") Registry.load();
    if (name === "op") Operplan.load();
  }

  function selectTab(name) {
    showTab(name);
    loadTabData(name);
  }

  /* Вкладки под роль: скрываем лишние и уводим с закрытой вкладки. */
  function applyRole(me) {
    state.me = me;
    var open = null;
    tabNodes().forEach(function (tab) {
      var name = tab.getAttribute("data-p");
      var allowed = me.is_fin || CFO_TABS.indexOf(name) >= 0;
      tab.hidden = !allowed;
      if (allowed && !open) open = name;
      if (allowed && tab.getAttribute("aria-selected") === "true") open = name;
    });
    var active = document.querySelector('.tab[aria-selected="true"]');
    if (!active || active.hidden) showTab(open || "op");   // данные догрузит reload
  }

  function fillHeader(cfg) {
    var years = [];
    for (var y = cfg.year - 2; y <= cfg.year + 1; y++) years.push(y);
    U.fillSelect(document.getElementById("year"), years, null, null, cfg.year);

    U.fillSelect(document.getElementById("closed"),
      [{ value: "0", text: "не закрыт" }].concat(U.MONTHS_FULL.map(function (name, i) {
        return { value: String(i + 1), text: name };
      })), "value", "text", cfg.closed_through);

    document.getElementById("asof").value = cfg.as_of;
  }

  function fillRoles() {
    var options = [{ value: "", text: "Финансовый отдел" }].concat(
      state.cfoList.map(function (cfo) {
        return { value: "cfo:" + cfo.id, text: "Руководитель · " + cfo.name };
      })
    );
    U.fillSelect(document.getElementById("role"), options, "value", "text", API.getRole());
  }

  /* Строки ЦФО нужны формам заявок и корректировок. */
  function loadRowsFor(cfoId) {
    if (!cfoId) return Promise.resolve([]);
    return API.cfoCard(cfoId).then(function (card) {
      var rows = [];
      card.budgets.forEach(function (budget) {
        budget.rows.forEach(function (row) { rows.push(row); });
      });
      state.rowsByCfo[cfoId] = rows;
      Claims.setRowsFromCards(state.rowsByCfo);
      Adjust.setRows(state.rowsByCfo);
      return rows;
    }).catch(function () { return []; });
  }

  /* Финотделу нужны все сводные данные, руководителю — только его ЦФО:
     лишние запросы не шлём, часть из них ему и так закрыта на сервере. */
  function loadForFin() {
    return Promise.all([
      API.dashboard(), API.cfoList(), API.heatmap(), API.claims(),
      API.outOfBudget(), API.audit(), API.imports(),
      API.unmatched().catch(function () { return []; })
    ]).then(function (results) {
      Dash.render(results[0]);
      Sum.render(results[0]);
      Heat.render(results[2]);
      Claims.renderList(results[3]);
      Sum.renderOutOfBudget(results[4]);
      Adjust.renderLog(results[5]);
      IO.renderImports(results[6]);
      Matching.render(results[7]);
      return results[1];
    });
  }

  function fillCfoPickers(cfoList) {
    state.cfoList = cfoList;
    Operplan.setCfoList(cfoList);
    U.fillSelect(document.getElementById("cfo-pick"), cfoList, "id", "name",
      state.currentCfo || (cfoList[0] && cfoList[0].id));
    U.fillSelect(document.getElementById("c-cfo"), cfoList, "id", "name");
    U.fillSelect(document.getElementById("j-cfo"), cfoList, "id", "name");
    fillRoles();

    var pick = document.getElementById("cfo-pick");
    if (pick.value) {
      state.currentCfo = Number(pick.value);
      CfoCard.load(state.currentCfo);
      loadRowsFor(state.currentCfo);
    }
    if (!cfoList.length) {
      U.toast(state.me && !state.me.is_fin
        ? "К вашей учётной записи не привязано ни одного ЦФО — обратитесь в финансовый отдел."
        : "Данных пока нет: загрузите бюджеты на вкладке «Импорт / экспорт».");
    }
  }

  function reload() {
    return API.me().then(function (me) {
      applyRole(me);
      return API.settings().then(function (cfg) {
        state.cfg = cfg;
        fillHeader(cfg);
        return me.is_fin ? loadForFin() : API.cfoList();
      });
    }).then(function (cfoList) {
      fillCfoPickers(cfoList);
      loadTabData(activeTab());
    }).catch(function (e) {
      U.toast("Не удалось загрузить данные: " + e.message, "error");
    });
  }

  function saveSettings(patch) {
    API.saveSettings(patch)
      .then(function () { reload(); })
      .catch(function (e) { U.toast(e.message, "error"); });
  }

  window.App = {
    year: function () { return state.cfg ? state.cfg.year : new Date().getFullYear(); },
    reload: reload,
    loadRowsFor: loadRowsFor,
    openCfo: function (cfoId) {
      state.currentCfo = cfoId;
      document.getElementById("cfo-pick").value = String(cfoId);
      CfoCard.load(cfoId);
      loadRowsFor(cfoId);
      selectTab("cfo");
    }
  };

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
      tab.onclick = function () { selectTab(tab.getAttribute("data-p")); };
    });
    var refresh = document.getElementById("reg-refresh");
    if (refresh) refresh.onclick = function () { Registry.load(); };
    Registry.init();

    Dash.init();
    Sum.init();
    CfoCard.init();
    Operplan.init();
    Matching.init();
    IO.init();
    Claims.init([]);
    Adjust.init([]);

    document.getElementById("theme").onclick = function () {
      var current = document.documentElement.getAttribute("data-theme");
      document.documentElement.setAttribute("data-theme", current === "light" ? "dark" : "light");
    };
    document.getElementById("year").onchange = function () {
      saveSettings({ year: Number(this.value) });
    };
    document.getElementById("closed").onchange = function () {
      saveSettings({ closed_through: Number(this.value) });
    };
    document.getElementById("asof").onchange = function () {
      saveSettings({ as_of: this.value });
    };
    document.getElementById("role").onchange = function () {
      API.setRole(this.value);
      reload();
    };
    document.getElementById("cfo-pick").onchange = function () {
      state.currentCfo = Number(this.value);
      CfoCard.load(state.currentCfo);
      loadRowsFor(state.currentCfo);
    };

    reload();
  });
})();