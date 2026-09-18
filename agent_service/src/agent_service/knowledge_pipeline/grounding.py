"""Claim, citation, and coverage validation helpers (pure)."""

from __future__ import annotations

import re
from collections.abc import Callable

from agent_service.contracts import GroundedClaim
from agent_service.retrieval import SearchResult, tokenize
from agent_service.security_policies import SECURITY_POLICIES, is_policy_id

from .models import StructuredKnowledgeAnswer

_ERROR_CODE_TOKEN_RE = re.compile(r"\((-?\d{1,5})\)")
_PROCEDURE_QUERY_MARKERS: tuple[str, ...] = (
    "順序",
    "步驟",
    "首次設定",
    "視覺順序",
    "安裝步驟",
    "Visual Evidence",
    "先後順序",
    "操作章節",
    "如何設定",
    "設定順序",
)
# Distinctive executable steps that summarization often drops.
_PROCEDURE_STEP_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("intune_company_portal", ("intune", "公司入口網站")),
    ("qr_code_scan", ("qr code", "qrcode", "掃描電腦畫面")),
    ("number_matching", ("number matching", "數字匹配")),
    (
        "restart_outlook",
        ("重啟 outlook", "重新啟動 outlook", "重新開啟 outlook", "重啟app", "重啟 app"),
    ),
    ("second_device_verify", ("第二次", "再次驗證", "後續驗證", "裝置驗證")),
    # Avoid matching 「焦點收件匣」 alone; require completion/entry phrasing.
    ("reach_inbox", ("進入收件匣", "主介面", "收件匣使用", "進入 outlook 主")),
    ("bind_phone", ("綁定電話", "簡訊驗證")),
    ("authenticator", ("authenticator", "驗證器")),
)
_VISUAL_EVIDENCE_PLATE_RE = re.compile(r"\bp0(\d{2})\b", re.IGNORECASE)
_VISUAL_CHAPTER_RE = re.compile(r"###\s*(\d+)\.")
_VISUAL_HANDBOOK_PAGE_RE = re.compile(r"手冊第\s*(\d+)\s*頁")
_VISUAL_EVIDENCE_QUERY_MARKERS: tuple[str, ...] = (
    "Visual Evidence",
    "視覺順序",
    "視覺證據",
    "操作章節",
)
_COMPOSITE_S_MARKER_RE = re.compile(
    r"\[\s*((?:S\d+\s*[,，、]\s*)+S\d+)\s*\]",
    re.IGNORECASE,
)
_POLICY_MARKER_TOKEN = re.compile(r"\[POLICY-SEC-\d{3}\]")
_CITATION_OR_POLICY_MARKER = re.compile(r"\[(?:S\d+|POLICY-SEC-\d{3})\]")
_UNCITED_POLICY_LEAK_RE = re.compile(
    r"(?:"
    r"資料最小化|機敏資訊|登入密碼|憑證密碼|動態驗證碼|"
    r"遮蔽或移除|無關的個人|無關敏感|"
    r"變更(?:前|安全性設定前)(?:需|須)(?:先)?向|"
    r"切勿擅自變更|關閉\s*Proxy|停用\s*Proxy|"
    r"系統(?:資安|安全)政策|全域資安"
    r")",
    re.IGNORECASE,
)
_UNSAFE_ACTION_CLAIM = re.compile(
    r"(?:我|系統)?已(?:為您|替您|幫您)(?:建立|修改|重設|刪除|提交|核准)"
)
_PROMPT_DISCLOSURE_MARKERS = ("system prompt", "系統提示詞", "developer message")


def error_branch_codes_in_text(text: str) -> list[str]:
    """Extract parenthetical error codes like ``(-455)`` from knowledge context."""
    return list(dict.fromkeys(_ERROR_CODE_TOKEN_RE.findall(text)))


def answer_covers_error_branches(answer: str, codes: list[str]) -> bool:
    """Whether the answer mentions enough error-code branches from the context."""
    if len(codes) < 2:
        return True
    hits = sum(1 for code in codes if code in answer)
    required = max(2, (len(codes) + 1) // 2)
    return hits >= required


def query_asks_for_procedure(query: str) -> bool:
    return any(marker in query for marker in _PROCEDURE_QUERY_MARKERS)


def procedure_steps_in_text(text: str) -> list[str]:
    """Return distinctive procedure-step ids present in ``text``."""
    folded = text.casefold()
    found: list[str] = []
    for step_id, variants in _PROCEDURE_STEP_MARKERS:
        if any(variant.casefold() in folded for variant in variants):
            found.append(step_id)
    return found


def answer_covers_procedure_steps(answer: str, step_ids: list[str]) -> bool:
    """Whether the answer retains enough distinctive steps from the context."""
    if len(step_ids) < 2:
        return True
    answer_steps = set(procedure_steps_in_text(answer))
    hits = sum(1 for step_id in step_ids if step_id in answer_steps)
    required = max(2, (len(step_ids) + 1) // 2)
    return hits >= required


def query_asks_for_visual_evidence(query: str) -> bool:
    return any(marker in query for marker in _VISUAL_EVIDENCE_QUERY_MARKERS)


def visual_evidence_plates_in_text(text: str) -> list[str]:
    """Return handbook visual-structure markers from retrieved context.

    Indexed Outlook manuals use chapter headings (``### N.``) and
    ``手冊第 N 頁`` labels rather than raw ``p0N.png`` asset names. Prefer
    those stable markers; only keep ``p0N`` plates that appear beside
    Visual Evidence captions so unrelated PDFs do not pollute coverage.
    """
    markers: list[str] = []
    for match in _VISUAL_CHAPTER_RE.finditer(text):
        markers.append(f"chapter:{match.group(1)}")
    for match in _VISUAL_HANDBOOK_PAGE_RE.finditer(text):
        markers.append(f"page:{match.group(1)}")
    for match in _VISUAL_EVIDENCE_PLATE_RE.finditer(text):
        start = max(0, match.start() - 80)
        window = text[start : match.end() + 20]
        if "Visual Evidence" in window or "手冊" in window or "assets/" in window:
            markers.append(f"p0{match.group(1)}")
    return list(dict.fromkeys(markers))


def _answer_mentions_visual_marker(answer: str, marker: str) -> bool:
    kind, _, value = marker.partition(":")
    if kind == "chapter":
        # Do not treat ordinary numbered steps ("1. ...") as chapter citations.
        patterns = (
            rf"章節\s*{value}\b",
            rf"第\s*{value}\s*章",
            rf"###\s*{value}\.",
        )
        return any(re.search(pattern, answer) for pattern in patterns)
    if kind == "page":
        patterns = (
            rf"手冊第\s*{value}\s*頁",
            rf"第\s*{value}\s*頁",
            rf"\bp0{int(value):02d}\b",
        )
        return any(re.search(pattern, answer, flags=re.IGNORECASE) for pattern in patterns)
    # Raw p0N plate id.
    return re.search(rf"\b{re.escape(marker)}\b", answer, flags=re.IGNORECASE) is not None


def answer_covers_visual_evidence_plates(answer: str, plates: list[str]) -> bool:
    """Whether the answer cites enough visual-structure markers from context."""
    if len(plates) < 2:
        return True
    hits = sum(1 for plate in plates if _answer_mentions_visual_marker(answer, plate))
    required = max(2, (len(plates) + 1) // 2)
    return hits >= required


def missing_visual_evidence_plates(answer: str, plates: list[str]) -> list[str]:
    return [plate for plate in plates if not _answer_mentions_visual_marker(answer, plate)]


def missing_procedure_steps(answer: str, step_ids: list[str]) -> list[str]:
    answer_steps = set(procedure_steps_in_text(answer))
    return [step_id for step_id in step_ids if step_id not in answer_steps]


def normalize_composite_citation_markers(text: str) -> str:
    """Expand ``[S2, S3]`` style composites into discrete ``[S2][S3]`` markers."""

    def _expand(match: re.Match[str]) -> str:
        numbers = re.findall(r"S(\d+)", match.group(1), flags=re.IGNORECASE)
        return "".join(f"[S{number}]" for number in numbers)

    return _COMPOSITE_S_MARKER_RE.sub(_expand, text)


def claim_text_overlaps_chunk(claim_text: str, chunk_content: str) -> bool:
    """Require substantive overlap so S# remaps cannot cite an unrelated first chunk."""
    stop = {
        "可使",
        "使用",
        "可以",
        "進行",
        "相關",
        "問題",
        "內容",
        "說明",
        "根據",
        "以及",
        "或者",
        "若",
        "請",
        "需",
        "應",
    }
    claim_tokens = {
        token.casefold()
        for token in tokenize(claim_text)
        if len(token) >= 2 and token.casefold() not in stop
    }
    if not claim_tokens:
        return False
    content_tokens = {
        token.casefold()
        for token in tokenize(chunk_content)
        if len(token) >= 2 and token.casefold() not in stop
    }
    if not content_tokens:
        return False
    overlap = claim_tokens & content_tokens
    if not overlap:
        return False
    return len(overlap) / len(claim_tokens) >= 0.34 or len(overlap) >= 2


def remap_claim_marker_ids_to_chunk_ids(
    claims: list[GroundedClaim],
    *,
    marker_to_chunk_ids: dict[str, list[str]],
    chunk_content_by_id: dict[str, str] | None = None,
) -> list[GroundedClaim]:
    """Replace claim chunkIds like ``S1`` with supporting retrieved chunk ids.

    Concrete chunk ids emitted by the model are kept as-is. Marker ids (``S1``)
    expand to every chunk under that document marker and keep only chunks whose
    content overlaps the claim text—legal id remapping alone is not sufficient.
    """
    remapped: list[GroundedClaim] = []
    contents = chunk_content_by_id or {}
    for claim in claims:
        resolved_ids: list[str] = []
        for chunk_id in claim.chunkIds:
            key = chunk_id.strip()
            if is_policy_id(key):
                resolved_ids.append(key)
                continue
            if key.startswith("POLICY-SEC-"):
                # Unknown policy ids are dropped rather than treated as knowledge.
                continue
            is_marker = bool(re.fullmatch(r"[Ss]\d+", key))
            if not is_marker:
                # Model already cited a concrete chunk id; do not re-filter by overlap.
                if not contents or key in contents:
                    resolved_ids.append(key)
                continue
            candidates = (
                marker_to_chunk_ids.get(key) or marker_to_chunk_ids.get(key.upper()) or []
            )
            if contents:
                supported = [
                    candidate
                    for candidate in candidates
                    if candidate in contents
                    and claim_text_overlaps_chunk(claim.text, contents[candidate])
                ]
                resolved_ids.extend(supported)
            else:
                resolved_ids.extend(candidates)
        deduped = list(dict.fromkeys(cid for cid in resolved_ids if cid))
        if not deduped:
            continue
        remapped.append(claim.model_copy(update={"chunkIds": deduped}))
    return remapped


def prune_unbacked_sentences_and_citations(
    text: str,
    common_doc_keys: set[str],
    resolve_doc_key: Callable[[int], str | None],
) -> str:
    markers = set(re.findall(r"\[S(\d+)\]", text))
    unbacked_numbers = {
        int(m) for m in markers if resolve_doc_key(int(m)) not in common_doc_keys
    }
    cleaned = text
    if unbacked_numbers:
        lines = text.splitlines()
        cleaned_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append("")
                continue

            if _POLICY_MARKER_TOKEN.search(line) and not re.search(r"\[S\d+\]", line):
                cleaned_lines.append(line)
                continue

            line_cites = [int(m) for m in re.findall(r"\[S(\d+)\]", line)]
            if not line_cites:
                cleaned_lines.append(line)
                continue

            if all(c in unbacked_numbers for c in line_cites):
                continue

            sentences = re.split(r"(?<=[。！？\n])", line)
            cleaned_sentences: list[str] = []
            for sentence in sentences:
                if not sentence.strip():
                    continue
                if _POLICY_MARKER_TOKEN.search(sentence) and not re.search(
                    r"\[S\d+\]", sentence
                ):
                    cleaned_sentences.append(sentence)
                    continue
                s_cites = [int(m) for m in re.findall(r"\[S(\d+)\]", sentence)]
                if not s_cites:
                    cleaned_sentences.append(sentence)
                    continue
                if all(c in unbacked_numbers for c in s_cites):
                    continue

                clauses = re.split(r"(?<=[，；,;])", sentence)
                cleaned_clauses: list[str] = []
                for clause in clauses:
                    c_cites = [int(m) for m in re.findall(r"\[S(\d+)\]", clause)]
                    if c_cites and all(c in unbacked_numbers for c in c_cites):
                        continue
                    cleaned_clauses.append(clause)

                rebuilt = "".join(cleaned_clauses).strip()
                rebuilt = re.sub(r"[，；,;]+([。！？]?)$", r"\1", rebuilt)
                if rebuilt and not rebuilt.endswith(("。", "！", "？", "；", "，")):
                    rebuilt += "。"
                if rebuilt and (
                    _POLICY_MARKER_TOKEN.search(rebuilt)
                    or any(
                        int(m) not in unbacked_numbers
                        for m in re.findall(r"\[S(\d+)\]", rebuilt)
                    )
                ):
                    cleaned_sentences.append(rebuilt)

            if cleaned_sentences:
                cleaned_lines.append("".join(cleaned_sentences))

        cleaned_text = "\n".join(cleaned_lines)

        def _strip_any_remaining(match: re.Match[str]) -> str:
            val = int(match.group(1))
            if val in unbacked_numbers:
                return ""
            return match.group(0)

        cleaned = re.sub(r"\[S(\d+)\]", _strip_any_remaining, cleaned_text)

    return prune_uncited_material_sentences(cleaned)


def prune_uncited_material_sentences(text: str) -> str:
    """Remove uncited security-policy leaks clause-by-clause.

    A sibling clause that carries ``[S1]`` must not preserve a later
    uncited policy sentence on the same line. Procedure steps and ordinary
    knowledge prose without markers remain allowed.
    """
    lines = text.splitlines()
    kept_lines: list[str] = []
    for line in lines:
        if not line.strip():
            kept_lines.append("")
            continue
        sentences = re.split(r"(?<=[。！？\n])", line)
        kept_sentences: list[str] = []
        for sentence in sentences:
            if not sentence.strip():
                continue
            clauses = re.split(r"(?<=[，；,;])", sentence)
            kept_clauses: list[str] = []
            for clause in clauses:
                if not clause.strip():
                    continue
                if _CITATION_OR_POLICY_MARKER.search(clause):
                    kept_clauses.append(clause)
                    continue
                if _UNCITED_POLICY_LEAK_RE.search(clause):
                    continue
                kept_clauses.append(clause)
            if kept_clauses:
                kept_sentences.append("".join(kept_clauses))
        if kept_sentences:
            kept_lines.append("".join(kept_sentences))
    collapsed: list[str] = []
    previous_blank = False
    for line in kept_lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = is_blank
    return "\n".join(collapsed).strip()


def repair_structured_answer(
    response: StructuredKnowledgeAnswer,
) -> StructuredKnowledgeAnswer:
    # Align answerability and unknowns
    if response.answerability == "NONE" and response.claims:
        response.answerability = "PARTIAL" if response.unknowns else "FULL"
    elif response.answerability == "PARTIAL" and not response.unknowns:
        response.unknowns = ["未盡事宜或特定限制以權責單位規範為準"]
    elif response.answerability == "FULL" and response.unknowns:
        response.answerability = "PARTIAL"
    elif response.answerability is None:
        response.answerability = "FULL" if not response.unknowns else "PARTIAL"
    return response


def structured_answer_is_grounded(
    answer: StructuredKnowledgeAnswer,
    results: list[SearchResult],
) -> bool:
    if (
        answer.answerability == "NONE"
        or not answer.answer.strip()
        or not answer_passes_safety_checks(answer.answer)
    ):
        return False
    if answer.answerability == "PARTIAL" and not answer.unknowns:
        return False
    if answer.answerability == "FULL" and answer.unknowns:
        return False
    valid_chunk_ids = {result.chunk.chunk_id for result in results}
    valid_policy_ids = set(SECURITY_POLICIES)
    if not answer.claims:
        return False
    valid_claims: list[GroundedClaim] = []
    has_knowledge_claim = False
    for claim in answer.claims:
        if not claim.text.strip() or not claim.chunkIds:
            continue
        knowledge_ids = [chunk_id for chunk_id in claim.chunkIds if not is_policy_id(chunk_id)]
        policy_ids = [chunk_id for chunk_id in claim.chunkIds if is_policy_id(chunk_id)]
        if knowledge_ids and set(knowledge_ids) <= valid_chunk_ids:
            valid_claims.append(claim)
            has_knowledge_claim = True
        elif not knowledge_ids and policy_ids and set(policy_ids) <= valid_policy_ids:
            valid_claims.append(claim)
    if not valid_claims or not has_knowledge_claim:
        return False
    answer.claims = valid_claims
    return True


def answer_passes_safety_checks(answer: str) -> bool:
    normalized = answer.casefold()
    return not _UNSAFE_ACTION_CLAIM.search(answer) and not any(
        marker in normalized for marker in _PROMPT_DISCLOSURE_MARKERS
    )
