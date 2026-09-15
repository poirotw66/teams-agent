# AI Ops Console 工作流整合與前端漸進遷移規格

| 項目 | 內容 |
|---|---|
| 版本／日期 | v1.0／2026-09-14 |
| 狀態 | Proposed；可供排程、拆票及驗收，非完成實作聲明 |
| 適用專案 | teams-agent |
| 程式盤點基準 | `7e62bb35552ad745427ab0282682819353d1e530` |
| 討論來源 | [管理後台方向比較](chatgpt-conversation://6aa80350-dc54-83e9-a2aa-e149ca0d1ef4) |
| 產出邊界 | 本次只新增規格；不修改應用、不搬移資料、不部署 |
| 新里程碑 | W0–W6，避免與既有 Phase 0–3、M0–M4、U1–U4 混淆 |

## 1. 決策與最優先行動

下一階段將現有後台發展為以工作完成為核心的 AI Ops Console。保留 FastAPI、Agent Runtime、RAG、知識生命週期、評測、治理及權限領域服務；前端優先採 React、TypeScript、Refine 與 Vite，以小範圍驗證後逐步替換自製基礎設施。

產品工作與技術遷移分別驗收。四條工作流是產品目標，換框架是降低長期維護成本的手段；首頁換成四張卡片或所有頁面改成 React 均不足以宣告成功。

建議執行順序：

1. **W0：確認真實流程與 API 契約。** 盤點現有 BU UI、示範入口、權限、任務來源及尚缺的證據連結，建立舊版任務基準。
2. **W1：限時完成 `/console-v2/` 技術試點。** 用登入、權限、即時工作首頁、Health 唯讀頁驗證新前端與既有後端整合，保留舊 UI。
3. **W2：交付第一條端到端閉環。** 從真實品質案件進入文件修正、審核、發布、確認 Agent 生效、驗收與觀察，回到案件；第一輪容許跳到既有編輯器，但不丟上下文。
4. **W3–W5：以工作流逐步擴大遷移。** 再補知識營運全貌、AI 變更治理、平台治理與其餘頁面。
5. **W6：在角色 UAT、回退演練與功能對照通過後，才切換預設入口並退場舊 UI。**

不採用先搬完全部唯讀頁、再搬全部設定頁、最後才碰工作流的長序列。唯讀試點限縮到能驗證技術風險的程度，接著優先交付使用者可完成的真實工作。

## 2. 現況證據與既有規格關係

以下為本機原始碼與測試檔的靜態觀察；本輪未啟動服務、執行測試或核對正式環境。測試存在不代表本輪已通過。

| 可確認事項 | 原始碼依據（相對 repository root） | 本案決策 |
|---|---|---|
| Classic 導覽已有三工作區，並非單一扁平選單 | `agent_service/src/ai_ops_backoffice/static/js/app/workspaces.js` | 四條流程建立在現有分組之上，不重新發明全部 IA |
| 已有 BU route aliases、深連結、返回上下文與 dirty-state 防護 | 同目錄 `routeRegistry.js`、`navigation.js`、`returnTo.js` | 將行為列入新舊相容契約 |
| `workHub.js` 直接使用 `vpnWorkItems()` 與準備好的故事 | `static/js/views/workHub.js`、`static/js/demo/vpnStory.js` | 即時任務首頁是優先缺口；示範不可作為真實工作完成證據 |
| 示範也連到案件、對話、文件清單 | `static/js/views/quality.js`、`conversations.js`、`contentLists.js` | 盤點及隔離所有示範分支，不只替換首頁 |
| 權限由 capability 組合與 knowledge bridge 開關決定 | `static/js/app/capabilities.js` | Refine access provider 需適配兩組 capability，不能只看角色名稱 |
| 已有統一知識 bridge `/api/knowledge` | `knowledge_bridge/routes.py`、`delegation.py`、`capabilities.py` | 保留代理、可信身分及資料隔離，不直接從瀏覽器呼叫 Portal |
| 已有案件建立文件草稿、FAQ 草稿、內容關聯、評測關聯查詢與觀察更新 | `routers/quality_routes.py` | 延伸既有 API，缺口驗證後才新增 |
| 案件具備 assignee、due time、etag、觀察指標及結案欄位 | `quality_domain/models.py` | 不另建第二套案件或任務狀態機 |
| Prompt、Model、Flag 已有版本生命週期，另有 eval／gate 領域 | `governance_domain/models.py`、`evaluation_domain/` | 共用工作流外觀，領域語意及狀態仍分開 |
| 登入端已有 Entra bearer 驗證，舊 client 另有開發 HEADER 模式 | `entra_auth.py`、`static/js/api.js` | 正式環境不把 client 傳入角色視為授權 |
| Backoffice 容器目前以 Python image 打包來源 | `agent_service/Dockerfile.backoffice` | 新增前端建置階段，不把 Node 開發伺服器帶到正式環境 |

### 2.1 與既有文件的分工

| 文件 | 保留的契約 | 本文件新增或調整 |
|---|---|---|
| [BU UI／UX 重構](ai-ops-bu-ui-ux-refactor-plan.md) | 已定義的任務命名、BU 清單／詳情、returnTo、舊連結相容 | 在既有成果之上加入四條流程與 React 遷移；不重做 U1–U4 |
| [知識介面整併](ai-ops-knowledge-portal-consolidation-spec.md) | 單一身分、bridge、知識資料主權、發布與生效區分 | 本案另開前端遷移範圍，原整併案排除框架遷移的範圍限制不擴張到本案 |
| [Phase 2 品質閉環](ai-ops-backoffice-phase-2-quality-loop-spec.md) | 案件、內容、觀察及品質改善領域 | 補跨頁上下文、證據可見性與可操作閉環 |
| [Phase 3 AI 治理](ai-ops-backoffice-phase-3-ai-governance-spec.md) | Candidate、核准、啟用、回退及稽核政策 | 提供一致工作流入口，不藉 UI 改寫政策 |
| [Golden Eval 四階段](golden-eval-set-four-phase-spec.md) | 題庫、manifest、執行與評分契約 | 將結果掛回工作流程，不另建評測引擎 |
| [Production readiness](ai-ops-production-readiness-refactor-spec.md) | 生產可靠性及資料層約束 | 僅處理本案新增 API、資產部署與遷移風險 |

規格與原始碼不同時，以原始碼描述現況、以驗收條件描述目標。既有審核、自審例外、資料保存與發布政策沿用，不因導覽整合而放寬或默默收緊；若閉環所需證據尚無後端保護，列為明確新增需求。

## 3. 目標、範圍與非目標

| ID | 必達成果 | 完成判定 |
|---|---|---|
| G01 | 登入即可找到真實下一步 | 首頁資料來自授權範圍內的實際來源，無示範混入 |
| G02 | 四條工作流可持續操作 | 刷新、返回、跨新舊頁後仍能定位原工作與版本 |
| G03 | 改善有證據 | 發布、runtime 生效、eval、觀察與結案均可分別查證 |
| G04 | 前端共通成本下降 | 新頁共用表格、表單、錯誤與權限 adapter，不複製自製 routing／fetch 邏輯 |
| G05 | 不退化 | 既有功能、角色、深連結及 API 仍通過相容矩陣 |
| G06 | 可漸進切換與回退 | 每一遷移批次可獨立關閉，舊 UI 仍能讀寫共用資料 |

納入：工作首頁、流程入口、案件詳情、上下文與證據、前端平台、必要的聚合讀取契約、相容路由、建置部署、UAT 與回退。

不納入：重寫 Agent／RAG、替換資料庫、低代碼平台導入、通用 BPM 引擎、另建 ITSM 工單系統、自動核准或自動發布、全面修改 RBAC、只為視覺效果的品牌重設計。FAQ 與文件仍是不同內容類型，不能自動互抄；分類正反例與 Golden 題庫不能互相冒充。

## 4. 使用者與權限原則

| 使用者 | 首要工作 | 建議預設位置 |
|---|---|---|
| Knowledge Admin／BU 內容維護者 | 待辦、草稿、退回修正與知識維護 | 我的工作 |
| Service Owner | 分派、觀察、結案與改善成效 | 我的工作／團隊範圍 |
| AI Admin | Candidate、eval、gate 與版本啟用 | AI 變更與驗證 |
| System Admin | 服務異常、成本、執行與治理 | 平台營運 |
| Analyst | 成效查詢與問題定位 | 平台營運／分析 |
| Auditor | 版本、核准與操作證據 | 平台營運／稽核 |

角色只是首頁預設偏好；導覽、資料、動作均依 server capability 與實體資料範圍決定。使用者可儲存自己有權限的預設位置。只有案件讀取權時，不因此取得對話全文、Prompt 原文或評測資料。

聚合資料必須先授權再計數、分頁及排序。知識權限還需確認 bridge 可用；無權限不暴露標題、存在性、數量或被遮罩前摘要。前端登入完成且 capability 載入前採 deny-by-default，不短暫顯示管理者選單。

## 5. 資訊架構與頁面契約

### 5.1 一級入口

以「我的工作」作為跨流程首頁，四條工作流作為主要工作區。搜尋位於共用頂欄；個人偏好與說明位於次要選單。每個流程只在內部顯示當前角色可用的頁籤。

| 工作區／新 URL 提案 | 子頁 | 既有功能歸屬 |
|---|---|---|
| 我的工作 `/console-v2/work` | 待我處理、待我審核、追蹤中；有權者切團隊 | workHub 與各來源待辦 |
| 知識營運 `/console-v2/knowledge` | 文件、FAQ、待審、發布與生效、同步、內容成效 | contentHub、contentLists、knowledgePortal、knowledgeWork、knowledgeReviews、knowledgeReleases、faq、knowledge、sync、knowledgeAudit |
| 問題改善 `/console-v2/improvements` | 案件、回饋、知識缺口、相關對話 | quality、conversations、gaps；issues 分析可作來源連結 |
| AI 變更與驗證 `/console-v2/changes` | 候選、測試、驗收、核准與啟用、版本歷史 | prompts、models、flags、evaluations、examples、release gate |
| 平台營運與治理 `/console-v2/operations` | 總覽、健康、成本／預算、問題／處理方式、權限、保存／遮罩、稽核 | overview、health、costs、budgets、issues、routes、roles、retention、masking、audit |

同一實體只保留一個 canonical 詳情頁，可從不同流程進入；例如品質驗收既可從案件開啟，也可從 AI 變更開啟，不建立兩套驗收結果。全域搜尋 `search` 保留可分享結果頁。知識稽核作知識流程的來源篩選檢視，不假設它與全域 audit 已是同一儲存來源。

### 5.2 我的工作

首頁標題使用「今天要處理什麼」，先顯示責任範圍與待辦，再顯示最多四個流程摘要。四個數字僅代表各自可見工作，不跨來源相加冒充總案件數。

每列包含：工作標題、來源類型、負責人、目前階段、等待時間、明確下一步、資料更新時間。主要動作只能有一個，例如「補齊草稿」「審核」「確認生效」「查看驗收」；其他動作收在次要選單。

- 「待我處理」限確實指派給自己的可執行工作；未指派案件放團隊未分派清單。
- 「待我審核」依實體審核權及政策決定，不把所有 `WAITING_REVIEW` 案件視為自己可審。
- 「追蹤中」包含已授權且符合追蹤規則的觀察案件、執行中作業及待生效發布；追蹤規則須在 UI 說明，不等同全域所有工作。
- 以來源類型、來源 ID、工作種類組成穩定 key；同一工作的分類優先順序為待審核、待處理、追蹤中。不同工作即使屬同一案件仍可分列。
- 清單與 badge 使用相同篩選及 snapshot；沒有精確 total 時不以當頁長度冒充總數。
- 無資料顯示 0；服務失敗顯示「暫時無法取得」及 retry；無權限不顯示來源；舊快取必須標示時間。
- 有 `target_due_at` 才可稱逾期；其他只顯示等待時間。
- VPN 故事另置示範入口，固定顯示「預先準備的示範資料」；正式工作清單、統計、eval 與稽核不得混入。

### 5.3 共用工作詳情

頁首呈現工作名稱、目前階段、負責人與下一步。主區放問題／內容／diff，旁區放證據與時間線；小螢幕改為上下排列。每一步顯示「完成、進行中、受阻、不適用、未知」之一，並能說明依據。

流程圖只是由領域資料推導的導覽，不可當成可任意點擊的狀態修改器。缺少權限、前置資料或來源故障時，動作需顯示具體原因與可採取的下一步。

所有頁面具備 loading、empty、partial、error、forbidden、stale 狀態。表單保留失敗輸入；離開未儲存草稿需攔截；mutation 使用 pessimistic 更新，高風險操作成功後才顯示完成。

## 6. 四條工作流與完成條件

### 6.1 知識營運

`建立／同步 → 編修 → 驗證 → 審核 → 發布 → 確認 Agent 生效 → 追蹤成效`

1. 從真實文件或 FAQ 建立工作，保留來源、owner、版本及案件關聯。
2. 文件使用既有草稿、附件與驗證服務；FAQ 沿用自己的版本與發布規則。
3. 審核頁呈現 diff、驗證結果與來源；核准規則依現行 policy，不假設所有角色都能自審或均不可自審。
4. 發布完成顯示 immutable release 及 artifact／manifest 證據；發布成功不能顯示「員工已看到」。
5. runtime 回報已套用目標版本才顯示生效；部分實例生效、版本未知或 reload 失敗，均不能顯示全面成功。
6. 用生效後時間窗查看使用與品質成效；沒有流量時顯示樣本不足。

例外：同步失敗可重試單次工作；審核退回返回草稿；發布成功而 reload 失敗只重試套用，不重複發布；回退選擇既有版本並留下稽核。

完成條件：目標內容與審核可追溯、發布與 runtime 證據完整、可查成效。若該內容不需 reload，必須由來源服務提供不適用理由，不能由前端猜測。

### 6.2 問題改善——第一條交付閉環

`回饋／對話 → 建立或合併案件 → 查證與根因 → 內容／AI 修正 → 驗證 → 觀察 → 結案`

第一輪支援「真實品質案件 → 文件修正」；FAQ 和 Prompt 修正分支分別在 W3、W4 完整化。未遷移分支仍可從 canonical 案件進入舊功能。

| 既有案件狀態 | 流程呈現 | 要求 |
|---|---|---|
| `NEW` | 待分流 | 顯示來源及影響，支持指派與合併 |
| `TRIAGED` | 已確認方向 | 記錄問題、根因假設及處理責任 |
| `IN_PROGRESS` | 修正中 | 關聯既有或新建內容／Candidate，不靠複製 ID |
| `WAITING_REVIEW` | 等待審核或驗證 | 顯示實際阻塞物件及其負責人；案件狀態本身不代表內容已送審 |
| `OBSERVING` | 已進入觀察 | 顯示修正版本、生效證據、eval 與觀察起點 |
| `RESOLVED` | 已驗證結案 | 記錄核對證據、結果、操作者與結案理由 |
| `WONT_FIX`／`DUPLICATE` | 有理由終止 | 必填理由；重複案件指向 canonical 案件 |

本表是顯示映射，不新增合法 transition。每個狀態切換仍需領域服務判定。W0 對照現行 transition 規則，W2 僅補不足的證據前置條件。

對「已修復」結案，後端必須核對：修正物件／版本、適用的發布與生效證據、同一目標的完成 eval／gate、觀察結論。合理不適用的項目須記錄理由及執行者權限。`WONT_FIX`、`DUPLICATE` 不套用發布要求，也不計入修復成功率。

建議預設觀察窗為生效後 7 天且至少 30 筆相關有效樣本；這是產品初始值，W0 由 Service Owner 依實際流量校準並版本化。樣本不足維持觀察或記錄經授權的人工結案理由，不能宣稱統計改善。前後比較保留 owner scope、分類規則及分母，期間或分類不同須明示。

例外：建立草稿成功但案件關聯失敗時顯示可恢復狀態，重試連結原草稿，避免產生孤兒或重複草稿。根因發現不同修正方向時保留原證據並新增關聯；不覆蓋歷史。

### 6.3 AI 變更與驗證

`Candidate → Sandbox／靜態檢查 → Eval → Gate → 核准 → Canary／啟用 → 監控／回退`

- Prompt、Model、Flag 保留各自 ID、schema 及 `DRAFT → CANDIDATE → EVALUATED → APPROVED → CANARY → ACTIVE` 等既有生命週期；不新增一個替代所有版本的「change」主資料庫。
- 候選內容變更即產生新版本／hash，舊 eval、gate 與核准不可自動沿用。
- Sandbox 與正式 eval 明確分開；準備好的示範結果、fixtures、incomplete 或 failed run 均不得當成真實完成評測。
- 比較畫面顯示 baseline、candidate manifest、dataset／scorer 版本及執行環境。不同基準不能直接呈現為改善百分比。
- Gate 與 promote 必須由 server 在操作當下重驗同一目標、政策版本、必要核准及最新允許條件；UI 的可點擊狀態不是通行證。
- Canary／monitor／rollback 依既有治理能力；未實作的能力需標示不可用並列領域缺口，不能以動畫模擬已啟用。

完成條件：每個 Active 版本可追至候選、有效 eval、gate、核准及啟用紀錄，且可用既有 immutable 版本回退。

### 6.4 平台營運與治理

`監控 → 定位異常／成本來源 → 進入既有處理動作 → 驗證恢復 → 留下稽核`

Health、Costs、Budgets、Routes／Issues 提供範圍一致的 drill-down；共享期間、環境與 owner filters。健康異常與預算告警是不同來源，無法取得者顯示 unknown，不一律判為健康。

處理動作連到已有的預算、執行作業、AI 設定或權限政策。若服務沒有可執行修復 API，僅提供 runbook 及後續驗證入口；本案不額外打造通用 incident 系統。

Roles、Masking、Retention 與 Audit 作為治理子頁；所有高風險寫入維持既有審核與 audit 原則。恢復成功須依新的觀測資料確認，不依「已按重試」判斷。

## 7. 前端架構與框架決策

### 7.1 技術選擇

首選 React + TypeScript + Refine + Vite，以單一成熟元件庫供應表格、表單、對話框及通知。W1 預設試用 Ant Design，沿用現有 Teams 色彩與繁中命名；詳細 patch 版本、React／router／UI integration 相容組合在 W1 固定於 lockfile，不在本文件宣稱尚未驗證的版本組合可用。

Refine 使用 dataProvider、authProvider、accessControlProvider 與 routing 整合；這些抽象可適配既有 API。Refine 並不會替本案實作業務審核、可靠發布或知識編輯器，這些仍由既有領域及應用程式負責。依據：[Refine providers](https://refine.dev/core/docs/guides-concepts/general-concepts/)、[Data Provider](https://refine.dev/core/docs/data/data-provider/)。

| 選項 | 本案取捨 |
|---|---|
| 持續全用原生 ES Modules | 初期變更小，但需繼續維護 routing、表單、資料狀態與共通互動；作 W1 失敗時的短期延續方案 |
| React + Refine | 優先選擇；以 adapters 整合現有非標準 API，將領域 command 保持明確 |
| React 配 routing／query／UI 套件自行組裝 | 若 Refine adapter 成本過高的退路；要有實測證據才增加自製整合 |
| 全面低代碼重建 | 不列本輪選項；既有編輯、eval、gate 及版本流程仍需大量客製，不值得同時搬平台與領域 |

W1 通過條件：Entra／scope、兩組 capability、真實待辦、Health、深連結、錯誤、建置及回退全部可驗證；不需為 Refine 把既有 API 全改成通用 CRUD。試點超過 5 個工程日仍卡在 provider 適配時，記錄具體障礙並停止擴大遷移，先以既有 UI 交付 W2 所需產品能力。框架採用不阻塞閉環交付。

### 7.2 程式與責任邊界提案

```text
console_frontend/
  src/app/              # router、providers、shell
  src/features/work/
  src/features/knowledge/
  src/features/improvements/
  src/features/changes/
  src/features/operations/
  src/shared/ui/        # 共用表格／表單／狀態模板
  src/shared/api/       # generated types、resource adapters、commands
  src/shared/workflow/  # context、evidence 呈現，不持有領域真相
  tests/
  package.json

agent_service/src/ai_ops_backoffice/
  routers/              # 必要的新 console 聚合讀取
  existing domains/     # 繼續負責授權、狀態、交易及稽核
  static/console-v2/    # 建置產物，禁止人工修改
```

建議由 FastAPI 同源提供 `/console-v2/` 與 `/api/*`。開發時 Vite 代理 `/api`；正式不依賴 Vite dev server、不新增不必要的跨域認證。Vite 提供 manifest 與後端靜態資產整合方式，供建置採用：[Backend Integration](https://vite.dev/guide/backend-integration)。

`dataProvider` 僅統一各 resource 的回應外形、分頁、排序、篩選及錯誤；發布、transition、promote、reload 使用具名 command client，不把 action 偽裝成一般 update。後端未支援某種 filter 時應顯示限制或補後端，禁止只過濾當頁卻宣稱搜尋全部。

Refine query cache 作為 server-state 單一來源；UI store 僅保存面板、偏好及未提交輸入。高風險 mutation 不自動重試、不 optimistic；完成後精確 invalidate 受影響清單、詳情與待辦。登入／租戶切換清空整個使用者 cache。

## 8. 工作上下文、資料與 API 契約

以下 `/api/console/*` 與欄位均為**提案**，不可當作目前存在。W0 先對照 OpenAPI 與既有回應，能直接重用者不另造同義 endpoint。

### 8.1 既有資料與新讀取投影

| 概念 | 真實來源 | 本案新增內容 |
|---|---|---|
| 品質案件 | `QualityCase` | 缺少時補證據關聯；沿用 `case_id`、`etag` |
| 文件／FAQ／release | 各自領域與 knowledge bridge | 跨來源顯示及版本引用，不複製內文 |
| Candidate／eval／gate | governance 與 evaluation 領域 | 統一呈現連結與有效性，不建立第二套狀態 |
| 工作項目 `WorkItem` | 授權後的領域查詢 | 可重建 read projection，不另設可修改的工作狀態 |
| 流程上下文 `WorkflowContext` | 路由＋經 server 授權的實體 | 原工作、返回位置及關聯參照 |
| 證據 `EvidenceRef` | 可追溯來源紀錄 | 必要時以 typed relation 保存關聯，不快取敏感全文 |

`WorkItem` 最小欄位：`key`、`workflow`、`source_type`、`source_id`、`title`、`owner_unit_id`、`assignee_id`、`source_status`、`step`、`next_action`、`blocked_reason`、`due_at`、`updated_at`、`revision`。`next_action` 由允許的 action ID 與 route descriptor 組成，不能接受任意可執行 URL。

`EvidenceRef` 最小欄位：來源種類、來源 ID、版本／hash、與目標的關係、發生時間、取得時間及有效性。有效性為 `valid | stale | unknown | revoked`；以來源重查結果為準。若新增 relation 儲存，key 包含可信 tenant、來源／目標型別與 ID，寫入驗證兩端權限及版本，刪除／保存政策跟隨來源，避免產生旁路資料庫。

`WorkflowContext` 使用 `workflow`、`root_type`、`root_id`、`return_route`、白名單 filters；不在 URL 放對話全文、token、Prompt 或敏感搜尋內容。URL 傳入 tenant／owner 不具授權效果。返回 route 必須限制同源及允許路由，拒絕外部、javascript scheme 和遞迴 returnTo。

### 8.2 聚合 API 提案

| Endpoint | 契約 |
|---|---|
| `GET /api/console/work-items` | `bucket`、`workflow`、授權 scope、cursor、limit（預設 25、最多 100）；穩定排序及 opaque cursor |
| `GET /api/console/work-summary` | 回傳相同 filters 的計數、來源健康、snapshot、產生時間；不能只數第一頁 |
| `GET /api/console/workflows/{kind}/{id}` | 授權後的原始實體參照、步驟、允許動作、阻塞及可見證據；kind 必須 allowlist |

清單回應包含 `items`、`next_cursor`、`total`（未知為 null）、`snapshot_id`、`generated_at`、`partial`、`sources`。summary 與清單可帶同一 snapshot；若來源不支援一致 snapshot，明示 eventual consistency、時間差及計數可變，不能保證假一致性。

來源狀態為 `ok | unavailable | stale`，不回傳使用者無權知道的來源描述。某來源故障時回傳其他合法結果與 partial；若沒有任何可用結果且是服務故障，回 503，不能回空成功。不能把 exception 吞掉轉成零待辦。

初期採 request-time 聚合與短時間、依 actor scope 隔離的 cache，避免新建同步平台。各來源設 timeout、並行上限及 circuit behavior；禁止無上限抓取全部結果後在瀏覽器授權或排序。跨來源 cursor 必須綁定 filters、actor scope 與版本，拒絕其他身份重用。

### 8.3 寫入、衝突與非同步

繼續使用已存在的 `/api/quality-cases/{case_id}`、`/transition`、`/content`、`/document-draft`、`/faq-draft`、`/observation/refresh` 及各 domain commands。不新增可直接修改任意步驟的 generic workflow transition。

- 版本衝突沿用 `expected_etag`／`expected_case_etag`；409 呈現最新版本及使用者輸入，不默默覆蓋。
- 有副作用的 command 如需新增 idempotency，key scope 包含 tenant、actor、action、target 與 payload hash；相同 key／payload 回原結果，不同 payload 拒絕。先核對已有領域實作再補缺口。
- 發布、評測、reload 等長工作取得 operation／run ID 後顯示 pending；新非同步契約用 202 與查詢位置，既有回應由 adapter 對應，不強迫全面改版。
- 斷線後先查 operation 狀態，不直接再送。可恢復作業由後端持久化；切換頁面不終止已接受的工作。
- 新 job 讀取採 2、5、10 秒退避，頁面隱藏暫停前端 polling，恢復時立即重查；重試次數有限且顯示人工重試入口。
- 共用 error 外形：`code`、安全 `message`、`correlation_id`、`retryable`、可選 `field_errors`；adapter 相容既有 FastAPI detail 及 bridge error。
- 401 進重新登入；403 不重試；404 使用不洩漏存在性的訊息；409 保留輸入；422 指向欄位；429 尊重 Retry-After；5xx 顯示安全重試。

## 9. 身分、稽核與安全邊界

新前端沿用 server 的 Entra 驗證與可信 ActorContext；W1 驗證現行登入、續期及登出流程，不僅測手動貼 token。HEADER 模式只供顯式本機／測試設定，正式不得以 sessionStorage 中的 role 代替 Entra claim。

`authProvider` 與 `accessControlProvider` 分工：前者處理登入生命週期，後者適配 `/api/capabilities` 的一般／知識權限；server 仍在每個 read／write 重新檢查。具體 token 保存及 SSO callback 沿用可驗證的現有方式；若不足則列 W1 auth 子項，不另開未評估的認證架構。

已取得的 capability 會失效：403 後重新整理 capability 並移除失效資料，保留未提交內容前先判斷是否仍可見。cache key 至少綁定 principal、可信 tenant、scope 與 filter；登出清除快取及 session 資料。

高風險 command 的稽核沿用既有 fail-closed 政策；client activity event 不可代替 domain audit。每個新 command 需有 actor、scope、target/version、action、時間、結果與 correlation ID；不能記錄 secret 或未遮罩對話。跨服務 trace 只傳可信 context，瀏覽器不能提供 delegation secret。

## 10. 遷移、部署與回退

### 10.1 新舊並存

新增 server-controlled `console_v2_enabled` 與 route／cohort allowlist 提案，名稱與既有 `bu_ui_shell_v1` 分開；開關只控制路由選擇，不授予資料權限。舊入口在 W6 前持續可用。

遷移登錄表每筆包含舊 view／alias、canonical 新 URL、filter mapping、目前 owner（legacy／v2）、角色驗收、回退位置。W0 從 `workspaces.js`、`routeRegistry.js` 與 main routes 匯出完整清單，而非手寫少數頁即稱完整相容。

legacy hash 由瀏覽器 adapter 解析，因為 server 收不到 `#` 後內容。未遷移頁在同分頁進入舊 shell，使用已有安全 returnTo 傳回根工作；新舊頁皆重新授權，不用 iframe 或將舊 DOM controller 掛進 React 生命週期。

每個功能同時只有一個 canonical 實作作為預設寫入入口，但新舊 UI 使用同一領域 API。相容期允許舊 URL 操作；不能因導覽切換形成第二份狀態或資料同步需求。

### 10.2 建置與發布

- 在 `agent_service/Dockerfile.backoffice` 加 Node build stage，以固定 lockfile 安裝及建置，再複製產物到 Python runtime；正式 runtime 不需 Node。
- `deploy/cloudbuild-backoffice.yaml` 納入新前端輸入、快取與建置失敗 gate；維持其他服務部署責任。
- Vite base 為 `/console-v2/`；FastAPI 僅對此 prefix 的合法頁面提供 SPA fallback，`/api/*`、缺失資產及不存在資源保持正確錯誤碼。
- HTML 不長期快取；具 hash 的資產可 immutable cache；跨版部署保留上一版必要資產，避免開啟中的 tab 取不到 chunk。
- artifact 包含版本、commit 與前後端契約版本；CI 驗證打包後深連結、刷新、缺失資產及舊首頁。
- server secret 不進 `VITE_*` 或 JS bundle；執行環境與非秘密公開設定明確區分。

### 10.3 切換與回退條件

依序 local／測試、指定內部角色、小範圍正式 cohort、預設新入口。每次擴大前檢查權限隔離、核心 command、來源錯誤及任務完成率。

立即回退觸發：越權或跨 scope 洩漏、發布／結案證據錯配、重複副作用、登入不可用；一般新前端錯誤率或核心任務成功率退步，先停止擴大並由 owner 判斷。不能為了完成遷移繞過既有領域保護。

回退方式為關閉對應 route／cohort，導回 legacy canonical URL；不回復領域資料、不撤銷已合法發布版本。正在執行的 server job 繼續並可從舊 UI／runbook 查詢。新增 schema 採 additive，至少與目前及上一版 UI 相容；W6 前不刪舊欄位或 endpoint。

## 11. 交付里程碑與工作票

工時為熟悉本 repo 的一位工程師之粗估工程日，不含外部審核等待，W0 後重估；不代表固定交期。可由同一人依序承擔各職責，不預設已有完整團隊。

| 階段 | 粗估 | 主要交付與負責職責 | Exit gate |
|---|---:|---|---|
| W0 現況與契約 | 2–3 日 | 工程／產品：來源、路由、角色、示範、證據缺口及基準 | 完整 route ledger；真實閉環 trace；有具體 W1／W2 合約 |
| W1 技術試點 | 3–5 日 | 前端／平台：新 shell、providers、真實首頁、Health、同源 build | §7.1 全部試點條件通過或正式記錄停止擴大理由 |
| W2 第一條閉環 | 5–8 日 | 前後端／Service Owner：案件→文件→生效→驗收→觀察 | 真實資料 E2E，故障／衝突／重試與返回均可驗證 |
| W3 知識營運 | 5–8 日 | 前端／知識 owner：FAQ、文件編輯、審核、發布、同步、成效 | 舊能力對照及各角色 UAT 通過 |
| W4 AI 變更治理 | 5–8 日 | 前後端／AI owner：Prompt、Model、Flag、eval／gate | stale evidence、權限、核准、啟用與回退測試通過 |
| W5 平台治理 | 3–5 日 | 前端／平台：分析、成本、預算、權限、保存、遮罩、稽核 | 所有剩餘路由與高風險動作相容 |
| W6 切換與退場 | 2–3 日 | 平台／產品：cohort、演練、runbook、舊 UI 退場 | 連續觀察與角色 UAT；正式回退可完成 |

總估 25–40 工程日；若 W0 發現 runtime 生效查詢、持久化 job 或治理能力欠缺，作為獨立領域工作估算，不藏在前端工時內。

### 11.1 第一批可直接拆票的工作

| 票號 | 工作 | 依賴 | 驗收產物 |
|---|---|---|---|
| W0-01 | 匯出全部 view、aliases、filters、角色與新路由映射 | 無 | route ledger，涵蓋 demo 分支 |
| W0-02 | 追一筆真實案件與一個發布，逐項核對 evidence | 無 | API request／response 的遮罩樣本、缺口清單 |
| W0-03 | 定義待辦來源、bucket 規則、計數、失敗與分頁 | W0-02 | OpenAPI／contract fixtures，不使用示範故事 |
| W0-04 | 執行五項代表任務基準測量 | W0-01 | 任務完成率、時間、回跳次數與求助記錄 |
| W1-01 | 建立 React／Refine／Vite 工程、共用模板與 providers | W0-01／03 | lockfile、型別、build、provider contract tests |
| W1-02 | 實作真實我的工作與 Health 試點 | W1-01 | 權限隔離、partial、零資料與 deep-link 驗收 |
| W1-03 | 同源 serving、新舊路由開關、容器與回退 | W1-01 | 打包 smoke 與切回 legacy 證據 |
| W2-01 | 案件主頁整合步驟、證據與安全返回 | W0-02、W1 gate | 刷新／返回後同案件、同版本 |
| W2-02 | 補發布→runtime→eval→結案的必要後端缺口 | W0-02 | 每個缺口有失敗案例與有效修復測試 |
| W2-03 | 真實文件修正 E2E 與角色 UAT | W2-01／02 | 成功路徑及故障復原紀錄 |

每張票需包含 source-of-truth、觸及 API、角色、成功與失敗驗收、回退方法；沒有頁面完成率作為唯一結案依據。

## 12. 驗證與驗收矩陣

優先跑與變更直接相關的既有與新增測試，保留完整失敗輸出。純導覽不要為此重跑完整 RAG 評測；發布／gate 語意有變更才啟動對應領域與整合測試。

| ID | 情境 | 必須觀察到的結果 | 層級 |
|---|---|---|---|
| A01 | 登入後開工作首頁 | 只有可見的真實資料，沒有 VPN demo 計數 | API＋UI |
| A02 | 一個來源故障／所有來源故障 | partial＋重試／503；不能錯顯全部 0 | contract |
| A03 | 無權角色直接貼詳情 URL、改 owner filter | API 拒絕／隱藏存在性，計數及摘要不洩漏 | 授權整合 |
| A04 | 多頁待辦、同物件多個工作、切 bucket | 分頁穩定、同工作不重複、計數範圍一致 | contract |
| A05 | 案件→舊編輯器→返回→刷新 | 同案件與相關版本、filters 保留，dirty-state 可取消離開 | Browser E2E |
| A06 | 發布成功而 reload 失敗／只有部分實例套用 | 不顯示完全生效；可查具體狀態並安全重試 | 整合 |
| A07 | Candidate 改動後使用舊 eval／approval promote | server 拒絕並提示重新驗證 | governance |
| A08 | 兩人同改案件，重複按建立草稿 | stale etag 拒絕；重試不產生第二份副作用 | domain＋整合 |
| A09 | 草稿建立後連結失敗 | 可找回原草稿並補連結，不遺失工作 | 整合 |
| A10 | 無生效／eval 證據嘗試以已修復結案 | 後端拒絕；合法不適用需理由與權限 | domain |
| A11 | 示範／fixture／incomplete eval 用來結案 | 不當作真實品質通過證據 | evaluation |
| A12 | 關閉 v2 開關、job 正在執行 | 舊路由恢復、資料仍可讀、job 未被取消或重送 | deploy smoke |
| A13 | 深連結刷新、404 asset、401、logout／換使用者 | 正確頁面／錯誤，無跨身份 cache | UI＋HTTP |
| A14 | audit 寫入失敗的受保護 command | 遵循既有 fail-closed，不顯示成功 | domain |
| A15 | 知識與 FAQ、正反例與 Golden 題庫 | 各自資料／權限／版本契約不被 UI 合併 | 回歸 |
| A16 | 鍵盤、焦點、200% zoom、小螢幕 | 主要任務可完成，dialog 關閉恢復焦點，狀態不只靠顏色 | UI UAT |

可重用的既有證據位置：

- `agent_service/tests/frontend/navigation.test.mjs`、`bu-role-matrix.test.mjs`、`work-hub-buckets.test.mjs`：相容與 bucket 測試資產；bucket 測試存在不代表目前 workHub 已連到 live queue。
- `agent_service/tests/frontend/bu-shell-e2e.mjs`：既有 BU 旅程參考，新增 v2 與 legacy 交接案例。
- `agent_service/tests/test_quality_case_knowledge_vertical_slice.py`、`test_ai_ops_portal_governance_integration.py`：案件與知識整合。
- `agent_service/tests/test_backoffice_quality_domain.py`、`test_backoffice_governance_api.py`、`test_backoffice_req021_audit.py`：領域、治理及稽核。
- `agent_service/tests/test_ai_ops_backoffice_performance.py`：先核對測量範圍，再擴充新聚合 endpoint。

本 spec 的完成只代表需求整理完成；上述實作驗收必須在相應里程碑執行。

## 13. 品質指標與非功能要求

| 指標 | 目標／測量方式 |
|---|---|
| 任務成功率 | 每角色代表使用者完成指定旅程；試點至少 5 人、共至少 20 次嘗試，無工程師代操作成功率目標 ≥90%；記錄樣本限制 |
| 首次定位下一步 | 已登入到正確工作動作的中位數 ≤30 秒，排除認證等待 |
| 工作完成時間 | W0 基準相同任務及角色條件，W2／W6 目標中位數降低 ≥30%；尚無基準時不宣稱達標 |
| 跨功能重新搜尋 | 核心旅程不需重新找案件或人工輸入關聯 ID；以 session walkthrough 驗證 |
| 聚合 API | 測試資料至少每主來源 10,000 筆、25 筆分頁、20 concurrent readers；暖機後 p95 ≤1.5 秒，逾時來源可 partial；為待驗證目標 |
| 首頁可操作 | 約定一般辦公室網路與基準筆電，首訪 p75 ≤3 秒；記錄設備、cache 及資料規模 |
| 正確性底線 | 所有權限隔離、證據錯配、防重與回退驗收必過，不能用平均成功率抵銷 |

Telemetry 事件提案：`workflow_opened`、`next_action_clicked`、`handoff_to_legacy`、`workflow_blocked`、`workflow_completed`；只收 workflow、step、route、匿名化 actor/session、耗時、error code 及 correlation ID，不收內容全文。`workflow_completed` 由確認的 domain 結果產生，點按按鈕不計完成。事件保存沿用現有政策。

## 14. 風險、待確認項與預設處置

| 風險／尚待確認 | 預設處置 | 負責職責／最晚點 |
|---|---|---|
| 真實 runtime release／各實例版本是否可查 | 無證據顯示 unknown；需要補查詢則獨立領域票 | Runtime owner／W0 |
| 某些 API 的 pagination／filter／total 不完整 | 明確有限資料集；補 server contract，不前端假分頁 | Backend／W0 |
| Refine 對客製 API 的適配是否划算 | 五日試點與停止擴大條件，不全頁先遷移 | Frontend／W1 |
| 正式登入／續期／新舊切換行為 | 真實 Entra UAT；不僅用 HEADER 測試 | Platform／W1 |
| 已有 U1–U4 與 demo 調整造成文件落差 | 以目前原始碼、實際路由及 live API 重建清單 | 工程／W0 |
| 聚合暴露跨 owner／tenant 計數 | 授權前置與 cache 隔離測試；失敗不得上線 | Backend／W1 |
| 新舊編輯器長期並存 | 每批次設 canonical owner 與退場 gate，避免永久維護兩套 | 工程／W3–W6 |
| 觀察樣本不足或指標定義不同 | 顯示不足、保留分母與 policy 版本，不自動推論改善 | Service Owner／W2 |
| 只有一名維護者、工時有限 | 以 W0–W2 作首輪承諾，其餘通過閉環後再排程 | 產品／W0 |

W6 退場前需至少一個完整發布／觀察週期與連續 7 天的試點使用紀錄；無足夠使用樣本則延長觀察，不將「無錯誤回報」視為通過。舊 UI 刪除必須另有完整功能 ledger、無未處理阻塞、runbook 及經演練的上一版 artifact；本文件不要求現在刪除。

## 15. 本輪建議承諾

先投入 W0–W2，預估 10–16 工程日，交付**真實待辦首頁、可回退的新前端基礎、以及一條案件到改善證據的完整路徑**。使用者可在不理解後端模組分類的情況下完成工作，工程上也能確認框架確實減少共通成本，再擴大 W3–W6。

這一輪的交付說法應是「使用者能從真實負評一路完成可驗證的改善」，而不是「後台已換成 React」。
