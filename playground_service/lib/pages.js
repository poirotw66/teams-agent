"use strict";

function loginPage(error = "") {
  const message = error ? `<p class="error">${error}</p>` : "";
  return `<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Microsoft 365 Agents Playground 測試登入</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f6fb; color: #242424; }
    main { width: min(88vw, 390px); padding: 32px; background: white; border-radius: 14px; box-shadow: 0 12px 34px #0002; }
    h1 { margin: 0 0 10px; font-size: 22px; }
    p { color: #616161; line-height: 1.5; }
    label { display: block; margin: 24px 0 8px; font-weight: 600; }
    input, button { width: 100%; box-sizing: border-box; border-radius: 7px; font: inherit; }
    input { padding: 11px 12px; border: 1px solid #8a8886; }
    button { margin-top: 16px; padding: 11px; border: 0; background: #5b5fc7; color: white; font-weight: 700; cursor: pointer; }
    .error { color: #a4262c; font-weight: 600; }
  </style>
</head>
<body><main>
  <h1>Agents Playground 測試環境</h1>
  <p>此環境僅供短期驗收。請輸入測試密碼。</p>
  ${message}
  <form method="post" action="/login">
    <label for="password">密碼</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
    <button type="submit">進入測試</button>
  </form>
</main></body></html>`;
}

function knowledgeControlScript() {
  return `"use strict";
(function () {
  const host = document.createElement("aside");
  host.id = "knowledge-backend-control";
  host.innerHTML = '<strong>知識後端</strong><select aria-label="知識後端"></select><button type="button" data-action="apply">套用</button><button type="button" data-action="reset">新對話</button><span role="status">載入中…</span>';
  const warning = document.createElement("aside");
  warning.id = "multi-window-warning";
  warning.setAttribute("role", "note");
  warning.textContent = "⚠ 多視窗提示：Playground 會將回覆同步顯示於所有已開啟視窗。測試時請只使用一個視窗，避免對話互相影響。刷新頁面不會重設 Bot 對話；請按「新對話」。";
  const style = document.createElement("style");
  style.textContent = '#knowledge-backend-control{position:fixed;z-index:2147483647;top:10px;right:16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center;max-width:min(720px,calc(100vw - 32px));padding:9px 12px;border:1px solid #d1d1d1;border-radius:8px;background:#fff;box-shadow:0 4px 14px #0002;font:13px system-ui,-apple-system,"Segoe UI",sans-serif;color:#242424}#knowledge-backend-control select,#knowledge-backend-control button{font:inherit;padding:5px 8px;border:1px solid #8a8886;border-radius:5px;background:#fff}#knowledge-backend-control button[data-action="apply"],#knowledge-backend-control button[data-action="reset"]{border-color:#5b5fc7;background:#5b5fc7;color:#fff;cursor:pointer}#knowledge-backend-control button[data-action="reset"]{border-color:#8a8886;background:#fff;color:#242424}#knowledge-backend-control button:disabled{opacity:.55;cursor:wait}#knowledge-backend-control span{max-width:230px;color:#616161}#multi-window-warning{position:fixed;z-index:2147483646;top:62px;right:16px;box-sizing:border-box;max-width:min(560px,calc(100vw - 32px));padding:9px 12px;border:1px solid #d83b01;border-radius:8px;background:#fff4ce;box-shadow:0 4px 14px #0002;color:#5c2d00;font:600 13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}';
  document.head.appendChild(style);
  document.body.appendChild(host);
  document.body.appendChild(warning);
  const select = host.querySelector("select");
  const applyButton = host.querySelector('[data-action="apply"]');
  const resetButton = host.querySelector('[data-action="reset"]');
  const status = host.querySelector("span");

  function render(data) {
    select.replaceChildren(...data.options.map(function (option) {
      const node = document.createElement("option");
      node.value = option.id;
      node.textContent = option.available ? option.label : option.label + "（未設定）";
      node.disabled = !option.available;
      node.title = option.reason || "";
      node.selected = option.id === data.activeBackend;
      return node;
    }));
    status.textContent = "目前：" + (select.selectedOptions[0] ? select.selectedOptions[0].textContent : data.activeBackend);
  }

  async function load() {
    try {
      const response = await fetch("/api/knowledge-backend", { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      render(await response.json());
    } catch (error) {
      status.textContent = "無法讀取後端狀態";
      applyButton.disabled = true;
      resetButton.disabled = true;
    }
  }

  applyButton.addEventListener("click", async function () {
    applyButton.disabled = true;
    resetButton.disabled = true;
    status.textContent = "切換中…";
    try {
      const response = await fetch("/api/knowledge-backend", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ backend: select.value }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "切換失敗");
      render(data);
    } catch (error) {
      status.textContent = error.message || "切換失敗";
    } finally {
      applyButton.disabled = false;
      resetButton.disabled = false;
    }
  });

  resetButton.addEventListener("click", async function () {
    applyButton.disabled = true;
    resetButton.disabled = true;
    status.textContent = "重設對話中…";
    try {
      const response = await fetch("/api/new-conversation", { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "重設失敗");
      try {
        localStorage.clear();
        sessionStorage.clear();
      } catch (_error) {}
      window.location.assign("/");
    } catch (error) {
      status.textContent = error.message || "重設失敗";
      applyButton.disabled = false;
      resetButton.disabled = false;
    }
  });
  load();
})();`;
}

async function proxyIndex(res, target) {
  try {
    const response = await fetch(`${target}/`);
    let body = await response.text();
    body = body.replace("</body>", '<script src="/_knowledge-control.js"></script></body>');
    const headers = { "content-type": response.headers.get("content-type") || "text/html; charset=utf-8", "cache-control": "no-store" };
    res.writeHead(response.status, headers);
    res.end(body);
  } catch (_error) {
    res.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    res.end("Agents Playground 尚未就緒，請稍後重試。\n");
  }
}

module.exports = {
  loginPage,
  knowledgeControlScript,
  proxyIndex,
};
