"""Gemini File Search Knowledge Service adapter — SPIKE ONLY (spec §8.3).

Per spec §8.3, Gemini File Search is *only* a candidate adapter behind
``KNOWLEDGE_SERVICE_MODE=GEMINI_FILE_SEARCH``. It must not replace
``HybridKnowledgeService`` (spec §8.2) as the default in this phase, and
this phase only requires a technical spike (create a store, upload a few
test documents, run Traditional Chinese queries, inspect sources, test a
metadata filter, test document deletion, compare error-code/專有名詞 recall)
rather than a full File Search document-sync platform.

The ``google-genai`` SDK is treated as an optional, spike-only dependency
(pyproject ``[project.optional-dependencies].spike``). It is imported lazily
inside ``search()`` so importing this module — and running the rest of the
test suite — never requires it to be installed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import Citation, KnowledgeResult, UserContext

_SDK_INSTALL_HINT = (
    "google-genai is required for GeminiFileSearchKnowledgeService. "
    "Install the spike extra: pip install 'teams-agent-rag-service[spike]' "
    "(or `uv sync --extra spike` from agent_service/)."
)


def _import_genai():
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:  # pragma: no cover - exercised only without SDK
        raise ImportError(_SDK_INSTALL_HINT) from exc
    return genai, types


@dataclass(frozen=True)
class GeminiGroundingChunk:
    """A single grounding chunk as returned by the File Search API.

    Kept as a small internal shape so mapping-to-``KnowledgeResult`` logic is
    independently testable without a live API response object.
    """

    title: str
    uri: str | None
    document_name: str | None
    text: str | None


class GeminiFileSearchKnowledgeService:
    """Candidate Knowledge Service adapter backed by Gemini File Search.

    NOT the default. Selected only when
    ``settings.knowledge_service_mode == "GEMINI_FILE_SEARCH"``.
    """

    def __init__(
        self,
        api_key: str | None,
        file_search_store: str,
        model: str = "gemini-2.5-flash",
        top_k: int = 4,
    ) -> None:
        if not file_search_store:
            raise ValueError(
                "file_search_store is required (GEMINI_FILE_SEARCH_STORE)."
            )
        self.api_key = api_key
        self.file_search_store = file_search_store
        self.model = model
        self.top_k = top_k
        self._client = None

    def _get_client(self):
        genai, _types = _import_genai()
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    async def search(
        self,
        query: str,
        user_context: UserContext,
        *,
        correlation_id: str | None = None,
        metadata_filter: str | None = None,
    ) -> KnowledgeResult:
        """Run a grounded query against the configured File Search store.

        Note: this is a spike-quality synchronous-under-the-hood call (the
        google-genai client is sync); it is wrapped so the async
        ``KnowledgeService`` Protocol shape (spec §8.1) is satisfied. ACL /
        tenant allowlist enforcement for File Search stores is NOT part of
        this spike (spec §8.3 explicitly scopes the spike to store creation,
        upload, Chinese queries, sources, metadata filter, deletion and
        error-code comparison only) — do not select GEMINI_FILE_SEARCH mode
        for any environment carrying ACL-restricted documents until that is
        addressed.
        """
        _genai, types = _import_genai()
        client = self._get_client()

        file_search_tool = types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[self.file_search_store],
                top_k=self.top_k,
                metadata_filter=metadata_filter,
            )
        )
        response = await client.aio.models.generate_content(
            model=self.model,
            contents=query,
            config=types.GenerateContentConfig(tools=[file_search_tool]),
        )

        chunks = self._grounding_chunks(response)
        if not chunks:
            # Spec §8.4: 找不到答案時明確表示未命中, 不得編造.
            return KnowledgeResult(
                found=False,
                answer="",
                sources=[],
                images=[],
                backend="GEMINI_FILE_SEARCH",
            )

        answer = self._response_text(response)
        sources = [
            Citation(title=chunk.title, url=chunk.uri, chunkId=chunk.document_name)
            for chunk in chunks
        ]
        return KnowledgeResult(
            found=True,
            answer=answer,
            sources=sources,
            images=[],  # spike does not map File Search results to AgentImage
            backend="GEMINI_FILE_SEARCH",
        )

    @staticmethod
    def _response_text(response) -> str:
        text = getattr(response, "text", None)
        return str(text).strip() if text else ""

    @staticmethod
    def _grounding_chunks(response) -> list[GeminiGroundingChunk]:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            return []
        grounding_metadata = getattr(candidates[0], "grounding_metadata", None)
        if not grounding_metadata:
            return []
        raw_chunks = getattr(grounding_metadata, "grounding_chunks", None) or []

        chunks: list[GeminiGroundingChunk] = []
        for raw in raw_chunks:
            context = getattr(raw, "retrieved_context", None)
            if not context:
                continue
            title = getattr(context, "title", None) or getattr(context, "uri", None) or "未命名文件"
            chunks.append(
                GeminiGroundingChunk(
                    title=title,
                    uri=getattr(context, "uri", None),
                    document_name=getattr(context, "document_name", None),
                    text=getattr(context, "text", None),
                )
            )
        return chunks
