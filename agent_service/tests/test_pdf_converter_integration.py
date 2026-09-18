"""Tests for PDF converter client and Portal async/sync import routing."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import httpx
import pytest
from fastapi.testclient import TestClient
from pdf_test_helpers import build_text_pdf_bytes

from knowledge_portal.api import create_app
from knowledge_portal.pdf_convert_jobs import (
    conversion_to_import_dict,
    convert_pdf_bytes,
    should_convert_async,
)
from knowledge_portal.pdf_converter_client import (
    PdfAsset,
    PdfConversionResult,
    PdfConverterClient,
    _parse_json_result,
)
from knowledge_portal.settings import PdfConverterAuthMode, PortalSettings


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


def test_import_places_rendered_images_after_each_source_mapped_page() -> None:
    result = PdfConversionResult(
        markdown=(
            "# Guide\n\n"
            "<!-- source-map:page_index=0 page_label=1 -->\n"
            "First page instructions.\n\n"
            "<!-- source-map:page_index=1 page_label=2 -->\n"
            "Second page instructions.\n"
        ),
        page_count=2,
        assets=(
            PdfAsset(filename="p01.png", content=b"page-one"),
            PdfAsset(filename="p02.png", content=b"page-two"),
        ),
    )

    imported = conversion_to_import_dict(
        result,
        filename="Guide.pdf",
        owner_unit_id="IT Service Desk",
    )

    markdown = imported["markdown_content"]
    assert markdown.index("First page instructions.") < markdown.index("p01.png")
    assert markdown.index("p01.png") < markdown.index("page_index=1")
    assert markdown.index("Second page instructions.") < markdown.index("p02.png")


def test_import_places_rendered_images_inside_page_heading_sections() -> None:
    result = PdfConversionResult(
        markdown="## Page 1\n\nFirst page.\n\n## Page 2\n\nSecond page.\n",
        page_count=2,
        assets=(
            PdfAsset(filename="p01.png", content=b"page-one"),
            PdfAsset(filename="p02.png", content=b"page-two"),
        ),
    )

    imported = conversion_to_import_dict(
        result,
        filename="Guide.pdf",
        owner_unit_id="IT Service Desk",
    )

    markdown = imported["markdown_content"]
    assert markdown.index("First page.") < markdown.index("p01.png")
    assert markdown.index("p01.png") < markdown.index("## Page 2")
    assert markdown.index("Second page.") < markdown.index("p02.png")


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
        headers: ClassVar[dict[str, str]] = {"content-type": "application/json"}
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


@pytest.mark.asyncio
async def test_pdf_converter_client_fetches_google_id_token_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {"content-type": "application/json"}
        text = ""

        def json(self):
            return {"markdown": "# Authenticated\n", "assets": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, files=None, data=None):
            captured["headers"] = headers
            return FakeResponse()

    async def fake_to_thread(function, *args):
        captured["token_function"] = function
        captured["audience"] = args[0]
        return "google-id-token"

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(
        "knowledge_portal.pdf_converter_client.asyncio.to_thread",
        fake_to_thread,
    )
    client = PdfConverterClient(
        base_url="https://converter.example.run.app/",
        auth_mode=PdfConverterAuthMode.GOOGLE_ID_TOKEN,
    )

    await client.convert_pdf(b"%PDF-demo")

    assert captured["audience"] == "https://converter.example.run.app"
    assert captured["headers"]["Authorization"] == "Bearer google-id-token"


def test_pdf_converter_auth_mode_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE", "unknown")

    with pytest.raises(
        ValueError,
        match="KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE must be one of",
    ):
        PortalSettings.from_env()


def test_google_id_token_auth_requires_converter_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_PORTAL_PDF_CONVERTER_AUTH_MODE", "GOOGLE_ID_TOKEN")
    monkeypatch.delenv("KNOWLEDGE_PORTAL_PDF_CONVERTER_URL", raising=False)
    monkeypatch.delenv("PDF_CONVERTER_URL", raising=False)

    with pytest.raises(
        ValueError,
        match="KNOWLEDGE_PORTAL_PDF_CONVERTER_URL is required",
    ):
        PortalSettings.from_env()


@pytest.mark.asyncio
async def test_configured_converter_failure_does_not_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = PortalSettings.from_env()
    object.__setattr__(settings, "pdf_converter_url", "https://converter.example.run.app")

    async def fail_conversion(*args, **kwargs):
        raise RuntimeError("converter unavailable")

    def fail_legacy_extraction(*args, **kwargs):
        pytest.fail("legacy extraction must not run for a configured converter")

    monkeypatch.setattr(PdfConverterClient, "convert_pdf", fail_conversion)
    monkeypatch.setattr(
        "knowledge_portal.pdf_convert_runner.extract_text_pdf",
        fail_legacy_extraction,
    )

    with pytest.raises(RuntimeError, match="converter unavailable"):
        await convert_pdf_bytes(settings, b"%PDF-demo", filename="guide.pdf")


def test_import_pdf_sync_uses_converter_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        headers: ClassVar[dict[str, str]] = {"content-type": "application/json"}
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
        files={
            "file": (
                "vpn.pdf",
                build_text_pdf_bytes("VPN login troubleshooting steps"),
                "application/pdf",
            )
        },
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
