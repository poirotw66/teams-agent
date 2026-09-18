"""Compatibility facade for Gemini File Search ACL encoding."""

from __future__ import annotations

from knowledge_core.file_search_acl import (
    MAX_FILTER_GROUPS,
    PUBLIC_GROUP_KEY,
    filter_for,
    group_metadata_key,
    upload_metadata_for,
)

__all__ = [
    "MAX_FILTER_GROUPS",
    "PUBLIC_GROUP_KEY",
    "filter_for",
    "group_metadata_key",
    "upload_metadata_for",
]
