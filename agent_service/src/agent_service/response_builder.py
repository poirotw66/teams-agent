"""Deterministic Response Builder (spec §5.3).

This module renders the final Teams-facing text for a batch of processed
:class:`~agent_service.contracts.Issue` / :class:`~agent_service.contracts.IssueResult`
pairs using **plain Python string templating only**.

Hard constraint (spec §5.3): this module MUST NEVER call an LLM. No
paragraph rewriting, no "tidying up" of sources, no rewording of FAQ
answers, no polishing of ticket results. Concretely that means: no
imports of an LLM/chat-model client, no network calls, no prompt
construction. Everything here is `f"..."` formatting over data that was
already produced upstream (Issue Extractor, FAQ, Knowledge Service,
Ticket Service).

Why this rule exists (spec §5.3 "避免"):

- Modifying the original answer risks silently changing what a FAQ/
  knowledge document actually says.
- An LLM pass over sources risks dropping citations.
- An extra LLM call adds latency and token cost for no benefit.
- An extra LLM call risks hallucinating content that was never in the
  retrieved answer (spec §8.4, §17 "不使用模型一般知識補充公司流程").

Design notes / decisions where the spec text was not verbatim
---------------------------------------------------------------
- Non-IT issues never produce an :class:`IssueResult` at all — per the
  workflow (spec §5.1) the "Filter IT Issues" node keeps them out of
  "Process Issues" entirely. This builder therefore renders the non-IT
  line straight from ``Issue.isIT`` / ``Issue.description``, not from a
  result type (``IssueResultType`` has no ``NOT_IT`` member).
- "Topic" wording in NEED_MORE_INFO / NOT_IT templates uses
  ``Issue.description`` verbatim as produced by the Issue Extractor —
  this module does not shorten or rephrase it (that would require an
  LLM, which is forbidden here).
- ``IssueResult`` has no dedicated ticket-URL field. Ticket-producing
  nodes are expected to place ticket links as :class:`Citation` entries
  in ``IssueResult.sources`` (``title`` = ticket title/status, ``url`` =
  ticket link) — this module treats ``sources`` on TICKET_CREATED /
  TICKET_FOUND results exactly like it treats KNOWLEDGE_ANSWERED
  sources, which keeps a single rendering path and avoids a bespoke
  ticket schema in this module.
- Ticket offering after NO_KNOWLEDGE (spec §11.3) is controlled by the
  ``offer_ticket_on_no_knowledge`` flag passed in by the caller
  (workflow), not by this module reaching into the ticket service.
- FAILED never surfaces ``IssueResult.error`` (spec §17 forbids leaking
  stack traces to the user). Only an optional ``correlation_id`` passed
  in by the caller is surfaced, as a support-friendly tracking id.
- Feedback (spec §14): the 👍/👎 buttons are rendered as an Adaptive
  Card by the Teams adapter in a later task, not as literal text here.
  This module only signals ``feedback_enabled`` and exposes the prompt
  copy as :data:`FEEDBACK_PROMPT` so both the adapter and a plain-text
  fallback can reuse the exact same wording.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import AgentImage, Citation, Issue, IssueResult
from .sanitize import sanitize_description
from .settings import RagSettings

# Spec §14: shown after every FAQ / Knowledge answer. The actual 👍/👎
# buttons are an Adaptive Card rendered by the Teams adapter; this module
# only supplies the prompt copy and the boolean flag.
FEEDBACK_PROMPT = "這個回答有解決你的問題嗎？"

# Fallback when no issue description is available.
ALL_NON_IT_MESSAGE = (
    "我目前專門協助處理公司 IT 問題。\n"
    "請描述使用的系統、功能或錯誤訊息，我會協助你確認。"
)

# Result types that trigger the feedback prompt (spec §14: "每次 FAQ 或
# Knowledge 回答後").
_FEEDBACK_ELIGIBLE_RESULT_TYPES = frozenset({"FAQ_ANSWERED", "KNOWLEDGE_ANSWERED"})

_MAX_QUESTIONS = 2


@dataclass(frozen=True)
class BuiltResponse:
    """Final deterministic rendering of a batch of issue results."""

    text: str
    citations: list[Citation]
    images: list[AgentImage]
    feedback_enabled: bool


def _render_sources_block(sources: list[Citation]) -> str:
    """Render a ``來源`` block matching the Teams adapter's own rendering.

    Mirrors ``src/teams_agent/contracts.py::format_agent_response`` so the
    two surfaces stay visually consistent: ``- [title](url)`` when a URL
    is present, ``- title`` otherwise.
    """
    lines = [
        f"- [{citation.title}]({citation.url})" if citation.url else f"- {citation.title}"
        for citation in sources
    ]
    return "\n".join(lines)


def _dedupe_citations(all_sources: list[Citation]) -> list[Citation]:
    seen: set[tuple[str, str | None, str | None]] = set()
    result: list[Citation] = []
    for citation in all_sources:
        key = (citation.title, citation.url, citation.chunkId)
        if key in seen:
            continue
        seen.add(key)
        result.append(citation)
    return result


def _dedupe_images(all_images: list[AgentImage]) -> list[AgentImage]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[AgentImage] = []
    for image in all_images:
        key = (image.path, image.title, image.altText, image.sourceChunkId)
        if key in seen:
            continue
        seen.add(key)
        result.append(image)
    return result


def _safe_description(issue: Issue) -> str:
    """Spec §17 defence in depth: the last gate before ``Issue.description``
    is rendered to the user. The primary gate is the Issue Extractor's own
    post-processing (``extractor.py``'s ``_coerce_issue``), which already
    runs every description through the same ``sanitize_description``. This
    call is a no-op in the normal path and only matters if a description
    ever reaches this module without going through the extractor (a future
    workflow change, a test double, a bug). It is plain deterministic
    string handling, not a model call -- it does not violate spec §5.3.
    """
    return sanitize_description(issue.description)


def _render_not_it(issue: Issue) -> str:
    # Spec §13 "非 IT": "{topic}問題不在此 IT 助手的服務範圍。"
    return f"{_safe_description(issue)}問題不在此 IT 助手的服務範圍。"


def _render_all_not_it(issues: list[Issue]) -> str:
    topics = list(dict.fromkeys(_safe_description(issue) for issue in issues))
    if not topics:
        return ALL_NON_IT_MESSAGE
    quoted_topics = "、".join(f"「{topic}」" for topic in topics)
    return (
        f"{quoted_topics}不屬於公司 IT 支援範圍，因此我不會查詢企業知識庫。\n"
        "我可以協助處理公司系統、設備、帳號、權限或錯誤訊息等 IT 問題。"
    )


def _render_faq_answered(issue: Issue, result: IssueResult) -> str:
    # Spec §13 "FAQ" — exact template.
    return (
        f"問題：{_safe_description(issue)}\n\n"
        f"處理方式：\n{result.answer}\n\n"
        f"來源：\nFAQ"
    )


def _render_knowledge_answered(issue: Issue, result: IssueResult) -> str:
    # Citations travel separately in BuiltResponse and are rendered by the
    # Teams adapter. Keeping them out of the answer body prevents duplicate
    # source sections in both plain text and Adaptive Cards.
    return f"問題：{_safe_description(issue)}\n\n處理方式：\n{result.answer}"


def _render_need_more_info(issue: Issue, result: IssueResult) -> str:
    # Spec §13 "Need More Info" — numbered, at most 2 questions (§6.3).
    questions = result.questions[:_MAX_QUESTIONS]
    if issue.route == "TICKET":
        return "\n".join(questions)
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1))
    return f"為了協助確認 {_safe_description(issue)} 問題，請補充：\n\n{numbered}"


def _render_no_knowledge(
    issue: Issue, result: IssueResult, *, offer_ticket: bool
) -> str:
    # Explicit create requests are routed with route=TICKET and should only
    # ask for confirmation — never pretend we searched the knowledge base.
    if offer_ticket and issue.route == "TICKET":
        return "是否需要協助建立派工單？請回覆<是>以建立派工單。"

    # Spec §8.4: never fabricate an answer when the knowledge base has none.
    text = f"問題：{_safe_description(issue)}\n\n目前企業知識庫中查無相關資訊，我無法提供答案。"
    if offer_ticket:
        text += "\n\n是否需要協助建立派工單？請回覆<是>以建立派工單。"
    return text


def _render_ticket_created(issue: Issue, result: IssueResult) -> str:
    lines = [
        f"問題：{_safe_description(issue)}",
        "",
        f"已為你建立派工單，派工單編號：{result.ticketId}",
    ]
    if result.sources and result.sources[0].url:
        lines.append(f"派工單連結：{result.sources[0].url}")
    if result.answer:
        lines.append("")
        lines.append(result.answer)
    return "\n".join(lines)


def _render_ticket_found(issue: Issue, result: IssueResult) -> str:
    description = _safe_description(issue)
    header = f"問題：{description}\n\n你的派工單如下："
    if not result.sources:
        return f"問題：{description}\n\n目前查無你建立的派工單。"
    return f"{header}\n{_render_sources_block(result.sources)}"


def _render_ticket_cancelled() -> str:
    """A cancellation is a direct acknowledgement, never a knowledge answer."""
    return "好的，目前不會建立派工單。若之後需要協助，請告訴我「建立派工單」。"


def _render_ticket_delete_denied() -> str:
    """Mock acceptance environment keeps tickets as an auditable record."""
    return (
        "目前不支援刪除派工單。若派工單已不需要處理，正式串接工單系統後，"
        "可使用取消或關閉功能。"
    )


def _render_failed(issue: Issue, correlation_id: str | None) -> str:
    # Spec §17: never leak IssueResult.error / a stack trace to the user.
    text = f"問題：{_safe_description(issue)}\n\n處理時發生問題，請稍後再試。"
    if correlation_id:
        text += f"\n\n追蹤編號：{correlation_id}"
    return text


def _render_result(
    issue: Issue,
    result: IssueResult,
    *,
    offer_ticket_on_no_knowledge: bool,
    correlation_id: str | None,
) -> str:
    if result.resultType == "FAQ_ANSWERED":
        return _render_faq_answered(issue, result)
    if result.resultType == "KNOWLEDGE_ANSWERED":
        return _render_knowledge_answered(issue, result)
    if result.resultType == "NEED_MORE_INFO":
        return _render_need_more_info(issue, result)
    if result.resultType == "NO_KNOWLEDGE":
        return _render_no_knowledge(
            issue, result, offer_ticket=offer_ticket_on_no_knowledge
        )
    if result.resultType == "TICKET_CREATED":
        return _render_ticket_created(issue, result)
    if result.resultType == "TICKET_FOUND":
        return _render_ticket_found(issue, result)
    if result.resultType == "TICKET_CANCELLED":
        return _render_ticket_cancelled()
    if result.resultType == "TICKET_DELETE_DENIED":
        return _render_ticket_delete_denied()
    # FAILED (and any unrecognised/defensive fallback).
    return _render_failed(issue, correlation_id)


def _render_multi_issue_block(position: int, issue: Issue, content: str) -> str:
    """Give each issue a distinct Markdown section without changing its answer."""
    description = _safe_description(issue)
    problem_prefix = f"問題：{description}\n\n"
    clarification_prefix = f"為了協助確認 {description} 問題，請補充：\n\n"

    if content.startswith(problem_prefix):
        body = content.removeprefix(problem_prefix)
    elif content.startswith(clarification_prefix):
        body = f"**需要補充資訊**\n\n{content.removeprefix(clarification_prefix)}"
    else:
        body = content

    return f"**問題 {position}｜{description}**\n\n{body}"


def build_response(
    *,
    issues: list[Issue],
    results: list[IssueResult],
    too_many_issues: bool = False,
    settings: RagSettings,
    offer_ticket_on_no_knowledge: bool = False,
    correlation_id: str | None = None,
) -> BuiltResponse:
    """Deterministically render the final Teams reply text.

    Iterates ``issues`` in ascending ``id`` order (spec §4.2 requires a
    stable, predictable ordering and that a single issue's failure or
    need-more-info never suppresses the others). Non-IT issues are
    rendered straight from ``Issue`` (spec §4.1); IT issues are rendered
    from their matching :class:`IssueResult` by ``issueId``.

    Never calls an LLM — see the module docstring (spec §5.3).
    """
    ordered_issues = sorted(issues, key=lambda issue: issue.id)
    results_by_issue_id = {result.issueId: result for result in results}

    if ordered_issues and all(not issue.isIT for issue in ordered_issues):
        return BuiltResponse(
            text=_render_all_not_it(ordered_issues),
            citations=[],
            images=[],
            feedback_enabled=False,
        )

    blocks: list[str] = []
    if too_many_issues:
        # Spec §4.2: ask the user to prioritise when there were more
        # issues than the workflow processed.
        blocks.append(
            f"你的訊息包含多個問題，已先協助你處理最重要的 "
            f"{settings.max_issues_per_message} 個。"
            "如果還有其他問題，請告訴我你最需要優先處理的項目。"
        )

    all_sources: list[Citation] = []
    all_images: list[AgentImage] = []
    feedback_eligible = False

    multiple_issues = len(ordered_issues) > 1
    issue_blocks: list[str] = []
    for position, issue in enumerate(ordered_issues, start=1):
        if not issue.isIT:
            rendered = _render_not_it(issue)
            issue_blocks.append(
                _render_multi_issue_block(position, issue, rendered)
                if multiple_issues
                else rendered
            )
            continue

        result = results_by_issue_id.get(issue.id)
        if result is None:
            # Defensive: an IT issue that never got a result. Do not
            # silently drop it (§4.2) — surface it as a generic failure
            # without inventing details.
            rendered = _render_failed(issue, correlation_id)
            issue_blocks.append(
                _render_multi_issue_block(position, issue, rendered)
                if multiple_issues
                else rendered
            )
            continue

        rendered = _render_result(
            issue,
            result,
            offer_ticket_on_no_knowledge=offer_ticket_on_no_knowledge,
            correlation_id=correlation_id,
        )
        issue_blocks.append(
            _render_multi_issue_block(position, issue, rendered)
            if multiple_issues
            else rendered
        )
        if result.resultType not in {"TICKET_CREATED", "TICKET_FOUND"}:
            all_sources.extend(result.sources)
        all_images.extend(result.images)
        if result.resultType in _FEEDBACK_ELIGIBLE_RESULT_TYPES:
            feedback_eligible = True

    if issue_blocks:
        blocks.append(("\n\n---\n\n" if multiple_issues else "\n\n").join(issue_blocks))

    if not blocks:
        text = ALL_NON_IT_MESSAGE if not ordered_issues else ""
    else:
        text = "\n\n".join(blocks)

    return BuiltResponse(
        text=text,
        citations=_dedupe_citations(all_sources),
        images=_dedupe_images(all_images),
        feedback_enabled=settings.feedback_enabled and feedback_eligible,
    )
