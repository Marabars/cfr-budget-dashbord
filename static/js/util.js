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
    kpi: kpi, empty: empty, clear: clear, chips: chips, fillSelect: fillSelect, toast: toast
  };
})();