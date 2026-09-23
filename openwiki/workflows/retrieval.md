---
type: workflow
title: Retrieval backends
description: How FAQ, hybrid local search, and Gemini File Search are selected, and what access filter each one applies before an answer is grounded.
tags: [retrieval, rag, faq, gemini]
sources:
  - id: openwiki-source-a3f1c5259bc8a0679f11ace2
    resource: repo://agent_service/src/agent_service/deps_sync.py
  - id: openwiki-source-568530483fe59755c42c9104
    resource: repo://agent_service/src/agent_service/gemini_file_search.py
  - id: openwiki-source-2eee0616077f000182d43e61
    resource: repo://agent_service/src/agent_service/graph.py
  - id: openwiki-source-424391e43b8a125606ec6ac9
    resource: repo://agent_service/src/agent_service/knowledge_backends.py
  - id: openwiki-source-26e5f04fe4ca52bd844900b2
    resource: repo://agent_service/src/agent_service/knowledge_release.py
  - id: openwiki-source-6be06485608fa2987b258286
    resource: repo://agent_service/src/agent_service/retrieval_acl.py
  - id: openwiki-source-4ff29211df7a7d63f59f2f1b
    resource: repo://agent_service/src/agent_service/retrieval.py
generated: { by: "cursor", at: "2026-09-22T17:10:06.227Z" }
verified:
  - by: openwiki/0.5.1
    at: 2026-09-22T17:10:06.227Z
---

# Retrieval backends

FAQ is not a retrieval backend. The issue workflow checks FAQ first and returns a verbatim answer on hit. Only a miss, a disabled entry, or a knowledge route reaches this page. See [Issue resolution workflow](/openwiki/workflows/issue-resolution.md).

## Which search runs

The knowledge router has two services: `HYBRID` (local index) and `GEMINI_FILE_SEARCH`. `resolve_backend` uses the request's evaluation backend only when the channel is in the evaluation-channel allowlist. Otherwise it uses the active backend stored in memory or Firestore. Selecting an unavailable backend raises. A stored name that is no longer registered falls back to a registered service instead of failing the turn.

Playground exposes the switch after login. That switch changes the active backend. It does not change FAQ behavior.

## Hybrid index

`HybridIndex.search` scores every chunk with BM25. Chinese runs are tokenized as characters and adjacent bigrams, so a query is not required to match a whole word. If an embedding client and chunk vectors exist, the score mixes the normalized BM25 score with cosine similarity. Without embeddings, `/readyz` reports retrieval as `chinese-bm25` rather than `hybrid`.

A chunk with `allowed_groups` is skipped unless the caller's groups intersect that set. An empty allow-list is visible to the search. Under `KNOWLEDGE_RELEASE_STORE_MODE=FILE`, the loaded index comes from the bundled file or the active portal release under `data/releases`. Under `GCS`, HYBRID loads from the verified local mirror (or an explicit LOCAL_SANDBOX release); ask-time resolution fails closed when no verified snapshot exists and does not silently fall back to bundled/FILE production trees. FOLLOW_CLOUD may hot-swap the in-memory index after sync via `apply_follow_cloud_mirror_reload`. See [Local GCS knowledge sync](/openwiki/workflows/local-gcs-knowledge-sync.md) and [Knowledge release](/openwiki/workflows/knowledge-release.md).

The small RAG graph in front of hybrid search routes a bare greeting (`hi`, `hello`, `你好`, `謝謝`, and the same set in English) to a direct reply and does not search. Other queries retrieve when no model is configured. With a model, a structured route decision chooses `direct` or `retrieve`.

## Gemini File Search

This backend queries a configured File Search store. It is not the default hybrid index. ACL enforcement is on unless the service is constructed with `enforce_acl=False`, and that disable is logged. When enforcement is on, the metadata filter is derived from the caller's groups and cannot be omitted. A caller-supplied `metadata_filter` is rejected rather than AND-combined, because that combination was not verified against a live store and a wrong combination would be a privilege bug. Extra narrowing belongs in `allowed_groups` at upload time.

A File Search hit is still a knowledge result. It does not bypass citation or the "no knowledge means no invented answer" rule owned by the issue workflow.
