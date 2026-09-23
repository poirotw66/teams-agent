/**
 * Release-gate checks for console architecture acceptance items that are
 * configuration/deploy contracts rather than React component behavior.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const root = join(dirname(fileURLToPath(import.meta.url)), "../..");

test("deploy-backoffice defaults auth mode to ENTRA", () => {
  const script = readFileSync(join(root, "deploy/deploy-backoffice.sh"), "utf8");
  assert.match(
    script,
    /BACKOFFICE_AUTH_MODE="\$\{AI_OPS_BACKOFFICE_AUTH_MODE:-\$\{AUTH_MODE:-ENTRA\}\}"/,
  );
  assert.match(script, /AI_OPS_BACKOFFICE_AUTH_MODE=\$\{BACKOFFICE_AUTH_MODE\}/);
  assert.match(script, /AI_OPS_ENTRA_TENANT_ID=/);
  assert.match(script, /AI_OPS_ENTRA_CLIENT_ID=/);
});

test("production config validator requires ENTRA and blocks file stores", () => {
  const validator = readFileSync(
    join(root, "agent_service/src/ai_ops_backoffice/config_validator.py"),
    "utf8",
  );
  assert.match(validator, /auth_mode must be ENTRA in production/);
  assert.match(validator, /ENTRA_TENANT_ID and ENTRA_CLIENT_ID/);
  assert.match(validator, /ops_store_mode must not be/);
});

test("header auth is denied outside controlled environments", () => {
  const auth = readFileSync(
    join(root, "agent_service/src/ai_ops_backoffice/auth.py"),
    "utf8",
  );
  assert.match(auth, /def header_auth_allowed/);
  assert.match(auth, /dev", "test", "poc"/);
  assert.match(auth, /AI_OPS_BACKOFFICE_ALLOW_HEADER_AUTH/);
});

test("frontend session default admin header remains explicit for local-only use", () => {
  const session = readFileSync(
    join(root, "console_frontend/src/shared/auth/session.ts"),
    "utf8",
  );
  assert.match(session, /SYSTEM_ADMIN/);
  assert.match(session, /bearerToken/);
  // Deploy gate relies on backend denying these headers outside DEV/TEST/POC.
});
