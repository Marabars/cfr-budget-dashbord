/* Связка модулей: шапка, вкладки, загрузка данных. */
(function () {
  "use strict";

  var state = { cfg: null, cfoList: [], rowsByCfo: {}, currentCfo: null };

  function selectTab(name) {
    Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
      tab.setAttribute("aria-selected", tab.getAttribute("data-p") === name ? "true" : "false");
    });
    Array.prototype.forEach.call(document.querySelectorAll(".panel"), function (panel) {
      panel.classList.toggle("on", panel.id === "p-" + name);
    });
    window.scrollTo(0, 0);
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

  function reload() {
    return API.settings().then(function (cfg) {
      state.cfg = cfg;
      fillHeader(cfg);
      return Promise.all([
        API.dashboard(), API.cfoList(), API.heatmap(), API.claims(),
        API.outOfBudget(), API.audit(), API.imports(),
        API.me().then(function (me) {
          return me.is_fin ? API.unmatched().catch(function () { return []; }) : [];
        })
      ]);
    }).then(function (results) {
      var dash = results[0];
      state.cfoList = results[1];

      Dash.render(dash);
      Sum.render(dash);
      Heat.render(results[2]);
      Claims.renderList(results[3]);
      Sum.renderOutOfBudget(results[4]);
      Adjust.renderLog(results[5]);
      IO.renderImports(results[6]);
      Matching.render(results[7]);

      U.fillSelect(document.getElementById("cfo-pick"), state.cfoList, "id", "name",
        state.currentCfo || (state.cfoList[0] && state.cfoList[0].id));
      U.fillSelect(document.getElementById("c-cfo"), state.cfoList, "id", "name");
      U.fillSelect(document.getElementById("j-cfo"), state.cfoList, "id", "name");
      fillRoles();

      var pick = document.getElementById("cfo-pick");
      if (pick.value) {
        state.currentCfo = Number(pick.value);
        CfoCard.load(state.currentCfo);
        loadRowsFor(state.currentCfo);
      }
      if (!state.cfoList.length) {
        U.toast("Данных пока нет: загрузите бюджеты на вкладке «Импорт / экспорт».");
      }
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

    Dash.init();
    Sum.init();
    CfoCard.init();
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