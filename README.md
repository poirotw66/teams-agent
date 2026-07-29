# Teams Agent Backend

這是一個最小可用的 Microsoft Teams Bot 後端，使用 Python 與 Microsoft 365
Agents SDK。第一階段只提供 Echo 功能：

```text
使用者：hello
Bot：收到：hello
```

服務端點：

- `POST /api/messages`：Azure Bot Service 的 Messaging endpoint
- `GET /healthz`：部署平台的健康檢查

## 專案狀態

截至 2026-07-29，Milestone 1「Azure Bot 與本機後端打通」已完成。

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
- [x] 使用 Dev Tunnels 暴露本機 HTTPS endpoint
- [x] Azure Bot `Test in Web Chat` 端到端測試成功
- [x] 加入 Dockerfile、環境變數範例、單元測試與 Ruff
- [x] 確認錯誤 App ID 會被 JWT audience validation 阻擋

目前尚未完成：

- [ ] 啟用 Microsoft Teams channel
- [ ] 建立與上傳 Teams app package
- [ ] 在 Teams 頻道以 `@Bot` 完成 Echo 測試
- [ ] 串接真正的 AI Agent API、RAG 與內部 API
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
```

啟動：

```bash
uv run teams-agent
```

確認 health endpoint：

```bash
curl http://localhost:3978/healthz
```

預期結果：

```json
{"status": "ok"}
```

`POST /api/messages` 會驗證 Azure Bot 傳入的 Bearer token，因此不能用普通 `curl`
模擬完整 Bot Activity。

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

## 4. Docker

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

## 5. 測試與程式碼檢查

```bash
uv run pytest
uv run ruff check .
```

## 未來方向

### Milestone 2：接入 Microsoft Teams 頻道

目標是讓 Team 頻道中的使用者可以透過 `@Bot hello` 觸發現有 Echo handler。

1. 在 Azure Bot 啟用 Microsoft Teams channel。
2. 建立 Teams app manifest 與 app package。
3. Bot scope 第一版加入 `team`，建議同時保留 `personal`。
4. 將 app package 上傳或交由 Microsoft 365 管理員發布。
5. 安裝到測試 Team，驗證頻道 `@mention`、使用者、Team 與 Channel 資訊。

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

第一版 Agent API 應支援：

- request ID 與 trace ID
- Teams tenant、team、channel、conversation 與使用者識別
- 問題文字與 locale
- 結構化答案、來源引用及錯誤狀態
- timeout、重試與友善降級訊息

### Milestone 4：RAG 知識問答

1. 建立文件 ingestion、切塊與版本管理。
2. 導入 hybrid retrieval、reranker 與無答案門檻。
3. 在 retrieval 階段套用部門／群組 ACL。
4. 回覆附上文件標題、URL 與 chunk trace。
5. 建立 FAQ 測試集，評估正確率、引用率與無答案率。

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
目前：Web Chat Echo ✅
→ Teams Channel Echo
→ Agent API
→ RAG + 引用
→ 唯讀內部工具
→ 身分與 ACL
→ 正式雲端部署
→ 寫入型工具與審批
```
