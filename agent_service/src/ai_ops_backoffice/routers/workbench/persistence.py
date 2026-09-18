"""JSON file I/O and portal upload helpers for workbench routes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def get_project_root(ops_store_path: Path) -> Path:
    # ops_store_path is typically <repo>/data/ops/events
    data_dir = ops_store_path.parent.parent
    return data_dir.parent


def load_json_safe(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        logger.warning("Failed to load JSON file %s: %s", path, err)
        return None


def save_json_safe(path: Path, data: Any) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as err:
        logger.error("Failed to save JSON file %s: %s", path, err)


def portal_upload_body(
    *,
    filename: str,
    payload: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    request = httpx.Request(
        "POST",
        "https://knowledge-portal.invalid/upload",
        files={"file": (filename, payload, content_type)},
    )
    return request.read(), str(request.headers["content-type"])


# Compatibility aliases matching the former private names.
_get_project_root = get_project_root
_load_json_safe = load_json_safe
_save_json_safe = save_json_safe
_portal_upload_body = portal_upload_body
