"""Parse AgentResponse nested payload fields."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from .contracts import AgentImage, Citation, IssueResult


def parse_citations(raw_citations: object) -> list[Citation]:
    citations: list[Citation] = []
    if not isinstance(raw_citations, list):
        return citations
    for item in raw_citations:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        url = item.get("url")
        chunk_id = item.get("chunkId")
        source_path = item.get("sourcePath")
        source_ref_id = item.get("sourceRefId")
        release_id = item.get("releaseId")
        original_url = item.get("originalUrl")
        if isinstance(title, str) and (isinstance(url, str) or url is None):
            citations.append(
                Citation(
                    title=title,
                    url=url if isinstance(url, str) and url.strip() else None,
                    chunkId=chunk_id if isinstance(chunk_id, str) else None,
                    sourcePath=(
                        source_path
                        if isinstance(source_path, str) and source_path.strip()
                        else None
                    ),
                    sourceRefId=(
                        source_ref_id
                        if isinstance(source_ref_id, str) and source_ref_id.strip()
                        else None
                    ),
                    releaseId=(
                        release_id
                        if isinstance(release_id, str) and release_id.strip()
                        else None
                    ),
                    originalUrl=(
                        original_url
                        if isinstance(original_url, str) and original_url.strip()
                        else None
                    ),
                )
            )
    return citations


def parse_images(raw_images: object) -> list[AgentImage]:
    images: list[AgentImage] = []
    if not isinstance(raw_images, list):
        return images
    for item in raw_images:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        title = item.get("title")
        alt_text = item.get("altText")
        source_chunk_id = item.get("sourceChunkId")
        release_id = item.get("releaseId")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (path, title, alt_text, source_chunk_id)
        ):
            continue
        pure_path = PurePosixPath(path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            continue
        images.append(
            AgentImage(
                path=pure_path.as_posix(),
                title=title.strip(),
                altText=alt_text.strip(),
                sourceChunkId=source_chunk_id.strip(),
                releaseId=(
                    release_id.strip()
                    if isinstance(release_id, str) and release_id.strip()
                    else None
                ),
            )
        )
    return images


def parse_issue_results(raw_issue_results: object) -> list[IssueResult]:
    issue_results: list[IssueResult] = []
    if not isinstance(raw_issue_results, list):
        return issue_results
    for item in raw_issue_results:
        if not isinstance(item, dict):
            continue
        issue_id = item.get("issueId")
        result_type = item.get("resultType")
        if not isinstance(issue_id, int) or isinstance(issue_id, bool):
            continue
        if not isinstance(result_type, str) or not result_type:
            continue
        answer_text = item.get("answer", "")
        issue_results.append(
            IssueResult(
                issueId=issue_id,
                resultType=result_type,
                answer=answer_text if isinstance(answer_text, str) else "",
            )
        )
    return issue_results


def parse_optional_cost(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, (int, float)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
