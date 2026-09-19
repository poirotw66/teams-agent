"""Unit tests for scripts/check_console_openapi_matrix.py."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load() -> object:
    path = REPO_ROOT / "scripts" / "check_console_openapi_matrix.py"
    spec = importlib.util.spec_from_file_location("check_console_openapi_matrix", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConsoleOpenApiMatrixTest(unittest.TestCase):
    def test_catch_all_knowledge_proxy_covers_nested_paths(self) -> None:
        check = _load()
        openapi_paths = {
            "/api/knowledge/{full_path}",
            "/api/console/workbench/overview",
        }
        self.assertTrue(
            check._path_matches(
                "/api/knowledge/v1/documents/{id}/chunk-preview",
                openapi_paths,
            )
        )
        self.assertTrue(
            check._path_matches("/api/console/workbench/overview", openapi_paths)
        )
        self.assertFalse(
            check._path_matches("/api/console/missing", openapi_paths)
        )

    def test_repo_matrix_passes(self) -> None:
        check = _load()
        self.assertEqual(check.main(), 0)


if __name__ == "__main__":
    unittest.main()
