import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const appSource = readFileSync(join(root, "src/app/App.tsx"), "utf8");
const viteSource = readFileSync(join(root, "vite.config.ts"), "utf8");

test("console App registers v2 work and health routes", () => {
  assert.match(appSource, /basename=["']\/console-v2["']/);
  assert.match(appSource, /path=["']\/work["']/);
  assert.match(appSource, /path=["']\/operations\/health["']/);
  assert.match(appSource, /path=["']\/improvements\/cases["']/);
  assert.match(appSource, /path=["']\/ai\/evaluations["']/);
});

test("console App keeps Refine shell wiring", () => {
  assert.match(appSource, /<Refine/);
  assert.match(appSource, /authProvider/);
  assert.match(appSource, /accessControlProvider/);
  assert.match(appSource, /toRefineResources/);
  assert.match(appSource, /Authenticated/);
});

test("console App lazy-loads feature routes under Suspense", () => {
  assert.match(appSource, /React\.lazy\(/);
  assert.match(appSource, /<Suspense\b/);
  assert.match(appSource, /features\/dashboard\/pages\/DashboardPage/);
  assert.match(appSource, /features\/triage\/pages\/TriagePage/);
  assert.match(appSource, /features\/governance\/pages\/GovernancePages/);
  assert.match(appSource, /features\/operations\/pages\/OpsPages/);
  assert.doesNotMatch(appSource, /import\s+\{\s*DashboardPage\s*\}/);
  assert.doesNotMatch(appSource, /import\s+\{\s*TriagePage\s*\}/);
});

test("vite build splits vendor and feature chunks", () => {
  assert.match(viteSource, /manualChunks/);
  assert.match(viteSource, /vendor-antd/);
  assert.match(viteSource, /vendor-react/);
});
