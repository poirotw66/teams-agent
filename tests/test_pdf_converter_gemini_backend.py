"""PDF Vision client factory honors GEMINI_API_BACKEND without key fallback."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APPLY_SCRIPT_DIR = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "pdf_converter"
    / "scripts"
)
sys.path.insert(0, str(APPLY_SCRIPT_DIR))
from apply_gemini_backend_patch import apply_patch

PATCH_DIR = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "pdf_converter"
    / "patches"
)
sys.path.insert(0, str(PATCH_DIR))

from gemini_backend_client import GeminiBackendError, build_genai_client


class FakeGenAI:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def Client(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return kwargs


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GEMINI_API_BACKEND",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "VERTEX_AI_PROJECT",
        "GCP_PROJECT_ID",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEX_AI_PDF_LOCATION",
        "GOOGLE_GENAI_USE_VERTEXAI",
    ):
        monkeypatch.delenv(name, raising=False)


def test_developer_api_uses_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "dev-key")
    genai = FakeGenAI()
    client = build_genai_client(genai)
    assert client == {"api_key": "dev-key"}
    assert "vertexai" not in client


def test_vertex_uses_project_location_and_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-pdf")
    monkeypatch.setenv("VERTEX_AI_PDF_LOCATION", "us")
    genai = FakeGenAI()
    client = build_genai_client(genai, fallback_api_key="leftover-file-key")
    assert client == {
        "vertexai": True,
        "project": "proj-pdf",
        "location": "us",
    }


def test_vertex_maps_single_alias_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("GCP_PROJECT_ID", "alias-proj")
    monkeypatch.setenv("VERTEX_AI_PDF_LOCATION", "us")
    client = build_genai_client(FakeGenAI())
    assert client == {
        "vertexai": True,
        "project": "alias-proj",
        "location": "us",
    }


def test_vertex_refuses_disagreeing_project_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("GCP_PROJECT_ID", "proj-a")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-b")
    monkeypatch.setenv("VERTEX_AI_PDF_LOCATION", "us")
    with pytest.raises(GeminiBackendError, match="disagree"):
        build_genai_client(FakeGenAI())


def test_vertex_rejects_unapproved_global_pdf_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-pdf")
    monkeypatch.setenv("VERTEX_AI_PDF_LOCATION", "global")
    with pytest.raises(GeminiBackendError, match="unapproved P0 placeholder"):
        build_genai_client(FakeGenAI())


def test_vertex_refuses_process_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_BACKEND", "VERTEX_AI")
    monkeypatch.setenv("VERTEX_AI_PROJECT", "proj-pdf")
    monkeypatch.setenv("VERTEX_AI_PDF_LOCATION", "us")
    monkeypatch.setenv("GOOGLE_API_KEY", "injected")
    with pytest.raises(GeminiBackendError, match="refuses"):
        build_genai_client(FakeGenAI())


def test_apply_patch_skips_convert_api_key_gate_for_vertex(tmp_path: Path) -> None:
    parser = tmp_path / "src" / "utils" / "pdf_parser.py"
    api = tmp_path / "app" / "api" / "pdf_convert.py"
    parser.parent.mkdir(parents=True)
    api.parent.mkdir(parents=True)
    parser.write_text(
        "from src.utils.prompts import PROMPT\n"
        "        api_key_to_use = api_key if api_key and api_key.strip() else settings.google_api_key\n"
        '        if not api_key_to_use or not api_key_to_use.strip():\n'
        '            raise ValueError("Google Gemini API key is required. Please provide api_key parameter or set GOOGLE_API_KEY in environment.")\n'
        "        self.gemini_model = resolve_gemini_model(gemini_model)\n"
        "        \n"
        "        if USE_GOOGLE_GENAI_SDK:\n"
        "            self.client = genai.Client(api_key=api_key_to_use.strip())\n",
        encoding="utf-8",
    )
    api.write_text(
        "    if not api_key_to_use:\n"
        "        service_metrics.increment(\"conversion_rejected_total\")\n"
        "        raise HTTPException(\n"
        "            status_code=400,\n"
        "            detail=(\n"
        "                \"API key is required. Please provide your Google Gemini API key in \"\n"
        "                \"the form or set GOOGLE_API_KEY in environment variables.\"\n"
        "            ),\n"
        "        )\n",
        encoding="utf-8",
    )

    apply_patch(tmp_path)

    patched_api = api.read_text(encoding="utf-8")
    assert "resolve_backend() != VERTEX_AI" in patched_api
    assert "teams-agent-gemini-backend-patch" in patched_api
    assert "build_genai_client" in parser.read_text(encoding="utf-8")
    assert (tmp_path / "src" / "utils" / "gemini_backend_client.py").is_file()
