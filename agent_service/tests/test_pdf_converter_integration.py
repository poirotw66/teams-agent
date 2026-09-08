"""Tests for PDF converter client and Portal async/sync import routing."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from knowledge_portal.api import create_app
from knowledge_portal.pdf_convert_jobs import should_convert_async
from knowledge_portal.pdf_converter_client import PdfConverterClient, _parse_json_result
from knowledge_portal.settings import PortalSettings
from pdf_test_helpers import build_text_pdf_bytes


def portal_headers(
    user_id: str = "contributor.demo",
    name: str = "Contributor",
    role: str = "CONTRIBUTOR",
) -> dict[str, str]:
    return {
        "X-Portal-User-Id": user_id,
        "X-Portal-User-Name": name,
        "X-Portal-Role": role,
        "X-Portal-Owner-Units": "IT Service Desk",
    }


def test_should_convert_async_thresholds() -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "pdf_sync_max_bytes", 1000)
    object.__setattr__(settings, "pdf_sync_max_pages", 2)
    assert should_convert_async(settings, byte_size=1001, page_count=1) is True
    assert should_convert_async(settings, byte_size=10, page_count=3) is True
    assert should_convert_async(settings, byte_size=10, page_count=1) is False
    assert should_convert_async(settings, byte_size=10, page_count=99, force="sync") is False
    assert should_convert_async(settings, byte_size=1, page_count=1, force="async") is True


def test_parse_json_converter_result() -> None:
    result = _parse_json_result(
        {
            "markdown": "# Hello\n",
            "page_count": 2,
            "warnings": ["ok"],
            "assets": [{"filename": "p01.png", "content_base64": "aGVsbG8="}],
        }
    )
    assert result.markdown.startswith("# Hello")
    assert result.page_count == 2
    assert result.assets[0].filename == "p01.png"
    assert result.assets[0].content == b"hello"


@pytest.mark.asyncio
async def test_pdf_converter_client_posts_multipart(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = ""

        def json(self):
            return {"markdown": "# From converter\n", "page_count": 1, "warnings": [], "assets": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, files=None, data=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["files"] = files
            captured["data"] = data
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = PdfConverterClient(base_url="http://converter.local", token="secret")
    result = await client.convert_pdf(b"%PDF-demo", filename="guide.pdf")
    assert result.markdown.startswith("# From converter")
    assert captured["url"] == "http://converter.local/api/v1/convert-pdf"
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_import_pdf_sync_uses_converter_when_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "pdf_converter_url", "http://converter.local")
    object.__setattr__(settings, "pdf_converter_engine", "gemini_vision")
    object.__setattr__(settings, "pdf_jobs_dir", tmp_path / "pdf-jobs")
    object.__setattr__(settings, "pdf_sync_max_pages", 50)
    object.__setattr__(settings, "pdf_sync_max_bytes", 5_000_000)

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = ""

        def json(self):
            return {
                "markdown": "# Converter VPN\n\nUse MFA.\n",
                "page_count": 1,
                "warnings": ["vision"],
                "assets": [],
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    client = TestClient(create_app(settings))
    response = client.post(
        "/api/documents/import-pdf?async_mode=sync",
        files={"file": ("vpn.pdf", build_text_pdf_bytes("ignored body"), "application/pdf")},
        headers=portal_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "sync"
    assert body["conversion_mode"] == "converter"
    assert body["conversion_engine"] == "gemini_vision"
    assert "Converter VPN" in body["markdown_content"]


def test_import_pdf_async_job_completes(tmp_path: Path) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "service_token", "")
    object.__setattr__(settings, "repository_mode", "MEMORY")
    object.__setattr__(settings, "pdf_converter_url", None)
    object.__setattr__(settings, "pdf_jobs_dir", tmp_path / "pdf-jobs")
    object.__setattr__(settings, "pdf_sync_max_pages", 1)
    object.__setattr__(settings, "pdf_sync_max_bytes", 10)

    client = TestClient(create_app(settings))
    # Force async regardless of size
    response = client.post(
        "/api/documents/import-pdf?async_mode=async",
        files={"file": ("vpn.pdf", build_text_pdf_bytes("VPN login troubleshooting steps"), "application/pdf")},
        headers=portal_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "async"
    job_id = body["jobId"]

    # BackgroundTasks run after response in TestClient
    status = None
    for _ in range(20):
        status = client.get(f"/api/documents/pdf-jobs/{job_id}", headers=portal_headers())
        assert status.status_code == 200
        if status.json()["status"] in {"COMPLETED", "FAILED"}:
            break
    assert status is not None
    payload = status.json()
    assert payload["status"] == "COMPLETED"
    assert "VPN" in payload["result"]["markdown_content"]
