"""Immutable baseline records seeded into governance state."""

from __future__ import annotations

import uuid
from datetime import datetime

from operations_core.default_extractor_prompt import SYSTEM_PROMPT

from .constants import FLAG_CATALOG, ISSUE_EXTRACTOR_PROMPT_ID
from .helpers import content_hash, short_version
from .models import (
    FlagRecord,
    FlagVersion,
    ModelConfigRecord,
    ModelConfigVersion,
    PromptRecord,
    PromptVersion,
)


def _baseline_prompt(now: datetime) -> tuple[PromptRecord, PromptVersion]:
    version_id = str(uuid.uuid4())
    version = PromptVersion(
        version_id=version_id,
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        version=short_version(SYSTEM_PROMPT),
        status="ACTIVE",
        template=SYSTEM_PROMPT,
        content_hash=content_hash(SYSTEM_PROMPT),
        input_schema_version="issue-extractor-input-v1",
        output_schema_version="issue-extractor-output-v1",
        taxonomy_version="imported-baseline",
        model_id="gemini-3.8-flash",
        created_by="system-baseline",
        created_at=now,
        submitted_by="system-baseline",
        submitted_at=now,
        approved_by="system-baseline",
        approved_at=now,
        activated_by="system-baseline",
        activated_at=now,
        change_reason="import code-based prompt as immutable baseline",
    )
    prompt = PromptRecord(
        prompt_id=ISSUE_EXTRACTOR_PROMPT_ID,
        component="issue-extractor",
        display_name="Issue Extractor",
        description="Splits user turns into classified IT issues",
        active_version_id=version_id,
        previous_healthy_version_id=version_id,
        etag=1,
    )
    return prompt, version


def _baseline_model(now: datetime) -> tuple[ModelConfigRecord, ModelConfigVersion]:
    version_id = str(uuid.uuid4())
    version = ModelConfigVersion(
        version_id=version_id,
        config_id="issue-extractor-model",
        provider="google_genai",
        model_id="gemini-3.8-flash",
        component="issue-extractor",
        status="ACTIVE",
        temperature=0.0,
        max_output_tokens=2048,
        timeout_seconds=30,
        retry=1,
        secret_ref="secret://gemini-api-key",
        region="asia-east1",
        pricing_version="v1",
        fallback_model_id="gemini-3.1-flash-lite",
        fallback_on=("TIMEOUT", "UNAVAILABLE"),
        content_hash=content_hash("google_genai:gemini-3.8-flash"),
        created_by="system-baseline",
        created_at=now,
        approved_by="system-baseline",
        activated_by="system-baseline",
        activated_at=now,
        change_reason="import env model allowlist as baseline",
    )
    config = ModelConfigRecord(
        config_id="issue-extractor-model",
        component="issue-extractor",
        active_version_id=version_id,
        previous_healthy_version_id=version_id,
        etag=1,
    )
    return config, version


def _baseline_flags(now: datetime) -> tuple[list[FlagRecord], list[FlagVersion]]:
    flags: list[FlagRecord] = []
    versions: list[FlagVersion] = []
    for flag_id, spec in FLAG_CATALOG.items():
        version_id = str(uuid.uuid4())
        version = FlagVersion(
            version_id=version_id,
            flag_id=flag_id,
            status="ACTIVE",
            value=str(spec["default"]),
            environment="lab",
            effective_at=now,
            created_by="system-baseline",
            created_at=now,
            approved_by="system-baseline",
            activated_by="system-baseline",
            activated_at=now,
            change_reason="import existing runtime default",
        )
        flags.append(
            FlagRecord(
                flag_id=flag_id,
                description=spec["description"],
                owner=spec["owner"],
                flag_type=spec["flag_type"],
                safety_locked=bool(spec["safety_locked"]),
                default_value=str(spec["default"]),
                active_version_id=version_id,
                etag=1,
            )
        )
        versions.append(version)
    return flags, versions
