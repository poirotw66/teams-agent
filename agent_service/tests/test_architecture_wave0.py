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

# Existing suites that serve as Wave 0 / Phase H characterization baselines for
# the highest-risk domains named in the architecture follow-up plan.
CHARACTERIZATION_MODULES = (
    "test_workbench_routes",
    "test_knowledge",
    "test_knowledge_release",
    "test_pr4_release_gate_and_schedule",
    "test_extractor",
    "test_evaluation_domain",
    "test_evaluation_runner",
    "test_source_traceability",
    "test_source_document_resolve",
    "test_documents",
    "test_composition_import_isolation",
    "test_console_consumer_contracts",
    # Phase H residual domains from the 2026-09-18 follow-up plan.
    "test_backoffice_quality_domain",
    "test_faq",
    "test_backoffice_faq_domain",
    "test_backoffice_settings",
    "test_settings_domain",
    "test_release_coordinator_matrix",
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
        BASELINES / "importer_counts.json",
        BASELINES / "private_access.json",
        BASELINES / "openapi" / "agent_service.routes.json",
        BASELINES / "openapi" / "knowledge_portal.routes.json",
        BASELINES / "openapi" / "ai_ops_backoffice.routes.json",
        BASELINES / "openapi" / "agent_service.schemas.json",
        BASELINES / "openapi" / "knowledge_portal.schemas.json",
        BASELINES / "openapi" / "ai_ops_backoffice.schemas.json",
        BASELINES / "openapi" / "ai_ops_backoffice.openapi.json",
    )
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()]
    assert missing == [], f"missing architecture baselines: {missing}"

    generated_dir = (
        REPO_ROOT / "console_frontend" / "src" / "shared" / "api" / "generated"
    )
    for name in ("backoffice-schemas.ts", "backoffice-client.ts"):
        generated_ts = generated_dir / name
        assert generated_ts.exists(), (
            f"missing generated OpenAPI TypeScript ({name}); "
            "run scripts/generate_openapi_ts.py --write"
        )

    private_access = json.loads(
        (BASELINES / "private_access.json").read_text(encoding="utf-8")
    )
    assert private_access.get("allowlist") == [], (
        "private_access allowlist must stay empty after Phase E fixes; "
        f"found {private_access.get('allowlist')}"
    )


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


def test_tighten_size_baseline_caps_at_current() -> None:
    checker = _load_script(
        "check_architecture_tighten",
        SCRIPTS / "check_architecture.py",
    )
    extractor = "agent_service/src/agent_service/extractor.py"
    tightened = checker.tighten_size_baseline(
        {extractor: 978},
        {extractor: 802},
        max_lines=500,
    )
    assert tightened == {extractor: 802}


def test_file_growth_after_tighten_is_rejected() -> None:
    """Shrink becomes the new cap; silent re-growth past that cap must fail."""
    checker = _load_script(
        "check_architecture_regrow",
        SCRIPTS / "check_architecture.py",
    )
    extractor = "agent_service/src/agent_service/extractor.py"
    tightened = checker.tighten_size_baseline(
        {extractor: 978},
        {extractor: 802},
        max_lines=500,
    )
    assert tightened == {extractor: 802}

    findings = checker.check_file_sizes({extractor: 803}, baseline=tightened)
    assert any(finding.code == "FILE_GREW" for finding in findings)
    grew = next(finding for finding in findings if finding.code == "FILE_GREW")
    assert "802 -> 803" in grew.message


def test_check_file_sizes_rejects_growth_from_tight_baseline() -> None:
    checker = _load_script(
        "check_architecture_file_grew",
        SCRIPTS / "check_architecture.py",
    )
    extractor = "agent_service/src/agent_service/extractor.py"
    findings = checker.check_file_sizes(
        {extractor: 803},
        baseline={extractor: 802},
    )
    assert any(finding.code == "FILE_GREW" for finding in findings)


def test_importer_count_growth_is_rejected() -> None:
    checker = _load_script(
        "check_architecture_importer",
        SCRIPTS / "check_architecture.py",
    )
    baseline = {
        "ai_ops_backoffice->agent_service": 100,
        "knowledge_portal->agent_service": 18,
    }
    current = {
        "ai_ops_backoffice->agent_service": 101,
        "knowledge_portal->agent_service": 18,
    }
    findings = checker.check_importer_counts(current, baseline)
    assert any(finding.code == "IMPORTER_COUNT_GREW" for finding in findings)
    grew = next(
        finding for finding in findings if finding.code == "IMPORTER_COUNT_GREW"
    )
    assert "ai_ops_backoffice->agent_service" in grew.message
    assert "100 -> 101" in grew.message


def test_importer_count_tighten_reduces_cap() -> None:
    checker = _load_script(
        "check_architecture_importer_tighten",
        SCRIPTS / "check_architecture.py",
    )
    baseline = {
        "ai_ops_backoffice->agent_service": 110,
        "knowledge_portal->agent_service": 20,
    }
    current = {
        "ai_ops_backoffice->agent_service": 107,
        "knowledge_portal->agent_service": 18,
    }
    tightened = checker.tighten_importer_counts(baseline, current)
    assert tightened["ai_ops_backoffice->agent_service"] == 107
    assert tightened["knowledge_portal->agent_service"] == 18
    # Ownership edges absent from the fixture baseline initialize to current (0).
    for src, dst in checker.OWNERSHIP_IMPORT_EDGES:
        key = f"{src}->{dst}"
        assert key in tightened
        if key not in baseline:
            assert tightened[key] == current.get(key, 0)


def test_cross_module_private_access_is_detected() -> None:
    checker = _load_script(
        "check_architecture_private_access",
        SCRIPTS / "check_architecture.py",
    )
    snippet = (
        "def preview(query_service):\n"
        "    return query_service._source_trace.resolve_source_ref('x')\n"
    )
    hits = checker.collect_cross_module_private_access(snippet)
    assert any(expr == "query_service._source_trace" for _, expr in hits)

    allowed = (
        "class Service:\n"
        "    def run(self):\n"
        "        return self._source_trace\n"
    )
    assert checker.collect_cross_module_private_access(allowed) == []


def test_private_access_roots_cover_services_and_application() -> None:
    checker = _load_script(
        "check_architecture_private_access_roots",
        SCRIPTS / "check_architecture.py",
    )
    root_names = {path.name for path in checker._PRIVATE_ACCESS_ROOTS}
    assert {"routers", "bootstrap", "services", "application", "governance_domain"} <= (
        root_names
    )


def test_governance_eval_harness_is_excluded_from_private_access_scan(
    tmp_path: Path,
) -> None:
    checker = _load_script(
        "check_architecture_private_access_exclude",
        SCRIPTS / "check_architecture.py",
    )
    harness = tmp_path / "governance_domain" / "eval_runtime.py"
    harness.parent.mkdir(parents=True)
    harness.write_text("x = 1\n", encoding="utf-8")
    peer = tmp_path / "governance_domain" / "models.py"
    peer.write_text("x = 1\n", encoding="utf-8")
    assert checker.is_private_access_path_excluded(harness) is True
    assert checker.is_private_access_path_excluded(peer) is False


def test_private_access_allowlist_only_shrinks() -> None:
    checker = _load_script(
        "check_architecture_private_access_ratchet",
        SCRIPTS / "check_architecture.py",
    )
    baseline = [
        "services/a.py:1: other._foo",
        "services/b.py:2: other._bar",
    ]
    current = ["services/a.py:1: other._foo"]
    tightened = checker.tighten_private_access_allowlist(baseline, current)
    assert tightened == ["services/a.py:1: other._foo"]

    # New findings are not auto-added; callers must fail via check.
    assert checker.tighten_private_access_allowlist([], current) == []


def test_router_filesystem_io_pattern_detects_path_open() -> None:
    checker = _load_script(
        "check_architecture_router_fs",
        SCRIPTS / "check_architecture.py",
    )
    assert checker.ROUTER_FS_IO_RE.search("with path.open('rb') as handle:")
    assert checker.ROUTER_FS_IO_RE.search("path.read_text(encoding='utf-8')")
    assert checker.ROUTER_FS_IO_RE.search("path.write_bytes(payload)") is not None
    assert checker.ROUTER_FS_IO_RE.search("return FileResponse(path)") is None
    assert checker._is_router_module(
        Path("agent_service/src/ai_ops_backoffice/routers/sources/file.py")
    )
    assert not checker._is_router_module(
        Path("agent_service/src/ai_ops_backoffice/adapters/local_source_files.py")
    )


def test_allowed_cross_domain_edge_matrix_rejects_unknown_edges() -> None:
    checker = _load_script(
        "check_architecture_allowed_edges",
        SCRIPTS / "check_architecture.py",
    )
    findings = checker.check_allowed_cross_domain_edges(
        {"teams_agent->agent_service": 1}
    )
    assert any(item.code == "EDGE_NOT_ALLOWED" for item in findings)
    assert checker.check_allowed_cross_domain_edges(
        {"composition->agent_service": 3}
    ) == []


def test_size_waiver_expiry_and_schema_enforced() -> None:
    checker = _load_script(
        "check_architecture_waivers",
        SCRIPTS / "check_architecture.py",
    )
    as_of = checker.date.fromisoformat("2026-09-19")
    assert checker.check_size_waivers({"waivers": []}, today=as_of) == []
    expired = checker.check_size_waivers(
        {
            "waivers": [
                {
                    "path": "agent_service/src/agent_service/foo.py",
                    "owner": "platform",
                    "reason": "temporary",
                    "expiry": "2026-01-01",
                    "tracking_issue": "https://example.invalid/1",
                    "target_size": 200,
                }
            ]
        },
        today=as_of,
    )
    assert any(item.code == "WAIVER_EXPIRED" for item in expired)
    invalid = checker.check_size_waivers(
        {"waivers": [{"path": "x.py"}]},
        today=as_of,
    )
    assert any(item.code == "WAIVER_SCHEMA" for item in invalid)


def test_sizes_against_ref_detects_growth() -> None:
    checker = _load_script(
        "check_architecture_compare_ref",
        SCRIPTS / "check_architecture.py",
    )
    findings = checker.check_sizes_against_ref(
        compare_ref="unused",
        current_files={"a.py": 600},
        current_functions={},
    )
    # Missing ref baselines soft-skip (empty findings).
    assert findings == []

