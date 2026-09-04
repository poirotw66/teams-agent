"""Versioned masking rule packs bound to governance policy versions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .contracts import MASKING_POLICY_VERSION

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"\b(?:\+886|0)\d{1,2}[- ]?\d{3,4}[- ]?\d{3,4}\b")
_EMPLOYEE_ID_PATTERN = re.compile(r"\b[A-Z]{1,3}\d{5,8}\b")
_NATIONAL_ID_PATTERN = re.compile(r"\b[A-Z][12]\d{8}\b")


@dataclass(frozen=True)
class MaskingRulePack:
    policy_version: str
    rules_hash: str
    mask_email: bool = True
    mask_phone: bool = True
    mask_employee_id: bool = True
    mask_national_id: bool = False
    mask_credentials: bool = True


def _hash_rules(*, policy_version: str, flags: dict[str, bool]) -> str:
    material = "|".join(
        [policy_version] + [f"{key}={int(value)}" for key, value in sorted(flags.items())]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _pack(policy_version: str, **flags: bool) -> MaskingRulePack:
    return MaskingRulePack(
        policy_version=policy_version,
        rules_hash=_hash_rules(policy_version=policy_version, flags=flags),
        **flags,
    )


MASKING_RULE_PACKS: dict[str, MaskingRulePack] = {
    "v2": _pack(
        "v2",
        mask_email=True,
        mask_phone=True,
        mask_employee_id=True,
        mask_national_id=False,
        mask_credentials=True,
    ),
    "v3": _pack(
        "v3",
        mask_email=True,
        mask_phone=True,
        mask_employee_id=True,
        mask_national_id=True,
        mask_credentials=True,
    ),
}

# Keep code baseline alias aligned with contracts.MASKING_POLICY_VERSION.
if MASKING_POLICY_VERSION not in MASKING_RULE_PACKS:
    MASKING_RULE_PACKS[MASKING_POLICY_VERSION] = MASKING_RULE_PACKS["v2"]


def resolve_masking_pack(policy_version: str | None) -> MaskingRulePack:
    version = (policy_version or MASKING_POLICY_VERSION).strip()
    pack = MASKING_RULE_PACKS.get(version)
    if pack is None:
        raise KeyError(f"Unsupported masking policy version: {version}")
    return pack


def apply_masking_pack(text: str, pack: MaskingRulePack, *, reveal: bool = False) -> tuple[str, bool]:
    """Apply the concrete rules for a pack. Returns (text, was_masked)."""
    if reveal:
        return text, False
    masked = text
    if pack.mask_email:
        masked = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", masked)
    if pack.mask_phone:
        masked = _PHONE_PATTERN.sub("[REDACTED_PHONE]", masked)
    if pack.mask_employee_id:
        masked = _EMPLOYEE_ID_PATTERN.sub("[REDACTED_ID]", masked)
    if pack.mask_national_id:
        masked = _NATIONAL_ID_PATTERN.sub("[REDACTED_NATIONAL_ID]", masked)
    return masked, masked != text
