# 知識營運介面產品與系統規格

> 文件狀態：Draft for review  
> 適用專案：Microsoft Teams IT 智能助手 POC  
> 目標讀者：證券團隊知識維護者、審核者、產品負責人、IT／平台維運人員  
> 預設決策：獨立內部 Web；Teams 保留為一般使用者問答入口，不在第一階段製作 Teams Tab  

## 1. 執行摘要

本介面的目的不是讓非技術使用者操作 RAG，而是讓業務團隊安全地完成知識營運：新增或更新文件、設定適用對象、預覽解析結果、測試問題、送審、發布、觀察回饋與回滾。

產品應將「知識內容生命週期」與「聊天執行期」分離：

```text
知識來源
  → 草稿
  → 解析與規則檢查
  → 問答測試
  → 人工審核
  → 建立不可變發布版本
  → 原子切換正式版本
  → Teams 僅讀取正式發布內容
  → 回饋與到期檢視回到營運工作台
```

第一階段的成功標準是：一位不熟悉 Git、GCP、Terraform、embedding 或 LangGraph 的證券團隊同仁，能在 10–15 分鐘內安全完成一份知識更新，並能自行驗證、發布及回滾。

## 2. 現況與設計前提

### 2.1 現有能力

- 知識來源為 Markdown，支援標題、擁有者、版本、生效日、檢視日及 audience。
- Hybrid RAG 支援 BM25、可選 embedding、文件 ACL、引用與來源圖片。
- Teams 端支援回答後的正負向回饋。
- Agent Service 與 Teams Adapter 已分離；Agent Service 為私有服務。
- 對話與 handoff 可使用 Firestore；部署由 Terraform 與 Cloud Run 管理。
- Gemini File Search 是可替換的實驗性後端，不應成為知識營運介面的直接依賴。

### 2.2 現有限制

- 語料與索引目前偏向在建置／部署時打包，不具備正式的線上發布與回滾流程。
- 知識 metadata 目前多為可選；正式營運時需提高必填與驗證強度。
- 回饋目前主要寫入服務 log，尚不足以形成營運工作台。
- Teams／Entra 群組尚未完整串入，受限文件的 ACL 不宜在此之前全面啟用。
- 現有 `/admin/knowledge-backend` 是技術後端切換能力，不是知識內容管理介面。

### 2.3 核心架構決策

1. 管理介面採獨立內部 Web，使用 Entra ID SSO。
2. Teams 僅負責一般使用者問答；可選擇接收待審、發布失敗或大量負評通知及深層連結。
3. 知識營運介面不得直接寫入聊天服務使用中的索引。
4. 每次發布產生不可變版本，通過檢查後才原子切換 active version。
5. 聊天服務只讀取 `PUBLISHED` 且符合使用者 ACL 的內容。
6. Terraform、Cloud Run、Secret Manager、模型與 chunk 參數僅由 IT／平台角色管理。

## 3. 產品目標與非目標

### 3.1 產品目標

- 降低知識更新對開發者與部署人員的依賴。
- 建立「草稿、審核、發布、回滾」的可追溯治理流程。
- 在發布前發現格式、權限、過期、重複與無法回答的問題。
- 讓負評、未命中與到期文件形成可處理的營運待辦。
- 確保受限知識不因預覽、測試、引用或索引而外洩。
- 保留 Hybrid RAG 與其他 Knowledge Backend 的可替換性。

### 3.2 第一階段非目標

- 不建立通用企業 CMS 或文件協作平台。
- 不讓使用者調整 embedding model、top-k、chunk size、prompt 或 LangGraph 節點。
- 不在 Teams 內嵌完整管理介面。
- 不做多人同步編輯；第一階段採鎖定或樂觀版本控制。
- 不取代原始文件的法定歸檔系統。
- 不讓生成式 AI 自動發布內容。
- 不在第一階段承諾完整 BI、跨部門知識市場或多租戶 SaaS 能力。

## 4. 使用者、角色與責任

| 角色 | 主要工作 | 可見範圍 | 關鍵限制 |
|---|---|---|---|
| 一般使用者 | 在 Teams 查詢 IT 問題、提供回饋 | 只看其 ACL 可存取的已發布內容 | 不可進入營運介面 |
| 知識貢獻者 | 建立草稿、更新內容、設定 metadata、測試、送審 | 自己或所屬單位可維護的文件 | 不可自行發布正式版本 |
| 知識審核者 | 比對差異、檢查權限與測試結果、核准或退回 | 被指派單位的待審內容 | 原則上不可審核自己提交的版本 |
| 知識管理者 | 管理擁有單位、分類、audience、緊急下架、回滾 | 全部知識與稽核紀錄 | 不管理雲端基礎設施 |
| IT／平台管理者 | 身分整合、服務設定、索引工作、部署、監控與事故處理 | 技術設定與營運狀態 | 不替業務決定內容正確性 |
| 稽核／唯讀 | 查閱發布、審核、權限及操作紀錄 | 依稽核授權範圍 | 不可修改任何內容 |

建議採雙人覆核。PoC 若人力不足，可允許知識管理者自行發布，但系統必須留下明確的例外標記與理由。

## 5. 資訊架構與導覽

主選單固定為：

1. 儀表板
2. 知識庫
3. 我的待辦
4. 問答測試室
5. 回饋工作台
6. 發布紀錄
7. 稽核紀錄
8. 設定（僅管理角色）

所有頁面應使用業務語言。介面不得向知識貢獻者顯示向量、embedding、chunk、top-k、temperature、API key、Cloud Run revision 或 Terraform resource 等技術詞彙。

## 6. 功能需求

### 6.1 儀表板

系統應顯示：

- 待我處理：草稿、待修正、待審核、發布失敗。
- 內容健康度：已過檢視日、30 天內到期、缺少擁有者、受限內容待確認。
- 最近 7／30 天：查詢量、知識回答率、未命中、負評、熱門主題。
- 最近發布與回滾事件。
- 系統狀態：正式知識版本、最近成功發布時間、是否存在發布警示。

儀表板不得以模型 token 或推論成本作為業務使用者的主要指標；成本資訊只放在平台管理檢視。

### 6.2 知識庫列表

應支援：

- 以標題、關鍵字、文件編號搜尋。
- 依狀態、擁有單位、分類、audience、檢視日及最後更新者篩選。
- 顯示正式版本、草稿版本、擁有者、下次檢視日、適用對象及健康狀態。
- 批次指派擁有者、調整檢視日與匯出清單；不得批次發布內容。
- 清楚標示「公開給所有員工」與「僅限特定群組」。
- 預設不顯示技術來源路徑；管理者可在詳細資訊中查閱追溯 ID。

### 6.3 新增與更新精靈

新增流程分為五步：

1. 選擇來源：貼上內容、上傳 Markdown；第二階段再支援 PDF、DOCX 或 SharePoint 連結。
2. 基本資料：標題、摘要、擁有單位、業務聯絡人、分類、版本說明。
3. 適用範圍：全體員工或受核准的 Entra 群組；顯示可見人數或群組驗證結果。
4. 生效管理：生效日、下次檢視日、是否取代既有文件。
5. 內容預覽：標題結構、步驟、連結、圖片、敏感資訊與解析警告。

正式營運必填欄位：

- 標題
- 擁有單位
- 內容版本說明
- 生效日
- 下次檢視日
- audience
- 變更原因

版本號由系統產生，不要求非技術使用者手動決定語意版本。

### 6.4 文件編輯與差異檢視

- 第一階段提供表單式 metadata 編輯與 Markdown／純文字內容編輯。
- 顯示目前正式版與草稿的逐段差異。
- 圖片必須有替代文字；外部圖片 URL 預設拒絕或轉存至受控儲存區。
- 儲存時執行版本衝突檢查，避免覆蓋他人修改。
- 自動儲存只存草稿，絕不可自動發布。
- 支援「另存新版本」與「放棄草稿」。刪除正式內容應改為下架，不做實體刪除。

### 6.5 解析預覽與品質檢查

發布前至少檢查：

- 檔案格式、大小、編碼與惡意檔案掃描。
- 必填 metadata、日期邏輯及 audience 是否有效。
- 標題層級、空白內容、失效連結、缺圖、圖片替代文字。
- 疑似密碼、API key、個資、客戶資料或機密資訊。
- 與既有知識高度重複或互相矛盾。
- 內容是否包含「聯絡某人」但缺少明確窗口或有效期限。
- 解析後可被檢索的段落預覽；對業務使用者稱為「系統可讀段落」，不顯示向量資料。

檢查結果分級：

- `BLOCKING`：不可送審或發布，例如 audience 無效、疑似機密、空內容。
- `WARNING`：可送審，但審核者必須確認，例如內容重複、檢視日過近。
- `INFO`：改善建議，不影響流程。

### 6.6 問答測試室

知識貢獻者應能針對草稿建立至少三個測試問題，包含：

- 典型問法。
- 口語或簡短問法。
- 容易與其他文件混淆的問法。

測試結果應顯示：

- 模擬回答。
- 使用的來源標題與段落。
- 是否命中新草稿。
- 是否引用到不應使用的其他文件。
- 使用不同 audience 身分模擬時，是否可見。
- 通過、需確認或失敗，以及可理解的原因。

測試室不得允許貢獻者任意冒充高權限群組。可模擬的 audience 必須受其角色與審核流程控制。正式發布門檻至少包含：所有必填測試執行完成、無 ACL 洩漏、無 blocking issue。

### 6.7 送審與審核

送審時系統建立不可修改的 review snapshot，內容包括：

- 草稿內容與 metadata。
- 與正式版的差異。
- 品質檢查結果。
- 問答測試結果。
- 提交人、時間與變更原因。

審核者可核准、退回修改或拒絕。退回與拒絕必須填寫原因。草稿在送審後如有任何修改，原核准失效並產生新的 review snapshot。

涉及 audience 從受限改為全體員工、疑似敏感資料、緊急政策或大量文件變更時，應要求知識管理者額外核准。

### 6.8 發布、下架與回滾

發布流程：

```text
核准版本
  → 建立候選知識版本
  → 完整解析與索引
  → ACL／回歸／冒煙測試
  → 產生發布 manifest
  → 原子切換 active version
  → 驗證 Teams 正式問答
  → 標記發布成功
```

發布必須符合：

- 每次發布有唯一 release ID、內容雜湊、文件清單、索引設定版本及建立時間。
- 發布中的版本不可被修改。
- 正式服務在整個切換過程只能看到完整舊版或完整新版，不可看到半套索引。
- 發布失敗時維持舊版，不影響 Teams 問答。
- 發布後自動執行關鍵問答與 `/readyz` 類健康檢查。
- 支援一鍵回滾至最近一個健康版本；回滾需填原因並留下稽核紀錄。
- 緊急下架可立即將單份文件排除，但仍需事後補審。

第一階段不建議讓知識發布觸發 Terraform apply。基礎設施部署與內容發布應完全分離。

### 6.9 回饋工作台

應彙整：

- 負評回答。
- 無知識／低信心結果。
- 熱門但未覆蓋的問題。
- 被引用但持續負評的文件。
- 使用者可選填的原因與補充文字。

每一筆營運事件應可指派、分類、合併及結案，並連回：

- 原問題與回答。
- 引用文件及發布版本。
- audience 與知識後端。
- correlation ID；個資須依權限遮蔽。

建議結案原因包含：已更新知識、回答其實正確、問題不在範圍、權限問題、系統問題、重複事件。回饋原始資料應從 log 升級為可查詢的受控資料儲存。

### 6.10 到期檢視

- 在檢視日前 30、14、7 天通知擁有者。
- 擁有者可確認內容仍有效並產生一個「無內容變更的覆核版本」。
- 超過檢視日顯示警示，但不自動下架，除非該分類政策明確要求。
- 長期無擁有者或逾期內容應升級通知知識管理者。

### 6.11 通知

第一階段以 Email 或 Teams 訊息通知下列事件，但所有操作均回到 Web：

- 被指派審核。
- 草稿被退回。
- 發布成功或失敗。
- 文件即將到期。
- 文件被緊急下架或回滾。
- 負評超過門檻。

通知內容不得包含受限文件全文或敏感片段。

## 7. 文件生命週期

```text
DRAFT
  ├─→ IN_REVIEW
  │      ├─→ CHANGES_REQUESTED → DRAFT
  │      ├─→ REJECTED
  │      └─→ APPROVED → PUBLISHING → PUBLISHED
  │                                  ├─→ SUPERSEDED
  │                                  ├─→ UNPUBLISHED
  │                                  └─→ ROLLED_BACK
  └─→ DISCARDED

PUBLISHING ─失敗→ PUBLISH_FAILED → APPROVED（可重試）
```

狀態轉換必須由伺服器端驗證，不可只依賴前端隱藏按鈕。`PUBLISHED` 版本不可編輯；更新一定建立新版本。

## 8. 資料模型

### 8.1 Knowledge Document

- `document_id`：永久識別碼，不隨標題或檔名改變。
- `title`
- `summary`
- `category`
- `owner_unit_id`
- `business_contact`
- `classification`
- `audience_type`：`ALL_EMPLOYEES` 或 `RESTRICTED_GROUPS`。
- `audience_group_ids`
- `current_published_version_id`
- `status`
- `created_at`、`created_by`、`updated_at`、`updated_by`

### 8.2 Knowledge Version

- `version_id`、`document_id`、`version_number`
- `source_type`、`source_object_uri`、`content_hash`
- `canonical_content`
- `change_summary`、`change_reason`
- `effective_at`、`review_due_at`
- `metadata_snapshot`
- `validation_summary`
- `created_at`、`created_by`

### 8.3 Review

- `review_id`、`version_id`
- `snapshot_hash`
- `reviewer_id`、`decision`、`comment`
- `submitted_at`、`decided_at`
- `policy_exceptions`

### 8.4 Test Case／Test Run

- 測試問題、預期文件、預期可見 audience、可選關鍵點。
- 實際回答、引用、使用後端、執行時間、結果與失敗原因。
- 測試案例本身需版本化，避免發布後無法重現。

### 8.5 Release

- `release_id`、`status`
- 文件與版本清單。
- corpus hash、index artifact URI、index setting version。
- 建立、啟用、驗證與回滾時間。
- 前一 active release ID。
- 發布者、核准資訊、失敗摘要。

### 8.6 Feedback Case

- correlation／conversation／issue ID。
- rating、reason、comment。
- answer snapshot 或受控引用、引用文件版本。
- assigned_to、resolution、resolved_at。
- 使用者識別資訊應依保留政策最小化或雜湊。

### 8.7 Audit Event

- actor、角色、時間、來源 IP／session、action。
- target type／ID、before／after hash、reason。
- result、correlation ID。
- 稽核資料追加寫入，不允許由一般管理介面修改。

## 9. 權限與安全規格

### 9.1 身分驗證

- 使用公司 Entra ID OIDC／OAuth SSO，不建立獨立密碼。
- 僅允許核准 tenant；停權或離職帳號不得登入。
- 後端必須驗證 token issuer、audience、tenant、有效期及必要 claims。
- 高風險操作可要求近期重新驗證或條件式存取。

### 9.2 授權

- 角色與可管理單位由可信任目錄或後端資料映射，不採信瀏覽器傳入的角色文字。
- 文件 audience 必須使用不可變的 Entra group ID；介面另顯示群組名稱。
- 群組刪除、改名或無法解析時阻擋發布。
- 預覽、搜尋、測試、匯出、通知及稽核頁面均須套用相同 ACL 原則。
- 平台 service account 採最小權限；聊天讀取與管理寫入使用不同身分。

### 9.3 資料保護

- 傳輸與儲存加密。
- 原始檔、候選索引、正式索引與稽核紀錄分區或分 bucket prefix 管理。
- 上傳檔案執行 MIME 驗證、大小限制、惡意程式掃描及檔名正規化。
- 禁止將 secret、客戶個資或未核准機密內容送入外部模型。
- 記錄內容最小化；一般 log 不寫完整文件、完整回答或 access token。
- 明確定義原始檔、版本、回饋與稽核紀錄的保存期限及 legal hold 例外。

### 9.4 ACL 上線閘門

在 Teams／Entra 真實群組尚未可靠映射前：

- 不得宣稱受限文件 ACL 已可正式使用。
- 受限文件只能停留於草稿／測試環境，或由明確核准的暫行規則處理。
- 正式啟用前需完成正向、負向、群組移除、超過群組上限及快取失效測試。

## 10. 系統架構

### 10.1 邏輯元件

```text
Entra ID
   │ SSO / roles
   ▼
Knowledge Operations Web
   │
   ▼
Knowledge Admin API ──────→ Metadata / workflow / audit store
   │                         (Firestore or approved database)
   ├────→ Source object store
   ├────→ Validation and indexing job
   ├────→ Evaluation runner
   └────→ Notification adapter

Approved version
   ▼
Versioned index artifact store
   │ active release pointer
   ▼
Private Agent Service / Knowledge Service
   ▲
Teams Adapter ← Microsoft Teams
```

管理 API 與現有 Agent chat API 應分離。即使初期部署於同一專案，也應使用不同路由邊界、服務身分與 IAM；正式階段建議獨立 Cloud Run service。

### 10.2 儲存建議

- Firestore／核准資料庫：文件 metadata、工作流程、測試結果、回饋案件及 active release pointer。
- Cloud Storage／核准物件儲存：原始檔、圖片、解析產物、不可變索引 artifact 與 release manifest。
- 不把大檔案或完整索引存入 Firestore document。
- 每個環境使用獨立 bucket、collection namespace、service account 與 release pointer。

### 10.3 執行期索引策略

目標態應由 Agent Service 載入「指定 release 的不可變索引」，而不是把每次內容更新綁定到應用程式 image。切換可採：

1. 新 revision 啟動時下載指定 release 並通過 readiness 後接流量；或
2. 服務背景下載、驗證後原子替換記憶體 index。

PoC 初期優先採第一種，行為較容易理解及回滾；驗證頻繁發布需求後再考慮不中斷熱切換。無論採何者，內容發布都不應執行 Terraform apply。

### 10.4 Knowledge Backend 邊界

- 管理介面管理的是 canonical knowledge 與發布版本，不直接操作 Hybrid 或 Gemini File Search。
- Index Publisher 依後端 adapter 產生所需 artifact／同步結果。
- 後端切換是平台管理行為，必須與內容審核權限分離。
- Gemini File Search 在具備完整文件同步、刪除、版本、ACL 與回滾驗證前維持候選能力。

## 11. 管理 API 能力需求

此處定義能力，不鎖定 URL 或框架：

- 文件列表、詳細資料、建立與更新草稿。
- 上傳原始檔及取得安全預覽。
- 執行驗證並取得結構化檢查結果。
- 建立及執行問答測試。
- 送審、核准、退回、拒絕。
- 建立發布、查詢進度、啟用、回滾、緊急下架。
- 查詢 feedback case、指派與結案。
- 查詢稽核紀錄及匯出。
- 查詢系統健康度與 active release。

所有寫入 API 必須支援：

- 伺服器端 RBAC／ABAC。
- request／correlation ID。
- idempotency key，避免重複發布或重複審核。
- optimistic concurrency／ETag。
- 結構化錯誤代碼與可理解的前端訊息。
- 完整 audit event。

## 12. 非功能需求

### 12.1 可用性與效能

- 一般列表與詳細頁 p95 小於 2 秒；大型檔案處理可採非同步工作。
- 發布過程不降低既有 Teams 問答可用性。
- 發布失敗時自動保留舊版。
- 管理後台目標可用性初期 99.5%；聊天服務可另訂較高目標。

### 12.2 可存取性與易用性

- 支援桌面瀏覽器，繁體中文為第一語言。
- 符合 WCAG 2.1 AA 的核心表單、鍵盤操作、對比與錯誤提示。
- 重要狀態不可只用顏色表示。
- 每個阻擋訊息需說明「發生什麼、誰能處理、下一步是什麼」。

### 12.3 可觀測性

至少監控：

- 上傳、驗證、索引、發布各階段成功率與耗時。
- active release、各 instance 載入的 release 是否一致。
- 索引文件數／段落數異常變化。
- 發布後關鍵問答通過率。
- ACL 拒絕與異常群組數量，但不記錄敏感內容。
- 回饋率、負評率、未命中率及到期文件數。

### 12.4 備份與復原

- metadata、workflow 與 audit store 依公司政策備份。
- 原始檔與發布 artifact 啟用版本控制及保留策略。
- 回滾不依賴重新解析原始檔，應直接切回已驗證的不可變 artifact。
- 定期演練單份文件下架、完整版本回滾及 metadata 復原。

## 13. 錯誤與例外處理

| 情境 | 系統行為 |
|---|---|
| 檔案格式不支援 | 不建立可送審版本，說明支援格式與修正方式 |
| audience 群組不存在 | 阻擋送審／發布，不可自動改為全體員工 |
| 解析或索引失敗 | 保留草稿與舊正式版，提供可重試事件 ID |
| 發布後冒煙測試失敗 | 不切換或自動切回前版，通知平台與提交者 |
| 兩人同時修改 | 保留雙方內容，要求比較後合併，不靜默覆蓋 |
| 原始來源遭移除 | 已發布版本仍可追溯；建立待處理警示 |
| 模型不可用 | 允許完成內容編輯；標記問答測試暫不可用，不誤判為通過 |
| 稽核寫入失敗 | 高風險寫入採 fail closed，不完成發布／權限變更 |

## 14. 驗收規格

### 14.1 核心業務驗收

1. 非 IT 使用者可用 SSO 登入，且只看到被授權的單位與功能。
2. 貢獻者可新增文件、完成必填欄位、預覽解析結果及建立測試問題。
3. 系統能阻擋 audience 不存在、空內容及疑似 secret 的文件。
4. 貢獻者不能發布自己的內容；審核者能比較差異並留下決策理由。
5. 發布失敗不影響 Teams 既有問答，active release 不變。
6. 發布成功後，指定測試問題可在正式環境命中新版本並顯示正確引用。
7. 未授權群組在搜尋、測試及 Teams 問答均無法取得受限文件。
8. 管理者可在 5 分鐘內回滾，回滾後正式問答回到前一版本。
9. 每次新增、修改、送審、核准、發布、下架與回滾均可查到稽核事件。
10. 負評可在工作台被指派、追蹤並連回當時的文件版本。

### 14.2 技術上線閘門

- 身分與角色滲透測試通過。
- ACL 正向與負向測試通過，且已驗證真實 Entra group mapping。
- 發布併發、重試、重複請求及部分失敗測試通過。
- 至少一次完整回滾與災難復原演練通過。
- 重要操作 audit coverage 為 100%。
- 既有 RAG 評估集未出現超過核准門檻的退化。
- Terraform 管理新增雲端資源，但不管理知識內容本身。

## 15. 分期建議

### Phase 0：現在完成規格與治理基線（建議立即做）

- 確認角色、擁有單位、審核責任與 audience 命名來源。
- 盤點全部文件，補齊 owner、review date、audience 與來源。
- 定義 20–30 個黃金問答及 ACL 負向案例。
- 確認發布與回滾責任，不先做完整 UI。

完成條件：沒有「無擁有者」的正式文件，且證券團隊能理解並簽認治理流程。

### Phase 1：交接型 MVP（POC 核心流程穩定後優先做）

- Entra SSO 與 RBAC。
- 儀表板、知識列表、Markdown 新增／更新、metadata 表單。
- 解析預覽、基本品質檢查、測試室。
- 送審、核准、不可變發布、回滾、稽核紀錄。
- Email／Teams 通知深層連結。
- 先支援小量文件與單一業務單位。

不納入：PDF／DOCX 完整解析、SharePoint 同步、進階 analytics、Teams Tab。

### Phase 2：正式知識營運

- PDF／DOCX、圖片 OCR 與受控 SharePoint 匯入。
- 可查詢 feedback store 與營運案件流程。
- 到期覆核、自動提醒、重複／衝突偵測。
- 批次匯入、發布排程、完整報表與 SLA。
- 多單位委派與更細緻 ABAC。

### Phase 3：需求證實後再做

- Teams Tab 包裝同一個 Web URL。
- 多知識庫、多語系、跨部門內容重用。
- 自動建議修稿，但仍維持人工發布。
- 後端熱切換或更進階的零停機索引同步。

## 16. 建議時程與估工邊界

在一名後端、一名前端／全端、兼任 UX 與平台支援的條件下：

- Phase 0：1–2 週，主要是治理決策、語料盤點與驗收資料。
- Phase 1：6–10 週，取決於 Entra 權限申請、發布 artifact 改造與資安審查。
- Phase 2：再 6–12 週，文件格式、SharePoint、回饋資料與報表會顯著增加範圍。

以上為規劃級範圍，不是承諾工期。正式估工前需先完成 Entra app／group 權限、資料保存政策、部署環境及審核人力確認。

## 17. 上線與移轉計畫

1. 將現有 Markdown 與 metadata 轉成 `Knowledge Document`／`Version`，保留來源路徑作追溯欄位。
2. 以目前正式索引建立 `release-0001`，不得假設 Git 中資料等於線上資料。
3. 執行文件數、標題、內容 hash、ACL、圖片及黃金問答比對。
4. 先由 IT 與一名證券知識管理者試用，再開放貢獻者。
5. 初期所有發布由 IT 旁站；連續三次正常發布與一次回滾演練後移交。
6. 交接時提供角色名冊、操作手冊、異常處理、回滾演練紀錄與平台升級窗口。

## 18. 交接文件清單

- 知識維護者快速手冊。
- 審核者檢查表。
- 發布與回滾 Runbook。
- audience／Entra group 對照與申請流程。
- 文件分類、命名、檢視週期與下架政策。
- 黃金問答與 ACL 測試案例。
- 平台監控、告警、備份、復原與事故處理 Runbook。
- Terraform resource inventory、環境差異及部署權限說明。
- 已知限制、風險接受與第二階段 backlog。

## 19. 待決策事項與建議預設值

| 待決策 | 建議預設 |
|---|---|
| 是否放進 Teams | 第一階段否；僅通知與深層連結 |
| 是否允許自審自發 | 否；PoC 例外需記錄理由 |
| 首批輸入格式 | Markdown／貼上文字 |
| 正式發布方式 | 不可變 artifact + 新 revision 載入 + 健康後切流量 |
| 過期是否自動下架 | 否；先警示與升級，敏感分類另訂政策 |
| audience 識別 | Entra group immutable ID |
| 是否保留 Hybrid RAG | 是；管理介面不綁定特定 backend |
| 是否現在完整開發 | 先做 Phase 0；核心 POC 穩定且交接日期明確後做 Phase 1 |
| 是否導入 SharePoint | Phase 2；確認來源責任與同步衝突規則後再做 |

## 20. Definition of Done

知識營運介面第一階段只有在以下條件全部成立時才算完成：

- 非技術維護者完成一次新增、更新、測試、送審與發布，無需 CLI、Git、GCP Console 或 Terraform。
- 審核者可理解內容差異、適用對象與測試結果。
- 正式聊天只讀取核准版本，發布失敗不影響既有服務。
- ACL 已在真實身分與群組情境完成正負向驗證。
- 回滾、稽核、備份與事故處理已演練，不只是文件存在。
- IT／平台與證券團隊的責任邊界已簽認。
- Teams Tab、進階文件解析與完整 BI 未被誤列為第一階段完成條件。
