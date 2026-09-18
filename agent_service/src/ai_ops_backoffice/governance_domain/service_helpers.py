"""Governance service helper re-exports (stable import path for mixins)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .flag_lifecycle_ops import _activate_flag, _approve_flag
from .governance_baselines import _baseline_flags, _baseline_model, _baseline_prompt
from .governance_state_ops import _allowed, _upsert
from .model_lifecycle_ops import (
    _activate_model,
    _approve_model,
    _find_model,
    _find_model_version,
    _public_model,
    _validate_model,
)
from .prompt_lifecycle_ops import (
    _activate_prompt,
    _active_prompt,
    _approve_prompt,
    _candidate_template,
    _eval_for,
    _find_prompt,
    _find_prompt_version,
    _verified_examples,
)

Clock = Callable[[], datetime]

__all__ = [
    "Clock",
    "_activate_flag",
    "_activate_model",
    "_activate_prompt",
    "_active_prompt",
    "_allowed",
    "_approve_flag",
    "_approve_model",
    "_approve_prompt",
    "_baseline_flags",
    "_baseline_model",
    "_baseline_prompt",
    "_candidate_template",
    "_eval_for",
    "_find_model",
    "_find_model_version",
    "_find_prompt",
    "_find_prompt_version",
    "_public_model",
    "_upsert",
    "_validate_model",
    "_verified_examples",
]
