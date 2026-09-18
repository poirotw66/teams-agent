"""Tool fixture lifecycle service and stable public re-exports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .errors import EvaluationDomainError, EvaluationNotFoundError, EvaluationValidationError
from .tool_fixture_models import (
    MockResponseSpec,
    ToolCallTrace,
    ToolFixture,
    ToolFixtureVersion,
    calculate_tool_fixture_hash,
)
from .tool_fixture_repository import (
    FileToolFixtureRepository,
    FirestoreToolFixtureRepository,
    ToolFixtureRepository,
)
from .tool_fixture_sandbox import SIDE_EFFECT_TOOLS, execute_sandbox_tool
from .tool_fixture_seeds import seed_default_tool_fixtures

__all__ = [
    "SIDE_EFFECT_TOOLS",
    "FileToolFixtureRepository",
    "FirestoreToolFixtureRepository",
    "ToolFixtureRepository",
    "ToolFixtureService",
]


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
        parsed_mocks = tuple(MockResponseSpec(**resp) for resp in (mock_responses or []))
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
        parsed_mocks = tuple(MockResponseSpec(**resp) for resp in (mock_responses or []))
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
            raise EvaluationValidationError(f"Cannot approve fixture in status '{v.status}'")

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
        attempt: int = 1,
    ) -> dict[str, Any]:
        """Match arguments against fixture mock responses or return default response."""
        trace = self.execute_sandbox_tool(
            tool_name="",
            arguments=arguments,
            fixture_id=fixture_id,
            version=version,
            attempt=attempt,
        )
        if trace.is_error:
            return {
                "status": "error",
                "error_code": "TOOL_EXECUTION_ERROR",
                "error_message": trace.error_message or "Simulated tool failure",
            }
        return trace.result or {"status": "success", "data": {}}

    def execute_sandbox_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        fixture_id: str | None = None,
        version: int | None = None,
        call_id: str | None = None,
        attempt: int = 1,
    ) -> ToolCallTrace:
        """Execute a tool within the safe evaluation sandbox."""
        return execute_sandbox_tool(
            self._repository,
            tool_name=tool_name,
            arguments=arguments,
            fixture_id=fixture_id,
            version=version,
            call_id=call_id,
            attempt=attempt,
        )

    def _seed_default_fixtures(self) -> None:
        seed_default_tool_fixtures(self._repository)
