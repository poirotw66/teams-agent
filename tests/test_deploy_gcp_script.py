"""Static contracts for the legacy Cloud Run deploy script."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_GCP = ROOT / "deploy" / "deploy-gcp.sh"


def _script() -> str:
    return DEPLOY_GCP.read_text(encoding="utf-8")


def test_cloud_deploy_does_not_require_a_local_hybrid_index() -> None:
    script = _script()

    assert "uv run rag-index" not in script
    assert "缺少 data/index/chunks.json" not in script


def test_cloud_deploy_loads_knowledge_releases_from_gcs() -> None:
    script = _script()

    assert 'KNOWLEDGE_RELEASE_STORE_MODE="${KNOWLEDGE_RELEASE_STORE_MODE:-GCS}"' in script
    assert "KNOWLEDGE_RELEASE_STORE_MODE=GCS，本機 FILE 索引不會打進映像" in script
    assert "KNOWLEDGE_RELEASE_STORE_MODE=${KNOWLEDGE_RELEASE_STORE_MODE}" in script
    assert "KNOWLEDGE_RELEASE_GCS_BUCKET=${KNOWLEDGE_RELEASE_BUCKET}" in script
    assert "KNOWLEDGE_RELEASE_GCS_PREFIX=${KNOWLEDGE_RELEASE_PREFIX}" in script
    assert "KNOWLEDGE_RELEASE_TENANT_ID=${KNOWLEDGE_RELEASE_TENANT_ID}" in script
    assert "KNOWLEDGE_RELEASE_FIRESTORE_PROJECT=${PROJECT_ID}" in script


def test_cloud_agent_follows_cloud_release_explicitly() -> None:
    script = _script()

    assert (
        'KNOWLEDGE_RELEASE_SELECTION_MODE="${KNOWLEDGE_RELEASE_SELECTION_MODE:-FOLLOW_CLOUD}"'
        in script
    )
    assert "KNOWLEDGE_RELEASE_SELECTION_MODE=${KNOWLEDGE_RELEASE_SELECTION_MODE}" in script
    assert "KNOWLEDGE_ACTIVE_RELEASE_ID=${KNOWLEDGE_ACTIVE_RELEASE_ID}" in script
    assert "does not" in script
    assert "infer PINNED" in script


def test_cloud_deploy_grants_agent_read_access_to_release_bucket() -> None:
    script = _script()

    assert "ensure_private_bucket \"${KNOWLEDGE_RELEASE_BUCKET}\"" in script
    assert "serviceAccount:${AGENT_SA}" in script
    assert "roles/storage.objectViewer" in script
    assert "映像不打包 data/index" in script
