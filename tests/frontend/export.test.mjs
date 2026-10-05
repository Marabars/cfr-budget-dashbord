/* Выгрузка файлов: роль живёт в заголовке X-User, которого при переходе по
   ссылке нет. Именно из-за этого руководителю приезжал шаблон со всеми
   дирекциями — сервер считал его финотделом. Здесь поднимается настоящий
   js/api.js с подменённым fetch и проверяется, что и адрес, и заголовок на месте.

   Запуск: npm test */
import { readFileSync } from "node:fs";
import { describe, it, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { JSDOM, VirtualConsole } from "jsdom";

const asset = (rel) =>
  readFileSync(new URL(`../../static/${rel}`, import.meta.url), "utf8");

/** Поднимает api.js в jsdom и журналит запросы вместо сети. */
function mountApi() {
  // скачивание щёлкает по служебной ссылке blob:, а jsdom не умеет переходы —
  // ругань в журнал гасим, на проверки она не влияет
  const quiet = new VirtualConsole();
  const dom = new JSDOM("<!doctype html><body></body>",
    { runScripts: "outside-only", virtualConsole: quiet });
  const { window } = dom;
  const requests = [];
  window.fetch = (url, options) => {
    requests.push({ url, headers: (options && options.headers) || {} });
    return Promise.resolve({
      ok: true,
      status: 200,
      headers: { get: () => "attachment; filename*=UTF-8''%D1%84%D0%B0%D0%B9%D0%BB.xlsx" },
      blob: () => Promise.resolve({}),
    });
  };
  window.URL.createObjectURL = () => "blob:stub";
  window.URL.revokeObjectURL = () => {};
  window.eval(asset("js/api.js"));
  return { window, requests, API: window.API };
}

describe("выгрузка файлов", () => {
  let t;
  beforeEach(() => { t = mountApi(); });

  it("собирает адрес с годом", () => {
    assert.equal(t.API.exportUrl("budget-template", null, { year: 2027 }),
      "/api/export/budget-template.xlsx?year=2027");
    assert.equal(t.API.exportUrl("budget", null, {}), "/api/export/budget.xlsx",
      "без параметров хвоста быть не должно");
    assert.equal(t.API.exportUrl("cfo", 7, { year: 2026 }),
      "/api/export/cfo/7.xlsx?year=2026");
  });

  it("несёт роль руководителя в заголовке", async () => {
    t.API.setRole("cfo:5");
    await t.API.download("budget-template", null, { year: 2027 });
    assert.equal(t.requests.length, 1);
    assert.equal(t.requests[0].url, "/api/export/budget-template.xlsx?year=2027");
    assert.equal(t.requests[0].headers["X-User"], "cfo:5",
      "без заголовка сервер отдаст шаблон со всеми дирекциями");
  });

  it("финотделу заголовок не шлёт — он и так видит всё", async () => {
    t.API.setRole("");
    await t.API.download("budget", null, { year: 2027 });
    assert.equal(t.requests[0].headers["X-User"], undefined);
  });
});
