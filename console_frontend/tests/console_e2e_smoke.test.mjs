/**
 * Optional live smoke for React Console when a backoffice is reachable.
 * Skips by default so unit CI stays offline. Enable with:
 *   CONSOLE_E2E_BASE_URL=http://127.0.0.1:8092 node --test tests/console_e2e_smoke.test.mjs
 */
import assert from "node:assert/strict";
import test from "node:test";

const baseUrl = String(process.env.CONSOLE_E2E_BASE_URL || "").replace(/\/$/, "");

function roleHeaders(role, userId = `${role.toLowerCase()}_e2e`) {
  return {
    "Content-Type": "application/json",
    "X-Backoffice-User-Id": userId,
    "X-Backoffice-User-Name": role,
    "X-Backoffice-Role": role,
    "X-Backoffice-Owner-Units": "IT Service Desk",
    "X-Backoffice-Tenant-Id": "default",
    "X-Backoffice-Groups": "grp_public",
  };
}

async function fetchAs(path, { role = "SYSTEM_ADMIN", method = "GET", body } = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: roleHeaders(role),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = null;
  }
  return { status: response.status, text, json };
}

test("console e2e smoke (optional live)", async (t) => {
  if (!baseUrl) {
    t.skip("Set CONSOLE_E2E_BASE_URL to run live console smoke");
    return;
  }

  const health = await fetchAs("/api/health/summary");
  assert.equal(health.status, 200, "health summary should be reachable");
  assert.match(health.text, /overallStatus|status|components|probes/i);

  const shell = await fetchAs("/console-v2/");
  assert.equal(shell.status, 200, "console-v2 shell should be served");
  assert.match(shell.text, /console-v2|root|index/i);

  const dashboardShell = await fetchAs("/console-v2/dashboard");
  assert.equal(dashboardShell.status, 200);
  const triageShell = await fetchAs("/console-v2/triage");
  assert.equal(triageShell.status, 200);

  const capabilities = await fetchAs("/api/capabilities");
  assert.equal(capabilities.status, 200);
  assert.match(capabilities.text, /capabilities|SYSTEM_ADMIN|userId/i);

  const conversations = await fetchAs("/api/console/workbench/conversations");
  assert.equal(conversations.status, 200);
  assert.ok(Array.isArray(conversations.json), "conversations should return an array");

  const faqQuestion = `e2e-smoke-${Date.now()}`;
  const faqs = await fetchAs("/api/console/workbench/faqs", {
    method: "POST",
    body: {
      question: faqQuestion,
      answer: "live smoke answer",
      category: "網路通訊",
    },
  });
  assert.ok([200, 201].includes(faqs.status), `FAQ write should persist, got ${faqs.status}`);
  assert.ok(faqs.json?.id || faqs.json?.faq_id || faqs.json?.faq?.id, "FAQ response should include an id");

  const listed = await fetchAs("/api/console/workbench/faqs");
  assert.equal(listed.status, 200);
  const faqList = Array.isArray(listed.json) ? listed.json : listed.json?.items || [];
  assert.ok(
    faqList.some((item) => JSON.stringify(item).includes(faqQuestion)),
    "saved FAQ should be readable from the FAQ list",
  );
});

test("console e2e VIEWER 403 write does not invalidate session", async (t) => {
  if (!baseUrl) {
    t.skip("Set CONSOLE_E2E_BASE_URL to run live console smoke");
    return;
  }

  const forbidden = await fetchAs("/api/console/workbench/faqs", {
    role: "VIEWER",
    method: "POST",
    body: {
      question: `viewer-forbidden-${Date.now()}`,
      answer: "should fail",
      category: "網路通訊",
    },
  });
  assert.equal(forbidden.status, 403, "VIEWER FAQ write must be forbidden");

  const stillAuthed = await fetchAs("/api/capabilities", { role: "VIEWER" });
  assert.equal(stillAuthed.status, 200, "403 must not invalidate VIEWER session");
  assert.equal(stillAuthed.json?.role, "VIEWER");
  assert.ok(Array.isArray(stillAuthed.json?.capabilities));

  const triageRead = await fetchAs("/api/console/workbench/conversations", {
    role: "VIEWER",
  });
  assert.equal(triageRead.status, 200, "VIEWER can still read conversations after 403");
});

test("console e2e auth config exposes mode and headerAuthAllowed", async (t) => {
  if (!baseUrl) {
    t.skip("Set CONSOLE_E2E_BASE_URL to run live console smoke");
    return;
  }

  const config = await fetchAs("/api/auth/config");
  assert.equal(config.status, 200);
  assert.ok(
    config.json?.authMode || config.json?.auth_mode,
    "authMode must be present for deploy checks",
  );
  assert.ok(
    "headerAuthAllowed" in (config.json || {}) ||
      "header_auth_allowed" in (config.json || {}),
    "headerAuthAllowed must be present for deploy checks",
  );
});
