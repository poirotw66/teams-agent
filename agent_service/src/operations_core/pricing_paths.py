"""Shared pricing store path resolution for Agent and Backoffice.

Backoffice pricing bootstrap and Agent pricing_bootstrap share one default path
so emit-time costs and budget evaluation read the same rules file.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_pricing_store_path(ops_store_path: Path | None = None) -> Path:
    """Resolve the FILE-mode pricing rules path from env or ops store layout."""
    explicit = os.environ.get("AI_OPS_PRICING_STORE_PATH")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if ops_store_path is not None:
        return (ops_store_path.parent / "phase2" / "pricing_rules.json").resolve()
    root = Path(__file__).resolve().parents[3]
    return (root / "data" / "ops" / "phase2" / "pricing_rules.json").resolve()
