# AI 資訊客服營運後台 Phase 1：營運可視化 MVP 規格

> 文件狀態：Draft for review
>
> 規格版本：v1.0
>
> 前置條件：Phase 0 的事件、Issue taxonomy、遮罩、角色與保存契約已驗收
>
> 目標讀者：BU 產品負責人、Service Owner、知識管理者、營運分析者、稽核與平台維運
> 本階段定位：讓授權人員能回答「使用量、成本、問題類型、回答來源、品質與系統狀態」，並保留現有知識營運流程。

## 1. 執行摘要

Phase 1 交付第一個可供 BU 日常使用的完整後台。現有知識營運介面保留為 Knowledge 模組，新增營運總覽、對話查詢、Issue 分析、知識成效、回饋及健康度頁面。

本階段不做 Prompt 自動優化、動態模型切換或完整品質案件閉環；先確保資料可查、可追溯、可匯出且權限正確。

## 2. 對應 BU 需求

| BU 需求 | Phase 1 範圍 |
|---|---|
| REQ-001 | 對話量、使用者數與趨勢 Dashboard |
| REQ-002 | Token、模型、成本與匯出 |
| REQ-003 | 授權、遮罩、可稽核的對話查詢 |
| REQ-007 | Markdown／PDF 文件、版本、狀態與索引狀態 |
| REQ-008 | 文件命中與正負回饋 |
| REQ-009 | 文件命中的 Issue 分析 |
| REQ-011 | Issue 數量與期間趨勢 |
| REQ-012 | FAQ／RAG／Handoff／Ticket 路由來源追查 |
| REQ-017 | AI 回覆品質、解決、回饋與轉人工分析 |
| REQ-021 | Phase 1 模組的基本查詢與匯出稽核 |
| REQ-024 | Agent、RAG、LLM、Handoff／Ticket 的健康度摘要 |

REQ-027 在本階段只提供模組內搜尋；跨所有模組的全域搜尋留在 Phase 3。

## 3. 目標與非目標

### 3.1 目標

- 以一致口徑呈現日／週／月對話量、Issue、路由、命中、品質、Token 與成本。
- 讓授權角色可由 Dashboard 下鑽至 Issue、對話與來源文件。
- 讓負評、無答案、低信心與轉人工可被發現，並作為 Phase 2 品質池資料來源。
- 讓每份知識文件可查看命中、Issue、回饋及使用中的發布版本。
- 讓平台角色快速辨識 Agent／RAG／LLM／派工鏈路異常。
- 支援受控 CSV／XLSX 匯出與完整 Audit。

### 3.2 非目標

- 不在此階段提供 FAQ 維護、品質案件指派與 Knowledge Gap clustering。
- 不提供 Prompt、模型參數或 Feature Flag 的寫入操作。
- 不把 Dashboard 當作供應商帳務對帳系統。
- 不允許一般 Viewer 查看未遮罩對話、完整群組或 Credential。
- 不取代 Cloud Monitoring 的完整 incident management。

## 4. 使用者與權限

| 角色 | 預設可見 |
|---|---|
| Service Owner | 所屬服務的總覽、Issue、來源、品質與成本 |
| Knowledge Admin | 知識營運、文件成效、相關對話的遮罩內容 |
| Analyst／Viewer | 授權範圍的彙總及遮罩明細，不可執行高風險操作 |
| AI Admin | 模型／路由／成本分析；Phase 1 無設定寫入 |
| System Admin | 健康度與技術錯誤；未額外授權不得看原始對話 |
| Auditor | 唯讀 Audit、查詢與匯出軌跡 |

所有查詢套用 Phase 0 的 data scope。使用者搜尋、對話展開、未遮罩查閱與匯出都要產生 Audit Event。

## 5. 資訊架構

```text
營運總覽
對話紀錄
Issue 分析
品質與回饋
知識營運
  ├─ 文件
  ├─ 審核
  ├─ 發布
  └─ 文件成效
成本分析
系統健康度
稽核紀錄
```

Dashboard 卡片必須可下鑽，不提供無法追溯來源的裝飾性數字。

## 6. 功能需求

### 6.1 營運總覽

可切換今天、最近 7 天、最近 30 天、本月、最近 6 個月及自訂期間，顯示：

- Conversation 數、Turn 數、去識別 active user 數。
- Issue Occurrence 數及前五名 Issue Type。
- FAQ 回答、Knowledge 回答、無答案、澄清、Handoff／Ticket 比率。
- 正評、負評、已解決、轉人工。
- 總 Token、估算成本、成本完整率。
- P50／P95 回應時間與錯誤率。
- 資料更新時間、時區與指標定義版本。

不得將缺少成本資料的請求當作零成本；應顯示 coverage。

### 6.2 對話紀錄查詢

支援日期、使用者 pseudonymous ID／授權身分、Conversation ID、Issue Type、Route、模型、回饋、是否 Handoff／Ticket 篩選。

對話明細至少顯示：

- 時間軸中的使用者提問與 AI 回覆。
- 每個 Turn 的模型、Issue、Route、最終結果。
- FAQ／文件／版本／Release／Citation。
- 回饋、是否解決、Handoff／Ticket 結果。
- correlation ID 與資料遮罩狀態。

預設遮罩姓名、Email、電話、員編及政策指定欄位。查閱未遮罩內容需要額外 capability、理由與 Audit；Credential 永不顯示。

### 6.3 Token 與成本分析

- 依日期、Provider、模型、元件、Route、Issue Type、環境聚合。
- 顯示 input、output、tool context、embedding token 與 LLM call count。
- 顯示估算 USD／TWD、pricing version、usage source 與 coverage。
- 成本率表只能由 Phase 3 高權限設定流程修改；Phase 1 唯讀。
- 匯出包含查詢條件、時區、產生時間與 pricing version。

### 6.4 Issue Dashboard

- 期間：1 日、1 週、1 月、6 個月、自訂。
- 顯示 Issue 數量、占比、趨勢、負評率、無答案率、Handoff 率及成本。
- 可展開 parent／child taxonomy。
- 可由 Issue 下鑽至 Route、FAQ、文件及遮罩對話。
- `other.unclassified` 必須獨立顯示，不可藏入其他類別。
- taxonomy 版本變更時，畫面顯示所採口徑。

### 6.5 路由來源分析

對每個 Issue 顯示 FAQ、Knowledge、Ticket、Handoff、Clarification、Failed 的分布。Knowledge 路徑需顯示實際採用的 Document／Version／Release，而非只顯示檢索候選。

支援從：

```text
Issue Type → Route → FAQ／Document → Conversation Turn
Document → Issue Type → Conversation Turn
```

雙向追查。

### 6.6 知識文件維護擴充

沿用現有草稿、測試、送審、發布、下架與回復流程，新增：

- 檔案格式、解析狀態、索引狀態、目前 Release。
- PDF 上傳與解析；文字型 PDF 為必要，掃描 PDF 若未導入 OCR 應明確拒絕並說明。
- 上傳前執行檔案類型、大小、惡意內容與敏感資訊檢查。
- PDF 仍轉為受治理的 canonical text／segments，不直接把二進位檔當作 RAG 唯一來源。
- 文件命中、正負評、Issue 分布、最近使用時間及對應對話。
- 未發布草稿不得計入正式命中。

### 6.7 品質與回饋

保存並查詢：

- `UP | DOWN`。
- 負評原因：答案錯誤、過時、步驟不清楚、無關、權限／來源問題、其他。
- 是否解決：`YES | NO | UNKNOWN`。
- 是否轉人工／建單及結果。
- 回答使用的 FAQ／文件版本、Issue、Route 與模型。

Phase 1 提供篩選與下鑽，不提供完整案件指派；可將事件標記為 Phase 2 品質候選。

### 6.8 系統健康度

顯示：

- Teams Adapter、Agent Service、LLM API、Issue Extractor、FAQ、RAG／索引、Handoff／Ticket API。
- Availability、request count、error rate、timeout rate、P50／P95 latency。
- 使用中的 Knowledge Release、最近發布與索引狀態。
- 最近異常摘要與 Cloud Monitoring deep link。

本頁不得暴露 secret、完整 stack trace 或未遮罩 prompt／message。

### 6.9 匯出

- 對話、成本、Issue、路由、文件成效及回饋支援受控匯出。
- 大型匯出使用非同步 Job，狀態為 `QUEUED | RUNNING | COMPLETED | FAILED | EXPIRED`。
- 下載網址短效且綁定申請者；檔案到期自動刪除。
- 每次匯出記錄條件、欄位、筆數、理由及結果。
- 超過政策允許期間或筆數時拒絕，不能由前端分批繞過。

## 7. 資料模型

Phase 1 主要 read model：

- `DailyOperationsAggregate`
- `ConversationSearchDocument`
- `TurnDetail`
- `IssueOccurrenceFact`
- `RouteOutcomeFact`
- `KnowledgeAttributionFact`
- `FeedbackFact`
- `UsageCostFact`
- `ServiceHealthSnapshot`
- `ExportJob`

所有 read model 可由 Phase 0 immutable events 重建；不得成為新的未定義事實來源。

## 8. API 能力需求

- `GET /operations/summary`
- `GET /conversations`
- `GET /conversations/{id}`
- `GET /issues/summary`
- `GET /issues/{issueTypeId}/routes`
- `GET /knowledge/{documentId}/performance`
- `GET /feedback`
- `GET /costs/summary`
- `GET /health/summary`
- `POST /exports`、`GET /exports/{jobId}`

以上為能力契約，不強制實際 URL。所有查詢須支援 cursor、期間與 data scope；禁止把任意 SQL、log query 或 collection path 暴露給前端。

## 9. UI／UX 規格

- 使用業務語言，技術欄位放入進階資訊。
- 圖表必須附數值表格或可存取替代內容。
- 空狀態說明沒有資料、權限不足或管線延遲，不混為同一狀態。
- 篩選條件可見、可清除、可分享但不可在 URL 放置敏感值。
- 對話頁先顯示摘要，原始脈絡採明確展開，避免無意暴露敏感內容。
- 所有統計顯示資料更新時間；資料不完整時顯示 coverage／warning。
- WCAG 2.1 AA；鍵盤操作、focus、loading、error、empty、forbidden 狀態完整。

## 10. 安全與稽核

- 所有 API 驗證 Entra identity、capability 與 data scope。
- 對話全文不可進入瀏覽器 log、URL、analytics beacon 或錯誤追蹤 payload。
- 未遮罩查閱與匯出採 step-up 理由確認，並記錄 Audit。
- CSV／XLSX 防公式注入；以 `= + - @` 開頭的使用者文字需安全輸出。
- Audit 頁只讀，不提供一般管理者刪除。
- 知識文件的 audience 與對話資料範圍使用相同授權來源。

## 11. 效能與可用性

- Dashboard 30 天預設查詢 P95 小於 3 秒。
- 對話搜尋 P95 小於 3 秒；單一對話明細 P95 小於 2 秒。
- 一般分析資料延遲小於 15 分鐘；健康度小於 5 分鐘。
- 大型匯出不阻塞互動 API。
- 每頁預設 25–50 筆並採 cursor pagination。
- Analytics 管線失效不影響 Teams 回答；後台應顯示資料延遲警告。

## 12. 驗收標準

1. 日／週／月對話數可與去重後原始事件抽樣核對。
2. 每個模型的 Token 與成本可追溯 pricing version，未知價格不顯示為零。
3. 授權人員可查指定使用者最近六個月對話；未授權者只看到遮罩或 403。
4. 對話可追查 Issue、Route、FAQ／文件、回饋及 Handoff／Ticket。
5. Issue Dashboard 支援 1 日、1 週、1 月、6 個月與自訂期間。
6. 文件頁可顯示命中、正負評、Issue 與對應對話。
7. Markdown 及文字型 PDF 可治理、解析、測試、送審、發布及顯示索引狀態。
8. 系統健康度可辨識至少一個模擬 LLM、RAG、Ticket API 異常。
9. 匯出套用畫面相同權限與遮罩，且留下 Audit。
10. Dashboard 所有數字皆可下鑽或連結至定義，不出現無來源 KPI。

## 13. 上線與移轉

- 先以歷史事件 replay 建立 30–90 天測試資料，驗證口徑後再開放 BU。
- 對話查詢先開放少數授權角色，完成資安抽查後擴大。
- 現有知識營運 URL 可保留導向新後台 Knowledge 模組。
- Cloud Logging 舊資料若欄位不足，只標示為 legacy aggregate，不偽造明細。
- 上線初期每日核對 event count、duplicate、late event、cost coverage 與遮罩失敗。

## 14. 待決策事項

| 決策 | 建議預設 |
|---|---|
| PDF OCR | Phase 1 不含；掃描 PDF 明確拒絕 |
| 對話未遮罩權限 | Service Owner 不預設擁有，需額外 capability |
| 成本幣別 | USD 為計算基準，TWD 為版本化匯率估算 |
| Dashboard 更新 | 15 分鐘內 |
| 匯出期限 | 24 小時後失效並刪除 |
| Legacy log 匯入 | 只匯入欄位完整、可驗證資料 |

## 15. Definition of Done

- 所有 Phase 1 指標均使用 Phase 0 定義並完成抽樣 reconciliation。
- 角色、data scope、遮罩、未遮罩查閱及匯出安全測試通過。
- Dashboard、對話、Issue、知識成效、成本、回饋、健康度具 loading／empty／error／forbidden 狀態。
- Markdown／PDF 與現有知識發布流程完成端到端 UAT。
- Analytics 延遲、資料品質與服務健康度具有監控及 runbook。
- BU 可在 15 分鐘內完成「由負評找到對話、Issue、來源文件」的驗收任務。
