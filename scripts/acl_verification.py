#!/usr/bin/env python3
"""Dedicated ACL verification probe for GeminiFileSearchKnowledgeService (Task 18).

Why this exists (do not fold this into the 30-case A/B's ACL column):
``data/eval/retrieval_eval_set.json``'s two ACL cases (``cs-vpn-acl-open``,
``cs-vpn-acl-other-group``) both expect ``expectedFound=True``, because every
document currently shipped under ``data/sources/`` is ``audience:
all-employees`` (see ``docs/knowledge-document-governance.md``). A backend
that enforces no permissions at all still scores 100% on that column. This
script is the honest alternative: it uploads one document that is genuinely
restricted (``allowed_groups=['cs-team']``) and one that is genuinely public,
directly to a throwaway store, then queries through
``GeminiFileSearchKnowledgeService.search`` -- the real adapter, not a
hand-built filter -- as a caller who has the group and as a caller who does
not, and reports whether visibility matches what §17 requires.

Per the task scope, this does NOT touch ``data/sources/**`` or rebuild the
shared index. The restricted/public documents are synthetic, built and
uploaded by this script alone, into a store this script also deletes when
done.

Usage:
    export GEMINI_API_KEY=...
    cd agent_service
    .venv/bin/python ../scripts/acl_verification.py

Requires the google-genai SDK (agent_service `spike` extra) and network
access. Always deletes the store it creates, including on failure.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path


def _require_api_key() -> str:
    api_key = (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print(
            "error: neither GOOGLE_API_KEY nor GEMINI_API_KEY is set. This probe "
            "makes real API calls and must not run without an explicit key.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return api_key


def _upload_probe_documents(client, types, store_name: str, upload_metadata_for) -> None:
    """Synchronous setup: create the two synthetic documents and upload them.

    Kept out of the async ``main`` on purpose -- the google-genai client's
    upload/poll path is blocking, and polling it with ``time.sleep`` inside
    an ``async def`` trips ruff's ASYNC251 (ruff is right: it would block the
    event loop). There is nothing else running concurrently in this
    single-purpose probe, so a plain synchronous helper is simpler than
    threading it through ``asyncio.to_thread`` for no benefit.
    """
    restricted_text = (
        "CS 團隊內部薪資核算流程：本文件僅供 cs-team 群組使用，"
        "內容涉及 CS 團隊薪資核算表填寫方式與提交窗口。"
    )
    public_text = "公司午餐補助申請方式：全體員工皆可於員工入口網申請午餐補助。"

    with tempfile.TemporaryDirectory(prefix="acl-probe-") as staging:
        restricted_path = Path(staging) / "restricted-doc.txt"
        restricted_path.write_text(restricted_text, encoding="utf-8")
        public_path = Path(staging) / "public-doc.txt"
        public_path.write_text(public_text, encoding="utf-8")

        print("Uploading restricted document (allowed_groups=['cs-team'])...")
        restricted_metadata = upload_metadata_for(["cs-team"])
        restricted_config = types.UploadToFileSearchStoreConfig(
            display_name="restricted-doc.txt",
            mime_type="text/plain",
        )
        restricted_config.custom_metadata = restricted_metadata
        op = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store_name,
            file=str(restricted_path),
            config=restricted_config,
        )
        while not op.done:
            time.sleep(2)
            op = client.operations.get(op)
        if op.error:
            raise RuntimeError(f"restricted-doc upload FAILED: {op.error}")
        print("  done.")

        print("Uploading public document (allowed_groups=[])...")
        public_metadata = upload_metadata_for([])
        public_config = types.UploadToFileSearchStoreConfig(
            display_name="public-doc.txt",
            mime_type="text/plain",
        )
        public_config.custom_metadata = public_metadata
        op = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store_name,
            file=str(public_path),
            config=public_config,
        )
        while not op.done:
            time.sleep(2)
            op = client.operations.get(op)
        if op.error:
            raise RuntimeError(f"public-doc upload FAILED: {op.error}")
        print("  done.")


async def main() -> int:
    try:
        from agent_service.contracts import UserContext
        from agent_service.file_search_acl import upload_metadata_for
        from agent_service.gemini_file_search import GeminiFileSearchKnowledgeService
    except ImportError as exc:
        print(
            "error: could not import agent_service. Run this script with "
            "agent_service/.venv/bin/python, not the repo-root venv.\n"
            f"  ({exc})",
            file=sys.stderr,
        )
        return 2

    from google import genai
    from google.genai import types

    api_key = _require_api_key()
    client = genai.Client(api_key=api_key)

    store_display_name = f"acl-probe-{int(time.time())}"
    print(f"Creating throwaway store: {store_display_name}")
    store = client.file_search_stores.create(
        config=types.CreateFileSearchStoreConfig(display_name=store_display_name)
    )
    store_name = store.name
    print(f"  store: {store_name}")

    try:
        try:
            _upload_probe_documents(client, types, store_name, upload_metadata_for)
        except RuntimeError as exc:
            print(f"  {exc}", file=sys.stderr)
            return 1

        # Query through the real adapter, not a hand-built filter.
        service = GeminiFileSearchKnowledgeService(
            api_key=api_key,
            file_search_store=store_name,
            top_k=4,
        )

        restricted_query = "CS 團隊薪資核算表要交給誰？"
        public_query = "午餐補助怎麼申請？"
        RESTRICTED_TITLE = "restricted-doc.txt"
        PUBLIC_TITLE = "public-doc.txt"

        # The real, security-relevant signal is which document TITLE comes
        # back, not the bare ``found`` boolean. With only two tiny documents
        # in the store and top_k=4, an unrelated but *visible* document can
        # still surface as a grounding chunk once metadata_filter excludes
        # the relevant-but-restricted one (observed on the first run of this
        # probe: groups=[] against the restricted query returned found=True
        # with sources=['public-doc.txt'] -- not a leak, just File Search
        # falling back to the only document the filter let through). Content
        # leakage means the restricted title appears where it should not,
        # so that is what each check below asserts on directly.

        print("\n--- Probe 1: groups=['cs-team'], restricted query ---")
        r1 = await service.search(restricted_query, UserContext(groups=["cs-team"]))
        titles1 = [s.title for s in r1.sources]
        print(f"  found={r1.found} sources={titles1}")

        print("\n--- Probe 2: groups=[], restricted query ---")
        r2 = await service.search(restricted_query, UserContext(groups=[]))
        titles2 = [s.title for s in r2.sources]
        print(f"  found={r2.found} sources={titles2}")
        print(f"  answer preview: {r2.answer[:200]!r}")

        print("\n--- Probe 3: groups=[], public query ---")
        r3 = await service.search(public_query, UserContext(groups=[]))
        titles3 = [s.title for s in r3.sources]
        print(f"  found={r3.found} sources={titles3}")

        print("\n=== Summary ===")
        checks = [
            (
                "cs-team can see the restricted doc",
                RESTRICTED_TITLE in titles1,
            ),
            (
                "no-group does NOT see the restricted doc (no content leak)",
                RESTRICTED_TITLE not in titles2,
            ),
            (
                "no-group's restricted-query answer does not leak restricted content",
                # "提交窗口" only exists in the restricted document's text, not
                # in the query itself -- unlike "薪資核算", which the query
                # repeats and would false-positive on a correct decline that
                # merely echoes the question back.
                "提交窗口" not in r2.answer,
            ),
            (
                "no-group sees the public doc",
                PUBLIC_TITLE in titles3,
            ),
        ]
        ok = True
        for label, passed in checks:
            status = "PASS" if passed else "FAIL"
            ok = ok and passed
            print(f"  [{status}] {label}")

        print(f"\nOverall: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        print(f"\nDeleting store: {store_name}")
        client.file_search_stores.delete(
            name=store_name, config=types.DeleteFileSearchStoreConfig(force=True)
        )
        print("  deleted.")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
