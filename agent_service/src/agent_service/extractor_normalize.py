"""Issue normalization and post-LLM coercion for IssueExtractor."""

from __future__ import annotations

import re

from .contracts import Issue
from .extractor_heuristics import (
    _has_helpdesk_domain_evidence,
    _is_known_dazhou_issue,
)
from .sanitize import sanitize_description

# Terms that must never appear in a missingInfo follow-up question, per spec
# §6.3 / §12 / §17. Matched case-insensitively, substring match, against both
# the Traditional Chinese and English/romanized forms an LLM might produce.
FORBIDDEN_MISSING_INFO_TERMS: tuple[str, ...] = (
    "密碼",
    "password",
    "驗證碼",
    "otp",
    "one-time",
    "access token",
    "token",
    "secret",
    "金鑰",
    "api key",
    "apikey",
    "員工編號",
    "身分證",
    "身份證",
    "credential",
    "帳號密碼",
    "信用卡",
    "銀行帳號",
)

_RAW_UTTERANCE_QUALIFIERS: tuple[str, ...] = (
    "不知道裝置是否受企業政策管理",
    "來源能支持哪些答案",
    "未確認政策",
    "政策未確認",
    "來源能支持",
    "為何不能",
    "是否可以",
    "處置原則",
    "操作順序",
    "XQ",
    "PowerPivot",
    "五檔",
    "可否",
    "能否",
)

_NEGATIVE_DESCRIPTION_MARKERS: tuple[str, ...] = (
    "不能",
    "無法",
    "不可",
    "不得",
    "未",
    "失敗",
    "異常",
    "中斷",
)

_NEGATIVE_UTTERANCE_MARKERS: tuple[str, ...] = ("為何不能", "不能", "不可", "不得")


def strip_forbidden_missing_info(items: list[str]) -> list[str]:
    kept: list[str] = []
    for item in items:
        lowered = item.lower()
        if any(term in lowered for term in FORBIDDEN_MISSING_INFO_TERMS):
            continue
        kept.append(item)
    return kept


def restore_utterance_qualifiers(issue: Issue, raw_utterance: str) -> Issue:
    """Reattach important utterance phrases the model dropped from description."""
    updated = issue
    if "來源能支持哪些答案" in raw_utterance:
        updated = updated.model_copy(
            update={
                "description": re.sub(
                    r"支援(?:的|哪些)?資料來源",
                    "來源能支持哪些答案",
                    updated.description,
                )
            }
        )

    missing_qualifiers: list[str] = []
    for qualifier in _RAW_UTTERANCE_QUALIFIERS:
        if (
            qualifier in raw_utterance
            and qualifier not in updated.description
            and not any(qualifier in marker for marker in missing_qualifiers)
            and not any(marker in qualifier for marker in missing_qualifiers)
        ):
            missing_qualifiers.append(qualifier)

    has_negative = any(marker in updated.description for marker in _NEGATIVE_DESCRIPTION_MARKERS)
    if not has_negative:
        for marker in _NEGATIVE_UTTERANCE_MARKERS:
            if (
                marker in raw_utterance
                and marker not in missing_qualifiers
                and not any(marker in existing for existing in missing_qualifiers)
            ):
                missing_qualifiers.append(marker)
                break

    if missing_qualifiers:
        updated = updated.model_copy(
            update={"description": f"{' '.join(missing_qualifiers)} {updated.description}".strip()}
        )
    return updated


def coerce_issue(
    issue: Issue,
    *,
    new_id: int,
    allowed_faq_keys: set[str],
    max_missing_info: int,
    raw_utterance: str = "",
) -> Issue:
    data = issue.model_dump()
    data["id"] = new_id

    # §17: structured output only constrains the *shape* of the model's
    # response, not the *content* of a free-text field. If the model is
    # compromised into placing system-prompt text or an injection-style
    # instruction inside `description`, sanitize it here -- once, before
    # it can reach either response_builder (rendered to the user) or
    # workflow._handle_knowledge (used as the retrieval query). See
    # sanitize.py's module docstring for the detection/tradeoff design.
    data["description"] = sanitize_description(data["description"])

    # §6.3/§12/§17: strip forbidden follow-up questions regardless of what
    # the model produced. A prompt instruction alone is not sufficient.
    data["missingInfo"] = strip_forbidden_missing_info(data.get("missingInfo") or [])
    data["missingInfo"] = data["missingInfo"][:max_missing_info]

    has_domain_evidence = _has_helpdesk_domain_evidence(data["description"]) or (
        bool(raw_utterance) and _has_helpdesk_domain_evidence(raw_utterance)
    )
    if not data["isIT"] and has_domain_evidence:
        data["isIT"] = True
        data["readiness"] = "NEED_MORE_INFO"
        data["route"] = "KNOWLEDGE"
        data["missingInfo"] = data["missingInfo"] or ["請確認您希望查詢的系統與處理面向。"]
        data["faqKey"] = None

    if not data["isIT"]:
        data["readiness"] = "NOT_IT"
        data["route"] = "NOT_IT"
        data["missingInfo"] = []
        data["faqKey"] = None
    else:
        if _is_known_dazhou_issue(data["description"]):
            data["readiness"] = "READY"
            data["missingInfo"] = []

        if data["readiness"] == "NOT_IT":
            # isIT is true but the model said NOT_IT; treat as READY unless
            # missing info says otherwise below.
            data["readiness"] = "READY"

        if data["readiness"] == "NEED_MORE_INFO" and not data["missingInfo"]:
            # All follow-up questions were stripped (e.g. all forbidden) or
            # none were ever provided: downgrade rather than ask nothing.
            data["readiness"] = "READY"
        elif data["readiness"] != "NEED_MORE_INFO":
            data["missingInfo"] = []

        if data["route"] == "FAQ" and data.get("faqKey") not in allowed_faq_keys:
            data["route"] = "KNOWLEDGE"
            data["faqKey"] = None
        if data["route"] != "FAQ":
            data["faqKey"] = None

    return Issue.model_validate(data)


def postprocess_issues(
    issues: list[Issue],
    faq_keys: list[str],
    *,
    max_issues: int,
    max_missing_info: int,
    raw_utterance: str = "",
) -> tuple[list[Issue], bool]:
    too_many = len(issues) > max_issues
    truncated = issues[:max_issues]

    allowed_faq_keys = set(faq_keys)
    coerced: list[Issue] = []
    for index, issue in enumerate(truncated, start=1):
        coerced.append(
            coerce_issue(
                issue,
                new_id=index,
                allowed_faq_keys=allowed_faq_keys,
                max_missing_info=max_missing_info,
                raw_utterance=raw_utterance,
            )
        )

    if raw_utterance and len(coerced) == 1 and coerced[0].isIT:
        coerced[0] = restore_utterance_qualifiers(coerced[0], raw_utterance)

    return coerced, too_many
