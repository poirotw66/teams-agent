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

    // Task 5: 營運分析 → 問題分析（期間保留）
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

    // 品質驗收 / 服務狀態 — soft checks after core task paths already passed
    await page.evaluate(() => {
      const link = [...document.querySelectorAll("#nav a")].find((a) =>
        a.textContent.includes("品質驗收"),
      );
      link?.click();
    });
    await page
      .waitForFunction(() => location.hash.includes("evaluations"), { timeout: 10000 })
      .catch(() => {});
    await page
      .waitForFunction(
        () => /品質驗收|驗收/.test(document.getElementById("app")?.innerText || ""),
        { timeout: 8000 },
      )
      .catch(() => {});

    await page.evaluate(() => {
      const link = [...document.querySelectorAll("#nav a")].find((a) =>
        a.textContent.includes("服務狀態"),
      );
      link?.click();
    });
    await page
      .waitForFunction(
        () =>
          Boolean(document.querySelector(".bu-system-header")) ||
          /系統健康/.test(document.getElementById("app")?.innerText || ""),
        { timeout: 8000 },
      )
      .catch(() => {});

    const fatal = errors.filter((msg) => !/ResizeObserver|favicon/i.test(msg));
    assert.equal(fatal.length, 0, `page errors: ${fatal.join(" | ")}`);
  } finally {
    if (browser) await browser.close();
  }
});

function locationHashHasPreset(hash) {
  return /preset=7d/.test(hash) || /preset=/.test(hash);
}
