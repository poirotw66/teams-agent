"""Sanitize citation source paths before deriving document identifiers."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit, urlunsplit

from .classification import IssueClassifier
from .masking import mask_text


def safe_source(source_path: str | None) -> tuple[str | None, str | None]:
    """Sanitize before deriving identifiers: slugification erases secret markers."""
    if not source_path:
        return None, None
    decoded = source_path
    for _ in range(4):
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    else:
        return "[REDACTED_SOURCE]", None
    masked = mask_text(decoded)
    if masked.was_masked:
        return masked.text, None
    try:
        parts = urlsplit(decoded)
        if parts.username is not None or parts.password is not None:
            return "[REDACTED_SOURCE]", None
    except ValueError:
        return "[REDACTED_SOURCE]", None
    # Query strings/fragments may carry signed access credentials even when a
    # free-text detector does not recognize the provider's parameter names.
    path = parts.path
    safe_path = urlunsplit((parts.scheme, parts.netloc, path, "", ""))
    return safe_path, IssueClassifier.document_id_from_source_path(path)
