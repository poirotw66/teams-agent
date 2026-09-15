"""Unit tests for historical source original migration dry-run."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "migrate_historical_source_originals.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_historical_source_originals", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_migrate_dry_run_marks_unproven_pairings(tmp_path: Path, capsys) -> None:
    module = _load_module()
    records = tmp_path / "ops" / "sources" / "records" / "tenant-a"
    records.mkdir(parents=True)
    (records / "src-keep.json").write_text(
        json.dumps(
            {
                "source_ref_id": "src-keep",
                "tenant_id": "tenant-a",
                "document_id": "doc-1",
                "version_id": "ver-1",
                "release_id": "release-1",
                "mapping_status": "AVAILABLE",
                "artifact_ref": "artifacts/doc-1",
                "original_asset_name": "guide.pdf",
            }
        ),
        encoding="utf-8",
    )
    (records / "src-legacy.json").write_text(
        json.dumps(
            {
                "source_ref_id": "src-legacy",
                "tenant_id": "tenant-a",
                "document_id": "doc-2",
                "version_id": "ver-1",
                "release_id": "release-1",
                "mapping_status": "AVAILABLE",
                "source_path": "sources/missing.md",
            }
        ),
        encoding="utf-8",
    )

    code = module.migrate(
        data_dir=tmp_path,
        tenant_filter="tenant-a",
        dry_run=True,
        apply=False,
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["keep"] == 1
    assert report["counts"]["mark_legacy_unverified"] == 1
