"""Deterministic answer presentation for chat surfaces (no LLM).

Splits dense how-to paragraphs into readable blocks and numbered steps.
Keep behavior aligned with ``teams_agent.formatting.format_teams_answer``.
"""

from __future__ import annotations

import re

_ACTION_SPLIT_RE = re.compile(r"，(?=(?:請|使用|不要|勿|並請))")
_CONDITIONAL_HOWTO_RE = re.compile(
    r"^(若|如果)(.+?)，(請.+)$",
)
_CITATION_TAIL_RE = re.compile(r"(\s*\[S\d+\][。.]?)\s*$")


def split_condition_sentences(text: str) -> str:
    """Insert paragraph breaks before a new『若…』sentence after a full stop."""
    if not text:
        return text
    # Broader than the old 若需-only split used by Teams formatting.
    return re.sub(r"(?<=[。！？])[ \t]*(?=若|如果)", "\n\n", text)


def expand_conditional_howto_paragraph(paragraph: str) -> str:
    """Expand『若…，請A，使用B…[S1]』into a short lead-in plus numbered steps."""
    stripped = (paragraph or "").strip()
    if not stripped or "\n" in stripped:
        return paragraph

    cite = ""
    body = stripped
    cite_match = _CITATION_TAIL_RE.search(stripped)
    if cite_match:
        cite = cite_match.group(1).strip()
        body = stripped[: cite_match.start()].rstrip("。．. ")

    match = _CONDITIONAL_HOWTO_RE.match(body)
    if not match:
        return paragraph

    lead = f"{match.group(1)}{match.group(2)}".strip()
    rest = match.group(3).strip()
    parts = [part.strip() for part in _ACTION_SPLIT_RE.split(rest) if part.strip()]
    if len(parts) < 2:
        return paragraph

    lines = [f"{lead}，請依下列步驟處理：", ""]
    for index, part in enumerate(parts, start=1):
        step = part.rstrip("。．. ")
        if index == len(parts) and cite:
            marker = re.search(r"\[S\d+\]", cite)
            suffix = f" {marker.group(0)}" if marker else ""
            lines.append(f"{index}. {step}{suffix}")
        else:
            lines.append(f"{index}. {step}")
    return "\n".join(lines)


def format_knowledge_answer_display(answer: str) -> str:
    """Apply deterministic layout polish for knowledge answers."""
    if not answer or not answer.strip():
        return answer
    text = split_condition_sentences(answer.strip())
    blocks = re.split(r"\n{2,}", text)
    formatted_blocks = [expand_conditional_howto_paragraph(block) for block in blocks]
    text = "\n\n".join(formatted_blocks)
    text = re.sub(
        r"(?<!\*)(Ctrl\s*\+\s*Alt\s*\+\s*Delete)(?!\*)",
        r"**\1**",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


__all__ = [
    "expand_conditional_howto_paragraph",
    "format_knowledge_answer_display",
    "split_condition_sentences",
]
