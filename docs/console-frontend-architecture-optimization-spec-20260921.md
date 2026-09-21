# React Console 前端架構與可靠性優化實作規格書

> 日期：2026-09-21  
> 範圍：`console_frontend/`（`/console-v2/`）及必要的前後端契約驗證  
> 性質：實作規格；本文件不代表功能已完成  
> 依據：目前原始碼、測試、`console_frontend/README.md` 與既有 BU UI／UX 規劃  
> 與 `docs/ai-ops-bu-ui-ux-refactor-plan.md` 的關係：該文件定義 BU 任務流與視覺方向；本文件定義目前 React Console 的工程邊界、正確性、權限及驗收方式。

## 1. 決策摘要

保留 React 18、TypeScript、Vite、Ant Design、Refine，以及目前的 monorepo 與 `/console-v2/` 路徑。**不進行一次性重寫、不拆 repo、不為重構而加入新狀態管理框架**。先修復會誤導使用者的操作，再建立一致的資料及權限契約，最後整理導覽、響應式與可及性。

優先級：

| 優先級 | 工作包 | 完成定義 |
|---|---|---|
| P0 | 操作結果可信度 | FAQ、廣播、根因、結案等不再假成功；Golden Eval 按鈕不再宣稱未執行的寫入 |
| P1 | 身分與權限 | 路由、導覽、操作使用同一份 capability 對照；401/403 區分；跨身分資料不殘留 |
| P1 | 資料存取與狀態 | 頁面按需載入；局部失敗不顯示為零或完成；同一資料域只有一個前端權威狀態 |
| P2 | 資訊架構與介面 | 導覽覆蓋正式路由；窄視窗與鍵盤可用；健康狀態不再是靜態綠燈 |
| P2 | 測試與發布閘門 | 重要任務流、權限與失敗情境有自動化驗證；建置資產同步檢查通過 |

## 2. 現況與證據

以下是原始碼可確認的現象；尚未進行實機視覺／效能量測的項目在後文列為驗證工作，而非已發生的 production incident。

| ID | 現況與證據 | 風險 |
|---|---|---|
| FE-01 | `features/dashboard/components/QuickFaqDrawer.tsx` 呼叫 `workbenchStore.quickSaveFaq(...)` 未等待 Promise 即顯示成功並關閉；`BroadcastModal.tsx` 同樣未等待 `setSpikeBroadcast(...)` | 伺服器失敗仍向使用者回報完成；未處理的 rejected Promise |
| FE-02 | `features/triage/components/TriageActionPanel.tsx` 的 `handleAddToGoldenEval` 只有 `message.success`，沒有持久化請求 | 「加入 Golden Eval」是沒有實際效果的操作 |
| FE-03 | `shared/api/workbench/conversationsSlice.ts` 先改本地狀態，再把後端錯誤 `.catch` 後吞掉；`TriageActionPanel.tsx`、`ActionInbox.tsx` 立即顯示成功 | 介面與後端狀態分歧，刷新後可能回復原狀 |
| FE-04 | `app/providers/accessControlProvider.ts` 對未知 resource 回傳 `can: true`；`app/App.tsx` 註冊更多實際路由；`app/providers/authProvider.ts` 將 401 和 403 都視為登出 | 介面與 API 授權不一致；權限不足被誤判為憑證失效 |
| FE-05 | `shared/api/workbench/storeCore.ts` 首次訂閱啟動整批載入；`store.ts` 一次載入五類資料，部分或全部失敗仍 `markLoaded()`；`WorkbenchLoadErrorBanner.tsx` 只提供整批重試 | 不相關資料請求耦合；局部失敗難辨、重試過廣 |
| FE-06 | 同時存在 `app/providers/dataProvider.ts`、各頁直接 `apiClient(...)`、`shared/api/workbench/` 單例 store；部分 API 使用 generated client，部分使用 `any` | 資料擁有權、快取、錯誤和型別契約難以一致 |
| FE-07 | `app/shell/Header.tsx` 只有五個頂部選單，但 `App.tsx` 有二十多個路由；部分路由回退選取「儀表板」；兩個服務狀態標籤寫死；Header `minWidth: 500` | 路由難找、所在位置錯誤、健康訊號誤導、窄視窗擁擠 |
| FE-08 | `features/triage/pages/TriagePage.tsx` 與 `features/knowledge/pages/KnowledgePage.tsx` 固定內容高 760px；前者三欄在 `xs` 疊排但外層仍固定高度 | 小螢幕／縮放下捲動與內容可達性需實機驗證 |
| FE-09 | `shared/auth/session.ts` 無 Bearer token 時預設送出 `SYSTEM_ADMIN` header；後端 `ai_ops_backoffice/auth.py` 在非 dev/test/poc 預設禁止 header auth，部署腳本預設 ENTRA | 不是已證實的正式環境漏洞；需把環境邊界及跨身分清理納入發布檢查 |

現有優點也必須保留：`app / features / shared` 分層、路由 lazy load、generated OpenAPI client、共用 `apiClient`、工作台 slice 拆分、BU 舊 URL 相容與獨立 UI 靜態映像能力。這輪重構不撤銷這些設計。

## 3. 範圍與非目標

### 3.1 範圍

1. React Console 的路由、導覽、權限、身分切換、前端資料流與操作回饋。
2. FAQ、臨時廣播、對話根因／結案、Golden Eval 候選入口及相關 API 契約。
3. 儀表板、分診、知識、工單等工作台頁面的載入／錯誤／空狀態。
4. 窄視窗、鍵盤、焦點、狀態文案與基本效能量測。
5. 對應測試與 CI／發布驗收。

### 3.2 非目標

- 不修改 RAG 檢索、LangGraph、Teams bot 或後端業務語意，除非現有 API 無法支持本規格的真實操作；此時先明確列出缺口與契約，再另行實作。
- 不把 Refine、Ant Design、React Router 全面替換。
- 不遷移至 Next.js，不拆 repo，不新增平行前端。
- 不為消除所有 `any` 而做無關大規模重排；只處理本輪觸及的 API 邊界。
- 不將「FAQ 已儲存」自動宣稱「Agent 已使用新內容」；若後端另有索引、發布或同步狀態，必須依實際回傳呈現。

## 4. 目標分層與依賴規則

目標是讓每個資料域有清楚 owner，同時保持現有入口及 API 相容。建議結構如下；路徑是落地指引，不要求先建立空目錄。

```text
console_frontend/src/
  app/
    App.tsx                    # Providers + route composition only
    routing/                   # Route registry, aliases, guards, navigation metadata
    providers/                 # Refine/auth/data adapters
    shell/                     # Responsive shell, status, user actions
  features/
    triage/
      api/                     # Conversation queries and actions
      hooks/                   # Triage state orchestration
      components/
      pages/
    knowledge/
      api/                     # FAQ/document queries and actions
      components/
      pages/
    operations/ ...
  shared/
    api/                       # HTTP transport and generated OpenAPI client
    auth/                      # Session/token lifecycle
    ui/                        # Domain-neutral UI primitives
```

依賴方向：`app → features → shared`；跨 feature 若是同一業務能力，抽到其真正 owner 或明確的共享業務模組，不讓 `triage`／`knowledge` 長期依賴 `dashboard/components`。例如 FAQ 儲存表單由 `knowledge` 擁有，Dashboard 和 Triage 透過公開入口使用。`shared/ui` 不可反向匯入 feature。

資料規則：

- `apiClient` 只負責傳輸、認證 header、解析、錯誤分類、取消與必要逾時；不得在此放頁面業務狀態。
- 優先使用現有 OpenAPI generated types/client；手寫 adapter 僅處理 generated client 尚未覆蓋或特殊 multipart／輪詢的端點。不要手改 `shared/api/generated/`。
- 同一資源的讀取、更新、重新整理與失敗處理在同一 feature 資料模組定義。Refine `dataProvider` 可以作為 adapter，但不得另外維持一份相互矛盾的快取。
- 僅跨頁共享且需要即時同步的狀態才保留共享 store；純伺服器資料優先由既有 Refine 查詢機制或局部 hook 管理。選定單一策略後逐頁遷移，勿一口氣引入第四套資料層。
- UI component 只接收資料／狀態及操作 callback；不可在顯示元件中隱藏未等待的持久化呼叫。
- 不在 domain API 或 store 中吞下寫入錯誤。需要 fallback 的讀取可回報 `partial`，但寫入必須向呼叫者傳遞失敗。

## 5. P0：操作結果可信度

### 5.1 共通 mutation 契約

所有會改變伺服器資料的按鈕採一致狀態：`idle → validating → submitting → success | error`。成功訊息只在 API 已確認成功後出現。送出中禁止重複提交；失敗時保留表單／選取內容、顯示可理解錯誤及可重試入口，不關閉 Modal／Drawer。表單驗證失敗與網路／伺服器失敗應分開處理，不能用空 `catch` 一概忽略。

若使用樂觀更新，必須具備 rollback、重試衝突處理、測試與明確理由；這輪 FAQ、廣播、根因、結案先採「伺服器確認後更新」以降低錯誤風險。請求成功後只刷新受影響的資料域；不因 FAQ 儲存而無條件重抓五類工作台資料。

| 操作 | 目前入口 | 實作要求 | 驗收 |
|---|---|---|---|
| 新增／修訂 FAQ | `QuickFaqDrawer` | 等待 `quickSaveFaq`；區分「儲存成功」與後續發布／索引完成；錯誤留在表單 | 模擬 5xx 時不關閉、不顯示成功；成功一次提交一次請求 |
| 臨時廣播 | `BroadcastModal` | 等待 `setSpikeBroadcast`；顯示實際生效狀態與到期時間，未確認前不可宣稱已啟用 | 模擬逾時／5xx 時內容保留且可重試 |
| 根因標記 | `TriageActionPanel` | 等待 `setRootCause`，失敗還原／維持舊值並提示 | 刷新後與伺服器一致；失敗不顯示成功 |
| 對話結案 | `TriageActionPanel`、`ActionInbox` | 等待 `resolveConversation`；同一操作共享處理邏輯；失敗不減少 KPI／不移除待辦 | 兩個入口相同；重複點擊不重複寫入 |
| 建立工單 | `EscalateTicketModal` | 保留既有 `await`；補 API 失敗可見錯誤，不將所有例外視為表單錯誤 | 5xx 時 Modal 保持開啟且沒有成功通知 |
| Golden Eval 候選 | `TriageActionPanel` | 先確認後端題庫／候選 API 與審核流程；依正式契約寫入並顯示候選 ID／狀態。若 API 未具備，按鈕應停用或改為明確導向可用流程，**不得顯示已加入成功** | 成功可在題庫查得；失敗或無 API 時不產生假成功 |

文案不得超出後端已證實的結果：例如 `QuickFaqDrawer` 目前的「已同步推送至向量資料庫、Teams 即刻生效」只能在回應或後續狀態可驗證時使用。

### 5.2 實作順序

1. 加失敗測試，固定現有錯誤行為的重現。
2. 修 mutation 的 `await`、錯誤傳播及按鈕狀態。
3. 修 store 中吞錯及本地資料提前變更；確認 KPI 不因失敗漂移。
4. 為 Golden Eval 決定真實 API 契約或移除虛假成功入口。
5. 做一次「成功／403／409／5xx／斷網／重複點擊」手動驗收。

## 6. P1：路由、身分與權限

### 6.1 單一 route/capability registry

在 `app/routing` 定義 route ID、path、導覽分組、顯示名稱、所需 read capability、可用動作及相容 alias。`App.tsx` 路由、Header／側欄選單與 access-control adapter 使用同一來源，不允許三處分別維護同一路由名稱與權限。

**先產生盤點表再填 capability。** 以後端 `/api/capabilities` 回傳及端點 policy 為準，不從頁面名稱猜能力，也不自行發明 capability key。至少盤點 dashboard、triage、knowledge/reviews/releases/sync、tickets、AI evaluations/examples/prompts/models/flags、operations health/issues/routes/costs/budgets/search、governance roles/retention/masking/audit、knowledge analytics/audit，以及所有寫入動作。

預設策略是 fail closed：未映射 route/action 不呈現有權限狀態，開發與測試中要可見地報出缺漏；正式頁面展示適合的「無權限」狀態，不用 404 假裝資源不存在。後端仍是最終授權者；前端隱藏或停用不取代 API 驗證。

### 6.2 認證、授權與資料生命週期

- 私有 route 必須有明確登入檢查與 loading 狀態；未登入導回 `/console-v2/login`，保留經驗證的站內返回路徑。避免認證未完成時先顯示舊資料或 private shell。
- 401：憑證失效，依 Entra／本機模式啟動重新登入流程。403：登入仍有效但操作無權，保留所在頁與其他可用功能，不強制登出。409／412：顯示衝突或版本已變更，要求重新載入；429／5xx：保留輸入並提供安全重試。
- 登出、登入另一身分、tenant／owner scope 變更時，清除 `cachedSession`、共享 server state、workbench store 與相關查詢快取。不得在下一位使用者的畫面顯示前一位的資料；跨 tab 行為需依實際 session 機制驗證。
- `session.ts` 的預設 admin header 僅作受控 dev/test 情境。正式部署需驗證 `authMode=ENTRA`、header auth 未開啟；避免瀏覽器自行聲明的 role 被視為 production 授權。此項是部署檢查，不宣稱現有 production 已遭繞過。
- Header 中的「快速新增 FAQ」等全域操作必須遵守同一 capability；不能只限制頁面、保留未授權全域按鈕。

驗收矩陣至少涵蓋 SYSTEM_ADMIN、AI_ADMIN、KNOWLEDGE_ADMIN、SERVICE_OWNER、ANALYST、VIEWER、AUDITOR，以及無登入；使用後端實際 capability 回應做期望值，測試直接輸入 URL、選單可見性、按鈕、401、403、身分切換。不同角色的實際授權以後端契約為準，不在本文件另定權限政策。

## 7. P1：資料查詢、局部錯誤與更新

### 7.1 查詢切分

將目前 `loadAll()` 五類資料的首次載入改為按頁面／區塊需求：Dashboard 讀 overview 與首屏任務摘要；Triage 讀 conversations；Knowledge 依頁籤讀 documents／FAQs／gaps；Tickets 讀 tickets。若某頁確實需要跨域摘要，仍可並行，但每個來源有獨立狀態。避免一個頁面僅因訂閱 workbench store 就抓完所有資料。

每個資料域需要 `idle/loading/success/error`、資料時間戳及刷新策略。不可把 API 失敗顯示為「0 件」或「目前無待辦」；局部成功顯示已取得的部分，同時標明失敗來源及只重試該來源。成功後資料可留在畫面但標為「可能過期」，避免更新中閃回空白。清單分頁與篩選須明確傳入 API，不以全量拉取後前端過濾掩蓋資料量問題；是否需要新後端 endpoint 先以實際流量與契約驗證。

### 7.2 伺服器狀態一致性

- 為每個 feature 訂定查詢 key／刷新規則；mutation 成功只 invalidates 受影響的查詢，例如 FAQ 寫入刷新 FAQ 清單及相關 overview，不重抓 documents 與 tickets。
- 重複請求應可取消或忽略過時回應，避免舊篩選結果覆寫新結果。對長時間輪詢（文件匯入等）保留現有 idempotency 與進度機制。
- `apiClient` 要有一致的 `ApiError` 分類及呼叫端可選 `AbortSignal`；超時策略依讀取／寫入／長任務區分，不可對非冪等 POST 自動重試。不要把網路錯誤一律包裝成登入錯誤。
- 對 API 的 typed adapter 採增量遷移。`dataProvider.ts` 目前有 `any` 與泛用 `/api/${resource}` fallback；對進入本輪範圍的資源改為明確 endpoint／response mapping，未知 resource 以可診斷錯誤拒絕，不盲發猜測的 URL。
- 保留 `shared/api/generated/` 的產生程序。端點 schema 變更時同步 OpenAPI snapshot／generated client；不得手改生成檔。

### 7.3 Workbench store 退場條件

這不是要求立即刪除 store。按 Dashboard → Triage → Knowledge → Tickets 遷移；每遷移一頁，確認舊 store 不再為該頁維護第二份可變 server state，再移除對應 slice。過渡期間建立明確單向 adapter，禁止同一頁混用兩份可能互相覆寫的快取。最後保留必要的純 UI state（例如目前開啟的 Drawer），不把伺服器資料當作長存單例。

## 8. P2：導覽、響應式、可及性與狀態呈現

### 8.1 導覽

以任務分組呈現所有正式可達功能，而非把超過二十個路由擠入頂欄。建議分組可沿用既有 BU 規劃：「我的工作／分診」、「知識內容」、「品質驗收」、「營運分析」、「系統管理」；實際名稱先與產品／BU 核對。每個深層路由須有正確的上層選取狀態、頁面標題與返回路徑。現有 `/console-v2` alias 與深連結需保持可用；不在 URL 放 token、對話原文或使用者敏感資訊。

Header 固定服務標籤要改為真實 health API 加「最後更新」及 unknown/stale 狀態，或直接移除。不能用硬編碼正常狀態。舊版後台連結在確認 `/` 仍存在且受支援前不得作為主要導覽；若僅相容跳轉，文字應準確表達。

### 8.2 響應式與可及性

- 以 360px、768px、1024px、1440px 寬，以及 200% 瀏覽器縮放驗收。不是要求所有資料表在 360px 展示全部欄位，而是核心任務可完成、沒有被遮擋的主要操作。
- 移除僅靠固定 760px 容器造成的疊欄溢出；窄視窗可切換清單／對話／動作面板，而非三個 100% 高區塊擠在同一固定高度。
- 點擊品牌返回首頁需使用可鍵盤操作的 link/button；Modal／Drawer 開關後焦點回到觸發處；表單錯誤與非同步成功／失敗通知可被輔助工具感知。狀態不僅靠顏色辨識。
- 建立 loading、empty、error、partial、permission denied、stale 六種可區分的 UI 狀態；標題與文案不得承諾實際未實現的「10 秒修訂」「即刻同步」。

## 9. 測試與驗證規格

### 9.1 自動化測試

現有 `npm test` 包含少量路由結構與元件測試，尚不足以保護本規格的高風險流程。每個工作包先補回歸測試：

| 層級 | 必須覆蓋 |
|---|---|
| 單元 | capability registry 映射／未知資源拒絕；401 vs 403；資料狀態轉換；過時回應不覆寫；logout 清快取 |
| 元件 | FAQ、廣播、根因、結案、工單的成功／失敗／重複點擊；錯誤時保留輸入；Golden Eval 真實結果或禁用狀態 |
| 整合 | 角色直連 URL 與導覽；局部 API 失敗；頁籤切換與按需請求；身分切換不洩漏先前資料 |
| 瀏覽器 E2E | 登入→分診→修正 FAQ→確認結果；403 後仍可使用其他功能；窄視窗可完成核心任務；刷新／深連結可用 |

測試不可只檢查 toast 文字；必須斷言 API 寫入、資料刷新、失敗 rollback／保留、以及後端可查的持久結果。需要 Golden Eval API 時以其正式狀態／ID 作斷言，不以假資料通過。

### 9.2 品質閘門與量測

每個 PR：檢查 diff、`npm test --prefix console_frontend`、TypeScript typecheck、相關建置與 OpenAPI freshness；發布前依 `console_frontend/README.md` 執行 `scripts/sync_console_v2.py --check`。不要直接改生成的 `static/console-v2/` 資產；需要更新時用既有同步腳本。跨資料契約變更補後端 consumer／contract tests。

效能先記錄 baseline 再設閘門，避免捏造現有數字。至少量測：登入後首屏可用時間、首屏 API 請求數、各主要頁切換時間、實際傳輸量、長任務感知進度、操作完成時間及錯誤率。比較同一測試環境／角色／資料量下的改造前後；若請求數或首屏時間退步，需說明原因與修正計畫。路由懶載入及 vendor chunking 保持，避免因共用大模組使所有頁面下載治理／評測程式碼。

## 10. 分階段實施與交付

### Phase 0：基線與契約盤點（先做）

- 列出每條正式 route、API endpoint、HTTP method、後端 capability、頁面 owner、資料域及是否需保留 alias。
- 對 P0 操作記錄目前請求／回應／持久化狀態；確認 Golden Eval 是否有可用正式 API。
- 建立測試角色、最小權限 fixture 與瀏覽器基線；記錄前端網路請求及主要頁面截圖。
- 交付：route/capability/API 對照表、baseline、尚無 API 的缺口清單。未知項不得當成已完成。

### Phase 1：操作可靠性（P0）

- 修 FAQ、廣播、根因、結案、工單及 Golden Eval 候選入口。
- 統一可見錯誤與防重複送出；覆蓋成功、失敗、競態測試。
- 交付：沒有假成功、沒有吞掉寫入錯誤、每個操作的持久結果可核對。

### Phase 2：認證與權限（P1）

- 建立 route/capability registry，接上導覽、路由與按鈕；區分 401／403。
- 明確保護 private route，清除跨身分資料；確認 production auth 模式。
- 交付：角色矩陣與直接 URL 測試通過；未映射資源 fail closed。

### Phase 3：資料域遷移（P1）

- 先 Dashboard／Triage，再 Knowledge／Tickets；逐頁按需載入、局部錯誤與精準刷新。
- 從頁面移除第二份 server state；保留相容 facade 直到呼叫者完成遷移。
- 交付：各頁只請求需要的來源；部分失敗不顯示假零；身分切換不殘留資料。

### Phase 4：介面與發布（P2）

- 重整導覽與 Header，完成響應式及鍵盤驗收；移除靜態健康綠燈。
- 執行 E2E、typecheck、測試、建置資產同步檢查及效能前後比較。
- 交付：可部署的 React Console 與驗收報告；不要求後端系統／RAG 另行重構。

每階段可獨立合併、可回退。若後端契約尚未支援某項 UI 操作，先停用虛假入口並記錄依賴，不應阻塞其他可靠性修復，也不能用前端假成功充數。

## 11. 整體驗收條件

1. 所有宣稱成功的寫入都經後端確認；錯誤時沒有成功 toast、沒有不可逆的本地假狀態。
2. Golden Eval 候選操作有真實持久化及可查結果，或明確不可操作且不宣稱成功。
3. 所有正式路由與寫入動作都有經後端核對的 capability；未知資源不預設放行；403 不登出。
4. 首次進入頁面只載入該頁所需資料；局部失敗不被誤認為零資料；失敗來源可單獨重試。
5. 登出／換身分後不顯示上一身分的工作台資料；正式部署不接受瀏覽器自稱管理員 header。
6. 主要路由在導覽中可找到且 active state 正確；窄視窗、200% 縮放與鍵盤可完成主要任務。
7. 固定健康綠燈消失，或由真實狀態與時間戳驅動；UI 文案不超出後端已確認的生效階段。
8. 前端測試、typecheck、相關 API contract test、資產同步檢查通過，且有改造前後效能紀錄。

## 12. 風險與決策點

| 決策點 | 處理原則 |
|---|---|
| Golden Eval 真正寫入 API 尚未確認 | Phase 0 對照後端；無 API 則禁用或移除虛假入口，另列後端工作，不擅自改題庫流程 |
| 後端 capability 粒度不足 | 列出缺口與最小後端契約；不以角色名稱硬編碼替代 capability，也不放寬後端授權 |
| Refine 與現有 store 共存 | 逐頁確立唯一 owner；只允許短期單向相容 adapter；每階段刪除已遷移的重複狀態 |
| 舊 `/console-v2` URL 與靜態產物 | 路由 alias、深連結及 `scripts/sync_console_v2.py --check` 納入回歸；獨立 UI image 與後端內嵌資產均需保持可用 |
| 視覺重構擴大範圍 | 以核心任務與實測問題為準；不做無關換色、動畫、元件庫替換 |

最終優先判斷：**先讓每個操作值得信任，再讓資料與權限只有一個答案，最後改善找得到、看得懂、用得順的介面。**
