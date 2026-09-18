import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const appSource = readFileSync(join(root, "src/app/App.tsx"), "utf8");

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
});
