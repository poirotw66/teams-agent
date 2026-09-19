"""Unit tests for the fail-closed Phase G legacy-js delete helper."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load_delete_legacy_js():
    scripts_dir = str(SCRIPTS)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(
        "delete_legacy_js_under_test",
        SCRIPTS / "delete_legacy_js.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["delete_legacy_js_under_test"] = module
    spec.loader.exec_module(module)
    return module


class DeleteLegacyJsTest(unittest.TestCase):
    def test_refuses_without_confirmation(self) -> None:
        delete = _load_delete_legacy_js()
        self.assertEqual(delete.main([]), 2)

    def test_dry_run_with_confirmation_does_not_delete(self) -> None:
        delete = _load_delete_legacy_js()
        before = delete.LEGACY_JS.is_dir()
        self.assertTrue(before)
        self.assertEqual(
            delete.main(["--confirm-unused-release-completed"]),
            0,
        )
        self.assertTrue(delete.LEGACY_JS.is_dir())

    def test_soft_blockers_detect_product_html_ref(self) -> None:
        delete = _load_delete_legacy_js()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy-js"
            legacy.mkdir()
            (root / "index.html").write_text(
                '<script src="/static/legacy-js/main.js"></script>\n',
                encoding="utf-8",
            )
            blockers = delete.soft_blockers(legacy_js_dir=legacy)
            self.assertTrue(
                any("product HTML still references legacy-js" in item for item in blockers)
            )

    def test_update_waivers_marks_deleted_row(self) -> None:
        delete = _load_delete_legacy_js()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oversized-waivers.md"
            path.write_text(
                "| Legacy quarantine (non-product) | `static/legacy-js/**` | "
                "Emergency kill-switch only; not on default product path | "
                "Delete after **one full release cycle** where production never sets "
                "`BACKOFFICE_LEGACY_SHELL_ENABLED`; gate: `scripts/check_legacy_shell.py` "
                "(defaults + deploy/env samples must stay off). Do not delete the tree "
                "until that cycle completes |\n",
                encoding="utf-8",
            )
            delete._update_waivers_after_delete(path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("deleted", text)
            self.assertIn("retired after unused release", text)


if __name__ == "__main__":
    unittest.main()
