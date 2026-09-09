from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from agent_service.operations.access import ActorContext

from ..evaluation_domain.tool_fixtures import ToolFixtureService


class CreateToolFixturePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixture_id: str
    tool_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    mock_responses: list[dict[str, Any]] = Field(default_factory=list)
    default_response: dict[str, Any] = Field(default_factory=dict)
    allowlist_enabled: bool = True
    is_sandbox_safe: bool = True
    is_mutation: bool = False


class CreateFixtureVersionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    mock_responses: list[dict[str, Any]] = Field(default_factory=list)
    default_response: dict[str, Any] = Field(default_factory=dict)
    allowlist_enabled: bool = True
    is_sandbox_safe: bool = True
    is_mutation: bool = False


class ApproveFixtureVersionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = None


def register_tool_fixture_routes(
    app: FastAPI,
    fixture_service: ToolFixtureService,
    current_actor: Callable[..., ActorContext],
    require_capability: Callable[[ActorContext, str], None],
) -> None:
    router = APIRouter(prefix="/api/evaluations/tool-fixtures", tags=["evaluations.tool_fixtures"])

    @router.get("")
    async def list_tool_fixtures(actor: ActorContext = Depends(current_actor)) -> list[dict[str, Any]]:
        require_capability(actor, "ops.evals.read")
        fixtures = fixture_service.repository.list_fixtures()
        return [f.model_dump(mode="json") for f in fixtures]

    @router.post("")
    async def create_tool_fixture(
        payload: CreateToolFixturePayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        tenant_id = actor.tenant_id or "default"
        fix, ver = fixture_service.create_fixture(
            fixture_id=payload.fixture_id,
            tenant_id=tenant_id,
            tool_name=payload.tool_name,
            created_by=actor.user_id,
            description=payload.description,
            input_schema=payload.input_schema,
            mock_responses=payload.mock_responses,
            default_response=payload.default_response,
            allowlist_enabled=payload.allowlist_enabled,
            is_sandbox_safe=payload.is_sandbox_safe,
            is_mutation=payload.is_mutation,
        )
        return {
            "fixture": fix.model_dump(mode="json"),
            "version": ver.model_dump(mode="json"),
        }

    @router.get("/{fixture_id}")
    async def get_tool_fixture(
        fixture_id: str,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        fixture = fixture_service.repository.get_fixture(fixture_id)
        if not fixture:
            return {"error": f"Tool fixture '{fixture_id}' not found"}
        versions = fixture_service.repository.list_versions(fixture_id)
        return {
            "fixture": fixture.model_dump(mode="json"),
            "versions": [v.model_dump(mode="json") for v in versions],
        }

    @router.post("/{fixture_id}/versions")
    async def create_fixture_version(
        fixture_id: str,
        payload: CreateFixtureVersionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.write")
        ver = fixture_service.create_version(
            fixture_id=fixture_id,
            created_by=actor.user_id,
            description=payload.description,
            input_schema=payload.input_schema,
            mock_responses=payload.mock_responses,
            default_response=payload.default_response,
            allowlist_enabled=payload.allowlist_enabled,
            is_sandbox_safe=payload.is_sandbox_safe,
            is_mutation=payload.is_mutation,
        )
        return {"version": ver.model_dump(mode="json")}

    @router.get("/{fixture_id}/versions/{version}")
    async def get_fixture_version(
        fixture_id: str,
        version: int,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.read")
        ver = fixture_service.repository.get_version(fixture_id, version)
        if not ver:
            return {"error": f"Tool fixture version '{fixture_id}:v{version}' not found"}
        return {"version": ver.model_dump(mode="json")}

    @router.post("/{fixture_id}/versions/{version}/approve")
    async def approve_fixture_version(
        fixture_id: str,
        version: int,
        payload: ApproveFixtureVersionPayload,
        actor: ActorContext = Depends(current_actor),
    ) -> dict[str, Any]:
        require_capability(actor, "ops.evals.review")
        approved = fixture_service.approve_version(
            fixture_id=fixture_id,
            version=version,
            approved_by=actor.user_id,
            reason=payload.reason,
        )
        return {"version": approved.model_dump(mode="json")}

    app.include_router(router)
