"""Hybrid retrieval ACL visibility helpers."""

from __future__ import annotations

from .documents import DocumentChunk

# Publisher ALL_EMPLOYEES / File Search public sentinel. Empty allowlists and
# sole ``grp_public`` are both public; restricted docs use concrete group ids.
PUBLIC_ACL_GROUP = "grp_public"

__all__ = ["PUBLIC_ACL_GROUP", "is_chunk_visible_to_groups"]


def is_chunk_visible_to_groups(
    chunk: DocumentChunk,
    groups: set[str] | None,
) -> bool:
    """Return whether Hybrid ACL allows the caller to see ``chunk``.

    Public documents use an empty ``allowed_groups`` list or only
    ``grp_public`` (portal ALL_EMPLOYEES). Otherwise the caller's groups must
    intersect the document allowlist.
    """
    caller_groups = groups or set()
    allowed = {str(group) for group in (chunk.allowed_groups or []) if str(group)}
    if not allowed or allowed == {PUBLIC_ACL_GROUP}:
        return True
    return bool(allowed.intersection(caller_groups))
