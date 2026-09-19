"""Legacy shell route characterization (quarantined with static/legacy-js)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_ops_backoffice.api import create_app
from ai_ops_backoffice.settings import BackofficeSettings

REPO_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
LEGACY_JS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ai_ops_backoffice"
    / "static"
    / "legacy-js"
)

pytestmark = pytest.mark.skipif(
    not LEGACY_JS.is_dir(),
    reason="legacy-js tree deleted; quarantine tests no longer apply",
)


def _build_settings(tmp_path: Path) -> BackofficeSettings:
    return BackofficeSettings(
        host="127.0.0.1",
        port=8092,
        service_token="",
        auth_mode="HEADER",
        ops_store_mode="MEMORY",
        ops_store_path=tmp_path / "events",
        ops_taxonomy_path=REPO_DATA_DIR / "ops" / "issue_taxonomy_v1.json",
        ops_metrics_path=REPO_DATA_DIR / "ops" / "metrics_definitions_v1.json",
        ops_classification_rules_path=REPO_DATA_DIR / "ops" / "issue_classification_rules.json",
        ops_audit_store_mode="MEMORY",
        knowledge_portal_url="http://127.0.0.1:8091",
        agent_api_url="http://127.0.0.1:8000",
        adapter_api_url="http://127.0.0.1:3978",
        ticket_service_url=None,
        default_owner_unit_id="IT Service Desk",
        entra_tenant_id=None,
        entra_client_id=None,
        governance_store_path=tmp_path / "governance.json",
        quality_store_mode="FILE",
        quality_store_path=tmp_path / "quality.json",
        console_v2_enabled=True,
        legacy_shell_enabled=True,
    )


def test_legacy_shell_serves_legacy_js_bundle(tmp_path: Path) -> None:
    app = create_app(_build_settings(tmp_path))
    client = TestClient(app)

    legacy_res = client.get("/legacy")
    assert legacy_res.status_code == 200
    assert "text/html" in legacy_res.headers.get("content-type", "")
    assert "/static/legacy-js/main.js" in legacy_res.text
    assert "/static/js/main.js" not in legacy_res.text
    assert '"/static/legacy-js/' in legacy_res.text

    legacy_bundle = client.get("/static/legacy-js/main.js")
    assert legacy_bundle.status_code == 200
    assert "from \"./api.js\"" in legacy_bundle.text or 'from "./api.js"' in legacy_bundle.text


def test_legacy_api_js_keeps_entra_modal_without_prompt() -> None:
    api_js = LEGACY_JS / "api.js"
    assert api_js.is_file()
    content = api_js.read_text(encoding="utf-8")
    assert "window.prompt" not in content
    assert "showEntraLoginModal" in content
