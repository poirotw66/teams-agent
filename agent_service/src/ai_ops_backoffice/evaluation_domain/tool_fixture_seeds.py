"""Default IT/HR tool fixture seed builders for evaluation sandboxes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from .tool_fixture_models import MockResponseSpec, ToolFixture, ToolFixtureVersion

__all__ = ["seed_default_tool_fixtures"]


class _FixtureSeedRepository(Protocol):
    def get_fixture(self, fixture_id: str) -> ToolFixture | None: ...

    def save_fixture(self, fixture: ToolFixture) -> None: ...

    def save_version(self, version: ToolFixtureVersion) -> None: ...


def _default_fixture_specs() -> list[tuple[Any, ...]]:
    return [
        (
            "fixture-leave-balance",
            "query_leave_balance",
            "查詢同仁特休與補休餘額",
            {"user_id": {"type": "string"}},
            [
                MockResponseSpec(
                    match_parameters={"user_id": "E12345"},
                    response_payload={
                        "user_id": "E12345",
                        "annual_leave_days": 12,
                        "comp_leave_hours": 8,
                    },
                ),
                MockResponseSpec(
                    match_parameters={"user_id": "M88888"},
                    response_payload={
                        "user_id": "M88888",
                        "annual_leave_days": 21,
                        "comp_leave_hours": 16,
                    },
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
                    response_payload={
                        "ticket_id": "INC-9901",
                        "status": "IN_PROGRESS",
                        "assigned_to": "IT-Helpdesk",
                    },
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
                    response_payload={
                        "topic": "remote_work",
                        "rules": "每週最多兩天申請遠距，需主管核准。",
                    },
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


def _persist_seed_fixture(
    repository: _FixtureSeedRepository,
    *,
    fixture_id: str,
    tool_name: str,
    description: str,
    input_schema: dict[str, Any],
    mocks: list[MockResponseSpec],
    default_response: dict[str, Any],
    is_mutation: bool,
    now: datetime,
) -> None:
    fixture = ToolFixture(
        fixture_id=fixture_id,
        tenant_id="default",
        tool_name=tool_name,
        current_version=1,
        created_by="system",
        created_at=now,
        updated_by="system",
        updated_at=now,
    )
    version = ToolFixtureVersion(
        fixture_id=fixture_id,
        version=1,
        schema_version="v1",
        tool_name=tool_name,
        description=description,
        input_schema=input_schema,
        mock_responses=tuple(mocks),
        default_response=default_response,
        allowlist_enabled=True,
        is_sandbox_safe=True,
        is_mutation=is_mutation,
        content_hash="seed-hash-" + fixture_id,
        status="APPROVED",
        created_by="system",
        created_at=now,
        approved_by="admin",
        approved_at=now,
    )
    repository.save_fixture(fixture)
    repository.save_version(version)


def seed_default_tool_fixtures(repository: _FixtureSeedRepository) -> None:
    """Seed baseline tool fixtures for IT / HR enterprise scenarios."""
    now = datetime.now(timezone.utc)
    for (
        fixture_id,
        tool_name,
        description,
        schema,
        mocks,
        default_response,
        is_mutation,
    ) in _default_fixture_specs():
        if repository.get_fixture(fixture_id):
            continue
        _persist_seed_fixture(
            repository,
            fixture_id=fixture_id,
            tool_name=tool_name,
            description=description,
            input_schema=schema,
            mocks=mocks,
            default_response=default_response,
            is_mutation=is_mutation,
            now=now,
        )
