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
    spendOpen: {},       // id строки -> раскрыты ли расходы по контрагентам
    missingOpen: false,  // блок замечаний свёрнут, пока его не раскроют
    filters: null,
    fresh: {},           // id строк, заведённых в этой сессии: подсвечены и правятся списками
    editMode: false,     // правка по ячейкам включается карандашом, а не всегда
    year: null           // год в фокусе: к нему привязаны замок и справочники
  };

  /* Классификатор юрлица: значений ровно два, поэтому правится списком,
     а не набором текста. Порядок колонок — как в выгрузке Excel. */
  var CLASSIFIERS = ["МРГ", "МРК"];
  var CLASSIFIER_DEFAULT = "МРГ";

  var FIELDS = [
    { key: "article", title: "Статья оборотов" },
    { key: "classifier", title: "Классификатор" },
    { key: "counterparty", title: "Контрагент" },
    { key: "contract", title: "Договор" },
    { key: "detail_text", title: "Детализация" }
  ];
  var MONTH_FIELD = /^m\d+$/;
  // № + текстовые колонки + ИТОГО + 12 месяцев + прошлый год
  var COLS = 1 + FIELDS.length + 1 + 12 + 1;

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

  function byText(a, b) {
    return String(a || "").localeCompare(String(b || ""), "ru");
  }

  /* Порядок строк внутри блока ЦФО: статьи по алфавиту, внутри статьи —
     контрагенты, затем договоры. Одинаковые ключи разводит номер строки,
     чтобы порядок не плавал между перерисовками.

     Незаполненные строки держим сверху блока: их только что завели кнопкой
     «+ расход», и уезжать вниз по алфавиту им незачем — их ещё заполняют.

     Сортируем на клиенте: выгрузка в Excel повторяет раскладку исходного
     листа, и менять там порядок нельзя — файл возвращают загрузкой обратно. */
  function sortRows(rows) {
    return rows.slice().sort(function (a, b) {
      var emptyA = !(a.article || "").length, emptyB = !(b.article || "").length;
      if (emptyA !== emptyB) return emptyA ? -1 : 1;
      return byText(a.article, b.article)
        || byText(a.counterparty, b.counterparty)
        || byText(a.contract, b.contract)
        || (a.row_no || 0) - (b.row_no || 0);
    });
  }

  /* Под активным фильтром пустые заголовки дирекций прячем: фильтр — это поиск
     по уже внесённому, и пустые блоки только мешали бы читать результат. */
  function filtering() {
    return Object.keys(state.filters || {}).some(function (key) {
      return state.filters[key].selected().length > 0;
    });
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
    /* Четвёртая плитка — потраченное мимо плана: и объявленное дирекцией в
       блоке «ВНЕ БЮДЖЕТА», и то, чему не нашлось строки. При фильтре по
       дирекции показывает её одну, без фильтра — сумму по всем доступным. */
    host.appendChild(kpiTile(
      "Вне бюджета " + k.base_year, U.fmtShort(k.outside_total) + " ₽",
      k.outside_total ? "k-crit" : "",
      k.outside_total ? k.outside_pct : null,
      k.outside_total
        ? k.outside_rows + " позиций в " + k.outside_cfo + " ЦФО · от бюджета " + k.base_year
        : "расхода без строки бюджета нет"));
    renderSummary();
  }

  /* Строка под плитками. Прежде она повторяла их словами — план, базу и факт,
     те же числа второй раз. Оставлено только то, чего на плитках нет. */
  function renderSummary() {
    var count = state.missing && state.missing.count;
    document.getElementById("op-sub").textContent =
      count ? "замечаний: " + count : "";
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
  /* Право на правку: планируемый год, доступ есть, замок снят. Прошлый год —
     база для сравнения, его сервер править и не даст. */
  function sectionEditable(sec) {
    return !!sec && !!sec.can_edit && !sec.locked
      && !!state.data && sec.year === state.data.plan_year_no;
  }

  /* Правят ли сейчас: к праву добавляется включённый карандаш. */
  function sectionEditing(sec) {
    return sectionEditable(sec) && state.editMode;
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
    total.appendChild(U.el("td", { colspan: FIELDS.length + 1, class: "total-label",
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

  /* Строка считается новой, пока её заводили в этой сессии или пока в ней нет
     статьи: такую подсвечиваем и правим списками, а не голым текстом. Пустая
     статья переживает перезагрузку страницы, поэтому брошенную строку видно
     и после F5. */
  function isDraft(row) {
    return !!state.fresh[row.id] || !(row.article || "").length;
  }

  /* editable считается по году строки, а не по году в фокусе: замок стоит на год,
     и раскрытый базовый год может быть закрыт для правки, когда плановый открыт. */
  function rowNode(row, cfoName, canEdit, position) {
    var tr = U.el("tr", { "data-id": row.id });
    var editable = canEdit;
    var unfinished = isDraft(row);
    var draft = editable && unfinished;
    // подсветка держится и вне режима правки: брошенную заготовку надо видеть
    if (unfinished && state.rowYear[row.id] !== state.data.base_year_no) {
      tr.classList.add("is-new");
    }

    var del = U.el("button", { class: "mini", title: "Удалить строку", text: "✕" });
    del.onclick = function (event) {
      event.stopPropagation();
      var what = row.article ? "строку «" + row.article + "»" : "пустую строку";
      if (!window.confirm("Удалить " + what + "?")) return;
      API.deleteRow(row.id)
        .then(function () {
          delete state.fresh[row.id];
          U.toast("Строка удалена");
          load(state.rowYear[row.id] || state.year);
        })
        .catch(function (e) { U.toast(e.message, "error"); });
    };
    /* В колонке № — позиция строки в блоке, а не номер из исходного файла:
       таблица отсортирована по статьям, и файловые номера в ней выглядели
       вперемешку. Настоящие номера проставляются, когда план утверждают
       замком, — тогда позиция и номер совпадают. */
    tr.appendChild(U.el("td", {}, [U.el("div", { class: "no-cell" }, [
      U.el("span", { text: position || "•" }),
      (row.spends && row.spends.length) ? spendToggle(row) : null,
      editable ? del : null
    ])]));

    FIELDS.forEach(function (f) {
      if (f.key === "classifier") {
        tr.appendChild(classifierCell(row, editable));
      } else {
        tr.appendChild(draft ? pickCell(row, f.key)
          : editableCell(row, f.key, row[f.key] || "", "wrap", editable));
      }
    });

    tr.appendChild(draft ? sumCell(row) : U.el("td", { class: "num n-plan",
      "data-total": row.id, text: U.fmt(row.plan_year) }));

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

  /* ---------- расходы под строкой ---------- */

  /* Из чего сложился факт строки: контрагент, договор и те же двенадцать
     месяцев. Отдельные платежи сюда не разворачиваются — у дирекции вроде
     Сервисного обслуживания их сотни; в файле дирекции расход тоже сгруппирован
     по контрагенту. Строки раскрываются по клику на значок в колонке №. */
  function spendNode(spend, parentPosition) {
    var cells = [U.el("td", {}, [U.el("div", { class: "no-cell" }, [
      U.el("span", { class: "dim", text: "↳ " + (parentPosition || "") })])])];
    FIELDS.forEach(function (f) {
      var value = "";
      if (f.key === "counterparty") value = spend.counterparty || "—";
      else if (f.key === "contract") value = spend.contract || "—";
      else if (f.key === "detail_text") value = spend.detail || "";
      cells.push(U.el("td", { class: "wrap dim", text: value }));
    });
    cells.push(U.el("td", { class: "num dim", text: "—" }));
    for (var i = 0; i < 12; i++) {
      var amount = spend.months[i] || 0;
      cells.push(U.el("td", { class: "num" + (amount ? "" : " dim"),
        text: amount ? U.fmt(amount) : "—" }));
    }
    cells.push(U.el("td", { class: "num dim", text: U.fmt(spend.total) }));
    return U.el("tr", { class: "spend-row" }, cells);
  }

  function spendToggle(row) {
    var open = !!state.spendOpen[row.id];
    var btn = U.el("button", {
      class: "mini", title: "Расходы по контрагентам: " + row.spends.length,
      text: open ? "−" : "+"
    });
    btn.onclick = function (event) {
      event.stopPropagation();
      state.spendOpen[row.id] = !open;
      render();
    };
    return btn;
  }

  /* ---------- подсказки при правке ячейки ---------- */

  var SUGGEST = ["article", "counterparty", "contract", "detail_text"];
  var openSuggest = null;

  /* Ячейку правят на месте, contenteditable, — но значения те же, что в новой
     строке: статьи, контрагенты, договоры и детализация своего ЦФО. Список
     подставляется к ячейке по фокусу и сужается по набранному тексту. Где
     справочник пуст (детализация не у ИТ), ячейка остаётся свободным текстом. */
  function bindSuggest(table) {
    table.addEventListener("focusin", function (event) {
      var td = event.target;
      if (openSuggest) { openSuggest.close(); openSuggest = null; }
      if (td.tagName !== "TD" || !td.hasAttribute("contenteditable")) return;
      var field = td.getAttribute("data-f");
      var row = state.rows[Number(td.getAttribute("data-id"))];
      if (!row || SUGGEST.indexOf(field) < 0) { U.closePopups(); return; }
      var options = cellOptions(row, field);
      if (!options || !options.length) { U.closePopups(); return; }
      /* На фокусе показываем весь список, не сужая его тем, что уже в ячейке:
         в неё заходят как раз затем, чтобы поменять значение. Сужает набор
         текста — это обрабатывается ниже. */
      openSuggest = U.suggest(td, options, function (value) {
        td.textContent = value;
        td.blur();                       // Inline сохранит по focusout
      });
    });

    table.addEventListener("input", function (event) {
      if (openSuggest && event.target.hasAttribute("contenteditable")) {
        openSuggest.filter(event.target.textContent);
      }
    });

    table.addEventListener("focusout", function () {
      if (openSuggest) { openSuggest.close(); openSuggest = null; }
    });
  }

  /* ---------- ячейки новой строки ---------- */

  var PLACEHOLDER = {
    article: "статья оборотов", counterparty: "контрагент",
    contract: "договор", detail_text: "на что расход"
  };

  /* Значения списка для ячейки. Договоры сужаются по контрагенту строки, как
     это было в прежней форме: иначе список тянул бы все договоры дирекции. */
  function cellOptions(row, field) {
    var refs = cfoRefs(row.cfo_id);
    var all = document.getElementById("op-a-all").checked;
    if (field === "article") return all ? refs.all.articles : refs.own.articles;
    if (field === "counterparty") {
      return all ? refs.all.counterparties : refs.own.counterparties;
    }
    if (field === "contract") {
      if (all) return refs.all.contracts;
      var byCp = refs.own.contracts || {};
      if (row.counterparty && byCp[row.counterparty]) return byCp[row.counterparty];
      return Object.keys(byCp).reduce(function (acc, key) {
        return acc.concat(byCp[key]);
      }, []);
    }
    if (field === "detail_text") {
      /* Детализация подсказывает только там, где колонка своя (ИТ): у остальных
         дирекций в ней лежит комментарий к строке, и прошлые фразы в нём не
         повторяются. Галочка «все» список не расширяет — чужие расшифровки
         подсказкой не работают. */
      if (row.detail_source !== "detail") return null;
      var details = refs.own.details || [];
      return details.length ? details : null;
    }
    return null;
  }

  function commitCell(row, field, text, td) {
    var value = (text || "").replace(/^\s+|\s+$/g, "");
    if (value === (row[field] || "")) return;
    var payload = {};
    if (field === "detail_text") {
      payload[row.detail_source === "detail" ? "detail" : "comment"] = value;
    } else {
      payload[field] = value;
    }
    td.classList.add("saving");
    API.patchRow(row.id, payload).then(function (result) {
      td.classList.remove("saving");
      applied(row, result.row, field, payload);
      afterSave(row);
    }).catch(function (e) {
      td.classList.remove("saving");
      U.toast(e.message, "error");
    });
  }

  /* Классификатор — не текст, а выбор из двух. Отдельной ячейкой, а не через
     Inline: contenteditable пустил бы туда что угодно, а сервер знает ровно
     два значения и на третье отвечает 422. */
  function classifierCell(row, editable) {
    var value = row.classifier || CLASSIFIER_DEFAULT;
    if (!editable) {
      return U.el("td", { class: "cls", text: value });
    }
    var td = U.el("td", { class: "cls" });
    var select = U.el("select", { class: "cls-pick" });
    CLASSIFIERS.forEach(function (name) {
      select.appendChild(U.el("option", { value: name, text: name }));
    });
    select.value = value;
    select.addEventListener("change", function () {
      commitCell(row, "classifier", select.value, td);
    });
    td.appendChild(select);
    return td;
  }

  function pickCell(row, field) {
    var td = U.el("td", { class: "wrap cell-pick" });
    var input = U.el("input", { class: "f-in", value: row[field] || "" });
    input.placeholder = PLACEHOLDER[field] || "";
    td.appendChild(input);
    var options = cellOptions(row, field);
    if (!options) {
      // справочника нет — гасим чужой список, иначе он висел бы поверх таблицы
      input.addEventListener("focus", U.closePopups);
    }
    if (options) {
      var box = U.combo(input, function (value) { commitCell(row, field, value, td); }, true);
      box.setOptions(options);
      // список договоров пересобираем на фокусе: контрагента могли выбрать секунду назад
      input.addEventListener("focus", function () { box.setOptions(cellOptions(row, field)); });
    }
    input.addEventListener("change", function () { commitCell(row, field, input.value, td); });
    return td;
  }

  /* Как разложить годовую сумму по месяцам. Один список вместо двух полей:
     «равномерно», «не раскладывать» и двенадцать месяцев подряд. */
  function spreadOptions() {
    var out = [{ value: "even", text: "равномерно" },
               { value: "none", text: "не раскладывать" }];
    U.MONTHS_FULL.forEach(function (name, i) {
      out.push({ value: String(i), text: "весь в " + name.toLowerCase() });
    });
    return out;
  }

  function spreadMonths(amount, mode) {
    var months = [];
    for (var i = 0; i < 12; i++) months.push(0);
    if (!amount || mode === "none") return months;
    if (mode === "even") {
      for (var j = 0; j < 12; j++) months[j] = Math.round(amount / 12 * 100) / 100;
      return months;
    }
    months[Number(mode)] = amount;
    return months;
  }

  function sumCell(row) {
    var td = U.el("td", { class: "num n-plan cell-sum", "data-total": row.id });
    var input = U.el("input", { class: "f-in sum-in",
      value: row.plan_year ? U.fmt(row.plan_year) : "" });
    var spread = U.el("select", { class: "f-in spread-in" });
    U.fillSelect(spread, spreadOptions(), "value", "text");
    spread.value = state.spread || "even";

    /* При «не раскладывать» сумму за год вводить незачем: строку заводят пустой
       и вписывают суммы по месяцам, а ИТОГО складывается из них само. Поле
       остаётся на месте, но только показывает результат. */
    function syncMode() {
      var manual = spread.value === "none";
      input.readOnly = manual;
      input.classList.toggle("dim", manual);
      input.placeholder = manual ? "сложится по месяцам" : "сумма за год";
      input.title = manual
        ? "Впишите суммы по месяцам — ИТОГО посчитается само"
        : "Сумма за год: разложится по выбранному правилу";
      input.value = row.plan_year ? U.fmt(row.plan_year) : "";
    }

    function apply() {
      state.spread = spread.value;
      if (spread.value === "none") return;          // месяцы заполняют руками
      var amount = U.parseSum(input.value);
      if (amount < 0) { U.toast("Сумма не может быть отрицательной", "error"); return; }
      if (!amount && !row.plan_year) return;
      var months = spreadMonths(amount, spread.value);
      td.classList.add("saving");
      API.patchRow(row.id, { months: months }).then(function (result) {
        td.classList.remove("saving");
        applied(row, result.row, "months", { months: months });
        input.value = row.plan_year ? U.fmt(row.plan_year) : "";
        paintMonths(row);
        afterSave(row);
      }).catch(function (e) {
        td.classList.remove("saving");
        U.toast(e.message, "error");
      });
    }
    input.addEventListener("change", apply);
    spread.addEventListener("change", function () {
      state.spread = spread.value;
      syncMode();
      if (spread.value !== "none" && U.parseSum(input.value)) apply();
    });

    td.appendChild(input);
    td.appendChild(spread);
    syncMode();
    return td;
  }

  /* Месяцы строки перерисовываем на месте: раскладка суммы меняет двенадцать
     ячеек сразу, а полная перерисовка таблицы выбила бы фокус из строки. */
  function paintMonths(row) {
    for (var i = 0; i < 12; i++) {
      var td = document.querySelector(
        '***REMOVED***t-op td[data-id="' + row.id + '"][data-f="m' + i + '"]');
      if (td) paint(td, row, "m" + i);
    }
  }

  /* Куда положить новую строку. Список тот же, что и заголовки блоков плана:
     ЦФО плюс бюджет, потому что у ИТ-дирекции бюджетов два. */
  function addTargets() {
    var sec = state.sections[state.data.plan_year_no];
    if (!sec || !sectionEditable(sec)) return [];
    var targets = blocksOf(sec, true);
    var chosen = state.filters && state.filters.cfo_name
      ? state.filters.cfo_name.selected() : [];
    if (chosen.length) {
      // фильтр сузил таблицу до одной дирекции — не спрашиваем лишний раз
      targets = targets.filter(function (b) { return chosen.indexOf(b.cfo_name) >= 0; });
    }
    return targets;
  }

  /* Выбор дирекции для новой строки. У руководителя вариант один и списка
     не будет; финотделу список нужен — по заголовку таблицы не угадать. */
  function addMenu(button, targets) {
    U.closePopups();
    var stale = document.getElementById("op-add-menu");
    if (stale) stale.parentNode.removeChild(stale);   // иначе меню копятся в body
    var list = U.el("div", { class: "flist" });
    var pop = U.el("div", { class: "fpop fpop-fixed", id: "op-add-menu" });
    var search = null;
    if (targets.length > 8) {
      search = U.el("input", { class: "fsearch" });
      search.placeholder = "поиск дирекции";
      pop.appendChild(search);
    }
    pop.appendChild(list);

    function draw() {
      var needle = (search && search.value || "").toLowerCase();
      U.clear(list);
      targets.forEach(function (block) {
        var label = block.cfo_name + (block.budget_name === "Основной бюджет"
          ? "" : " · " + block.budget_name);
        if (needle && label.toLowerCase().indexOf(needle) < 0) return;
        list.appendChild(U.el("div", { class: "fopt copt" + (block.placeholder ? " dim" : ""),
          text: label,
          on: { mousedown: function (event) {
            event.preventDefault();
            pop.parentNode.removeChild(pop);
            addRow(block, state.data.plan_year_no, button);
          } } }));
      });
      if (!list.childNodes.length) {
        list.appendChild(U.el("div", { class: "dim fempty", text: "ничего не найдено" }));
      }
    }

    if (search) search.oninput = draw;
    pop.onclick = function (event) { event.stopPropagation(); };
    document.body.appendChild(pop);
    var r = button.getBoundingClientRect();
    pop.style.width = "320px";
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 332)) + "px";
    pop.style.top = (r.bottom + 4) + "px";
    list.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 60) + "px";
    draw();
    if (search) search.focus();
  }

  function addRowFromHeader() {
    var button = document.getElementById("op-add-row");
    if (!state.editMode) setEditMode(true);   // заполнять строку без правки нечем
    var targets = addTargets();
    if (!targets.length) {
      U.toast("Некуда добавить строку: нет доступных дирекций", "error");
      return;
    }
    if (targets.length === 1) {
      addRow(targets[0], state.data.plan_year_no, button);
      return;
    }
    addMenu(button, targets);
  }

  /* Строка заводится сразу, пустой, и заполняется прямо в таблице.
     ЦФО и бюджет берутся из выбранного блока. */
  function addRow(block, year, button) {
    button.disabled = true;
    API.createOperplanRow({
      cfo_id: block.cfo_id,
      budget_name: block.budget_name,
      article: "", counterparty: "", contract: "", detail: "", comment: "",
      plan_year: 0, months: null
    }, year).then(function (result) {
      var id = result.id || (result.row && result.row.id);
      state.fresh[id] = true;
      state.collapsed[block.budget_id] = false;
      return load(year).then(function () {
        var tr = document.querySelector('***REMOVED***t-op tr[data-id="' + id + '"]');
        if (!tr) return;
        tr.scrollIntoView({ block: "center" });
        var first = tr.querySelector("input");
        if (first) first.focus();
      });
    }).catch(function (e) { U.toast(e.message, "error"); })
      .then(function () { button.disabled = false; });
  }

  function groupNode(block, shown, sum) {
    var collapsed = !!state.collapsed[block.budget_id];
    var td = U.el("td", { colspan: COLS }, [
      U.el("span", { class: "grp-caret", text: collapsed ? "▸" : "▾" }),
      U.el("b", { text: block.cfo_name }),
      U.el("span", { class: "dim", text: " · " + block.budget_name }),
      U.el("span", { class: "grp-sum", text: block.placeholder
        ? "строк нет" : U.fmt(sum) + " ₽ · " + shown + " строк" })
    ]);
    var tr = U.el("tr", { class: "group" + (block.placeholder ? " is-empty" : "") }, [td]);
    tr.onclick = function () {
      state.collapsed[block.budget_id] = !collapsed;
      render();
    };
    return tr;
  }

  /* Дирекции без единой строки тоже показываем заголовком: иначе в пустом году
     планировать было бы не с чего — блоков нет, значит нет и кнопки «+ расход». */
  function blocksOf(sec, editable) {
    var blocks = sec.blocks.slice();
    if (!editable || sec.year !== state.data.plan_year_no) return blocks;
    var have = {};
    blocks.forEach(function (b) { have[b.cfo_id] = true; });
    (state.cfoList || []).forEach(function (cfo) {
      if (have[cfo.id]) return;
      blocks.push({ budget_id: "new-" + cfo.id, cfo_id: cfo.id, cfo_name: cfo.name,
        budget_name: "Основной бюджет", rows: [], rows_count: 0,
        plan_year: 0, months: [], placeholder: true });
    });
    return blocks.sort(function (a, b) {
      return byText(a.cfo_name, b.cfo_name) || byText(a.budget_name, b.budget_name);
    });
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
    /* Перерисовка выбрасывает ячейки вместе с их списками: открытый список
       иначе остался бы висеть над таблицей, привязанный к мёртвому полю. */
    U.closePopups();
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
      /* Заголовки пустых дирекций показываем по праву правки: они говорят, где
         можно планировать. Ячейки открываем только по карандашу. */
      var canEdit = sectionEditable(sec);
      var editable = sectionEditing(sec);
      var yearRows = [];
      var nodes = [];
      blocksOf(sec, canEdit).forEach(function (block) {
        /* Позицию считаем по всему блоку, а не по отфильтрованному остатку:
           иначе номера менялись бы от каждого фильтра. */
        var position = {};
        sortRows(block.rows).forEach(function (row, index) {
          position[row.id] = index + 1;
        });
        var rows = sortRows(block.rows.filter(function (row) {
          return passes(row, block.cfo_name);
        }));
        // заголовок пустой дирекции держим ради кнопки «+ расход», но не под фильтром
        if (!rows.length && !(block.placeholder && !filtering())) return;
        var sum = rows.reduce(function (acc, row) { return acc + row.plan_year; }, 0);
        nodes.push(groupNode(block, rows.length, sum));
        rows.forEach(function (row) {
          state.rows[row.id] = row;
          state.rowYear[row.id] = year;
          yearRows.push(row);
        });
        if (state.collapsed[block.budget_id]) return;
        rows.forEach(function (row) {
          var node = rowNode(row, block.cfo_name, editable, position[row.id]);
          if (year !== state.data.plan_year_no) node.classList.add("y-past");
          nodes.push(node);
          /* В режиме правки расходы прячем: они не редактируются и мешают
             попадать по ячейкам — так же сделано в карточке ЦФО. */
          if (editable || !state.spendOpen[row.id]) return;
          (row.spends || []).forEach(function (spend) {
            nodes.push(spendNode(spend, position[row.id]));
          });
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
          ? "Пока нет строк за " + ctx.years.join(" и ") + ". Нажмите «⟳ Бюджет "
            + "прошлого года» или заведите строку кнопкой «+ расход» у нужной дирекции."
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
    ["article", "classifier", "counterparty", "contract", "detail", "comment"]
      .forEach(function (key) {
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
    if (totalCell) {
      /* У новой строки в этой колонке поле ввода: правка месяцев должна
         подтянуть в него пересчитанное ИТОГО, но не затирать то, что человек
         как раз набирает. */
      var field = totalCell.querySelector(".sum-in");
      if (!field) {
        totalCell.textContent = U.fmt(row.plan_year);
      } else if (document.activeElement !== field) {
        field.value = row.plan_year ? U.fmt(row.plan_year) : "";
      }
    }
    repaintTotal(state.rowYear[row.id]);
    refreshFilterOptions();
  }

  /* ---------- замок ---------- */

  /* Правка включена по умолчанию; кнопка с перечёркнутым карандашом её закрывает.
     Замок общий на год: финотдел закрывает правку и себе, чтобы случайно не задеть
     утверждённый план, и тем же нажатием открывает обратно. */
  /* Карандаш включает правку по ячейкам, «Сохранить» её выключает. Так таблица
     по умолчанию читается как отчёт, а не как форма: раньше любой клик по ячейке
     начинал правку, и задеть чужую цифру было легко. */
  function renderEditMode() {
    var can = sectionEditable(state.data);
    if (!can) state.editMode = false;
    var pencil = document.getElementById("op-edit-mode");
    var save = document.getElementById("op-save");
    pencil.hidden = !can;
    pencil.textContent = state.editMode ? "✎̸" : "✎";
    pencil.classList.toggle("locked", state.editMode);
    pencil.setAttribute("aria-pressed", state.editMode ? "true" : "false");
    pencil.title = state.editMode
      ? "Правка включена. Нажмите, чтобы закрыть ячейки от случайных изменений."
      : "Разрешить правку ячеек";
    save.hidden = !state.editMode;
  }

  function setEditMode(on) {
    state.editMode = !!on;
    renderLock();
    render();
  }

  /* «Сохранить» дописывает начатую ячейку, закрепляет нумерацию и выключает
     правку. Каждая ячейка уходит на сервер, как только её покидают, поэтому
     кнопке остаётся снять фокус — это и есть сохранение начатого, — проставить
     номера строк по порядку таблицы и перечитать год. */
  function saveAndClose() {
    var active = document.activeElement;
    if (active && active.blur) active.blur();
    U.closePopups();
    var button = document.getElementById("op-save");
    button.disabled = true;
    window.setTimeout(function () {
      state.editMode = false;
      API.operplanRenumber(state.data.plan_year_no)
        .catch(function (e) { U.toast("Нумерация: " + e.message, "error"); })
        .then(function () {
          return reloadAll().then(function () {
            button.disabled = false;
            U.toast("Изменения сохранены");
          });
        });
    }, 60);
  }

  function renderLock() {
    var locked = !!state.data.locked;
    var editable = sectionEditable(state.data);
    state.editing = sectionEditing(state.data);

    /* Два разных запрета, поэтому и две кнопки. Замок в шапке вкладки —
       общий на год и на всех, его ставит финотдел: утверждённый план правке
       не подлежит. Карандаш в шапке таблицы — личный и на сессию: защита
       от случайного клика по ячейке. */
    var button = document.getElementById("op-lock");
    button.hidden = !state.data.is_fin;
    button.textContent = locked ? "🔒" : "🔓";
    button.classList.toggle("locked", locked);
    button.setAttribute("aria-pressed", locked ? "true" : "false");
    button.title = locked
      ? "План " + state.data.plan_year_no + " закрыт для всех. Нажмите, чтобы открыть."
      : "План " + state.data.plan_year_no
        + " открыт. Нажмите, чтобы закрыть правку для всех.";
    var note = document.getElementById("op-lock-note");
    note.textContent = locked ? "план закрыт" : "";
    note.hidden = !state.data.is_fin || !locked;

    /* Плашки-инструкции под шапкой нет: правила правки живут в «ℹ Инфо»,
       а состояние видно по карандашу и по кнопке «Сохранить». */
    document.getElementById("op-locked-note").hidden = !locked;

    /* Переносы прошлого года переехали в шапку карточки строк; под замком
       гасим их, а кнопку «+ расход» в заголовках блоков render просто не рисует. */
    ["op-copy-run", "op-fact-run", "op-add-row"].forEach(function (id) {
      document.getElementById(id).disabled = !editable;
    });
    document.getElementById("op-index-wrap").hidden = !editable;
    document.getElementById("op-copy-run").title = "Повторить бюджет "
      + state.data.base_year_no + " года в плане " + state.data.plan_year_no;
    document.getElementById("op-fact-run").title = "Перенести в план "
      + state.data.plan_year_no + " суммы факта " + state.data.base_year_no + " года";
    /* Загрузка доступна всем, кто вправе править: круг ЦФО режет сервер, чужие
       строки файла он пропускает. Под замком грузить нечего — кнопку убираем,
       иначе она отвечала бы 403. Выгрузка и шаблон не зависят от замка. */
    document.getElementById("op-import").hidden = !editable;
    if (!editable) document.getElementById("op-import-form").hidden = true;

    /* Факт заливает только финансовый отдел: у руководителя ЦФО выбора «факт
       года» в форме нет вовсе, остаётся один бюджет. Сервер отвечает на такую
       загрузку 403 — здесь мы лишь не предлагаем того, чего нельзя. */
    var fin = !!state.data.is_fin;
    ["op-imp-fact", "op-imp-fact-note"].forEach(function (id) {
      document.getElementById(id).hidden = !fin;
    });
    if (!fin) {
      document.querySelector('input[name="op-imp-kind"][value="plan"]').checked = true;
    }
    renderImportCfo();

    /* Выгрузка факта — за базовый год, он же стоит в подписи кнопки. */
    var factBtn = document.getElementById("op-export-fact");
    factBtn.textContent = "⭳ Выгрузить факт " + state.data.base_year_no;
    factBtn.title = "Факт " + state.data.base_year_no
      + " года листом «Бюджеты ЦФО» — тем же, каким выгружается бюджет";
    renderEditMode();
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
    if (state.data && state.data.kpi) renderSummary();

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

  /* Все три файла — через API.download, а не переходом по ссылке: роль
     передаётся заголовком X-User, которого в обычной навигации нет, и
     руководителю приезжал бы файл со всеми дирекциями. */
  function runExport() {
    API.download("budget", null, { year: state.data.plan_year_no })
      .catch(function (e) { U.toast(e.message, "error"); });
  }

  /* Факт выгружается за базовый год и той же раскладкой, что и бюджет: год
     планирования фактом не наполняется. Выгружать факт вправе каждый,
     загружать — только финотдел; круг ЦФО и там, и там режет сервер. */
  function runFactExport() {
    API.download("budget-fact", null, { year: state.data.base_year_no })
      .catch(function (e) { U.toast(e.message, "error"); });
  }

  /* Шаблон — тот же лист «Бюджеты ЦФО», но пустой: блоки своих ЦФО и подсказка.
     Заполненный файл принимается кнопкой «Загрузить из Excel». */
  function runTemplate() {
    API.download("budget-template", null, { year: state.data.plan_year_no })
      .catch(function (e) { U.toast(e.message, "error"); });
  }

  /* Выбор дирекций галочками. Файлы приходят по одному на дирекцию, и явная
     отметка защищает от промаха: что не отмечено, то и не тронется — строки
     чужих ЦФО в файлах будут пропущены, а их факт останется как был.
     Ни одной галочки — прежнее поведение: круг берётся из самих файлов. */
  function importCfoList() {
    var seen = {};
    var out = [];
    (state.cfoList || []).forEach(function (c) {
      if (seen[c.id]) return;
      seen[c.id] = true;
      out.push({ id: c.id, name: c.name });
    });
    return out;
  }

  function checkedCfo() {
    return Array.prototype.filter
      .call(document.querySelectorAll("***REMOVED***op-import-cfo input[type=checkbox]"),
        function (box) { return box.checked; })
      .map(function (box) { return Number(box.value); });
  }

  function renderImportCfoHint() {
    var n = checkedCfo().length;
    document.getElementById("op-cfo-hint").textContent = n
      ? " — отмечено " + n + ", остальное в файлах будет пропущено"
      : " — ни одной: круг возьмётся из файлов";
  }

  function renderImportCfo() {
    var kind = document.querySelector('input[name="op-imp-kind"]:checked');
    var isFact = !!kind && kind.value === "fact";
    document.getElementById("op-import-cfo-wrap").hidden = !isFact;
    if (!isFact) return;

    var host = document.getElementById("op-import-cfo");
    var was = {};
    checkedCfo().forEach(function (id) { was[id] = true; });
    U.clear(host);
    importCfoList().forEach(function (c) {
      var box = U.el("input", { type: "checkbox", value: String(c.id) });
      box.checked = !!was[c.id];
      box.onchange = function () {
        // прежний предпросмотр относился к другому кругу — убираем
        document.getElementById("op-import-preview").hidden = true;
        renderImportCfoHint();
      };
      host.appendChild(U.el("label", {}, [box, U.el("span", { text: c.name })]));
    });
    renderImportCfoHint();
  }

  function setAllCfo(value) {
    Array.prototype.forEach.call(
      document.querySelectorAll("***REMOVED***op-import-cfo input[type=checkbox]"),
      function (box) { box.checked = value; });
    document.getElementById("op-import-preview").hidden = true;
    renderImportCfoHint();
  }

  /* Что выбрано в форме: вид загрузки, дирекция и год. Год у факта всегда
     базовый — фактом наполняется прошлый год, а не планируемый. */
  function importParams() {
    var kind = "plan";
    Array.prototype.forEach.call(
      document.querySelectorAll('input[name="op-imp-kind"]'), function (radio) {
        if (radio.checked) kind = radio.value;
      });
    return {
      kind: kind,
      cfoIds: kind === "fact" ? checkedCfo() : [],
      year: kind === "fact" ? state.data.base_year_no : state.data.plan_year_no
    };
  }

  function importFiles(note) {
    var input = document.getElementById("op-import-file");
    if (input.files && input.files.length) {
      return Array.prototype.slice.call(input.files);
    }
    note.style.color = "var(--critical)";
    note.textContent = "Выберите файл .xlsx";
    return null;
  }

  function money(value) { return U.fmt(value) + " ₽"; }

  /* Предпросмотр: сколько строк сойдётся, сколько факта ляжет мимо плана и что
     станет с прежним фактом. Нужен потому, что загрузка заменяет факт дирекции
     целиком, и промах виден только числами — файл дирекции внешне правдоподобен
     в любом случае. */
  function previewTable(lines) {
    var table = U.el("table", { class: "mini-table" });
    lines.forEach(function (line) {
      table.appendChild(U.el("tr", {}, [
        U.el("td", { class: "dim", text: line[0] }),
        U.el("td", { class: line[2] === "crit" ? "err" : (line[2] === "warn" ? "warn" : ""),
          text: line[1] })
      ]));
    });
    return table;
  }

  function renderPreview(p) {
    var host = document.getElementById("op-import-preview");
    U.clear(host);
    host.hidden = false;

    // по каждому файлу отдельно: какие дирекции в нём и сколько ляжет
    var byFile = [];
    (p.files || []).forEach(function (f) {
      if (f.error) { byFile.push([f.filename, f.error, "crit"]); return; }
      var what = (f.cfo && f.cfo.length ? f.cfo.join(", ") : "дирекции не распознаны");
      byFile.push([f.filename,
        what + " · " + f.matched + " строк на " + money(f.total) +
        (f.unlinked ? " · без пары " + f.unlinked : "") +
        (f.out_of_budget ? " · вне бюджета " + f.out_of_budget : ""),
        (f.cfo && f.cfo.length) ? "" : "crit"]);
    });
    if (byFile.length) {
      host.appendChild(U.el("div", { class: "sub", text: "Файлы" }));
      host.appendChild(previewTable(byFile));
    }

    /* По каждой дирекции отдельно: её факт заменится целиком, а файл одной
       дирекции может лежать внутри файла другой — бюджеты стратегии и
       аналитики приходят в файле ИТ. Без даты прежней загрузки не видно,
       что старый файл затирает более свежую отдельную. */
    var lines = [];
    if (!p.cfo.length) lines.push(["Дирекции", "не распознаны", "crit"]);
    p.cfo.forEach(function (c) {
      var was = c.before
        ? "сейчас " + money(c.before) + ", заменится целиком"
        : "факта ещё нет";
      if (c.last_file) was += " · залит " + c.last_at + " из «" + c.last_file + "»";
      lines.push([c.name, was, c.before ? "warn" : ""]);
    });
    if (lines.length) {
      host.appendChild(U.el("div", { class: "sub", style: "margin-top:8px",
        text: "Дирекции, чей факт заменится" }));
      host.appendChild(previewTable(lines));
    }

    var totals = [["Ляжет на строки плана", p.matched + " · " + money(p.total), ""]];
    if (p.unlinked) {
      totals.push(["Без строки плана",
        p.unlinked + " · " + money(p.unlinked_total) +
        " — попадёт в «вне бюджета», план не изменится", "warn"]);
    }
    if (p.out_of_budget) {
      totals.push(["Вне бюджета по файлам",
        p.out_of_budget + " · " + money(p.out_of_budget_total), "warn"]);
    }
    if (p.foreign) {
      totals.push(["Пропущено строк чужих дирекций", String(p.foreign), ""]);
    }
    if (p.unknown_cfo && p.unknown_cfo.length) {
      totals.push(["ЦФО нет в справочнике", p.unknown_cfo.join(", "), "crit"]);
    }
    if (p.errors_count) {
      totals.push(["Строк с ошибкой", p.errors_count + ": " +
        (p.errors || []).slice(0, 3).map(function (e) {
          return (e.filename ? e.filename + ", " : "") +
            (e.excel_row ? "строка " + e.excel_row + " — " : "") + (e.problem || "");
        }).join("; "), "crit"]);
    }
    host.appendChild(U.el("div", { class: "sub", style: "margin-top:8px", text: "Итого" }));
    host.appendChild(previewTable(totals));
  }

  function runPreview() {
    var note = document.getElementById("op-import-note");
    var files = importFiles(note);
    if (!files) return;
    var p = importParams();
    if (p.kind !== "fact") {
      note.style.color = "var(--critical)";
      note.textContent = "Проверка есть только у загрузки факта";
      return;
    }
    note.style.color = "";
    note.textContent = "Проверяю " + files.length + " файл(ов)…";
    API.previewImport(files, p.year, p.kind, p.cfoIds)
      .then(function (result) { note.textContent = ""; renderPreview(result); })
      .catch(function (e) {
        document.getElementById("op-import-preview").hidden = true;
        note.style.color = "var(--critical)";
        note.textContent = e.message;
      });
  }

  function runImport() {
    var note = document.getElementById("op-import-note");
    var files = importFiles(note);
    if (!files) return;
    var p = importParams();
    if (p.kind === "plan" && files.length > 1) {
      note.style.color = "var(--critical)";
      note.textContent = "Бюджет загружается по одному файлу";
      return;
    }
    note.style.color = "";
    note.textContent = "Загружаю " + files.length + " файл(ов)…";
    API.importBudget(files, p.year, p.kind, p.cfoIds)
      .then(function (result) {
        note.textContent = "";
        document.getElementById("op-import-file").value = "";
        document.getElementById("op-import-preview").hidden = true;
        document.getElementById("op-import-form").hidden = true;
        var failed = (result.failed || []).length;
        U.toast("Загружено строк: " + result.rows +
          (result.files ? " из " + result.files.length + " файлов" : "") +
          (result.unmatched ? ", без строки плана: " + result.unmatched : "") +
          (result.out_of_budget ? ", вне бюджета: " + result.out_of_budget : "") +
          (result.removed ? ", заменено прежних: " + result.removed : "") +
          (result.foreign ? ", пропущено чужих ЦФО: " + result.foreign : ""),
          failed ? "error" : undefined);
        if (failed) {
          // упавший файл называем поимённо: остальные уже залиты
          U.toast("Не загрузились: " + result.failed.map(function (f) {
            return f.filename + " — " + f.error;
          }).join("; "), "error");
        }
        reloadAll();
      })
      .catch(function (e) { note.style.color = "var(--critical)"; note.textContent = e.message; });
  }

  /* ---------- справочники для списков в ячейках ---------- */

  function cfoRefs(cfoId) {
    var all = state.refs && state.refs.all ? state.refs.all
      : { articles: [], counterparties: [], contracts: [] };
    var own = state.refs && state.refs.by_cfo ? state.refs.by_cfo[String(cfoId)] : null;
    return { own: own || { articles: [], counterparties: [], contracts: {}, details: [] },
             all: all };
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
      document.getElementById("op-all-wrap").hidden = !data.is_fin;
      if (!data.is_fin) all.checked = false;

      initFilters();
      renderLock();
      render();
    });
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
          render();                     // списки в ячейках новых строк берут их отсюда
        })
      ]);
    }).catch(function (e) { U.toast("Бюджет: " + e.message, "error"); });
  }

  window.Operplan = {
    setCfoList: function (list) { state.cfoList = list; },
    load: reloadAll,
    init: function () {
      bindSuggest(document.getElementById("t-op"));
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
      document.getElementById("op-add-row").onclick = addRowFromHeader;
      document.getElementById("op-edit-mode").onclick = function () {
        setEditMode(!state.editMode);
      };
      document.getElementById("op-save").onclick = saveAndClose;
      document.getElementById("op-copy-run").onclick = function () { runCopy("plan"); };
      document.getElementById("op-fact-run").onclick = function () { runCopy("fact"); };
      document.getElementById("op-export").onclick = runExport;
      document.getElementById("op-export-fact").onclick = runFactExport;
      document.getElementById("op-template").onclick = runTemplate;
      document.getElementById("op-import").onclick = function () {
        var form = document.getElementById("op-import-form");
        form.hidden = !form.hidden;
      };
      document.getElementById("op-import-run").onclick = runImport;
      document.getElementById("op-import-check").onclick = runPreview;
      document.getElementById("op-import-cancel").onclick = function () {
        document.getElementById("op-import-form").hidden = true;
        document.getElementById("op-import-preview").hidden = true;
      };
      /* Смена вида загрузки убирает устаревший предпросмотр: он относился
         к прежнему выбору и ввёл бы в заблуждение. */
      Array.prototype.forEach.call(
        document.querySelectorAll('input[name="op-imp-kind"]'), function (radio) {
          radio.onchange = function () {
            document.getElementById("op-import-preview").hidden = true;
            renderImportCfo();
          };
        });
      document.getElementById("op-cfo-all").onclick = function (e) {
        e.preventDefault(); setAllCfo(true);
      };
      document.getElementById("op-cfo-none").onclick = function (e) {
        e.preventDefault(); setAllCfo(false);
      };
      document.getElementById("op-import-file").onchange = function () {
        document.getElementById("op-import-preview").hidden = true;
      };
      /* Галочка меняет наполнение списков в ячейках — перерисовываем таблицу. */
      document.getElementById("op-a-all").onchange = render;
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
