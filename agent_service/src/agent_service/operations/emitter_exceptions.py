"""Replay conflict and duplicate exceptions for operational event emission."""

from __future__ import annotations


class OperationalEventReplayConflict(ValueError):
    """A replay changed previously observed immutable facts."""


class OperationalEventReplayDuplicate(Exception):
    """A finalized logical request was delivered again without changed facts."""
