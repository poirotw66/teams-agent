# AI 資訊客服營運後台 Phase 0：資料、治理與平台基礎規格

> 文件狀態：Draft for review
>
> 規格版本：v1.1
>
> 適用專案：Microsoft Teams IT 智能助手
>
> 目標讀者：BU 產品負責人、證券團隊、AI／平台工程師、資安、法遵、稽核
>
> 前置文件：`knowledge-operations-portal-spec.md`、BU《AI資訊客服_管理後臺完整需求規格V1》
>
> 需求基準：2026-09-03 提供之《功能需求清單》與《資料保存規則》CSV
> 本階段定位：先建立可被後續 Dashboard、對話查詢、品質改善與 AI 設定共同使用的資料及治理契約；不以大量後台畫面為交付重點。

## 1. 執行摘要

Phase 0 解決的不是頁面問題，而是「後台數字能否被信任」與「敏感資料能否安全查詢」。完成後，系統應具備一致的 Issue 分類、營運事件、資料關聯、保存期限、遮罩、角色與稽核規則，讓 Phase 1–3 不需各自發明資料定義。

核心資料流：

```text
Teams Turn / Agent Request
  → 執行期 Agent、FAQ、RAG、Handoff、Feedback
  → 標準化 Operational Event
  → 分流至 Analytics Store / Transcript Store / Audit Store
  → 保存、遮罩與權限政策
  → Phase 1–3 後台查詢與操作
```

## 2. 目標與非目標

### 2.1 目標

- 定義穩定且可版本化的 Issue taxonomy，支援趨勢、命中與 Knowledge Gap 分析。
- 定義跨 Agent、FAQ、RAG、Handoff、Feedback、Cost 的標準事件 envelope。
- 讓 conversation、request、turn、issue、citation、feedback、ticket/handoff 可透過 ID 關聯。
- 將原始對話、分析事件、設定資料及 Audit Log 分開治理。
- 建立一年保存、到期刪除、去識別化及例外保留的執行規則。
- 建立後台角色、資料範圍與高風險操作的授權基線。
- 補齊後台部署、資料儲存、監控與環境隔離的 Terraform 目標架構。
- 產出 Phase 1 可直接使用的資料契約、驗收資料與查詢定義。

### 2.2 非目標

- 不交付完整 Dashboard、對話查詢、FAQ CRUD 或 Prompt 管理 UI。
- 不在此階段自動修改 Prompt、模型或 LangGraph 流程。
- 不把 Cloud Logging 當成長期業務資料庫。
- 不把 Firestore Conversation Repository 直接開放為管理查詢 API。
- 不建立本地密碼或自行維護的公司帳號系統。
- 不讓分析事件保存 API key、密碼、OTP、Token、完整 Credential 或未經核准的個資。

## 3. 對應 BU 需求

Phase 0 是下列需求的共同前置，並完成其治理基線：

CSV 的「POC／Production」欄位表示需求應達成的交付環境與成熟度，本系列的 Phase 0–3 則表示技術實作順序，兩者不可直接視為同一分期。同一 REQ 可跨多個技術 Phase 演進，但必須在 CSV 指定的交付階段滿足該列驗收條件；例如 REQ-014／015 的唯讀檢視與候選產生在 POC 完成，REQ-016 的生產核准、啟用與回復在 Phase 3 完成。

| BU 需求 | Phase 0 交付 |
|---|---|
| REQ-001、002、005、008、009、011、012、017、019、023、024 | 指標定義、事件 schema、關聯 ID、資料品質規則 |
| REQ-003 | 對話資料分類、遮罩、查詢稽核與保存契約 |
| REQ-006、010、014、015 | Issue taxonomy 與正反例資料集契約 |
| REQ-020 | 角色、capability 與資料範圍基線 |
| REQ-021 | Audit Event schema 與不可任意刪除原則 |
| REQ-026 | 敏感資訊分類、遮罩與保存基線 |
| REQ-027 | 跨模組搜尋所需索引欄位與權限過濾契約 |
| REQ-030 | 設定版本、變更理由與 Audit 基線 |

Phase 0 不代表上述需求的使用者功能已完成；使用者功能分別在 Phase 1–3 驗收。

## 4. 名詞與統計口徑

| 名詞 | 定義 |
|---|---|
| Conversation | Teams conversation scope 中的一段客服會話；不可等同單一問題。 |
| Turn | 一次使用者訊息及其對應的一次 Agent 最終回覆。 |
| Request | Agent Service 接收的一次 API 請求；重試需以 request ID 與 idempotency 資訊辨識。 |
| Issue Occurrence | Issue Extractor 在某一 Turn 產生的一個問題實例。 |
| Issue Type | 跨對話穩定的問題分類，例如 `vpn.account_locked`；與當次描述分離。 |
| Route | FAQ、KNOWLEDGE、TICKET、HANDOFF、NOT_IT 等實際處理路徑。 |
| Answered | 最終結果為 FAQ／Knowledge 回答，且必要來源資料完整；不代表使用者已解決。 |
| Resolved | 使用者明確回饋已解決，或案件依核准規則結案。 |
| Knowledge Hit | 最終回答引用至少一個有效文件／版本；單純檢索候選不算命中。 |
| FAQ Hit | 最終結果採用特定 FAQ 版本回答；Extractor 曾選 FAQ 但 fallback 不算命中。 |
| Low Confidence | 由版本化政策判定的需人工確認結果，不可用散落在程式中的單一 magic number。 |
| Active User | 指定期間內至少產生一個有效使用者 Turn 的去識別使用者。 |

所有 Dashboard 必須顯示統計時區、資料更新時間及指標定義版本。預設統計時區為 `Asia/Taipei`，事件儲存時間一律使用 UTC。

## 5. Issue Taxonomy 規格

### 5.1 Issue Type

每個 Issue Type 至少包含：

- `issueTypeId`：穩定、不可重用的 slug，例如 `vpn.account_locked`。
- `displayName`：繁體中文顯示名稱。
- `description`：納入與排除範圍。
- `parentIssueTypeId`：可選，最多三層。
- `ownerUnitId`：負責 BU／服務單位。
- `status`：`DRAFT | ACTIVE | DEPRECATED`。
- `taxonomyVersion`：分類版本。
- `effectiveAt`、`retiredAt`。
- `createdBy`、`approvedBy`。

禁止使用當次 Issue 的整數流水號作為分析分類。每一筆 Issue Occurrence 應同時保存原始描述、正規化描述、`issueTypeId`、taxonomy 版本、分類來源及信心狀態。

### 5.2 分類來源

- `MODEL`：模型 structured output。
- `FAQ_MAPPING`：由 FAQ 固定對應。
- `DOCUMENT_MAPPING`：由文件治理 metadata 對應。
- `MANUAL`：授權人員人工修正。
- `FALLBACK`：無法分類時的安全降級。

人工修正不得覆寫歷史原始判斷；應新增 correction event，保留前後值與理由。

### 5.3 Taxonomy 治理

- 新增、合併、停用分類需經 Service Owner 核准。
- 已使用的 ID 不可刪除或重新指派其他語意。
- taxonomy 改版後，歷史統計預設保留原版本；若執行重分類，必須產生可追溯的新投影。
- Phase 0 至少建立 20–50 筆代表性 IT 問題的 seed taxonomy 與未分類 `other.unclassified`。

## 6. Operational Event 規格

### 6.1 共用 Envelope

每個事件至少包含：

```yaml
eventId: UUID
eventType: string
schemaVersion: integer
occurredAt: UTC timestamp
ingestedAt: UTC timestamp
environment: dev|test|poc|prod
tenantId: string|null
teamId: string|null
channelScope: personal|channel|group_chat|playground
conversationId: string|null
turnId: string|null
requestId: string|null
correlationId: string
issueOccurrenceId: string|null
issueTypeId: string|null
taxonomyVersion: string|null
actorRef: pseudonymous string|null
dataClassification: PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED
retentionExpiresAt: UTC timestamp
payload: object
```

`eventId` 必須支援冪等寫入；重試不得重複計數。事件一旦寫入只允許新增 correction／redaction event，不直接修改分析事實。

### 6.2 必要事件類型

- `conversation.started`
- `turn.received`
- `issue.extracted`
- `issue.classified`
- `route.selected`
- `faq.answered`
- `knowledge.retrieved`
- `knowledge.answered`
- `answer.completed`
- `feedback.recorded`
- `handoff.offered | handoff.started | handoff.completed | handoff.cancelled`
- `ticket.created | ticket.failed`
- `usage.recorded`
- `request.failed`
- `knowledge.release.activated`
- `config.changed`

### 6.3 Knowledge Attribution

每次 FAQ／RAG 回答應保存：

- FAQ ID 與 FAQ version；或 Document ID、Knowledge Version ID、Release ID。
- Citation／Chunk ID 與排名。
- Knowledge backend。
- 回答結果與 retrieval 結果的區分。
- audience 判斷結果，但不得在分析事件中展開使用者所有群組。

### 6.4 Cost Attribution

每個模型／工具呼叫應保存 provider、model、input/output/tool/embedding token、pricing version、usage source、估算成本、狀態與 latency。Request 層另保存總計，且不得將「估算成本」顯示為供應商帳單實際金額。

## 7. 資料儲存與責任邊界

| 儲存 | 用途 | 禁止用途 |
|---|---|---|
| Analytics Store（建議 BigQuery） | 趨勢、成本、Issue、命中、回饋、匯出 | 不保存未遮罩完整對話作為一般分析欄位 |
| Transcript Store | 授權對話查詢與脈絡重建 | 不供一般 Dashboard 全表掃描 |
| Operational Store（建議 Firestore） | FAQ、品質案件、Prompt／設定版本、Job 狀態 | 不執行大型 BI 聚合 |
| Audit Store | 高風險管理操作、前後值與結果 | 一般管理角色不可刪除 |
| Cloud Logging／Monitoring | 技術 log、錯誤、SLO、告警 | 不作唯一業務事實來源 |

管理後台不得直接查詢 Agent 執行期記憶體。所有跨服務查詢經後端 API 執行欄位白名單、資料範圍與遮罩。

## 8. 資料分類、遮罩與保存

### 8.1 資料分類

- `INTERNAL`：一般統計、Issue 類型、技術狀態。
- `CONFIDENTIAL`：使用者識別、對話文字、工單與負評內容。
- `RESTRICTED`：Credential、金融個資、客戶資料、法遵指定內容。

### 8.2 遮罩規則

- Credential 類資料原則上不得持久化；偵測後以不可逆標記替代。
- Email、電話、員編、姓名等依角色顯示遮罩或授權原文。
- 分析層使用 pseudonymous actor ID；不得以 email 作 Dashboard group key。
- 匯出套用與畫面相同或更嚴格的遮罩，不得繞過欄位授權。
- 遮罩規則須版本化，事件保存 `maskingPolicyVersion`。

### 8.3 保存期限

- 對話量／Token／成本統計、原始對話、FAQ 命中歷史、知識文件命中／回饋／Issue 歷史、Issue 統計與路由歷史：保存一年。
- 正反例與其來源明細、Quality Case／Gap 明細、Sync Job、Budget／Alert／Notification 歷史：保存一年。
- 模型設定與 Feature Flag 的變更及生效歷史：保存一年；若同一紀錄同時屬於 Audit，仍須遵循較長的稽核保存政策。
- 到期後原始明細刪除；經核准可保留不可逆、無法回推個人的彙總。
- Prompt／FAQ／文件版本歷史：保存期限待治理決議；Phase 0 建議至少保存有效期間加三年，在正式決議前不得宣稱固定期限。
- Legal hold／調查保全由資安法遵定義；若未確認，不得宣稱已支援。
- 現有 Conversation／Handoff 兩年預設值需在上線前與一年政策對齊。

## 9. 身分、角色與授權

### 9.1 角色

| 角色 | 主要能力 |
|---|---|
| System Admin | 平台整合、角色映射、Feature Flag；不可任意查看未遮罩對話 |
| AI Admin | Prompt／模型候選、評測、啟用申請 |
| Knowledge Admin | FAQ／文件／品質案件與知識發布 |
| Service Owner | 查看所屬服務資料、分類、品質與成本，核准治理變更 |
| Analyst／Viewer | 查看授權範圍的遮罩統計與明細 |
| Auditor | 唯讀查看稽核、設定與操作軌跡 |

### 9.2 原則

- 身分來源以 Entra ID SSO 與 App Role／Group mapping 為主。
- 後台資料權限必須同時檢查 capability 與 data scope。
- 查詢未遮罩對話、匯出、Prompt 啟用、模型切換、權限調整為高風險操作。
- 前端隱藏按鈕不是授權；API 必須重新驗證。
- 若 LAB 尚無法串接正式 AA／IAM，Phase 0 只允許測試映射，不建立無治理的正式本地帳號主檔。

## 10. Audit Event 規格

Audit Event 至少包含 actor、actor role、action、target type/id、before、after、reason、result、correlation ID、IP／client context（依政策）、occurredAt 與 retention policy。

以下事件必須 fail closed：權限變更、Prompt／模型啟用、Feature Flag 高風險切換、知識發布／回復、資料匯出、遮罩原文查閱。Audit 寫入失敗時，不完成操作。

Before／After 必須執行 secret redaction；不得把 API key、完整 Prompt 中的秘密或未遮罩對話複製進 Audit。

## 11. 平台與 Terraform 交付

Phase 0 應完成或定版下列 Terraform 目標：

- 獨立 AI Operations Console／Backend 部署單元或明確的 Portal 整合方式。
- Entra 驗證所需設定、Secret 及服務帳號權限邊界。
- Analytics dataset、資料表、partition／cluster 與 retention。
- Operational／Transcript／Audit collection 與 TTL。
- Log sink 或應用事件寫入路徑。
- Cloud Monitoring 基礎 metrics、Dashboard 與 notification channel 介面。
- dev／test／poc／prod 分離，禁止共用 state 與正式資料。
- 備份、復原、資料刪除與部署 runbook。

## 12. API 與資料契約交付

Phase 0 不要求完整管理 UI，但至少交付下列契約：

- Event ingestion interface 與 schema validation。
- Issue taxonomy read API／repository protocol。
- Actor capability／data scope contract。
- Masking service contract。
- Audit append contract。
- Retention／deletion job contract。
- Query service 的分頁、期間、時區、欄位白名單與匯出 job contract。

所有 list API 採 cursor pagination；大型匯出採非同步 Job，不在同步 HTTP request 內產生完整檔案。

## 13. 非功能需求

- 事件寫入不得使一般客服回答增加超過 100 ms 的同步延遲；可採可靠 outbox／非同步管線。
- 關鍵事件在服務重試後不得重複計數，遺失率目標小於 0.1%。
- Dashboard 分析資料 P95 延遲不超過 15 分鐘；Audit Event 應近即時可查。
- 所有 schema 變更需向後相容或提供 migration。
- 敏感欄位需加密傳輸與靜態加密，並使用最小權限 service account。
- 查詢與匯出須具 rate limit、最大期間及最大筆數限制。

## 14. 驗收標準

1. 同一 Turn 的 conversation、request、issue、route、source、feedback、handoff 與 cost 可透過 ID 關聯。
2. 重送同一 `eventId` 不增加統計數量。
3. Dashboard 口徑文件可回答「對話數、Issue 數、命中、解決、成本」如何計算。
4. 至少 20–50 個 seed Issue Type 通過 BU review，且含版本及 owner。
5. 未分類 Issue 不會被丟棄，會進入 `other.unclassified` 並可後續修正。
6. 未授權角色無法取得未遮罩對話或匯出敏感欄位。
7. Credential 測試資料不會出現在 Analytics、Audit 或一般 application log。
8. 一年 TTL／刪除流程可在測試環境以縮短期限驗證。
9. Audit 寫入失敗時，高風險操作 fail closed。
10. dev／test／poc／prod 的資料與 Terraform state 明確隔離。

## 15. 交付物

- Issue taxonomy v1 與治理流程。
- Operational Event schema v1 及資料字典。
- 指標定義表與範例查詢。
- 資料分類、遮罩、保存及刪除決策紀錄。
- 角色／capability／data scope matrix。
- Analytics、Transcript、Operational、Audit 儲存架構決策。
- Terraform 變更設計與環境 inventory。
- 測試資料集、事件 replay 工具規格及驗收報告。

## 16. 待決策事項

| 決策 | 建議預設 |
|---|---|
| Issue taxonomy owner | Service Owner 主責，AI Admin 與 Knowledge Admin 共同維護 |
| Analytics store | BigQuery |
| Transcript store | 與目前 Firestore Conversation 分離的授權 read model |
| 原始對話保存 | 一年；到期刪除，僅留不可逆彙總 |
| Prompt／文件版本保存 | 有效期間加三年，待法遵確認 |
| 使用者識別 | Analytics 僅保存 pseudonymous ID |
| LAB 身分限制 | 測試 mapping 可接受；正式環境必須 Entra SSO |
| 資料更新 SLA | 一般分析 15 分鐘內，Audit 近即時 |

## 17. Definition of Done

Phase 0 只有在以下條件全部成立時完成：

- BU、IT、資安／法遵共同核准指標與資料治理契約。
- Issue taxonomy v1 可被 Agent structured output 或 mapping 使用。
- 關鍵客服路徑能產生 schema-valid、可關聯、可冪等的事件。
- 儲存、TTL、遮罩、授權與 Audit 的自動化測試通過。
- Terraform plan 與環境 inventory 可交接，且不存在未說明的正式手工作業。
- Phase 1 不需要重新定義核心 ID、指標、角色或保存期限即可開始實作。
