# LangGraph Agent Service

> English (this page) | [繁體中文](./README-TW.md)

This is the standalone Agent Service behind the Teams Adapter. It loads
conversation context, extracts issues, and runs FAQ / follow-up / Hybrid RAG /
ticket flows, then assembles the reply with a Deterministic Response Builder.
Knowledge content comes from `data/sources/*.md` at the project root.

```text
Teams Adapter
  → POST /agent/chat  (or /agent/chat/stream)
  → Load Conversation
  → Extract Issues (max 3)
  → Filter IT
  → Process Issues (in parallel)
       ├─ FAQ (fixed answer, no LLM)
       ├─ Need More Info (max 2 questions)
       ├─ Hybrid RAG (ACL + BM25/embedding)
       └─ Ticket (explicit confirmation required)
  → Response Builder → Save Conversation
```

The older single-shot RAG graph (`graph.py` route / retrieve / grade / rewrite /
generate) is still kept inside the knowledge backend; the public entry point is
`AgentWorkflow` in `workflow.py`. For the full specification and Adapter setup,
see the root [`README.md`](../README.md)
(Traditional Chinese: [`README-TW.md`](../README-TW.md)).

## Done

- Markdown cleanup, chunking, and stable chunk IDs
- Chinese word and bigram BM25 retrieval
- Optional embedding hybrid search
- Document-level `allowedGroups` ACL filtering before retrieval
- LangGraph Workflow: conversation, issues, FAQ, follow-up, knowledge, tickets, feedback
- Preserve Markdown images and parent-section links; answers can return image metadata from ACL-protected sources
- Extractive local mode that works without an LLM key
- `/agent/chat`, `/agent/chat/stream` SSE, `/feedback`, `/retrieval/search`
- Conversation MEMORY / FILE / FIRESTORE; Ticket HTTP Adapter
- Service token, tenant allowlist, health/readiness endpoints
- Dockerfile and unit / integration / security tests
- Each `/agent/chat` call logs LLM / embedding token usage and an estimated USD cost on the backend

## Local startup

From `agent_service/`:

```bash
uv sync --extra dev
cp .env.example .env
uv run rag-index
uv run rag-agent
```

Check the service:

```bash
curl http://localhost:8000/readyz
```

Test retrieval:

```bash
curl -X POST http://localhost:8000/retrieval/search \
  -H 'Content-Type: application/json' \
  --data '{
    "query": "VPN 密碼錯誤如何處理？",
    "groups": [],
    "limit": 3
  }'
```

Test the Agent:

```bash
curl -X POST http://localhost:8000/agent/chat \
  -H 'Content-Type: application/json' \
  --data '{
    "requestId": "local-test-1",
    "channel": "local-test",
    "conversation": {
      "tenantId": "local",
      "conversationId": "local"
    },
    "user": {
      "displayName": "tester",
      "groups": []
    },
    "message": {
      "text": "VPN 密碼錯誤如何處理？",
      "locale": "zh-TW"
    }
  }'
```

If `AGENT_SERVICE_TOKEN` is set, both POST endpoints must include:

```text
Authorization: Bearer <相同 token>
```

## Enable generative answers

By default no external model is called; only retrieved source text is returned,
which is useful for validating data and permissions first. To let LangGraph do
semantic routing, relevance grading, query rewrite, and answer synthesis, pick a
model in `.env`:

OpenAI:

```dotenv
RAG_MODEL=openai:gpt-4.1-mini
OPENAI_API_KEY=<secret>
```

Google Gemini:

```dotenv
RAG_MODEL=google_genai:gemini-3.5-flash-lite
GOOGLE_API_KEY=<secret>
```

Model names are a deployment setting and must not be hard-coded. Before
production use, adjust them to your company-approved model service and the
actual available model IDs.

To enable dense embeddings and hybrid search:

```dotenv
RAG_EMBEDDING_MODEL=google_genai:gemini-embedding-2
RAG_MAX_IMAGES=2
```

Rebuild the index after changing chunk or embedding settings:

```bash
uv run rag-index
```

## Document permissions

Copy `agent_service/metadata.example.json` to `data/metadata.json` and set
document permissions by source-relative path:

```json
{
  "sources/VPN常見Q&A問答.md": {
    "classification": "internal",
    "allowedGroups": ["IT-Employees"]
  }
}
```

- Documents without `allowedGroups` are readable by any user who already passed Agent Gateway authentication.
- Documents with `allowedGroups` are returned only for requests that include at least one matching group.
- Groups must come from a trusted Teams / Entra / IAM backend mapping; never trust user-supplied text.

This is a local JSON index suitable for a PoC. As data volume, concurrency, or
ACL rules grow, you can keep LangGraph and the API contract and only replace
`HybridIndex` with a company-approved vector database.

## Wire up the Teams Adapter

In the Teams Adapter `.env` at the project root:

```dotenv
AGENT_MODE=api
AGENT_API_URL=http://localhost:8000/agent/chat
AGENT_API_TIMEOUT_SECONDS=20
AGENT_API_TOKEN=<與 AGENT_SERVICE_TOKEN 相同的值>
```

Start both locally:

```text
Terminal 1：cd agent_service && uv run rag-agent
Terminal 2：uv run teams-agent
Terminal 3：devtunnel host -p 3978 --allow-anonymous
```

Dev Tunnel only needs to expose the Teams Adapter on `3978`; Agent Gateway
`8000` can stay local and does not need to be public.

When a matched Markdown section contains `assets/...` images, `/agent/chat`
also returns:

```json
{
  "images": [
    {
      "path": "大州系統_功能無法點選/p01.png",
      "title": "大州無法點選 — IE 安全性調整",
      "altText": "大州無法點選 — IE 安全性調整",
      "sourceChunkId": "816cb874325a3f5d8be5"
    }
  ]
}
```

The Agent Service does not serve public image files; the Teams Adapter validates
relative paths, signs them, and serves thumbnails through its own HTTPS domain.
That way `8000` can remain an internal service.

## API

- `GET /healthz`: process liveness
- `GET /readyz`: index loaded plus current model / retrieval mode
- `POST /retrieval/search`: retrieval debugging
- `POST /agent/chat`: production entry used by the Teams Adapter
- `POST /agent/chat/stream`: the same answer, returned as Server-Sent Events

`/agent/chat/stream` event format:

```text
event: stage
data: {"label": "正在檢索知識庫…"}

event: response
data: {"answer": "...", "citations": [...], "feedbackEnabled": true, ...}
```

`stage` corresponds to LangGraph node completion (labels defined in
`workflow.STAGE_LABELS`). The `response` body is identical to `/agent/chat`, and
exactly one of them appears last: on workflow failure an `event: error` is sent
instead.

Error semantics differ from `/agent/chat` in one unavoidable way: the HTTP
status is fixed when the first byte is sent, so **in-flight** failures cannot
become 503 and must be delivered as an `error` event. Rejections that can be
decided before the workflow starts (bad service token, tenant not on the
allowlist) still return normal HTTP 401 / 403.

Each completed `/agent/chat` emits a structured backend log with:

```text
input_tokens / output_tokens / total_tokens / embedding_tokens / estimated_cost_usd
```

LLM tokens come from provider usage metadata; embedding tokens are a rough
estimate of the query text. Cost is estimated from a built-in Standard paid-tier
rate table (USD); unknown models log tokens only and skip pricing.

Swagger UI: `http://localhost:8000/docs`

## Verification

```bash
uv run pytest -q
uv run ruff check src tests
```
