/* Вкладка «Бюджет»: план следующего года по всем ЦФО, фильтры, правка таблицы. */
(function () {
  "use strict";

  var state = {
    data: null,          // ответ /api/operplan
    refs: null,          // справочники статей, контрагентов, договоров
    missing: null,       // строки прошлого года, которых нет в плане
    rows: {},            // id -> строка (для правки и пересчёта)
    editing: false,
    collapsed: {},       // budget_id -> свёрнут ли блок
    filters: null,
    combos: null,       // выпадающие списки формы новой строки
    year: null
  };

  var FIELDS = [
    { key: "article", title: "Статья оборотов" },
    { key: "counterparty", title: "Контрагент" },
    { key: "contract", title: "Договор" },
    { key: "detail_text", title: "Детализация" }
  ];
  var MONTH_FIELD = /^m\d+$/;
  var COLS = 6 + 12 + 1;   // № + 4 текстовых + ИТОГО + 12 месяцев + прошлый год

  /* ---------- фильтры ---------- */

  function initFilters() {
    if (state.filters) return;
    var host = document.getElementById("op-filters");
    state.filters = {};
    [{ key: "cfo_name", title: "ЦФО" }].concat(FIELDS).forEach(function (f) {
      var filter = U.multiFilter(f.title, render);
      state.filters[f.key] = filter;
      host.appendChild(filter.node);
    });
  }

  function refreshFilterOptions() {
    var seen = {};
    Object.keys(state.filters).forEach(function (key) { seen[key] = {}; });
    allRows().forEach(function (row) {
      Object.keys(seen).forEach(function (key) {
        seen[key][String(row[key] == null ? "" : row[key])] = true;
      });
    });
    Object.keys(state.filters).forEach(function (key) {
      state.filters[key].setOptions(Object.keys(seen[key]));
    });
  }

  function allRows() {
    if (!state.data) return [];
    return state.data.blocks.reduce(function (acc, block) {
      return acc.concat(block.rows.map(function (row) {
        return Object.assign({ cfo_name: block.cfo_name }, row);
      }));
    }, []);
  }

  function passes(row, cfoName) {
    var values = { cfo_name: cfoName };
    return Object.keys(state.filters).every(function (key) {
      var chosen = state.filters[key].selected();
      if (!chosen.length) return true;
      var value = String((key in values ? values[key] : row[key]) || "");
      return chosen.indexOf(value) >= 0;
    });
  }

  /* ---------- KPI ---------- */

  function kpiTile(label, value, tone, battery, note) {
    return U.el("div", { class: "kpi " + (tone || "") }, [
      U.el("div", { class: "lbl", text: label }),
      U.el("div", { class: "val hero", text: value }),
      battery === null ? U.el("div", { class: "sub", text: note }) : U.battery(battery, 0),
      battery === null ? null : U.el("div", { class: "batt-note", text: note })
    ]);
  }

  function renderKpi() {
    var k = state.data.kpi;
    var host = document.getElementById("op-kpis");
    U.clear(host);
    host.appendChild(kpiTile(
      "Бюджет " + k.plan_year + " года", U.fmtShort(k.plan_total) + " ₽", "k-accent",
      null, k.plan_rows + " строк плана"));
    host.appendChild(kpiTile(
      "Бюджет " + k.base_year + " года", U.fmtShort(k.base_total) + " ₽", "k-warm",
      k.base_ratio, "от бюджета " + k.plan_year + " года"));
    host.appendChild(kpiTile(
      "План-факт " + k.base_year, U.fmtShort(k.base_fact) + " ₽",
      k.fact_loaded ? "k-good" : "",
      k.fact_loaded ? k.base_pct : null,
      k.fact_loaded ? "освоено от бюджета " + k.base_year
        : "факт за " + k.base_year + " год ещё не загружен"));
  }

  /* ---------- шапка и итог ---------- */

  function renderHead() {
    var head = document.getElementById("op-head");
    U.clear(head);
    head.appendChild(U.th("№"));
    FIELDS.forEach(function (f) { head.appendChild(U.th(f.title, "wrap")); });
    head.appendChild(U.th("ИТОГО", "num"));
    U.MONTHS_SHORT.forEach(function (name) { head.appendChild(U.th(name, "num month-col")); });
    head.appendChild(U.th(state.data.base_year_no + " год", "num"));
  }

  function renderTotal(rows) {
    var total = document.getElementById("op-total");
    U.clear(total);
    var months = [];
    for (var i = 0; i < 12; i++) months.push(0);
    var sum = 0, base = 0;
    rows.forEach(function (row) {
      sum += row.plan_year;
      base += row.base_plan_year || 0;
      for (var i = 0; i < 12; i++) months[i] += row.months[i] || 0;
    });
    var filtered = rows.length !== (state.data.totals.rows_count || 0);
    total.appendChild(U.el("td", { colspan: 5, class: "total-label",
      text: "ИТОГО" + (filtered ? " по фильтру · " + rows.length + " строк" : " · " + rows.length + " строк") }));
    total.appendChild(U.el("td", { class: "num total-sum", text: U.fmt(sum) }));
    months.forEach(function (value) {
      total.appendChild(U.el("td", { class: "num", text: value ? U.fmt(value) : "—" }));
    });
    total.appendChild(U.el("td", { class: "num dim", text: base ? U.fmt(base) : "—" }));
  }

  /* ---------- строки ---------- */

  function editableCell(row, field, value, cls) {
    return Inline.cell(row.id, field, value, cls, state.editing && state.data.can_edit);
  }

  function rowNode(row, cfoName) {
    var tr = U.el("tr", { "data-id": row.id });

    var del = U.el("button", { class: "mini", title: "Удалить строку", text: "✕" });
    del.onclick = function (event) {
      event.stopPropagation();
      if (!window.confirm("Удалить строку «" + row.article + "»?")) return;
      API.deleteRow(row.id)
        .then(function () { U.toast("Строка удалена"); load(state.year); })
        .catch(function (e) { U.toast(e.message, "error"); });
    };
    tr.appendChild(U.el("td", {}, [U.el("div", { class: "no-cell" }, [
      U.el("span", { text: row.row_no || "•" }),
      state.editing && state.data.can_edit ? del : null
    ])]));

    FIELDS.forEach(function (f) {
      tr.appendChild(editableCell(row, f.key, row[f.key] || "", "wrap"));
    });

    tr.appendChild(U.el("td", { class: "num n-plan", "data-total": row.id,
      text: U.fmt(row.plan_year) }));

    for (var i = 0; i < 12; i++) {
      var value = row.months[i] || 0;
      var td = editableCell(row, "m" + i, value ? U.fmt(value) : (state.editing ? "" : "—"),
        "num" + (value ? "" : " dim"));
      tr.appendChild(td);
    }

    tr.appendChild(U.el("td", { class: "num dim",
      text: row.base_plan_year == null ? "—" : U.fmt(row.base_plan_year) }));
    return tr;
  }

  function groupNode(block, shown, sum) {
    var collapsed = !!state.collapsed[block.budget_id];
    var td = U.el("td", { colspan: COLS }, [
      U.el("span", { class: "grp-caret", text: collapsed ? "▸" : "▾" }),
      U.el("b", { text: block.cfo_name }),
      U.el("span", { class: "dim", text: " · " + block.budget_name }),
      U.el("span", { class: "grp-sum", text: U.fmt(sum) + " ₽ · " + shown + " строк" })
    ]);
    var tr = U.el("tr", { class: "group" }, [td]);
    tr.onclick = function () {
      state.collapsed[block.budget_id] = !collapsed;
      render();
    };
    return tr;
  }

  function render() {
    if (!state.data) return;
    renderKpi();
    renderHead();

    var body = document.querySelector("***REMOVED***t-op tbody");
    U.clear(body);
    state.rows = {};
    var visible = [];

    state.data.blocks.forEach(function (block) {
      var rows = block.rows.filter(function (row) { return passes(row, block.cfo_name); });
      if (!rows.length) return;
      var sum = rows.reduce(function (acc, row) { return acc + row.plan_year; }, 0);
      body.appendChild(groupNode(block, rows.length, sum));
      if (state.collapsed[block.budget_id]) {
        visible = visible.concat(rows);
        rows.forEach(function (row) { state.rows[row.id] = row; });
        return;
      }
      rows.forEach(function (row) {
        state.rows[row.id] = row;
        visible.push(row);
        body.appendChild(rowNode(row, block.cfo_name));
      });
    });

    if (!visible.length) {
      body.appendChild(U.empty(COLS, state.data.totals.rows_count
        ? "Под фильтр ничего не подошло — снимите часть условий."
        : "В плане " + state.year + " года пока нет строк. Нажмите «Повторить бюджет прошлого года» "
          + "или добавьте строку вручную."));
    }

    renderTotal(visible);
    document.getElementById("op-count").textContent =
      visible.length + " из " + state.data.totals.rows_count + " строк · " +
      U.fmt(visible.reduce(function (a, r) { return a + r.plan_year; }, 0)) + " ₽";
    document.querySelector("***REMOVED***t-op").classList.toggle("editing", state.editing);
    refreshFilterOptions();
  }

  /* ---------- правка ячеек ---------- */

  function visibleRows() {
    var out = [];
    state.data.blocks.forEach(function (block) {
      block.rows.forEach(function (row) {
        if (passes(row, block.cfo_name)) out.push(row);
      });
    });
    return out;
  }

  function paint(td, row, field) {
    if (MONTH_FIELD.test(field)) {
      var value = row.months[Number(field.slice(1))] || 0;
      td.textContent = value ? U.fmt(value) : (state.editing ? "" : "—");
      td.classList.toggle("dim", !value);
    } else {
      td.textContent = row[field] || "";
    }
  }

  /* Что уходит на сервер при правке ячейки. null — значение не изменилось. */
  function payloadFor(field, text, row) {
    if (MONTH_FIELD.test(field)) {
      var index = Number(field.slice(1));
      var value = U.parseSum(text);
      if (value === (row.months[index] || 0)) return null;
      var months = row.months.slice();
      months[index] = value;
      return { months: months };
    }
    if (field === "detail_text") {
      if (text === (row.detail_text || "")) return null;
      // у ИТ «Детализация» — колонка бюджета, у остальных — наш комментарий
      return row.detail_source === "detail" ? { detail: text } : { comment: text };
    }
    if (text === (row[field] || "")) return null;
    if (field === "article" && !text) throw new Error("Статья оборотов не может быть пустой");
    var payload = {};
    payload[field] = text;
    return payload;
  }

  function applied(row, saved, field, payload) {
    if (payload.months) row.months = payload.months;
    ["article", "counterparty", "contract", "detail", "comment"].forEach(function (key) {
      if (key in saved) row[key] = saved[key];
    });
    if (field === "detail_text") {
      row.detail_text = row.detail_source === "detail" ? saved.detail : saved.comment;
    }
    row.plan_year = Number(saved.plan_year);
  }

  function afterSave(row) {
    var totalCell = document.querySelector('[data-total="' + row.id + '"]');
    if (totalCell) totalCell.textContent = U.fmt(row.plan_year);
    renderTotal(visibleRows());
    refreshFilterOptions();
  }

  /* ---------- замок ---------- */

  function renderLock() {
    var button = document.getElementById("op-lock");
    var locked = state.data.locked;
    button.textContent = locked ? "🔒 Внесение изменений заблокировано" : "🔓 Внесение изменений разрешено";
    button.classList.toggle("locked", locked);
    button.hidden = !state.data.is_fin;
    button.title = locked
      ? "Руководители ЦФО не могут править план. Финансовый отдел — может. Нажмите, чтобы снять."
      : "Нажмите, чтобы закрыть внесение изменений для руководителей ЦФО";

    var banner = document.getElementById("op-locked-note");
    banner.hidden = !(locked && !state.data.can_edit);
    document.getElementById("op-edit").hidden = !state.data.can_edit;
    document.getElementById("op-add").hidden = !state.data.can_edit;
    document.getElementById("op-copy").hidden = !state.data.can_edit;
  }

  /* ---------- пропавшие строки (п.8) ---------- */

  function renderMissing() {
    var data = state.missing;
    var body = document.querySelector("***REMOVED***t-op-missing tbody");
    U.clear(body);
    document.getElementById("op-missing-sub").textContent = data.count
      ? data.count + " строк на " + U.fmt(data.total) + " ₽ были в " + data.base_year +
        " году и не попали в план " + data.plan_year
      : "все расходы " + data.base_year + " года учтены в плане " + data.plan_year;
    document.getElementById("op-add-all").hidden = !data.count || !state.data.can_edit;

    if (!data.count) {
      body.appendChild(U.empty(7, "Ничего не потеряно."));
      return;
    }
    data.items.forEach(function (item) {
      var add = U.el("button", { class: "btn sm", text: "Добавить в " + data.plan_year });
      add.onclick = function () {
        add.disabled = true;
        API.addMissingRow(item.id, data.plan_year)
          .then(function () { reloadAll(); })
          .catch(function (e) { add.disabled = false; U.toast(e.message, "error"); });
      };
      body.appendChild(U.el("tr", {}, [
        U.el("td", { class: "wrap cfo-name", text: item.cfo_name }),
        U.el("td", { class: "wrap", text: item.article }),
        U.el("td", { class: "wrap", text: item.counterparty || "—" }),
        U.el("td", { class: "wrap", text: item.contract || "—" }),
        U.el("td", { class: "wrap" }, [U.el("div", { class: "clamp", text: item.detail_text || "—" })]),
        U.tdn(item.plan_year),
        U.el("td", {}, [state.data.can_edit ? add : U.el("span", { class: "dim", text: "—" })])
      ]));
    });
  }

  function addAllMissing() {
    var items = state.missing.items.slice();
    if (!items.length) return;
    if (!window.confirm("Перенести все " + items.length + " строк в план " +
        state.missing.plan_year + " года?")) return;
    var button = document.getElementById("op-add-all");
    button.disabled = true;
    var done = 0, failed = 0;
    var chain = Promise.resolve();
    items.forEach(function (item) {
      chain = chain.then(function () {
        return API.addMissingRow(item.id, state.missing.plan_year)
          .then(function () { done++; })
          .catch(function () { failed++; });
      });
    });
    chain.then(function () {
      button.disabled = false;
      U.toast("Перенесено строк: " + done + (failed ? ", не удалось: " + failed : ""),
        failed ? "error" : "");
      reloadAll();
    });
  }

  /* ---------- повтор бюджета прошлого года ---------- */

  function runCopy() {
    var pct = U.parseSum(document.getElementById("op-index").value);
    var note = document.getElementById("op-copy-note");
    note.textContent = "Переношу строки…";
    API.copyYear({
      from_year: state.data.base_year_no,
      to_year: state.data.plan_year_no,
      index_pct: pct
    }).then(function (result) {
      note.textContent = "";
      document.getElementById("op-copy-form").hidden = true;
      U.toast("Скопировано строк: " + result.copied + ", пропущено дублей: " + result.skipped +
        (result.index_pct ? ", индексация " + result.index_pct + "%" : ""));
      state.year = state.data.plan_year_no;
      document.getElementById("op-year").value = String(state.year);
      reloadAll();
    }).catch(function (e) { note.textContent = e.message; });
  }

  /* ---------- форма добавления строки ---------- */

  function cfoRefs(cfoId) {
    var all = state.refs && state.refs.all ? state.refs.all
      : { articles: [], counterparties: [], contracts: [] };
    var own = state.refs && state.refs.by_cfo ? state.refs.by_cfo[String(cfoId)] : null;
    return { own: own || { articles: [], counterparties: [], contracts: {} }, all: all };
  }

  function initCombos() {
    if (state.combos) return;
    state.combos = {
      budget: U.combo(document.getElementById("op-a-budget")),
      article: U.combo(document.getElementById("op-a-article")),
      cp: U.combo(document.getElementById("op-a-cp"), function () { syncAddLists(); }),
      contract: U.combo(document.getElementById("op-a-contract"))
    };
  }

  function syncAddLists() {
    initCombos();
    var cfoId = Number(document.getElementById("op-a-cfo").value);
    var refs = cfoRefs(cfoId);
    var showAll = document.getElementById("op-a-all").checked;

    state.combos.article.setOptions(showAll ? refs.all.articles : refs.own.articles);
    state.combos.cp.setOptions(showAll ? refs.all.counterparties : refs.own.counterparties);

    var cp = document.getElementById("op-a-cp").value;
    var contracts = showAll ? refs.all.contracts : (refs.own.contracts[cp] || []);
    if (!showAll && !contracts.length) {
      contracts = Object.keys(refs.own.contracts).reduce(function (acc, key) {
        return acc.concat(refs.own.contracts[key]);
      }, []);
    }
    state.combos.contract.setOptions(contracts);

    var hint = document.getElementById("op-a-hint");
    hint.textContent = showAll
      ? "Показаны значения по всем ЦФО"
      : "Показаны значения этого ЦФО: статей " + refs.own.articles.length +
        ", контрагентов " + refs.own.counterparties.length;

    /* Бюджет выбирают только там, где их несколько: у ИТ-дирекции это бюджет
       обязательных затрат и бюджет развития. У остальных ЦФО бюджет один —
       поле прячем и подставляем его молча. */
    var budgets = {};
    (state.data ? state.data.blocks : []).forEach(function (b) {
      if (b.cfo_id === cfoId) budgets[b.budget_name] = true;
    });
    var names = Object.keys(budgets);
    if (!names.length) names = ["Основной бюджет"];
    var field = document.getElementById("op-a-budget");
    if (!field.value || budgets[field.value] === undefined) field.value = names[0];
    state.combos.budget.setOptions(names);
    document.getElementById("op-a-budget-wrap").hidden = names.length < 2;
  }

  function monthPlan() {
    var amount = U.parseSum(document.getElementById("op-a-sum").value);
    var spread = document.getElementById("op-a-spread").value;
    var month = Number(document.getElementById("op-a-month").value);
    var months = [];
    for (var i = 0; i < 12; i++) months.push(0);
    if (!amount) return months;
    if (spread === "even") {
      for (var j = 0; j < 12; j++) months[j] = Math.round(amount / 12 * 100) / 100;
    } else if (spread === "one") {
      months[month] = amount;
    }
    return months;
  }

  function saveNewRow() {
    var err = document.getElementById("op-a-err");
    err.style.color = "";
    var article = document.getElementById("op-a-article").value.replace(/^\s+|\s+$/g, "");
    var amount = U.parseSum(document.getElementById("op-a-sum").value);
    if (!article) { err.textContent = "Укажите статью оборотов"; return; }
    if (amount <= 0) { err.textContent = "Укажите сумму больше нуля"; return; }

    var months = monthPlan();
    API.createOperplanRow({
      cfo_id: Number(document.getElementById("op-a-cfo").value),
      budget_name: document.getElementById("op-a-budget").value || "Основной бюджет",
      article: article,
      counterparty: document.getElementById("op-a-cp").value,
      contract: document.getElementById("op-a-contract").value,
      detail: document.getElementById("op-a-detail").value,
      comment: document.getElementById("op-a-detail").value,
      plan_year: amount,
      months: months
    }, state.year).then(function () {
      ["op-a-article", "op-a-cp", "op-a-contract", "op-a-detail", "op-a-sum"]
        .forEach(function (id) { document.getElementById(id).value = ""; });
      err.style.color = "var(--good)";
      err.textContent = "Строка добавлена";
      window.setTimeout(function () { err.textContent = ""; err.style.color = ""; }, 2500);
      reloadAll();
    }).catch(function (e) { err.textContent = e.message; });
  }

  /* ---------- загрузка ---------- */

  function load(year) {
    return API.operplan(year).then(function (data) {
      state.data = data;
      state.year = data.year;
      U.fillSelect(document.getElementById("op-year"), data.years, null, null, data.year);
      /* «Показать все» — привилегия финотдела: руководителю сервер и не отдаёт
         чужие статьи с контрагентами, так что галочка ему только мешала бы. */
      var all = document.getElementById("op-a-all");
      all.parentNode.hidden = !data.is_fin;
      if (!data.is_fin) all.checked = false;

      document.getElementById("op-sub").textContent =
        "план " + data.plan_year_no + " года, база — " + data.base_year_no;
      document.getElementById("op-copy-title").textContent =
        "Повторить бюджет " + data.base_year_no + " года в плане " + data.plan_year_no;
      U.fillSelect(document.getElementById("op-a-cfo"),
        (state.cfoList || []).length ? state.cfoList : blockCfoList(), "id", "name");
      initFilters();
      renderLock();
      render();
      syncAddLists();
    });
  }

  function blockCfoList() {
    var seen = {}, out = [];
    (state.data ? state.data.blocks : []).forEach(function (b) {
      if (!seen[b.cfo_id]) { seen[b.cfo_id] = true; out.push({ id: b.cfo_id, name: b.cfo_name }); }
    });
    return out.sort(function (a, b) { return a.name.localeCompare(b.name, "ru"); });
  }

  function reloadAll() {
    return load(state.year).then(function () {
      return Promise.all([
        API.operplanMissing(state.year).then(function (data) {
          state.missing = data;
          renderMissing();
        }),
        API.operplanRefs(state.year).then(function (data) {
          state.refs = data;
          syncAddLists();
        })
      ]);
    }).catch(function (e) { U.toast("Бюджет: " + e.message, "error"); });
  }

  window.Operplan = {
    setCfoList: function (list) { state.cfoList = list; },
    load: reloadAll,
    init: function () {
      initCombos();
      U.fillSelect(document.getElementById("op-a-month"),
        U.MONTHS_FULL.map(function (name, i) { return { value: String(i), text: name }; }),
        "value", "text");
      Inline.bind(document.getElementById("t-op"), {
        row: function (id) { return state.rows[id]; },
        payload: payloadFor,
        applied: applied,
        paint: paint,
        after: afterSave
      });

      document.getElementById("op-year").onchange = function () {
        state.year = Number(this.value);
        reloadAll();
      };
      document.getElementById("op-edit").onclick = function () {
        state.editing = !state.editing;
        this.classList.toggle("primary", state.editing);
        this.textContent = state.editing ? "✓ Готово" : "✎ Редактировать";
        document.getElementById("op-edit-note").hidden = !state.editing;
        render();
      };
      document.getElementById("op-lock").onclick = function () {
        API.operplanLock(state.year, !state.data.locked)
          .then(function () { reloadAll(); })
          .catch(function (e) { U.toast(e.message, "error"); });
      };
      document.getElementById("op-copy").onclick = function () {
        var form = document.getElementById("op-copy-form");
        form.hidden = !form.hidden;
      };
      document.getElementById("op-copy-run").onclick = runCopy;
      document.getElementById("op-copy-cancel").onclick = function () {
        document.getElementById("op-copy-form").hidden = true;
      };
      document.getElementById("op-add").onclick = function () {
        var form = document.getElementById("op-add-form");
        form.hidden = !form.hidden;
        if (!form.hidden) { syncAddLists(); document.getElementById("op-a-article").focus(); }
      };
      document.getElementById("op-a-save").onclick = saveNewRow;
      document.getElementById("op-a-cancel").onclick = function () {
        document.getElementById("op-add-form").hidden = true;
      };
      document.getElementById("op-a-cfo").onchange = syncAddLists;
      // oninput у поля занят выпадающим списком, поэтому вешаем вторым слушателем:
      // набранный вручную контрагент тоже должен сузить список договоров
      document.getElementById("op-a-cp").addEventListener("input", syncAddLists);
      document.getElementById("op-a-all").onchange = syncAddLists;
      document.getElementById("op-a-spread").onchange = function () {
        document.getElementById("op-a-month-wrap").hidden = this.value !== "one";
      };
      document.getElementById("op-add-all").onclick = addAllMissing;
      document.getElementById("op-reset").onclick = function () {
        Object.keys(state.filters).forEach(function (key) { state.filters[key].clear(); });
        render();
      };
      document.getElementById("op-collapse").onclick = function () {
        var anyOpen = state.data.blocks.some(function (b) { return !state.collapsed[b.budget_id]; });
        state.data.blocks.forEach(function (b) { state.collapsed[b.budget_id] = anyOpen; });
        this.textContent = anyOpen ? "Развернуть все" : "Свернуть все";
        render();
      };
    }
  };
})();
