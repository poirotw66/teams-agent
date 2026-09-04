# LangGraph Agent Service

> 繁體中文（本頁）｜[English](./README.md)

這是 Teams Adapter 後方的獨立 Agent Service。它會載入對話上下文、拆解
Issue、走 FAQ／追問／Hybrid RAG／工單流程，再以 Deterministic Response
Builder 組裝回覆。知識語料來自專案根目錄 `data/sources/*.md`。

```text
Teams Adapter
  → POST /agent/chat  （或 /agent/chat/stream）
  → Load Conversation
  → Extract Issues（最多 3）
  → Filter IT
  → Process Issues（並行）
       ├─ FAQ（固定答案，不呼叫 LLM）
       ├─ Need More Info（最多 2 問）
       ├─ Hybrid RAG（ACL + BM25/embedding）
       └─ Ticket（需明確確認）
  → Response Builder → Save Conversation
```

舊的單次 RAG graph（`graph.py` 的 route／retrieve／grade／rewrite／generate）
仍保留於知識後端內部；對外入口以 `workflow.py` 的 `AgentWorkflow` 為準。
完整規格與 Adapter 設定見根目錄 [`README-TW.md`](../README-TW.md)
（English: [`README.md`](../README.md)）。

## 已完成

- Markdown 清理、切塊與穩定 chunk ID
- 中文字詞與 bigram BM25 檢索
- 可選的 embedding hybrid search
- 文件層 `allowedGroups` ACL，在 retrieval 前過濾
- LangGraph Workflow：對話、Issue、FAQ、追問、知識、工單、Feedback
- 保存 Markdown 圖片與父章節關聯，回答可回傳受 ACL 保護來源的圖片 metadata
- 沒有 LLM 金鑰也能運作的 extractive local mode
- `/agent/chat`、`/agent/chat/stream` SSE、`/feedback`、`/retrieval/search`
- Conversation MEMORY／FILE／FIRESTORE；Ticket HTTP Adapter
- Service token、tenant allowlist、health/readiness endpoints
- Dockerfile 與單元／整合／安全測試
- 每次 `/agent/chat` 會在後端 log 記錄 LLM／embedding token 用量與 USD 價格估算

## 本機啟動

從 `agent_service/` 執行：

```bash
uv sync --extra dev
cp .env.example .env
uv run rag-index
uv run rag-agent
```

檢查服務：

```bash
curl http://localhost:8000/readyz
```

測試檢索：

```bash
curl -X POST http://localhost:8000/retrieval/search \
  -H 'Content-Type: application/json' \
  --data '{
    "query": "VPN 密碼錯誤如何處理？",
    "groups": [],
    "limit": 3
  }'
```

測試 Agent：

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

如果有設定 `AGENT_SERVICE_TOKEN`，兩個 POST 端點都必須加入：

```text
Authorization: Bearer <相同 token>
```

## 啟用生成式回答

預設不會呼叫外部模型，只回傳檢索到的原文，適合先驗證資料與權限。若要讓
LangGraph 進行語意 routing、relevance grading、query rewrite 與答案整理，
在 `.env` 選擇一個模型：

OpenAI：

```dotenv
RAG_MODEL=openai:gpt-4.1-mini
OPENAI_API_KEY=<secret>
```

Google Gemini：

```dotenv
RAG_MODEL=google_genai:gemini-3.5-flash-lite
GOOGLE_API_KEY=<secret>
```

模型名稱是部署設定，不應寫死在程式中。正式使用前，請依公司核准的模型服務
與實際可用 model ID 調整。

若要啟用 dense embedding 與 hybrid search：

```dotenv
RAG_EMBEDDING_MODEL=google_genai:gemini-embedding-2
RAG_MAX_IMAGES=2
```

更改 chunk 或 embedding 設定後需重建索引：

```bash
uv run rag-index
```

## 文件權限

複製 `agent_service/metadata.example.json` 為 `data/metadata.json`，以來源相對路徑設定
文件權限：

```json
{
  "sources/VPN常見Q&A問答.md": {
    "classification": "internal",
    "allowedGroups": ["IT-Employees"]
  }
}
```

- 沒有 `allowedGroups` 的文件視為所有已通過 Agent Gateway 驗證的使用者可讀。
- 有 `allowedGroups` 的文件只會對擁有任一對應群組的請求回傳。
- 群組必須由 Teams／Entra／IAM 的可信任後端映射，不可採信使用者文字。

目前是適合 PoC 的本機 JSON 索引。資料量、併發量或 ACL 規則成長後，可保留
LangGraph 與 API contract，只將 `HybridIndex` 替換成公司核准的向量資料庫。

## 串接 Teams Adapter

在專案根目錄的 Teams Adapter `.env` 設定：

```dotenv
AGENT_MODE=api
AGENT_API_URL=http://localhost:8000/agent/chat
AGENT_API_TIMEOUT_SECONDS=20
AGENT_API_TOKEN=<與 AGENT_SERVICE_TOKEN 相同的值>
```

本機需同時啟動：

```text
Terminal 1：cd agent_service && uv run rag-agent
Terminal 2：uv run teams-agent
Terminal 3：devtunnel host -p 3978 --allow-anonymous
```

Dev Tunnel 只需要暴露 Teams Adapter 的 `3978`；Agent Gateway 的 `8000` 可留在
本機，不必公開。

當命中的 Markdown 章節包含 `assets/...` 圖片時，`/agent/chat` 會額外回傳：

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

Agent Service 不提供公開圖片檔案；Teams Adapter 會驗證相對路徑、簽名並透過
自己的 HTTPS domain 提供縮圖。如此 `8000` 仍可保持內部服務。

## API

- `GET /healthz`：程序存活
- `GET /readyz`：索引已載入及目前模型／檢索模式
- `POST /retrieval/search`：檢索除錯
- `POST /agent/chat`：Teams Adapter 使用的正式入口
- `POST /agent/chat/stream`：同一份答案，改以 Server-Sent Events 回傳

`/agent/chat/stream` 的事件格式：

```text
event: stage
data: {"label": "正在檢索知識庫…"}

event: response
data: {"answer": "...", "citations": [...], "feedbackEnabled": true, ...}
```

`stage` 對應 LangGraph 節點完成（標籤定義在 `workflow.STAGE_LABELS`），
`response` 的 body 與 `/agent/chat` 完全相同，兩者必定擇一出現在最後：
workflow 失敗時改送 `event: error`。

錯誤語意與 `/agent/chat` 有一處必然的差異：HTTP status 在第一個 byte 送出
時就已定案，因此**執行中**的失敗無法再變成 503，只能以 `error` 事件送出。
在 workflow 開始前就能判定的拒絕（service token 錯誤、tenant 不在
allowlist）仍然是正常的 HTTP 401／403。

每次 `/agent/chat` 完成時，後端會輸出 structured log，包含：

```text
input_tokens / output_tokens / total_tokens / embedding_tokens / estimated_cost_usd
```

LLM token 來自 provider 回傳的 usage metadata；embedding token 為查詢文字的粗估。
價格依內建 Standard paid-tier 費率表估算（USD），未知模型只記 token、不估價。

Swagger UI：`http://localhost:8000/docs`

## 驗證

```bash
uv run pytest -q
uv run ruff check src tests
```
