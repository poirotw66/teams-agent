"""Knowledge search helpers for evaluation fixture repositories."""

from __future__ import annotations

from typing import Any


def search_release_index(
    *,
    query: str,
    groups: set[Any],
    chunks: list[dict[str, Any]],
    release_id: str,
    bindings: Any,
) -> Any:
    query_tokens = [t.lower() for t in query.split() if len(t) > 1]
    cjk_chars = [ch for ch in query if "\u4e00" <= ch <= "\u9fff" or ch.isalnum()]
    for i in range(len(cjk_chars) - 1):
        query_tokens.append("".join(cjk_chars[i : i + 2]).lower())
    if not query_tokens:
        query_tokens = [query.lower()]

    matched: list[tuple[int, dict[str, Any]]] = []
    for chunk in chunks:
        chunk_groups = set(chunk.get("allowed_groups") or chunk.get("acl_groups") or [])
        if chunk_groups and not (chunk_groups & groups):
            continue
        content = str(chunk.get("content", "")).lower()
        title = str(chunk.get("title", "")).lower()
        score = sum(1 for tok in query_tokens if tok in content or tok in title)
        if score > 0:
            matched.append((score, chunk))

    matched.sort(key=lambda x: x[0], reverse=True)
    if matched:
        top_chunks = [item[1] for item in matched[:3]]
        citations = [
            bindings.build_citation(
                title=str(c.get("title", "Release Doc")),
                url=str(c.get("source_path", c.get("source_id", f"release://{release_id}"))),
                chunkId=str(c.get("chunk_id", "")),
            )
            for c in top_chunks
        ]
        combined_answer = "\n".join(str(c.get("content", ""))[:200] for c in top_chunks)
        return bindings.build_knowledge_result(
            found=True,
            answer=combined_answer,
            sources=citations,
            images=[],
            backend="release-index",
        )
    return bindings.build_knowledge_result(
        found=False,
        answer="",
        sources=[],
        images=[],
        backend="release-index",
    )


def search_eval_fixture(*, query: str, bindings: Any) -> Any:
    normalized = (query or "").casefold()
    miss_markers = ("網路打不開", "無法上網", "打不開", "按鈕無法點選")
    if any(marker in query for marker in miss_markers):
        return bindings.build_knowledge_result(
            found=False, answer="", sources=[], images=[], backend="eval-fixture"
        )
    hit = (
        ("vpn" in normalized and any(token in query for token in ("密碼", "鎖定", "lock")))
        or ("帳號鎖定" in query)
        or ("vpn 密碼鎖定" in normalized)
    )
    if hit:
        return bindings.build_knowledge_result(
            found=True,
            answer="VPN 或帳號鎖定時，請先自助解鎖；仍無法登入再聯繫資訊小幫手。[S1]",
            sources=[
                bindings.build_citation(
                    title="帳號與 VPN 解鎖 FAQ",
                    url="eval://fixture/unlock",
                    chunkId="eval-unlock-1",
                )
            ],
            images=[],
            backend="eval-fixture",
        )
    return bindings.build_knowledge_result(
        found=False, answer="", sources=[], images=[], backend="eval-fixture"
    )


def record_knowledge_tool_call(
    tool_calls: list[dict[str, Any]],
    *,
    query: str,
    groups: set[Any],
    result: Any,
    backend: str,
    release_id: str | None = None,
    intercept_reason: str,
) -> None:
    arguments: dict[str, Any] = {
        "query": query,
        "groups": list(groups) if groups else [],
        "backend": backend,
    }
    if release_id is not None:
        arguments["release_id"] = release_id
    tool_calls.append(
        {
            "call_id": f"knowledge-search-{len(tool_calls)}",
            "tool_name": "knowledge.search",
            "arguments": arguments,
            "result": {
                "found": bool(result.found),
                "source_count": len(list(result.sources or [])),
                "chunk_ids": [getattr(src, "chunkId", None) for src in list(result.sources or [])],
            },
            "duration_ms": 0.0,
            "is_error": False,
            "was_intercepted": True,
            "side_effect_blocked": False,
            "intercept_reason": intercept_reason,
        }
    )
