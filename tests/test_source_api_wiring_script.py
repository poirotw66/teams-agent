"""Static contracts for citation Source API deploy wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "deploy" / "lib" / "source-api-wiring.sh"
DEPLOY_GCP = ROOT / "deploy" / "deploy-gcp.sh"
DEPLOY_BACKOFFICE = ROOT / "deploy" / "deploy-backoffice.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deploy_scripts_source_shared_wiring_helper() -> None:
    helper_source = 'source "${PROJECT_DIR}/deploy/lib/source-api-wiring.sh"'
    assert helper_source in _read(DEPLOY_GCP)
    assert helper_source in _read(DEPLOY_BACKOFFICE)


def test_helper_creates_missing_secrets_without_rotation() -> None:
    helper = _read(HELPER)
    assert "ensure_generated_secret" in helper
    assert "openssl rand -hex" in helper
    assert "gcloud secrets versions add" not in helper
    assert "teams-ai-ops-backoffice-token" in helper
    assert "teams-agent-knowledge-delegation-secret" in helper


def test_helper_preserves_runtime_on_image_update() -> None:
    helper = _read(HELPER)
    assert "--update-env-vars" in helper
    assert "--update-secrets" in helper
    assert "不使用 --set-env-vars" in helper
    assert "cloud_run_service_exists" in helper


def test_helper_warns_when_backoffice_is_missing() -> None:
    helper = _read(HELPER)
    assert "略過 Adapter Source API 接線" in helper
    assert "deploy-backoffice.sh" in helper
    assert "SOURCE_API_BASE_URL" in helper
    assert "run.invoker" in helper


def test_helper_wires_adapter_source_api_keys() -> None:
    helper = _read(HELPER)
    assert "SOURCE_API_TOKEN=" in helper
    assert "SOURCE_DELEGATION_SECRET=" in helper
    assert "AI_OPS_BACKOFFICE_TOKEN=" in helper
    assert "AI_OPS_SOURCE_DELEGATION_SECRET=" in helper
    assert "TEAMS_CITATION_OPEN_ACTIONS=true" in helper


def test_deploy_gcp_keeps_citation_flag_and_rewires_when_possible() -> None:
    script = _read(DEPLOY_GCP)
    assert "TEAMS_CITATION_OPEN_ACTIONS=true" in script
    assert "ensure_source_api_secrets" in script
    assert "ensure_source_api_wiring" in script
    assert "deploy_cloud_run_preserving_runtime" in script
    assert script.count("deploy_cloud_run_preserving_runtime") >= 2
    assert "--set-env-vars=" not in script.split("部署 public Teams Adapter", 1)[1]


def test_deploy_gcp_agent_uses_preserving_runtime_without_knowledge_set_env() -> None:
    script = _read(DEPLOY_GCP)
    agent_only = script.split("部署 private LangGraph Agent", 1)[1].split(
        "部署 public Teams Adapter", 1
    )[0]
    assert "deploy_cloud_run_preserving_runtime" in agent_only
    assert "--set-env-vars=" not in agent_only
    assert "preserve_live_agent_knowledge_env" in script
    assert "KNOWLEDGE_SERVICE_MODE=HYBRID" in agent_only


def test_deploy_backoffice_uses_remote_portal_without_locking_writes() -> None:
    script = _read(DEPLOY_BACKOFFICE)
    assert "AI_OPS_KNOWLEDGE_IN_PROCESS=false" in script
    assert "AI_OPS_CONSOLE_SURFACE=CLOUD" in script
    assert "AI_OPS_KNOWLEDGE_WORKSPACE_MODE=LOCAL_SANDBOX" in script
    assert "AI_OPS_KNOWLEDGE_WORKSPACE_MODE=CLOUD_FORMAL" not in script
    assert "KNOWLEDGE_PORTAL_PUBLIC_URL=" in script
    assert "KNOWLEDGE_PORTAL_INTERNAL_URL=" in script
    assert "KNOWLEDGE_PORTAL_UPSTREAM_AUTH_MODE=GOOGLE_ID_TOKEN" in script
    assert "不會假裝本機 in-process Portal" in script
    assert "wire_backoffice_remote_portal" in script


def test_deploy_backoffice_always_rewires_adapter() -> None:
    script = _read(DEPLOY_BACKOFFICE)
    assert "ensure_source_api_secrets" in script
    assert "ensure_source_api_wiring" in script
    assert "AI_OPS_BACKOFFICE_TOKEN=${BACKOFFICE_TOKEN_SECRET}:latest" in script
    assert "AI_OPS_SOURCE_DELEGATION_SECRET=${SOURCE_DELEGATION_SECRET}:latest" in script
    assert "AI_OPS_BACKOFFICE_TOKEN=${BACKOFFICE_TOKEN}," not in script
    assert "deploy_cloud_run_preserving_runtime" in script
