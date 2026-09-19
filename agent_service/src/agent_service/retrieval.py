import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from langchain.embeddings import init_embeddings

from knowledge_core.contextual_representation import effective_retrieval_text

from .documents import DocumentChunk
from .knowledge_eligibility import is_chunk_generation_eligible

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_./:\\-]+|[\u3400-\u9fff]+")


def hybrid_index_fusion_kwargs(settings: object) -> dict[str, object]:
    """Map RagSettings fusion knobs onto HybridIndex constructor kwargs."""
    return {
        "fusion_mode": str(getattr(settings, "rag_fusion_mode", "RRF")),
        "rrf_k": int(getattr(settings, "rag_rrf_k", 5)),
        "sparse_candidate_k": int(getattr(settings, "rag_sparse_candidate_k", 40)),
        "dense_candidate_k": int(getattr(settings, "rag_dense_candidate_k", 10)),
        "fusion_candidate_k": int(getattr(settings, "rag_fusion_candidate_k", 20)),
        "sparse_weight": float(getattr(settings, "rag_sparse_weight", 0.5)),
        "dense_weight": float(getattr(settings, "rag_dense_weight", 1.5)),
    }

def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in TOKEN_PATTERN.findall(text.lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", match):
            tokens.extend(match)
            tokens.extend(match[index : index + 2] for index in range(len(match) - 1))
        else:
            tokens.append(match)
    return tokens


def sparse_index_text(chunk: DocumentChunk) -> str:
    """BM25 document text: prefer contextual retrieval_text when present."""
    contextual = (chunk.retrieval_text or "").strip()
    if contextual:
        return contextual
    fields = [
        chunk.title,
        *chunk.source_aliases,
        chunk.section or "",
        chunk.section_path or "",
        *chunk.heading_path,
        chunk.content,
    ]
    return "\n".join(field for field in fields if field)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot_product / (left_norm * right_norm)


def is_chunk_visible_to_groups(
    chunk: DocumentChunk,
    groups: set[str] | None,
) -> bool:
    """Return whether Hybrid ACL allows the caller to see ``chunk``.

    Empty ``allowed_groups`` means public. Otherwise the caller's groups must
    intersect the document allowlist.
    """
    caller_groups = groups or set()
    if not chunk.allowed_groups:
        return True
    return bool(set(chunk.allowed_groups).intersection(caller_groups))


@dataclass(frozen=True)
class SearchResult:
    chunk: DocumentChunk
    score: float
    sparse_score: float
    dense_score: float | None = None
    # RAG v2 ranking provenance (docs/rag-v2-spec.md §10). Optional for
    # backward compatibility with weighted hybrid callers.
    sparse_rank: int | None = None
    dense_rank: int | None = None
    fusion_score: float | None = None
    fusion_rank: int | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None
    final_rank: int | None = None


def _normalize_embedding_model_id(model_id: str) -> str:
    """Compare embedding ids with or without provider prefix."""

    normalized = model_id.strip()
    if ":" in normalized:
        return normalized.split(":", 1)[1].strip()
    return normalized


def _embedding_models_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    return _normalize_embedding_model_id(left) == _normalize_embedding_model_id(right)


class HybridIndex:
    def __init__(
        self,
        chunks: list[DocumentChunk],
        embedding_model: str | None = None,
        *,
        fusion_mode: str = "RRF",
        rrf_k: int = 5,
        sparse_candidate_k: int = 40,
        dense_candidate_k: int = 10,
        fusion_candidate_k: int = 20,
        sparse_weight: float = 0.5,
        dense_weight: float = 1.5,
    ) -> None:
        self.chunks = chunks
        self.embedding_model_name = embedding_model
        self.embedding_client = init_embeddings(embedding_model) if embedding_model else None
        self.tokenized_documents = [tokenize(sparse_index_text(chunk)) for chunk in chunks]
        self.last_search_timings_ms: dict[str, float] = {}
        self.fusion_mode = (fusion_mode or "RRF").strip().upper()
        if self.fusion_mode not in {"RRF", "WEIGHTED", "LEGACY_WEIGHTED"}:
            self.fusion_mode = "RRF"
        self.rrf_k = rrf_k
        self.sparse_candidate_k = sparse_candidate_k
        self.dense_candidate_k = dense_candidate_k
        self.fusion_candidate_k = fusion_candidate_k
        self.sparse_weight = sparse_weight
        self.dense_weight = dense_weight

    @classmethod
    def load(
        cls,
        index_path: Path,
        embedding_model: str | None = None,
        **fusion_kwargs: object,
    ) -> "HybridIndex":
        value = json.loads(index_path.read_text(encoding="utf-8"))
        chunks = [DocumentChunk.from_dict(item) for item in value["chunks"]]
        indexed_model = value.get("embeddingModel")
        if (
            indexed_model
            and embedding_model
            and not _embedding_models_compatible(indexed_model, embedding_model)
        ):
            raise ValueError(
                "Configured embedding model does not match the built index. Run rag-index again."
            )
        # Prefer a provider-prefixed id so init_embeddings can resolve the client.
        runtime_model = None
        if indexed_model:
            if embedding_model and ":" in embedding_model:
                runtime_model = embedding_model
            elif ":" in str(indexed_model):
                runtime_model = str(indexed_model)
            else:
                runtime_model = embedding_model or str(indexed_model)
        return cls(chunks, runtime_model, **fusion_kwargs)  # type: ignore[arg-type]

    def save(self, index_path: Path) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        has_contextual = any((chunk.retrieval_text or "").strip() for chunk in self.chunks)
        contextual_versions = {
            chunk.contextualization_version
            for chunk in self.chunks
            if chunk.contextualization_version
        }
        payload = {
            "version": 2 if has_contextual else 1,
            "indexSchemaVersion": 2 if has_contextual else 1,
            "contextualizationVersion": (
                next(iter(contextual_versions)) if len(contextual_versions) == 1 else None
            ),
            "embeddingModel": self.embedding_model_name,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
        }
        index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_embeddings(self) -> None:
        if not self.embedding_client:
            return
        vectors = self.embedding_client.embed_documents(
            [effective_retrieval_text(chunk) for chunk in self.chunks]
        )
        for chunk, vector in zip(self.chunks, vectors, strict=True):
            chunk.vector = vector

    def _bm25_scores(
        self,
        query: str,
        candidate_indices: list[int],
    ) -> list[float]:
        query_terms = tokenize(query)
        candidate_tokens = [self.tokenized_documents[index] for index in candidate_indices]
        document_count = len(candidate_tokens)
        average_length = (
            mean(len(tokens) for tokens in candidate_tokens) if candidate_tokens else 0.0
        )
        if not query_terms or not document_count or average_length == 0:
            return [0.0] * len(self.chunks)

        document_frequencies: Counter[str] = Counter()
        for tokens in candidate_tokens:
            document_frequencies.update(set(tokens))

        k1 = 1.5
        b = 0.75
        scores = [0.0] * len(self.chunks)
        for index in candidate_indices:
            document_tokens = self.tokenized_documents[index]
            term_counts = Counter(document_tokens)
            document_length = len(document_tokens)
            score = 0.0
            for term in query_terms:
                frequency = term_counts[term]
                if frequency == 0:
                    continue
                document_frequency = document_frequencies[term]
                inverse_document_frequency = math.log(
                    1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                numerator = frequency * (k1 + 1)
                denominator = frequency + k1 * (1 - b + b * document_length / average_length)
                score += inverse_document_frequency * numerator / denominator
            scores[index] = score
        return scores

    def search(
        self,
        query: str,
        limit: int,
        groups: set[str] | None = None,
        *,
        environment: str = "dev",
        fusion_mode: str | None = None,
    ) -> list[SearchResult]:
        results, timings = self.search_with_timings(
            query,
            limit,
            groups,
            environment=environment,
            fusion_mode=fusion_mode,
        )
        self.last_search_timings_ms = timings
        return results

    def search_with_timings(
        self,
        query: str,
        limit: int,
        groups: set[str] | None = None,
        *,
        environment: str = "dev",
        fusion_mode: str | None = None,
    ) -> tuple[list[SearchResult], dict[str, float]]:
        """Search and return per-call timings from locals (safe under parallel calls)."""
        from .retrieval_fusion import fuse_hybrid_candidates

        groups = groups or set()
        effective_mode = (fusion_mode or self.fusion_mode or "RRF").strip().upper()
        # WEIGHTED and LEGACY_WEIGHTED both run the linear blend path so A/B
        # baselines stay honest (RAG v2.1 — do not alias WEIGHTED → RRF).
        use_legacy_weighted = effective_mode in {"WEIGHTED", "LEGACY_WEIGHTED"}
        started = time.perf_counter()
        authorized_indices = [
            index
            for index, chunk in enumerate(self.chunks)
            if is_chunk_visible_to_groups(chunk, groups)
            and is_chunk_generation_eligible(chunk, environment=environment)
        ]
        sparse_started = time.perf_counter()
        sparse_scores = self._bm25_scores(query, authorized_indices)
        sparse_ms = (time.perf_counter() - sparse_started) * 1000
        max_sparse = max(sparse_scores, default=0.0)
        normalized_sparse = [
            score / max_sparse if max_sparse else 0.0 for score in sparse_scores
        ]

        query_vector: list[float] | None = None
        embedding_ms = 0.0
        if self.embedding_client and any(chunk.vector for chunk in self.chunks):
            embed_started = time.perf_counter()
            query_vector = self.embedding_client.embed_query(query)
            embedding_ms = (time.perf_counter() - embed_started) * 1000

        results = self._candidate_results(authorized_indices, normalized_sparse, query_vector)
        sparse_candidate_k = self.sparse_candidate_k
        dense_candidate_k = self.dense_candidate_k
        sparse_weight = self.sparse_weight
        dense_weight = self.dense_weight
        if not use_legacy_weighted:
            from .retrieval_adaptive_fusion import adaptive_fusion_weights

            weights = adaptive_fusion_weights(
                query,
                default_sparse_weight=self.sparse_weight,
                default_dense_weight=self.dense_weight,
                default_sparse_candidate_k=self.sparse_candidate_k,
                default_dense_candidate_k=self.dense_candidate_k,
            )
            sparse_candidate_k = weights.sparse_candidate_k
            dense_candidate_k = weights.dense_candidate_k
            sparse_weight = weights.sparse_weight
            dense_weight = weights.dense_weight
        filtered = fuse_hybrid_candidates(
            results,
            query=query,
            limit=limit,
            sparse_candidate_k=sparse_candidate_k,
            dense_candidate_k=dense_candidate_k,
            fusion_candidate_k=self.fusion_candidate_k,
            rrf_k=self.rrf_k,
            sparse_weight=sparse_weight,
            dense_weight=dense_weight,
            legacy_weighted=use_legacy_weighted,
        )
        timings = {
            "embeddingMs": round(embedding_ms, 1),
            "sparseMs": round(sparse_ms, 1),
            "searchTotalMs": round((time.perf_counter() - started) * 1000, 1),
        }
        return filtered, timings

    def _candidate_results(
        self,
        authorized_indices: list[int],
        normalized_sparse: list[float],
        query_vector: list[float] | None,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for index in authorized_indices:
            chunk = self.chunks[index]
            dense_score: float | None = None
            score = normalized_sparse[index]
            if query_vector is not None and chunk.vector:
                dense_score = max(0.0, cosine_similarity(query_vector, chunk.vector))
                score = dense_score
            results.append(
                SearchResult(
                    chunk=chunk,
                    score=round(score, 6),
                    sparse_score=round(normalized_sparse[index], 6),
                    dense_score=round(dense_score, 6) if dense_score is not None else None,
                )
            )
        return results
