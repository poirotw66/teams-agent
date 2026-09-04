import logging

from .documents import load_source_chunks
from .file_search_slugs import (
    FileSearchSlugCollisionError,
    ensure_unique_file_search_slugs,
)
from .retrieval import HybridIndex
from .settings import RagSettings

logger = logging.getLogger(__name__)


def build_index(settings: RagSettings) -> HybridIndex:
    chunks = load_source_chunks(
        settings.data_dir,
        settings.chunk_size,
        settings.chunk_overlap,
    )
    if not chunks:
        raise ValueError("No Markdown source documents were found.")

    source_paths = sorted({chunk.source_path for chunk in chunks})
    try:
        ensure_unique_file_search_slugs(source_paths, strict=True)
    except FileSearchSlugCollisionError as exc:
        # Fail closed at index time so collisions are not discovered only
        # when GEMINI_FILE_SEARCH starts up.
        logger.error("%s", exc)
        raise

    index = HybridIndex(chunks, settings.embedding_model)
    index.add_embeddings()
    index.save(settings.index_path)
    logger.info(
        "RAG index built: documents=%s chunks=%s path=%s embeddings=%s",
        len(source_paths),
        len(chunks),
        settings.index_path,
        settings.embedding_model or "disabled",
    )
    return index


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    try:
        build_index(RagSettings.from_env())
    except FileSearchSlugCollisionError as exc:
        # Surface the full multi-line report without a traceback wall.
        print(exc, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
