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
devtunnel host -p 3978 --allow-anonymous
```

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

## 下一階段

Web Chat Echo 成功後，再依序：

1. 啟用 Azure Bot 的 Microsoft Teams channel。
2. 建立 Teams app manifest，Bot scope 加入 `team`。
3. 在 Team 頻道以 `@Bot hello` 測試。
4. 將 `src/teams_agent/agent.py` 的 Echo handler 改為呼叫獨立 Agent API。
5. 接入 RAG、來源引用與唯讀內部工具。
