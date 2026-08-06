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
import os
import sys
import time
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
        import google.genai as genai
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
        operation = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=args.store,
            file=str(path),
            config=types.UploadToFileSearchStoreConfig(display_name=path.name),
        )
        while not operation.done:
            time.sleep(2)
            operation = client.operations.get(operation)
        if operation.error:
            print(f"  FAILED: {operation.error}", file=sys.stderr)
        else:
            print(f"  done: {operation.response}")


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
    client = _client(_require_api_key())
    client.file_search_stores.documents.delete(name=args.document)
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
