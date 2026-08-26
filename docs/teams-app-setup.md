# Teams App 設定與測試說明（spec §20 項目 20）

本文件涵蓋 Teams app 註冊與側載（sideload）、Teams Developer Portal 的 bot
設定、endpoint 切換、本機 Dev Tunnel 測試，以及只能在真實 Teams 用戶端手動
驗證的 POC 驗收項目（spec §19 第 1、2、12 項）。

環境變數、Docker、Cloud Run 部署細節請見
[`../README.md`](../README.md)（English）／[`../README-TW.md`](../README-TW.md)
（繁中）與 [`../deploy/README.md`](../deploy/README.md)；
本文件只涵蓋 Teams 這一側的設定與手動測試。

> **為什麼不用 Azure Bot Service。** 集團沒有 Azure Subscription，無法建立
> Azure Bot resource。Teams Adapter 因此改用
> [Microsoft Teams SDK](https://microsoft.github.io/teams-sdk)
> （`microsoft-teams-apps`），bot 註冊改在
> [Teams Developer Portal](https://dev.teams.microsoft.com/apps) 完成。
> Entra ID app registration 隨 Microsoft 365 授權提供，不需要 Azure 訂閱。

## 1. 先備條件

- 一個 Entra ID app registration（Microsoft Entra admin center →
  App registrations，**不需要 Azure 訂閱**）。
- 具有 Teams 授權的 Microsoft 365 公司或學校帳號（免費／個人版 Teams 不
  支援自訂 app 側載）。
- 可存取 [Teams Developer Portal](https://dev.teams.microsoft.com)。
- 若沒有 `Upload a custom app` 選項：需要 Teams 管理員在 app setup policy
  開啟 custom app upload，或由管理員直接在 Teams admin center 上傳
  package。

> **上線前要先跟 Teams／Entra 管理員確認的一件事**：租戶是否允許在
> Developer Portal 自行建立 app registration 與 bot。部分企業租戶會鎖住
> 「使用者可註冊應用程式」，此時 app registration 必須由管理員代建，再把
> client ID／secret 交給開發者——流程仍然不需要 Azure 訂閱。

## 2. App registration 與 bot 設定（取代 Azure Bot Service）

### 2.1 建立 Entra ID app registration

1. [Microsoft Entra admin center](https://entra.microsoft.com) →
   **Identity → Applications → App registrations → New registration**。
2. Supported account types 選 **Accounts in this organizational directory
   only**（單一租戶）。不需要設定 Redirect URI。
3. 建立後記下並妥善保存：
   - Application (client) ID → `CLIENT_ID`
   - Directory (tenant) ID → `TENANT_ID`
4. **Certificates & secrets → New client secret**，記下 secret 的
   **Value**（只在建立當下顯示一次）→ `CLIENT_SECRET`。

### 2.2 在 Teams Developer Portal 設定 bot

1. [Teams Developer Portal](https://dev.teams.microsoft.com) → **Tools →
   Bot management → New bot**（或選擇既有 bot）。
2. 把 bot 綁定到 2.1 的 Application (client) ID。
3. **Configure → Endpoint address** 設為：
   - 本機開發：目前的 Dev Tunnel HTTPS URL + `/api/messages`（見第 4 節）
   - 雲端：`https://<teams-agent-adapter-cloud-run-url>/api/messages`
     （見 [`../deploy/README.md`](../deploy/README.md)）
4. 確認 **Channels** 已包含 **Microsoft Teams**。

`appPackage/manifest.json` 的 `bots[0].botId` 必須與這個 App ID 一致
（見第 3 節）。

### 2.3 寫進 `.env`

```dotenv
CLIENT_ID=<Application (client) ID>
CLIENT_SECRET=<Client secret Value>
TENANT_ID=<Directory (tenant) ID>
```

這三個值只能放在本機 `.env` 或雲端 Secret Manager，絕不可提交到 Git 或
寫進程式碼（spec §17）。`CLIENT_SECRET` 在 Cloud Run 上一律走 Secret
Manager，不可用一般環境變數。

Teams SDK 會直接從環境讀這三個變數，並用它們驗證打進
`POST /api/messages` 的 Bot Framework JWT。本機若要在完全沒有憑證的情況下
測試，可暫時設定 `DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS=true`——**僅限
本機**，設在 Cloud Run 等同把 endpoint 對全世界開放。

## 3. Teams App 註冊與側載（Sideload）

1. 確認 `appPackage/manifest.json`、`appPackage/color.png`（192×192 全彩
   icon）、`appPackage/outline.png`（32×32 白色透明 outline icon）齊全。
2. `manifest.json` 中需要確認／調整：
   - `id`：Teams app 的唯一識別碼（GUID）
   - `bots[0].botId`：與第 2 節 app registration 的 Application (client) ID 一致
   - `bots[0].scopes`：`["personal", "team"]`
   - `supportsChannelFeatures: "tier1"`（v1.25 schema 必要欄位）
   - `developer.websiteUrl` / `privacyUrl` / `termsOfUseUrl`：**目前是
     PoC placeholder**（`https://example.com/...`）。正式對外發布前必須
     換成公司真實網址；PoC 內部測試可先保留 placeholder。
3. 打包：

   ```bash
   ./scripts/build-teams-package.sh
   ```

   產出 `appPackage/dist/teams-ai-agent.zip`。

4. 側載到 Team：Teams 用戶端 → **Apps** → **Manage your apps** →
   **Upload an app** → **Upload a custom app** → 選擇
   `teams-ai-agent.zip` → 選擇要安裝的 Team。

## 4. 本機測試：Dev Tunnel

本機開發時 Teams 需要一個公開 HTTPS endpoint 才能打到 `localhost`。

啟動完整本機環境（Agent Service + Teams Adapter + Dev Tunnel）：

```bash
./start.sh
```

`start.sh` 會依序：

1. 啟動 Agent Service（`:8000`，等待 `/readyz` 就緒）。
2. 啟動 Teams Adapter（`:3978`，等待 `/readyz` 就緒）。
3. 啟動 `devtunnel host -p 3978 --allow-anonymous`。

若 Dev Tunnel 已由其他 Terminal 執行，改用：

```bash
START_TUNNEL=false ./start.sh
```

首次使用 Dev Tunnel 需要先登入：

```bash
devtunnel user login -e
```

取得 tunnel 顯示的 `Connect via browser` URL（**不要**使用 inspect URL 或
tunnel ID）後，回到第 2 節把 Developer Portal 的 bot Endpoint address 設為
`https://<tunnel-domain>/api/messages`，並確認根目錄 `.env` 的
`BOT_PUBLIC_BASE_URL` 與這個 tunnel domain 一致（用於簽出來源圖片
URL）——Dev Tunnel URL 每次啟動都可能改變，改變時要同步更新並重啟 Teams
Adapter。

`Ctrl+C` 會停止 `start.sh` 啟動的所有子程序（Agent Service、Teams
Adapter、Dev Tunnel）。若 `3978` 或 `8000` 已被舊程序占用，腳本會先偵測並
提示需要手動關閉哪個服務。

## 5. User Directory Service：Graph 權限（`USER_DIRECTORY_MODE=graph`）

預設 `USER_DIRECTORY_MODE=disabled`（不呼叫 Microsoft Graph，POC 預設，
不需要任何 Graph API 權限）。

若要啟用 `USER_DIRECTORY_MODE=graph`（在 Teams 訊息本身沒有帶 email 時，
透過 `GET /users/{id}` 補查使用者 email，供工單建立使用 spec §11.4／§12）：

1. [Microsoft Entra admin center](https://entra.microsoft.com) →
   App registrations → 找到第 2.1 節的 app registration →
   **API permissions**。
2. 新增 **Microsoft Graph → Application permissions → `User.Read.All`**。
3. 由 Entra 租戶管理員完成 **Grant admin consent**（Application
   permission 一定要 admin consent，使用者本人無法自行同意）。
4. 設定 `USER_DIRECTORY_MODE=graph`，需要時可調整
   `USER_DIRECTORY_CACHE_TTL_SECONDS`（預設 300 秒，查詢結果的 in-process
   快取時間）。

實作見 [`../src/teams_agent/directory.py`](../src/teams_agent/directory.py)：
Graph 呼叫使用 app 自己的 app-only 憑證（`EntraAppTokenProvider`，以
`CLIENT_ID` / `CLIENT_SECRET` / `TENANT_ID` 直接走 OAuth 2.0 client
credentials grant），從不使用使用者提供的 token；查詢失敗一律降級為「取不到 email」而不中斷該輪對話。若未授
予 `User.Read.All` 或未完成 admin consent，Graph 呼叫會失敗並記錄
warning，行為等同 `disabled`（工單建立會因缺少可信任 email 而明確拒絕，
不會用猜測值頂替，見 spec §11.4）。

## 5.5 兩段式本機驗收

驗收分兩段，順序不能顛倒——第一段能自動化、跑一次幾秒鐘，用來擋掉協定層的
錯誤；第二段只能靠人眼，成本高，所以放在後面。

```
修改程式
    │
    ▼
第 1 段：協定與往返（可自動化，不需要 Teams）
    │   scripts/simulate_teams.py
    │   或 Microsoft 365 Agents Playground
    ▼
第 2 段：Teams 用戶端渲染（只能人工）
    │   側載到真實 Teams
    ▼
驗收完成
```

### 第 0 步：準備知識語料（乾淨 clone 必做一次）

`data/sources/` 存放公司內部真實知識文件，是 gitignored 的，所以剛 clone 的
repo **沒有任何語料**，Agent Service 會啟動失敗。先用範例語料頂上：

```bash
cp -r data/sources.sample data/sources
```

`data/sources/` 本身被 gitignore，複製過去不會被誤 commit。拿到真實文件後直接
放進同一個目錄取代即可。

### 第 1 段：`scripts/simulate_teams.py`（最快，先跑這個）

在本機同時跑起真實的 Teams Adapter 與一個假的 Bot Framework 服務，送進真的
Bot Framework Activity，並把 Bot **送出去**的訊息攔下來印出。不需要 Teams、
不需要 Azure、不需要 devtunnel、不需要任何憑證。

```bash
# Echo 模式：只需要 Adapter，其他什麼都不用開
uv run python scripts/simulate_teams.py

# 完整 RAG 路徑：另一個 terminal 先 `cd agent_service && uv run rag-agent`
uv run python scripts/simulate_teams.py \
    --agent-url http://localhost:8000/agent/chat

# 頻道情境（會走非串流的單次回覆路徑）
uv run python scripts/simulate_teams.py \
    --agent-url http://localhost:8000/agent/chat --scope channel
```

1:1 私訊 + `--agent-url` 的預期輸出（串流會生效）：

```text
mode=api scope=personal streaming=True

--- 問題 ---
  POST /api/messages -> 200, 6 activity(ies) out
  send   [typing] 已收到你的問題…
  send   [typing] 正在理解你的問題…
  send   [typing] 正在確認問題類型…
  send   [typing] 正在檢索知識庫…
  send   [typing] 正在整理答案…
  send   AdaptiveCard blocks=[...] actions=['👍 已解決', '👎 未解決']
```

檢查點：

- [ ] 每一輪 `POST /api/messages` 都回 `200`。
- [ ] 每一輪都**至少送出一則** activity（沒送就代表使用者那邊是空的）。
- [ ] `--scope personal` 且 `AGENT_MODE=api` 時 `streaming=True`，並看到 5 個
      `[typing]` 進度。
- [ ] `--scope channel` 時 `streaming=False`，只有一則卡片。
- [ ] `/help` 在**兩種 scope** 都回「目前模式：…」而不是去查知識庫。
- [ ] 結尾是 `OK: ... 0 problem(s)`（非 0 會以 exit code 1 結束，可接 CI）。

### 第 1 段（替代）：Microsoft 365 Agents Playground

想要互動式介面時用這個。Teams SDK 自己的 `microsoft-teams-devtools` 已標記
deprecated，官方建議改用
[Agents Playground](https://learn.microsoft.com/en-us/microsoftteams/platform/toolkit/debug-your-agents-playground)。

```bash
cp .env.example .env                          # 若還沒有
cp agent_service/.env.example agent_service/.env
cp -r data/sources.sample data/sources        # 見第 0 步

START_TUNNEL=false ./start.sh        # Playground 在本機，不需要 devtunnel
```

`.env` 至少要改這幾項：

```dotenv
DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS=true
AGENT_MODE=api
AGENT_API_URL=http://localhost:8000/agent/chat
BOT_PUBLIC_BASE_URL=http://localhost:3978
```

`DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS` 是必要的：Playground 不帶真的
Bot Framework JWT，而且**沒有憑證時 `/readyz` 會回 503**，`start.sh` 等不到就
會直接失敗退出。這個旗標**只能用在本機**。

啟動成功的樣子：

```text
[start] 啟動 LangGraph Agent Service：http://localhost:8000
[start] 等待 Agent Service readiness…
[start] 啟動 Teams Adapter：http://localhost:3978
[start] 等待 Teams Adapter readiness…
[start] START_TUNNEL=false，略過 Dev Tunnel。
[start] 全部服務已啟動。按 Ctrl+C 可一起停止。
```

```bash
curl -sS http://localhost:3978/readyz
# {"status":"ready","agentMode":"api","teamsAuth":"ready","ragImages":"ready"}
```

Playground 的 messaging endpoint 指向 `http://localhost:3978/api/messages`。

Playground 與 Adapter 都在同一台電腦上，因此來源圖片可直接走
`http://localhost:3978/rag-assets/...`。這個 HTTP 例外只在
`DANGEROUSLY_ALLOW_UNAUTHENTICATED_REQUESTS=true` 時成立；真實 Teams 與
Cloud Run 仍強制使用公開 HTTPS URL。

### 第 2 段：側載到真實 Teams

第 1 段涵蓋不到的，全部集中在這裡——它們都是 Teams **用戶端**的行為，任何本機
模擬器都無法代勞：

- [ ] Adaptive Card 實際渲染正常（不是純文字或破版）。
- [ ] 來源圖片載得出來（簽章 URL 在 Teams 端可讀）。
- [ ] 👍/👎 按鈕按下去有反應，且後端收到 feedback。
- [ ] **串流在 1:1 私訊真的會動**（進度文字逐步更新，最後被卡片取代）。
- [ ] 串流的兩分鐘上限與使用者按 Stop 的行為符合預期。

詳細的手動測試腳本見下一節。

## 6. 手動測試腳本（僅能在真實 Teams 驗證）

以下項目對應 spec §19 POC 驗收標準中，只有在真實 Teams 用戶端才能觀察到
的部分（第 1、2、12 項），加上 Feedback 按鈕（spec §14）。自動化測試（單
元／整合測試）涵蓋的其餘 §19 項目不在此重複。

### 6.1 前置

- [ ] Teams app 已側載到測試 Team（第 3 節）。
- [ ] Teams Developer Portal 的 bot Endpoint address 指向要驗證的環境
      （Dev Tunnel 或 Cloud Run Adapter URL）。
- [ ] `agent_service` 與（若走 Dev Tunnel）本機 Teams Adapter 皆已啟動且
      `/readyz` 回應 `ready`。

### 6.2 項目 1／2：Teams 可正常與 Agent 對話、服務可部署且可達

1. 在已安裝的 Team 頻道輸入 `@Bot` 加上一句單一 IT 問題，例如：

   ```text
   @Bot VPN 連線一直失敗，錯誤代碼 691
   ```

   - [ ] Bot 在合理時間內（Cloud Run `--timeout=90` 之內）回覆。
   - [ ] 回覆內容非 Echo，而是知識庫／FAQ 產生的實際答案。
2. 切換到 `personal` scope（私訊 Bot），重複一句簡單問候：

   - [ ] Bot 正常回覆（不需要 `@mention`）。
3. 在頻道中傳送一句**未 `@mention`** Bot 的訊息：

   - [ ] Bot 不應觸發回覆（後端不應收到這則訊息的 request）。
4. 若正在驗證 Cloud Run 部署：確認 bot Endpoint address 已指向 Cloud Run
   Adapter URL（不是 Dev Tunnel），且上述對話仍然成功：

   - [ ] 驗證 Cloud Run Adapter 服務可從 Teams 端可達。

### 6.3 項目 12：來源圖片可正常顯示

1. 提出一個已知有對應圖片來源的問題（例如大州系統相關文件內含截圖）。
2. 檢查 Bot 回覆的 Adaptive Card：

   - [ ] 圖片實際渲染出來（不是破圖／空白／逾時）。
   - [ ] 圖片大小在 Teams 卡片內合理顯示（未被裁切或過大）。
3. 等待超過 `RAG_ASSET_URL_TTL_SECONDS`（預設 3600 秒）後，嘗試重新載入
   同一張卡片／同一個圖片 URL（例如重新整理 Teams 用戶端後回看舊訊息）：

   - [ ] 已過期的簽名 URL 不應再次可讀取（確認短效簽章確實生效）。

### 6.4 Feedback 👍/👎 按鈕（spec §14）

1. 提出一個會被 FAQ 或 Knowledge Service 命中的問題，取得回覆。
2. 確認回覆下方（或隨附卡片動作）出現：

   ```text
   這個回答有解決你的問題嗎？
   👍 已解決   👎 未解決
   ```

   - [ ] 兩個按鈕都會顯示（前提：`FEEDBACK_ENABLED=true`，預設值）。
3. 分別點擊 👍 與 👎：

   - [ ] 點擊後有明確的使用者可見結果（例如按鈕消失或顯示已收到回饋）。
   - [ ] Agent Service log 出現 `Feedback recorded: ...` 一行，包含
         correlation ID、conversation ID、issue ID、user ID 與
         `rating`（`up`/`down`），且不含問題原文或答案全文。
4. 將 `FEEDBACK_ENABLED=false` 後重啟 Agent Service，重複步驟 1：

   - [ ] 回覆不再顯示 Feedback 按鈕（`/agent/chat` 回應的
         `feedbackEnabled` 為 `false`）。

### 6.5 記錄結果

每次手動測試建議記錄：日期、測試環境（Dev Tunnel／Cloud Run）、
`agent_service` 與 Teams Adapter 的版本／commit、以上各項目的通過與否，
並保留任何失敗案例的 correlation ID 以便對照後端 log（spec §15）。
