"""Usage/cost extraction for the Gemini File Search adapter (spec §8.3, Task 16).

A grounded File Search call returns ``response.usage_metadata`` with four
counters: ``prompt_token_count``, ``tool_use_prompt_token_count``,
``candidates_token_count`` and ``total_token_count``. The retrieved document
content that File Search injects into the model's context lands in
``tool_use_prompt_token_count`` — NOT ``prompt_token_count``, which only
covers the user's own query text. A live probe recorded
``prompt=16, tool_use_prompt=2004, candidates=426, total=2446``: omitting
``tool_use_prompt_token_count`` from the billed input would understate cost
by roughly 99% (16 vs. 2020 real input tokens). Every input-token figure in
this module therefore always sums ``prompt_token_count`` and
``tool_use_prompt_token_count``. See docs/gemini-file-search-spike.md
finding 8.

Per-token pricing for the query itself is not duplicated here: it is read
from ``usage.py``'s existing ``_MODEL_RATES_USD`` table via the public
``estimate_cost_usd`` helper, so both adapters (Hybrid and File Search) stay
on one price list. Indexing (upload-time embedding) cost is the one
exception — see ``indexing_cost`` below for why it is not sourced the same
way.
"""

from __future__ import annotations

from dataclasses import dataclass

from .usage import estimate_cost_usd, normalize_model_name

# One-off indexing (upload-time) embedding cost. File Search storage itself
# is free; the initial indexing pass is billed as ordinary embedding tokens
# for the embedding model in use (docs/gemini-file-search-spike.md finding 8).
#
# The rate is read from usage.py's table rather than restated here, so both
# adapters stay on one price list. Note: the File Search guide's summary line
# quotes "$0.15 / 1M tokens", but the pricing table itself lists
# gemini-embedding-2 text input at $0.20/1M and gemini-embedding-001 at
# $0.15/1M (verified against ai.google.dev on 2026-08-07). The $0.15 figure
# belongs to the older model, so usage.py's $0.20 entry for
# gemini-embedding-2 is the correct one to use here.
_INDEXING_MODEL_NAME = "gemini-embedding-2"


@dataclass(frozen=True)
class FileSearchUsage:
    """Token counts pulled from a File Search ``response.usage_metadata``."""

    prompt_tokens: int
    tool_use_prompt_tokens: int
    candidates_tokens: int
    total_tokens: int

    @property
    def input_tokens(self) -> int:
        """Billed input tokens: query text + retrieved document content."""
        return self.prompt_tokens + self.tool_use_prompt_tokens

    @property
    def output_tokens(self) -> int:
        return self.candidates_tokens

    def log_fields(self) -> dict[str, object]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "tool_use_prompt_tokens": self.tool_use_prompt_tokens,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


def _safe_int(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def extract_usage(response: object) -> FileSearchUsage:
    """Defensively pull token counts off a File Search ``generate_content`` response.

    Any of the four fields, or ``usage_metadata`` itself, may be absent or
    ``None`` on a given response (e.g. a non-grounded or error response).
    This never raises — missing data degrades to zero counts.
    """
    usage_metadata = getattr(response, "usage_metadata", None)

    prompt = _safe_int(getattr(usage_metadata, "prompt_token_count", None))
    tool_use_prompt = _safe_int(getattr(usage_metadata, "tool_use_prompt_token_count", None))
    candidates = _safe_int(getattr(usage_metadata, "candidates_token_count", None))
    total = _safe_int(getattr(usage_metadata, "total_token_count", None))
    if total == 0 and (prompt or tool_use_prompt or candidates):
        total = prompt + tool_use_prompt + candidates

    return FileSearchUsage(
        prompt_tokens=prompt,
        tool_use_prompt_tokens=tool_use_prompt,
        candidates_tokens=candidates,
        total_tokens=total,
    )


def estimate_cost(usage: FileSearchUsage, model: str) -> float | None:
    """USD cost of a query, reusing usage.py's pricing table.

    Returns ``None`` for a model absent from that table (matching
    usage.py's existing "report tokens, cost unavailable" behaviour) rather
    than raising.
    """
    return estimate_cost_usd(model, usage.input_tokens, usage.output_tokens)


def indexing_cost(total_tokens: int, model: str = _INDEXING_MODEL_NAME) -> float | None:
    """One-off USD cost of indexing ``total_tokens`` at upload time.

    Priced through usage.py's table (embeddings are input-only there), so the
    project keeps a single price list. Returns ``None`` for a model the table
    does not know, matching usage.py's "report tokens, cost unavailable"
    behaviour.
    """
    if total_tokens <= 0:
        return 0.0
    return estimate_cost_usd(model, total_tokens, 0)


def log_fields(usage: FileSearchUsage, model: str) -> dict[str, object]:
    """Structured logging dict, shaped like usage.py's UsageReport.log_fields()."""
    cost = estimate_cost(usage, model)
    fields = usage.log_fields()
    fields["model"] = normalize_model_name(model)
    fields["estimated_cost_usd"] = None if cost is None else round(cost, 8)
    return fields
