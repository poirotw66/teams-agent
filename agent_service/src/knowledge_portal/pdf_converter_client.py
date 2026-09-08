"""HTTP client for the standalone PDF-to-Markdown converter Cloud Run service."""

from __future__ import annotations

import base64
import json
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import httpx


class PdfConverterError(RuntimeError):
    """Raised when the converter service fails or returns an unexpected payload."""


@dataclass(frozen=True)
class PdfAsset:
    filename: str
    content: bytes


@dataclass(frozen=True)
class PdfConversionResult:
    markdown: str
    page_count: int | None = None
    assets: tuple[PdfAsset, ...] = ()
    warnings: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


class PdfConverterClient:
    """Calls POST /api/v1/convert-pdf on the converter service."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = 120.0,
        prompt_template: str = "slide",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = (token or "").strip() or None
        self._timeout = timeout_seconds
        self._prompt_template = prompt_template

    async def convert_pdf(
        self,
        payload: bytes,
        *,
        filename: str = "document.pdf",
    ) -> PdfConversionResult:
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        files = {"file": (filename, payload, "application/pdf")}
        data = {"prompt_template": self._prompt_template}
        url = f"{self._base_url}/api/v1/convert-pdf"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, headers=headers, files=files, data=data)
        except httpx.HTTPError as exc:
            raise PdfConverterError(f"PDF converter unreachable: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:500]
            raise PdfConverterError(
                f"PDF converter returned HTTP {response.status_code}: {detail}"
            )
        return _parse_converter_response(response)


def _parse_converter_response(response: httpx.Response) -> PdfConversionResult:
    content_type = (response.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = response.json()
        if not isinstance(payload, dict):
            raise PdfConverterError("PDF converter JSON payload must be an object.")
        return _parse_json_result(payload)
    if "application/zip" in content_type or response.content[:2] == b"PK":
        return _parse_zip_result(response.content)
    text = response.text.strip()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PdfConverterError("PDF converter returned invalid JSON.") from exc
        if isinstance(payload, dict):
            return _parse_json_result(payload)
    if text:
        return PdfConversionResult(markdown=text if text.endswith("\n") else f"{text}\n")
    raise PdfConverterError("PDF converter returned an empty body.")


def _parse_json_result(payload: dict[str, Any]) -> PdfConversionResult:
    markdown = (
        payload.get("markdown")
        or payload.get("markdown_content")
        or payload.get("content")
        or payload.get("text")
    )
    if not isinstance(markdown, str) or not markdown.strip():
        raise PdfConverterError("PDF converter response missing markdown content.")
    page_count = payload.get("page_count") or payload.get("pages") or payload.get("pageCount")
    parsed_pages = int(page_count) if page_count is not None else None
    assets: list[PdfAsset] = []
    for item in payload.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("filename") or item.get("name") or "").strip()
        raw = item.get("content_base64") or item.get("contentBase64") or item.get("data")
        if not name or not isinstance(raw, str):
            continue
        try:
            content = base64.b64decode(raw)
        except Exception:
            continue
        assets.append(PdfAsset(filename=name, content=content))
    warnings = tuple(
        str(item)
        for item in (payload.get("warnings") or [])
        if item is not None and str(item).strip()
    )
    return PdfConversionResult(
        markdown=markdown if markdown.endswith("\n") else f"{markdown}\n",
        page_count=parsed_pages,
        assets=tuple(assets),
        warnings=warnings,
        raw=payload,
    )


def _parse_zip_result(payload: bytes) -> PdfConversionResult:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        markdown_name = next(
            (name for name in archive.namelist() if name.lower().endswith(".md")),
            None,
        )
        if markdown_name is None:
            raise PdfConverterError("Converter ZIP missing a .md file.")
        markdown = archive.read(markdown_name).decode("utf-8")
        assets = []
        for name in archive.namelist():
            lower = name.lower()
            if lower.endswith(".md") or name.endswith("/"):
                continue
            if "/assets/" in lower or lower.startswith("assets/"):
                assets.append(PdfAsset(filename=Path_basename(name), content=archive.read(name)))
            elif lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                assets.append(PdfAsset(filename=Path_basename(name), content=archive.read(name)))
    return PdfConversionResult(
        markdown=markdown if markdown.endswith("\n") else f"{markdown}\n",
        assets=tuple(assets),
        warnings=("Converted via ZIP download from PDF converter.",),
    )


def Path_basename(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]
