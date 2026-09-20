"""Tests for retrieval_eval_v3_blind corpus validation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_validator():
    path = _REPO_ROOT / "scripts" / "validate_retrieval_eval_v3_blind.py"
    spec = importlib.util.spec_from_file_location("validate_retrieval_eval_v3_blind", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_v3_blind_set_passes_corpus_validation() -> None:
    validator = _load_validator()
    errors = validator.validate_blind_set(
        blind_path=_REPO_ROOT / "data" / "eval" / "retrieval_eval_v3_blind.json",
        sources_dir=_REPO_ROOT / "data" / "sources",
    )
    assert errors == []
