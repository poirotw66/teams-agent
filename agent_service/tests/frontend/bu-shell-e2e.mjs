/**
 * Live BU shell smoke (headless Chrome via puppeteer-core).
 * Run: node agent_service/tests/frontend/bu-shell-e2e.mjs
 * Requires: backoffice on http://127.0.0.1:8092 and Google Chrome.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const BASE = process.env.AI_OPS_E2E_BASE || "http://127.0.0.1:8092";
const CHROME =
  process.env.CHROME_PATH ||
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

const require = createRequire(import.meta.url);

async function loadPuppeteer() {
  const cached = "/tmp/ai-ops-e2e-puppeteer/node_modules/puppeteer-core";
  try {
    return require(cached);
  } catch {
    try {
      return require("puppeteer-core");
    } catch {
      const { execSync } = await import("node:child_process");
      execSync("npm install --no-save --prefix /tmp/ai-ops-e2e-puppeteer puppeteer-core@24.2.0", {
        stdio: "inherit",
      });
      return require(cached);
    }
  }
}

async function openBuPage(browser, hash) {
  const page = await browser.newPage();
  await page.evaluateOnNewDocument(() => {
    localStorage.setItem("ai_ops_bu_shell_v1", "1");
    sessionStorage.setItem(
      "ai_ops_backoffice_auth",
      JSON.stringify({
        userId: "e2e.admin",
        userName: "E2E Admin",
        role: "SYSTEM_ADMIN",
        ownerUnits: "IT",
      }),
    );
  });
  const errors = [];
  page.on("pageerror", (err) => errors.push(String(err)));
  await page.goto(`${BASE}/?buShell=1${hash || ""}`, {
    waitUntil: "networkidle0",
    timeout: 45000,
  });
  // Wait for nav to render.
  await page.waitForSelector("#nav a, #nav .bu-nav-items a", { timeout: 20000 });
  return { page, errors };
}

test("BU shell live E2E: primary nav, five task pages, no classic switcher", async (t) => {
  let healthy = false;
  try {
    const res = await fetch(`${BASE}/healthz`);
    healthy = res.ok;
  } catch {
    healthy = false;
  }
  if (!healthy) {
    t.skip(`backoffice not reachable at ${BASE}`);
    return;
  }

  let browser;
  try {
    const puppeteer = await loadPuppeteer();
    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: "new",
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
  } catch (error) {
    t.skip(`Chrome/puppeteer unavailable: ${error.message}`);
    return;
  }

  try {
    const { page, errors } = await openBuPage(browser, "#/knowledge_ops/workHub");
    const navLabels = await page.$$eval("#nav a", (nodes) =>
      nodes.map((n) => n.textContent.trim()).filter(Boolean),
    );
    for (const label of ["我的工作", "改善案件", "知識內容", "對話紀錄", "品質驗收", "營運分析"]) {
      assert.ok(navLabels.includes(label), `missing nav ${label}; got ${navLabels.join(",")}`);
    }
    assert.equal(await page.$(".workspace-switcher"), null, "classic workspace switcher must be hidden");
    assert.ok(await page.$("body.bu-shell-v1"), "bu-shell-v1 body class missing");

    // Shared modal contract: keyboard users enter the dialog, get a semantic
    // dialog boundary, and return to the trigger when it closes.
    const roleButton = await page.$("#meta-panel button[title*='切換開發測試身分']");
    assert.ok(roleButton, "role switcher trigger missing");
    await roleButton.click();
    await page.waitForSelector("#modal-root:not([hidden]) [role=dialog]", { timeout: 5000 });
    const modalState = await page.$eval("#modal-root [role=dialog]", (modal) => ({
      modal: modal.getAttribute("aria-modal"),
      labelledBy: modal.getAttribute("aria-labelledby"),
      focusInside: modal.contains(document.activeElement),
    }));
    assert.equal(modalState.modal, "true", "modal must expose aria-modal");
    assert.ok(modalState.labelledBy, "modal must reference its heading");
    assert.equal(modalState.focusInside, true, "focus must enter the modal");
    await page.keyboard.down("Shift");
    await page.keyboard.press("Tab");
    await page.keyboard.up("Shift");
    assert.equal(
      await page.evaluate(() => document.activeElement?.textContent?.trim().startsWith("✕ 關閉")),
      true,
      "reverse Tab from the first control must wrap to the close control",
    );
    await page.keyboard.press("Tab");
    assert.equal(
      await page.evaluate(() => document.activeElement?.closest("#modal-root [role=dialog]") !== null),
      true,
      "forward Tab must remain inside the dialog",
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.$eval("#modal-root", (root) => root.hidden),
      true,
      "Escape must close the modal",
    );
    assert.equal(
      await page.evaluate(() => document.activeElement?.matches("#meta-panel button.meta-chip")),
      true,
      "closing the modal must restore focus to its trigger",
    );

    // Task 1: 我的工作
    await page.waitForFunction(
      () =>
        document.body.classList.contains("bu-shell-v1") &&
        (/早安/.test(document.querySelector("#app h2")?.textContent || "") ||
          /待我處理|我的待處理/.test(document.getElementById("app")?.innerText || "")),
      { timeout: 20000 },
    );

    // Task 2: 改善案件 list + detail if available
    await page.click("#nav a[href*='quality']");
    await page.waitForFunction(() => document.querySelector("#app h2")?.textContent?.includes("改善案件"), {
      timeout: 20000,
    });
    const openedCase = await page.evaluate(async () => {
      const res = await fetch("/api/quality-cases?limit=1", {
        headers: {
          "X-Backoffice-User-Id": "e2e.admin",
          "X-Backoffice-Role": "SYSTEM_ADMIN",
          "X-Backoffice-Owner-Units": "IT",
        },
      });
      const data = await res.json();
      const item = (data.items || data.cases || [])[0];
      return item?.case_id || null;
    });
    if (openedCase) {
      await page.goto(`${BASE}/?buShell=1#/knowledge_ops/quality?caseId=${encodeURIComponent(openedCase)}&tab=cases`, {
        waitUntil: "networkidle0",
        timeout: 45000,
      });
      await page.waitForSelector(".bu-case-page, .bu-case-crumb", { timeout: 20000 });
      const crumb = await page.$eval(".bu-case-crumb a, .bu-case-crumb", (el) => el.textContent || "");
      assert.ok(/返回/.test(crumb) || crumb.length > 0, "case detail crumb missing");
    }

    // Task 3: 知識內容
    await page.goto(`${BASE}/?buShell=1#/knowledge_ops/contentLists?tab=faq`, {
      waitUntil: "networkidle0",
      timeout: 45000,
    });
    await page.waitForFunction(() => document.querySelector("#app h2")?.textContent?.includes("知識內容"), {
      timeout: 20000,
    });
    const openGuideGrid = await page.$("details[open] .content-guide-grid");
    assert.equal(openGuideGrid, null, "full decision guide must stay collapsed until expanded");

    // Task 4: 對話紀錄
    await page.goto(`${BASE}/?buShell=1#/knowledge_ops/conversations`, {
      waitUntil: "networkidle0",
      timeout: 45000,
    });
    await page.waitForFunction(
      () => /對話/.test(document.querySelector("#app h2")?.textContent || ""),
      { timeout: 20000 },
    );
    const conversationId = await page.evaluate(async () => {
      const res = await fetch("/api/conversations?limit=1", {
        headers: {
          "X-Backoffice-User-Id": "e2e.admin",
          "X-Backoffice-Role": "SYSTEM_ADMIN",
          "X-Backoffice-Owner-Units": "IT",
        },
      });
      const data = await res.json();
      return (data.items || [])[0]?.conversationId || null;
    });
    if (conversationId) {
      await page.goto(
        `${BASE}/?buShell=1#/knowledge_ops/conversations?conversationId=${encodeURIComponent(conversationId)}`,
        { waitUntil: "networkidle0", timeout: 45000 },
      );
      await page.waitForSelector(".bu-conversation-detail, .bu-case-page", { timeout: 20000 });
    }

    // Task 5: 營運分析 → 問題分析（期間保留）→ 離開後不得被 stale issues 覆寫
    await page.goto(`${BASE}/?buShell=1#/platform/overview?preset=7d`, {
      waitUntil: "networkidle0",
      timeout: 45000,
    });
    await page.waitForSelector(".bu-quality-tabs", { timeout: 20000 });
    const tabLabels = await page.$$eval(".bu-quality-tabs button", (nodes) =>
      nodes.map((n) => n.textContent.trim()),
    );
    assert.ok(tabLabels.includes("問題分析"));
    assert.ok(tabLabels.includes("內容成效"));
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll(".bu-quality-tabs button")].find((b) =>
        b.textContent.includes("問題分析"),
      );
      btn?.click();
    });
    await page.waitForFunction(() => location.hash.includes("issues"), { timeout: 20000 });
    assert.ok(locationHashHasPreset(await page.evaluate(() => location.hash)));
    await page.waitForFunction(
      () => /問題分析|需改善/.test(document.getElementById("app")?.innerText || ""),
      { timeout: 20000 },
    );

    await page.evaluate(() => {
      const link = [...document.querySelectorAll("#nav a")].find((a) =>
        a.textContent.includes("品質驗收"),
      );
      link?.click();
    });
    await page.waitForFunction(() => location.hash.includes("evaluations"), { timeout: 15000 });
    // Give late issues renders a chance to race; content must stay on evaluations.
    await new Promise((r) => setTimeout(r, 1500));
    const evalSnapshot = await page.evaluate(() => ({
      heading: document.querySelector("#app h2")?.textContent || "",
      body: document.getElementById("app")?.innerText || "",
    }));
    assert.ok(
      /品質驗收|驗收/.test(evalSnapshot.heading) ||
        /品質驗收|驗收題庫|Golden|執行驗收|驗收結果/.test(evalSnapshot.body),
      `evaluations content overwritten after leave issues; heading=${evalSnapshot.heading}; body=${evalSnapshot.body.slice(0, 200)}`,
    );
    assert.ok(
      !/問題分析/.test(evalSnapshot.heading),
      "stale issues heading must not replace evaluations",
    );

    await page.evaluate(() => {
      const link = [...document.querySelectorAll("#nav a")].find((a) =>
        a.textContent.includes("服務狀態"),
      );
      link?.click();
    });
    await page.waitForFunction(
      () =>
        Boolean(document.querySelector(".bu-system-header")) ||
        /系統健康|服務狀態/.test(document.getElementById("app")?.innerText || ""),
      { timeout: 15000 },
    );

    const fatal = errors.filter((msg) => !/ResizeObserver|favicon/i.test(msg));
    assert.equal(fatal.length, 0, `page errors: ${fatal.join(" | ")}`);
  } finally {
    if (browser) await browser.close();
  }
});

test("BU shell live E2E: case → 修正 FAQ returnTo hop", async (t) => {
  let healthy = false;
  try {
    const res = await fetch(`${BASE}/healthz`);
    healthy = res.ok;
  } catch {
    healthy = false;
  }
  if (!healthy) {
    t.skip(`backoffice not reachable at ${BASE}`);
    return;
  }

  let browser;
  try {
    const puppeteer = await loadPuppeteer();
    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: "new",
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
  } catch (error) {
    t.skip(`Chrome/puppeteer unavailable: ${error.message}`);
    return;
  }

  try {
    const { page, errors } = await openBuPage(browser, "#/knowledge_ops/quality?tab=cases");
    const caseId = await page.evaluate(async () => {
      const res = await fetch("/api/quality-cases?limit=5", {
        headers: {
          "X-Backoffice-User-Id": "e2e.admin",
          "X-Backoffice-Role": "SYSTEM_ADMIN",
          "X-Backoffice-Owner-Units": "IT",
        },
      });
      const data = await res.json();
      const items = data.items || data.cases || [];
      return items[0]?.case_id || null;
    });
    if (!caseId) {
      t.skip("no quality cases available for returnTo hop");
      return;
    }

    await page.goto(
      `${BASE}/?buShell=1#/knowledge_ops/quality?caseId=${encodeURIComponent(caseId)}&tab=cases`,
      { waitUntil: "networkidle0", timeout: 45000 },
    );
    await page.waitForSelector(".bu-case-page, .bu-case-crumb", { timeout: 20000 });

    const faqHref = await page.evaluate(() => {
      const link = [...document.querySelectorAll("a")].find((a) =>
        (a.textContent || "").includes("修正 FAQ"),
      );
      return link?.getAttribute("href") || null;
    });
    assert.ok(faqHref, "修正 FAQ action missing on case detail");
    assert.ok(/contentLists/.test(faqHref), `expected contentLists hop, got ${faqHref}`);
    assert.ok(/returnTo=/.test(faqHref), `expected returnTo on FAQ hop, got ${faqHref}`);

    await page.goto(`${BASE}/?buShell=1${faqHref.startsWith("#") ? faqHref : `#${faqHref}`}`, {
      waitUntil: "networkidle0",
      timeout: 45000,
    });
    await page.waitForFunction(
      () =>
        /知識內容|FAQ/.test(document.querySelector("#app h2")?.textContent || "") ||
        Boolean(document.querySelector(".bu-return-bar")),
      { timeout: 20000 },
    );
    assert.ok(
      /returnTo=/.test(await page.evaluate(() => location.hash)),
      "returnTo must remain in hash on contentLists",
    );
    assert.ok(
      await page.$(".bu-return-bar a"),
      "return bar missing on contentLists after FAQ hop",
    );

    await page.click(".bu-return-bar a");
    await page.waitForSelector(".bu-case-page", { timeout: 25000 });
    assert.ok(
      await page.evaluate((id) => location.hash.includes("quality") && location.hash.includes(id), caseId),
      "returning from content must restore the same quality case",
    );

    const examplesHref = await page.evaluate(() => {
      const link = [...document.querySelectorAll("a")].find((a) =>
        (a.textContent || "").includes("案例驗證"),
      );
      return link?.getAttribute("href") || null;
    });
    assert.ok(examplesHref, "案例驗證 action missing on case detail");
    assert.ok(/returnTo=/.test(examplesHref), `expected returnTo on examples hop, got ${examplesHref}`);

    await page.goto(`${BASE}/?buShell=1${examplesHref.startsWith("#") ? examplesHref : `#${examplesHref}`}`, {
      waitUntil: "networkidle0",
      timeout: 45000,
    });
    await page.waitForFunction(
      () => /品質案例集/.test(document.querySelector("#app")?.innerText || "") &&
        Boolean([...document.querySelectorAll("button")].find((button) =>
          (button.textContent || "").includes("返回改善案件"),
        )),
      { timeout: 20000 },
    );
    await page.evaluate(() => {
      const back = [...document.querySelectorAll("button")].find((button) =>
        (button.textContent || "").includes("返回改善案件"),
      );
      back?.click();
    });
    await page.waitForFunction(
      (id) => location.hash.includes("quality") &&
        (location.hash.includes(id) || Boolean(document.querySelector(".bu-case-page"))),
      { timeout: 25000 },
      caseId,
    );
    await page.waitForFunction(
      () => /驗收追蹤/.test(document.getElementById("app")?.innerText || ""),
      { timeout: 20000 },
    );

    const evaluationTracking = await page.$eval("#app", (root) => ({
      body: root.innerText,
      goldenHref: [...root.querySelectorAll("a")].find((link) =>
        (link.textContent || "").includes("Golden 驗收"),
      )?.getAttribute("href") || null,
    }));
    assert.match(evaluationTracking.body, /驗收追蹤/);
    assert.ok(evaluationTracking.goldenHref, "Golden 驗收 action missing on case detail");
    assert.match(evaluationTracking.goldenHref, /evaluations/);
    assert.match(evaluationTracking.goldenHref, /tab=runs/);

    await page.goto(
      `${BASE}/?buShell=1${evaluationTracking.goldenHref.startsWith("#") ? evaluationTracking.goldenHref : `#${evaluationTracking.goldenHref}`}`,
      { waitUntil: "networkidle0", timeout: 45000 },
    );
    await page.waitForFunction(
      () => /執行驗收/.test(document.getElementById("app")?.innerText || "") &&
        /記錄到改善案件/.test(document.getElementById("app")?.innerText || ""),
      { timeout: 20000 },
    );
    const runBackClicked = await page.evaluate(() => {
      const back = [...document.querySelectorAll("button")].find((button) =>
        (button.textContent || "").includes("返回改善案件"),
      );
      back?.click();
      return Boolean(back);
    });
    assert.equal(runBackClicked, true, "run page must expose a return-to-case action");
    await page.waitForFunction(
      (id) => location.hash.includes("quality") && location.hash.includes(id),
      { timeout: 25000 },
      caseId,
    );

    const fatal = errors.filter((msg) => !/ResizeObserver|favicon/i.test(msg));
    assert.equal(fatal.length, 0, `page errors: ${fatal.join(" | ")}`);
  } finally {
    if (browser) await browser.close();
  }
});

test("BU shell live E2E: document detail separates publish, index, and Agent use", async (t) => {
  let healthy = false;
  try {
    const res = await fetch(`${BASE}/healthz`);
    healthy = res.ok;
  } catch {
    healthy = false;
  }
  if (!healthy) {
    t.skip(`backoffice not reachable at ${BASE}`);
    return;
  }

  let browser;
  try {
    const puppeteer = await loadPuppeteer();
    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: "new",
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
  } catch (error) {
    t.skip(`Chrome/puppeteer unavailable: ${error.message}`);
    return;
  }

  try {
    const { page, errors } = await openBuPage(
      browser,
      "#/knowledge_ops/knowledgeDocument?documentId=doc-vpn-jumpbox-connection-e-adc7a424ee",
    );
    await page.waitForSelector(".lifecycle-strip", { timeout: 20000 });
    const state = await page.$eval("#app", (root) => ({
      stages: [...root.querySelectorAll(".lifecycle-strip__item")].map((node) => node.textContent.trim()),
      evidence: root.querySelector("h3")?.textContent || "",
      body: root.innerText,
    }));
    assert.equal(state.stages.length, 5, "document lifecycle must expose index as its own stage");
    assert.ok(state.stages.includes("已完成索引"), `index evidence missing: ${state.stages.join(" / ")}`);
    assert.ok(state.stages.includes("Agent 已使用新版"), `Agent evidence missing: ${state.stages.join(" / ")}`);
    assert.match(state.body, /目前 active release/);
    assert.match(state.body, /ver-doc-vpn-jumpbox-connection-e-adc7a424ee-1/);
    const fatal = errors.filter((msg) => !/ResizeObserver|favicon/i.test(msg));
    assert.equal(fatal.length, 0, `page errors: ${fatal.join(" | ")}`);
  } finally {
    if (browser) await browser.close();
  }
});

test("BU shell live E2E: conversation detail failure preserves filters", async (t) => {
  let healthy = false;
  try {
    const res = await fetch(`${BASE}/healthz`);
    healthy = res.ok;
  } catch {
    healthy = false;
  }
  if (!healthy) {
    t.skip(`backoffice not reachable at ${BASE}`);
    return;
  }

  let browser;
  try {
    const puppeteer = await loadPuppeteer();
    browser = await puppeteer.launch({
      executablePath: CHROME,
      headless: "new",
      args: ["--no-sandbox", "--disable-dev-shm-usage"],
    });
  } catch (error) {
    t.skip(`Chrome/puppeteer unavailable: ${error.message}`);
    return;
  }

  try {
    const { page, errors } = await openBuPage(browser, "#/knowledge_ops/conversations");
    const conversationId = await page.evaluate(async () => {
      const res = await fetch("/api/conversations?limit=1", {
        headers: {
          "X-Backoffice-User-Id": "e2e.admin",
          "X-Backoffice-Role": "SYSTEM_ADMIN",
          "X-Backoffice-Owner-Units": "IT",
        },
      });
      const data = await res.json();
      return data.items?.[0]?.conversationId || null;
    });
    if (!conversationId) {
      t.skip("no conversation available for detail failure injection");
      return;
    }

    await page.setRequestInterception(true);
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname === `/api/conversations/${conversationId}`) {
        void request.abort();
      } else {
        void request.continue();
      }
    });
    await page.goto(
      `${BASE}/?buShell=1#/knowledge_ops/conversations?conversationId=${encodeURIComponent(conversationId)}&query=VPN&preset=7d`,
      { waitUntil: "networkidle0", timeout: 45000 },
    ).catch(() => {});
    await page.waitForFunction(
      () => /不是「查無資料」/.test(document.getElementById("app")?.innerText || ""),
      { timeout: 20000 },
    );
    assert.equal(
      await page.$eval("#conversation-query-filter", (input) => input.value),
      "VPN",
      "detail failure must keep the keyword filter",
    );
    assert.ok(
      await page.$$eval("button", (nodes) =>
        nodes.some((node) => (node.textContent || "").includes("重試這則對話")),
      ),
      "detail failure must offer a scoped retry",
    );
    const fatal = errors.filter((msg) => !/ResizeObserver|favicon|ERR_FAILED/i.test(msg));
    assert.equal(fatal.length, 0, `page errors: ${fatal.join(" | ")}`);
  } finally {
    if (browser) await browser.close();
  }
});

function locationHashHasPreset(hash) {
  return /preset=7d/.test(hash) || /preset=/.test(hash);
}
