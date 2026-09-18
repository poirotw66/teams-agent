"""Unit tests for console-v2 bundle sync helpers (Phase G seam)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load_sync_console_v2():
    scripts_dir = str(SCRIPTS)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(
        "sync_console_v2_under_test",
        SCRIPTS / "sync_console_v2.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["sync_console_v2_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


class SyncConsoleV2HelpersTest(unittest.TestCase):
    def test_inventory_and_compare_detect_content_drift(self) -> None:
        sync = _load_sync_console_v2()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            (left / "assets").mkdir(parents=True)
            (right / "assets").mkdir(parents=True)
            _write_text(left / "index.html", "a\n")
            _write_text(right / "index.html", "a\n")
            _write_text(left / "assets" / "app.js", "v1\n")
            _write_text(right / "assets" / "app.js", "v2\n")

            errors = sync.compare_inventories(
                expected=sync.inventory_files(left),
                actual=sync.inventory_files(right),
                expected_label="rebuild",
                actual_label="committed",
            )
            self.assertTrue(
                any("content mismatch: assets/app.js" in error for error in errors)
            )

    def test_compare_inventories_detects_missing_and_extra(self) -> None:
        sync = _load_sync_console_v2()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            left.mkdir()
            right.mkdir()
            _write_text(left / "keep.txt", "same\n")
            _write_text(right / "keep.txt", "same\n")
            _write_text(left / "only-rebuild.txt", "x\n")
            _write_text(right / "only-committed.txt", "y\n")

            errors = sync.compare_inventories(
                expected=sync.inventory_files(left),
                actual=sync.inventory_files(right),
                expected_label="rebuild",
                actual_label="committed",
            )
            self.assertIn("missing in committed: only-rebuild.txt", errors)
            self.assertIn(
                "extra in committed (not in rebuild): only-committed.txt", errors
            )

    def test_matching_trees_produce_no_errors(self) -> None:
        sync = _load_sync_console_v2()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left = root / "left"
            right = root / "right"
            for tree in (left, right):
                (tree / "assets").mkdir(parents=True)
                _write_text(tree / "index.html", "<html/>\n")
                (tree / "assets" / "app.js").write_bytes(b"console.log(1);\n")

            errors = sync.compare_inventories(
                expected=sync.inventory_files(left),
                actual=sync.inventory_files(right),
                expected_label="rebuild",
                actual_label="committed",
            )
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
