"""Trust / provenance helpers for issue display vs retrieval (docs/0919-arch.md).

Display text and retrieval queries must not share a single free-text pipe:

* ``Issue.description`` — user-facing / audit text (sanitized for injection).
* ``Issue.retrieval_query`` — search intent only; never rendered to users.

Prefer the original user utterance for retrieval when available so a
compromised model description cannot become the KnowledgeService query.
"""

from __future__ import annotations

from .contracts import Issue
from .sanitize import sanitize_description


def issue_display_text(issue: Issue) -> str:
    """Text safe to render to users (never use retrieval_query here)."""
    return sanitize_description(issue.description)


def issue_retrieval_text(issue: Issue, *, user_utterance: str = "") -> str:
    """Text for KnowledgeService.search / tool queries; never for display.

    Preference order:
    1. Explicit ``retrieval_query`` when set
    2. Sanitized original user utterance
    3. Sanitized description (legacy fallback)
    """
    if issue.retrieval_query and issue.retrieval_query.strip():
        return sanitize_description(issue.retrieval_query.strip())
    utterance = user_utterance.strip()
    if utterance:
        return sanitize_description(utterance)[:4000]
    return sanitize_description(issue.description)
