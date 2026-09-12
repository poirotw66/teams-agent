"""Fixture adapters and sandbox services for evaluation runtime.

Provides isolated mock repositories for FAQ, Knowledge (release chunks or
deterministic fixture), and Ticket services during evaluation sandbox runs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EvalBindingError(RuntimeError):
    """Candidate prompt, model, FAQ version, or knowledge release could not be bound to eval runtime."""


class _FixtureFaqRepository:
    """FAQ catalog for isolated eval probes: loads requested faq_version_id, or falls back to fixture only when unspecified."""

    def __init__(
        self,
        faq_version_id: str | None = None,
        faq_repository: Any = None,
    ) -> None:
        from agent_service.contracts import FaqEntry

        self.version_id = str(faq_version_id or "eval-faq-v1")
        self._entries: dict[str, FaqEntry] = {}

        if faq_version_id and faq_version_id not in ("eval-faq-v1", "default"):
            resolved = False
            if faq_repository is not None:
                try:
                    version_record = faq_repository.get_version(self.version_id)
                    if version_record:
                        faq_rec = faq_repository.get_faq(version_record.faq_id)
                        raw_content = getattr(version_record, "content", None)
                        faq_key = (
                            getattr(faq_rec, "faq_key", None)
                            or getattr(raw_content, "faq_key", None)
                            or self.version_id
                        )
                        if hasattr(raw_content, "answer"):
                            answer_text = raw_content.answer
                        elif isinstance(raw_content, dict):
                            answer_text = raw_content.get("answer", "")
                        elif raw_content is not None:
                            answer_text = str(raw_content)
                        else:
                            answer_text = getattr(version_record, "answer", "")
                        status = getattr(version_record, "status", "ACTIVE")
                        self._entries[faq_key] = FaqEntry(
                            id=version_record.version_id,
                            faqKey=faq_key,
                            enabled=status not in ("DISABLED", "SUPERSEDED"),
                            answer=str(answer_text),
                            versionId=self.version_id,
                        )
                        resolved = True
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "FAQ repository lookup failed for version=%s: %s",
                        self.version_id,
                        exc,
                    )
                    resolved = False

            if not resolved:
                raise EvalBindingError(f"faq_version_not_found:{self.version_id}")
        else:
            self._entries["account.unlock"] = FaqEntry(
                id="faq-account-unlock",
                faqKey="account.unlock",
                enabled=True,
                answer="帳號鎖定時請至自助解鎖頁面，或聯繫資訊小幫手。",
                versionId=self.version_id,
            )

    def get(self, faq_key: str, audience_group_ids: tuple[str, ...] = ()) -> Any:
        _ = audience_group_ids
        return self._entries.get(faq_key)

    def available_keys(self, audience_group_ids: tuple[str, ...] = ()) -> list[str]:
        _ = audience_group_ids
        return sorted(self._entries)


class _FixtureKnowledgeService:
    """Knowledge search for eval probes: queries release chunks if knowledge_release_id is present, else falls back to fixtures."""

    def __init__(
        self,
        release_id: str | None = None,
        releases_dir: Any | None = None,
    ) -> None:
        self.tool_calls: list[dict[str, Any]] = []
        self.release_id = str(release_id).strip() if release_id else None
        self.releases_dir = releases_dir
        self._chunks: list[dict[str, Any]] | None = None

    def _load_release_chunks(self) -> list[dict[str, Any]]:
        if self._chunks is not None:
            return self._chunks
        if not self.release_id:
            self._chunks = []
            return self._chunks
        if not self.releases_dir:
            raise EvalBindingError(f"releases_dir_not_configured_for_release:{self.release_id}")

        rel_dir = Path(self.releases_dir) / self.release_id
        cand1 = rel_dir / "index" / "chunks.json"
        cand2 = rel_dir / "chunks.json"
        chosen = cand1 if cand1.is_file() else (cand2 if cand2.is_file() else None)
        if not chosen:
            raise EvalBindingError(f"knowledge_release_not_found:{self.release_id}")
        try:
            data = json.loads(chosen.read_text(encoding="utf-8"))
            self._chunks = list(data.get("chunks", []))
        except Exception as exc:
            raise EvalBindingError(f"knowledge_release_read_failed:{self.release_id}:{exc}") from exc
        return self._chunks

    async def search(self, query: str, user_context: Any, **kwargs: Any) -> Any:
        from agent_service.contracts import Citation, KnowledgeResult

        groups = set(
            getattr(user_context, "groups", None)
            or getattr(user_context, "audience_group_ids", None)
            or ()
        )
        _ = kwargs

        # When an explicit release_id is requested, NEVER fall back to eval-fixture
        if self.release_id:
            chunks = self._load_release_chunks()
            query_tokens = [t.lower() for t in query.split() if len(t) > 1]
            cjk_chars = [ch for ch in query if "\u4e00" <= ch <= "\u9fff" or ch.isalnum()]
            for i in range(len(cjk_chars) - 1):
                query_tokens.append("".join(cjk_chars[i:i + 2]).lower())
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
                    Citation(
                        title=str(c.get("title", "Release Doc")),
                        url=str(c.get("source_path", c.get("source_id", f"release://{self.release_id}"))),
                        chunkId=str(c.get("chunk_id", "")),
                    )
                    for c in top_chunks
                ]
                combined_answer = "\n".join(str(c.get("content", ""))[:200] for c in top_chunks)
                result = KnowledgeResult(
                    found=True,
                    answer=combined_answer,
                    sources=citations,
                    images=[],
                    backend="release-index",
                )
            else:
                result = KnowledgeResult(
                    found=False,
                    answer="",
                    sources=[],
                    images=[],
                    backend="release-index",
                )

            self.tool_calls.append(
                {
                    "call_id": f"knowledge-search-{len(self.tool_calls)}",
                    "tool_name": "knowledge.search",
                    "arguments": {
                        "query": query,
                        "groups": list(groups) if groups else [],
                        "backend": "release-index",
                        "release_id": self.release_id,
                    },
                    "result": {
                        "found": result.found,
                        "source_count": len(result.sources),
                        "chunk_ids": [c.chunkId for c in result.sources],
                    },
                    "duration_ms": 0.0,
                    "is_error": False,
                    "was_intercepted": True,
                    "side_effect_blocked": False,
                    "intercept_reason": "sandbox_release_index",
                }
            )
            return result

        # Only used when no knowledge_release_id was specified
        normalized = (query or "").casefold()
        miss_markers = ("網路打不開", "無法上網", "打不開", "按鈕無法點選")
        if any(marker in query for marker in miss_markers):
            result = KnowledgeResult(
                found=False, answer="", sources=[], images=[], backend="eval-fixture"
            )
        else:
            hit = (
                ("vpn" in normalized and any(token in query for token in ("密碼", "鎖定", "lock")))
                or ("帳號鎖定" in query)
                or ("vpn 密碼鎖定" in normalized)
            )
            if hit:
                result = KnowledgeResult(
                    found=True,
                    answer="VPN 或帳號鎖定時，請先自助解鎖；仍無法登入再聯繫資訊小幫手。[S1]",
                    sources=[
                        Citation(
                            title="帳號與 VPN 解鎖 FAQ",
                            url="eval://fixture/unlock",
                            chunkId="eval-unlock-1",
                        )
                    ],
                    images=[],
                    backend="eval-fixture",
                )
            else:
                result = KnowledgeResult(
                    found=False, answer="", sources=[], images=[], backend="eval-fixture"
                )
        self.tool_calls.append(
            {
                "call_id": f"knowledge-search-{len(self.tool_calls)}",
                "tool_name": "knowledge.search",
                "arguments": {
                    "query": query,
                    "groups": list(groups) if groups else [],
                    "backend": "eval-fixture",
                },
                "result": {
                    "found": bool(result.found),
                    "source_count": len(list(result.sources or [])),
                    "chunk_ids": [
                        getattr(src, "chunkId", None) for src in list(result.sources or [])
                    ],
                },
                "duration_ms": 0.0,
                "is_error": False,
                "was_intercepted": True,
                "side_effect_blocked": False,
                "intercept_reason": "sandbox_fixture",
            }
        )
        return result

    def consume_tool_calls(self) -> list[dict[str, Any]]:
        calls = list(self.tool_calls)
        self.tool_calls = []
        return calls


class _EvalTicketService:
    """Mock ticket service recording ticket creation and tool calls in evaluation sandbox."""

    def __init__(self) -> None:
        self.created_tickets: list[Any] = []
        self.tool_calls: list[dict[str, Any]] = []

    async def get_ticket_items(self, *, correlation_id: str | None = None) -> list[Any]:
        _ = correlation_id
        self.tool_calls.append(
            {
                "call_id": f"ticket-items-{len(self.tool_calls)}",
                "tool_name": "ticket.get_ticket_items",
                "arguments": {"correlation_id": correlation_id},
                "result": {"items": []},
                "duration_ms": 0.0,
                "is_error": False,
                "was_intercepted": True,
                "side_effect_blocked": False,
                "intercept_reason": "sandbox_fixture",
            }
        )
        return []

    async def create_ticket(self, draft: Any, **kwargs: Any) -> Any:
        self.created_tickets.append(draft)
        arguments = {
            "title": getattr(draft, "title", None),
            "description": getattr(draft, "description", None),
            "category": getattr(draft, "category", None),
            "priority": getattr(draft, "priority", None),
        }
        arguments.update({key: kwargs[key] for key in kwargs})
        from agent_service.contracts import Ticket

        ticket = Ticket(
            id=f"EVAL-{len(self.created_tickets)}",
            title=getattr(draft, "title", "eval-ticket") or "eval-ticket",
            status="OPEN",
        )
        self.tool_calls.append(
            {
                "call_id": f"ticket-create-{len(self.tool_calls)}",
                "tool_name": "ticket.create_ticket",
                "arguments": arguments,
                "result": {"ticket_id": ticket.id, "status": ticket.status},
                "duration_ms": 0.0,
                "is_error": False,
                "was_intercepted": True,
                "side_effect_blocked": False,
                "intercept_reason": "sandbox_fixture",
            }
        )
        return ticket

    async def list_tickets_by_requester(
        self, requester_id: str, *, correlation_id: str | None = None
    ) -> list[Any]:
        _ = requester_id, correlation_id
        return []

    async def get_ticket(
        self, ticket_id: str, requester_id: str, *, correlation_id: str | None = None
    ) -> Any:
        _ = ticket_id, requester_id, correlation_id
        return None

    def consume_tool_calls(self) -> list[dict[str, Any]]:
        calls = list(self.tool_calls)
        self.tool_calls = []
        return calls
