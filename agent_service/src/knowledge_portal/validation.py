from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path

from agent_service.documents import chunk_markdown, parse_front_matter

from .draft_assets import validate_asset_bundle
from .models import (
    AudienceType,
    ParsePreview,
    PreviewSegment,
    ValidationIssue,
    ValidationSummary,
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|client[_-]?secret|password|passwd|token)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(sk-[a-z0-9]{10,}|AIza[0-9A-Za-z\-_]{20,})\b"),
    re.compile(r"(?i)\b\d{3}-\d{2}-\d{4}\b"),
)
_EXTERNAL_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_iso_date(value: str) -> date | None:
    if not _DATE_PATTERN.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def build_parse_preview(markdown_content: str, title: str) -> ParsePreview:
    _, body = parse_front_matter(markdown_content)
    sections = re.split(r"(?m)(?=^#{1,3}\s+)", body.strip() or markdown_content)
    segments: list[PreviewSegment] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        heading_match = re.match(r"^#{1,3}\s+(.+)$", section, flags=re.MULTILINE)
        heading = heading_match.group(1).strip() if heading_match else title
        excerpt = re.sub(r"^#{1,6}\s+", "", section, flags=re.MULTILINE).strip()
        excerpt = excerpt[:280] + ("…" if len(excerpt) > 280 else "")
        segments.append(
            PreviewSegment(
                heading=heading,
                excerpt=excerpt,
                char_count=len(section),
            )
        )
    external_images = _EXTERNAL_IMAGE_PATTERN.findall(markdown_content)
    return ParsePreview(
        title=title,
        segments=segments[:12],
        image_count=len(re.findall(r"!\[[^\]]*\]\([^)]+\)", markdown_content)),
        external_image_urls=external_images,
    )


def validate_draft(
    *,
    title: str,
    owner_unit_id: str,
    change_reason: str,
    effective_at: str,
    review_due_at: str,
    audience_type: AudienceType,
    audience_group_ids: list[str],
    markdown_content: str,
    require_operational_fields: bool = True,
    asset_slug: str = "",
    draft_assets_root: Path | None = None,
) -> ValidationSummary:
    issues: list[ValidationIssue] = []

    def add(code: str, severity: str, message: str, field: str | None = None) -> None:
        issues.append(
            ValidationIssue(code=code, severity=severity, message=message, field=field)
        )

    if require_operational_fields:
        if not title.strip():
            add("TITLE_REQUIRED", "BLOCKING", "請填寫標題。", "title")
        if not owner_unit_id.strip():
            add("OWNER_REQUIRED", "BLOCKING", "請填寫擁有單位。", "owner_unit_id")
        if not change_reason.strip():
            add(
                "CHANGE_REASON_REQUIRED",
                "BLOCKING",
                "請填寫變更原因。",
                "change_reason",
            )
        if not effective_at.strip():
            add(
                "EFFECTIVE_DATE_REQUIRED",
                "BLOCKING",
                "請填寫生效日。",
                "effective_at",
            )
        if not review_due_at.strip():
            add(
                "REVIEW_DUE_REQUIRED",
                "BLOCKING",
                "請填寫下次檢視日。",
                "review_due_at",
            )

    effective = _parse_iso_date(effective_at)
    review_due = _parse_iso_date(review_due_at)
    if effective_at and effective is None:
        add("EFFECTIVE_DATE_INVALID", "BLOCKING", "生效日格式須為 YYYY-MM-DD。", "effective_at")
    if review_due_at and review_due is None:
        add("REVIEW_DUE_INVALID", "BLOCKING", "下次檢視日格式須為 YYYY-MM-DD。", "review_due_at")
    if effective and review_due and review_due < effective:
        add(
            "REVIEW_BEFORE_EFFECTIVE",
            "BLOCKING",
            "下次檢視日不可早於生效日。",
            "review_due_at",
        )

    if audience_type == "RESTRICTED_GROUPS" and not audience_group_ids:
        add(
            "AUDIENCE_GROUPS_REQUIRED",
            "BLOCKING",
            "特定群組可見時，至少須填寫一個群組。",
            "audience_group_ids",
        )
    if audience_type == "ALL_EMPLOYEES" and audience_group_ids:
        add(
            "AUDIENCE_GROUPS_IGNORED",
            "WARNING",
            "適用對象為全體員工時，特定群組設定將被忽略。",
            "audience_group_ids",
        )

    stripped = markdown_content.strip()
    if not stripped:
        add("EMPTY_CONTENT", "BLOCKING", "正文內容不可為空。", "markdown_content")
    else:
        try:
            parse_front_matter(stripped)
        except (TypeError, ValueError) as exc:
            add("FRONT_MATTER_INVALID", "BLOCKING", str(exc), "markdown_content")

    if not re.search(r"(?m)^#\s+\S", stripped):
        add(
            "MISSING_HEADING",
            "WARNING",
            "正文建議至少包含一個一級標題（#）。",
            "markdown_content",
        )

    for pattern in _SECRET_PATTERNS:
        if pattern.search(stripped):
            add(
                "SUSPECTED_SECRET",
                "BLOCKING",
                "內容疑似包含密碼、金鑰或其他敏感資訊。",
                "markdown_content",
            )
            break

    preview = build_parse_preview(stripped, title)
    if preview.external_image_urls:
        add(
            "EXTERNAL_IMAGE_URL",
            "BLOCKING",
            "外部圖片網址須先上傳至受控儲存後才能發布。",
            "markdown_content",
        )

    for image_match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", stripped):
        alt_text = image_match.group(1).strip()
        target = image_match.group(2).strip()
        if "://" not in target and not alt_text:
            add(
                "MISSING_ALT_TEXT",
                "WARNING",
                "圖片建議填寫替代文字。",
                "markdown_content",
            )
            break

    if asset_slug and draft_assets_root is not None:
        seen_codes: set[str] = set()
        for code, severity, message in validate_asset_bundle(
            stripped,
            asset_slug=asset_slug,
            assets_root=draft_assets_root,
        ):
            if code in seen_codes and code in {"MISSING_ALT_TEXT"}:
                continue
            seen_codes.add(code)
            add(code, severity, message, "markdown_content")

    if review_due:
        days = (review_due - datetime.now(UTC).date()).days
        if days < 0:
            add(
                "REVIEW_OVERDUE",
                "WARNING",
                "下次檢視日已過期。",
                "review_due_at",
            )
        elif days <= 7:
            add(
                "REVIEW_DUE_SOON",
                "INFO",
                "下次檢視日在 7 天內。",
                "review_due_at",
            )

    return ValidationSummary(issues=issues)


def build_front_matter_markdown(
    *,
    title: str,
    owner_unit_id: str,
    effective_at: str,
    review_due_at: str,
    audience_type: AudienceType,
    audience_group_ids: list[str],
    version_number: int,
    body: str,
) -> str:
    audience_values = (
        ["all-employees"]
        if audience_type == "ALL_EMPLOYEES"
        else audience_group_ids
    )
    front_matter = {
        "title": title,
        "owner": owner_unit_id,
        "version": str(version_number),
        "effectiveDate": effective_at,
        "reviewDate": review_due_at,
        "audience": audience_values,
    }
    import yaml

    header = yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False).strip()
    normalized_body = body.strip()
    if normalized_body.startswith("---"):
        return normalized_body
    return f"---\n{header}\n---\n\n{normalized_body}\n"


def estimate_retrieval_segments(markdown_content: str, title: str, chunk_size: int, overlap: int) -> int:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "draft.md"
        temp_path.write_text(markdown_content, encoding="utf-8")
        try:
            chunks = chunk_markdown(
                temp_path,
                "draft.md",
                chunk_size=chunk_size,
                overlap=overlap,
            )
        except (OSError, ValueError):
            return 0
        return len(chunks)
