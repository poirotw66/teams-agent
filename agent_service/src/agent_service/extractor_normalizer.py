"""Issue normalization and post-LLM coercion for IssueExtractor."""

from __future__ import annotations

import re

from .contracts import Issue
from .extractor_heuristics import (
    _has_helpdesk_domain_evidence,
    _is_known_dazhou_issue,
    _is_shu_channel_login_symptom,
)
from .sanitize import sanitize_description
from .service_scope_evidence import (
    has_service_scope_evidence,
    is_complete_service_scope_query,
)

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


def _description_is_known_ready(description: str, raw_utterance: str) -> bool:
    return (
        _is_known_dazhou_issue(description)
        or _is_shu_channel_login_symptom(description)
        or bool(raw_utterance and _is_shu_channel_login_symptom(raw_utterance))
    )


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
    # instruction inside `description`, sanitize it here.
    data["description"] = sanitize_description(data["description"])

    # Trust boundary: retrieval prefers the original user utterance (or an
    # explicit retrieval_query), never a model free-text field that is also
    # rendered to the user.
    existing_retrieval = (data.get("retrieval_query") or "").strip()
    if existing_retrieval:
        data["retrieval_query"] = sanitize_description(existing_retrieval)[:4000]
    elif raw_utterance.strip():
        data["retrieval_query"] = sanitize_description(raw_utterance.strip())[:4000]
    else:
        data["retrieval_query"] = data["description"]

    # §6.3/§12/§17: strip forbidden follow-up questions regardless of what
    # the model produced. A prompt instruction alone is not sufficient.
    data["missingInfo"] = strip_forbidden_missing_info(data.get("missingInfo") or [])
    data["missingInfo"] = data["missingInfo"][:max_missing_info]

    scope_probe = " ".join(
        part for part in (data["description"], raw_utterance) if part
    ).strip()
    has_scope_evidence = has_service_scope_evidence(data["description"]) or (
        bool(raw_utterance) and has_service_scope_evidence(raw_utterance)
    )
    has_domain_evidence = _has_helpdesk_domain_evidence(data["description"]) or (
        bool(raw_utterance) and _has_helpdesk_domain_evidence(raw_utterance)
    )
    # Service-directory / alias evidence vetoes NOT_IT. Complete catalog or
    # doc/process queries become READY+KNOWLEDGE; do not force NEED_MORE_INFO
    # for self-contained seat / contact-form lookups. Ambiguous non-catalog
    # domain signals still ask for system context.
    if not data["isIT"] and (has_scope_evidence or has_domain_evidence):
        data["isIT"] = True
        data["route"] = "KNOWLEDGE"
        data["faqKey"] = None
        if has_scope_evidence and is_complete_service_scope_query(scope_probe):
            data["readiness"] = "READY"
            data["missingInfo"] = []
        else:
            data["readiness"] = "NEED_MORE_INFO"
            data["missingInfo"] = data["missingInfo"] or [
                "請確認您希望查詢的系統與處理面向。"
            ]

    if not data["isIT"]:
        data["readiness"] = "NOT_IT"
        data["route"] = "NOT_IT"
        data["missingInfo"] = []
        data["faqKey"] = None
    else:
        if _description_is_known_ready(data["description"], raw_utterance):
            data["readiness"] = "READY"
            data["missingInfo"] = []

        # Catalog scope hits that arrived already marked isIT but NEED_MORE_INFO
        # (or NOT_IT readiness) for a complete doc query should still normalize.
        if (
            has_scope_evidence
            and is_complete_service_scope_query(scope_probe)
            and data["readiness"] in {"NEED_MORE_INFO", "NOT_IT"}
        ):
            data["readiness"] = "READY"
            data["missingInfo"] = []
            if data["route"] == "NOT_IT":
                data["route"] = "KNOWLEDGE"

        if data["readiness"] == "NOT_IT":
            data["readiness"] = "READY"

        if data["readiness"] == "NEED_MORE_INFO" and not data["missingInfo"]:
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
    # Prefer utterance-level scope/domain evidence only on single-issue turns so
    # a seat alias in a mixed message does not veto NOT_IT on unrelated issues.
    utterance_for_coerce = raw_utterance if len(truncated) == 1 else ""
    for index, issue in enumerate(truncated, start=1):
        coerced.append(
            coerce_issue(
                issue,
                new_id=index,
                allowed_faq_keys=allowed_faq_keys,
                max_missing_info=max_missing_info,
                raw_utterance=utterance_for_coerce,
            )
        )

    if raw_utterance and len(coerced) == 1 and coerced[0].isIT:
        coerced[0] = restore_utterance_qualifiers(coerced[0], raw_utterance)

    return coerced, too_many


class IssueNormalizer:
    """Encapsulates post-extraction normalization, domain sanitization, and security invariants."""

    def __init__(self, *, max_issues: int, max_missing_info: int) -> None:
        self.max_issues = max_issues
        self.max_missing_info = max_missing_info

    def postprocess(
        self,
        issues: list[Issue],
        faq_keys: list[str],
        *,
        raw_utterance: str = "",
    ) -> tuple[list[Issue], bool]:
        return postprocess_issues(
            issues,
            faq_keys,
            max_issues=self.max_issues,
            max_missing_info=self.max_missing_info,
            raw_utterance=raw_utterance,
        )

    def coerce(
        self,
        issue: Issue,
        *,
        new_id: int,
        allowed_faq_keys: set[str],
        raw_utterance: str = "",
    ) -> Issue:
        return coerce_issue(
            issue,
            new_id=new_id,
            allowed_faq_keys=allowed_faq_keys,
            max_missing_info=self.max_missing_info,
            raw_utterance=raw_utterance,
        )
