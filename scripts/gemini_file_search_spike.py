#!/usr/bin/env python3
"""Manual technical spike runner for Gemini File Search (spec §8.3).

This script is NOT part of the automated test suite and is never imported by
pytest. It requires a live Gemini API key and makes real network calls and
(optionally, with ``--delete``) real destructive calls against your Google
AI project. Run it by hand, on purpose.

Checklist covered (spec §8.3):
  1. 建立 Store            -> `create-store`
  2. 上傳少量測試文件        -> `upload`
  3. 執行中文查詢            -> `query`
  4. 取得來源                -> printed with every `query`
  5. 測試 metadata filter    -> `query --metadata-filter ...`
  6. 測試文件刪除            -> `delete-document` (requires --delete)
  7. 比較錯誤碼與專有名詞命中 -> `query` against error-code / proper-noun probes

Usage:
    export GEMINI_API_KEY=...
    python scripts/gemini_file_search_spike.py create-store --name it-spike
    python scripts/gemini_file_search_spike.py upload --store <store-name> \\
        data/sources/VPN常見Q&A問答.md data/sources/XQ問題.md
    python scripts/gemini_file_search_spike.py query --store <store-name> \\
        "VPN 連線出現 Error 619 怎麼辦？"
    python scripts/gemini_file_search_spike.py query --store <store-name> \\
        --metadata-filter 'category="vpn"' "VPN 常見問題"
    python scripts/gemini_file_search_spike.py list-documents --store <store-name>
    python scripts/gemini_file_search_spike.py delete-document --delete \\
        --store <store-name> --document <document-name>
    python scripts/gemini_file_search_spike.py delete-store --delete \\
        --store <store-name>

Record results (per checklist item, per query) into
docs/gemini-file-search-spike.md — do not commit fabricated numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

REQUIRED_ENV_VAR = "GEMINI_API_KEY"


def _require_api_key() -> str:
    api_key = os.environ.get(REQUIRED_ENV_VAR, "").strip()
    if not api_key:
        print(
            f"error: {REQUIRED_ENV_VAR} is not set. This spike makes real API "
            "calls and must not run without an explicit key.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return api_key


def _client(api_key: str):
    try:
        from google import genai
    except ImportError as exc:
        print(
            "error: google-genai is not installed. Install the spike extra:\n"
            "  cd agent_service && uv sync --extra spike\n"
            "or: pip install 'teams-agent-rag-service[spike]'",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    return genai.Client(api_key=api_key)


def cmd_create_store(args: argparse.Namespace) -> None:
    from google.genai import types

    client = _client(_require_api_key())
    store = client.file_search_stores.create(
        config=types.CreateFileSearchStoreConfig(display_name=args.name)
    )
    print(f"created store: {store.name!r} (display_name={args.name!r})")


def cmd_upload(args: argparse.Namespace) -> None:
    from google.genai import types

    client = _client(_require_api_key())
    for raw_path in args.files:
        path = Path(raw_path)
        if not path.is_file():
            print(f"skip (not a file): {path}", file=sys.stderr)
            continue
        print(f"uploading {path} ...")
        # The SDK guesses the mime type from the filename and raises
        # ValueError for .md on systems whose mimetypes registry has no
        # markdown entry (observed on macOS). Always pass it explicitly.
        config = types.UploadToFileSearchStoreConfig(
            display_name=_ascii_display_name(path),
            mime_type=_mime_type_for(path),
        )
        # custom_metadata drives `--metadata-filter` on query (spec §8.3
        # item 5). Unlike the file path, metadata values DO accept
        # non-ASCII, so the real Chinese filename is preserved here.
        metadata = _parse_metadata(args.metadata) if args.metadata else []
        metadata.extend(_parse_metadata([f"source_file={path.name}"]))
        config.custom_metadata = metadata

        with _ascii_path(path) as upload_path:
            operation = client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=args.store,
                file=str(upload_path),
                config=config,
            )
            while not operation.done:
                time.sleep(2)
                operation = client.operations.get(operation)
        if operation.error:
            print(f"  FAILED: {operation.error}", file=sys.stderr)
        else:
            print(f"  done: {operation.response}")


@contextmanager
def _ascii_path(path: Path):
    """Yield a path safe to hand to ``upload_to_file_search_store``.

    FINDING (spec §8.3 / §18.7 ops-complexity, verified 2026-08-06): the
    resumable-upload path puts the *file path* into an HTTP header, and
    httpx rejects non-ASCII header values with UnicodeEncodeError. Every
    document in ``data/sources/`` has a Traditional Chinese filename, so
    File Search cannot ingest this corpus directly — each file must be
    staged under an ASCII name first.

    Isolated precisely: an ASCII path succeeds even when ``display_name``
    and ``custom_metadata`` carry Chinese, so the restriction is on the
    path alone. Documented in docs/gemini-file-search-spike.md.
    """
    if str(path).isascii():
        yield path
        return
    with tempfile.TemporaryDirectory(prefix="gemini-spike-") as staging:
        staged = Path(staging) / _ascii_display_name(path)
        shutil.copyfile(path, staged)
        print(f"  (staged as ASCII filename: {staged.name})")
        yield staged


# Markdown is the only source format in data/sources/. text/plain is used
# rather than text/markdown because the File Search ingestion pipeline
# accepts it uniformly across SDK versions.
_MIME_TYPES = {
    ".md": "text/plain",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".json": "application/json",
}


def _mime_type_for(path: Path) -> str:
    return _MIME_TYPES.get(path.suffix.lower(), "text/plain")


def _ascii_display_name(path: Path) -> str:
    """Derive an ASCII slug from a filename.

    Used for the staged upload filename (see ``_ascii_path``, where ASCII
    is a verified hard requirement) and reused as ``display_name`` for
    consistency between the two.

    Note: whether ``display_name`` *itself* tolerates non-ASCII was not
    tested in the 2026-08-06 spike — only the file path was isolated as
    the failing input. Do not cite this function as evidence about
    ``display_name``.
    """
    stem = path.stem.encode("ascii", "ignore").decode("ascii").strip(" -_")
    if not stem:
        # Entirely non-ASCII filename: fall back to a stable content hash so
        # two different documents never collide.
        digest = hashlib.sha256(path.name.encode("utf-8")).hexdigest()[:12]
        stem = f"doc-{digest}"
    return f"{stem}{path.suffix.lower()}"


def _parse_metadata(pairs: list[str]) -> list:
    """Parse ``key=value`` pairs into CustomMetadata entries."""
    from google.genai import types

    metadata = []
    for pair in pairs:
        key, _, value = pair.partition("=")
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise SystemExit(f"invalid --metadata entry (expected key=value): {pair!r}")
        metadata.append(types.CustomMetadata(key=key, string_value=value))
    return metadata


def cmd_list_documents(args: argparse.Namespace) -> None:
    client = _client(_require_api_key())
    for document in client.file_search_stores.documents.list(parent=args.store):
        print(document)


def cmd_query(args: argparse.Namespace) -> None:
    from google.genai import types

    client = _client(_require_api_key())
    file_search = types.FileSearch(
        file_search_store_names=[args.store],
        top_k=args.top_k,
        metadata_filter=args.metadata_filter,
    )
    response = client.models.generate_content(
        model=args.model,
        contents=args.question,
        config=types.GenerateContentConfig(tools=[types.Tool(file_search=file_search)]),
    )
    print("=== answer ===")
    print(response.text)
    print("=== sources ===")
    candidates = response.candidates or []
    grounding_metadata = candidates[0].grounding_metadata if candidates else None
    chunks = (grounding_metadata.grounding_chunks or []) if grounding_metadata else []
    if not chunks:
        print("(no grounding chunks returned - would be treated as found=False)")
    for chunk in chunks:
        context = chunk.retrieved_context
        if not context:
            continue
        print(
            f"  title={context.title!r} uri={context.uri!r} "
            f"document={context.document_name!r}"
        )


def cmd_delete_document(args: argparse.Namespace) -> None:
    if not args.delete:
        print("refusing to delete: pass --delete to confirm.", file=sys.stderr)
        raise SystemExit(2)
    from google.genai import types

    client = _client(_require_api_key())
    # force=True is required: without it the API rejects the call with
    # 400 FAILED_PRECONDITION "Cannot delete non-empty Document", because
    # an ingested document always owns its derived chunks.
    client.file_search_stores.documents.delete(
        name=args.document,
        config=types.DeleteDocumentConfig(force=True),
    )
    print(f"deleted document: {args.document}")


def cmd_delete_store(args: argparse.Namespace) -> None:
    from google.genai import types

    if not args.delete:
        print("refusing to delete: pass --delete to confirm.", file=sys.stderr)
        raise SystemExit(2)
    client = _client(_require_api_key())
    client.file_search_stores.delete(
        name=args.store, config=types.DeleteFileSearchStoreConfig(force=True)
    )
    print(f"deleted store: {args.store}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_store = subparsers.add_parser("create-store", help="Create a File Search store.")
    create_store.add_argument("--name", required=True, help="Store display name.")
    create_store.set_defaults(func=cmd_create_store)

    upload = subparsers.add_parser("upload", help="Upload documents to a store.")
    upload.add_argument("--store", required=True, help="Store resource name (fileSearchStores/...).")
    upload.add_argument("files", nargs="+", help="Paths under data/sources/ to upload.")
    upload.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Custom metadata applied to every uploaded file, e.g. --metadata category=vpn. "
        "Repeatable. Needed to exercise --metadata-filter on query (spec §8.3 item 5).",
    )
    upload.set_defaults(func=cmd_upload)

    list_documents = subparsers.add_parser("list-documents", help="List documents in a store.")
    list_documents.add_argument("--store", required=True)
    list_documents.set_defaults(func=cmd_list_documents)

    query = subparsers.add_parser("query", help="Run a Traditional Chinese grounded query.")
    query.add_argument("--store", required=True)
    query.add_argument("--model", default="gemini-2.5-flash")
    query.add_argument("--top-k", type=int, default=4)
    query.add_argument("--metadata-filter", default=None, help="e.g. 'category=\"vpn\"'")
    query.add_argument("question")
    query.set_defaults(func=cmd_query)

    delete_document = subparsers.add_parser("delete-document", help="Delete one document (destructive).")
    delete_document.add_argument("--store", required=True)
    delete_document.add_argument("--document", required=True, help="Document resource name.")
    delete_document.add_argument("--delete", action="store_true", help="Confirm the deletion.")
    delete_document.set_defaults(func=cmd_delete_document)

    delete_store = subparsers.add_parser("delete-store", help="Delete an entire store (destructive).")
    delete_store.add_argument("--store", required=True)
    delete_store.add_argument("--delete", action="store_true", help="Confirm the deletion.")
    delete_store.set_defaults(func=cmd_delete_store)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
