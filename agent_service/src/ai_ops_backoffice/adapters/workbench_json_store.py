"""File-backed JSON store for workbench operational state.

Keeps filesystem I/O out of HTTP router packages.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def resolve_project_root(ops_store_path: Path) -> Path:
    """Derive repository root from an ops store path such as ``data/ops/events``."""
    data_dir = ops_store_path.parent.parent
    return data_dir.parent


@dataclass(frozen=True)
class WorkbenchJsonStore:
    """Small JSON document repository used by workbench application routes."""

    def load(self, path: Path) -> Any:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as err:
            logger.warning("Failed to load JSON file %s: %s", path, err)
            return None

    def save(self, path: Path, data: Any) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as err:
            logger.error("Failed to save JSON file %s: %s", path, err)


def build_portal_upload_body(
    *,
    filename: str,
    payload: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    """Build a multipart upload body for Knowledge Portal bridge calls."""
    request = httpx.Request(
        "POST",
        "https://knowledge-portal.invalid/upload",
        files={"file": (filename, payload, content_type)},
    )
    return request.read(), str(request.headers["content-type"])
