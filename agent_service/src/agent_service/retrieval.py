import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

from langchain.embeddings import init_embeddings

from .documents import DocumentChunk
from .knowledge_eligibility import is_chunk_generation_eligible

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_./:\\-]+|[\u3400-\u9fff]+")


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


@dataclass(frozen=True)
class SearchResult:
    chunk: DocumentChunk
    score: float
    sparse_score: float
    dense_score: float | None = None


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
    ) -> None:
        self.chunks = chunks
        self.embedding_model_name = embedding_model
        self.embedding_client = init_embeddings(embedding_model) if embedding_model else None
        self.tokenized_documents = [tokenize(sparse_index_text(chunk)) for chunk in chunks]

    @classmethod
    def load(
        cls,
        index_path: Path,
        embedding_model: str | None = None,
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
        return cls(chunks, runtime_model)

    def save(self, index_path: Path) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
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
            [f"{chunk.title}\n{chunk.content}" for chunk in self.chunks]
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
    ) -> list[SearchResult]:
        groups = groups or set()
        authorized_indices = [
            index
            for index, chunk in enumerate(self.chunks)
            if (not chunk.allowed_groups or bool(set(chunk.allowed_groups).intersection(groups)))
            and is_chunk_generation_eligible(
                chunk,
                environment=environment,
            )
        ]
        sparse_scores = self._bm25_scores(query, authorized_indices)
        max_sparse = max(sparse_scores, default=0.0)
        normalized_sparse = [score / max_sparse if max_sparse else 0.0 for score in sparse_scores]

        query_vector: list[float] | None = None
        if self.embedding_client and any(chunk.vector for chunk in self.chunks):
            query_vector = self.embedding_client.embed_query(query)

        results: list[SearchResult] = []
        for index in authorized_indices:
            chunk = self.chunks[index]
            dense_score: float | None = None
            score = normalized_sparse[index]
            if query_vector is not None and chunk.vector:
                dense_score = max(0.0, cosine_similarity(query_vector, chunk.vector))
                score = 0.45 * normalized_sparse[index] + 0.55 * dense_score

            results.append(
                SearchResult(
                    chunk=chunk,
                    score=round(score, 6),
                    sparse_score=round(normalized_sparse[index], 6),
                    dense_score=round(dense_score, 6) if dense_score is not None else None,
                )
            )

        results.sort(key=lambda item: item.score, reverse=True)
        return [result for result in results[:limit] if result.score > 0]
