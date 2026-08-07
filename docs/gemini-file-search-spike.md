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

## Results — spike executed 2026-08-06

Executed against a real store with 4 corpus documents
(`VPN常見Q&A問答`, `國泰期貨艾揚登入出現-200`, `樹精靈AP無法登入`,
`金控入口網密碼變更方式`), model `gemini-3.5-flash-lite`. The store was
deleted afterwards. Numbers below are observed, not estimated.

### Checklist outcome

| # | Item | Result |
| --- | --- | --- |
| 1 | 建立 Store | OK |
| 2 | 上傳少量測試文件 | OK **only after fixing three script defects** (see below) |
| 3 | 執行中文查詢 | OK — fluent Traditional Chinese answers |
| 4 | 取得來源 | Partial — titles returned, but `uri` and `document_name` are both `None` |
| 5 | 測試 metadata filter | OK — `category="vpn"` returned only the VPN doc; `category="app"` only the three app docs |
| 6 | 測試文件刪除 | OK — requires `DeleteDocumentConfig(force=True)`; document count 4 → 3 and the deleted content stopped being cited |
| 7 | 錯誤碼 / 專有名詞命中 | Mixed — see findings 4 and 5 |

### Findings

**1. The corpus cannot be uploaded as-is: file paths must be ASCII.**
`upload_to_file_search_store` puts the file path into an HTTP header, and
httpx raises `UnicodeEncodeError` for non-ASCII values. All 19 documents in
`data/sources/` have Traditional Chinese filenames, so every one of them
fails. Isolated precisely by bisection: an ASCII path succeeds while
`custom_metadata` carries Chinese, so **only the path** is restricted.
`scripts/gemini_file_search_spike.py` now stages each file under an ASCII
name before upload and records the real filename in `custom_metadata`.

A production migration would need this staging step plus a stable
slug→original-title mapping. Note the derived slugs are near-useless on
their own: 「國泰期貨艾揚登入出現-200.md」 → `200.md`,
「樹精靈AP無法登入.md」 → `AP.md`, 「金控入口網密碼變更方式.md」 →
`doc-41c1698e7c60.md` (no ASCII characters survive at all).

**2. Two further SDK requirements the script had wrong.** `.md` has no
mimetype entry on macOS, so `mime_type` must be passed explicitly; and
document deletion needs `force=True` or the API returns
`400 FAILED_PRECONDITION: Cannot delete non-empty Document`. Both are fixed
in the script. All three defects existed because the script had been written
against the SDK but never executed until this spike.

**3. Citation quality is materially worse than Hybrid.** Grounding chunks
return `title` only — set to the ASCII slug — with `uri=None` and
`document_name=None`. Mapping a citation back to a real document therefore
requires a side lookup through `custom_metadata`. Hybrid returns the real
document title and chunk id directly and scored 100% Citation Accuracy on
the 30-case set (`docs/retrieval-ab-test-report.md`).

> **Superseded on 2026-08-07.** The adapter now always sends a grounding
> system instruction (commit `b71602e`), and the full 30-case A/B run scored
> Gemini at 100% Answer Accuracy, 100% No-answer and 100% Error-code
> accuracy. The behaviour described below was observed *without* that
> instruction and no longer occurs. See `docs/retrieval-ab-test-report.md`
> §4 for the corrected quality comparison — the reasons to stay on Hybrid
> are latency and the missing ACL/image support, not answer quality.

**4. Default answers violate §8.4 — but this is configuration, not a hard
limit.** With File Search's built-in prompting, answers drifted into model
general knowledge. Asked about `Error -619` (absent from the corpus) it
correctly said so, then continued 「但通常VPN連線問題可能與以下幾個方面有關」
and volunteered generic steps. Asked about 艾揚 -200 it mixed in TLS/proxy
steps belonging to a different document and prefaced them with 「通常這類
錯誤…」. Both breach §8.4/§17 (不得使用模型一般知識補充公司流程).

Re-running the same `-619` query with an explicit `system_instruction`
carrying our grounding rules produced a clean refusal with no general
knowledge added. So the adapter must supply its own system instruction —
File Search's defaults are not safe for this requirement on their own.

**5. Error-code retrieval itself worked.** The `-455` probe returned the
correct grounded procedure with the right source document.

**6. Store lifecycle needs ownership conventions.** The API key in use
already had 54 pre-existing File Search stores from unrelated work
(`session-*`, `helpdesk-store`, `your-fileSearchStore-name`). Nothing
identifies an owner or a project. Adopting File Search would need naming and
cleanup conventions, or stores accumulate indefinitely.

**8. Cost model (looked up 2026-08-07, not estimated).** Per
ai.google.dev: File Search **storage is free**; quotas are 1 GB (free tier),
10 GB (tier 1), 100 GB (tier 2), 1 TB (tier 3). Indexing is charged as
`gemini-embedding-2` embeddings ($0.15 / 1M tokens); query-time embedding is
free, and only the retrieved document tokens are billed as ordinary context.

Measured on this corpus: indexing all 19 documents (~9,665 tokens) is a
**one-off US$0.0014**. A single grounded query reported
`prompt=16, tool_use_prompt=2004, output=426` via `usage_metadata`, i.e.
**US$0.001671/query** at gemini-3.5-flash-lite list price, against Hybrid's
measured **US$0.001065/query** — File Search is ~1.57x per query. Storage
being free means the difference is entirely per-query volume:

| Queries | Gemini FS | Hybrid | Difference |
| --- | --- | --- | --- |
| 1,000 | US$1.67 | US$1.07 | US$0.61 |
| 10,000 | US$16.71 | US$10.65 | US$6.06 |
| 100,000 | US$167.10 | US$106.50 | US$60.60 |

Caveat: the per-query figure is one probe, not a 30-case mean — the adapter
does not yet surface `usage_metadata`, which is why the A/B table reports
Gemini cost as unmeasured. Wiring that up would make the comparison exact.

**7. Data residency is a new consideration.** Unlike inference calls, a File
Search store keeps a *persistent copy* of internal IT documents on Google's
side. The corpus already transits Google for embeddings, but persistence is
an additional step that needs an explicit infosec decision before any
production use. The spike store was deleted immediately after these runs.


### Criterion comparison

Hybrid figures come from the 30-case run in
`docs/retrieval-ab-test-report.md`. The File Search column is a qualitative
result from 4 documents and a handful of probes — it is **not** a
like-for-like score, and is labelled accordingly rather than given a fake
percentage.

| Criterion | HybridKnowledgeService | GeminiFileSearchKnowledgeService | Notes |
| --- | --- | --- | --- |
| Answer Accuracy | 100% (25/25) | Not scored — answers fluent and mostly correct | Not run on the full eval set |
| Recall@K | 100% (25/25) | Not scored | Relevant doc was retrieved in every probe |
| Groundedness | 100% (25/25) | **Fails by default** | Adds model general knowledge unless a custom system_instruction is supplied (finding 4) |
| Citation Accuracy | 100% (25/25) | **Degraded** | Only an ASCII slug title; uri and document_name are None (finding 3) |
| No-answer Accuracy | 100% (5/5) | Correct on both probes | Correctly says the code is undocumented, but then over-explains without a custom prompt |
| Error-code Accuracy | 100% (7/7) | Correct on the -455 probe | Cross-document contamination seen on the 艾揚 -200 probe |
| ACL Accuracy | TBD | N/A (not implemented in spike) | |
| Image Match Accuracy | TBD | N/A (not implemented in spike) | |
| P95 Latency | 3.31 s | Not measured | Probes were run interactively, not timed |
| 單次成本 | US$0.00106/query | Not measured | Storage cost of a persistent store not assessed |
| 維運複雜度 | Index built locally via `rag-index`; corpus and index stay under repo control | **Higher** | ASCII staging required, slug↔title mapping needed, store lifecycle unowned, persistent external copy of internal documents (findings 1, 6, 7) |

## Known spike limitations (by design, per §8.3 scope)

- No ACL / tenant allowlist enforcement.
- No image/`AgentImage` mapping from grounding metadata.
- No document governance metadata (owner/version/effectiveDate) round-trip.
- No automatic re-sync of `data/sources/` into a File Search store.

These are all out of scope for "just a spike" per §8.3 and should not block
landing this file; they are exactly what would need to be built if the A/B
test above justified promoting this adapter.
