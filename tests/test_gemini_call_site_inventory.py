"""Static inventory: Gemini client construction stays behind the dual-backend contract."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    REPO_ROOT / "agent_service" / "src",
    REPO_ROOT / "scripts",
    REPO_ROOT / "src",
    REPO_ROOT / "services" / "pdf_converter",
)
SKIP_DIR_NAMES = {
    ".venv",
    "node_modules",
    "__pycache__",
    "upstream",
    "app",
}

INIT_CHAT_ALLOWED = {
    REPO_ROOT / "agent_service" / "src" / "agent_service" / "graph.py",
}
INIT_EMBEDDINGS_ALLOWED = {
    REPO_ROOT / "agent_service" / "src" / "knowledge_core" / "gemini_clients.py",
}
GENAI_CLIENT_ALLOWED = {
    REPO_ROOT / "agent_service" / "src" / "agent_service" / "gemini_file_search.py",
    REPO_ROOT / "agent_service" / "src" / "knowledge_portal" / "file_search_release.py",
    REPO_ROOT / "scripts" / "acl_verification.py",
    REPO_ROOT / "scripts" / "gemini_file_search_spike.py",
    REPO_ROOT / "scripts" / "migrate_legacy_file_search_acl.py",
    REPO_ROOT / "services" / "pdf_converter" / "patches" / "gemini_backend_client.py",
    REPO_ROOT / "services" / "pdf_converter" / "scripts" / "apply_gemini_backend_patch.py",
}

_INIT_CHAT = re.compile(r"\binit_chat_model\s*\(")
_INIT_EMBEDDINGS = re.compile(r"\binit_embeddings\s*\(")
_GENAI_CLIENT = re.compile(r"genai\.Client\s*\(")


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            files.append(path)
    return files


def test_init_chat_model_only_used_by_build_chat_model() -> None:
    found = [path for path in _iter_python_files() if _INIT_CHAT.search(path.read_text(encoding="utf-8"))]
    assert set(found) == INIT_CHAT_ALLOWED
    text = next(iter(INIT_CHAT_ALLOWED)).read_text(encoding="utf-8")
    assert "chat_model_init_kwargs" in text


def test_init_embeddings_only_used_for_non_gemini_providers() -> None:
    found = [
        path for path in _iter_python_files() if _INIT_EMBEDDINGS.search(path.read_text(encoding="utf-8"))
    ]
    assert set(found) == INIT_EMBEDDINGS_ALLOWED
    text = next(iter(INIT_EMBEDDINGS_ALLOWED)).read_text(encoding="utf-8")
    assert "is_google_genai_model" in text


def test_genai_client_call_sites_are_mode_constrained() -> None:
    found = [path for path in _iter_python_files() if _GENAI_CLIENT.search(path.read_text(encoding="utf-8"))]
    assert set(found) <= GENAI_CLIENT_ALLOWED
    for path in found:
        if path.name == "apply_gemini_backend_patch.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert (
            "require_developer_api_for_file_search" in text
            or "build_genai_client" in text
            or "VERTEX_AI refuses" in text
        )
