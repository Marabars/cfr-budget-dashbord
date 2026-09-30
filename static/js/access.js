/* Вкладка «Доступ»: учётные записи, пароли и привязка к ЦФО.

   Вкладка только для финотдела — на сервере то же правило, здесь она просто
   спрятана вместе с прочими его вкладками (см. app.js). Одна форма работает и
   на создание, и на правку: в режиме правки логин не меняется, а пустой пароль
   означает «оставить прежний». */
(function () {
  "use strict";

  var ROLES = { fin: "Финансовый отдел", cfo: "Руководитель ЦФО" };

  var cfoList = [];
  var users = [];
  var editing = null;      // логин правимой учётки или null, когда создаём новую

  function node(id) { return document.getElementById(id); }

  function setError(message) { node("u-err").textContent = message || ""; }

  function chosenCfo() {
    return Array.prototype.slice
      .call(node("u-cfo").querySelectorAll("input:checked"))
      .map(function (box) { return Number(box.value); });
  }

  function renderCfoPicker(selected) {
    var box = node("u-cfo");
    U.clear(box);
    cfoList.forEach(function (cfo) {
      var input = U.el("input", { type: "checkbox", value: cfo.id });
      input.checked = (selected || []).indexOf(Number(cfo.id)) >= 0;
      input.onchange = updateCfoCount;
      box.appendChild(U.el("label", { class: "pick-opt" }, [input, cfo.name]));
    });
    updateCfoCount();
  }

  function updateCfoCount() {
    var count = chosenCfo().length;
    node("u-cfo-count").textContent = count ? "— выбрано " + count : "— не выбрано";
  }

  /* Финотдел видит всё, поэтому список ЦФО ему в форме не нужен. */
  function applyRoleToForm() {
    node("u-cfo-box").hidden = node("u-role").value !== "cfo";
  }

  function startCreate() {
    editing = null;
    node("u-login").value = "";
    node("u-login").disabled = false;
    node("u-name").value = "";
    node("u-role").value = "cfo";
    node("u-pass").value = "";
    node("u-pass").placeholder = "";
    node("u-save").textContent = "Создать";
    node("u-cancel").hidden = true;
    renderCfoPicker([]);
    applyRoleToForm();
    setError("");
  }

  function startEdit(user) {
    editing = user.login;
    node("u-login").value = user.login;
    node("u-login").disabled = true;
    node("u-name").value = user.name;
    node("u-role").value = user.role;
    node("u-pass").value = "";
    node("u-pass").placeholder = "оставьте пустым — не менять";
    node("u-save").textContent = "Сохранить";
    node("u-cancel").hidden = false;
    renderCfoPicker(user.cfo_ids);
    applyRoleToForm();
    setError("");
    node("u-name").focus();
  }

  function cfoNames(ids) {
    if (!ids.length) return "";
    return ids.map(function (id) {
      var cfo = cfoList.filter(function (c) { return Number(c.id) === Number(id); })[0];
      return cfo ? cfo.name : "ЦФО " + id;
    }).join(", ");
  }

  function stateCell(user) {
    if (!user.is_active) return U.badge("critical", "отключена");
    if (!user.has_password) return U.badge("warning", "без пароля");
    return U.badge("good", "активна");
  }

  function actionButton(text, handler, cls) {
    return U.el("button", { class: "btn sm " + (cls || ""), text: text,
      on: { click: handler } });
  }

  function run(promise, note) {
    return promise.then(function () {
      if (note) U.toast(note);
      startCreate();
      load();
    }).catch(function (e) { setError(e.message); });
  }

  function render() {
    var body = node("t-users").querySelector("tbody");
    U.clear(body);
    if (!users.length) {
      body.appendChild(U.empty(6, "Учётных записей пока нет."));
    }
    users.forEach(function (user) {
      var actions = U.el("div", { class: "row-actions" }, [
        actionButton("Изменить", function () { startEdit(user); }),
        actionButton(user.is_active ? "Отключить" : "Включить", function () {
          run(API.updateUser(user.login, { is_active: !user.is_active }));
        }),
        actionButton("Удалить", function () {
          if (!window.confirm("Удалить учётную запись «" + user.login + "»?")) return;
          run(API.deleteUser(user.login), "Учётная запись удалена");
        }, "danger")
      ]);
      body.appendChild(U.el("tr", {}, [
        U.td(user.login), U.td(user.name), U.td(ROLES[user.role] || user.role),
        U.td(cfoNames(user.cfo_ids), "wrap"),
        U.el("td", {}, [stateCell(user)]),
        U.el("td", {}, [actions])
      ]));
    });
    node("acc-sub").textContent = users.length
      ? users.length + " учётных записей" : "";
    node("acc-open").hidden = !(Auth.state().setup_required);
  }

  function load() {
    return API.users().then(function (data) {
      users = data;
      render();
    }).catch(function (e) {
      U.toast("Не удалось прочитать учётные записи: " + e.message, "error");
    });
  }

  function save() {
    setError("");
    var name = node("u-name").value.trim();
    var role = node("u-role").value;
    var password = node("u-pass").value;
    var ids = role === "cfo" ? chosenCfo() : [];
    if (!name) { setError("Укажите имя — им подписываются изменения в журнале"); return; }
    if (role === "cfo" && !ids.length) { setError("Выберите хотя бы одно ЦФО"); return; }

    if (!editing) {
      var login = node("u-login").value.trim().toLowerCase();
      if (!login) { setError("Укажите логин"); return; }
      if (password.length < 8) { setError("Пароль должен быть не короче 8 символов"); return; }
      run(API.createUser({ login: login, name: name, role: role,
        cfo_ids: ids, password: password }), "Учётная запись создана");
      return;
    }

    if (password && password.length < 8) {
      setError("Пароль должен быть не короче 8 символов");
      return;
    }
    var login = editing;
    var chain = API.updateUser(login, { name: name, role: role, cfo_ids: ids });
    if (password) {
      chain = chain.then(function () { return API.resetPassword(login, password); });
    }
    run(chain, "Учётная запись сохранена");
  }

  window.Access = {
    setCfoList: function (list) {
      cfoList = list || [];
      renderCfoPicker(editing ? chosenCfo() : []);
      if (users.length) render();
    },
    load: load,
    init: function () {
      node("u-role").onchange = applyRoleToForm;
      node("u-save").onclick = save;
      node("u-cancel").onclick = startCreate;
      node("acc-refresh").onclick = load;
      startCreate();
    }
  };
})();
