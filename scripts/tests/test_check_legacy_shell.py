"""Unit tests for the Phase G legacy-shell quarantine gate."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load_check_legacy_shell():
    scripts_dir = str(SCRIPTS)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    spec = importlib.util.spec_from_file_location(
        "check_legacy_shell_under_test",
        SCRIPTS / "check_legacy_shell.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_legacy_shell_under_test"] = module
    spec.loader.exec_module(module)
    return module


class LegacyShellCheckTest(unittest.TestCase):
    def test_repo_check_passes(self) -> None:
        check = _load_check_legacy_shell()
        self.assertEqual(check.run_checks(), [])

    def test_find_enabled_assignments_detects_truthy(self) -> None:
        check = _load_check_legacy_shell()
        enabled = check.find_enabled_assignments(
            "BACKOFFICE_LEGACY_SHELL_ENABLED=true\n"
            "OTHER=1\n"
            'BACKOFFICE_LEGACY_SHELL_ENABLED: "yes"\n'
        )
        self.assertEqual(len(enabled), 2)

    def test_find_enabled_assignments_ignores_false(self) -> None:
        check = _load_check_legacy_shell()
        self.assertEqual(
            check.find_enabled_assignments(
                "BACKOFFICE_LEGACY_SHELL_ENABLED=false\n"
                "BACKOFFICE_LEGACY_SHELL_ENABLED=0\n"
            ),
            [],
        )

    def test_settings_defaults_reject_true_field(self) -> None:
        check = _load_check_legacy_shell()
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.py"
            settings.write_text(
                textwrap.dedent(
                    """
                    class BackofficeSettings:
                        legacy_shell_enabled: bool = True

                    def from_env():
                        import os
                        return os.environ.get(
                            "BACKOFFICE_LEGACY_SHELL_ENABLED", "false"
                        )
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            findings = check.check_settings_defaults(settings)
            self.assertTrue(
                any("must default to False" in finding.message for finding in findings)
            )

    def test_deploy_sample_scan_flags_enabled_env(self) -> None:
        check = _load_check_legacy_shell()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deploy = root / "deploy"
            deploy.mkdir()
            (deploy / "sample.env").write_text(
                "BACKOFFICE_LEGACY_SHELL_ENABLED=true\n",
                encoding="utf-8",
            )
            # Minimal stubs so other checks do not dominate.
            settings = (
                root
                / "agent_service"
                / "src"
                / "ai_ops_backoffice"
                / "settings.py"
            )
            settings.parent.mkdir(parents=True)
            settings.write_text(
                textwrap.dedent(
                    """
                    class BackofficeSettings:
                        legacy_shell_enabled: bool = False

                    def from_env():
                        import os
                        return os.environ.get(
                            "BACKOFFICE_LEGACY_SHELL_ENABLED", "false"
                        )
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            legacy_js = (
                root
                / "agent_service"
                / "src"
                / "ai_ops_backoffice"
                / "static"
                / "legacy-js"
            )
            legacy_js.mkdir(parents=True)
            findings = check.run_checks(repo_root=root)
            self.assertTrue(
                any("must not enable legacy shell" in f.message for f in findings)
            )

    def test_product_html_must_not_import_legacy_js(self) -> None:
        check = _load_check_legacy_shell()
        with tempfile.TemporaryDirectory() as tmp:
            static = Path(tmp) / "static"
            static.mkdir()
            (static / "knowledge-ui.html").write_text(
                '<script type="module" src="/static/legacy-js/api.js"></script>\n',
                encoding="utf-8",
            )
            (static / "index.html").write_text(
                '<script type="module" src="/static/legacy-js/main.js"></script>\n',
                encoding="utf-8",
            )
            findings = check.check_product_html_avoids_legacy_js(static)
            self.assertEqual(len(findings), 1)
            self.assertIn("knowledge-ui.html", findings[0].format())
            self.assertIn("must not import /static/legacy-js/", findings[0].message)


if __name__ == "__main__":
    unittest.main()
