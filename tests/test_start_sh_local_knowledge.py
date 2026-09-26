"""Static contracts for local start.sh knowledge + Gemini backend wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_SH = ROOT / "start.sh"


def _script() -> str:
    return START_SH.read_text(encoding="utf-8")


def test_developer_api_does_not_follow_cloud_vertex_pointer() -> None:
    script = _script()

    assert 'source "${GCS_KNOWLEDGE_OVERRIDE}"' in script
    assert (
        'GEMINI_API_BACKEND_VALUE}" == "DEVELOPER_API" && '
        '"${KNOWLEDGE_RELEASE_SELECTION_MODE:-}" == "FOLLOW_CLOUD"'
    ) in script
    assert "KNOWLEDGE_RELEASE_SELECTION_MODE=LOCAL_SANDBOX" in script
    assert "FOLLOW_CLOUD → LOCAL_SANDBOX" in script
    assert "RAG_ASSET_GCS_BUCKET" in script


def test_vertex_local_start_still_exports_follow_cloud_keys() -> None:
    script = _script()

    assert "KNOWLEDGE_RELEASE_SELECTION_MODE" in script
    assert 'GEMINI_API_BACKEND_VALUE}" == "VERTEX_AI"' in script
