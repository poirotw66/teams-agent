"""Adversarial contract tests; fixture verifiers are NOT organisational approvals."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ops_uat_handoff as uat_cli
from ops_acceptance_evidence import (
    UTC, FORMAL_ACCEPTANCE, LAB_SELF_TEST, LOCAL_SCOPE, PHASE01_SCOPE,
    REQUIRED_PHASE01_GATES, REQUIRED_REVIEWER_ROLES, REQUIRED_TECHNICAL_GATES,
    SPEC_CRITERIA, formal_acceptance_errors, manifest_sha256, protect_output,
    read_json, technical_manifest, technical_verification_errors, validate_acceptance_evidence,
)
from ops_formal_acceptance_audit import build_audit
from ops_signoff_checklist import sync_checklist

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TARGET = {
    "environment": "lab", "commitSha": "a" * 40,
    "artifactIdentity": {"kind": "image-sha256", "value": "b" * 64},
}


def _time(**delta: int) -> str:
    return (NOW + timedelta(**delta)).isoformat()


def _uat_report(scope: str = PHASE01_SCOPE) -> dict:
    ids = REQUIRED_PHASE01_GATES if scope == PHASE01_SCOPE else REQUIRED_TECHNICAL_GATES
    evidence = {
        "schemaVersion": "v2", "classification": LAB_SELF_TEST,
        "assessmentScope": scope, "target": copy.deepcopy(TARGET),
        "runId": "fixture-run-001", "expiresAt": _time(days=7),
        "technicalEvidence": {
            "requiredGateIds": list(ids),
            "gates": [
                {
                    "id": gate_id, "status": "PASSED", "command": f"check {gate_id}",
                    "cwd": "/trusted-runner/workspace", "exitCode": 0,
                    "executedAt": _time(hours=-2), "expiresAt": _time(days=7),
                    "result": {"summary": "fixture result"},
                    "artifactScope": {
                        "target": copy.deepcopy(TARGET),
                        "references": [{"id": f"fixture-run-001:{gate_id}", "sha256": "c" * 64}],
                    },
                }
                for gate_id in ids
            ],
        },
    }
    evidence["technicalManifestSha256"] = manifest_sha256(evidence)
    return {"acceptanceEvidence": evidence}


def _formal_checklist(report: dict | None = None) -> dict:
    evidence = copy.deepcopy((report or _uat_report())["acceptanceEvidence"])
    evidence["classification"] = FORMAL_ACCEPTANCE
    evidence["requiredReviewerRoles"] = list(REQUIRED_REVIEWER_ROLES)
    evidence["formalApprovals"] = [
        {
            "role": role, "status": "APPROVED", "decisionId": f"fixture-decision:{role}",
            "assessmentScope": PHASE01_SCOPE,
            "reviewer": {"subjectId": f"fixture-subject:{role}", "displayName": "Same Display Name"},
            "approvedAt": _time(hours=-1), "expiresAt": _time(days=7),
            "reviewedTarget": copy.deepcopy(TARGET),
            "reviewedManifestSha256": evidence["technicalManifestSha256"],
            "authorityEvidence": {
                "sourceSystem": "FIXTURE_ONLY", "sourceRecordId": f"fixture-record:{role}",
                "verificationStatus": "EXTERNALLY_VERIFIED", "verifiedAt": _time(minutes=-30),
            },
        }
        for role in REQUIRED_REVIEWER_ROLES
    ]
    return {"acceptanceEvidence": evidence}


class FakeReadOnlyVerifier:
    """Pin independent fixture records, not caller claims. Never used by a CLI."""

    def __init__(self) -> None:
        self.expected = _uat_report()["acceptanceEvidence"]
        self.decisions = _formal_checklist()["acceptanceEvidence"]["formalApprovals"]

    def verify_technical(self, *, manifest: dict, manifest_sha256: str, now: datetime) -> tuple[bool, str]:
        return (
            manifest == technical_manifest(self.expected)
            and manifest_sha256 == self.expected["technicalManifestSha256"] and now == NOW,
            "fixture runner record comparison",
        )

    def verify_approval(
        self, *, approval: dict, manifest: dict, manifest_sha256: str, now: datetime,
    ) -> tuple[bool, str]:
        return (
            approval in self.decisions and manifest == technical_manifest(self.expected)
            and manifest_sha256 == self.expected["technicalManifestSha256"] and now == NOW,
            "fixture complete decision comparison",
        )


def _formal_errors(checklist: dict, report: dict | None = None) -> list[str]:
    fake = FakeReadOnlyVerifier()
    return formal_acceptance_errors(
        checklist, report or _uat_report(), now=NOW, verifier=fake, technical_verifier=fake,
    )


def _rehash(evidence: dict) -> None:
    evidence["technicalManifestSha256"] = manifest_sha256(evidence)


def test_legacy_lab_self_test_approved_fields_are_not_formal() -> None:
    legacy = {"signOffItems": [
        {"role": role, "status": "approved", "approvedBy": "Justin", "notes": "LAB 自驗"}
        for role in REQUIRED_REVIEWER_ROLES
    ]}
    assert formal_acceptance_errors(legacy, {"formalAcceptanceComplete": True}, now=NOW)
    # Neither note language nor different names affect the trust boundary.
    for item in legacy["signOffItems"]:
        item["notes"] = "Production approved"
        item["approvedBy"] = item["role"]
    assert formal_acceptance_errors(legacy, _uat_report(), now=NOW)


def test_complete_fixture_can_be_formal_with_both_injected_verifiers() -> None:
    assert _formal_errors(_formal_checklist()) == []


@pytest.mark.parametrize("approval_verifier,technical_verifier", [(None, None), (True, None), (None, True)])
def test_default_metadata_or_only_one_verifier_is_untrusted(approval_verifier, technical_verifier) -> None:
    fake = FakeReadOnlyVerifier()
    assert formal_acceptance_errors(
        _formal_checklist(), _uat_report(), now=NOW,
        verifier=fake if approval_verifier else None,
        technical_verifier=fake if technical_verifier else None,
    )


def test_schema_valid_does_not_mean_trusted_execution(tmp_path: Path) -> None:
    report = _uat_report()
    assert validate_acceptance_evidence(report["acceptanceEvidence"], now=NOW) == []
    assert technical_verification_errors(report["acceptanceEvidence"], now=NOW)
    audit = build_audit(tmp_path, uat_report=report, checklist=_formal_checklist(), now=NOW)
    assert audit["technicalSchemaValid"]
    assert audit["automatedVerification"]["status"] == "SCHEMA_VALID_UNTRUSTED"
    assert not audit["labSelfTest"]["accepted"]
    assert not audit["formalAcceptanceComplete"]


@pytest.mark.parametrize("status", ["SKIPPED", "NOT_RUN", "FAILED"])
def test_nonpassed_gate_blocks_even_with_approvals(status: str) -> None:
    checklist = _formal_checklist()
    checklist["acceptanceEvidence"]["technicalEvidence"]["gates"][0]["status"] = status
    assert _formal_errors(checklist)


@pytest.mark.parametrize("exit_code", [1, None, False, "0"])
def test_exit_code_must_be_executed_integer_zero(exit_code: object) -> None:
    checklist = _formal_checklist()
    checklist["acceptanceEvidence"]["technicalEvidence"]["gates"][0]["exitCode"] = exit_code
    assert _formal_errors(checklist)


def test_missing_approval_cannot_be_overridden_by_tests() -> None:
    checklist = _formal_checklist()
    checklist["acceptanceEvidence"]["formalApprovals"].pop()
    assert any("formal approval BU/Knowledge Admin is missing" in error for error in _formal_errors(checklist))


@pytest.mark.parametrize("where", ["gates", "requiredGateIds", "formalApprovals", "requiredReviewerRoles"])
def test_duplicate_records_and_required_lists_fail_closed(where: str) -> None:
    checklist = _formal_checklist()
    evidence = checklist["acceptanceEvidence"]
    values = evidence["technicalEvidence"][where] if where in ("gates", "requiredGateIds") else evidence[where]
    duplicate = copy.deepcopy(values[0])
    if where == "gates":
        duplicate.update(status="FAILED", exitCode=1)
    values.insert(0, duplicate)
    assert any("duplicate" in error for error in _formal_errors(checklist))


@pytest.mark.parametrize("where", ["gates", "requiredGateIds", "formalApprovals", "requiredReviewerRoles"])
@pytest.mark.parametrize("bad", [[{}], [None], "not-a-list", [], [1]])
def test_malformed_record_and_required_lists_return_errors(where: str, bad: object) -> None:
    checklist = _formal_checklist()
    evidence = checklist["acceptanceEvidence"]
    container = evidence["technicalEvidence"] if where in ("gates", "requiredGateIds") else evidence
    container[where] = bad
    assert _formal_errors(checklist)


@pytest.mark.parametrize("field", ["command", "cwd", "result", "artifactScope"])
def test_missing_command_result_or_scope_is_incomplete(field: str) -> None:
    checklist = _formal_checklist()
    del checklist["acceptanceEvidence"]["technicalEvidence"]["gates"][0][field]
    assert _formal_errors(checklist)


@pytest.mark.parametrize("change", ["reference", "result", "run", "commit"])
def test_changed_manifest_cannot_reuse_approval(change: str) -> None:
    checklist = _formal_checklist()
    evidence = checklist["acceptanceEvidence"]
    if change == "reference":
        evidence["technicalEvidence"]["gates"][0]["artifactScope"]["references"][0]["id"] = "different-unreviewed-result"
    elif change == "result":
        evidence["technicalEvidence"]["gates"][0]["result"]["summary"] = "changed result"
    elif change == "run":
        evidence["runId"] = "different-run"
    else:
        evidence["target"]["commitSha"] = "d" * 40
    assert _formal_errors(checklist)
    _rehash(evidence)
    assert _formal_errors(checklist)


def test_rehashing_both_files_and_rebinding_approval_still_requires_external_records() -> None:
    report = _uat_report()
    evidence = report["acceptanceEvidence"]
    evidence["technicalEvidence"]["gates"][0]["result"]["summary"] = "self-authored passed result"
    _rehash(evidence)
    checklist = _formal_checklist(report)
    assert validate_acceptance_evidence(checklist["acceptanceEvidence"], require_formal=True, now=NOW) == []
    assert any("trusted verification failed" in error for error in _formal_errors(checklist, report))


def test_verifier_checks_entire_approval_decision_not_only_role() -> None:
    checklist = _formal_checklist()
    checklist["acceptanceEvidence"]["formalApprovals"][0]["decisionId"] = "self-signed-new-decision"
    assert any("trusted verification failed" in error for error in _formal_errors(checklist))


@pytest.mark.parametrize("part", ["execution", "approval", "verification"])
@pytest.mark.parametrize("delta", [{"minutes": 6}, {"days": -31}])
def test_future_and_old_occurrences_are_rejected(part: str, delta: dict) -> None:
    checklist = _formal_checklist()
    evidence = checklist["acceptanceEvidence"]
    if part == "execution":
        evidence["technicalEvidence"]["gates"][0]["executedAt"] = _time(**delta)
    elif part == "approval":
        evidence["formalApprovals"][0]["approvedAt"] = _time(**delta)
    else:
        evidence["formalApprovals"][0]["authorityEvidence"]["verifiedAt"] = _time(**delta)
    assert _formal_errors(checklist)


@pytest.mark.parametrize("part", ["envelope", "gate", "approval"])
def test_expiry_boundary_is_exclusive(part: str) -> None:
    checklist = _formal_checklist()
    evidence = checklist["acceptanceEvidence"]
    node = evidence if part == "envelope" else (
        evidence["technicalEvidence"]["gates"][0] if part == "gate" else evidence["formalApprovals"][0]
    )
    node["expiresAt"] = _time()
    assert any("expired" in error for error in _formal_errors(checklist))


@pytest.mark.parametrize("bad_order", ["approval-before-run", "verification-before-approval", "execution-after-expiry"])
def test_chronology_is_checked(bad_order: str) -> None:
    checklist = _formal_checklist()
    evidence = checklist["acceptanceEvidence"]
    if bad_order == "approval-before-run":
        evidence["formalApprovals"][0]["approvedAt"] = _time(hours=-3)
    elif bad_order == "verification-before-approval":
        evidence["formalApprovals"][0]["authorityEvidence"]["verifiedAt"] = _time(hours=-3)
    else:
        evidence["technicalEvidence"]["gates"][0]["executedAt"] = _time(minutes=4)
        evidence["technicalEvidence"]["gates"][0]["expiresAt"] = _time(minutes=3)
    assert any("chronology" in error for error in _formal_errors(checklist))


def test_past_occurrences_and_timezone_z_are_valid() -> None:
    checklist = _formal_checklist()
    checklist["acceptanceEvidence"]["formalApprovals"][0]["approvedAt"] = "2026-09-03T11:00:00Z"
    assert validate_acceptance_evidence(checklist["acceptanceEvidence"], now=NOW) == []


def test_full_phase_scope_cannot_be_reduced_to_six_commands() -> None:
    report = _uat_report(LOCAL_SCOPE)
    assert validate_acceptance_evidence(report["acceptanceEvidence"], now=NOW) == []
    assert _formal_errors(_formal_checklist(report), report)
    evidence = report["acceptanceEvidence"]
    evidence["assessmentScope"] = PHASE01_SCOPE
    _rehash(evidence)
    assert any("missing gates" in error for error in validate_acceptance_evidence(evidence, now=NOW))
    assert len(SPEC_CRITERIA) == 32


class BrokenVerifier:
    def verify_technical(self, **kwargs):
        raise RuntimeError("source unavailable")

    def verify_approval(self, **kwargs):
        raise RuntimeError("source unavailable")


def test_unavailable_verifiers_fail_closed() -> None:
    assert formal_acceptance_errors(
        _formal_checklist(), _uat_report(), now=NOW,
        verifier=BrokenVerifier(), technical_verifier=BrokenVerifier(),
    )


def test_duplicate_json_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.json"
    path.write_text('{"status":"FAILED","status":"PASSED"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON"):
        read_json(path)


def test_sync_retains_legacy_approval_without_promoting_it(tmp_path: Path) -> None:
    source = tmp_path / "local-checklist.json"
    source.write_text(json.dumps({"signOffItems": [{"id": "bu-taxonomy-metrics", "status": "approved", "approvedBy": "Justin"}]}))
    payload = sync_checklist(SCRIPTS.parent, source)
    assert payload["signOffItems"][0]["status"] == "approved"
    assert payload["legacyApprovalRecords"][0]["trustStatus"] == "UNVERIFIED_LEGACY"
    assert _formal_errors(payload)


def test_tracked_historical_output_protected_even_for_sync(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / "history.json"
    path.write_text("{}")
    subprocess.run(["git", "add", "history.json"], cwd=tmp_path, check=True)
    with pytest.raises(ValueError, match="tracked evidence"):
        protect_output(path, allow_local_update=True)
    assert path.read_text() == "{}"


def test_read_only_uat_default_does_not_execute_or_write(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["ops_uat_handoff.py"])
    monkeypatch.setattr(uat_cli.subprocess, "run", lambda *args, **kwargs: pytest.fail("read-only command executed a subprocess"))
    assert uat_cli.main() == 0
    assert '"formalAcceptanceComplete": false' in capsys.readouterr().out


@pytest.mark.parametrize("junit_text", [
    "<testsuite/>",
    '<testsuite><testcase name="skipped"><skipped/></testcase></testsuite>',
    '<testsuite><testcase name="failed"><failure/></testcase></testsuite>',
])
def test_current_zero_exit_with_skipped_empty_or_failed_junit_is_not_passed(tmp_path, monkeypatch, junit_text) -> None:
    path = tmp_path / "current.xml"
    path.write_text(junit_text)
    monkeypatch.setattr(uat_cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="done", stderr=""))
    result = uat_cli._run_step("pytest", ["pytest", "exact-target"], tmp_path, TARGET, "run-001", junit=path)
    assert result["exitCode"] == 0
    assert result["status"] == "FAILED"
    assert result["command"] == "pytest exact-target"


def test_current_command_failure_cannot_use_existing_passed_report(tmp_path, monkeypatch) -> None:
    path = tmp_path / "result.json"
    path.write_text('{"passed":true}')
    monkeypatch.setattr(uat_cli.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failed"))
    result = uat_cli._run_step("live", ["current-command"], tmp_path, TARGET, "run-001", result_json=path)
    assert result["status"] == "FAILED"


def test_trusted_lab_and_formal_statuses_are_separate(tmp_path: Path) -> None:
    fake = FakeReadOnlyVerifier()
    audit = build_audit(
        tmp_path, uat_report=_uat_report(), checklist=_formal_checklist(), now=NOW,
        technical_verifier=fake,
    )
    assert audit["labSelfTest"]["accepted"]
    assert audit["automatedVerificationPassed"]
    assert not audit["formalAcceptanceComplete"]
    audit = build_audit(
        tmp_path, uat_report=_uat_report(), checklist=_formal_checklist(), now=NOW,
        technical_verifier=fake, verifier=fake,
    )
    assert audit["formalAcceptanceComplete"]
