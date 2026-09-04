from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .contracts import MASKING_POLICY_VERSION

_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(r"\b(?:\+886|0)\d{1,2}[- ]?\d{3,4}[- ]?\d{3,4}\b")
_EMPLOYEE_ID_PATTERN = re.compile(r"\b[A-Z]{1,3}\d{5,8}\b")
_CREDENTIAL_FIELD_ALIASES = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "apikey",
        "secret",
        "token",
        "sessiontoken",
        "identitytoken",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "authtoken",
        "bearertoken",
        "credential",
        "credentials",
        "clientsecret",
        "privatekey",
        "otp",
        "verificationcode",
        "密碼",
        "驗證碼",
    }
)
_TOKEN_METRIC_FIELD_ALIASES = frozenset(
    {
        "totaltokens",
        "inputtokens",
        "outputtokens",
        "tooltokens",
        "embeddingtokens",
        "tokencount",
        "tokensused",
        "toolcontexttokens",
        "cachedinputtokens",
        "reasoningtokens",
    }
)
_STRUCTURED_STRING_FIELD_ALIASES = frozenset(
    {
        "model",
        "provider",
        "pricingversion",
        "usagesource",
        "sourceid",
        "documentid",
        "knowledgeversionid",
        "releaseid",
        "faqkey",
        "issueid",
        "issuetypeid",
        "classificationsource",
        "confidencestatus",
        "route",
        "outcome",
        "knowledgebackend",
    }
)
_REDACTED_CREDENTIAL = "[REDACTED_CREDENTIAL]"
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (?:
        \b(?:my\s+)?(?:password|passwd|api[ -]?key|apikey|secret|credential|
        client[ -]?secret|private[ -]?key|token)["']?\s*
        (?:
            [:=]\s*["']?\S+
            |\bis\b\s*(?!locked\b|expired\b|reset\b|invalid\b|required\b)\S+
        )
        |\b(?:password|passwd)\b[ \t]+(?:
            ["'][^"'\r\n]+["']
            |(?=\S*[0-9_])\S+
        )
        |\b(?:otp|verification[ ]code)["']?\s*(?:
            (?:is|=|:)\s*["']?\S+
            |\s+\d{4,10}\b
        )
        |\bbearer\s+\S+
        |(?:我的)?密碼["']?\s*(?:
            [:=：]\s*["']?\S+
            |(?:是|為)\s*(?!什麼|何時|如何|[?？])["']?\S+
        )
        |驗證碼["']?\s*(?:
            (?:是|為|=|:|：)\s*["']?\S+
            |\s+\d{4,10}\b
        )
    )
    """,
)


@dataclass(frozen=True)
class MaskingResult:
    text: str
    was_masked: bool
    contains_credential: bool
    policy_version: str = MASKING_POLICY_VERSION


def pseudonymous_actor_id(raw_id: str | None) -> str | None:
    if not raw_id:
        return None
    digest = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
    return f"actor_{digest[:16]}"


def mask_text(text: str, *, reveal: bool = False) -> MaskingResult:
    from .masking_rules import apply_masking_pack
    from .policy_runtime import active_masking_policy

    policy = active_masking_policy()
    pack = policy.pack
    contains_credential = bool(_CREDENTIAL_ASSIGNMENT_PATTERN.search(text))
    if pack.mask_credentials and contains_credential:
        return MaskingResult(
            text=_REDACTED_CREDENTIAL,
            was_masked=True,
            contains_credential=True,
            policy_version=policy.policy_version,
        )
    # `reveal` is for an already-authorized PII view only.  It must never reveal
    # a credential: that branch is deliberately after credential detection.
    if reveal:
        return MaskingResult(
            text=text,
            was_masked=False,
            contains_credential=False,
            policy_version=policy.policy_version,
        )
    masked, was_masked = apply_masking_pack(text, pack, reveal=False)
    return MaskingResult(
        text=masked,
        was_masked=was_masked,
        contains_credential=False,
        policy_version=policy.policy_version,
    )


def _normalise_field_name(key: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", key.lower())


def _is_credential_field(key: str) -> bool:
    normalised = _normalise_field_name(key)
    if normalised in _TOKEN_METRIC_FIELD_ALIASES:
        return False
    return (
        normalised in _CREDENTIAL_FIELD_ALIASES
        # Suffixes cover fields such as ``newPassword`` and ``clientSecret``.
        # Token is deliberately excluded here: a generic ``resultToken`` or
        # ``reasonToken`` can be an enum/identifier, not a credential value.
        or any(
            normalised.endswith(alias)
            for alias in _CREDENTIAL_FIELD_ALIASES
            if alias != "token"
        )
    )


def _redact_value(value: object, *, field_name: str | None = None) -> object:
    if isinstance(value, dict):
        return redact_secrets(value)
    if isinstance(value, list):
        return [_redact_value(item, field_name=field_name) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, field_name=field_name) for item in value)
    if isinstance(value, str):
        if (
            field_name is not None
            and _normalise_field_name(field_name) in _STRUCTURED_STRING_FIELD_ALIASES
        ):
            # Metadata identifiers are not free text.  Avoid changing valid
            # values such as ``max_tokens`` or a tokenized source ID, while
            # still catching an explicit credential assignment in one.
            if _CREDENTIAL_ASSIGNMENT_PATTERN.search(value):
                return _REDACTED_CREDENTIAL
            return value
        return mask_text(value).text
    return value


def redact_secrets(payload: dict[str, object]) -> dict[str, object]:
    """Return a stable, persistence-safe copy of an untrusted structured payload.

    Credentials are removed by explicit field aliases and by the existing
    free-text detector.  Token usage metric fields are intentionally exempt so
    analytics values such as ``totalTokens`` remain numeric.
    """
    redacted: dict[str, object] = {}
    for key, value in payload.items():
        if _is_credential_field(key):
            redacted[key] = _REDACTED_CREDENTIAL
        else:
            redacted[key] = _redact_value(value, field_name=key)
    return redacted
