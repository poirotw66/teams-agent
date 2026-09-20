"""Tests for retrieval_eval_v3_blind corpus validation."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

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
    """Full corpus check requires local data/sources (gitignored; not in CI)."""
    sources_dir = _REPO_ROOT / "data" / "sources"
    markdown_files = [
        path for path in sources_dir.glob("*.md") if path.name != "README.md"
    ]
    if not markdown_files:
        pytest.skip("data/sources corpus is not present in this environment")

    validator = _load_validator()
    errors = validator.validate_blind_set(
        blind_path=_REPO_ROOT / "data" / "eval" / "retrieval_eval_v3_blind.json",
        sources_dir=sources_dir,
        require_frozen=True,
    )
    assert errors == []


def test_frozen_blind_metadata_gates_without_corpus(tmp_path: Path) -> None:
    """Freeze metadata gates must fail closed even when sources are absent."""
    validator = _load_validator()
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    (sources_dir / "doc-a.md").write_text("# Doc A\nbody\n", encoding="utf-8")

    blind_path = tmp_path / "blind.json"
    blind_path.write_text(
        json.dumps(
            {
                "role": "release_holdout",
                "minCaseCount": 1,
                "frozen": True,
                "freezeVersion": 2,
                "reviewerSignoff": {"reviewer": "test", "recommendation": "APPROVE_FREEZE"},
                "fillProgress": {"filled": 1, "reviewed": 1},
                "cases": [
                    {
                        "id": "case-1",
                        "query": "how to unlock",
                        "split": "test",
                        "labelStatus": "frozen",
                        "expectedFound": True,
                        "expectedDocuments": ["Doc A"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert (
        validator.validate_blind_set(
            blind_path=blind_path,
            sources_dir=sources_dir,
            require_frozen=True,
        )
        == []
    )

    unfrozen = json.loads(blind_path.read_text(encoding="utf-8"))
    unfrozen["frozen"] = False
    blind_path.write_text(json.dumps(unfrozen), encoding="utf-8")
    errors = validator.validate_blind_set(
        blind_path=blind_path,
        sources_dir=sources_dir,
        require_frozen=True,
    )
    assert any("frozen must be true" in error for error in errors)
