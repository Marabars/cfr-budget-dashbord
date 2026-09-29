/* Вкладка «Бюджет»: план следующего года по всем ЦФО, фильтры, правка таблицы. */
(function () {
  "use strict";

  var state = {
    data: null,          // ответ /api/operplan
    refs: null,          // справочники статей, контрагентов, договоров
    missing: null,       // строки прошлого года, которых нет в плане
    rows: {},            // id -> строка (для правки и пересчёта)
    rowYear: {},         // id -> год строки (чтобы обновить ИТОГО нужного года)
    editing: false,
    collapsed: {},       // budget_id -> свёрнут ли блок
    sections: {},        // год -> ответ /api/operplan по этому году
    yearOpen: {},        // год -> развёрнут ли раздел года в таблице
    missingOpen: false,  // блок замечаний свёрнут, пока его не раскроют
    entryOpen: false,    // панель внесения расходов внутри карточки строк
    filters: null,
    combos: null,       // выпадающие списки формы новой строки
    year: null           // год в фокусе: к нему привязаны замок, справочники и форма строки
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

  /* Значения для фильтров собираем по всем загруженным годам, а не только
     по году в фокусе: иначе, развернув базовый год, пользователь не нашёл бы
     в списке его ЦФО и статьи. */
  function allRows() {
    var out = [];
    Object.keys(state.sections).forEach(function (year) {
      state.sections[year].blocks.forEach(function (block) {
        block.rows.forEach(function (row) {
          out.push(Object.assign({ cfo_name: block.cfo_name }, row));
        });
      });
    });
    return out;
  }

  /* Порядок разделов: год в фокусе первым, остальные ниже по убыванию. */
  function orderedYears() {
    var years = (state.data && state.data.years) ? state.data.years.slice() : [];
    if (years.indexOf(state.year) < 0) years.push(state.year);
    years.sort(function (a, b) { return b - a; });
    return [state.year].concat(years.filter(function (y) { return y !== state.year; }));
  }

  /* Что видно сейчас: строки развёрнутых лет после фильтров и сколько их всего.
     Свёрнутый блок ЦФО в счёт входит — свёрнутый год нет. */
  function visibleContext() {
    var rows = [], years = [], total = 0;
    orderedYears().forEach(function (year) {
      var sec = state.sections[year];
      if (!sec || !state.yearOpen[year]) return;
      years.push(year);
      total += sec.totals.rows_count;
      sec.blocks.forEach(function (block) {
        block.rows.forEach(function (row) {
          if (passes(row, block.cfo_name)) rows.push(row);
        });
      });
    });
    return { rows: rows, years: years, total: total };
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

  /* battery === null — плитка без шкалы. st-plan красит заполненные сегменты:
     без класса статуса они оставались цветом фона и шкала выглядела пустой. */
  function kpiTile(label, value, tone, battery, note) {
    var cls = "kpi " + (tone || "") + (battery === null ? "" : " st-plan");
    return U.el("div", { class: cls }, [
      U.el("div", { class: "lbl", text: label }),
      U.el("div", { class: "val hero", text: value }),
      battery === null ? U.el("div", { class: "sub", text: note }) : U.battery(battery, null),
      battery === null ? null : U.el("div", { class: "batt-note", text: note })
    ]);
  }

  function renderKpi() {
    var k = state.data.kpi;
    var host = document.getElementById("op-kpis");
    U.clear(host);
    /* Шкала первой плитки — сколько плана уже набрано от прошлогоднего бюджета.
       Она растёт по мере наполнения плана; 100% = повторили прошлый год. */
    host.appendChild(kpiTile(
      "Бюджет " + k.plan_year + " года", U.fmtShort(k.plan_total) + " ₽", "k-accent",
      k.base_total ? k.plan_ratio : null,
      k.base_total ? "от бюджета " + k.base_year + " года · " + k.plan_rows + " строк"
        : k.plan_rows + " строк плана"));
    host.appendChild(kpiTile(
      "Бюджет " + k.base_year + " года", U.fmtShort(k.base_total) + " ₽", "k-warm",
      null, k.base_rows + " строк базы"));
    host.appendChild(kpiTile(
      "План-факт " + k.base_year, U.fmtShort(k.base_fact) + " ₽",
      k.fact_loaded ? "k-good" : "",
      k.fact_loaded ? k.base_pct : null,
      k.fact_loaded ? "освоено от бюджета " + k.base_year
        : "факт за " + k.base_year + " год ещё не загружен"));
    renderSummary(k);
  }

  /* Резюме: одной строкой то же, что на плитках, — чтобы не считать в уме. */
  function renderSummary(k) {
    var parts = [
      "план " + k.plan_year + ": " + U.fmt(k.plan_total) + " ₽ по " + k.plan_rows + " строкам",
      "база " + k.base_year + ": " + U.fmt(k.base_total) + " ₽ по " + k.base_rows + " строкам",
      k.fact_loaded
        ? "факт " + k.base_year + ": " + U.fmt(k.base_fact) + " ₽"
        : "факт " + k.base_year + " не загружен"
    ];
    if (state.missing && state.missing.count) {
      parts.push("замечаний: " + state.missing.count);
    }
    document.getElementById("op-sub").textContent = parts.join(" · ");
  }

  /* ---------- какой год перед пользователем ---------- */

  /* На вкладке соседствуют план нового года и залитая база прошлого, а таблицы
     у них одинаковые. Поэтому год подписан в заголовке, в метке и в строке ИТОГО. */
  function renderYearMark() {
    var isPlan = state.year === state.data.plan_year_no;
    var text = state.year + " год · " + (isPlan ? "план" : "база");
    ["op-year-tag", "op-year-tag-top"].forEach(function (id) {
      var node = document.getElementById(id);
      node.textContent = text;
      node.classList.toggle("is-base", !isPlan);
    });
    var title = document.getElementById("op-rows-title");
    title.textContent = "Строки бюджета";
    title.parentNode.parentNode.classList.toggle("y-base", !isPlan);
  }

  /* Правка года разрешена, когда у роли есть доступ и год не заблокирован.
     Финотделу сервер разрешает править и под замком — замок для него означает
     «я закрыл правку», поэтому таблица гасится и на его экране тоже. */
  function sectionEditable(sec) {
    return !!sec && !!sec.can_edit && !sec.locked;
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

  /* Итог считается по каждому году отдельно: складывать план 2027 с базой 2026
     бессмысленно, поэтому общей строки ИТОГО у таблицы больше нет. */
  function totalNode(year, rows, allRows) {
    var total = U.el("tr", { class: "total-row", "data-year": year });
    var months = [];
    for (var i = 0; i < 12; i++) months.push(0);
    var sum = 0, base = 0;
    rows.forEach(function (row) {
      sum += row.plan_year;
      base += row.base_plan_year || 0;
      for (var i = 0; i < 12; i++) months[i] += row.months[i] || 0;
    });
    var filtered = rows.length !== allRows;
    total.appendChild(U.el("td", { colspan: 5, class: "total-label",
      text: "ИТОГО " + year + (filtered ? " по фильтру · " + rows.length + " строк"
        : " · " + rows.length + " строк") }));
    total.appendChild(U.el("td", { class: "num total-sum", text: U.fmt(sum) }));
    months.forEach(function (value) {
      total.appendChild(U.el("td", { class: "num", text: value ? U.fmt(value) : "—" }));
    });
    total.appendChild(U.el("td", { class: "num dim", text: base ? U.fmt(base) : "—" }));
    return total;
  }

  /* ---------- строки ---------- */

  function editableCell(row, field, value, cls, editable) {
    return Inline.cell(row.id, field, value, cls, editable);
  }

  /* editable считается по году строки, а не по году в фокусе: замок стоит на год,
     и раскрытый базовый год может быть закрыт для правки, когда плановый открыт. */
  function rowNode(row, cfoName, canEdit) {
    var tr = U.el("tr", { "data-id": row.id });
    var editable = canEdit;

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
      editable ? del : null
    ])]));

    FIELDS.forEach(function (f) {
      tr.appendChild(editableCell(row, f.key, row[f.key] || "", "wrap", editable));
    });

    tr.appendChild(U.el("td", { class: "num n-plan", "data-total": row.id,
      text: U.fmt(row.plan_year) }));

    for (var i = 0; i < 12; i++) {
      var value = row.months[i] || 0;
      var td = editableCell(row, "m" + i, value ? U.fmt(value) : (state.editing ? "" : "—"),
        "num" + (value ? "" : " dim"), editable);
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

  /* Объём года известен из KPI ещё до того, как раздел загружен. */
  function yearSummary(year, sec) {
    if (sec) return { rows: sec.totals.rows_count, total: sec.totals.plan_year };
    var k = state.data.kpi;
    if (year === k.plan_year) return { rows: k.plan_rows, total: k.plan_total };
    if (year === k.base_year) return { rows: k.base_rows, total: k.base_total };
    return { rows: 0, total: 0 };
  }

  function yearNode(year, sec, open) {
    var isPlan = year === state.data.plan_year_no;
    var s = yearSummary(year, sec);
    var td = U.el("td", { colspan: COLS }, [
      U.el("span", { class: "grp-caret", text: open ? "▾" : "▸" }),
      U.el("b", { text: year + " год" }),
      U.el("span", { class: "year-tag" + (isPlan ? "" : " is-base"),
        text: isPlan ? "план" : "база" }),
      U.el("span", { class: "grp-sum", text: U.fmt(s.total) + " ₽ · " + s.rows + " строк" })
    ]);
    var tr = U.el("tr", { class: "year-row" + (isPlan ? "" : " is-base") }, [td]);
    tr.onclick = function () {
      state.yearOpen[year] = !open;
      render();
    };
    return tr;
  }

  function render() {
    if (!state.data) return;
    renderKpi();
    renderYearMark();
    renderHead();

    var body = document.querySelector("***REMOVED***t-op tbody");
    U.clear(body);
    state.rows = {};
    state.rowYear = {};

    /* Годы идут разделами: план нового года сверху развёрнут, база прошлого —
       свёрнута под ним. Клик по строке года разворачивает и сворачивает раздел. */
    orderedYears().forEach(function (year) {
      var sec = state.sections[year];
      var open = !!state.yearOpen[year];
      body.appendChild(yearNode(year, sec, open));
      if (!sec || !open) return;
      var editable = sectionEditable(sec);
      var yearRows = [];
      var nodes = [];
      sec.blocks.forEach(function (block) {
        var rows = block.rows.filter(function (row) { return passes(row, block.cfo_name); });
        if (!rows.length) return;
        var sum = rows.reduce(function (acc, row) { return acc + row.plan_year; }, 0);
        nodes.push(groupNode(block, rows.length, sum));
        rows.forEach(function (row) {
          state.rows[row.id] = row;
          state.rowYear[row.id] = year;
          yearRows.push(row);
        });
        if (state.collapsed[block.budget_id]) return;
        rows.forEach(function (row) {
          var node = rowNode(row, block.cfo_name, editable);
          if (year !== state.data.plan_year_no) node.classList.add("y-past");
          nodes.push(node);
        });
      });
      // ИТОГО года идёт сразу под его заголовком, до блоков ЦФО
      body.appendChild(totalNode(year, yearRows, sec.totals.rows_count));
      nodes.forEach(function (node) { body.appendChild(node); });
    });

    var ctx = visibleContext();
    if (!ctx.rows.length) {
      body.appendChild(U.empty(COLS, ctx.total
        ? "Под фильтр ничего не подошло — снимите часть условий."
        : ctx.years.length
          ? "Пока нет строк за " + ctx.years.join(" и ") + ". Нажмите «Повторить бюджет "
            + "прошлого года» или добавьте строку вручную."
          : "Все годы свёрнуты — раскройте нужный строкой года выше."));
    }

    /* Счётчик тоже по годам: общая сумма плана и базы вместе смысла не имеет. */
    document.getElementById("op-count").textContent = ctx.years.length
      ? ctx.years.map(function (year) {
          var sec = state.sections[year];
          var rows = ctx.rows.filter(function (r) { return state.rowYear[r.id] === year; });
          var sum = rows.reduce(function (a, r) { return a + r.plan_year; }, 0);
          return year + ": " + (rows.length === sec.totals.rows_count
            ? rows.length + " строк"
            : rows.length + " из " + sec.totals.rows_count + " строк") +
            " · " + U.fmt(sum) + " ₽";
        }).join("   ·   ")
      : "все годы свёрнуты";
    document.querySelector("***REMOVED***t-op").classList.toggle("editing", state.editing);
    refreshFilterOptions();
  }

  /* ---------- правка ячеек ---------- */

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

  /* Пересобирает строку ИТОГО одного года на месте — полная перерисовка таблицы
     после правки ячейки выбивала бы фокус из соседней. */
  function repaintTotal(year) {
    var sec = state.sections[year];
    var old = document.querySelector('***REMOVED***t-op tbody tr.total-row[data-year="' + year + '"]');
    if (!sec || !old || !old.parentNode) return;
    var rows = [];
    sec.blocks.forEach(function (block) {
      block.rows.forEach(function (row) {
        if (passes(row, block.cfo_name)) rows.push(row);
      });
    });
    var fresh = totalNode(year, rows, sec.totals.rows_count);
    old.parentNode.insertBefore(fresh, old);
    old.parentNode.removeChild(old);
  }

  function afterSave(row) {
    var totalCell = document.querySelector('[data-total="' + row.id + '"]');
    if (totalCell) totalCell.textContent = U.fmt(row.plan_year);
    repaintTotal(state.rowYear[row.id]);
    refreshFilterOptions();
  }

  /* ---------- панель внесения расходов ---------- */

  /* Панель свёрнута по умолчанию и живёт внутри карточки строк — на странице
     одним блоком меньше. Кнопка-переключатель в шапке таблицы не прячется
     никогда, поэтому возможность внести строку не может пропасть. */
  function renderEntry() {
    var editable = sectionEditable(state.data);
    if (!editable) state.entryOpen = false;
    var toggle = document.getElementById("op-entry-toggle");
    toggle.hidden = !editable;
    toggle.textContent = state.entryOpen ? "× Скрыть внесение" : "+ Внести расходы";
    toggle.classList.toggle("primary", !state.entryOpen);
    document.getElementById("op-entry").hidden = !state.entryOpen;
  }

  /* ---------- замок ---------- */

  /* Правка включена по умолчанию; кнопка с перечёркнутым карандашом её закрывает.
     Замок общий на год: финотдел закрывает правку и себе, чтобы случайно не задеть
     утверждённый план, и тем же нажатием открывает обратно. */
  function renderLock() {
    var locked = !!state.data.locked;
    var editable = sectionEditable(state.data);
    state.editing = editable;

    var button = document.getElementById("op-lock");
    button.hidden = !state.data.is_fin;
    button.textContent = locked ? "✎̸ Правка заблокирована" : "✎ Правка разрешена";
    button.classList.toggle("locked", locked);
    button.title = locked
      ? "Правка плана " + state.data.plan_year_no + " закрыта. Нажмите, чтобы разрешить."
      : "Нажмите, чтобы заблокировать правку плана " + state.data.plan_year_no;

    document.getElementById("op-locked-note").hidden = !locked;
    document.getElementById("op-edit-note").hidden = !editable;
    document.getElementById("op-edit-scope").textContent = state.data.is_fin
      ? "Правка плана по всем ЦФО." : "Правка плана вашего ЦФО.";

    ["op-a-save", "op-copy-run", "op-fact-run"].forEach(function (id) {
      document.getElementById(id).disabled = !editable;
    });
    document.getElementById("op-entry-title").textContent =
      "Внесение плановых расходов на " + state.data.plan_year_no + " год";
    document.getElementById("op-copy-title").textContent =
      "Перенести " + state.data.base_year_no + " год в план " + state.data.plan_year_no;
    /* Загрузка доступна всем, кто вправе править: круг ЦФО режет сервер, чужие
       строки файла он пропускает. Под замком грузить нечего — кнопку убираем,
       иначе она отвечала бы 403. Выгрузка и шаблон не зависят от замка. */
    document.getElementById("op-import").hidden = !editable;
    if (!editable) document.getElementById("op-import-form").hidden = true;
    renderEntry();
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
    document.getElementById("op-add-all").hidden =
      !data.count || !sectionEditable(state.data) || !state.missingOpen;
    if (state.data && state.data.kpi) renderSummary(state.data.kpi);

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

  /* source: "plan" — суммы берутся из бюджета прошлого года, "fact" — из факта.
     Доступные ЦФО режет сервер, руководителю переносится только его дирекция. */
  function runCopy(source) {
    var pct = U.parseSum(document.getElementById("op-index").value);
    var note = document.getElementById("op-copy-note");
    note.style.color = "";
    note.textContent = "Переношу строки…";
    API.copyYear({
      from_year: state.data.base_year_no,
      to_year: state.data.plan_year_no,
      index_pct: pct,
      source: source || "plan"
    }).then(function (result) {
      note.textContent = "";
      var what = source === "fact" ? "факт" : "бюджет";
      if (!result.copied && result.skipped) {
        U.toast("Всё уже в плане: пропущено дублей " + result.skipped);
      } else if (!result.copied) {
        U.toast("Переносить нечего: за " + state.data.base_year_no +
          " год нет подходящих строк" + (source === "fact" ? " с фактом" : ""), "error");
      } else {
        U.toast("Перенесён " + what + ": строк " + result.copied +
          ", пропущено дублей " + result.skipped +
          (result.index_pct ? ", индексация " + result.index_pct + "%" : ""));
      }
      state.yearOpen[state.data.plan_year_no] = true;
      reloadAll();
    }).catch(function (e) { note.style.color = "var(--critical)"; note.textContent = e.message; });
  }

  /* ---------- Excel ---------- */

  function runExport() {
    window.location.href = "/api/export/budget.xlsx?year=" + state.data.plan_year_no;
  }

  /* Шаблон — тот же лист «Бюджеты ЦФО», но пустой: блоки своих ЦФО и подсказка.
     Заполненный файл принимается кнопкой «Загрузить из Excel». */
  function runTemplate() {
    window.location.href = "/api/export/budget-template.xlsx?year=" + state.data.plan_year_no;
  }

  function runImport() {
    var note = document.getElementById("op-import-note");
    var input = document.getElementById("op-import-file");
    if (!input.files || !input.files.length) {
      note.style.color = "var(--critical)";
      note.textContent = "Выберите файл .xlsx";
      return;
    }
    var kind = "plan";
    Array.prototype.forEach.call(
      document.querySelectorAll('input[name="op-imp-kind"]'), function (radio) {
        if (radio.checked) kind = radio.value;
      });
    note.style.color = "";
    note.textContent = "Загружаю…";
    // факт грузится за базовый год, бюджет — за плановый
    var year = kind === "fact" ? state.data.base_year_no : state.data.plan_year_no;
    API.importBudget(input.files[0], year, kind)
      .then(function (result) {
        note.textContent = "";
        input.value = "";
        document.getElementById("op-import-form").hidden = true;
        U.toast("Загружено строк: " + result.rows +
          (result.unmatched ? ", заведено новых: " + result.unmatched : "") +
          (result.removed ? ", заменено прежних: " + result.removed : "") +
          (result.foreign ? ", пропущено чужих ЦФО: " + result.foreign : ""));
        reloadAll();
      })
      .catch(function (e) { note.style.color = "var(--critical)"; note.textContent = e.message; });
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
    var spread = document.getElementById("op-a-spread").value;
    if (!article) { err.textContent = "Укажите статью оборотов"; return; }
    /* При «не распределять» сумма необязательна: создаётся пустая строка,
       в которую суммы вписывают прямо в таблице по месяцам. */
    if (spread !== "none" && amount <= 0) {
      err.textContent = "Укажите сумму больше нуля или выберите «не распределять»";
      return;
    }
    if (amount < 0) { err.textContent = "Сумма не может быть отрицательной"; return; }

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
    }, state.data.plan_year_no).then(function () {
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
      state.sections[data.year] = data;
      /* Год в фокусе всегда раскрыт, остальные по умолчанию свёрнуты. */
      state.yearOpen[data.year] = true;
      /* «Показать все» — привилегия финотдела: руководителю сервер и не отдаёт
         чужие статьи с контрагентами, так что галочка ему только мешала бы. */
      var all = document.getElementById("op-a-all");
      all.parentNode.hidden = !data.is_fin;
      if (!data.is_fin) all.checked = false;

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
    Object.keys(state.sections).forEach(function (year) {
      state.sections[year].blocks.forEach(function (b) {
        if (seen[b.cfo_id]) return;
        seen[b.cfo_id] = true;
        out.push({ id: b.cfo_id, name: b.cfo_name });
      });
    });
    return out.sort(function (a, b) { return a.name.localeCompare(b.name, "ru"); });
  }

  /* Остальные годы догружаем сразу: их разделы свёрнуты, но сумма и число строк
     в заголовке года должны быть настоящими, а фильтры — знать про их значения. */
  function loadOtherYears() {
    var others = (state.data.years || []).filter(function (y) { return y !== state.year; });
    return Promise.all(others.map(function (year) {
      return API.operplan(year).then(function (data) {
        state.sections[year] = data;
        if (state.yearOpen[year] === undefined) state.yearOpen[year] = false;
      });
    }));
  }

  function reloadAll() {
    return load(state.year).then(function () {
      return Promise.all([
        loadOtherYears().then(function () { render(); }),
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

      document.getElementById("op-lock").onclick = function () {
        API.operplanLock(state.data.plan_year_no, !state.data.locked)
          .then(function () { reloadAll(); })
          .catch(function (e) { U.toast(e.message, "error"); });
      };
      document.getElementById("op-copy-run").onclick = function () { runCopy("plan"); };
      document.getElementById("op-fact-run").onclick = function () { runCopy("fact"); };
      document.getElementById("op-export").onclick = runExport;
      document.getElementById("op-template").onclick = runTemplate;
      document.getElementById("op-entry-toggle").onclick = function () {
        state.entryOpen = !state.entryOpen;
        renderEntry();
        if (state.entryOpen) {
          document.getElementById("op-entry").scrollIntoView({ block: "nearest" });
          document.getElementById("op-a-article").focus();
        }
      };
      document.getElementById("op-import").onclick = function () {
        var form = document.getElementById("op-import-form");
        form.hidden = !form.hidden;
      };
      document.getElementById("op-import-run").onclick = runImport;
      document.getElementById("op-import-cancel").onclick = function () {
        document.getElementById("op-import-form").hidden = true;
      };
      document.getElementById("op-a-save").onclick = saveNewRow;
      document.getElementById("op-a-cfo").onchange = syncAddLists;
      // oninput у поля занят выпадающим списком, поэтому вешаем вторым слушателем:
      // набранный вручную контрагент тоже должен сузить список договоров
      document.getElementById("op-a-cp").addEventListener("input", syncAddLists);
      document.getElementById("op-a-all").onchange = syncAddLists;
      document.getElementById("op-a-spread").onchange = function () {
        document.getElementById("op-a-month-wrap").hidden = this.value !== "one";
      };
      document.getElementById("op-add-all").onclick = function (event) {
        event.stopPropagation();          // кнопка внутри кликабельного заголовка
        addAllMissing();
      };
      /* Замечания свёрнуты: это справка «что потеряли», а не ежедневная работа. */
      document.getElementById("op-missing-head").onclick = function () {
        state.missingOpen = !state.missingOpen;
        document.getElementById("op-missing-body").hidden = !state.missingOpen;
        document.getElementById("op-missing-caret").textContent = state.missingOpen ? "▾" : "▸";
        if (state.missing) renderMissing();
      };
      document.getElementById("op-info").onclick = function () {
        var panel = document.getElementById("op-info-panel");
        panel.hidden = !panel.hidden;
        this.classList.toggle("primary", !panel.hidden);
      };
      document.getElementById("op-reset").onclick = function () {
        Object.keys(state.filters).forEach(function (key) { state.filters[key].clear(); });
        render();
      };
      document.getElementById("op-collapse").onclick = function () {
        var blocks = [];
        Object.keys(state.sections).forEach(function (year) {
          if (state.yearOpen[year]) blocks = blocks.concat(state.sections[year].blocks);
        });
        var anyOpen = blocks.some(function (b) { return !state.collapsed[b.budget_id]; });
        blocks.forEach(function (b) { state.collapsed[b.budget_id] = anyOpen; });
        this.textContent = anyOpen ? "Развернуть все" : "Свернуть все";
        render();
      };
    }
  };
})();
