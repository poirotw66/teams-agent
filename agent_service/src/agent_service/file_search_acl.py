"""ACL encoding/filtering for the Gemini File Search adapter (spec §8.3, Task 16).

Gemini File Search's ``metadata_filter`` only matches **scalar**
``CustomMetadata.string_value`` entries. A live probe against a real store
established that ``string_list_value`` (a ``StringList``) is silently
unmatchable — an unfiltered query still returns the document, but any filter
against the list field returns nothing, and an ``IN [...]`` filter is
rejected outright with ``400 INVALID_ARGUMENT``. See
``docs/gemini-file-search-spike.md`` finding 9. This module therefore encodes
group membership as one scalar key per group (``grp_<slug>_<digest>="1"``)
rather than a single list-valued field, and builds an OR-of-equalities filter
string at query time — the only filter shape verified to work.

The semantics this module must reproduce exactly are Hybrid's
(``retrieval.py::HybridIndex.search``): a chunk with an **empty**
``allowed_groups`` is visible to everyone; a chunk with a **non-empty**
``allowed_groups`` is visible only to callers whose groups intersect it.
"""

from __future__ import annotations

import hashlib
import re

# --- Group -> metadata key encoding -----------------------------------------
#
# Scheme: ``grp_<slug>_<digest>`` where:
#   - ``slug`` is the group name lowercased with every run of non
#     [a-z0-9] characters collapsed to a single "_" (purely for human
#     readability when eyeballing stored metadata / filter strings — it is
#     NOT relied on for uniqueness and is allowed to collide).
#   - ``digest`` is the first _DIGEST_HEX_LEN hex characters of
#     sha256(group_name.encode("utf-8")), computed from the *raw*,
#     unnormalised group string.
#
# Collision-freedom rests entirely on the digest, not the slug: two distinct
# group strings (e.g. "cs team" and "cs-team", which slug to the same
# "cs_team") get different digests because the hash input is the original
# string, not the slug. Two groups can only produce the same key if they are
# the same string, or in the astronomically unlikely event of a SHA-256
# prefix collision at _DIGEST_HEX_LEN hex chars (40 bits) — occupying the
# same "worth worrying about" tier as hash-based content addressing
# elsewhere in this codebase. A key collision is a privilege leak (one
# group's documents become visible to another group's members), so digest
# length is chosen generously rather than minimally.
#
# Because the raw group name only ever flows into a *hash*, never into the
# filter string as literal text, this encoding is inherently immune to
# metadata-filter injection: a group named ``x" OR grp_admin="1`` still hashes
# to an opaque, harmless key.
_DIGEST_HEX_LEN = 16
_KEY_PREFIX = "grp_"
_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Sentinel key marking a document as visible to every caller, used to encode
# Hybrid's "empty allowed_groups == visible to all" rule (see module
# docstring). Structurally distinct from any group_metadata_key() output:
# a real group key always ends in exactly _DIGEST_HEX_LEN lowercase hex
# characters, and "public" (6 letters, some non-hex) can never match that
# shape, so this constant cannot collide with a hashed group key.
PUBLIC_GROUP_KEY = f"{_KEY_PREFIX}public"

# Conservative cap on how many of the caller's groups get OR'd into a query
# filter. No File Search API length limit for `metadata_filter` was measured
# during the spike (see docs/gemini-file-search-spike.md finding 9 caveats) —
# this is a defensive guess, not a verified ceiling. Exceeding it raises
# rather than silently truncating: a silently truncated filter would make a
# user's document set depend on set/list ordering and could look like a
# flaky, unexplained "why can't I see this doc" bug. Raising surfaces the
# problem immediately and lets the caller decide how to shrink the group set
# (e.g. only send group memberships relevant to this tenant).
MAX_FILTER_GROUPS = 50


def group_metadata_key(group: str) -> str:
    """Deterministic, filter-safe, collision-free metadata key for a group.

    Same input always produces the same output; distinct inputs practically
    never collide (see module docstring). The result is safe to use unquoted
    as a ``metadata_filter`` key (``grp_`` + lowercase alnum/underscore).
    """
    if not isinstance(group, str) or not group:
        raise ValueError("group must be a non-empty string")
    slug = _SLUG_RE.sub("_", group.lower()).strip("_") or "g"
    digest = hashlib.sha256(group.encode("utf-8")).hexdigest()[:_DIGEST_HEX_LEN]
    return f"{_KEY_PREFIX}{slug}_{digest}"


def upload_metadata_for(allowed_groups: list[str] | None) -> list:
    """Scalar ``CustomMetadata`` entries to attach to a document at upload time.

    Mirrors Hybrid's ACL semantic exactly:
    - empty/None ``allowed_groups`` -> the document is public: attach only
      :data:`PUBLIC_GROUP_KEY`.
    - non-empty ``allowed_groups`` -> the document is restricted: attach one
      scalar key per (de-duplicated) group, and NOT the public sentinel.

    ``types`` is imported lazily, matching ``gemini_file_search.py``'s
    convention of not requiring the google-genai SDK at module import time.
    """
    from google.genai import types

    groups = list(dict.fromkeys(allowed_groups or []))
    if not groups:
        return [types.CustomMetadata(key=PUBLIC_GROUP_KEY, string_value="1")]
    return [
        types.CustomMetadata(key=group_metadata_key(group), string_value="1")
        for group in groups
    ]


def filter_for(user_groups: list[str] | None) -> str | None:
    """Query-time ``metadata_filter`` string for a caller's groups.

    Always includes :data:`PUBLIC_GROUP_KEY` so unrestricted documents stay
    visible regardless of the caller's own groups (including a caller with
    *no* groups at all — that is not the same as "no filter"). This
    function never returns ``None``: an unfiltered File Search query returns
    every document in the store, restricted or not, which is never a safe
    default here — at minimum the caller must still be scoped down to public
    documents. The ``str | None`` return type exists only because it is the
    shape passed straight into ``types.FileSearch(metadata_filter=...)``,
    which does accept ``None`` for "no restriction"; this function simply
    never chooses that value.

    Raises ``ValueError`` if the caller belongs to more than
    :data:`MAX_FILTER_GROUPS` distinct groups (see that constant's docstring).
    """
    groups = list(dict.fromkeys(user_groups or []))
    if len(groups) > MAX_FILTER_GROUPS:
        raise ValueError(
            f"filter_for: caller has {len(groups)} distinct groups, "
            f"exceeding MAX_FILTER_GROUPS={MAX_FILTER_GROUPS}; refusing to "
            "build a metadata_filter rather than silently truncating it."
        )

    keys = [PUBLIC_GROUP_KEY] + [group_metadata_key(group) for group in groups]
    return " OR ".join(f'{key}="1"' for key in keys)
