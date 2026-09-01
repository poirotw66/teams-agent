import logging

from .documents import load_source_chunks
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

    index = HybridIndex(chunks, settings.embedding_model)
    index.add_embeddings()
    index.save(settings.index_path)
    logger.info(
        "RAG index built: documents=%s chunks=%s path=%s embeddings=%s",
        len({chunk.source_path for chunk in chunks}),
        len(chunks),
        settings.index_path,
        settings.embedding_model or "disabled",
    )
    return index


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    build_index(RagSettings.from_env())


if __name__ == "__main__":
    main()

