"""Eval prompt resolution for Backoffice evaluation runners."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _lookup_by_immutable_id(
    version: str,
    *,
    governance_repository: Any,
    prompt_repository: Any,
) -> str | None:
    if governance_repository is not None:
        try:
            state = governance_repository.load()
            for item in state.prompt_versions:
                if item.version_id == version:
                    template = str(item.template or "").strip()
                    if template:
                        return template
        except Exception:
            logger.debug(
                "governance prompt lookup by version_id failed for version=%s",
                version,
                exc_info=True,
            )
    if prompt_repository is not None:
        try:
            for candidate in prompt_repository.load().candidates:
                if candidate.candidate_id == version:
                    content = str(candidate.content or "").strip()
                    if content:
                        return content
        except Exception:
            logger.debug(
                "prompt repository lookup by candidate_id failed for version=%s",
                version,
                exc_info=True,
            )
    return None


def _lookup_by_prompt_and_version(
    target_prompt_id: str,
    target_version: str,
    *,
    governance_repository: Any,
    prompt_repository: Any,
) -> str | None:
    if governance_repository is not None:
        try:
            state = governance_repository.load()
            for item in state.prompt_versions:
                if item.prompt_id == target_prompt_id and item.version == target_version:
                    template = str(item.template or "").strip()
                    if template:
                        return template
        except Exception:
            pass
    if prompt_repository is not None:
        try:
            for candidate in prompt_repository.load().candidates:
                if candidate.prompt_id == target_prompt_id and candidate.version == target_version:
                    content = str(candidate.content or "").strip()
                    if content:
                        return content
        except Exception:
            pass
    return None


def _lookup_by_version_label(
    version: str,
    target_version: str,
    *,
    governance_repository: Any,
    prompt_repository: Any,
) -> str | None:
    # Fallback: match generic version label only when no prompt identity was specified.
    # If the version label matches multiple prompts across repositories, reject as ambiguous.
    matches: list[tuple[str, str]] = []
    seen_prompts: set[str] = set()

    if governance_repository is not None:
        try:
            state = governance_repository.load()
            for item in state.prompt_versions:
                if item.version == target_version:
                    template = str(item.template or "").strip()
                    if template:
                        matches.append((item.prompt_id, template))
                        seen_prompts.add(item.prompt_id)
        except Exception:
            logger.debug(
                "governance prompt lookup failed for version=%s",
                version,
                exc_info=True,
            )
    if prompt_repository is not None:
        try:
            for candidate in prompt_repository.load().candidates:
                if candidate.version == target_version:
                    content = str(candidate.content or "").strip()
                    if content and candidate.prompt_id not in seen_prompts:
                        matches.append((candidate.prompt_id, content))
                        seen_prompts.add(candidate.prompt_id)
        except Exception:
            logger.debug(
                "prompt repository lookup failed for version=%s",
                version,
                exc_info=True,
            )

    if len(seen_prompts) > 1:
        logger.warning(
            "Ambiguous prompt version '%s' matches multiple prompts: %s. "
            "Rejecting; specify qualified 'prompt_id:version'.",
            target_version,
            sorted(seen_prompts),
        )
        return None
    if len(matches) == 1:
        return matches[0][1]
    return None


def build_eval_prompt_resolver(
    governance_repository: Any = None,
    prompt_repository: Any = None,
) -> Callable[[str], str | None]:
    def resolver(prompt_version: str) -> str | None:
        version = str(prompt_version or "").strip()
        if not version or version == "default":
            from ai_ops_backoffice.ports.answer_prompt import get_default_answer_prompt

            return get_default_answer_prompt()

        target_prompt_id: str | None = None
        target_version = version
        if ":" in version:
            target_prompt_id, target_version = version.split(":", 1)
            target_prompt_id = target_prompt_id.strip()
            target_version = target_version.strip()

        # 1. Match immutable version_id / candidate_id first
        immutable = _lookup_by_immutable_id(
            version,
            governance_repository=governance_repository,
            prompt_repository=prompt_repository,
        )
        if immutable is not None:
            return immutable

        # 2. Match (prompt_id, version) precisely
        if target_prompt_id:
            return _lookup_by_prompt_and_version(
                target_prompt_id,
                target_version,
                governance_repository=governance_repository,
                prompt_repository=prompt_repository,
            )

        # If an explicit immutable ID was requested but not found in step 1, fail closed.
        if version.startswith(("pv-", "cand-", "prompt-")):
            return None

        # 3. Fallback: match generic version label only when no prompt identity was specified.
        return _lookup_by_version_label(
            version,
            target_version,
            governance_repository=governance_repository,
            prompt_repository=prompt_repository,
        )

    return resolver
