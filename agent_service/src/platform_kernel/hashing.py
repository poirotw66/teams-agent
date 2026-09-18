"""Pure hashing helpers shared across domains."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def short_version(value: str) -> str:
    return content_hash(value)[:12]


def fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return content_hash(encoded)


def sticky_bucket(tenant: str, conversation_id: str) -> int:
    digest = content_hash(f"{tenant}:{conversation_id}")
    return int(digest[:8], 16) % 100
