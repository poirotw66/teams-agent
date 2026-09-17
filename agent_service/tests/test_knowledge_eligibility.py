from datetime import UTC, datetime

import pytest

from agent_service.documents import DocumentChunk
from agent_service.knowledge_eligibility import is_chunk_generation_eligible

EVALUATED_AT = datetime(2026, 9, 17, tzinfo=UTC)


def chunk(
    *,
    content_state: str = "ACTIVE",
    effective_at: str | None = None,
    expires_at: str | None = None,
    applicable_environments: list[str] | None = None,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id="chunk-1",
        title="Governed document",
        source_path="sources/governed.md",
        content="Approved support guidance.",
        content_state=content_state,
        effective_at=effective_at,
        expires_at=expires_at,
        applicable_environments=applicable_environments or [],
    )


@pytest.mark.parametrize("content_state", ["TEST", "PLACEHOLDER", "RETIRED", "unknown"])
def test_non_active_content_is_ineligible(content_state: str) -> None:
    assert not is_chunk_generation_eligible(
        chunk(content_state=content_state),
        environment="prod",
        evaluated_at=EVALUATED_AT,
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"effective_at": "2026-09-18T00:00:00Z"}, False),
        ({"effective_at": "invalid"}, False),
        ({"expires_at": "2026-09-17T00:00:00Z"}, False),
        ({"expires_at": "invalid"}, False),
        ({"applicable_environments": ["test"]}, False),
        ({"applicable_environments": ["prod"]}, True),
        ({}, True),
    ],
)
def test_lifecycle_and_environment_eligibility(
    overrides: dict[str, object],
    expected: bool,
) -> None:
    assert (
        is_chunk_generation_eligible(
            chunk(**overrides),
            environment="prod",
            evaluated_at=EVALUATED_AT,
        )
        is expected
    )
