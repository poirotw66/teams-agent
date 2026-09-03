# AI 資訊客服營運後台 Phase 3：AI 設定與高風險治理規格

> 文件狀態：Draft for review
>
> 規格版本：v1.1
>
> 需求基準：2026-09-03 提供之《功能需求清單》與《資料保存規則》CSV
>
> 前置條件：Phase 0–2 已完成；已有穩定事件、Issue taxonomy、eval dataset、版本化 FAQ／知識與品質流程
>
> 目標讀者：AI Admin、System Admin、Service Owner、資安、稽核、平台工程師
> 本階段定位：提供 Prompt、模型、參數、Feature Flag、角色與全域治理能力；所有變更必須候選化、評測、審核、漸進啟用、可回復且可稽核。

## 1. 執行摘要

Phase 3 處理最容易影響全體使用者的高風險能力。後台不得提供「直接改 production prompt／model」的普通設定表單，而應採用受治理的 release 流程：

```text
建立候選設定
  → 靜態檢查
  → 離線 Eval 與安全測試
  → 與目前正式版比較
  → 人工核准
  → Test／Canary
  → 正式啟用
  → 監控
  → 必要時 Rollback
```

任何自動優化只能產生 Candidate，不得直接覆蓋 Active 版本。Phase 2 已交付 REQ-014／015 的 POC 唯讀檢視與候選產生；本階段補齊生產所需的 Eval、核准、Canary、啟用與回復治理。

## 2. 對應 BU 需求

| BU 需求 | Phase 3 範圍 |
|---|---|
| REQ-014 | 延伸 Phase 2 唯讀檢視，納入完整 Prompt Registry、版本 diff 與權限治理 |
| REQ-015 | 延伸 Phase 2 Candidate POC，加入可重現 Eval 與生產治理 |
| REQ-016 | Prompt 核准、啟用、Canary、回復與歷史 |
| REQ-020 | 完整角色映射與 capability／data scope 管理 |
| REQ-021 | 跨 FAQ、文件、Prompt、模型、同步、權限、設定的完整 Audit |
| REQ-022 | 模型、Provider、允許參數、Fallback 與設定版本 |
| REQ-026 | 敏感資訊政策、遮罩版本、資料請求與保留治理完成版 |
| REQ-027 | FAQ、文件、Issue、對話、設定與 Audit 的權限感知全域搜尋 |
| REQ-030 | 工單模式與相關 Feature Flag 的受治理切換 |

## 3. 目標與非目標

### 3.1 目標

- 讓授權角色看見目前正式 Prompt／模型／設定及其來源版本。
- 以核准 examples／evaluation set 產生並比較 Prompt Candidate。
- 所有 AI 設定變更皆需評測、審核、部署、監控與回復。
- 提供 Provider／Model allowlist、必要參數與 Fallback 策略版本。
- 提供 Feature Flag 及工單／Handoff 模式的安全切換。
- 完成角色映射、資料範圍、完整 Audit 與全域搜尋。
- 將 PII／敏感資訊遮罩、保存、刪除與 legal hold 納入可治理政策。

### 3.2 非目標

- 不提供任意 Python、LangGraph、SQL、shell 或 system prompt 執行能力。
- 不讓 AI Admin 查看或修改 API key／secret value。
- 不允許未經 allowlist 的 Provider、Model 或參數。
- 不承諾模型更新一定提升品質；必須用 Eval 與 Canary 證明。
- 不讓生成式 AI 自行核准、發布或關閉安全告警。
- 不以 Feature Flag 取代正式部署、資料 migration 或安全審查。

## 4. 高風險治理原則

- Candidate 與 Active 完全分離。
- 生產啟用至少需要提出者以外的一位核准者；資安類變更依政策增加核准。
- Eval 使用固定版本 dataset、taxonomy、knowledge release、模型及評分器。
- 啟用前記錄完整 manifest 與內容 hash。
- Production 採 Canary／percentage rollout；不可直接全量切換，緊急修復除外。
- 監控失敗率、無答案率、負評、Handoff、延遲、成本及 safety regression。
- Rollback 必須不依賴重新撰寫設定，使用既有 immutable release。
- Audit 寫入失敗時 fail closed。

## 5. Prompt Registry

### 5.1 Prompt Definition

- `promptId`：例如 `issue-extractor`。
- `component`、`displayName`、`description`。
- `template`：Prompt 內容；secret 以 reference 表示，不嵌入明文。
- `inputSchemaVersion`、`outputSchemaVersion`。
- `taxonomyVersion`、`faqReleaseId` 等相依版本。
- `version`、`contentHash`。
- `status`：`DRAFT | CANDIDATE | EVALUATED | APPROVED | CANARY | ACTIVE | RETIRED | REJECTED`。
- created／submitted／approved／activated actor 與 timestamps。
- `changeReason`、`rollbackOfVersion`。

### 5.2 Prompt 檢視

- 所有 AI Admin 可辨識目前 Active version、啟用時間、核准者與相依版本。
- Prompt 原文是否可見由 capability 控制；一般角色只看版本與摘要。
- 提供版本 diff，明確區分 system instructions、examples、schema 與 policy blocks。
- 不顯示 secret value；僅顯示 secret reference 是否有效。

## 6. Prompt Candidate 與自動優化

### 6.1 Candidate 產生輸入

- 明確指定 Verified Dataset Version。
- 指定基準 Prompt Version。
- 指定 Issue taxonomy、FAQ／Knowledge release、候選模型及生成策略版本。
- 指定納入／排除的資料期間、Issue、來源與遮罩政策。
- 保存產生者、輸入 manifest、模型 usage、成本與 correlation ID。

### 6.2 安全限制

- 原始未遮罩對話不可送至未核准 Provider。
- Candidate generation 不得修改 Active Prompt。
- 產生後先執行 schema、禁語、secret、prompt injection 與長度檢查。
- Dataset 與 Candidate 必須不可變；重新執行建立新 Candidate。
- 若 dataset coverage 不足或 masking failure，Job 失敗，不產生可核准 Candidate。

### 6.3 人工編輯

AI Admin 可在 Candidate 上編輯，但任何修改都產生新版本並使既有 Eval 失效。不得在 APPROVED／ACTIVE 物件上直接編輯。

## 7. Evaluation 規格

### 7.1 Eval Suite

至少包含：

- Issue classification accuracy／macro F1。
- Positive／negative example precision、recall。
- Route accuracy。
- Clarification appropriateness。
- FAQ key validity。
- Structured output validity。
- Credential／PII 索取與洩漏測試。
- Prompt injection resistance。
- 多 Issue、短句、改述、補充、greeting、non-IT、handoff regression。
- LLM call、latency、Token 與成本比較。

### 7.2 比較與門檻

- Candidate 與目前 Active 使用同一 Eval manifest。
- 顯示整體與各 Issue Type 結果，避免平均值掩蓋重要類別退化。
- Critical safety test 必須全數通過。
- 品質、延遲與成本門檻版本化，由 Service Owner／AI Governance 核准。
- 未達門檻只能 REJECT 或申請有期限、具理由的 policy exception。
- LLM-as-judge 不得是唯一核准依據；需結合 deterministic assertions 與人工抽樣。

### 7.3 Eval Run

狀態：`QUEUED | RUNNING | COMPLETED | FAILED | CANCELLED`，保存 dataset、candidate、baseline、model、runner、metric version、raw result artifact、摘要、成本與 timestamps。

## 8. Prompt 啟用、Canary 與回復

### 8.1 核准

- 提出者不可單獨核准自己的 Candidate。
- 核准畫面顯示 diff、Eval、policy exception、成本與風險。
- 核准只授權特定版本與 deployment target；Candidate 修改後核准失效。

### 8.2 Canary

- 支援 test environment 及 production percentage／allowlisted audience Canary。
- 分流規則不使用敏感屬性，且同一 conversation 維持 sticky version。
- 比較錯誤、Issue、Route、負評、Handoff、latency、cost 與 safety alerts。
- 達停止條件時自動停止擴大並通知；是否自動 rollback 由政策決定。

### 8.3 Rollback

- 一鍵回復至最近健康 immutable version。
- 回復需理由與最終確認；緊急回復可先執行但需事後覆核。
- Runtime 設定切換採原子 pointer／version reference，不出現半套設定。
- 回復後保留失敗版本、Canary 結果與 incident link。

## 9. 模型、Provider 與 Fallback 管理

### 9.1 Model Configuration

- Provider、Model ID、用途元件、status。
- 允許參數白名單：temperature、max output、timeout、retry、top-k 等依元件限制。
- 使用的 secret reference、region／data residency、quota class。
- pricing version、context limit、能力標籤。
- primary／fallback chain 與觸發條件。
- config version、hash、owner、核准與生效時間。

### 9.2 規則

- UI 不接受任意 model name；只能選 allowlist。
- Secret value 由 Secret Manager 管理，後台不可讀回。
- Fallback 必須定義哪些錯誤可切換、最大嘗試、成本與資料邊界。
- 模型切換需跑適用元件 Eval，不因 API 可連線就視為可上線。
- 參數超出安全範圍由 API 拒絕。
- 設定變更沿用 Candidate → Eval → Approval → Canary → Active → Rollback。

## 10. Feature Flag 與系統設定

### 10.1 Feature Flag

- `flagId`、description、owner。
- type：boolean／enum／percentage。
- environment、audience scope、default、rules。
- effectiveAt／expiresAt。
- status、version、etag。
- changeReason、approval、Audit。

至少治理：Ticket mode、Handoff mode、Feedback、Cost display、Knowledge backend evaluation、非關鍵實驗功能。

### 10.2 安全限制

- 影響權限、資料保存、遮罩、Audit 或安全檢查的 flag 不可由一般 UI 關閉。
- Production flag 需核准與到期日；暫時例外到期自動回預設值。
- Percentage rollout 必須 sticky 且可解釋。
- 設定讀取失敗採安全預設，不從前端決定 fallback。

## 11. 角色與權限管理

### 11.1 身分來源

- Entra ID 為人員與群組 source of truth。
- 後台管理的是 App Role／Group 到 capability／data scope 的 mapping，而不是複製公司帳號。
- 若公司 AA／IAM 有既有流程，以申請 deep link／API 整合為主；不建立平行帳號治理。

### 11.2 操作

- 查看角色、capability、data scope 與來源群組。
- 提出 mapping 變更、審核、設定生效／到期時間。
- 緊急撤權近即時生效。
- 不允許操作者授予自己更高權限。
- System Admin 不因平台角色自動取得未遮罩對話權限。

## 12. 完整 Audit 與治理

Audit 支援日期、actor、role、action、target、result、correlation、environment 篩選，並顯示經遮罩 before／after diff、理由、核准與關聯 release／job。

涵蓋：

- FAQ／文件／Prompt／模型／Flag 版本與啟用。
- Sync／Eval／Canary／Rollback。
- Role mapping／data scope。
- 未遮罩對話查閱與匯出。
- Budget／notification policy。
- Retention、redaction、deletion、legal hold。

Audit 一般管理者不可刪除；匯出採獨立 capability。完整性需有 retention lock、外部 sink 或等價防竄改機制。

## 13. 敏感資訊與資料治理完成版

- 模型設定與 Feature Flag 的變更、生效及操作歷史保存一年；若同時屬於 Audit，採較長的稽核保存政策。
- Prompt／FAQ／文件版本歷史的期限依最新保存規則仍待治理決議；在決議完成前不得因一般 TTL 刪除仍被 Active／Rollback／Audit 引用的版本。
- 管理遮罩政策版本、測試集、生效環境與 rollback。
- 提供資料刪除 request、執行狀態、受影響 store 與證明。
- 若法遵要求，提供 legal hold 建立、核准、解除與 Audit。
- Data retention policy 依資料類型版本化；禁止直接改 TTL 而不記錄 migration 計畫。
- 管理資料匯出目的、接收者、欄位、到期與撤銷。
- 提供 masking coverage、failure、unclassified sensitive data 的監控。

遮罩政策本身屬高風險設定，需測試、核准、Canary 及回復；不得用 Feature Flag 任意關閉。

## 14. 全域搜尋

搜尋範圍：FAQ、文件、Issue Type、Quality Case、遮罩對話、Prompt／設定版本及 Audit metadata。

規則：

- 搜尋結果先套用 capability 與 data scope，再產生 snippet。
- 未授權內容不得透過結果數、標題、highlight 或 facet 洩漏存在性。
- 預設不搜尋未遮罩全文；只有額外授權的對話查詢流程可使用。
- 支援類型、Owner、狀態、日期、Issue、環境篩選。
- Prompt、設定及 Audit 搜尋不索引 secret value。
- 每次敏感搜尋及匯出皆 Audit。

## 15. API 能力需求

- Prompt registry、candidate、diff、eval、submit、approve、canary、activate、rollback。
- Model／provider config candidate、eval、approve、activate、rollback。
- Feature Flag list／candidate／approve／activate／disable。
- Role mapping read／request／approve／revoke。
- Audit query／detail／export。
- Retention policy、redaction policy、deletion request、legal hold（若核准）。
- Global search。

所有高風險 mutation 使用 idempotency key、etag、reason、approval token／server-side state validation。不得接受前端傳入 `approved=true` 直接跳過審核。

## 16. UI／UX 規格

- 高風險頁面明確顯示 environment、目前 Active 版本及影響範圍。
- Compare 頁先顯示風險與 Eval，再顯示技術 diff。
- 啟用／回復採「查看影響 → 填理由 → 最終確認」。
- 不使用模糊的「儲存」表示 production 啟用；使用「建立候選」「送審」「開始 Canary」「啟用正式版」。
- 顯示 Job 進度、失敗階段、可重試性與 correlation ID。
- 一般使用者不看到 temperature、schema hash、secret reference 等不必要技術欄位。
- 所有畫面具 loading、empty、error、conflict、forbidden 與 partial-data 狀態。

## 17. 非功能需求

- Runtime config 讀取失敗時使用最後已知健康版本或安全預設。
- 設定切換在目標 SLA 內全 instance 收斂，且同一 conversation 版本一致。
- Eval／Canary／search／Audit export 為非同步可恢復 Job。
- 高風險操作具 rate limit、雙人覆核及 session timeout。
- Active config、Prompt、Model、Flag release 可跨環境重現並驗證 hash。
- 任何 rollout 不得中斷 Teams 正常問答；失敗可在 5 分鐘內回復。
- Audit 與設定版本支援備份、還原演練及完整性檢查。

## 18. 驗收標準

1. 可清楚辨識 Issue Extractor 目前 Active Prompt、版本、核准者及相依 taxonomy／dataset。
2. 使用 verified dataset 產生 Candidate，不會修改 Active Prompt。
3. Candidate 與 baseline 完成同 manifest Eval，顯示分類、路由、安全、延遲及成本比較。
4. Critical safety test 失敗時無法核准或啟用。
5. Prompt 經不同人核准、Canary 後啟用，且可原子回復舊版。
6. 模型只能從 allowlist 選擇，secret 不會顯示於 UI／API／Audit。
7. Fallback 模擬 primary timeout 時依版本化策略執行，且保留成本與結果事件。
8. Ticket／Handoff Feature Flag 可受治理切換、到期回復並 Audit。
9. 操作者無法提高自己的角色，撤權能在目標 SLA 生效。
10. Audit 可追查所有高風險設定的 before／after、理由、核准、結果與 rollback。
11. 全域搜尋不洩漏未授權對話、文件、Prompt 或 Audit 目標的存在性。
12. Retention／redaction policy 可測試、核准、啟用及回復，Credential 不被持久化。

## 19. 上線策略

- 先將現有 code-based Prompt／env 設定匯入 Registry，標記為 baseline，不直接改行為。
- Test 環境完成 replay Eval，再開放 POC Canary。
- 初期只允許少數 AI／System Admin，完成操作演練後再擴大。
- Prompt、模型及 Flag 分開 release，避免一次變更多個變因。
- 每次 production rollout 設定觀察期與自動停止條件。
- 至少完成一次 Prompt、Model Config 及 Feature Flag rollback 演練。

## 20. 待決策事項

| 決策 | 建議預設 |
|---|---|
| Prompt 核准人數 | 至少兩人，提出者不可單獨核准 |
| Canary 比例 | 先 5%，再 25%，最後 100% |
| Canary sticky key | tenant＋conversation pseudonymous key |
| 自動 rollback | 僅 critical safety／availability；其他停止擴大並人工確認 |
| Model allowlist owner | AI Governance＋資安／平台共同核准 |
| Local role management | 不建立；Entra／AA 為 source of truth |
| Legal hold | 由法遵決定；未核准前不宣稱支援 |
| LLM-as-judge | 只作輔助，不作唯一 gate |

## 21. Definition of Done

- Prompt、Model Config、Feature Flag 均採 immutable candidate／release lifecycle。
- Eval dataset、runner、metric、taxonomy、knowledge release 與結果可完整重現。
- Approval、Canary、activation、monitoring、rollback 的端到端演練通過。
- Role mapping、data scope、Audit、retention、redaction 與全域搜尋完成資安測試。
- 現有 code／environment 設定完成 baseline migration，沒有未治理的 production 後門。
- 操作 runbook、事故回復、權限申請、備份還原與 Audit 匯出文件可交接。
- 人工簽核採 `SYSTEM_ADMIN` 一次最終核准（與 Phase 0/1 產品決策一致）；不要求 BU／資安／稽核分別簽核。技術 gate 仍不可被核准略過。
