"""Architecture Wave 0 characterization registry and ratchet tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
BASELINES = REPO_ROOT / "docs" / "architecture" / "baselines"

# Existing suites that serve as Wave 0 characterization baselines for the
# three highest-risk domains named in the architecture refactor plan.
CHARACTERIZATION_MODULES = (
    "test_workbench_routes",
    "test_knowledge",
    "test_knowledge_release",
    "test_pr4_release_gate_and_schedule",
)


def _load_script(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_characterization_modules_are_present() -> None:
    tests_dir = Path(__file__).resolve().parent
    missing = [
        name
        for name in CHARACTERIZATION_MODULES
        if not (tests_dir / f"{name}.py").exists()
    ]
    assert missing == [], f"missing characterization modules: {missing}"


def test_architecture_baselines_exist() -> None:
    required = (
        BASELINES / "oversized_files.json",
        BASELINES / "oversized_functions.json",
        BASELINES / "reverse_imports.json",
        BASELINES / "openapi" / "agent_service.routes.json",
        BASELINES / "openapi" / "knowledge_portal.routes.json",
        BASELINES / "openapi" / "ai_ops_backoffice.routes.json",
        BASELINES / "openapi" / "agent_service.schemas.json",
        BASELINES / "openapi" / "knowledge_portal.schemas.json",
        BASELINES / "openapi" / "ai_ops_backoffice.schemas.json",
    )
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()]
    assert missing == [], f"missing architecture baselines: {missing}"


def test_reverse_import_allowlist_is_empty_after_wave1() -> None:
    payload = json.loads((BASELINES / "reverse_imports.json").read_text(encoding="utf-8"))
    allowlist = payload["allowlist"]
    assert allowlist == {}, (
        "Wave 1 exit condition: no agent_service/knowledge_portal reverse imports remain; "
        f"found {allowlist}"
    )
    assert "agent_service->ai_ops_backoffice" in payload["forbidden_edges"]
    assert "knowledge_portal->ai_ops_backoffice" in payload["forbidden_edges"]


def test_check_architecture_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_architecture.py")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_new_oversized_file_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    checker = _load_script(
        "check_architecture_under_test",
        SCRIPTS / "check_architecture.py",
    )
    fake_root = tmp_path / "agent_service" / "src" / "agent_service"
    fake_root.mkdir(parents=True)
    giant = fake_root / "brand_new_giant.py"
    giant.write_text("\n".join(f"x{i} = {i}" for i in range(520)) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        checker,
        "PACKAGE_ROOTS",
        {"agent_service": fake_root},
    )
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)

    current = checker.collect_file_sizes()
    findings = checker.check_file_sizes(current, baseline={})
    assert any(finding.code == "FILE_NEW_OVERSIZED" for finding in findings)


def test_package_cycle_is_detected() -> None:
    checker = _load_script(
        "check_architecture_under_test",
        SCRIPTS / "check_architecture.py",
    )
    cycle_graph = {
        "agent_service": {"composition", "platform_kernel"},
        "composition": {"agent_service"},
        "platform_kernel": set(),
    }
    cycles = checker.find_package_cycles(cycle_graph)
    assert len(cycles) == 1
    assert sorted(cycles[0]) == ["agent_service", "composition"]

    findings = checker.check_package_cycles(cycle_graph)
    assert any(finding.code == "PACKAGE_CYCLE" for finding in findings)


def test_acyclic_graph_has_no_cycles() -> None:
    checker = _load_script(
        "check_architecture_under_test",
        SCRIPTS / "check_architecture.py",
    )
    acyclic_graph = {
        "composition": {"ai_ops_backoffice", "knowledge_portal", "agent_service"},
        "ai_ops_backoffice": {"knowledge_portal", "agent_service", "platform_kernel"},
        "knowledge_portal": {"agent_service", "platform_kernel"},
        "agent_service": {"platform_kernel"},
        "platform_kernel": set(),
    }
    assert checker.find_package_cycles(acyclic_graph) == []
    assert checker.check_package_cycles(acyclic_graph) == []


def test_domain_to_composition_edges_are_forbidden() -> None:
    payload = json.loads((BASELINES / "reverse_imports.json").read_text(encoding="utf-8"))
    assert "agent_service->composition" in payload["forbidden_edges"]
    assert "ai_ops_backoffice->composition" in payload["forbidden_edges"]
    assert "knowledge_portal->composition" in payload["forbidden_edges"]

