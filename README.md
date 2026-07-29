# Teams Agent Backend

這是一個可擴充的 Microsoft Teams Bot 後端，使用 Python 與 Microsoft 365
Agents SDK。目前預設以 Echo 模式驗證通訊，也已具備切換至獨立 Agent API
的標準 contract：

```text
使用者：hello
Bot：收到：hello
```

服務端點：

- `POST /api/messages`：Azure Bot Service 的 Messaging endpoint
- `GET /healthz`：部署平台的健康檢查
- `GET /readyz`：Bot 與 Agent 模式的就緒檢查

## 專案狀態

截至 2026-07-29：

- Milestone 1「Azure Bot 與本機後端打通」已完成。
- Milestone 2 的 Teams app package 已成功上傳公司 Teams。
- 下一個驗收點是讓 Teams Adapter 切換為 API 模式，完成
  `@Bot <內部問題>` 的 LangGraph RAG 端到端測試。

目前已驗證的完整路徑：

```text
Azure Bot Test in Web Chat
→ 公開 HTTPS Dev Tunnel
→ POST /api/messages
→ Microsoft 365 Agents SDK
→ Echo handler
→ Azure Bot
→ Web Chat 顯示「收到：hello」
```

已完成項目：

- [x] 建立 Python 3.11 專案與 `uv` 開發環境
- [x] 使用 Microsoft 365 Agents SDK 建立 `AgentApplication`
- [x] 使用 MSAL connection manager 連接 Azure Bot／Entra App
- [x] 建立受 Connector JWT 保護的 `POST /api/messages`
- [x] 建立公開的 `GET /healthz`
- [x] 支援歡迎訊息、`/help` 與 Echo 回覆
- [x] 清除 Teams 訊息中的 Bot `@mention`
- [x] 擷取 tenant、team、channel、conversation 與 Entra user metadata
- [x] 建立 Echo／Agent API 雙模式
- [x] 建立 Agent Gateway request／response contract
- [x] 支援 Agent timeout、錯誤降級、trace ID 與來源引用
- [x] 建立 `/readyz` readiness endpoint
- [x] 使用 Dev Tunnels 暴露本機 HTTPS endpoint
- [x] Azure Bot `Test in Web Chat` 端到端測試成功
- [x] 加入 Dockerfile、環境變數範例、單元測試與 Ruff
- [x] 確認錯誤 App ID 會被 JWT audience validation 阻擋

Teams 與後續里程碑狀態：

- [x] 啟用 Microsoft Teams channel，Azure 狀態為 `Healthy`
- [x] 建立通過 v1.25 schema 驗證的 Teams app package
- [x] 加入 manifest v1.25 必要的 `supportsChannelFeatures`
- [x] 使用 Microsoft 365 公司／學校帳號將 app package 上傳到 Teams
- [ ] 在 Teams 頻道以 `@Bot` 完成 Echo 測試
- [x] 建立獨立 LangGraph Agentic RAG Gateway
- [x] 將 `data/sources` 內部文件建立為中文檢索索引
- [x] 完成 route、retrieve、relevance、rewrite、grounded answer graph
- [x] 完成來源引用、文件 ACL、service token 與 tenant allowlist
- [ ] 選定並設定正式 LLM／embedding model
- [ ] 由 Teams 頻道完成 Agent API 模式端到端驗收
- [ ] 串接唯讀內部 API 工具
- [ ] 部署到可長期運作的雲端環境

## 1. 必要條件

- Python 3.10–3.14（建議 3.11）
- 已建立的 Azure Bot resource
- Azure Bot 綁定之 Entra App Registration 的：
  - Application (client) ID
  - Directory (tenant) ID
  - Client secret **Value**

Client secret 只放在本機 `.env` 或雲端 Secret Manager，不可提交到 Git。

## 2. 本機設定

使用 `uv`：

```bash
uv sync --extra dev
cp .env.example .env
```

編輯 `.env`：

```dotenv
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID=<Microsoft App ID>
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET=<Client secret Value>
CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID=<Tenant ID>
PORT=3978
HOST=0.0.0.0
AGENT_MODE=echo
```

啟動：

```bash
uv run teams-agent
```

確認 health 與 readiness endpoints：

```bash
curl http://localhost:3978/healthz
curl http://localhost:3978/readyz
```

預期結果：

```json
{"status": "ok"}
{"status": "ready", "agentMode": "echo"}
```

`POST /api/messages` 會驗證 Azure Bot 傳入的 Bearer token，因此不能用普通 `curl`
模擬完整 Bot Activity。

### 本機 Log

只要 `uv run teams-agent` 保持執行，Teams／Web Chat 的請求會顯示在 Terminal：

```text
INFO teams_agent.agent Message received:
request_id=<uuid> channel=msteams conversation=<conversation-id>

POST /api/messages HTTP/1.1 200
```

目前 log 刻意不記錄使用者完整問題、Bot 回答、Client Secret 或 API Token。
每次請求會保留 request ID、channel 與 conversation ID 供問題追蹤。

Log level 可在 `.env` 設定：

```dotenv
LOG_LEVEL=INFO
```

需要更詳細的本機除錯資訊時可暫時改為 `DEBUG`，修改後必須重新啟動 Bot。
Dev Tunnel 的 inspect URL 可用來查看 HTTP 流量，但不得分享其中的
Authorization header。

## 3. 讓 Azure Bot 連到本機

開發時可使用 Microsoft Dev Tunnels 或其他提供公開 HTTPS 的 tunnel：

```bash
devtunnel user login -e
devtunnel host -p 3978 --allow-anonymous
```

使用 CLI 顯示的 `Connect via browser` URL；不要使用 inspect URL 或 tunnel ID。
取得 tunnel HTTPS URL 後，在 Azure Portal 設定：

```text
Azure Bot
→ Settings
→ Configuration
→ Messaging endpoint
→ https://<tunnel-domain>/api/messages
```

儲存後進入 `Test in Web Chat`，傳送 `hello`。成功時 Bot 應回覆：

```text
收到：hello
```

本機測試期間必須同時保持兩個程序執行：

```text
Terminal 1：uv run teams-agent
Terminal 2：devtunnel host -p 3978 --allow-anonymous
```

### 常見錯誤

`Invalid audience` 表示 `.env` 的 Client ID 與 Azure Bot 的 Microsoft App ID
不完全相同。請特別檢查多餘字元、前導字元及複製錯誤，修正後重新啟動後端。

瀏覽器直接開啟 `/` 或 `/api/messages` 時看到
`Authorization header not found` 是正常行為。瀏覽器只能直接檢查 `/healthz`；
`/api/messages` 必須由 Azure Bot Service 使用 `POST` 並攜帶 Connector JWT。

## 4. Agent 模式

### Echo 模式

開發與 Teams 通訊驗證階段使用：

```dotenv
AGENT_MODE=echo
```

這個模式不會呼叫外部 AI：

```text
hello → 收到：hello
```

### API 模式

本專案已在 `agent_service/` 建立 LangGraph Agent Gateway。啟動後設定：

```dotenv
AGENT_MODE=api
AGENT_API_URL=https://<agent-gateway-domain>/agent/chat
AGENT_API_TOKEN=<internal-service-token>
AGENT_API_TIMEOUT_SECONDS=10
```

非 localhost 的 `AGENT_API_URL` 強制使用 HTTPS。Token 只能放在 `.env`、
Secret Manager 或 Key Vault，不可寫入程式碼與 Git。

Teams Adapter 送出的 request：

```json
{
  "requestId": "uuid",
  "channel": "msteams",
  "conversation": {
    "tenantId": "tenant-id",
    "teamId": "team-id",
    "channelId": "channel-id",
    "conversationId": "conversation-id"
  },
  "user": {
    "teamsUserId": "teams-user-id",
    "entraObjectId": "entra-object-id",
    "displayName": "Justin"
  },
  "message": {
    "text": "如何申請 API Key？",
    "locale": "zh-TW"
  }
}
```

Agent Gateway 最小 response：

```json
{
  "answer": "請至內部平台提出申請。",
  "traceId": "trace-uuid",
  "citations": [
    {
      "title": "API Key 申請流程",
      "url": "https://internal.example/docs/api-key",
      "chunkId": "chunk-8"
    }
  ]
}
```

若 Agent API timeout、連線失敗或回傳格式錯誤，Teams 會收到友善降級訊息與
request trace ID。

## 5. Docker

```bash
docker build -t teams-agent-backend .
docker run --rm -p 8080:8080 --env-file .env teams-agent-backend
```

Messaging endpoint：

```text
https://<public-service-domain>/api/messages
```

部署到 GCP Cloud Run 或 Azure Container Apps 時，將三個
`CONNECTIONS__SERVICE_CONNECTION__SETTINGS__...` 值設成安全的環境變數／secret。
服務必須允許 Azure Bot Service 經由公網 HTTPS 呼叫；應用程式本身仍會驗證
Connector JWT。

## 6. 測試與程式碼檢查

```bash
uv run pytest
uv run ruff check .
```

## 未來方向

### Milestone 2：接入 Microsoft Teams 頻道

目標是讓 Team 頻道中的使用者可以透過 `@Bot hello` 觸發現有 Echo handler。

目前已完成：

- [x] Azure Bot 的 Microsoft Teams channel 已啟用且為 `Healthy`
- [x] 建立 Teams app manifest
- [x] Bot scopes 設為 `team` 與 `personal`
- [x] 預設安裝範圍設為 `team`
- [x] 建立符合規格的 192×192 彩色 icon
- [x] 建立具有透明背景的 32×32 白色 outline icon
- [x] 建立 app package 打包腳本
- [x] 加入 manifest v1.25 `supportsChannelFeatures: tier1`
- [x] App package 成功上傳公司 Teams

接下來操作：

1. 保持本機 Bot 與 Dev Tunnel 執行。
2. 確認 Azure Bot Messaging endpoint 仍指向目前的 Dev Tunnel `/api/messages`。
3. 將已上傳的 App 安裝到指定測試 Team。
4. 在一般頻道輸入 `@Teams AI Agent hello`。
5. 確認 Teams 收到 `收到：hello`。
6. 確認本機 log 出現 `channel=msteams` 與 HTTP `200`。
7. 再於 personal scope 傳送 `hello`，確認私人聊天也能回覆。

如果沒有 `Upload a custom app` 選項，需要 Teams 管理員在 app setup policy
開啟 custom app upload，或由管理員在 Teams admin center 上傳 package。
Microsoft Teams 免費／個人版不提供此企業自訂 app 上傳流程；請使用具有 Teams
授權的 Microsoft 365 公司或學校帳號。

`manifest.json` 中的 developer URLs 目前是 PoC placeholder。內部正式發布前，
必須替換成公司的網站、隱私權政策與使用條款 URL。

完成標準：

- App 可安裝到指定 Team。
- 頻道輸入 `@Bot hello` 可收到 `收到：hello`。
- 未提及 Bot 的訊息不觸發後端。

### Milestone 3：串接獨立 AI Agent API

保留 Teams Adapter 為薄通訊層，把 AI 邏輯放在獨立 Agent Gateway：

```text
Teams
→ Azure Bot Service
→ Teams Adapter /api/messages
→ Agent Gateway /agent/chat
→ 回傳答案
→ Teams
```

Adapter contract、client 與實際 LangGraph Agent Gateway 均已完成：

- request ID 與 trace ID
- Teams tenant、team、channel、conversation 與使用者識別
- 問題文字與 locale
- 結構化答案、來源引用及錯誤狀態
- timeout、重試與友善降級訊息

正式部署前仍需確定：

- Agent Gateway 的實際 HTTPS URL
- 服務間驗證方式
- request／response contract 是否沿用本專案格式
- timeout、無答案與錯誤回覆規則
- 哪些使用者識別欄位允許傳入 Agent Gateway

### Milestone 4：RAG 知識問答

- [x] 建立 Markdown ingestion、清理、切塊與穩定 chunk ID
- [x] 建立中文 BM25，並預留 embedding hybrid retrieval
- [x] 建立相關性門檻與無答案回覆
- [x] 在 retrieval 階段套用文件群組 ACL
- [x] 回覆附上文件標題與 chunk trace
- [x] 建立 LangGraph route、retrieve、grade、rewrite、generate 流程
- [ ] 選定正式 LLM 與 embedding model
- [ ] 將正式文件 URL 映射至 citation
- [ ] 建立 FAQ 評估集，量測正確率、引用率與無答案率

完整啟動、設定與 API 範例請見
[`agent_service/README.md`](agent_service/README.md)。

### Milestone 5：內部 API 與工具

先接唯讀工具，再評估寫入操作：

- Tool allowlist 與 JSON Schema 參數驗證
- 使用可信任的 Entra／IAM 身分，不接受模型自行提供 user ID 或 role
- API timeout、重試、rate limit 與 circuit breaker
- 敏感操作要求使用者明確確認
- 完整 audit log，不記錄 secret 或不必要的個資

### Milestone 6：正式部署與治理

- 部署至 GCP Cloud Run、Azure Container Apps 或公司既有容器平台
- Secret 改由 Secret Manager／Key Vault 管理
- 對話狀態由 MemoryStorage 遷移到 Redis、PostgreSQL 或受管儲存
- 加入 OpenTelemetry、集中式 log、錯誤率與 P95 latency 監控
- 加入 prompt injection 防護、PII 遮蔽、內容安全與工具權限政策
- 建立 dev、test、prod 環境與獨立 App Registration
- 正式環境移除對 Dev Tunnel 的依賴

## 建議執行順序

```text
Web Chat Echo ✅
→ Teams App 上傳 ✅
→ LangGraph Agent Gateway ✅
→ data/ 文件索引與 RAG API ✅
→ Teams Channel Agent API 模式（目前）
→ 選定 LLM／embedding 並建立評估集
→ 唯讀內部工具
→ 身分與 ACL
→ 正式環境部署與監控
→ 寫入型工具與審批
```

## 下一步驗收清單

- [ ] 測試 Team 成功安裝 App
- [ ] 頻道 `@Bot hello` 回覆成功
- [ ] 本機收到 `msteams` activity 並留下 request ID
- [ ] 未 `@mention` Bot 時不觸發
- [ ] Personal scope Echo 成功
- [ ] 啟動 `agent_service` 並將 Adapter 切為 `AGENT_MODE=api`
- [ ] 頻道提問可收到知識庫回答與來源
- [ ] 無關問題回覆「沒有足夠資訊」
- [ ] 記錄第一次 Teams + LangGraph RAG 端到端測試結果
