# AI 資訊客服營運後台 Phase 2：品質改善閉環規格

> 文件狀態：Draft for review
>
> 規格版本：v1.0
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

Phase 2 產生的 Issue 正反例可供 Phase 3 Prompt 候選與離線評測使用，但不得直接自動修改正式 Prompt。

## 2. 對應 BU 需求

| BU 需求 | Phase 2 範圍 |
|---|---|
| REQ-004 | FAQ 新增、修改、停用、查詢、版本與稽核 |
| REQ-005 | FAQ 日／週／月／總命中與來源追溯 |
| REQ-006 | FAQ 對應 Issue 的正反例維護 |
| REQ-010 | 文件 Issue 正反例與人工補標 |
| REQ-013 | 重新同步／重新索引 Job 與狀態 |
| REQ-018 | 無答案／低信心／負評／轉人工管理池 |
| REQ-019 | Knowledge Gap 聚合、排序與改善追蹤 |
| REQ-023 | 成本／Token 門檻與個人每日 50 元政策 |
| REQ-025 | 同步、API、成本等異常通知與追蹤 |

REQ-015 的 Prompt 候選產生不在本階段；Phase 2 只建立經治理的 examples／evaluation dataset。

## 3. 目標與非目標

### 3.1 目標

- 讓 FAQ 成為版本化、可審核、可回復的正式知識來源。
- 將品質異常轉為有 owner、狀態、優先級、期限及改善動作的案件。
- 找出高頻、負評高、無答案或轉人工率高的 Knowledge Gap。
- 讓改善案件可連結 FAQ／文件草稿、測試、發布及後續效果。
- 讓管理者安全執行全量或指定範圍重新索引，並看見進度與錯誤。
- 建立成本與系統事件的門檻、通知、確認與結案紀錄。
- 累積可供 Phase 3 使用的人工確認正反例資料集。

### 3.2 非目標

- 不讓 AI 自動發布 FAQ、文件或 Prompt。
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
| AI Admin | 查閱 examples dataset 品質；不可在 Phase 2 啟用 Prompt |
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
- 停用與回復需填原因並產生 Audit。
- `faqKey` 變更需檢查 Prompt／Issue mapping 相容性。
- FAQ 答案仍為 deterministic fixed answer，不經 LLM 改寫。

### 5.3 FAQ 維護介面

- 依分類、關鍵字、狀態、Owner、Issue、檢視日搜尋與篩選。
- 新增／編輯精靈、版本差異、測試、送審、核准、啟用、停用、回復。
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
- 人工新增的 Issue Type 必須來自 ACTIVE taxonomy；新增 taxonomy 走 Phase 0 治理流程。
- 未驗證 example 不得進入正式 eval dataset。
- 修改 example 產生新版本，不靜默改寫已使用的 dataset。

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

- FAQ list/detail/create/update/submit/review/activate/disable/rollback。
- FAQ／Document examples list/create/verify/retire。
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

## 14. 安全、稽核與資料治理

- 從對話建立 example／case 時先套用 Phase 0 masking policy。
- 一般 Quality Case 頁不顯示未遮罩全文；需要時以額外授權展開並 Audit。
- FAQ audience、文件 audience 與 runtime ACL 使用同一群組來源。
- FAQ 啟用、停用、回復、Sync、Budget Policy 及 Alert receiver 變更必須 Audit。
- 通知 receiver 不可由未授權角色任意輸入外部地址。
- Dataset export／下載沿用 Phase 1 匯出安全規則。

## 15. 非功能需求

- Quality Pool 更新延遲小於 15 分鐘。
- FAQ 正式啟用後，runtime 在目標 SLA 內讀到新 immutable release；不得依賴重啟所有 instance。
- Sync Job 可重試、可冪等，服務重啟後狀態不遺失。
- 單一通知供應商失敗不阻擋客服回答，但需記錄 delivery failure。
- Cluster／Gap 計算不得將未遮罩文本輸出到未核准外部模型。
- 品質案件、FAQ 與 examples 的所有版本可追溯。

## 16. 驗收標準

1. 可完成 FAQ 新增、測試、送審、核准、啟用、停用與回復，且 runtime 僅採用 ACTIVE 版本。
2. FAQ 日／週／月／總命中可追溯至 Turn 與 FAQ version。
3. 可為 FAQ／文件新增、驗證、退役正反例，未驗證資料不進正式 dataset。
4. 無答案、低信心、負評與 Handoff 可形成候選並合併成 Quality Case。
5. 可由 Case 建立知識／FAQ 草稿，發布後進入觀察期並以數據驗證改善。
6. Gap 可依頻率、負評、無答案及 Handoff 排序，且分數可解釋。
7. 全量與指定範圍 Sync 可顯示成功／失敗、錯誤與重試；失敗不影響舊正式版。
8. 個人每日 TWD 50 元測試政策可觸發一次告警，並完成通知、確認與結案。
9. 通知不包含未遮罩對話或受限內容。
10. 所有高風險寫入、狀態轉移與匯出具有 Audit。

## 17. 待決策事項

| 決策 | 建議預設 |
|---|---|
| FAQ 是否雙人覆核 | 正式環境是 |
| Clustering 模型 | 使用核准模型；只產生候選 |
| Quality Case 觀察期 | 14 天或至少 30 次相關 Issue |
| 個人每日 50 元 | 只告警，不自動停用 |
| 通知系統 | 優先既有 Notification Center；無法整合時先 Email／Teams webhook gateway |
| 掃描 PDF OCR | 不因 Phase 2 自動納入，另案治理 |

## 18. Definition of Done

- FAQ runtime 已從啟動時 JSON 改為版本化、可安全刷新或 release-based 的來源。
- Quality Candidate → Case → 內容改善 → 發布 → 觀察 → 結案完成端到端 UAT。
- examples dataset 具版本、遮罩、驗證與來源追溯，可供 Phase 3 eval 使用。
- Sync Job、Budget Policy、Alert 與 Notification 具持久化狀態、重試及 Audit。
- BU 可在 20 分鐘內將一組重複無答案問題轉為改善案件並指派處理。
- 資安確認對話轉案例、通知及外部模型 clustering 的資料邊界。
