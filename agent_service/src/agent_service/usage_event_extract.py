"""Provider usage extraction from LLM and File Search response objects."""

from __future__ import annotations

from collections.abc import Mapping

from .usage import normalize_model_name


def infer_provider(model: str | None) -> str | None:
    if not model:
        return None
    normalized = normalize_model_name(model).lower()
    if normalized.startswith(("gpt-", "text-embedding-")):
        return "openai"
    if "gemini" in normalized or normalized.startswith("embedding"):
        return "google"
    return None


def safe_int(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def usage_from_mapping(token_usage: Mapping[str, object]) -> dict[str, int | str] | None:
    input_tokens = safe_int(
        token_usage.get("input_tokens")
        or token_usage.get("prompt_tokens")
        or token_usage.get("prompt_token_count")
        or token_usage.get("inputTokenCount")
    )
    output_tokens = safe_int(
        token_usage.get("output_tokens")
        or token_usage.get("completion_tokens")
        or token_usage.get("candidates_token_count")
        or token_usage.get("outputTokenCount")
    )
    total_tokens = safe_int(token_usage.get("total_tokens") or token_usage.get("total_token_count"))
    if not (input_tokens or output_tokens or total_tokens):
        return None
    return {
        "input_tokens": input_tokens or max(0, total_tokens - output_tokens),
        "output_tokens": output_tokens,
        "usage_source": "PROVIDER",
    }


def model_name_from_response_metadata(result: object) -> str | None:
    response_metadata = getattr(result, "response_metadata", None) or {}
    if not isinstance(response_metadata, Mapping):
        return None
    model_name = response_metadata.get("model_name") or response_metadata.get("model")
    if isinstance(model_name, str) and model_name.strip():
        return normalize_model_name(model_name)
    return None


def _with_model(patch: dict[str, int | str], result: object) -> dict[str, int | str]:
    if "model" not in patch:
        model_name = model_name_from_response_metadata(result)
        if model_name:
            patch["model"] = model_name
    return patch


def extract_provider_usage_from_result(result: object) -> dict[str, int | str] | None:
    """Best-effort token extraction from a single LLM response object."""
    usage_metadata = getattr(result, "usage_metadata", None)
    if usage_metadata is not None:
        if isinstance(usage_metadata, Mapping):
            mapped = usage_from_mapping(usage_metadata)
            if mapped:
                return _with_model(mapped, result)
        input_tokens = safe_int(
            getattr(usage_metadata, "input_tokens", None)
            or getattr(usage_metadata, "prompt_token_count", None)
        )
        output_tokens = safe_int(
            getattr(usage_metadata, "output_tokens", None)
            or getattr(usage_metadata, "candidates_token_count", None)
        )
        total_tokens = safe_int(
            getattr(usage_metadata, "total_tokens", None)
            or getattr(usage_metadata, "total_token_count", None)
        )
        if input_tokens or output_tokens or total_tokens:
            return _with_model(
                {
                    "input_tokens": input_tokens or max(0, total_tokens - output_tokens),
                    "output_tokens": output_tokens,
                    "usage_source": "PROVIDER",
                },
                result,
            )

    response_metadata = getattr(result, "response_metadata", None) or {}
    if isinstance(response_metadata, Mapping):
        token_usage = (
            response_metadata.get("token_usage")
            or response_metadata.get("usage")
            or response_metadata.get("usage_metadata")
        )
        if isinstance(token_usage, Mapping):
            mapped = usage_from_mapping(token_usage)
            if mapped:
                return _with_model(mapped, result)
        model_name = model_name_from_response_metadata(result)
        if model_name:
            return {"model": model_name}

    return None


def extract_file_search_usage_from_result(result: object) -> dict[str, int | str] | None:
    usage_metadata = getattr(result, "usage_metadata", None)
    if usage_metadata is None:
        return None
    prompt = safe_int(getattr(usage_metadata, "prompt_token_count", None))
    tool_use = safe_int(getattr(usage_metadata, "tool_use_prompt_token_count", None))
    candidates = safe_int(getattr(usage_metadata, "candidates_token_count", None))
    if not (prompt or tool_use or candidates):
        return None
    return {
        "input_tokens": prompt,
        "tool_context_tokens": tool_use,
        "output_tokens": candidates,
        "usage_source": "PROVIDER",
    }
