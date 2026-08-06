# Gemini File Search — Technical Spike (spec §8.3)

**Status: spike only. `HybridKnowledgeService` (spec §8.2) remains the
default (`KNOWLEDGE_SERVICE_MODE=HYBRID`) until an A/B test (§18.7) proves
Gemini File Search has a clear quality, cost, or operational advantage.
`GeminiFileSearchKnowledgeService` must not be made the default as part of
landing this spike.**

## Why this exists

Spec §3.2 requires the Knowledge Service to be isolated behind an
interface so the LangGraph workflow never depends on a specific retrieval
product. `GeminiFileSearchKnowledgeService`
(`agent_service/src/agent_service/gemini_file_search.py`) is a second
implementation of that same interface, built only far enough to run the
§8.3 checklist and gather comparison data — it is not a production-ready
adapter and does not implement ACL/tenant filtering.

## Prerequisites

- A Gemini API key with File Search enabled:
  `export GEMINI_API_KEY=...`
- The spike-only SDK dependency (not installed by default):
  ```bash
  cd agent_service
  uv sync --extra spike
  # or: .venv/bin/pip install 'teams-agent-rag-service[spike]'
  ```
- A handful of representative documents from `data/sources/` (already
  Traditional Chinese IT support docs — good spike material as-is).

## Running the spike

The runner is `scripts/gemini_file_search_spike.py`. It is a manual CLI,
never executed by `pytest`, and requires `GEMINI_API_KEY` to be set or it
exits immediately. Destructive operations (document/store deletion) are
gated behind an explicit `--delete` flag so an accidental invocation cannot
wipe a store.

```bash
export GEMINI_API_KEY=...

# 1. 建立 Store
python scripts/gemini_file_search_spike.py create-store --name it-spike

# 2. 上傳少量測試文件
python scripts/gemini_file_search_spike.py upload --store <store-name> \
    "data/sources/VPN常見Q&A問答.md" \
    "data/sources/XQ問題.md" \
    "data/sources/國泰期貨艾揚登入出現-200.md"

# 3. 執行中文查詢 + 4. 取得來源 (printed together)
python scripts/gemini_file_search_spike.py query --store <store-name> \
    "VPN 連線出現 Error 619 怎麼辦？"

# 5. 測試 metadata filter
python scripts/gemini_file_search_spike.py query --store <store-name> \
    --metadata-filter 'category="vpn"' "VPN 常見問題有哪些？"

# 6. 測試文件刪除 (destructive, requires --delete)
python scripts/gemini_file_search_spike.py list-documents --store <store-name>
python scripts/gemini_file_search_spike.py delete-document --delete \
    --store <store-name> --document <document-name>

# 7. 錯誤碼 / 專有名詞命中能力: run `query` with probes such as an exact
#    error code ("200 錯誤", "Error 619") and a proper noun that only
#    appears in one source doc, then compare against the same probes run
#    through the existing Hybrid RAG (see agent_service tests / rag-index).

# cleanup
python scripts/gemini_file_search_spike.py delete-store --delete --store <store-name>
```

## What to record for each checklist item

For every run, capture at minimum:

| Checklist item (§8.3) | What to record |
| --- | --- |
| 建立 Store | store name, creation latency, any quota/setup friction |
| 上傳少量測試文件 | per-file upload latency, chunking behavior, failures |
| 執行中文查詢 | query text, returned answer, whether it was grounded |
| 取得來源 | number of grounding chunks, whether `title`/`uri`/`document_name` were populated and usable as a `Citation` |
| 測試 metadata filter | filter expression used, whether results changed as expected |
| 測試文件刪除 | latency, whether subsequent queries stopped citing the deleted doc |
| 錯誤碼與專有名詞命中比較 | side-by-side hit/miss vs. Hybrid RAG for the same probe queries |

## A/B comparison criteria (spec §18.7)

Run the **same** query set against both `HybridKnowledgeService` and
`GeminiFileSearchKnowledgeService` and score each on:

- Answer Accuracy
- Recall@K
- Groundedness
- Citation Accuracy
- No-answer Accuracy (does it correctly say "not found" instead of fabricating?)
- Error-code Accuracy
- ACL Accuracy (Hybrid only today — File Search spike has no ACL enforcement, so this is an automatic fail/N-A for it until implemented)
- Image Match Accuracy (File Search spike does not map images at all — automatic 0 until implemented)
- P95 Latency
- 單次成本 (per-query cost)
- 維運複雜度 (operational complexity: store lifecycle, document sync, monitoring)

**Do not promote `GEMINI_FILE_SEARCH` to the default `KNOWLEDGE_SERVICE_MODE`
until this table is filled in with real measurements and reviewed.**

## Results (TBD)

No spike has been run yet as part of this change. Fill in after executing
the checklist above — do not fabricate numbers.

| Criterion | HybridKnowledgeService | GeminiFileSearchKnowledgeService | Notes |
| --- | --- | --- | --- |
| Answer Accuracy | TBD | TBD | |
| Recall@K | TBD | TBD | |
| Groundedness | TBD | TBD | |
| Citation Accuracy | TBD | TBD | |
| No-answer Accuracy | TBD | TBD | |
| Error-code Accuracy | TBD | TBD | |
| ACL Accuracy | TBD | N/A (not implemented in spike) | |
| Image Match Accuracy | TBD | N/A (not implemented in spike) | |
| P95 Latency | TBD | TBD | |
| 單次成本 | TBD | TBD | |
| 維運複雜度 | TBD | TBD | |

## Known spike limitations (by design, per §8.3 scope)

- No ACL / tenant allowlist enforcement.
- No image/`AgentImage` mapping from grounding metadata.
- No document governance metadata (owner/version/effectiveDate) round-trip.
- No automatic re-sync of `data/sources/` into a File Search store.

These are all out of scope for "just a spike" per §8.3 and should not block
landing this file; they are exactly what would need to be built if the A/B
test above justified promoting this adapter.
