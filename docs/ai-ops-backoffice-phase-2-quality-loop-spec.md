# AI 資訊客服營運後台 Phase 2：品質改善閉環規格

> 文件狀態：Implementation in progress
>
> 規格版本：v1.2
>
> 需求基準：2026-09-03 提供之《功能需求清單》與《資料保存規則》CSV
>
> 前置條件：Phase 0 資料治理與 Phase 1 營運可視化已驗收
>
> 目標讀者：Knowledge Admin、Service Owner、內容維護者、Reviewer、AI Admin、平台維運
> 本階段定位：將 FAQ、無答案、低信心、負評與重複問題轉成可指派、可改善、可驗證、可結案的營運流程。

## 1. 執行摘要

Phase 2 將 Phase 1 的觀察能力轉為改善能力。系統不只呈現「哪裡不好」，還要讓營運人員建立品質案件、維護 FAQ、補強知識、執行重新索引、驗證改善效果並結案。

```text
無答案／低信心／負評／Handoff／重複 Issue
  → Quality Candidate
  → 去重與合併
  → 指派 Owner／設定優先級
  → 新增或更新 FAQ／知識
  → 測試、送審、發布／同步
  → 觀察改善結果
  → 結案或重新開啟
```

Phase 2 產生的 Issue 正反例可供 Prompt 候選與離線評測使用。本階段依 POC 需求提供目前正式 Prompt 的唯讀檢視及候選產生，但不得啟用候選或直接修改正式 Prompt；生產核准、Canary、啟用與回復由 Phase 3 負責。

### 1.1 實作進度（2026-09-03）

- FAQ 第一垂直切片已完成：FILE／Firestore repository、不可變版本、owner scope、etag、冪等、Audit、正反例、送審、SYSTEM_ADMIN 核准／退回／啟用／停用，以及 Backoffice 管理介面。
- 已驗證 FILE restart persistence、Knowledge Admin 與 SYSTEM_ADMIN 職責分離、API lifecycle，以及 390×844 responsive UI；focused suite 為 36 passed。
- Agent runtime adapter 已完成：`FAQ_RUNTIME_MODE=GOVERNED` 時只讀 immutable ACTIVE versions，沿用 request groups 執行 audience ACL，FILE mode 已驗證同一 instance 無重啟即可看見啟用與停用。production Firestore cutover 與故障注入證據仍待完成。
- 尚未完成：FAQ edit／rollback UI 與完整 API 驗收、FAQ 命中分析、examples dataset 治理，以及其餘 Quality Case、Gap、Sync、Budget、Alert、Notification、Prompt POC。
- 本節僅代表第一垂直切片完成，不代表 Phase 2 驗收完成。

## 2. 對應 BU 需求

| BU 需求 | Phase 2 範圍 |
|---|---|
| REQ-004 | FAQ 新增、修改、停用、查詢、版本與稽核 |
| REQ-005 | FAQ 日／週／月／總命中與來源追溯 |
| REQ-006 | FAQ 對應 Issue 的正反例維護 |
| REQ-010 | 文件 Issue 正反例與人工補標 |
| REQ-013 | 重新同步／重新索引 Job 與狀態 |
| REQ-014 | 目前啟用中的 Issue Extractor Prompt、版本與狀態唯讀檢視 |
| REQ-015 | 依已驗證正反例產生 Prompt Candidate；不覆蓋正式版本 |
| REQ-018 | 無答案／低信心／負評／轉人工管理池 |
| REQ-019 | Knowledge Gap 聚合、排序與改善追蹤 |
| REQ-023 | 成本／Token 門檻與個人每日 50 元政策 |
| REQ-025 | 同步、API、成本等異常通知與追蹤 |

REQ-014、REQ-015 在本階段以 POC 範圍交付；REQ-016 的核准、啟用與回復及 REQ-015 的完整生產 Eval／治理流程留在 Phase 3。

## 3. 目標與非目標

### 3.1 目標

- 讓 FAQ 成為版本化、可審核、可回復的正式知識來源。
- 將品質異常轉為有 owner、狀態、優先級、期限及改善動作的案件。
- 找出高頻、負評高、無答案或轉人工率高的 Knowledge Gap。
- 讓改善案件可連結 FAQ／文件草稿、測試、發布及後續效果。
- 讓管理者安全執行全量或指定範圍重新索引，並看見進度與錯誤。
- 建立成本與系統事件的門檻、通知、確認與結案紀錄。
- 累積可供 Phase 3 使用的人工確認正反例資料集。
- 讓 AI Admin 唯讀查看目前正式 Prompt，並以已驗證 dataset 產生不影響 Active 版本的候選。

### 3.2 非目標

- 不讓 AI 自動發布 FAQ／文件，或核准、啟用、回復 Prompt。
- 不將語意 clustering 結果直接視為正式 Issue taxonomy。
- 不建立通用客服工單系統；Quality Case 只管理 AI／知識改善。
- 不取代公司既有通知中心或 incident management；若有既有系統，以整合為優先。
- 不讓管理者任意輸入 shell command、index path 或 cloud resource ID。

## 4. 角色與職責

| 角色 | 能力 |
|---|---|
| Knowledge Contributor | 編輯被指派的 FAQ／知識草稿、補充案例、執行測試 |
| Knowledge Reviewer | 審核 FAQ／文件版本及品質案件改善證據 |
| Knowledge Admin | 管理 FAQ、品質池、Owner、同步範圍與緊急停用 |
| Service Owner | 排定 Gap 優先級、核准分類與結案、設定服務成本門檻 |
| AI Admin | 查閱 examples dataset 與目前正式 Prompt，產生 Prompt Candidate；不可在 Phase 2 啟用 Prompt |
| System Admin | 管理同步 Job、通知整合與技術告警 |
| Auditor | 唯讀查看案件、內容版本、同步、通知與操作稽核 |

建立內容的人原則上不可單獨核准並發布同一版本。POC 例外必須留下理由及例外標記。

## 5. FAQ Domain 規格

### 5.1 FAQ 資料模型

- `faqId`：穩定 ID。
- `faqKey`：供 Agent route 使用的不可重複 key。
- `question`、`answer`、`category`、`keywords`。
- `ownerUnitId`、`businessContact`。
- `issueTypeIds`。
- `audienceType`、`audienceGroupIds`。
- `status`、`draftVersionId`、`publishedVersionId`。
- `effectiveAt`、`reviewDueAt`。
- `createdBy`、`updatedBy`、timestamps、etag。

### 5.2 FAQ 生命週期

```text
DRAFT → IN_REVIEW → APPROVED → ACTIVE
   ↑         │           │        │
   └─ CHANGES_REQUESTED ─┘        ├─ DISABLED
                                  └─ SUPERSEDED
```

- Runtime 只能讀取 `ACTIVE` 且 audience 符合的不可變 FAQ release。
- 編輯既有 FAQ 必須建立新版本，不原地修改正式答案。
- 未發布且無相依關係的草稿可經權限與相依檢查後實體刪除；已發布 FAQ 不得硬刪除，應停用或由新版本取代並保留歷史關聯。
- 停用與回復需填原因並產生 Audit。
- `faqKey` 變更需檢查 Prompt／Issue mapping 相容性。
- FAQ 答案仍為 deterministic fixed answer，不經 LLM 改寫。

### 5.3 FAQ 維護介面

- 依分類、關鍵字、狀態、Owner、Issue、檢視日搜尋與篩選。
- 新增／編輯精靈、版本差異、測試、送審、核准、啟用、停用、受治理刪除、回復。
- 顯示日／週／月／總命中、正負評、無效 fallback 與對應對話。
- FAQ 啟用前至少測試典型問法、相似但不應命中的反例及 audience。

## 6. Issue 正反例資料集

### 6.1 Example Record

- `exampleId`
- `sourceType`：`FAQ | DOCUMENT | CONVERSATION | MANUAL`
- `sourceId`、`sourceVersionId`
- `text`：遮罩後、經授權的範例文字
- `expectedIssueTypeId`
- `expectedRoute`
- `label`：`POSITIVE | NEGATIVE`
- `reason`
- `status`：`DRAFT | VERIFIED | REJECTED | RETIRED`
- `verifiedBy`、`verifiedAt`
- `datasetVersion`

### 6.2 規則

- Positive 表示應分類／命中；Negative 表示不應分類／不應命中，必須寫明混淆對象。
- 由對話轉成 example 前先遮罩，並保留 source correlation 供授權追溯。
- Knowledge Admin 可為文件人工新增、修改或移除 ACTIVE Issue Type 關聯與正反例，並保存 `sourceType`、`sourceId`、`sourceVersionId` 及操作者；若需建立新的 Issue Type，必須走 Phase 0 taxonomy 治理流程。
- 未驗證 example 不得進入正式 eval dataset。
- 修改 example 產生新版本，不靜默改寫已使用的 dataset。
- FAQ／文件正反例支援新增、修改與刪除；「刪除」以 `RETIRED` 及新版本表示，已被 dataset 使用的紀錄不得硬刪除。

### 6.3 Prompt 檢視與候選產生（REQ-014／015 POC）

- AI Admin 可唯讀查看目前啟用中的 Issue Extractor Prompt、版本、狀態及生效時間；Prompt 原文另受 capability 控制，secret value 永不顯示。
- 候選產生必須指定 `VERIFIED` dataset version、目前 Active Prompt version、taxonomy version、資料範圍及 masking policy version。
- 每次執行建立新的 immutable Candidate，保存產生者、輸入 manifest、模型 usage／成本、狀態、時間及 correlation ID；失敗不得留下可啟用候選。
- Candidate 產生前執行 schema、secret、prompt injection 與長度檢查，產生後可與 Active 版本比較，但不得修改 Active pointer。
- Phase 2 不提供 submit／approve／activate／rollback API；完整 Eval、核准、Canary、啟用與回復由 Phase 3 實作。
- 雲端 LAB 無法串接正式 AA／IAM 時只允許 Phase 0 定義的測試角色映射；不得以本地正式帳號或略過授權方式執行候選產生。

## 7. Quality Case 管理池

### 7.1 進池條件

- `NO_KNOWLEDGE`。
- Low confidence／`NEEDS_REVIEW`。
- 使用者負評或未解決。
- Handoff／Ticket，且原因與知識不足有關。
- 同一 Issue／相似問題超過版本化頻率門檻。
- FAQ／文件持續負評或命中後轉人工。
- 平台、Service Owner 或 Knowledge Admin 人工建立。

每個來源先形成 Candidate；去重／合併後才建立 Quality Case，避免每個負評都變成獨立案件。

### 7.2 Quality Case 資料模型

- `caseId`、`title`、`description`。
- `caseType`：`NO_ANSWER | LOW_CONFIDENCE | NEGATIVE_FEEDBACK | HANDOFF | KNOWLEDGE_GAP | OTHER`。
- `issueTypeId`、`questionClusterId`。
- `priority`：`LOW | MEDIUM | HIGH | CRITICAL`。
- `ownerUnitId`、`assigneeId`。
- `status`：`NEW | TRIAGED | IN_PROGRESS | WAITING_REVIEW | OBSERVING | RESOLVED | WONT_FIX | DUPLICATE`。
- `sourceEventIds`、`conversationRefs`、`faqIds`、`documentIds`。
- `frequency`、`negativeRate`、`handoffRate`、`estimatedCostImpact`。
- `targetDueAt`、`resolutionType`、`resolutionNote`。
- `createdAt`、`updatedAt`、`resolvedAt`、etag。

### 7.3 操作流程

- 篩選原因、Issue、Owner、狀態、優先級及期間。
- 合併重複案件時保留原 Case ID 與事件關聯。
- 可從 Case 建立 FAQ 草稿、知識草稿或連結既有草稿。
- 改善內容發布後自動進入 `OBSERVING`，不能立即宣稱解決。
- 觀察期比較發布前後命中、負評、無答案及 Handoff；達門檻後才結案。
- `WONT_FIX`、`DUPLICATE`、`RESOLVED` 必須填理由。

## 8. Knowledge Gap 分析

### 8.1 排序指標

Gap Score 應使用可見、版本化的規則，至少考慮：

- 出現頻率。
- 無答案率。
- 負評／未解決率。
- Handoff／Ticket 率。
- 最近趨勢增幅。
- Service Owner 設定的重要度。
- 估算成本或人工處理影響。

不得只用 LLM 主觀分數。各項權重由設定版本管理，畫面可查看計算說明。

### 8.2 Question Clustering

- Clustering 使用遮罩後文字或受控 embedding。
- 每個 cluster 顯示代表問題、Issue 分布、頻率與來源樣本。
- AI 產生的 cluster 只是候選；Knowledge Admin 可合併、拆分、命名或拒絕。
- Cluster 版本變更不得改寫歷史原始事件。
- 可將 cluster 轉為 Quality Case，但不可自動發布答案。

## 9. 重新同步／重新索引

### 9.1 Sync Job

- `jobId`、`scopeType`、`scopeIds`。
- `requestedBy`、`reason`。
- `status`：`QUEUED | VALIDATING | BUILDING | VERIFYING | COMPLETED | FAILED | CANCELLED`。
- 開始／結束時間、目前階段、文件數、警告、錯誤摘要、correlation ID。
- target release、index setting version、artifact URI（技術資訊僅平台角色可見）。

### 9.2 規則

- 支援全部、指定 FAQ、指定文件或指定失敗範圍；實際支援範圍由 adapter capability 回報。
- 同一 scope 同時只能有一個有效 Job，重複請求需冪等或明確拒絕。
- 建置與驗證完成前不得切換正式 release。
- 失敗維持舊版，提供可理解原因與重試。
- 一般 Knowledge Admin 不輸入路徑、bucket、index 名稱或 shell 參數。
- 觸發、取消、重試、成功與失敗全部 Audit。

## 10. 成本門檻與告警

### 10.1 Budget Policy

- scope：個人、Service、Team、Tenant、全系統。
- period：daily／monthly。
- measure：TWD／USD／Token／LLM call count。
- warning threshold 與 critical threshold。
- enabled、effective period、owner、notification targets。
- pricing version 與匯率版本。

BU 提出的個人每日 TWD 50 元作為一個預設候選政策，正式啟用前需確認：是否只告警、是否限制服務、時區、跨模型計價及未完整成本的處理。

Phase 2 預設只告警、不自動停用服務；若未來要 hard limit，必須在 Phase 3 以 Feature Flag 及例外流程治理。

### 10.2 Alert Event

- `alertId`、type、severity、scope、threshold、actual value。
- firstTriggeredAt、lastTriggeredAt、status。
- receiver、delivery channel、delivery result。
- acknowledgedBy／At、resolvedBy／At、resolution note。

同一原因在抑制期間內合併，不大量重複通知。

## 11. 異常通知

通知類型至少包含：

- 知識／FAQ 同步失敗。
- Agent／LLM／RAG／Ticket API 錯誤率或延遲超標。
- 成本／Token 超標。
- 大量無答案、負評或 Handoff。
- Quality Case 逾期。

通知管道優先整合公司既有 Teams／Email／Notification Center。通知不得包含完整受限對話或文件內容；只提供摘要、嚴重度、時間及後台 deep link。

## 12. API 能力需求

- FAQ list/detail/create/update/delete/submit/review/activate/disable/rollback；已發布 FAQ 的 delete 只能執行受治理停用／退役。
- FAQ／Document Issue associations 與 examples list/create/update/verify/retire；retire 為已使用關聯或 example 的受治理刪除。
- Active Prompt read，以及 Prompt Candidate generate/list/detail/compare；不提供 approve／activate／rollback。
- Quality candidates list／merge，Quality cases CRUD／assign／transition／resolve。
- Gap summary、cluster detail、cluster correction。
- Sync job create/list/detail/retry/cancel。
- Budget policy list/create/update/disable。
- Alert list/detail/acknowledge/resolve，notification delivery status。

所有寫入使用 etag／版本衝突保護，狀態轉移由後端驗證，不接受任意 status 覆寫。

## 13. UI／UX 規格

- 首頁優先顯示「需處理」而非只顯示圖表。
- Quality Case 提供明確下一步、Owner、期限及關聯改善內容。
- FAQ 編輯使用業務欄位；`faqKey` 與技術 metadata 放進進階資訊。
- Gap 分數可解釋，顯示主要構成因素。
- 批次操作限指派、標籤與通知；不得批次發布 FAQ／文件。
- Sync Job 顯示階段與進度，不只顯示 spinner。
- 成本告警清楚區分估算值、資料 coverage 與帳單實際值。
- Prompt 頁明確區分 Active 與 Candidate，候選產生按鈕不得使用「啟用」或「發布」字樣。

## 14. 安全、稽核與資料治理

- 從對話建立 example／case 時先套用 Phase 0 masking policy。
- 一般 Quality Case 頁不顯示未遮罩全文；需要時以額外授權展開並 Audit。
- FAQ audience、文件 audience 與 runtime ACL 使用同一群組來源。
- FAQ 啟用、停用、回復、Sync、Budget Policy 及 Alert receiver 變更必須 Audit。
- FAQ／example 刪除、Active Prompt 查閱及 Candidate 產生必須 Audit；Prompt 與 dataset 內容先套用 secret redaction 與 masking policy。
- 通知 receiver 不可由未授權角色任意輸入外部地址。
- Dataset export／下載沿用 Phase 1 匯出安全規則。

依最新資料保存規則，FAQ 命中、正反例及來源明細、Quality Candidate／Case／Gap 明細、Sync Job、成本門檻實績、Alert 與 Notification 歷史保存一年；到期刪除明細或僅保留不可逆彙總。FAQ 主檔及 Prompt／FAQ／文件版本期限仍待治理決議；若資料同時屬於 Audit，採較長的稽核保存政策。

## 15. 非功能需求

- Quality Pool 更新延遲小於 15 分鐘。
- FAQ 正式啟用後，runtime 在目標 SLA 內讀到新 immutable release；不得依賴重啟所有 instance。
- Sync Job 可重試、可冪等，服務重啟後狀態不遺失。
- 單一通知供應商失敗不阻擋客服回答，但需記錄 delivery failure。
- Cluster／Gap 計算不得將未遮罩文本輸出到未核准外部模型。
- 品質案件、FAQ 與 examples 的所有版本可追溯。

## 16. 驗收標準

1. 可完成 FAQ 新增、修改、受治理刪除、查詢、測試、送審、核准、啟用、停用與回復，且 runtime 僅採用 ACTIVE 版本。
2. FAQ 日／週／月／總命中可追溯至 Turn 與 FAQ version。
3. 可為 FAQ／文件新增、修改、驗證及受治理刪除 Issue 關聯與正反例，並保留來源與操作者；未驗證資料不進正式 dataset，已使用資料不被硬刪除。
4. 無答案、低信心、負評與 Handoff 可形成候選並合併成 Quality Case。
5. 可由 Case 建立知識／FAQ 草稿，發布後進入觀察期並以數據驗證改善。
6. Gap 可依頻率、負評、無答案及 Handoff 排序，且分數可解釋。
7. 全量與指定範圍 Sync 可顯示成功／失敗、錯誤與重試；失敗不影響舊正式版。
8. 個人每日 TWD 50 元測試政策可觸發一次告警，並完成通知、確認與結案。
9. 通知不包含未遮罩對話或受限內容。
10. 所有高風險寫入、狀態轉移與匯出具有 Audit。
11. AI Admin 可辨識目前啟用中的 Issue Extractor Prompt、版本、狀態及生效時間，未授權角色看不到 Prompt 原文。
12. 使用已驗證 dataset 產生新 Prompt Candidate 時不修改 Active 版本，且 Phase 2 無法核准或啟用候選。

## 17. 待決策事項

| 決策 | 建議預設 |
|---|---|
| FAQ 覆核權限 | 由 SYSTEM_ADMIN 完成最終核准；目前指定核准人為 Justin，技術 gate 不得略過 |
| Clustering 模型 | 使用核准模型；只產生候選 |
| Quality Case 觀察期 | 14 天或至少 30 次相關 Issue |
| 個人每日 50 元 | 只告警，不自動停用 |
| 通知系統 | 優先既有 Notification Center；無法整合時先 Email／Teams webhook gateway |
| 掃描 PDF OCR | 不因 Phase 2 自動納入，另案治理 |

## 18. Definition of Done

- FAQ runtime 已從啟動時 JSON 改為版本化、可安全刷新或 release-based 的來源。
- Quality Candidate → Case → 內容改善 → 發布 → 觀察 → 結案完成端到端 UAT。
- examples dataset 具版本、遮罩、驗證與來源追溯，可供 Phase 3 eval 使用。
- REQ-014／015 POC 完成 Active Prompt 唯讀檢視與 Candidate 產生，並以權限及 API 測試證明無法改動 Active 版本。
- Sync Job、Budget Policy、Alert 與 Notification 具持久化狀態、重試及 Audit。
- BU 可在 20 分鐘內將一組重複無答案問題轉為改善案件並指派處理。
- 資安確認對話轉案例、通知及外部模型 clustering 的資料邊界。
