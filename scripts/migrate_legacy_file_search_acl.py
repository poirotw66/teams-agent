#!/usr/bin/env python3
"""Re-upload legacy File Search store documents with ACL metadata.

The helpdesk legacy store uses hand-written English ``display_name`` slugs
(see ``file_search_registry._LEGACY_FILE_SEARCH_ALIASES``). This script
deletes documents that lack ``grp_public``, then re-uploads the corpus
with ACL metadata while preserving those legacy slugs so citations/images
keep working.

Usage:
    export GEMINI_API_KEY=...
    cd agent_service
    uv run python ../scripts/migrate_legacy_file_search_acl.py \\
        --store fileSearchStores/helpdeskstore-1p3gu83qot1s
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = REPO_ROOT / "data" / "index" / "chunks.json"
DEFAULT_DATA = REPO_ROOT / "data"
PUBLIC_GROUP_KEY = "grp_public"


def _require_api_key() -> str:
    api_key = (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("error: GOOGLE_API_KEY or GEMINI_API_KEY must be set.", file=sys.stderr)
        raise SystemExit(2)
    return api_key


def _client(api_key: str):
    from google import genai

    return genai.Client(api_key=api_key)


def _mime_type_for(path: Path) -> str:
    return {".md": "text/plain", ".txt": "text/plain", ".pdf": "application/pdf"}.get(
        path.suffix.lower(), "text/plain"
    )


def _metadata_has_public(document) -> bool:
    metadata = getattr(document, "custom_metadata", None) or []
    for entry in metadata:
        if getattr(entry, "key", None) == PUBLIC_GROUP_KEY and getattr(entry, "string_value", None) == "1":
            return True
    return False


def _list_documents(client, store: str) -> list:
    return list(client.file_search_stores.documents.list(parent=store))


def _source_files(index_path: Path, data_dir: Path) -> list[Path]:
    value = json.loads(index_path.read_text(encoding="utf-8"))
    chunks = value.get("chunks", [])
    source_paths = sorted({chunk["source_path"] for chunk in chunks if chunk.get("source_path")})
    files: list[Path] = []
    for source_path in source_paths:
        candidate = data_dir / source_path
        if candidate.is_file():
            files.append(candidate)
            continue
        fallback = data_dir / "sources" / Path(source_path).name
        if fallback.is_file():
            files.append(fallback)
            continue
        raise FileNotFoundError(f"source file not found for index entry: {source_path}")
    return files


def _legacy_slug_for_filename(filename: str) -> str | None:
    from agent_service.file_search_registry import _LEGACY_FILE_SEARCH_ALIASES

    for slug, legacy_filename in _LEGACY_FILE_SEARCH_ALIASES.items():
        if legacy_filename == filename:
            return slug
    return None


def _upload_slug_for(path: Path) -> str:
    legacy_slug = _legacy_slug_for_filename(path.name)
    if legacy_slug is not None:
        return legacy_slug
    from agent_service.file_search_registry import FileSearchDocumentRegistry

    return FileSearchDocumentRegistry.slug_for(path.name)


def _load_acl_by_slug(index_path: Path, upload_plan: dict[str, Path]) -> dict[str, list[str]]:
    value = json.loads(index_path.read_text(encoding="utf-8"))
    acl_by_filename: dict[str, list[str]] = {}
    for chunk in value.get("chunks", []):
        source_path = chunk.get("source_path")
        if not source_path:
            continue
        filename = Path(source_path).name
        acl_by_filename.setdefault(filename, list(chunk.get("allowed_groups") or []))

    acl_by_upload_slug: dict[str, list[str]] = {}
    for slug, path in upload_plan.items():
        acl_by_upload_slug[slug] = acl_by_filename.get(path.name, [])
    return acl_by_upload_slug


def _delete_document(client, document_name: str) -> None:
    from google.genai import types

    client.file_search_stores.documents.delete(
        name=document_name,
        config=types.DeleteDocumentConfig(force=True),
    )


def _upload_file(client, store: str, path: Path, display_name: str, allowed_groups: list[str]) -> None:
    from google.genai import types

    from agent_service.file_search_acl import upload_metadata_for

    metadata = [
        types.CustomMetadata(key="source_file", string_value=path.name),
        *upload_metadata_for(allowed_groups),
    ]
    config = types.UploadToFileSearchStoreConfig(
        display_name=display_name,
        mime_type=_mime_type_for(path),
        custom_metadata=metadata,
    )

    with tempfile.TemporaryDirectory(prefix="file-search-migrate-") as staging:
        staged = Path(staging) / display_name
        shutil.copyfile(path, staged)
        operation = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store,
            file=str(staged),
            config=config,
        )
        while not operation.done:
            time.sleep(2)
            operation = client.operations.get(operation)
    if operation.error:
        raise RuntimeError(f"upload failed for {path.name}: {operation.error}")


def migrate(store: str, *, index_path: Path, dry_run: bool) -> int:
    source_files = _source_files(index_path, DEFAULT_DATA)
    upload_plan = {_upload_slug_for(path): path for path in source_files}
    acl_by_slug = _load_acl_by_slug(index_path, upload_plan)

    print(f"store={store}")
    print(f"index={index_path} ({len(source_files)} source files)")

    if dry_run:
        for slug, path in sorted(upload_plan.items()):
            print(
                f"  would ensure: slug={slug!r} file={path.name!r} "
                f"allowed_groups={acl_by_slug.get(slug, [])!r}"
            )
        return 0

    api_key = _require_api_key()
    client = _client(api_key)
    documents = _list_documents(client, store)
    print(f"existing documents: {len(documents)}")

    acl_ready = {doc.display_name for doc in documents if _metadata_has_public(doc)}
    legacy = [doc for doc in documents if not _metadata_has_public(doc)]

    print(f"acl-ready documents: {len(acl_ready)}")
    print(f"legacy documents to delete: {len(legacy)}")

    for doc in legacy:
        print(f"  delete: display_name={doc.display_name!r}")
        _delete_document(client, doc.name)
        print("    deleted")

    upload_targets = [(slug, path) for slug, path in sorted(upload_plan.items()) if slug not in acl_ready]
    print(f"documents to upload: {len(upload_targets)}")
    for slug, path in upload_targets:
        groups = acl_by_slug.get(slug, [])
        print(f"  upload: {path.name} -> slug={slug!r} allowed_groups={groups!r}")
        _upload_file(client, store, path, slug, groups)
        print("    done")

    final_docs = _list_documents(client, store)
    final_acl = [doc for doc in final_docs if _metadata_has_public(doc)]
    missing_slugs = sorted(set(upload_plan) - {doc.display_name for doc in final_acl})
    duplicate_slugs = [
        slug for slug in upload_plan if sum(1 for doc in final_docs if doc.display_name == slug) > 1
    ]

    print(f"final documents: {len(final_docs)} ({len(final_acl)} with {PUBLIC_GROUP_KEY})")
    if missing_slugs:
        print("ERROR: missing ACL-ready slugs:", missing_slugs, file=sys.stderr)
        return 1
    if duplicate_slugs:
        print("ERROR: duplicate display_name entries:", duplicate_slugs, file=sys.stderr)
        return 1
    print("migration complete")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    os.chdir(REPO_ROOT / "agent_service")
    raise SystemExit(migrate(args.store, index_path=args.index_path, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
