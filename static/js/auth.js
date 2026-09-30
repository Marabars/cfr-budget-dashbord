/* Вход в приложение: экран входа, первая настройка и смена пароля.

   Пока финотдел не задал первый пароль, приложение открыто (режим доверенной
   сети) — экран не показывается, в шапке висит кнопка «Настроить вход». После
   настройки любой запрос без сессии отдаёт 401, и экран поднимается сам. */
(function () {
  "use strict";

  var MODES = {
    login: {
      title: "Вход", submit: "Войти",
      hint: "Введите логин и пароль. Их выдаёт финансовый отдел.",
      show: ["f-gate-login"], passLabel: "Пароль", passAuto: "current-password"
    },
    setup: {
      title: "Настройка входа", submit: "Включить вход",
      hint: "Задайте пароль финансового отдела — логин будет «fin». " +
            "После этого приложение закроется для всех, кому не завели учётную запись.",
      show: ["f-gate-name", "f-gate-pass2"], passLabel: "Новый пароль",
      passAuto: "new-password", cancel: true
    },
    password: {
      title: "Смена пароля", submit: "Сменить",
      hint: "Новый пароль — не короче 8 символов. Прочие ваши сессии закроются.",
      show: ["f-gate-current", "f-gate-pass2"], passLabel: "Новый пароль",
      passAuto: "new-password", cancel: true
    }
  };

  var state = { authenticated: true, setup_required: true, user: null };
  var mode = "";

  function node(id) { return document.getElementById(id); }

  function setError(message) {
    var box = node("gate-err");
    box.textContent = message || "";
    box.hidden = !message;
  }

  function show(name) {
    var spec = MODES[name];
    mode = name;
    node("gate-title").textContent = spec.title;
    node("gate-hint").textContent = spec.hint;
    node("gate-submit").textContent = spec.submit;
    node("gate-cancel").hidden = !spec.cancel;
    node("gate-pass-label").textContent = spec.passLabel;
    node("gate-pass").setAttribute("autocomplete", spec.passAuto);
    ["f-gate-login", "f-gate-name", "f-gate-current", "f-gate-pass2"].forEach(function (id) {
      node(id).hidden = spec.show.indexOf(id) < 0;
    });
    ["gate-pass", "gate-pass2", "gate-current"].forEach(function (id) { node(id).value = ""; });
    setError("");
    node("gate").hidden = false;
    var first = spec.show.indexOf("f-gate-login") >= 0 ? "gate-login"
      : (spec.show.indexOf("f-gate-current") >= 0 ? "gate-current" : "gate-pass");
    node(first).focus();
  }

  function hide() {
    mode = "";
    node("gate").hidden = true;
    setError("");
  }

  /* Кто вошёл — в шапке. До настройки входа выходить некуда: сессии ещё нет. */
  function applyHeader() {
    var user = state.user;
    var configured = state.authenticated && !state.setup_required;
    node("who").hidden = !configured;
    node("who-setup").hidden = !(state.authenticated && state.setup_required &&
      user && user.is_fin);
    if (configured && user) node("who-name").textContent = user.name;
    // Роль подменяет только финотдел: руководителю переключатель не нужен и запрещён
    var roleCtl = node("role-ctl");
    if (roleCtl) roleCtl.hidden = !(user && user.is_fin) && !(user && user.viewing_as);
  }

  function readState() {
    return API.authState().then(function (data) {
      state = data;
      applyHeader();
      return data;
    });
  }

  function newPassword() {
    var pass = node("gate-pass").value;
    if (pass.length < 8) throw new Error("Пароль должен быть не короче 8 символов");
    if (pass !== node("gate-pass2").value) throw new Error("Пароли не совпадают");
    return pass;
  }

  /* После входа и после настройки путь один: перечитать состояние и данные. */
  function enter() {
    return readState().then(function () {
      hide();
      if (window.App) window.App.reload();
    });
  }

  function submit() {
    setError("");
    try {
      if (mode === "login") {
        return API.authLogin(node("gate-login").value.trim(), node("gate-pass").value)
          .then(enter).catch(function (e) { setError(e.message); });
      }
      if (mode === "setup") {
        return API.authSetup({ name: node("gate-name").value, password: newPassword() })
          .then(enter).catch(function (e) { setError(e.message); });
      }
      return API.authPassword(node("gate-current").value, newPassword())
        .then(function () {
          hide();
          U.toast("Пароль изменён");
        })
        .catch(function (e) { setError(e.message); });
    } catch (e) {
      setError(e.message);
      return Promise.resolve();
    }
  }

  window.Auth = {
    /* Первое решение при загрузке: пускать в приложение или показать экран. */
    boot: function () {
      return API.authState().then(function (data) {
        state = data;
        applyHeader();
        if (!data.authenticated) show("login");
        return data;
      }).catch(function () {
        // сервер недоступен — молчим, ошибку покажет первая же загрузка данных
        return state;
      });
    },
    state: function () { return state; },
    user: function () { return state.user; },
    /* Финотдел сменил роль в шапке — подпись и переключатель должны это показать.
       Состояние входа при этом не меняется: сессия та же. */
    showUser: function (me) {
      if (!state.authenticated) return;
      state.user = me;
      applyHeader();
    },
    /* Любой запрос ответил 401: сессия кончилась или её закрыли из-под нас. */
    expired: function () {
      if (mode === "login") return;
      state = { authenticated: false, setup_required: false, user: null };
      applyHeader();
      show("login");
      setError("Сессия закончилась — войдите заново");
    },
    openSetup: function () { show("setup"); },
    openPassword: function () { show("password"); },

    init: function () {
      node("gate-form").onsubmit = function (event) {
        event.preventDefault();
        submit();
      };
      node("gate-cancel").onclick = hide;
      node("who-setup").onclick = function () { show("setup"); };
      node("who-pass").onclick = function () { show("password"); };
      node("who-out").onclick = function () {
        API.authLogout().then(function () {
          state = { authenticated: false, setup_required: false, user: null };
          applyHeader();
          show("login");
        }).catch(function (e) { U.toast(e.message, "error"); });
      };
    }
  };
})();
