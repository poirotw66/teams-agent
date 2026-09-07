from __future__ import annotations

from fastapi import Depends, FastAPI, Header

from ..faq_domain import FaqValidationError
from ..request_models import PromptCandidateRequest


def register_prompt_poc_routes(
    app: FastAPI,
    *,
    resolved_settings,
    query_service,
    prompt_service,
    example_service,
    current_actor,
    require_capability,
) -> None:
    @app.get("/api/prompts/active")
    async def get_active_prompt(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return {"prompt": prompt_service.active(actor=actor)}

    @app.get("/api/prompts/candidates")
    async def list_prompt_candidates(actor=Depends(current_actor)) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        items = prompt_service.list_candidates(actor=actor)
        return {"items": items, "total": len(items)}

    @app.get("/api/prompts/candidates/{candidate_id}")
    async def get_prompt_candidate(
        candidate_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return {"candidate": prompt_service.detail(candidate_id, actor=actor)}

    @app.get("/api/prompts/candidates/{candidate_id}/compare")
    async def compare_prompt_candidate(
        candidate_id: str,
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.read")
        return prompt_service.compare(candidate_id, actor=actor)

    @app.post("/api/prompts/candidates")
    async def create_prompt_candidate(
        payload: PromptCandidateRequest,
        correlation_id: str | None = Header(default=None, alias="X-Correlation-Id"),
        actor=Depends(current_actor),
    ) -> dict[str, object]:
        require_capability(actor, "ops.prompts.candidates.create")
        if payload.taxonomy_version != query_service.taxonomy.version:
            raise FaqValidationError("taxonomy version is stale")
        if payload.masking_policy_version != resolved_settings.prompt_masking_policy_version:
            raise FaqValidationError("masking policy version is stale")
        verified_examples = example_service.list_examples(actor=actor, status="VERIFIED")
        return prompt_service.generate(
            **payload.model_dump(),
            verified_examples=verified_examples,
            correlation_id=correlation_id,
            actor=actor,
        )
