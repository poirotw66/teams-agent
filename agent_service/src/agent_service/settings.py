from dataclasses import dataclass
from os import environ
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> frozenset[str]:
    return frozenset(
        value.strip() for value in environ.get(name, "").split(",") if value.strip()
    )


@dataclass(frozen=True)
class RagSettings:
    data_dir: Path
    index_path: Path
    auto_build_index: bool = True
    model: str | None = None
    embedding_model: str | None = None
    top_k: int = 4
    min_score: float = 0.08
    max_rewrites: int = 1
    chunk_size: int = 900
    chunk_overlap: int = 120
    allowed_tenants: frozenset[str] = frozenset()
    source_base_url: str | None = None
    service_token: str | None = None
    max_images: int = 2

    @classmethod
    def from_env(cls) -> "RagSettings":
        project_dir = Path(__file__).resolve().parents[2]
        data_dir = Path(environ.get("RAG_DATA_DIR", project_dir.parent / "data"))
        index_path = Path(
            environ.get("RAG_INDEX_PATH", data_dir / "index" / "chunks.json")
        )

        settings = cls(
            data_dir=data_dir.expanduser().resolve(),
            index_path=index_path.expanduser().resolve(),
            auto_build_index=_bool_env("RAG_AUTO_BUILD_INDEX", True),
            model=environ.get("RAG_MODEL", "").strip() or None,
            embedding_model=environ.get("RAG_EMBEDDING_MODEL", "").strip() or None,
            top_k=int(environ.get("RAG_TOP_K", "4")),
            min_score=float(environ.get("RAG_MIN_SCORE", "0.08")),
            max_rewrites=int(environ.get("RAG_MAX_REWRITES", "1")),
            chunk_size=int(environ.get("RAG_CHUNK_SIZE", "900")),
            chunk_overlap=int(environ.get("RAG_CHUNK_OVERLAP", "120")),
            allowed_tenants=_csv_env("RAG_ALLOWED_TENANTS"),
            source_base_url=environ.get("RAG_SOURCE_BASE_URL", "").strip() or None,
            service_token=environ.get("AGENT_SERVICE_TOKEN", "").strip() or None,
            max_images=int(environ.get("RAG_MAX_IMAGES", "2")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.top_k < 1 or self.top_k > 20:
            raise ValueError("RAG_TOP_K must be between 1 and 20.")
        if not 0 <= self.min_score <= 1:
            raise ValueError("RAG_MIN_SCORE must be between 0 and 1.")
        if self.max_rewrites < 0 or self.max_rewrites > 3:
            raise ValueError("RAG_MAX_REWRITES must be between 0 and 3.")
        if self.chunk_size < 200:
            raise ValueError("RAG_CHUNK_SIZE must be at least 200.")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_SIZE.")
        if self.max_images < 0 or self.max_images > 4:
            raise ValueError("RAG_MAX_IMAGES must be between 0 and 4.")
