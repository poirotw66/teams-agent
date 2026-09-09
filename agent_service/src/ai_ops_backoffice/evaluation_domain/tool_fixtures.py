from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from .errors import EvaluationDomainError, EvaluationNotFoundError, EvaluationValidationError
from .tool_fixture_models import (
    MockResponseSpec,
    ToolFixture,
    ToolFixtureVersion,
    calculate_tool_fixture_hash,
)


class ToolFixtureRepository:
    """Thread-safe in-memory repository for tool fixtures and their versions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fixtures: dict[str, ToolFixture] = {}
        self._versions: dict[tuple[str, int], ToolFixtureVersion] = {}

    def save_fixture(self, fixture: ToolFixture) -> None:
        with self._lock:
            self._fixtures[fixture.fixture_id] = fixture

    def get_fixture(self, fixture_id: str) -> ToolFixture | None:
        with self._lock:
            return self._fixtures.get(fixture_id)

    def list_fixtures(self, tenant_id: str | None = None) -> list[ToolFixture]:
        with self._lock:
            if tenant_id:
                return [f for f in self._fixtures.values() if f.tenant_id == tenant_id]
            return list(self._fixtures.values())

    def save_version(self, version: ToolFixtureVersion) -> None:
        with self._lock:
            self._versions[(version.fixture_id, version.version)] = version

    def get_version(self, fixture_id: str, version: int) -> ToolFixtureVersion | None:
        with self._lock:
            return self._versions.get((fixture_id, version))

    def list_versions(self, fixture_id: str) -> list[ToolFixtureVersion]:
        with self._lock:
            versions = [v for (f_id, _), v in self._versions.items() if f_id == fixture_id]
            return sorted(versions, key=lambda v: v.version)


class ToolFixtureService:
    """Service managing tool fixture lifecycles, versions, and validation."""

    def __init__(self, repository: ToolFixtureRepository | None = None) -> None:
        self._repository = repository or ToolFixtureRepository()
        self._seed_default_fixtures()

    @property
    def repository(self) -> ToolFixtureRepository:
        return self._repository

    def create_fixture(
        self,
        *,
        fixture_id: str,
        tenant_id: str,
        tool_name: str,
        created_by: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        mock_responses: list[dict[str, Any]] | None = None,
        default_response: dict[str, Any] | None = None,
        allowlist_enabled: bool = True,
        is_sandbox_safe: bool = True,
        is_mutation: bool = False,
    ) -> tuple[ToolFixture, ToolFixtureVersion]:
        existing = self._repository.get_fixture(fixture_id)
        if existing:
            raise EvaluationValidationError(f"Tool fixture '{fixture_id}' already exists")

        now = datetime.now(timezone.utc)
        parsed_mocks = tuple(
            MockResponseSpec(**resp) for resp in (mock_responses or [])
        )
        schema = input_schema or {}
        default_resp = default_response or {}

        content_hash = calculate_tool_fixture_hash(
            tool_name=tool_name,
            input_schema=schema,
            mock_responses=parsed_mocks,
            default_response=default_resp,
            allowlist_enabled=allowlist_enabled,
            is_sandbox_safe=is_sandbox_safe,
            is_mutation=is_mutation,
        )

        fixture = ToolFixture(
            fixture_id=fixture_id,
            tenant_id=tenant_id,
            tool_name=tool_name,
            current_version=1,
            created_by=created_by,
            created_at=now,
            updated_by=created_by,
            updated_at=now,
        )

        version_record = ToolFixtureVersion(
            fixture_id=fixture_id,
            version=1,
            schema_version="v1",
            tool_name=tool_name,
            description=description,
            input_schema=schema,
            mock_responses=parsed_mocks,
            default_response=default_resp,
            allowlist_enabled=allowlist_enabled,
            is_sandbox_safe=is_sandbox_safe,
            is_mutation=is_mutation,
            content_hash=content_hash,
            status="DRAFT",
            created_by=created_by,
            created_at=now,
        )

        self._repository.save_fixture(fixture)
        self._repository.save_version(version_record)
        return fixture, version_record

    def create_version(
        self,
        *,
        fixture_id: str,
        created_by: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        mock_responses: list[dict[str, Any]] | None = None,
        default_response: dict[str, Any] | None = None,
        allowlist_enabled: bool = True,
        is_sandbox_safe: bool = True,
        is_mutation: bool = False,
    ) -> ToolFixtureVersion:
        fixture = self._repository.get_fixture(fixture_id)
        if not fixture:
            raise EvaluationDomainError(f"Tool fixture '{fixture_id}' not found")

        existing_versions = self._repository.list_versions(fixture_id)
        next_version_num = max([v.version for v in existing_versions], default=0) + 1

        now = datetime.now(timezone.utc)
        parsed_mocks = tuple(
            MockResponseSpec(**resp) for resp in (mock_responses or [])
        )
        schema = input_schema or {}
        default_resp = default_response or {}

        content_hash = calculate_tool_fixture_hash(
            tool_name=fixture.tool_name,
            input_schema=schema,
            mock_responses=parsed_mocks,
            default_response=default_resp,
            allowlist_enabled=allowlist_enabled,
            is_sandbox_safe=is_sandbox_safe,
            is_mutation=is_mutation,
        )

        version_record = ToolFixtureVersion(
            fixture_id=fixture_id,
            version=next_version_num,
            schema_version="v1",
            tool_name=fixture.tool_name,
            description=description,
            input_schema=schema,
            mock_responses=parsed_mocks,
            default_response=default_resp,
            allowlist_enabled=allowlist_enabled,
            is_sandbox_safe=is_sandbox_safe,
            is_mutation=is_mutation,
            content_hash=content_hash,
            status="DRAFT",
            created_by=created_by,
            created_at=now,
        )
        self._repository.save_version(version_record)
        return version_record

    def approve_version(
        self,
        *,
        fixture_id: str,
        version: int,
        approved_by: str,
        reason: str | None = None,
    ) -> ToolFixtureVersion:
        v = self._repository.get_version(fixture_id, version)
        if not v:
            raise EvaluationNotFoundError(f"Fixture version '{fixture_id}:v{version}' not found")

        if v.created_by == approved_by:
            raise EvaluationValidationError(
                f"Author '{v.created_by}' cannot approve their own tool fixture version"
            )

        if v.status != "DRAFT":
            raise EvaluationValidationError(
                f"Cannot approve fixture in status '{v.status}'"
            )

        now = datetime.now(timezone.utc)
        approved = ToolFixtureVersion(
            fixture_id=v.fixture_id,
            version=v.version,
            schema_version=v.schema_version,
            tool_name=v.tool_name,
            description=v.description,
            input_schema=v.input_schema,
            mock_responses=v.mock_responses,
            default_response=v.default_response,
            allowlist_enabled=v.allowlist_enabled,
            is_sandbox_safe=v.is_sandbox_safe,
            is_mutation=v.is_mutation,
            content_hash=v.content_hash,
            status="APPROVED",
            etag=v.etag + 1,
            created_by=v.created_by,
            created_at=v.created_at,
            approved_by=approved_by,
            approved_at=now,
            approval_reason=reason,
        )
        self._repository.save_version(approved)

        # Update fixture current version
        fixture = self._repository.get_fixture(fixture_id)
        if fixture and fixture.current_version <= version:
            updated_fixture = ToolFixture(
                fixture_id=fixture.fixture_id,
                tenant_id=fixture.tenant_id,
                tool_name=fixture.tool_name,
                current_version=version,
                created_by=fixture.created_by,
                created_at=fixture.created_at,
                updated_by=approved_by,
                updated_at=now,
            )
            self._repository.save_fixture(updated_fixture)

        return approved

    def execute_mock_tool(
        self,
        *,
        fixture_id: str,
        version: int | None = None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Matches arguments against fixture mock responses or returns default response."""
        fixture = self._repository.get_fixture(fixture_id)
        target_version = version or (fixture.current_version if fixture else 1)
        v = self._repository.get_version(fixture_id, target_version)
        if not v:
            return {"status": "error", "error": f"Tool fixture '{fixture_id}' not found"}

        # Search mock responses for parameter match
        for mock in v.mock_responses:
            if not mock.match_parameters:
                continue
            is_match = True
            for k, expected_val in mock.match_parameters.items():
                if arguments.get(k) != expected_val:
                    is_match = False
                    break
            if is_match:
                if mock.is_error:
                    return {
                        "status": "error",
                        "error_code": mock.error_status or "TOOL_EXECUTION_ERROR",
                        "error_message": mock.error_message or "Simulated tool failure",
                    }
                return mock.response_payload

        # Return default response
        return v.default_response or {"status": "success", "data": {}}

    def _seed_default_fixtures(self) -> None:
        """Seeds baseline tool fixtures for IT / HR enterprise scenarios."""
        now = datetime.now(timezone.utc)
        defaults = [
            (
                "fixture-leave-balance",
                "query_leave_balance",
                "查詢同仁特休與補休餘額",
                {"user_id": {"type": "string"}},
                [
                    MockResponseSpec(
                        match_parameters={"user_id": "E12345"},
                        response_payload={"user_id": "E12345", "annual_leave_days": 12, "comp_leave_hours": 8},
                    ),
                    MockResponseSpec(
                        match_parameters={"user_id": "M88888"},
                        response_payload={"user_id": "M88888", "annual_leave_days": 21, "comp_leave_hours": 16},
                    ),
                ],
                {"user_id": "unknown", "annual_leave_days": 0, "comp_leave_hours": 0},
                False,
            ),
            (
                "fixture-ticket-status",
                "query_it_ticket_status",
                "查詢IT服務工單進度",
                {"ticket_id": {"type": "string"}},
                [
                    MockResponseSpec(
                        match_parameters={"ticket_id": "INC-9901"},
                        response_payload={"ticket_id": "INC-9901", "status": "IN_PROGRESS", "assigned_to": "IT-Helpdesk"},
                    )
                ],
                {"status": "NOT_FOUND"},
                False,
            ),
            (
                "fixture-hr-policy",
                "query_hr_policy",
                "查詢人資出勤與差旅政策",
                {"topic": {"type": "string"}},
                [
                    MockResponseSpec(
                        match_parameters={"topic": "remote_work"},
                        response_payload={"topic": "remote_work", "rules": "每週最多兩天申請遠距，需主管核准。"},
                    )
                ],
                {"topic": "general", "rules": "請參照公司標準出勤手冊。"},
                False,
            ),
            (
                "fixture-create-ticket",
                "create_ticket",
                "建立IT支援工單（受控沙盒模擬）",
                {"user_id": {"type": "string"}, "summary": {"type": "string"}},
                [],
                {"status": "CREATED", "ticket_id": "SIM-TICKET-001"},
                True,
            ),
        ]

        for fix_id, tool_name, desc, schema, mocks, default_resp, is_mut in defaults:
            if not self._repository.get_fixture(fix_id):
                fix = ToolFixture(
                    fixture_id=fix_id,
                    tenant_id="default",
                    tool_name=tool_name,
                    current_version=1,
                    created_by="system",
                    created_at=now,
                    updated_by="system",
                    updated_at=now,
                )
                ver = ToolFixtureVersion(
                    fixture_id=fix_id,
                    version=1,
                    schema_version="v1",
                    tool_name=tool_name,
                    description=desc,
                    input_schema=schema,
                    mock_responses=tuple(mocks),
                    default_response=default_resp,
                    allowlist_enabled=True,
                    is_sandbox_safe=True,
                    is_mutation=is_mut,
                    content_hash="seed-hash-" + fix_id,
                    status="APPROVED",
                    created_by="system",
                    created_at=now,
                    approved_by="admin",
                    approved_at=now,
                )
                self._repository.save_fixture(fix)
                self._repository.save_version(ver)
