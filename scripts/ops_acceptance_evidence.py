"""Schema, immutable manifest linkage and separate trusted acceptance verification.

No network, dispatch, credential lookup or approval creation occurs here.
The caller supplies organisation-managed read-only verification adapters.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

# Keep these standalone CLIs usable with the host Python (including 3.9/3.10).
UTC = timezone.utc  # noqa: UP017

SCHEMA_VERSION = "v2"
LAB_SELF_TEST = "LAB_SELF_TEST"
FORMAL_ACCEPTANCE = "FORMAL_ACCEPTANCE"
LOCAL_SCOPE = "LOCAL_AUTOMATED_BUNDLE"
PHASE01_SCOPE = "PHASE_0_1_ACCEPTANCE_AND_DOD"
REQUIRED_REVIEWER_ROLES = ("BU", "IT", "Security/Legal", "BU/Knowledge Admin")
REQUIRED_TECHNICAL_GATES = (
    "pytest", "backup_verify", "phase0_deliverables",
    "terraform_validate", "terraform_plan", "daily_reconciliation",
)
# Original spec clauses, not inferred coverage from test filenames.
SPEC_CRITERIA = {
    "P0-14.1": "Link conversation/request/issue/route/source/feedback/handoff/cost IDs",
    "P0-14.2": "Repeated eventId does not increase statistics",
    "P0-14.3": "Document conversation, issue, hit, resolution and cost definitions",
    "P0-14.4": "20–50 versioned, owned seed issue types reviewed by BU",
    "P0-14.5": "Keep and correct other.unclassified occurrences",
    "P0-14.6": "Deny unauthorized unmasked conversations and sensitive exports",
    "P0-14.7": "Credentials absent from Analytics, Audit and application logs",
    "P0-14.8": "Exercise one-year TTL/deletion with shortened test expiry",
    "P0-14.9": "High-risk actions fail closed when Audit fails",
    "P0-14.10": "Isolate dev/test/poc/prod data and Terraform states",
    "P0-17.1": "BU, IT and Security/Legal jointly approve metrics and governance",
    "P0-17.2": "Taxonomy usable by structured output or mapping",
    "P0-17.3": "Key paths emit valid, linkable, idempotent events",
    "P0-17.4": "Storage, TTL, masking, authorization and Audit tests pass",
    "P0-17.5": "Terraform plan/inventory handoff; no unexplained formal manual operations",
    "P0-17.6": "Phase 1 reuses core IDs, metrics, roles and retention contracts",
    "P1-12.1": "Reconcile day/week/month counts against deduplicated events",
    "P1-12.2": "Trace model token/cost to pricing version; unknown is not zero",
    "P1-12.3": "Six-month authorized actor search; masked/403 for unauthorized users",
    "P1-12.4": "Trace conversations to issue, route, FAQ/document, feedback and handoff/ticket",
    "P1-12.5": "Issue periods: day/week/month/six months/custom",
    "P1-12.6": "Document hits, feedback, issues and conversations",
    "P1-12.7": "Markdown/text-PDF governance, parse, test, review, publish and index",
    "P1-12.8": "Recognize simulated LLM, RAG and Ticket anomalies",
    "P1-12.9": "Exports preserve permission/masking and Audit",
    "P1-12.10": "Every KPI drills down or links to its definition",
    "P1-15.1": "Phase 1 metrics use Phase 0 definitions and sample reconciliation",
    "P1-15.2": "Role, scope, masking, unmask and export security tests",
    "P1-15.3": "Loading/empty/error/forbidden states across all seven modules",
    "P1-15.4": "Markdown/PDF and existing publishing end-to-end UAT",
    "P1-15.5": "Analytics delay/data quality/health monitoring and runbook",
    "P1-15.6": "BU completes negative-feedback to conversation/issue/source task in 15 minutes",
}
# Joint governance approval is evaluated separately by all four approval decisions.
REQUIRED_PHASE01_GATES = (*REQUIRED_TECHNICAL_GATES, *(
    key for key in SPEC_CRITERIA if key != "P0-17.1"
))
MAX_EVIDENCE_AGE = timedelta(days=30)
MAX_CLOCK_SKEW = timedelta(minutes=5)


class TrustedTechnicalVerifier(Protocol):
    """Validate manifest against trusted runner records and actual artifact bytes.

    Verify execution/result/coverage (including no skipped tests), deployment
    identity, hashes and source provenance. A self-reported PASSED is insufficient.
    """

    def verify_technical(
        self, *, manifest: dict[str, Any], manifest_sha256: str, now: datetime,
    ) -> tuple[bool, str]: ...


class TrustedApprovalVerifier(Protocol):
    """Validate the entire decision, not just membership in a reviewer role.

    Verify decision ID/status, reviewer authority for this scope, dates, revocation,
    and approval of this exact run/manifest and governance contract. Do not trust
    sourceSystem/verificationStatus strings or a name supplied by the caller.
    """

    def verify_approval(
        self, *, approval: dict[str, Any], manifest: dict[str, Any],
        manifest_sha256: str, now: datetime,
    ) -> tuple[bool, str]: ...


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value: object, field: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not value or not all(_text(item) for item in value):
        errors.append(f"{field} must be a non-empty string list")
        return []
    if len(set(value)) != len(value):
        errors.append(f"{field} contains duplicates")
    return value


def _records(value: object, key: str, field: str, errors: list[str]) -> dict[str, dict]:
    records: dict[str, dict] = {}
    if not isinstance(value, list) or not value:
        errors.append(f"{field} must be a non-empty object list")
        return records
    for record in value:
        if not isinstance(record, dict) or not _text(record.get(key)):
            errors.append(f"{field} contains malformed {key}")
            continue
        identifier = record[key]
        if identifier in records:
            errors.append(f"{field} duplicate {key}: {identifier}")
            continue
        records[identifier] = record
    return records


def _timestamp(value: object, field: str, errors: list[str]) -> datetime | None:
    if not _text(value):
        errors.append(f"{field} is required")
        return None
    try:
        # Host Python 3.9/3.10 does not accept the Z suffix.
        parsed = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
    except ValueError:
        errors.append(f"{field} must be ISO-8601")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{field} must include a timezone")
        return None
    return parsed.astimezone(UTC)


def _occurred(value: object, field: str, errors: list[str], now: datetime) -> datetime | None:
    parsed = _timestamp(value, field, errors)
    if parsed is not None:
        if parsed > now + MAX_CLOCK_SKEW:
            errors.append(f"{field} is in the future beyond clock skew")
        if parsed < now - MAX_EVIDENCE_AGE:
            errors.append(f"{field} exceeds the maximum evidence age")
    return parsed


def _expiry(value: object, field: str, errors: list[str], now: datetime) -> datetime | None:
    parsed = _timestamp(value, field, errors)
    if parsed is not None and parsed <= now:
        errors.append(f"{field} is expired")
    return parsed


def _ordered(start: datetime | None, end: datetime | None, field: str, errors: list[str]) -> None:
    if start is not None and end is not None and start > end:
        errors.append(f"{field} chronology is invalid")


def target_identity(target: object) -> tuple[str, str, str, str] | None:
    if not isinstance(target, dict) or not isinstance(target.get("artifactIdentity"), dict):
        return None
    values = (target.get("environment"), target.get("commitSha"),
              target["artifactIdentity"].get("kind"), target["artifactIdentity"].get("value"))
    if not all(_text(value) for value in values):
        return None
    if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", values[1]) is None:
        return None
    return values


def technical_manifest(evidence: dict[str, Any]) -> dict[str, Any]:
    """Exact canonical digest input. Classification/approvals intentionally excluded."""
    return {key: evidence.get(key) for key in (
        "schemaVersion", "assessmentScope", "target", "runId", "expiresAt", "technicalEvidence",
    )}


def manifest_sha256(evidence: dict[str, Any]) -> str:
    encoded = json.dumps(technical_manifest(evidence), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_gates(evidence: dict, now: datetime, errors: list[str]) -> dict[str, dict]:
    technical = evidence.get("technicalEvidence")
    if not isinstance(technical, dict):
        errors.append("technicalEvidence must be an object")
        return {}
    required = _strings(technical.get("requiredGateIds"), "requiredGateIds", errors)
    baseline = REQUIRED_PHASE01_GATES if evidence.get("assessmentScope") == PHASE01_SCOPE else REQUIRED_TECHNICAL_GATES
    missing = set(baseline).difference(required)
    if missing:
        errors.append("requiredGateIds missing gates: " + ", ".join(sorted(missing)))
    gates = _records(technical.get("gates"), "id", "technical.gates", errors)
    if set(gates) != set(required):
        errors.append("technical.gates and requiredGateIds must match exactly")
    for gate_id, gate in gates.items():
        prefix = f"technical gate {gate_id}"
        if gate.get("status") != "PASSED":
            errors.append(f"{prefix} is not PASSED")
        if not _text(gate.get("command")) or not _text(gate.get("cwd")):
            errors.append(f"{prefix} missing executed command/cwd")
        if type(gate.get("exitCode")) is not int or gate["exitCode"] != 0:
            errors.append(f"{prefix} exitCode is not integer 0")
        result = gate.get("result")
        if not isinstance(result, dict) or not _text(result.get("summary")):
            errors.append(f"{prefix} missing command result summary")
        executed = _occurred(gate.get("executedAt"), f"{prefix}.executedAt", errors, now)
        expires = _expiry(gate.get("expiresAt"), f"{prefix}.expiresAt", errors, now)
        envelope_expiry = _timestamp(evidence.get("expiresAt"), "evidence.expiresAt", errors)
        _ordered(executed, expires, prefix, errors)
        _ordered(executed, envelope_expiry, prefix, errors)
        scope = gate.get("artifactScope")
        if not isinstance(scope, dict):
            errors.append(f"{prefix} missing artifact scope")
            continue
        if scope.get("target") != evidence.get("target"):
            errors.append(f"{prefix} artifact scope does not match acceptance target")
        refs = _records(scope.get("references"), "id", f"{prefix}.references", errors)
        for ref in refs.values():
            if not isinstance(ref.get("sha256"), str) or re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]) is None:
                errors.append(f"{prefix} artifact reference requires sha256")
    return gates


def _validate_approvals(evidence: dict, gates: dict[str, dict], now: datetime, errors: list[str]) -> None:
    roles = _strings(evidence.get("requiredReviewerRoles"), "requiredReviewerRoles", errors)
    if set(roles) != set(REQUIRED_REVIEWER_ROLES):
        errors.append("requiredReviewerRoles must contain every required role exactly")
    approvals = _records(evidence.get("formalApprovals"), "role", "formalApprovals", errors)
    if set(approvals) != set(roles):
        errors.append("formalApprovals must match requiredReviewerRoles")
    for role in REQUIRED_REVIEWER_ROLES:
        approval = approvals.get(role)
        prefix = f"formal approval {role}"
        if approval is None:
            errors.append(f"{prefix} is missing")
            continue
        if approval.get("status") != "APPROVED" or not _text(approval.get("decisionId")):
            errors.append(f"{prefix} missing APPROVED decision/decisionId")
        if approval.get("assessmentScope") != PHASE01_SCOPE:
            errors.append(f"{prefix} scope must be {PHASE01_SCOPE}")
        reviewer = approval.get("reviewer")
        if not isinstance(reviewer, dict) or not all(_text(reviewer.get(key)) for key in ("subjectId", "displayName")):
            errors.append(f"{prefix} missing reviewer identity")
        if approval.get("reviewedTarget") != evidence.get("target"):
            errors.append(f"{prefix} reviewedTarget mismatch")
        if approval.get("reviewedManifestSha256") != evidence.get("technicalManifestSha256"):
            errors.append(f"{prefix} reviewed manifest mismatch")
        approved = _occurred(approval.get("approvedAt"), f"{prefix}.approvedAt", errors, now)
        expires = _expiry(approval.get("expiresAt"), f"{prefix}.expiresAt", errors, now)
        _ordered(approved, expires, prefix, errors)
        _ordered(approved, _timestamp(evidence.get("expiresAt"), "evidence.expiresAt", errors), prefix, errors)
        for gate in gates.values():
            executed = _timestamp(gate.get("executedAt"), "gate.executedAt", errors)
            gate_expiry = _timestamp(gate.get("expiresAt"), "gate.expiresAt", errors)
            _ordered(executed, approved, f"{prefix} before execution", errors)
            _ordered(approved, gate_expiry, f"{prefix} after gate expiry", errors)
        authority = approval.get("authorityEvidence")
        if not isinstance(authority, dict):
            errors.append(f"{prefix} missing authorityEvidence")
            continue
        if not all(_text(authority.get(key)) for key in ("sourceSystem", "sourceRecordId")):
            errors.append(f"{prefix} missing authority source reference")
        verified = _occurred(authority.get("verifiedAt"), f"{prefix}.verifiedAt", errors, now)
        _ordered(approved, verified, f"{prefix} verification before decision", errors)
        _ordered(verified, expires, f"{prefix} verification after expiry", errors)


def validate_acceptance_evidence(
    evidence: object, *, require_formal: bool = False, now: datetime | None = None,
) -> list[str]:
    """Schema and integrity only. Empty errors do NOT establish trusted execution."""
    errors: list[str] = []
    current = now or datetime.now(UTC)
    if not isinstance(current, datetime) or current.tzinfo is None:
        return ["validation clock must be timezone-aware"]
    if not isinstance(evidence, dict):
        return ["acceptanceEvidence is required"]
    if evidence.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("acceptanceEvidence.schemaVersion must be v2")
    classification = evidence.get("classification")
    if classification not in (LAB_SELF_TEST, FORMAL_ACCEPTANCE):
        errors.append("invalid acceptance classification")
    if require_formal and classification != FORMAL_ACCEPTANCE:
        errors.append("evidence is not FORMAL_ACCEPTANCE")
    scope = evidence.get("assessmentScope")
    if scope not in (LOCAL_SCOPE, PHASE01_SCOPE):
        errors.append("invalid assessmentScope")
    if (require_formal or classification == FORMAL_ACCEPTANCE) and scope != PHASE01_SCOPE:
        errors.append(f"formal acceptance requires {PHASE01_SCOPE}")
    if target_identity(evidence.get("target")) is None:
        errors.append("target requires environment, full commitSha and artifactIdentity.kind/value")
    if not _text(evidence.get("runId")):
        errors.append("runId is required")
    _expiry(evidence.get("expiresAt"), "acceptanceEvidence.expiresAt", errors, current)
    try:
        digest = manifest_sha256(evidence)
    except (TypeError, ValueError, OverflowError):
        errors.append("technical manifest is not canonical JSON")
    else:
        if evidence.get("technicalManifestSha256") != digest:
            errors.append("technical manifest digest mismatch")
    gates = _validate_gates(evidence, current, errors)
    if classification == FORMAL_ACCEPTANCE:
        _validate_approvals(evidence, gates, current, errors)
    return errors


def _verification_result(result: object, label: str) -> list[str]:
    if not isinstance(result, tuple) or len(result) != 2 or result[0] is not True or not _text(result[1]):
        return [f"{label} trusted verification failed or unavailable"]
    return []


def technical_verification_errors(
    evidence: object, *, technical_verifier: TrustedTechnicalVerifier | None = None,
    now: datetime | None = None,
) -> list[str]:
    errors = validate_acceptance_evidence(evidence, now=now)
    if errors:
        return errors
    if technical_verifier is None:
        return ["technical evidence untrusted: organisation runner/artifact verifier pending"]
    current = now or datetime.now(UTC)
    try:
        result = technical_verifier.verify_technical(
            manifest=copy.deepcopy(technical_manifest(evidence)),
            manifest_sha256=evidence["technicalManifestSha256"], now=current,
        )
    except Exception:  # Fail closed on unavailable/broken adapters; no credential details in output.
        return ["technical evidence verifier unavailable"]
    return _verification_result(result, "technical evidence")


def formal_acceptance_errors(
    checklist: object, uat_report: object, *, now: datetime | None = None,
    verifier: TrustedApprovalVerifier | None = None,
    technical_verifier: TrustedTechnicalVerifier | None = None,
) -> list[str]:
    evidence = checklist.get("acceptanceEvidence") if isinstance(checklist, dict) else None
    uat = uat_report.get("acceptanceEvidence") if isinstance(uat_report, dict) else None
    errors = validate_acceptance_evidence(evidence, require_formal=True, now=now)
    errors += validate_acceptance_evidence(uat, now=now)
    if isinstance(evidence, dict) and isinstance(uat, dict):
        if evidence.get("target") != uat.get("target"):
            errors.append("formal acceptance target does not match executed UAT target")
        if uat.get("classification") != LAB_SELF_TEST:
            errors.append("UAT evidence must be LAB_SELF_TEST")
        if evidence.get("technicalManifestSha256") != uat.get("technicalManifestSha256"):
            errors.append("formal and UAT technical manifests differ")
    if errors:
        return errors
    errors += technical_verification_errors(uat, technical_verifier=technical_verifier, now=now)
    if verifier is None:
        return [*errors, "formal approval trusted verification failed: organisation decision verifier pending"]
    current = now or datetime.now(UTC)
    for approval in evidence["formalApprovals"]:
        try:
            result = verifier.verify_approval(
                approval=copy.deepcopy(approval),
                manifest=copy.deepcopy(technical_manifest(evidence)),
                manifest_sha256=evidence["technicalManifestSha256"], now=current,
            )
        except Exception:
            errors.append(f"formal approval {approval['role']} verifier unavailable")
            continue
        errors += _verification_result(result, f"formal approval {approval['role']}")
    return errors


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(payload, dict):
        raise TypeError("JSON root must be an object")
    return payload


def protect_output(path: Path, *, allow_local_update: bool = False) -> None:
    """Never overwrite tracked history. Only explicit local sync/review can update."""
    resolved = path.resolve()
    if resolved.exists() and not allow_local_update:
        raise ValueError(f"Output already exists; select a new path: {path}")
    for parent in (resolved.parent, *resolved.parents):
        if (parent / ".git").exists():
            completed = subprocess.run(
                ["git", "ls-files", "--error-unmatch", "--", str(resolved.relative_to(parent))],
                cwd=parent, capture_output=True, text=True, check=False,
            )
            if completed.returncode == 0:
                raise ValueError(f"Refusing to overwrite tracked evidence: {path}")
            if completed.returncode not in (0, 1):
                raise ValueError("Cannot establish whether output is tracked")
            break


def write_json(path: Path, payload: dict, *, allow_local_update: bool = False) -> None:
    protect_output(path, allow_local_update=allow_local_update)
    path.parent.mkdir(parents=True, exist_ok=True)
    # New files are exclusive; local sync/approval are explicit compatibility operations.
    with path.open("w" if allow_local_update else "x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
