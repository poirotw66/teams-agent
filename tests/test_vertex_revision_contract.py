"""Static contracts: BU Vertex deploys unmount Gemini keys instead of leaving them."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "deploy" / "lib" / "vertex-revision-contract.sh"
DEPLOY_GCP = ROOT / "deploy" / "deploy-gcp.sh"
DEPLOY_PORTAL = ROOT / "deploy" / "deploy-portal.sh"
DEPLOY_BACKOFFICE = ROOT / "deploy" / "deploy-backoffice.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_helper_is_sourced_and_not_executable_as_main() -> None:
    helper = _read(HELPER)
    assert "unmount_developer_api_key_secrets" in helper
    assert "assert_bu_vertex_revision" in helper
    assert "deploy_remove_developer_api_key_secrets_args" in helper
    assert "preserve_live_agent_knowledge_env" in helper
    assert "assert_bu_agent_knowledge_runtime" in helper
    assert "KNOWLEDGE_RELEASE_MODE" in helper
    assert "KNOWLEDGE_ACTIVE_RELEASE_ID" in helper
    assert "GEMINI_FILE_SEARCH_MODEL" in helper
    assert "KNOWLEDGE_SERVICE_MODE" in helper
    assert "GOOGLE_API_KEY" in helper
    assert "GEMINI_API_KEY" in helper
    assert "VERTEX_AI_PROJECT" in helper
    assert "VERTEX_AI_PDF_LOCATION" in helper
    assert "UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER" in helper
    assert 'UNAPPROVED_VERTEX_LOCATION_PLACEHOLDER="global"' in helper
    assert "require_explicit_vertex_project" in helper
    assert "require_approved_vertex_location" in helper
    assert "KNOWLEDGE_PORTAL_GEMINI_FILE_SEARCH_SYNC_ENABLED" in helper
    assert 'source deploy/lib/vertex-revision-contract.sh from a deploy script' in helper
    assert "--remove-secrets=" in helper


def test_bu_deploy_scripts_source_vertex_contract_and_assert() -> None:
    helper_source = 'source "${PROJECT_DIR}/deploy/lib/vertex-revision-contract.sh"'
    for path in (DEPLOY_GCP, DEPLOY_PORTAL, DEPLOY_BACKOFFICE):
        script = _read(path)
        assert helper_source in script
        assert "unmount_developer_api_key_secrets" in script
        assert "assert_bu_vertex_revision" in script
        assert 'GEMINI_API_BACKEND="VERTEX_AI"' in script
        assert "require_explicit_vertex_project" in script
        assert "require_approved_vertex_location" in script
        assert "${VERTEX_AI_PROJECT:-${PROJECT_ID}}" not in script
        assert "${VERTEX_AI_CHAT_LOCATION:-global}" not in script
        assert "${VERTEX_AI_EMBEDDING_LOCATION:-global}" not in script
        assert "${VERTEX_AI_PDF_LOCATION:-global}" not in script


def test_agent_deploy_removes_existing_developer_api_key_mount() -> None:
    script = _read(DEPLOY_GCP)
    wiring = _read(ROOT / "deploy" / "lib" / "source-api-wiring.sh")
    assert "deploy_remove_developer_api_key_secrets_args" in wiring
    assert "deploy_remove_developer_api_key_secrets_args" in _read(HELPER)
    agent_block = script.split("部署 private LangGraph Agent", 1)[1]
    agent_only = agent_block.split("部署 public Teams Adapter", 1)[0]
    assert "deploy_cloud_run_preserving_runtime" in agent_only
    assert "GOOGLE_API_KEY=" not in agent_only
    assert "unmount_developer_api_key_secrets" in agent_only
    assert "assert_bu_vertex_revision" in agent_only


def test_agent_deploy_preserves_live_knowledge_env_on_existing_revision() -> None:
    script = _read(DEPLOY_GCP)
    assert "preserve_live_agent_knowledge_env" in script
    assert "assert_bu_agent_knowledge_runtime" in script
    agent_only = script.split("部署 private LangGraph Agent", 1)[1].split(
        "部署 public Teams Adapter", 1
    )[0]
    assert "AGENT_VERTEX_RUNTIME_ENV_VARS=" in agent_only
    assert "AGENT_FIRST_TIME_KNOWLEDGE_ENV_VARS=" in agent_only
    assert "deploy_cloud_run_preserving_runtime" in agent_only
    assert "--set-env-vars=" not in agent_only
    _, _, rest = agent_only.partition("AGENT_VERTEX_RUNTIME_ENV_VARS=")
    runtime_value, _, after_runtime = rest.partition("AGENT_FIRST_TIME_KNOWLEDGE_ENV_VARS=")
    assert "KNOWLEDGE_SERVICE_MODE=HYBRID" in runtime_value
    assert "GEMINI_API_BACKEND=${GEMINI_API_BACKEND}" in runtime_value
    assert "VERTEX_AI_PROJECT=${VERTEX_AI_PROJECT}" in runtime_value
    assert "KNOWLEDGE_RELEASE_MODE=" not in runtime_value
    assert "KNOWLEDGE_ACTIVE_RELEASE_ID=" not in runtime_value
    assert "GEMINI_FILE_SEARCH_MODEL=" not in runtime_value
    assert "GEMINI_FILE_SEARCH_STORE=" not in runtime_value
    assert "KNOWLEDGE_RELEASE_MODE=${KNOWLEDGE_RELEASE_MODE}" in after_runtime
    assert "KNOWLEDGE_ACTIVE_RELEASE_ID=${KNOWLEDGE_ACTIVE_RELEASE_ID}" in after_runtime
    assert "GEMINI_FILE_SEARCH_MODEL=${GEMINI_FILE_SEARCH_MODEL}" in after_runtime
    assert 'AGENT_ENV_VARS="${AGENT_VERTEX_RUNTIME_ENV_VARS}"' in after_runtime
    assert (
        'AGENT_ENV_VARS="${AGENT_VERTEX_RUNTIME_ENV_VARS},${AGENT_FIRST_TIME_KNOWLEDGE_ENV_VARS}"'
        in after_runtime
    )
    assert "assert_bu_agent_knowledge_runtime" in agent_only


def test_portal_deploy_keeps_vision_and_updates_converter_without_key() -> None:
    script = _read(DEPLOY_PORTAL)
    assert "KNOWLEDGE_PORTAL_PDF_CONVERTER_ENGINE=gemini_vision" in script
    assert "Updating ${CONVERTER_SERVICE} to VERTEX_AI without changing the image" in script
    assert "GEMINI_MODEL=${PDF_CONVERTER_GEMINI_MODEL:-gemini-3.8-flash}" in script
    assert "deploy_remove_developer_api_key_secrets_args" in script
    assert 'converter_update_args+=("${converter_remove_secrets}")' in script
    assert 'portal_deploy_args+=("${portal_remove_secrets}")' in script
    assert 'assert_bu_vertex_revision "${CONVERTER_SERVICE}"' in script
    assert script.count('assert_bu_vertex_revision "${PORTAL_SERVICE}"') >= 2
    assert "KNOWLEDGE_PORTAL_GEMINI_FILE_SEARCH_SYNC_ENABLED=false" in script
    assert "KNOWLEDGE_PORTAL_REQUIRE_FILE_SEARCH_PARITY=false" in script


def test_backoffice_reasserts_vertex_after_portal_wiring() -> None:
    script = _read(DEPLOY_BACKOFFICE)
    wire_block = script.split("wire_backoffice_remote_portal()", 1)[1]
    assert 'assert_bu_vertex_revision "${BACKOFFICE_API_SERVICE}"' in wire_block
    assert 'assert_bu_vertex_revision "${BACKOFFICE_WORKER_SERVICE}"' in wire_block
    assert "unmount_developer_api_key_secrets" in wire_block
