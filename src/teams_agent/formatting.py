"""Teams response formatting and Markdown presentation logic."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import AgentResponse, Citation


def format_turn_cost_line(response: AgentResponse) -> str | None:
    """Return a subtle cost footer when the Agent Service included cost metadata."""
    if response.costComplete is None:
        return None
    if response.estimatedCostUsd is not None and response.estimatedCostTwd is not None:
        return (
            f"_預估成本：${response.estimatedCostUsd:.8f} USD / "
            f"${response.estimatedCostTwd:.3f} TWD_"
        )
    return "_預估成本：無法估算（費率或用量資料不完整）_"


def _dedupe_adjacent_citations(
    lines: list[str], lead_in_cite: str | None
) -> list[str]:
    result_lines: list[str] = []
    n = len(lines)
    for idx, line in enumerate(lines):
        m = re.match(r"^(\s*(?:\d+\.|[-*])\s+.*?)(\s*\[S\d+\][。.]?)\s*$", line)
        if m:
            content, cite = m.groups()
            cite_marker_m = re.search(r"\[S\d+\]", cite)
            if cite_marker_m:
                cite_marker = cite_marker_m.group(0)
                has_next_same = False
                if idx + 1 < n:
                    next_line = lines[idx + 1].strip()
                    if re.match(r"^(?:\d+\.|[-*])\s+", next_line) and cite_marker in next_line:
                        has_next_same = True
                if has_next_same or (lead_in_cite and lead_in_cite == cite_marker):
                    result_lines.append(content)
                    continue
        result_lines.append(line)
    return result_lines


def _format_steps_and_citations(text: str) -> str:
    """Format sequential steps with ordered numbers and clean repetitive citations."""
    text = re.sub(
        r"(?<!\n)(?:([：:。；;!?！？])\s*|(\s+))(\d+)\.\s+",
        r"\1\n\3. ",
        text,
    )
    lines = text.split("\n")
    new_lines: list[str] = []
    in_step_group = False
    step_num = 1
    lead_in_cite: str | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            new_lines.append(line)
            continue

        if re.search(r"(?:流程|步驟)(?:如下)?.*[:：]\s*$", stripped):
            in_step_group = True
            step_num = 1
            cite_m = re.search(r"\[S\d+\]", stripped)
            lead_in_cite = cite_m.group(0) if cite_m else None
            new_lines.append(line)
            continue

        is_already_numbered = bool(re.match(r"^\d+\.\s+", stripped))
        is_bullet = bool(re.match(r"^[-*]\s+", stripped))
        is_note = stripped.startswith((">", "註：", "備註："))

        if is_note or stripped.startswith(("**", "#")):
            in_step_group = False
            lead_in_cite = None
            new_lines.append(line)
            continue

        if is_already_numbered or is_bullet:
            new_lines.append(line)
            continue

        if in_step_group:
            if len(stripped) < 60 and not stripped.startswith("一般權限") and not stripped.startswith("若您"):
                new_lines.append(f"{step_num}. {stripped}")
                step_num += 1
                continue
            in_step_group = False
            lead_in_cite = None
            new_lines.append("")

        new_lines.append(line)

    return "\n".join(_dedupe_adjacent_citations(new_lines, lead_in_cite))



def format_teams_answer(answer: str) -> str:
    """Format raw agent answer for optimal Microsoft Teams Markdown rendering.

    Fixes common Teams rendering issues:
    - Bolds '問題：' and '處理方式：' and ensures double newline separation so
      Teams Adaptive Card Markdown does not collapse headings into the text.
    - Formats special notes or remarks as blockquote callouts (`> 💡 **注意事項**：...`).
    - Ensures sequential steps are numbered cleanly without citation repetition spam.
    """
    if not answer or not answer.strip():
        return answer

    text = answer.strip()

    # 1. Bold "問題：" header
    text = re.sub(r"(?m)^(?<!\*\*)問題：\s*([^\n]+)", r"**問題：** \1", text)

    # 2. Bold "處理方式：" and ensure double newline separation
    text = re.sub(
        r"(?:\n\s*|\A)(?:\*\*)?處理方式：(?:\*\*)?\s*\n*",
        r"\n\n**處理方式：**\n\n",
        text,
    )

    # 3. Bold "來源：\n" if present (e.g. FAQ answers from response_builder)
    text = re.sub(
        r"(?:\n\s*|\A)(?:\*\*)?來源：(?:\*\*)?\s*\n*",
        r"\n\n**來源：**\n\n",
        text,
    )

    # 4. Format notes/remarks (e.g. 註：... or 備註：...) as blockquote callout
    text = re.sub(
        r"(?m)^(?:\*\*)?(?:註|備註)：(?:\*\*)?\s*(.+)$",
        r"> 💡 **注意事項**：\1",
        text,
    )

    # 5. Format step lists and clean citation repetition
    text = _format_steps_and_citations(text)

    # Clean up any excessive newlines (more than 2 consecutive newlines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_POLICY_MARKER_DISPLAY_RE = re.compile(r"\[POLICY-SEC-\d{3}\]")
_SECURITY_POLICY_ADVISORY_LINE_RE = re.compile(
    r"(?m)^(?:>\s*)?[^\n]*系統資安政策提醒[^\n]*\n?",
)


def _strip_policy_overlay_for_display(answer: str) -> str:
    """Hide system security-policy markers/callouts from chat text."""
    if not answer:
        return answer
    text = _SECURITY_POLICY_ADVISORY_LINE_RE.sub("", answer)
    text = _POLICY_MARKER_DISPLAY_RE.sub("", text)
    text = re.sub(r"[ \t]+([。．.，,！!？?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_policy_advisory_citation(citation: Citation) -> bool:
    chunk_id = citation.chunkId or ""
    if chunk_id.startswith("POLICY-SEC-"):
        return True
    return bool(re.search(r"POLICY-SEC-\d{3}", citation.title or ""))


def format_agent_response(response: AgentResponse) -> str:
    formatted_answer = format_teams_answer(
        _strip_policy_overlay_for_display(response.answer)
    )
    parts = [formatted_answer]
    display_citations = [
        citation
        for citation in response.citations
        if not _is_policy_advisory_citation(citation)
    ]
    if display_citations:
        has_citations_in_answer = bool(re.search(r"\[S\d+\]", formatted_answer))
        sources = "\n".join(
            (
                f"- [S{index}] [{citation.title}]({citation.url})"
                if citation.url
                else f"- [S{index}] {citation.title}"
            )
            if has_citations_in_answer
            else (
                f"- [{citation.title}]({citation.url})"
                if citation.url
                else f"- {citation.title}"
            )
            for index, citation in enumerate(display_citations, start=1)
        )
        parts.append(f"**來源**\n\n{sources}")
    cost_line = format_turn_cost_line(response)
    if cost_line:
        parts.append(cost_line)
    return "\n\n".join(parts)


__all__ = [
    "format_agent_response",
    "format_teams_answer",
    "format_turn_cost_line",
]
