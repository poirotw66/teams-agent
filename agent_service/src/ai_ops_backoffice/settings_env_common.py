"""Shared environment parsing primitives for Backoffice settings loaders."""

from __future__ import annotations

import os
from pathlib import Path


def truthy(value: str, *, extras: set[str] | None = None) -> bool:
    accepted = {"1", "true", "yes"}
    if extras:
        accepted = accepted | extras
    return value.lower() in accepted


def env_path(key: str, default: Path) -> Path:
    return Path(os.environ.get(key, default)).expanduser().resolve()


def optional_env(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


def resolve_store_mode(
    env_key: str,
    primary_store_mode: str,
    default: str = "FILE",
) -> str:
    value = os.environ.get(env_key)
    if value is not None and value.strip():
        return value.strip().upper()
    if primary_store_mode == "FIRESTORE":
        return "FIRESTORE"
    return default.upper()
