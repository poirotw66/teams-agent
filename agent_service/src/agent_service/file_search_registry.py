"""Document registry for the Gemini File Search adapter (spec §8.3, Task 15).

A 2026-08-06 spike (docs/gemini-file-search-spike.md, findings 1, 3, 9)
established that:

  * ``upload_to_file_search_store`` must stage every non-ASCII source file
    under an ASCII slug (see ``_ascii_display_name`` below), because the
    resumable-upload path puts the file *path* into an HTTP header and
    non-ASCII header values raise ``UnicodeEncodeError``.
  * Grounding chunks returned by File Search carry that ASCII slug as
    ``title``, with ``uri`` and ``document_name`` both ``None`` — so a
    citation would otherwise show e.g. ``VPNQ&A.md`` instead of the real
    document title ``VPN常見Q&A問答``.
  * Images are never seen by File Search at all; they only exist in our own
    local index (``data/index/chunks.json``), keyed by source document.

This module lets the adapter go from "the slug File Search gave us back" to
"the real title and images our local index already knows about."
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .contracts import AgentImage
from .documents import DocumentChunk, DocumentImage

# The existing helpdesk-store was uploaded before the current ASCII slug
# algorithm and uses hand-written English display names. Keep this explicit
# compatibility table so grounding citations can still join to the canonical
# local source metadata and images. New uploads should use ``slug_for`` and do
# not need an entry here.
_LEGACY_FILE_SEARCH_ALIASES: dict[str, str] = {
    "branch-cs-vpn-permissions.md": "分公司CS團隊VPN連線可使用權限列表.md",
    "cathay-futures-ai-login-error-200.md": "國泰期貨艾揚登入出現-200.md",
    "chaoshu-app-crash.md": "超音樹-程式閃退問題.md",
    "email-garbled-text.md": "郵件為亂碼.md",
    "employee-portal-cteam-and-e-attendance.md": "國泰員工入口網、CTeam密碼、國泰e點名.md",
    "financial-portal-password-change.md": "金控入口網密碼變更方式.md",
    "gitlab-account-unlock.md": "Gitlab帳號解鎖跟重置.md",
    "head-office-ip-phone-guide.md": "總公司IP話機操作.md",
    "it-issue-reporting-guidelines.md": "資訊問題的通報格式.md",
    "seat-relocation-request.md": "座位搬遷需求.md",
    "shared-drive-folder-request.md": "同仁申請共用公槽資料夾.md",
    "shuling-ap-login-issue.md": "樹精靈AP無法登入.md",
    "vpn-faq.md": "VPN常見Q&A問答.md",
    "vpn-temporary-overseas-access.md": "VPN國外連線短暫申請.md",
    "webex-meeting-recording-request.md": "Webex會議借用-可錄影.md",
    "xiaozhou-feature-not-clickable.md": "大州系統_功能無法點選.md",
    "xiaozhou-first-time-setup.md": "大州首次使用設定.md",
    "xq-faq.md": "XQ問題.md",
}


def _ascii_display_name(path: Path) -> str:
    """Derive an ASCII slug from a filename.

    DUPLICATED from ``scripts/gemini_file_search_spike.py::_ascii_display_name``.
    That script is a standalone spike runner, not an importable package
    module, so this function is copied verbatim rather than imported. It
    MUST stay byte-for-byte in sync with the spike script's algorithm —
    ``tests/test_file_search_registry.py`` asserts the two implementations
    agree for every file currently in ``data/sources/``, but a future edit
    to either copy without updating the other will silently break every
    File Search citation/image lookup.
    """
    stem = path.stem.encode("ascii", "ignore").decode("ascii").strip(" -_")
    if not stem:
        # Entirely non-ASCII filename: fall back to a stable content hash so
        # two different documents never collide.
        digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:12]
        stem = f"doc-{digest}"
    return f"{stem}{path.suffix.lower()}"


@dataclass(frozen=True)
class _DocumentRecord:
    source_path: str
    title: str
    images: tuple[AgentImage, ...]


class FileSearchDocumentRegistry:
    """Maps a File Search upload slug back to local document knowledge.

    Build with :meth:`from_chunks` (or :meth:`from_index_path` to load a
    ``chunks.json`` index directly), then look up whatever slug a grounding
    chunk reported via :meth:`title_for`, :meth:`images_for`, and
    :meth:`source_path_for`. Unknown slugs degrade to ``None``/``[]``
    rather than raising, since a File Search store may reference documents
    the local index no longer has.
    """

    def __init__(self) -> None:
        self._by_slug: dict[str, _DocumentRecord] = {}

    @classmethod
    def from_chunks(cls, chunks: list[DocumentChunk]) -> FileSearchDocumentRegistry:
        registry = cls()

        source_order: list[str] = []
        chunks_by_source: dict[str, list[DocumentChunk]] = {}
        for chunk in chunks:
            if chunk.source_path not in chunks_by_source:
                source_order.append(chunk.source_path)
                chunks_by_source[chunk.source_path] = []
            chunks_by_source[chunk.source_path].append(chunk)

        slug_to_source: dict[str, str] = {}
        records_by_filename: dict[str, _DocumentRecord] = {}
        records_by_title: dict[str, _DocumentRecord] = {}
        for source_path in source_order:
            slug = cls.slug_for(source_path)
            if slug in slug_to_source:
                raise ValueError(
                    "File Search slug collision: "
                    f"{slug_to_source[slug]!r} and {source_path!r} both map to "
                    f"slug {slug!r}. Rename one of the source files so their "
                    "ASCII slugs no longer collide."
                )
            slug_to_source[slug] = source_path

            doc_chunks = chunks_by_source[source_path]
            title = next(
                (chunk.title for chunk in doc_chunks if chunk.title),
                Path(source_path).stem,
            )
            record = _DocumentRecord(
                source_path=source_path,
                title=title,
                images=tuple(_collect_images(doc_chunks)),
            )
            registry._by_slug[slug] = record
            records_by_filename[Path(source_path).name] = record
            records_by_title[title] = record

        for alias, filename in _LEGACY_FILE_SEARCH_ALIASES.items():
            record = records_by_filename.get(filename)
            if record is None:
                # Portal releases hash source filenames (doc-*.md) while the
                # helpdesk File Search store still uses legacy ASCII slugs.
                record = records_by_title.get(Path(filename).stem)
            if record is not None:
                registry._by_slug[alias] = record
        return registry

    @classmethod
    def from_index_path(cls, path: Path) -> FileSearchDocumentRegistry:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        chunks = [DocumentChunk.from_dict(item) for item in value["chunks"]]
        return cls.from_chunks(chunks)

    @staticmethod
    def slug_for(source_path: str) -> str:
        """The canonical ASCII slug an uploaded document is staged under."""
        return _ascii_display_name(Path(source_path))

    def title_for(self, slug: str) -> str | None:
        record = self._by_slug.get(slug)
        return record.title if record is not None else None

    def images_for(self, slug: str) -> list[AgentImage]:
        record = self._by_slug.get(slug)
        if record is None:
            return []
        return list(record.images)

    def source_path_for(self, slug: str) -> str | None:
        record = self._by_slug.get(slug)
        return record.source_path if record is not None else None


def _collect_images(doc_chunks: list[DocumentChunk]) -> list[AgentImage]:
    """De-duplicated, order-stable union of images across a document's chunks.

    Grounding is document-level (File Search only ever tells us the slug,
    not which chunk matched), so every image belonging to the document is
    returned regardless of which chunk the citation actually came from.
    ``sourceChunkId`` is set to the first chunk that actually carries that
    image, so the field stays truthful.
    """
    images: list[AgentImage] = []
    seen: set[str] = set()
    for chunk in doc_chunks:
        for image in chunk.images or []:
            if image.path in seen:
                continue
            seen.add(image.path)
            images.append(_to_agent_image(image, chunk.chunk_id))
    return images


def _to_agent_image(image: DocumentImage, chunk_id: str) -> AgentImage:
    return AgentImage(
        path=image.path,
        title=image.title,
        altText=image.alt_text,
        sourceChunkId=chunk_id,
    )
