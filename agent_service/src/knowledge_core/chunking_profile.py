"""Shared chunking-profile enum for knowledge ingestion."""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ChunkingProfile",
]


class ChunkingProfile(StrEnum):
    AUTO = "AUTO"
    SLIDE_DECK = "SLIDE_DECK"
    MANUAL = "MANUAL"
    POLICY = "POLICY"
