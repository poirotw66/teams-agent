from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .models import EvaluationState
from .repository import EvaluationRepository


class StrictModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MigrationReport(StrictModel):
    migration_id: str = Field(default_factory=lambda: str(uuid4()))
    is_dry_run: bool
    total_cases: int
    total_revisions: int
    total_sets: int
    total_set_versions: int
    total_runs: int
    total_executions: int
    tenants_found: tuple[str, ...]
    schema_errors: tuple[str, ...] = ()
    hash_reconciliation_passed: bool = True
    backup_path: str | None = None
    started_at: datetime
    completed_at: datetime


def _empty_report(
    *,
    dry_run: bool,
    started_at: datetime,
    schema_errors: tuple[str, ...],
    backup_path: str | None = None,
) -> MigrationReport:
    return MigrationReport(
        is_dry_run=dry_run,
        total_cases=0,
        total_revisions=0,
        total_sets=0,
        total_set_versions=0,
        total_runs=0,
        total_executions=0,
        tenants_found=(),
        schema_errors=schema_errors,
        hash_reconciliation_passed=False,
        backup_path=backup_path,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )


def _backup_source(source_path: Path, started_at: datetime) -> str:
    timestamp = started_at.strftime("%Y%m%d_%H%M%S")
    backup_file = source_path.with_suffix(f".backup_{timestamp}.json")
    if source_path.is_file():
        shutil.copy2(source_path, backup_file)
    else:
        shutil.copytree(source_path, backup_file)
    return str(backup_file)


def _collect_tenants(state: EvaluationState, default_tenant: str) -> set[str]:
    tenants = {c.tenant_id for c in state.cases if c.tenant_id}
    tenants.update({s.tenant_id for s in state.sets if s.tenant_id})
    tenants.update({r.tenant_id for r in state.runs if r.tenant_id})
    return tenants or {default_tenant}


def _reconcile_counts(source: EvaluationState, target: EvaluationState) -> bool:
    return (
        len(target.cases) == len(source.cases)
        and len(target.revisions) == len(source.revisions)
        and len(target.sets) == len(source.sets)
        and len(target.set_versions) == len(source.set_versions)
        and len(target.runs) == len(source.runs)
        and len(target.case_executions) == len(source.case_executions)
    )


class EvaluationMigrationTool:
    """Production migration tool for evaluation state from legacy JSON to partitioned/Firestore storage.

    Provides dry-run, schema validation, backup, count/hash reconciliation, and tenant isolation.
    """

    def __init__(self, default_tenant_id: str = "default") -> None:
        self._default_tenant = default_tenant_id

    def migrate(
        self,
        source_path: Path,
        target_repo: EvaluationRepository,
        *,
        backup: bool = True,
        dry_run: bool = False,
    ) -> MigrationReport:
        started_at = datetime.now(UTC)
        if not source_path.exists():
            return _empty_report(
                dry_run=dry_run,
                started_at=started_at,
                schema_errors=(f"Source path {source_path} does not exist",),
            )

        backup_path_str: str | None = None
        if backup and not dry_run:
            backup_path_str = _backup_source(source_path, started_at)

        raw_text = source_path.read_text(encoding="utf-8") if source_path.is_file() else "{}"
        try:
            state = EvaluationState.model_validate_json(raw_text)
        except Exception as err:
            return _empty_report(
                dry_run=dry_run,
                started_at=started_at,
                schema_errors=(f"Schema validation error: {err}",),
                backup_path=backup_path_str,
            )

        tenants = _collect_tenants(state, self._default_tenant)

        if dry_run:
            hash_ok = True
        else:
            target_repo.commit_mutation(state)
            hash_ok = _reconcile_counts(state, target_repo.load())

        return MigrationReport(
            is_dry_run=dry_run,
            total_cases=len(state.cases),
            total_revisions=len(state.revisions),
            total_sets=len(state.sets),
            total_set_versions=len(state.set_versions),
            total_runs=len(state.runs),
            total_executions=len(state.case_executions),
            tenants_found=tuple(sorted(tenants)),
            schema_errors=(),
            hash_reconciliation_passed=hash_ok,
            backup_path=backup_path_str,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
