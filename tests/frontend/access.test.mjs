/* Экран входа и вкладка «Доступ» в настоящем DOM: pytest проверяет сервер, а
   решение «пускать внутрь или показать форму» целиком на клиенте. index.html и
   js/* поднимаются в jsdom, сеть заменена заглушками window.API.

   Запуск: npm install && npm test (нужен только jsdom). */
import { readFileSync } from "node:fs";
import { describe, it, before } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const asset = (rel) =>
  readFileSync(new URL(`../../static/${rel}`, import.meta.url), "utf8");

const IT = "Первая дирекция";
const HR = "Вторая дирекция";
const CFO_LIST = [{ id: 1, name: IT }, { id: 2, name: HR }];

const FIN = { login: "fin", name: "Финансовый отдел", role: "fin", cfo_ids: [], is_fin: true,
  viewing_as: false };
const BOSS = { login: "ivanov", name: "Иванов И.", role: "cfo", cfo_ids: [1], is_fin: false,
  viewing_as: false };

const USERS = [
  { login: "fin", name: "Финансовый отдел", role: "fin", cfo_ids: [],
    is_active: true, has_password: true },
  { login: "ivanov", name: "Иванов И.", role: "cfo", cfo_ids: [1],
    is_active: true, has_password: true },
  { login: "petrova", name: "Петрова А.", role: "cfo", cfo_ids: [1, 2],
    is_active: false, has_password: false },
];

/* Состояния, в которых приложение встречает пользователя. */
const CLOSED = { authenticated: false, setup_required: false, user: null };
const OPEN = { authenticated: true, setup_required: true, user: FIN };
const INSIDE = { authenticated: true, setup_required: false, user: FIN };
const BOSS_INSIDE = { authenticated: true, setup_required: false, user: BOSS };

/* ---------- стенд ---------- */

/** Поднимает экран входа и вкладку доступа в jsdom.
    state — что отдаёт /api/auth/state; after — состояние после удачного входа. */
async function mount(state = CLOSED, { after = INSIDE, users = USERS, fail = null } = {}) {
  const calls = [];
  let current = state;

  const API = {
    authState: () => Promise.resolve(current),
    authLogin: (login, password) => {
      calls.push({ kind: "login", login, password });
      if (password !== "pravilnyy-parol") {
        return Promise.reject(new Error("Неверный логин или пароль"));
      }
      current = after;
      return Promise.resolve(after.user);
    },
    authSetup: (payload) => {
      calls.push({ kind: "setup", payload });
      current = after;
      return Promise.resolve({ ok: true, login: "fin" });
    },
    authLogout: () => {
      calls.push({ kind: "logout" });
      current = CLOSED;
      return Promise.resolve({ ok: true });
    },
    authPassword: (currentPass, password) => {
      calls.push({ kind: "password", current: currentPass, password });
      return Promise.resolve({ ok: true });
    },
    users: () => Promise.resolve(users),
    createUser: (payload) => {
      calls.push({ kind: "create", payload });
      return fail ? Promise.reject(new Error(fail)) : Promise.resolve(payload);
    },
    updateUser: (login, payload) => {
      calls.push({ kind: "update", login, payload });
      return Promise.resolve(payload);
    },
    resetPassword: (login, password) => {
      calls.push({ kind: "reset", login, password });
      return Promise.resolve({ ok: true });
    },
    deleteUser: (login) => {
      calls.push({ kind: "delete", login });
      return Promise.resolve(null);
    },
  };

  const dom = new JSDOM(asset("index.html"), {
    runScripts: "outside-only", pretendToBeVisual: true,
  });
  const { window } = dom;
  /* Настоящий css: экран входа перекрывает приложение только пока он
     position: fixed поверх всего — без стилей проверка была бы слепой. */
  const style = window.document.createElement("style");
  style.textContent = asset("css/app.css");
  window.document.head.appendChild(style);
  window.API = API;
  window.confirm = () => true;
  let reloaded = 0;
  window.App = { reload: () => { reloaded += 1; } };
  ["js/util.js", "js/auth.js", "js/access.js"].forEach((f) => window.eval(asset(f)));

  window.Auth.init();
  window.Access.init();
  window.Access.setCfoList(CFO_LIST);
  await window.Auth.boot();
  await settle(window);

  const $ = (sel) => window.document.querySelector(sel);
  return {
    window, calls, $,
    $$: (sel) => Array.from(window.document.querySelectorAll(sel)),
    reloads: () => reloaded,
    click: (node) => node.dispatchEvent(new window.MouseEvent("click", { bubbles: true })),
    fire: (node, type) => node.dispatchEvent(new window.Event(type)),
    styleOf: (node) => window.getComputedStyle(node),
    /* Заполняет и отправляет форму входа так же, как это делает кнопка. */
    submitGate: async (values) => {
      Object.keys(values).forEach((id) => { $("***REMOVED***" + id).value = values[id]; });
      $("***REMOVED***gate-form").dispatchEvent(new window.Event("submit", { cancelable: true }));
      await settle(window);
    },
    loadUsers: async () => { await window.Access.load(); await settle(window); },
  };
}

/** Даёт промисам обработчиков доиграть: всё уходит через API и then(). */
function settle(window, ms = 30) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

/* Объекты приезжают из окна jsdom: у них чужой Object.prototype, и строгое
   сравнение спотыкается об это раньше, чем об содержимое. */
const plain = (value) => JSON.parse(JSON.stringify(value));

const rows = (t) => t.$$("***REMOVED***t-users tbody tr");
const cells = (row) => Array.from(row.children).map((c) => c.textContent.trim());

/* ---------- экран входа ---------- */

describe("экран входа", () => {
  it("поднимается, когда сессии нет", async () => {
    const t = await mount(CLOSED);
    assert.equal(t.$("***REMOVED***gate").hidden, false);
    assert.equal(t.$("***REMOVED***gate-title").textContent, "Вход");
    assert.equal(t.$("***REMOVED***f-gate-login").hidden, false, "логин спрашиваем");
    assert.equal(t.$("***REMOVED***f-gate-pass2").hidden, true, "повтор пароля — только при смене");
    assert.equal(t.$("***REMOVED***gate-cancel").hidden, true, "отменять нечего: внутрь иначе не попасть");
    assert.equal(t.reloads(), 0, "данные за экраном не грузим");
  });

  it("перекрывает приложение, а не висит в потоке страницы", async () => {
    const t = await mount(CLOSED);
    const style = t.styleOf(t.$("***REMOVED***gate"));
    assert.equal(style.position, "fixed");
    assert.ok(Number(style.zIndex) > 1, "должен лежать поверх шапки");
  });

  it("неверный пароль показывает ошибку и не пускает", async () => {
    const t = await mount(CLOSED);
    await t.submitGate({ "gate-login": "fin", "gate-pass": "ne-tot" });
    assert.equal(t.$("***REMOVED***gate").hidden, false);
    assert.match(t.$("***REMOVED***gate-err").textContent, /Неверный логин или пароль/);
    assert.equal(t.reloads(), 0);
  });

  it("верный пароль гасит экран и грузит данные", async () => {
    const t = await mount(CLOSED);
    await t.submitGate({ "gate-login": " Fin ", "gate-pass": "pravilnyy-parol" });
    assert.equal(t.$("***REMOVED***gate").hidden, true);
    assert.equal(t.calls[0].login, "Fin", "пробелы обрезаем, регистр оставляем серверу");
    assert.equal(t.reloads(), 1);
    assert.equal(t.$("***REMOVED***who").hidden, false, "в шапке появляется, кто вошёл");
    assert.equal(t.$("***REMOVED***who-name").textContent, "Финансовый отдел");
  });

  it("401 из любого запроса поднимает экран заново", async () => {
    const t = await mount(INSIDE);
    assert.equal(t.$("***REMOVED***gate").hidden, true);
    t.window.Auth.expired();
    assert.equal(t.$("***REMOVED***gate").hidden, false);
    assert.match(t.$("***REMOVED***gate-err").textContent, /Сессия закончилась/);
    assert.equal(t.$("***REMOVED***who").hidden, true, "подпись о вошедшем снимаем");
  });

  it("выход возвращает к форме входа", async () => {
    const t = await mount(INSIDE);
    t.click(t.$("***REMOVED***who-out"));
    await settle(t.window);
    assert.equal(t.calls.pop().kind, "logout");
    assert.equal(t.$("***REMOVED***gate").hidden, false);
    assert.equal(t.$("***REMOVED***gate-title").textContent, "Вход");
  });
});

/* ---------- первая настройка ---------- */

describe("первая настройка входа", () => {
  it("пока пароля нет — приложение открыто, в шапке кнопка настройки", async () => {
    const t = await mount(OPEN);
    assert.equal(t.$("***REMOVED***gate").hidden, true, "экран не мешает работать");
    assert.equal(t.$("***REMOVED***who-setup").hidden, false);
    assert.equal(t.$("***REMOVED***who").hidden, true, "выходить некуда: сессии ещё нет");
  });

  it("форма настройки спрашивает имя и повтор пароля, логин не спрашивает", async () => {
    const t = await mount(OPEN);
    t.click(t.$("***REMOVED***who-setup"));
    assert.equal(t.$("***REMOVED***gate").hidden, false);
    assert.equal(t.$("***REMOVED***gate-title").textContent, "Настройка входа");
    assert.equal(t.$("***REMOVED***f-gate-login").hidden, true, "логин финотдела всегда «fin»");
    assert.equal(t.$("***REMOVED***f-gate-name").hidden, false);
    assert.equal(t.$("***REMOVED***f-gate-pass2").hidden, false);
    assert.equal(t.$("***REMOVED***gate-cancel").hidden, false, "передумать можно: приложение открыто");
  });

  it("короткий пароль и расхождение с повтором не уходят на сервер", async () => {
    const t = await mount(OPEN);
    t.click(t.$("***REMOVED***who-setup"));
    await t.submitGate({ "gate-pass": "1234", "gate-pass2": "1234" });
    assert.match(t.$("***REMOVED***gate-err").textContent, /не короче 8/);

    await t.submitGate({ "gate-pass": "dlinnyy-parol", "gate-pass2": "drugoy-parol" });
    assert.match(t.$("***REMOVED***gate-err").textContent, /не совпадают/);
    assert.equal(t.calls.length, 0, "ни одного запроса");
  });

  it("удачная настройка закрывает экран и перечитывает состояние", async () => {
    const t = await mount(OPEN);
    t.click(t.$("***REMOVED***who-setup"));
    await t.submitGate({ "gate-name": "Финотдел МР",
      "gate-pass": "dlinnyy-parol", "gate-pass2": "dlinnyy-parol" });
    assert.equal(t.calls[0].payload.name, "Финотдел МР");
    assert.equal(t.$("***REMOVED***gate").hidden, true);
    assert.equal(t.$("***REMOVED***who-setup").hidden, true, "настраивать больше нечего");
    assert.equal(t.$("***REMOVED***who").hidden, false);
    assert.equal(t.reloads(), 1);
  });

  it("отмена закрывает экран, ничего не меняя", async () => {
    const t = await mount(OPEN);
    t.click(t.$("***REMOVED***who-setup"));
    t.click(t.$("***REMOVED***gate-cancel"));
    assert.equal(t.$("***REMOVED***gate").hidden, true);
    assert.equal(t.calls.length, 0);
  });
});

/* ---------- смена пароля ---------- */

describe("смена своего пароля", () => {
  it("спрашивает текущий пароль и повтор нового", async () => {
    const t = await mount(INSIDE);
    t.click(t.$("***REMOVED***who-pass"));
    assert.equal(t.$("***REMOVED***gate-title").textContent, "Смена пароля");
    assert.equal(t.$("***REMOVED***f-gate-current").hidden, false);
    assert.equal(t.$("***REMOVED***f-gate-pass2").hidden, false);
    assert.equal(t.$("***REMOVED***f-gate-login").hidden, true);
  });

  it("отправляет старый и новый пароль, потом закрывается", async () => {
    const t = await mount(INSIDE);
    t.click(t.$("***REMOVED***who-pass"));
    await t.submitGate({ "gate-current": "staryy-parol",
      "gate-pass": "novyy-parol", "gate-pass2": "novyy-parol" });
    assert.deepEqual(plain(t.calls.pop()),
      { kind: "password", current: "staryy-parol", password: "novyy-parol" });
    assert.equal(t.$("***REMOVED***gate").hidden, true);
    assert.equal(t.reloads(), 0, "данные те же — перезагружать нечего");
  });
});

/* ---------- роль в шапке ---------- */

describe("переключатель роли", () => {
  it("виден финотделу", async () => {
    const t = await mount(INSIDE);
    assert.equal(t.$("***REMOVED***role-ctl").hidden, false);
  });

  it("скрыт от руководителя ЦФО", async () => {
    const t = await mount(BOSS_INSIDE);
    assert.equal(t.$("***REMOVED***role-ctl").hidden, true);
  });

  it("подпись и переключатель следуют за сменой роли в шапке", async () => {
    const t = await mount(INSIDE);
    assert.equal(t.$("***REMOVED***who-name").textContent, "Финансовый отдел");
    // так делает app.js после переключения роли: /api/me отдаёт уже руководителя
    t.window.Auth.showUser({ ...BOSS, name: "Руководитель · " + IT, viewing_as: true });
    assert.equal(t.$("***REMOVED***who-name").textContent, "Руководитель · " + IT);
    assert.equal(t.$("***REMOVED***role-ctl").hidden, false, "вернуться в свою роль должно быть чем");
  });

  it("остаётся, когда финотдел смотрит глазами руководителя", async () => {
    const viewing = { authenticated: true, setup_required: false,
      user: { ...BOSS, viewing_as: true } };
    const t = await mount(viewing);
    assert.equal(t.$("***REMOVED***role-ctl").hidden, false, "иначе не вернуться в свою роль");
  });
});

/* ---------- вкладка «Доступ» ---------- */

describe("вкладка «Доступ»", () => {
  let t;
  before(async () => { t = await mount(INSIDE); await t.loadUsers(); });

  it("показывает учётки с ролью и ЦФО по-русски", () => {
    assert.equal(rows(t).length, 3);
    assert.deepEqual(cells(rows(t)[1]).slice(0, 4),
      ["ivanov", "Иванов И.", "Руководитель ЦФО", IT]);
    assert.equal(cells(rows(t)[2])[3], IT + ", " + HR);
  });

  it("отмечает отключённые и беспарольные", () => {
    assert.equal(rows(t)[0].querySelector(".badge").textContent, "активна");
    assert.equal(rows(t)[2].querySelector(".badge").textContent, "отключена");
  });

  it("список ЦФО в форме — по галочке на дирекцию", () => {
    assert.equal(t.$$("***REMOVED***u-cfo .pick-opt").length, 2);
    assert.equal(t.$("***REMOVED***u-cfo-count").textContent, "— не выбрано");
  });

  it("финотделу список ЦФО не нужен", () => {
    t.$("***REMOVED***u-role").value = "fin";
    t.fire(t.$("***REMOVED***u-role"), "change");
    assert.equal(t.$("***REMOVED***u-cfo-box").hidden, true);
    t.$("***REMOVED***u-role").value = "cfo";
    t.fire(t.$("***REMOVED***u-role"), "change");
    assert.equal(t.$("***REMOVED***u-cfo-box").hidden, false);
  });
});

describe("вкладка «Доступ»: создание", () => {
  it("руководителя без ЦФО не заводит", async () => {
    const t = await mount(INSIDE);
    await t.loadUsers();
    t.$("***REMOVED***u-login").value = "sidorov";
    t.$("***REMOVED***u-name").value = "Сидоров";
    t.$("***REMOVED***u-pass").value = "dlinnyy-parol";
    t.click(t.$("***REMOVED***u-save"));
    await settle(t.window);
    assert.match(t.$("***REMOVED***u-err").textContent, /хотя бы одно ЦФО/);
    assert.equal(t.calls.filter((c) => c.kind === "create").length, 0);
  });

  it("короткий пароль не уходит на сервер", async () => {
    const t = await mount(INSIDE);
    await t.loadUsers();
    t.$("***REMOVED***u-login").value = "sidorov";
    t.$("***REMOVED***u-name").value = "Сидоров";
    t.$("***REMOVED***u-pass").value = "123";
    t.$$("***REMOVED***u-cfo input")[0].click();
    t.click(t.$("***REMOVED***u-save"));
    await settle(t.window);
    assert.match(t.$("***REMOVED***u-err").textContent, /не короче 8/);
    assert.equal(t.calls.filter((c) => c.kind === "create").length, 0);
  });

  it("заводит руководителя с выбранными ЦФО", async () => {
    const t = await mount(INSIDE);
    await t.loadUsers();
    t.$("***REMOVED***u-login").value = " Sidorov ";
    t.$("***REMOVED***u-name").value = "Сидоров";
    t.$("***REMOVED***u-pass").value = "dlinnyy-parol";
    t.$$("***REMOVED***u-cfo input")[1].click();
    assert.equal(t.$("***REMOVED***u-cfo-count").textContent, "— выбрано 1");
    t.click(t.$("***REMOVED***u-save"));
    await settle(t.window);
    const created = t.calls.filter((c) => c.kind === "create").pop();
    assert.deepEqual(plain(created.payload), {
      login: "sidorov", name: "Сидоров", role: "cfo",
      cfo_ids: [2], password: "dlinnyy-parol",
    });
    assert.equal(t.$("***REMOVED***u-login").value, "", "форма очищается под следующую учётку");
  });

  it("отказ сервера показывает рядом с формой", async () => {
    const t = await mount(INSIDE, { fail: "Логин «ivanov» уже занят" });
    await t.loadUsers();
    t.$("***REMOVED***u-login").value = "ivanov";
    t.$("***REMOVED***u-name").value = "Другой";
    t.$("***REMOVED***u-pass").value = "dlinnyy-parol";
    t.$$("***REMOVED***u-cfo input")[0].click();
    t.click(t.$("***REMOVED***u-save"));
    await settle(t.window);
    assert.match(t.$("***REMOVED***u-err").textContent, /уже занят/);
  });
});

describe("вкладка «Доступ»: правка", () => {
  async function editIvanov() {
    const t = await mount(INSIDE);
    await t.loadUsers();
    t.click(rows(t)[1].querySelectorAll("button")[0]);   // «Изменить»
    return t;
  }

  it("переносит учётку в форму и запирает логин", async () => {
    const t = await editIvanov();
    assert.equal(t.$("***REMOVED***u-login").value, "ivanov");
    assert.equal(t.$("***REMOVED***u-login").disabled, true, "логин — ключ, его не меняем");
    assert.equal(t.$("***REMOVED***u-name").value, "Иванов И.");
    assert.equal(t.$("***REMOVED***u-save").textContent, "Сохранить");
    assert.equal(t.$("***REMOVED***u-cancel").hidden, false);
    assert.equal(t.$$("***REMOVED***u-cfo input")[0].checked, true, "его ЦФО отмечено");
  });

  it("пустой пароль означает «оставить прежний»", async () => {
    const t = await editIvanov();
    t.$("***REMOVED***u-name").value = "Иванов И. И.";
    t.click(t.$("***REMOVED***u-save"));
    await settle(t.window);
    assert.deepEqual(plain(t.calls.filter((c) => c.kind === "update").pop()),
      { kind: "update", login: "ivanov",
        payload: { name: "Иванов И. И.", role: "cfo", cfo_ids: [1] } });
    assert.equal(t.calls.filter((c) => c.kind === "reset").length, 0);
  });

  it("заполненный пароль сбрасывается отдельным запросом", async () => {
    const t = await editIvanov();
    t.$("***REMOVED***u-pass").value = "vydannyy-parol";
    t.click(t.$("***REMOVED***u-save"));
    await settle(t.window);
    assert.deepEqual(plain(t.calls.filter((c) => c.kind === "reset").pop()),
      { kind: "reset", login: "ivanov", password: "vydannyy-parol" });
  });

  it("отмена возвращает форму к созданию", async () => {
    const t = await editIvanov();
    t.click(t.$("***REMOVED***u-cancel"));
    assert.equal(t.$("***REMOVED***u-login").value, "");
    assert.equal(t.$("***REMOVED***u-login").disabled, false);
    assert.equal(t.$("***REMOVED***u-save").textContent, "Создать");
  });

  it("отключает и удаляет с подтверждением", async () => {
    const t = await mount(INSIDE);
    await t.loadUsers();
    t.click(rows(t)[1].querySelectorAll("button")[1]);   // «Отключить»
    await settle(t.window);
    assert.deepEqual(plain(t.calls.filter((c) => c.kind === "update").pop()),
      { kind: "update", login: "ivanov", payload: { is_active: false } });

    t.click(rows(t)[1].querySelectorAll("button")[2]);   // «Удалить»
    await settle(t.window);
    assert.equal(t.calls.filter((c) => c.kind === "delete").pop().login, "ivanov");
  });

  it("без подтверждения не удаляет", async () => {
    const t = await mount(INSIDE);
    await t.loadUsers();
    t.window.confirm = () => false;
    t.click(rows(t)[1].querySelectorAll("button")[2]);
    await settle(t.window);
    assert.equal(t.calls.filter((c) => c.kind === "delete").length, 0);
  });
});
