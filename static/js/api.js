/* Обёртка над REST API. Роль передаётся заголовком X-User. */
(function () {
  "use strict";

  var role = "";   // "" = финотдел, "cfo:<id>" = руководитель ЦФО

  function headers(extra) {
    var out = extra || {};
    if (role) out["X-User"] = role;
    return out;
  }

  function request(method, path, body, isForm) {
    var options = { method: method, headers: headers({}) };
    if (body !== undefined && body !== null) {
      if (isForm) {
        options.body = body;
      } else {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
    }
    return fetch(path, options).then(function (response) {
      if (response.status === 204) return null;
      return response.json().then(function (data) {
        if (!response.ok) {
          var detail = data && data.detail;
          if (Array.isArray(detail)) detail = detail.map(function (d) { return d.msg; }).join("; ");
          throw new Error(detail || ("Ошибка " + response.status));
        }
        return data;
      }, function () {
        if (!response.ok) throw new Error("Ошибка " + response.status);
        return null;
      });
    });
  }

  window.API = {
    setRole: function (value) { role = value || ""; },
    getRole: function () { return role; },
    exportUrl: function (name, cfoId) {
      if (name === "cfo") return "/api/export/cfo/" + cfoId + ".xlsx";
      return "/api/export/" + name + ".xlsx";
    },
    download: function (name, cfoId) {
      var url = window.API.exportUrl(name, cfoId);
      return fetch(url, { headers: headers({}) }).then(function (response) {
        if (!response.ok) throw new Error("Не удалось выгрузить файл");
        var disposition = response.headers.get("content-disposition") || "";
        var match = /filename\*=UTF-8''([^;]+)/.exec(disposition);
        var filename = match ? decodeURIComponent(match[1]) : name + ".xlsx";
        return response.blob().then(function (blob) {
          var link = document.createElement("a");
          link.href = URL.createObjectURL(blob);
          link.download = filename;
          document.body.appendChild(link);
          link.click();
          document.body.removeChild(link);
          URL.revokeObjectURL(link.href);
        });
      });
    },

    me: function () { return request("GET", "/api/me"); },
    settings: function () { return request("GET", "/api/settings"); },
    saveSettings: function (payload) { return request("PUT", "/api/settings", payload); },
    dashboard: function (year) { return request("GET", "/api/dashboard" + (year ? "?year=" + year : "")); },
    cfoList: function () { return request("GET", "/api/cfo"); },
    cfoCard: function (id, year) { return request("GET", "/api/cfo/" + id + (year ? "?year=" + year : "")); },
    heatmap: function (year) { return request("GET", "/api/heatmap" + (year ? "?year=" + year : "")); },
    claims: function () { return request("GET", "/api/claims"); },
    outOfBudget: function () { return request("GET", "/api/out-of-budget"); },
    unmatched: function () { return request("GET", "/api/facts/unmatched"); },
    candidates: function (factId) { return request("GET", "/api/facts/" + factId + "/candidates"); },
    audit: function () { return request("GET", "/api/audit?limit=60"); },
    imports: function () { return request("GET", "/api/imports"); },
    rowLimit: function (rowId, amount) {
      return request("GET", "/api/rows/" + rowId + "/limit?amount=" + (amount || 0));
    },

    createRow: function (payload) { return request("POST", "/api/rows", payload); },
    deleteRow: function (rowId) { return request("DELETE", "/api/rows/" + rowId); },
    createFact: function (payload) { return request("POST", "/api/facts", payload); },
    createClaim: function (payload) { return request("POST", "/api/claims", payload); },
    deleteClaim: function (claimId) { return request("DELETE", "/api/claims/" + claimId); },
    matchFact: function (factId, rowId) {
      return request("POST", "/api/facts/" + factId + "/match", { row_id: rowId });
    },
    flagOutOfBudget: function (factId, flag) {
      return request("POST", "/api/facts/" + factId + "/out-of-budget?flag=" + (flag ? "true" : "false"));
    },
    autoMatch: function () { return request("POST", "/api/facts/auto-match"); },
    transfer: function (payload) { return request("POST", "/api/adjustments", payload); },

    operplan: function (year) {
      return request("GET", "/api/operplan" + (year ? "?year=" + year : ""));
    },
    operplanMissing: function (year) {
      return request("GET", "/api/operplan/missing" + (year ? "?year=" + year : ""));
    },
    operplanRefs: function (year) {
      return request("GET", "/api/operplan/references" + (year ? "?year=" + year : ""));
    },
    operplanLock: function (year, locked) {
      return request("POST", "/api/operplan/lock", { year: year, locked: locked });
    },
    copyYear: function (payload) { return request("POST", "/api/operplan/copy-year", payload); },
    addMissingRow: function (rowId, year) {
      return request("POST", "/api/operplan/missing/" + rowId + "/add?year=" + year);
    },
    createOperplanRow: function (payload, year) {
      return request("POST", "/api/operplan/rows?year=" + year, payload);
    },
    /* kind: "plan" — бюджет года, "fact" — факт года. Файл один и тот же по виду. */
    importBudget: function (file, year, kind) {
      var form = new FormData();
      form.append("file", file);
      form.append("year", String(year));
      form.append("kind", kind || "plan");
      return request("POST", "/api/operplan/import", form, true);
    },
    patchRow: function (rowId, payload) {
      return request("PATCH", "/api/rows/" + rowId, payload);
    },

    registry: function () { return request("GET", "/api/registry/cfo"); },
    mergePreview: function (sourceId, targetId) {
      return request("GET", "/api/registry/merge-preview?source_id=" + sourceId +
        "&target_id=" + targetId);
    },
    merge: function (sourceId, targetId) {
      return request("POST", "/api/registry/merge", { source_id: sourceId, target_id: targetId });
    },
    renameCfo: function (cfoId, name) {
      return request("PATCH", "/api/registry/cfo/" + cfoId, { name: name });
    },
    addAlias: function (cfoId, alias) {
      return request("POST", "/api/registry/cfo/" + cfoId + "/alias", { alias: alias });
    },
    deleteAlias: function (alias) {
      return request("DELETE", "/api/registry/alias?alias=" + encodeURIComponent(alias));
    },
    deleteCfo: function (cfoId) { return request("DELETE", "/api/registry/cfo/" + cfoId); },

    inspect: function (kind, file) {
      var form = new FormData();
      form.append("kind", kind);
      form.append("file", file);
      return request("POST", "/api/import/inspect", form, true);
    },
    importFile: function (kind, file, params) {
      var form = new FormData();
      form.append("file", file);
      Object.keys(params || {}).forEach(function (key) { form.append(key, params[key]); });
      return request("POST", "/api/import/" + kind, form, true);
    }
  };
})();