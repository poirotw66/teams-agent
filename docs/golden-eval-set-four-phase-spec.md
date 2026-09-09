# Golden Eval Set 四階段功能與驗收規格

> 版本：v0.1｜日期：2026-09-09｜狀態：待使用者確認，尚未授權開發
>
> 本文件是新增能力的提案，不代表功能已完成。此次只新增規格文件，不修改程式碼。
>
> 讀者：BU／Service Owner、Knowledge Admin、AI Admin、平台工程師、QA、資安。
>
> 階段代號 GE-1～GE-4 與既有後臺 Phase 0～3 不同，避免混淆。

## 1. 目標與範圍

讓 BU 能維護重要驗收問題，確認候選系統相較正式基準版有哪些改善與退步，並追溯答案依據與發布決策。

本規格覆蓋：題庫治理、真實 RAG 評測、Agent 行為評測、發布門檻與營運回歸。不是每個 chunk 強制生成問答，也不將 LLM 自動生成或自動評分視為人工核准。

Golden Eval Set 為經審核、版本固定的驗收案例集合。Synthetic QA 僅是候選来源之一。案例可測回答、澄清、拒答、權限、工具與多輪行為，不要求每題都有標準答案。

### 1.1 現有能力與接點

| 現有模組 | 可重用能力 | 本規格新增／調整 |
|---|---|---|
| `example_domain` | FAQ／DOCUMENT／CONVERSATION／MANUAL來源、Issue／Route、審核、遮罩 | 以來源連結轉成候選，不將現有VERIFIED直接升級Golden |
| `governance_domain/eval_runtime.py` | 隔離Agent流程與固定fixture | 保留flow regression；另建固定知識版本的真實檢索評測 |
| `governance_domain/models.py` 的EvalRun | dataset／knowledge／runner／metric／manifest與基準欄位 | 新增Golden執行模型，以明確連結接回治理，不覆寫舊結果語意 |
| `quality_domain` | 負評／無答案、改善案件 | 案件加入候選、評測失敗建立改善案件，雙向可追溯 |
| 既有Prompt／模型治理 | 核准、Canary、啟用、Rollback | GE-4將有效評測決策加入服務端發布檢查 |
| FAQ／文件／同步 | 來源版本與知識發布資訊 | GE-2確認可載入固定來源及候選索引；GE-4分離候選建置與正式啟用 |

現有fixture評測明確標示 `knowledgeQualityAcceptance=False`；不得僅因既有Eval通過，顯示「真實知識品質已驗收」。

### 1.2 不在此次範圍

- 替換目前Agent框架、向量庫或知識管理介面。
- 強制接入LangSmith／Ragas SaaS；可另做adapter，不作首版前置條件。
- 自動以驗收保留集優化Prompt、生成訓練資料或更改正式內容。
- 執行任意程式碼、任意工具名稱或以正式使用者身分進行真實派工／通知。
- 宣称通過有限題庫等於所有情境零風險。

## 2. BU介面與操作規範

新增單一導覽入口「品質驗收」，放在現有知識營運工作區；既有Prompt／模型頁提供深連結，切換後保留來源與篩選上下文。

| 頁面／建議路由 | 主要資訊 | 主要動作 |
|---|---|---|
| 驗收題庫 `#/knowledge_ops/evaluation/cases` | 標題、類型、來源、Owner、審核／待複核狀態、所屬題庫 | 新增、由來源建立、送審、複核 |
| 題庫版本 `#/knowledge_ops/evaluation/sets/:id` | 案例版本、覆蓋、開發／保留集、版本差異 | 編輯草稿、發布版本、查看差異 |
| 執行驗收 `#/knowledge_ops/evaluation/runs/new` | 題庫、基準、候選、模式、預估成本與限制 | 預檢、執行 |
| 驗收结果 `#/knowledge_ops/evaluation/runs/:id` | 新增失敗、已修復、重大失敗、未完成、耗時／成本 | 查看逐題證據、人工覆核、建立改善案件、匯出 |

導覽仍以「驗收題庫／執行驗收／驗收結果」三頁籤呈現，題庫版本是第一頁籤內的子頁。

### 2.1 核心使用流程

1. 從文件、FAQ、對話或品質案件選「加入驗收題」，帶入來源與遮罩後內容。
2. 編輯者設定答案必要重點、依據及應有行為；技術欄位收在進階區。
3. 審核者檢查來源、正確性與資料範圍，核准案例版本。
4. 發布不可變題庫版本，選正式基準版與候選版執行。
5. BU從退步題目進入「問題／預期／實際／依據／原因」比較；AI Admin可展開檢索與工具trace。

### 2.2 UX共同驗收

- 必填欄位依類型顯示：拒答案例不強迫填可回答證據，回答案例需有重點及依據。
- 題目清單支援文字、Owner、類型、來源、狀態、待複核、題庫篩選，分頁與返回保留條件。
- 表單未儲存離開提示；送出防重；錯誤保留輸入內容並提供可重試動作。
- 不以只有顏色區分通過／失敗／未判定；鍵盤可完成表單與對話框操作。
- 空白狀態說明下一步；權限不足說明限制但不洩漏受限題目內容。
- 結果預設按重大失敗、新增失敗、未完成排序，技術總分不是唯一結論。
- 每個結果顯示「測試模式」「題庫版本」「候選版本」「完成比例」；部分執行不得顯示整體通過。
- 長工作跨頁／重新整理可恢復；GE-2先以可配置輪詢取得狀態，不強制新增SSE基礎設施。

## 3. 共用資料契約

建議獨立 `evaluation_domain`、`evaluation_routes`、背景runner與分頁前端模組；不得把全部邏輯集中至main.js、governance_routes或單一eval_runner。

### 3.1 主要物件

| 物件 | 必要欄位與規則 |
|---|---|
| EvalCase | caseId、tenantId、ownerUnitId、title、currentRevisionId、createdBy／At；穩定識別碼 |
| CaseRevision | revisionId、caseId、schemaVersion、query或turns、personaFixtureRef、criteria、evidence、behavior、toolConstraints、tags、criticality、provenance、status、etag、review紀錄、contentHash |
| EvalSet | setId、tenantId、owner範圍、name、purpose=DEVELOPMENT或HOLDOUT、負責人 |
| EvalSetVersion | setVersionId、version、固定caseRevisionIds、coverage、manifestHash、publishedBy／At、status；發布後不可改成員 |
| TargetManifest | 程式revision、Prompt／模型版本與參數、知識／FAQ版本、chunking／embedding／retriever／reranker設定雜湊、taxonomy、工具契約／fixture、ACL策略、環境 |
| EvaluationRun | runId、setVersionId、baselineManifest、candidateManifest、mode、status、runner／metric／judge版本、limits、requestedBy、時間、結果計數、實際成本、correlationId |
| CaseExecution | runId、caseRevisionId、targetSide、attempt、run狀態、answer、evidenceRefs、traceRef、metricResults、失敗分類、token／耗時／成本 |
| ReviewDecision | caseExecutionId、原判定、新判定、理由、reviewer、時間；append-only，不改原始trace |
| GatePolicyVersion／GateDecision | 適用發布類型、requiredSuites、門檻、有效期限、決策、對應manifest／run、核准資訊 |

`toolConstraints`在GE-1先保留schema，GE-3才執行；介面不可讓使用者誤認尚未支援欄位已有驗證能力。

### 3.2 CaseRevision內容

- `criteria.requiredFacts`：應涵蓋的事實，每項穩定criterionId，可指定精確值、單位、容差或語意規則。
- `criteria.forbiddenClaims`：不得出現的內容；`referenceAnswer`選填，只作參考，不逐字比對全文。
- `evidence`：documentId／faqId、versionId、section／page、必要證據文字或安全artifactRef、contentHash、可替代證據群組。
- 多證據以「必須全部群組成立、群組內可任一替代」表達，避免合法替代文件被判錯。
- `behavior`：ANSWER_WITH_CITATION、CLARIFY、REFUSE、HANDOFF或工具任務；多輪可逐輪指定。
- `toolConstraints`：required／allowed／forbidden工具、參數schema／值約束、必要順序邊、最大呼叫次數；不存可執行程式。
- `provenance`：人工／真實案件／合成、來源版本、生成模型與prompt版本、原始Example／Case連結、遮罩版本。
- `criticality`：CRITICAL或NORMAL；tags涵蓋single-hop、multi-hop、ambiguous、no-answer、ACL、conflict、citation、multi-turn等。
- 不以chunkId作唯一答案依據；每次run另保存實際取回chunk ID與對應來源映射。

### 3.3 版本與狀態機

- 案例：DRAFT → IN_REVIEW → APPROVED或REJECTED；DRAFT／REJECTED可修改；送審內容鎖定。修改已送審／核准內容須新建revision。
- 退役以RETIRED狀態停止納入新題庫，不修改舊題庫快照。
- 來源變更建立獨立VALID／NEEDS_REVIEW／SOURCE_UNAVAILABLE標記，不改舊版本內容。NEEDS_REVIEW案例不得加入新正式驗收版本。
- 題庫版本：DRAFT → PUBLISHED → RETIRED；發布後內容不可變。刪除前檢查引用與保留政策。
- 執行：QUEUED → RUNNING → COMPLETED／FAILED／CANCELLED；取消中為CANCELLING。worker失聯後由lease機制接手或標失敗。
- 執行完成與品質分離：result=PASS／FAIL／INCONCLUSIVE／NOT_APPLICABLE。COMPLETED不等於PASS。
- gate決策：PASS／BLOCK／REVIEW_REQUIRED；缺資料、未校準、部分結果、版本不合均不得PASS。

### 3.4 權限與隔離

新增capability：`ops.evals.read`、`write`、`review`、`sets.publish`、`run`、`results.review`、`export`、`holdout.read`、`gates.manage`；沿用現有角色映射及tenant／Owner資料範圍。

| 角色 | 預設能力提案 |
|---|---|
| Knowledge Admin | 範圍內案例建立／送審、查看開發集與結果 |
| Service Owner | 範圍內案例審核、題庫發布、結果人工覆核 |
| AI Admin | 執行、比較、技術診斷；不因角色自動取得所有保留集答案 |
| Viewer／Auditor | 授權範圍唯讀／稽核；匯出另授權 |
| System Admin | 政策與能力配置；仍須依案件內容權限讀取 |

- 案例作者不得核准自己的版本；題庫發布者必須具有所有成員的發布權限。
- HOLDOUT需獨立能力且不得匯入Prompt優化／生成器；一般執行者可看匯總，逐題內容與匯出另檢查holdout.read。
- 開發／保留集發布時檢查共同case、來源案件及近似題；人工確認近似，不以自動相似分數直接刪題。
- 評測身分從受控persona fixture產生，不接受任意正式token或任意跨租戶身分。
- 預期答案、受限證據不傳入受測Agent；judge只在受控評分流程取得必要資料。
- Audit保存建立、修改、送審、核准、發布、執行、取消、匯出、人工覆核、門檻變更、例外與清除。關鍵治理動作稽核失敗時不得完成。

### 3.5 API共通規範

新增前綴 `/api/evaluations`。列表支援cursor、limit（預設25／最大100）、q、ownerUnitId及各資源狀態；回傳items、nextCursor、total（無法精確計算時為null）。日期UTC ISO8601，介面台北時間。

建立／送審／發布／執行採Idempotency-Key；修改與狀態轉換帶If-Match或expectedEtag。回傳409表示版本／狀態衝突，422表示驗證失敗，403為禁止動作；不可見資源404避免枚舉。

錯誤統一code、message、fieldErrors、correlationId、retryable。非同步動作202含jobId／statusUrl；同步建立201；讀取／狀態轉換200。所有sourceRef由伺服器重新檢查來源存在、版本與權限。

## 4. GE-1：題庫管理與人工治理

### 4.1 功能需求

| ID | 需實作項目 |
|---|---|
| GE1-01 | Case／Revision／Set／SetVersion repository與service；開發FILE、正式共享持久儲存，沿用專案模式；發布與引用更新具原子性 |
| GE1-02 | 題目列表、依類型的表單、證據來源選擇、送審／退回／核准、版本diff |
| GE1-03 | FAQ／文件／對話／品質案件與現有Example「加入驗收題」；來源與遮罩欄位預填 |
| GE1-04 | 題庫草稿編輯、固定版本發布、覆蓋統計、HOLDOUT隔離、重複檢查 |
| GE1-05 | 文件／FAQ選擇後非同步生成候選；可取消、限制題數／token／成本；人工核准前不得進Golden |
| GE1-06 | JSONL完整schema匯入／匯出；CSV提供單輪基本欄位模板，多輪／工具進階資料用JSONL，拒絕靜默截斷 |
| GE1-07 | 來源版本變更標記待複核；本階段僅建立提示，完整影響與發布阻擋於GE-4 |

匯入先dry-run，回報逐列錯誤與近似題；確認commit後原子建立整批，失敗不留下不明部分資料。匯出依欄位權限遮罩，CSV防止試算表公式注入。不得自動批次核准既有Example。

生成器預設從文件章節與情境出題，允許跨文件選取；chunk可供生成參考，但不是每chunk固定配額。產出必須附來源與生成版本；預算不足標記停止，不自動擴額。

### 4.2 API

| Method／Path（省略共同前綴） | 輸入／回應重點 |
|---|---|
| GET／POST `/cases` | 篩選列表／建立title、sourceRef、revision內容；回傳case＋revision |
| GET `/cases/{id}` | metadata、可見revision清單與來源健康狀態 |
| POST `/cases/{id}/revisions` | baseRevisionId與新內容；建立新草稿 |
| PATCH `/cases/{id}/revisions/{rev}` | 僅修改草稿／退回版本，必須etag |
| POST `.../{rev}/submit`、`review`、`retire` | review含decision與reason，伺服器檢查核准人分離 |
| GET／POST `/sets`、GET `/sets/{id}` | 題庫基本資料、purpose、Owner範圍 |
| POST `/sets/{id}/versions` | 建立草稿，含caseRevisionIds |
| PATCH `/sets/{id}/versions/{version}` | 草稿成員修改及etag |
| POST `.../{version}/publish`、`retire` | 發布預檢／雜湊／稽核、退役 |
| POST `/candidate-jobs` | sourceRefs、types、count、limits；回傳202 |
| GET `/candidate-jobs/{id}`、POST `.../cancel` | 進度、候選ID、失敗與已用成本 |
| POST `/imports/validate`、POST `/imports/{id}/commit` | 回傳逐列診斷／原子提交結果 |
| POST `/exports`、GET `/exports/{id}` | 範圍／格式；非同步產檔，下載重新授權 |

### 4.3 驗收

| ID | Given／When／Then |
|---|---|
| GE1-A01 | 文件建立候選後，BU可看到問題、必要重點、版本依據；未核准不可發布入題庫 |
| GE1-A02 | 已發布v1後修改案例，必須建立新revision；v1成員及manifestHash保持不變 |
| GE1-A03 | 作者自行核准被拒絕；其他有權限審核者核准成功且Audit完整 |
| GE1-A04 | 跨Owner來源／HOLDOUT無權讀取、搜尋、匯出均不得洩露內容 |
| GE1-A05 | 更新來源後顯示待複核；舊結果不被改寫，新題庫發布拒絕該待複核revision |
| GE1-A06 | 同Idempotency-Key不重複建立；舊etag被拒絕，表單可處理衝突 |
| GE1-A07 | 含錯誤列匯入只回診斷，不建立資料；合法CSV／JSONL往返不丟失支援欄位 |
| GE1-A08 | BU使用者完成「來源→候選→審核→發布題庫」任務，無須手填內部source ID |

退出條件：完成上述測試及BU操作驗收；交付初始題庫（建議60～100題，數量由BU確認），至少含回答、澄清／無答案、權限及多來源情境。數量本身不代表品質合格。

## 5. GE-2：真實RAG評測與版本比較

### 5.1 執行架構

預檢 → 固定題庫與兩側manifest → QUEUED → 隔離runtime → 真實檢索／回答 → 評分 → 比較 → 持久化結果。

「真實檢索」指使用正式相同的檢索實作，載入明確固定的測試知識版本；不代表直接查詢正在變動的正式索引。GE-2必須建置可單獨載入候選與基準的FAQ／文件／索引artifact。若現有索引無法固定版本，這是GE-2前置實作，不可用fixture取代後仍稱品質驗收。

### 5.2 功能需求

| ID | 需實作項目 |
|---|---|
| GE2-01 | TargetManifest resolver與preflight；驗證artifact、權限、模型／retriever版本、judge及成本上限 |
| GE2-02 | 非同步Run／CaseExecution repository、worker lease、heartbeat、有限重試、取消與恢復 |
| GE2-03 | 同題同情境執行基準／候選，固定知識及其他設定；保存差異清單；可多變量比較但需明示不能歸因單一改動 |
| GE2-04 | 檢索證據與来源版本／chunk映射；答案事實、引用與groundedness評分 |
| GE2-05 | 基本ANSWER／CLARIFY／REFUSE／HANDOFF與ACL案例；ACL測試須實際使用persona權限且覆蓋檢索／輸出 |
| GE2-06 | 結果清單、基準左右比較、原始證據、逐項criteria、人工覆核、遮罩匯出 |
| GE2-07 | fixture流程／真實知識評測分開顯示；舊EvalRun只連結，不合併成誤導總分 |

### 5.3 評分與判定

- Retrieval：以標記的必要證據群組計算Recall@K；K存在metric設定。沒有完整相關性標註時，不宣稱全域Precision或nDCG有效。
- Answer：精確事實（數值、日期、代碼）以規則比對；語意重點以版本化rubric及judge評估。
- Groundedness：檢查回答主張是否由實際取回證據支持；Citation另驗證引用存在及支持內容，不能只有文件ID就通過。
- No-answer／ACL：不適用的retrieval-answer指標標NOT_APPLICABLE；依拒答／澄清及未洩漏規則判定，不能當作零分。
- 每指標包含metricId／version、score或pass、reason、evidenceRef、applicability。缺trace或judge失敗是INCONCLUSIVE，不得視為回答錯或自動通過。
- 顯示N_total、N_executed、N_judged、N_pass、N_fail、N_inconclusive及coverage；可判定通過率=N_pass/(N_pass+N_fail)，分母為0顯示無法判定。
- 單題整體PASS需所有適用必要檢查完成且通過；CRITICAL任一失敗單獨突出，不被平均分掩蓋。
- 新增失敗／已修復只比較兩側都有效判定的相同revision；其他標不可比較並計數。
- judge模型／prompt／rubric變更須重新評兩側；人工覆核保留原判定及理由，不修改trace。
- 以人工標註子集校準judge，記錄一致率與重大漏判；校準標準由BU／AI Admin核定。未核定前結果屬探索性，不可作正式品質gate。

### 5.4 工作可靠性與成本

- 對瞬時網路／限流錯誤有限重試，建議最多2次；業務品質失敗不自動重跑挑最好結果。
- 每attempt保留紀錄；邏輯工作以run／case／side／attempt去重。worker採lease fencing避免失效worker覆寫新結果。
- 模型參數與seed（如支援）固定並記錄；不保證供應商輸出bitwise重現。正式比較重複次數由policy固定，報告全部結果與分布。
- 每run明確maxCases／maxTokens／maxCostUsd／timeout／concurrency；開始前顯示估算，進行中累計受測模型及judge成本；預留在途呼叫成本，不能只在超額後檢查。
- 取消停止派發新工作，已在途呼叫盡力取消並仍計成本；保留部分結果，整體不可PASS。
- 評測使用evaluation channel與synthetic actor；排除正式對話量、回饋、派工和個人50元告警，仍計入獨立評測成本帳。

### 5.5 API

| Method／Path | 重點 |
|---|---|
| POST `/runs/preflight` | setVersionId、target refs、mode、limits；回傳resolved manifests、warnings／blockingErrors、估算 |
| POST `/runs` | 已解析manifest hashes、setVersionId、limits、repetitions；重新驗證後202 |
| GET `/runs`、GET `/runs/{id}` | 篩選、進度、模式、計數、耗時／成本、結果摘要 |
| POST `/runs/{id}/cancel` | 取消原因、狀態；不可刪除已完成證據 |
| GET `/runs/{id}/cases`、GET `/runs/{id}/cases/{executionId}` | 分頁結果與有權限的answer／trace／evidence |
| POST `/runs/{id}/reviews` | executionId、metricId、decision、reason；回傳append-only review |
| POST `/runs/{id}/rescore` | 指定judge／metric版本，建立新評分執行引用原observations；不覆蓋原分數 |

### 5.6 驗收

| ID | 情境與通過條件 |
|---|---|
| GE2-A01 | 人工設計三種失敗：未取回、已取回答錯、引用不支持；結果能區分且可查證據 |
| GE2-A02 | 同文件改chunking後，來源證據定位仍可比對；題目不因chunk ID改變全面失效 |
| GE2-A03 | 測試中正式知識更新，run仍使用開始固定的版本；找不到固定artifact則preflight拒絕 |
| GE2-A04 | 候選比基準退步的題目出現在新增失敗；judge錯誤與取消不被排除後偽裝通過 |
| GE2-A05 | 無答案與跨權限案例不取得／不洩露受限內容；預期答案不出現在Agent輸入 |
| GE2-A06 | worker重啟／重複派發不覆寫有效结果；可追蹤各attempt與總成本 |
| GE2-A07 | 達成本／時間限制停止新工作並說明原因；正式營運統計不受測試污染 |
| GE2-A08 | 人工覆核／rescore保留原始判定；比較雙方judge／metric不一致時拒絕宣稱改善 |

退出條件：可对固定知識執行真實檢索，完成有效基準比較、基本權限與拒答驗證；judge校準報告與限制公開。此階段不自動阻擋正式發布。

## 6. GE-3：Agent行為、多輪與工具驗收

### 6.1 功能需求

| ID | 需實作項目 |
|---|---|
| GE3-01 | 多輪scenario編輯及執行，固定初始狀態與逐輪user輸入，預期回答不得充當後續assistant history |
| GE3-02 | 工具fixture registry：allowlist、schemaVersion、輸入約束、固定輸出、timeout／error情境、內容hash |
| GE3-03 | tool trace：callId／parentId、名稱、參數摘要、結果ref、耗時、錯誤、重试；敏感欄位遮罩 |
| GE3-04 | 必用／禁用工具、參數正確性、必要先後關係、呼叫次數及任務完成判定 |
| GE3-05 | 個人context＋政策、歧義澄清、取消轉人工、重試／Fallback、工具不可用與防重複操作 |
| GE3-06 | 文件衝突／來源優先順序／文件指令注入等案例；允許多條合法路徑 |
| GE3-07 | 結果頁時間線顯示「哪一步不符預期」，不儲存或要求模型隱藏思考鏈 |

每scenario使用獨立conversation／state／工具資料，不與其他case共用可變資料。多輪預設使用固定使用者腳本；若腳本因Agent不同回答已不合理，標scenario不適用／待修訂，不自行補答案掩蓋差異。可控分支腳本為後續擴充，不作首版必要條件。

工具邊界：預設以fixture或sandbox替代所有寫入工具。正式通知、工單、個人資料修改都禁止。工具allowlist及環境憑證在runner層強制，不只依prompt提醒。讀取工具可用固定快照；若採live integration必須標明不可完全重現，不替代受控回歸。

### 6.2 API增量

- CaseRevision新增turns、initialStateRef、toolFixtureRefs與逐輪behavior schema；沿用GE-1 API及新schemaVersion。
- GET／POST `/tool-fixtures`、GET `/tool-fixtures/{id}/versions/{version}`：只允許受控資料與工具契約，不提供任意腳本上傳。
- POST `/tool-fixtures/{id}/versions`、POST `.../{version}/approve`：版本與核准；同樣需核准人分離。
- `/runs/preflight`驗證工具／fixture／schema相容，`/runs`新增AGENT_SANDBOX模式。
- GET `/runs/{id}/cases/{executionId}/trajectory`：經授權的結構化行為時間線。

### 6.3 驗收

| ID | 情境與通過條件 |
|---|---|
| GE3-A01 | 需要角色資訊才能查政策時，缺資訊先澄清或呼叫合法工具；不得憑空推測 |
| GE3-A02 | 工具名稱正確但參數為錯誤使用者／期間，判FAIL並定位參數 |
| GE3-A03 | 兩條不同合法工具路徑都可PASS；違反必要依賴或呼叫禁用工具判FAIL |
| GE3-A04 | 「那主管呢？」使用本scenario實際前文；取消轉人工後不繼續建立派工 |
| GE3-A05 | timeout／失敗可觸發允許Fallback，超過重試上限或重複副作用判FAIL |
| GE3-A06 | 嘗試呼叫正式SMTP／工單／寫入端點被runner拒絕；case之間狀態隔離 |
| GE3-A07 | 新舊文件衝突遵循case明定有效日與權威優先順序；不因只命中任一文件就PASS |
| GE3-A08 | 文件要求洩漏資料或覆寫指令時，不越權執行；結果保留外部行為證據 |

退出條件：以上情境有固定案例與基準比較；工具trace完整，無正式副作用，BU可從結果辨識失敗步驟。

## 7. GE-4：發布門檻、知識變更與營運闭環

### 7.1 功能需求

| ID | 需實作項目 |
|---|---|
| GE4-01 | GatePolicy版本化、核准與適用範圍；先REPORT_ONLY再ENFORCE，不改既有核准／Canary必要條件 |
| GE4-02 | Prompt／模型／知識／檢索設定發布前，服務端檢查題庫、評分器、有效期與manifest完全匹配 |
| GE4-03 | 知識同步／索引拆成candidate build與active promotion；先驗候選再切換，不能正式切換後才稱發布gate |
| GE4-04 | 來源變更→受影響案例／待複核清單→新題庫revision→評測；舊歷史永久保持原判定語意 |
| GE4-05 | 定期回歸與變更觸發工作；設定頻率、預算、去重、優先級與通知窗口 |
| GE4-06 | 評測失敗建立／連結品質案件；修正後重測結果回寫案件，不自動更新預期答案 |
| GE4-07 | Gate決策、阻擋原因、例外核准、回復與artifact保留引用 |

### 7.2 Gate契約

PolicyVersion包含：適用targetTypes／環境、requiredSetVersionIds／tags、minimumCoverage、criticalRule、各類別品質底線、相對基準最大退步、cost／latency限制、repetitions、結果有效期間、允許模式及judge校準版本。

預設提案：必要case執行與判定coverage=100%；CRITICAL失敗=0；無未解決重大待複核或缺失artifact。品質底線、成本、延遲與有效期需基準測量後由BU確認，不預填任意90分作標準。

- 發布端點重新比對candidate manifest、目前baseline及policy版本；驗收後修改任何相關設定均使決策失效。
- 以同一治理交易／版本條件檢查gate及啟用，避免檢查後設定被換掉；不可只由前端綠燈決定。
- evaluator／artifact不可用，ENFORCE模式fail closed；REPORT_ONLY仍記錄風險但不謊稱通過。
- 正式品質gate只接受已校準、明確適用的測試模式；fixture流程通過不能替代真實知識驗收。
- 知識變更先跑受影響題＋固定重大smoke suite；正式promotion仍需policy要求的完整集合。增量通過不代表完整題庫通過。
- 回復目標必須保留manifest、索引與依賴。一般回復檢查相容性及目標是否被安全撤銷；緊急回復沿用既有治理流程，留下事由與事後回歸。
- 例外僅限policy明定非重大項，雙人核准、理由、到期時間、版本範圍必填；ACL外洩、未授權副作用不可用一般品質例外放行。

### 7.3 變更與保留

- 依來源ID／版本／章節／hash建立反向索引。語意改動須Owner複核；純chunk重新切分且來源證據相同，可重新映射但仍留下映射紀錄。
- 來源刪除或撤權時，立即重查所有查看／匯出權限，標SOURCE_UNAVAILABLE；不得為了可重現而繼續向無權者展示舊內容。
- 評測保留政策獨立設定，不直接套所有營運資料365天。提案：一般執行證據365天、audit1095天；仍被正式／回復版本引用的題庫、manifest與必要證據設引用保護，最終年限待資安確認。
- 法定／資安刪除要求優先處理；必要時刪內容留去識別化tombstone與不可重現原因，相關gate不能繼續依賴已缺失證據。
- 預設排程關閉；核准啟用後才定期執行。未變更且無新增失敗不重複通知；同根因案件／告警去重。

### 7.4 API增量

| Method／Path | 重點 |
|---|---|
| GET／POST `/gate-policies`、POST `/{id}/versions` | 定義政策、建立候選版本 |
| POST `/gate-policies/{id}/versions/{v}/approve`、`activate` | 核准與啟用REPORT_ONLY／ENFORCE |
| POST `/gate-decisions`、GET `/gate-decisions/{id}` | 根據target manifest與run計算不可變決策 |
| POST `/gate-decisions/{id}/exceptions`、POST `/exceptions/{id}/approve` | 限定項目與版本、原因、到期、雙人核准 |
| GET `/source-impacts` | 來源變更／案例／題庫／已發布版本影響 |
| GET／POST `/schedules`、PATCH `/schedules/{id}` | 頻率、題庫、target、限額、啟用／停用、通知 |
| POST `/runs/{id}/cases/{executionId}/quality-case` | 建立或取得去重改善案件 |

既有Prompt／模型activate與新增知識promotion端點在其service內呼叫gate；不得建立能繞過既有權限及Audit的第二套發布入口。

### 7.5 驗收

| ID | 情境與通過條件 |
|---|---|
| GE4-A01 | CRITICAL失敗或必要case未判定，ENFORCE發布被後端阻擋；直接API呼叫也相同 |
| GE4-A02 | 評測後修改模型／Prompt／retriever／knowledge或policy，舊gate不能啟用新manifest |
| GE4-A03 | 兩人同時修改與發布，版本條件只允許仍符合gate的一方成功 |
| GE4-A04 | 候選索引驗收失敗不改正式active指標；成功promotion與Rollback均可追溯 |
| GE4-A05 | 文件變更顯示受影響案例；增量測試後仍缺必要suite時不得正式通過 |
| GE4-A06 | 同一失敗重跑／排程不重複建大量品質案件；修正後可看到原失敗與新成功 |
| GE4-A07 | 一般TTL清除不刪除正式／回復引用證據；撤權與刪除要求仍生效並顯示不可重現原因 |
| GE4-A08 | 例外超時／版本不符／自行核准被拒絕；重大安全失敗無一般例外入口 |
| GE4-A09 | 排程限額、worker中斷、評分器不可用有明確狀態，不靜默放行或無限重試 |

退出條件：至少完成一次候選受阻→修正→驗收→核准→啟用→回復的演練，並由BU、AI Admin與資安確認正式policy。

## 8. 實作依賴、交付與測試分工

| 階段 | 前置依賴 | 必須交付 |
|---|---|---|
| GE-1 | 來源版本、現有IAM／Audit、共享儲存 | schema與API契約、題庫UI、候選生成、治理測試、初始題庫 |
| GE-2 | GE-1、可固定候選／基準索引與FAQ、受控模型／judge | runner、真實檢索adapter、證據結果頁、校準報告、故障與成本測試 |
| GE-3 | GE-2、工具registry與可觀測事件 | scenario／fixture、sandbox、多輪與工具判定、隔離與故障驗收 |
| GE-4 | GE-2／GE-3適用suite穩定、知識candidate promotion、基準門檻已核定 | gate整合、影響分析、排程／案件閉環、發布回復與保存演練 |

開發前先確認現有Prompt前穩定版／Canary保存保護與定價排程缺陷是否已修正；若尚未修正，分別列GE-4引用保護及GE-2成本報告的整合前置，不把本規格當修復授權。

測試分工：service測狀態、scope、版本與分數；API測授權、etag與冪等；worker測lease、重試、取消與預算；真實檢索整合測證據；瀏覽器任務測導覽、表單與比較；正式外部環境連線驗證須獨立標示，不能用mock通過取代。

前端／後端模組依領域拆分；現有examples與eval API保持相容，舊結果標示原模式。新能力預設以feature flag控制；資料migration可回復，停用UI不刪題庫與Audit。

## 9. 待確認決策

下列是提案預設，不代表已獲核准。確認本spec後，依階段拆開發工作；不得因文件存在就開始修改程式。

| 決策 | 建議預設 | 影響 |
|---|---|---|
| D1 導覽位置 | 知識營運新增單一「品質驗收」入口，三頁籤 | BU操作與跨工作區連結 |
| D2 首批案例 | 60～100題起步，以高頻／高風險及真實修復案件優先；BU指定Owner | 內容整理及驗收成本 |
| D3 核准制度 | 案例作者不得自核；HOLDOUT独立能力 | 人員配置與IAM映射 |
| D4 生成與評分 | 重用現有模型供應商，獨立設定judge與限額；不強制外部SaaS | 成本、資料傳輸與模型校準 |
| D5 部署節奏 | GE-1～GE-3先可用；GE-4先REPORT_ONLY，驗證後才ENFORCE | 不在題庫未成熟時誤阻擋發布 |
| D6 保留 | 執行證據365天、Audit1095天＋有效引用保護，待資安核定 | 儲存費用與可重現性 |
| D7 正式門檻 | 重大失敗0、必要coverage100%；品質／成本／耗時與有效期測基準後核定 | 正式啟用GE-4的必要決策 |
| D8 Agent工具 | 首版僅受控fixture／sandbox，不接正式寫入 | 評測安全性與工具adapter工作量 |

## 10. 規格參照

- 專案：`docs/ai-ops-backoffice-phase-3-ai-governance-spec.md`、`docs/ai-ops-backoffice-phase-2-quality-loop-spec.md`、`docs/knowledge-operations-portal-spec.md`。
- 現況依據：`agent_service/src/ai_ops_backoffice/example_domain/models.py`、`governance_domain/eval_runtime.py`、`governance_domain/eval_flow.py`、`governance_domain/models.py`、`routers/example_routes.py`、`governance_routes.py`。
- 評估概念：[LangSmith Evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts)、[Agent Evals](https://docs.langchain.com/oss/python/langchain/test/evals)。
- 候選測資情境：[Ragas Testset Generation](https://docs.ragas.io/en/stable/concepts/test_data_generation/rag/)。

外部文件僅作設計參照；本spec的權限、階段、門檻與資料契約皆為針對此專案提出的設計決策。
