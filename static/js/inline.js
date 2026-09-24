/* Правка таблицы прямо в ячейках: общая механика для Оперплана и карточки ЦФО.

   Ячейка помечается data-id (строка) и data-f (поле). В режиме правки она
   становится contenteditable: Enter сохраняет, Esc возвращает прежнее значение.
   Что именно уходит на сервер, решает вызывающий модуль — здесь только
   фокус, клавиши, показ сохранения и откат при ошибке. */
(function () {
  "use strict";

  /* Ячейка таблицы, которую можно править. */
  function cell(rowId, field, text, cls, editing) {
    var td = U.el("td", { class: cls || "", text: text });
    td.setAttribute("data-f", field);
    td.setAttribute("data-id", rowId);
    if (editing) td.setAttribute("contenteditable", "true");
    return td;
  }

  /* ctx: { row(id), payload(field, text, row), applied(row, saved, field, payload),
            paint(td, row, field), after() } */
  function bind(table, ctx) {
    function commit(td) {
      var id = Number(td.getAttribute("data-id"));
      var field = td.getAttribute("data-f");
      var row = ctx.row(id);
      if (!row) return;

      var text = td.textContent.replace(/^\s+|\s+$/g, "");
      var request;
      try {
        request = ctx.payload(field, text, row);
      } catch (e) {
        U.toast(e.message, "error");
        ctx.paint(td, row, field);
        return;
      }
      if (!request) return;                   // значение не изменилось

      td.classList.add("saving");
      API.patchRow(id, request).then(function (result) {
        td.classList.remove("saving");
        ctx.applied(row, result.row, field, request);
        ctx.paint(td, row, field);
        if (ctx.after) ctx.after(row);
      }).catch(function (e) {
        td.classList.remove("saving");
        U.toast(e.message, "error");
        ctx.paint(td, row, field);
      });
    }

    table.addEventListener("focusout", function (event) {
      var td = event.target;
      if (td.tagName === "TD" && td.hasAttribute("contenteditable")) commit(td);
    });

    table.addEventListener("keydown", function (event) {
      var td = event.target;
      if (td.tagName !== "TD" || !td.hasAttribute("contenteditable")) return;
      if (event.key === "Enter") {
        event.preventDefault();
        td.blur();
      } else if (event.key === "Escape") {
        var row = ctx.row(Number(td.getAttribute("data-id")));
        if (row) ctx.paint(td, row, td.getAttribute("data-f"));
        td.blur();
      }
    });
  }

  window.Inline = { cell: cell, bind: bind };
})();
