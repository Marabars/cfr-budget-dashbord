/* Общие утилиты: DOM, форматирование, элементы интерфейса. */
(function () {
  "use strict";

  var MONTHS_FULL = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
  var MONTHS_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"];

  function el(tag, attrs, kids) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key === "html") node.innerHTML = value;
        else if (key === "on") Object.keys(value).forEach(function (ev) { node.addEventListener(ev, value[ev]); });
        else if (key === "style") node.setAttribute("style", value);
        else node.setAttribute(key, value);
      });
    }
    (kids || []).forEach(function (kid) {
      if (kid === null || kid === undefined || kid === false) return;
      node.appendChild(typeof kid === "string" ? document.createTextNode(kid) : kid);
    });
    return node;
  }

  function fmt(value) {
    var n = Math.round(Number(value) || 0);
    var sign = n < 0 ? "−" : "";
    return sign + String(Math.abs(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  }

  function fmtShort(value) {
    var v = Number(value) || 0;
    var abs = Math.abs(v);
    if (abs >= 1e9) return (v / 1e9).toFixed(2).replace(".", ",") + " млрд";
    if (abs >= 1e6) return (v / 1e6).toFixed(1).replace(".", ",") + " млн";
    if (abs >= 1e3) return fmt(Math.round(v / 1e3)) + " тыс";
    return fmt(v);
  }

  function parseSum(text) {
    var cleaned = String(text || "").replace(/[^\d.,-]/g, "").replace(",", ".");
    return parseFloat(cleaned) || 0;
  }

  function td(text, cls) { return el("td", { class: cls || "", text: text }); }
  function tdn(value, cls) { return el("td", { class: "num " + (cls || ""), text: fmt(value) }); }
  function th(html, cls) { return el("th", { class: cls || "", html: html }); }

  function badge(kind, text) {
    return el("span", { class: "badge " + kind }, [el("span", { class: "dot" }), text]);
  }

  /* Полоса освоения с засечкой ожидаемого темпа. */
  function meter(pct, pace, status) {
    var fill = el("div", { class: "fill" + (status && status !== "good" ? " s-" + status : "") });
    fill.style.width = Math.min(100, pct * 100) + "%";
    var mark = el("div", { class: "pace" });
    mark.style.left = (pace * 100) + "%";
    var track = el("div", { class: "track" }, [fill, mark]);
    track.title = "Освоено " + (pct * 100).toFixed(1) + "% · ожидаемый темп " + (pace * 100).toFixed(0) + "%";
    return el("div", { class: "meter" }, [track,
      el("span", { class: "pct", text: Math.round(pct * 100) + "%" })]);
  }

  /* Батарейка освоения для карточек дашборда. */
  function battery(pct, pace) {
    var body = el("div", { class: "batt-body" });
    for (var i = 0; i < 10; i++) {
      body.appendChild(el("div", { class: "batt-seg" + (pct * 100 >= (i + 1) * 10 - 5 ? " on" : "") }));
    }
    var mark = el("div", { class: "batt-pace" });
    mark.style.left = "calc(" + (pace * 100) + "% - 1px)";
    mark.title = "Ожидаемый темп освоения: " + (pace * 100).toFixed(0) + "%";
    body.appendChild(mark);
    return el("div", { class: "batt" }, [
      el("div", { class: "batt-shell" }, [body, el("div", { class: "batt-cap" })]),
      el("span", { class: "batt-pct", text: Math.round(pct * 100) + "%" })
    ]);
  }

  function kpi(host, items) {
    host.innerHTML = "";
    items.forEach(function (item) {
      host.appendChild(el("div", { class: "kpi " + (item.tone || "") }, [
        el("div", { class: "lbl", text: item.label }),
        el("div", { class: "val" + (item.hero ? " hero" : ""), text: item.value }),
        el("div", { class: "sub " + (item.subClass || ""), text: item.sub || "" })
      ]));
    });
  }

  function empty(colspan, text) {
    return el("tr", {}, [el("td", { colspan: colspan, class: "dim wrap", text: text })]);
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  /* Переключатель группы «чипов»: возвращает выбранное значение. */
  function chips(container, attr, onChange) {
    var buttons = container.querySelectorAll(".chip");
    Array.prototype.forEach.call(buttons, function (chip) {
      chip.onclick = function () {
        Array.prototype.forEach.call(buttons, function (other) {
          other.setAttribute("aria-pressed", "false");
        });
        chip.setAttribute("aria-pressed", "true");
        onChange(chip.getAttribute(attr));
      };
    });
  }

  function fillSelect(select, items, valueKey, textKey, selected) {
    select.innerHTML = "";
    items.forEach(function (item) {
      var value = typeof item === "object" ? item[valueKey] : item;
      var text = typeof item === "object" ? item[textKey] : item;
      select.appendChild(el("option", { value: value, text: text }));
    });
    if (selected !== undefined && selected !== null) select.value = String(selected);
  }

  /* Фильтр колонки: кнопка со счётчиком, поиск и список значений с галочками.
     Пустой выбор = «не фильтруем», так значения, пришедшие позже, не отсекаются. */
  function multiFilter(label, onChange) {
    var chosen = {};
    var options = [];
    var count = el("span", { class: "fcount", hidden: "hidden" });
    var button = el("button", { class: "fbtn", type: "button" },
      [el("span", { text: label }), count, el("span", { class: "fcaret", text: "▾" })]);
    var search = el("input", { class: "fsearch", type: "search", placeholder: "Поиск…" });
    var list = el("div", { class: "flist" });
    var pop = el("div", { class: "fpop", hidden: "hidden" }, [
      search,
      el("div", { class: "frow" }, [
        el("button", { class: "flink", type: "button", text: "Выбрать все",
          on: { click: function () { setAll(true); } } }),
        el("button", { class: "flink", type: "button", text: "Очистить",
          on: { click: function () { setAll(false); } } })
      ]),
      list
    ]);
    var node = el("div", { class: "fwrap" }, [button, pop]);

    function selected() { return Object.keys(chosen); }

    function sync() {
      var n = selected().length;
      count.hidden = n === 0;
      count.textContent = n;
      button.setAttribute("aria-pressed", n ? "true" : "false");
    }

    function setAll(on) {
      var query = search.value.toLowerCase();
      options.forEach(function (value) {
        if (query && value.toLowerCase().indexOf(query) < 0) return;
        if (on) chosen[value] = true; else delete chosen[value];
      });
      draw();
      sync();
      onChange(selected());
    }

    function draw() {
      var query = search.value.toLowerCase();
      clear(list);
      var shown = 0;
      options.forEach(function (value) {
        if (query && value.toLowerCase().indexOf(query) < 0) return;
        if (shown >= 300) return;                   // длинные списки режем, поиск сузит
        shown++;
        var box = el("input", { type: "checkbox" });
        box.checked = !!chosen[value];
        box.onchange = function () {
          if (box.checked) chosen[value] = true; else delete chosen[value];
          sync();
          onChange(selected());
        };
        list.appendChild(el("label", { class: "fopt" }, [box,
          el("span", { text: value === "" ? "— не заполнено —" : value })]));
      });
      if (!shown) list.appendChild(el("div", { class: "dim fempty", text: "ничего не найдено" }));
      else if (options.length > shown) {
        list.appendChild(el("div", { class: "dim fempty",
          text: "показано " + shown + " из " + options.length + " — уточните поиск" }));
      }
    }

    search.oninput = draw;
    button.onclick = function (event) {
      event.stopPropagation();
      var opening = pop.hidden;
      closeAllFilters();
      pop.hidden = !opening;
      if (opening) { draw(); search.focus(); }
    };
    pop.onclick = function (event) { event.stopPropagation(); };

    return {
      node: node,
      selected: selected,
      setOptions: function (values) {
        options = values.slice().sort(function (a, b) { return a.localeCompare(b, "ru"); });
        // выбранное значение, пропавшее из данных, снимаем — иначе фильтр «залипнет»
        Object.keys(chosen).forEach(function (v) {
          if (options.indexOf(v) < 0) delete chosen[v];
        });
        sync();
        if (!pop.hidden) draw();
      },
      clear: function () { chosen = {}; sync(); if (!pop.hidden) draw(); },
      close: function () { pop.hidden = true; }
    };
  }

  function closeAllFilters() {
    Array.prototype.forEach.call(document.querySelectorAll(".fpop"), function (pop) {
      pop.hidden = true;
    });
  }

  document.addEventListener("click", closeAllFilters);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeAllFilters();
  });

  function toast(message, kind) {
    var node = document.getElementById("note");
    node.hidden = false;
    node.className = "note" + (kind === "error" ? " note-error" : "");
    node.textContent = message;
    if (kind !== "error") {
      window.clearTimeout(toast._timer);
      toast._timer = window.setTimeout(function () { node.hidden = true; }, 6000);
    }
  }

  window.U = {
    MONTHS_FULL: MONTHS_FULL, MONTHS_SHORT: MONTHS_SHORT,
    el: el, fmt: fmt, fmtShort: fmtShort, parseSum: parseSum,
    td: td, tdn: tdn, th: th, badge: badge, meter: meter, battery: battery,
    kpi: kpi, empty: empty, clear: clear, chips: chips, fillSelect: fillSelect, toast: toast,
    multiFilter: multiFilter
  };
})();