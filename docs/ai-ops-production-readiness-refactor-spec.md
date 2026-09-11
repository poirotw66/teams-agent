# AI 資訊客服營運後台：功能補齊與架構強化 Spec

> 版本：v0.2｜日期：2026-09-11｜狀態：第 11 節決策已由使用者確認，作為後續開工基準；本次未開始實作
>
> 範圍：承接本次專案檢視的全部 9 項功能與 9 項架構工作。本次僅更新文件。
> 基準：b196365 與檢視當時工作目錄中的未提交修改；開工前重新確認差異。

## 1. 目標、既有規格與範圍

讓 BU 能從對話與負評進行改善，以真實評估驗收候選版，受控發布後追蹤效果；回答可安全追溯至當時原檔、版本與段落。所有營運資料與長工作均可跨重新整理、服務重啟與多 instance 持續運作。

本文件補充並落實 [Golden Eval 四階段規格](golden-eval-set-four-phase-spec.md) 與 [BU UI／UX 重構計畫](ai-ops-bu-ui-ux-refactor-plan.md)，不重做已完成的題庫與導覽。既有 GE-1～GE-4 保留；本次使用 PR-1～PR-5，避免與舊階段混淆。若契約有差異，以本文件經確認後的明確補充為準，實作 PR 必須標出受影響的舊規格。

保留目前 Agent Runtime、Knowledge Portal、Operations Backoffice 與 domain 分層；不以拆微服務、換 Agent 框架、換向量庫或新增外部評估 SaaS 為前提。允許共用 repository、artifact、authorization 與 execution adapter。

### 1.1 完成定義

- 功能實際接線、失敗處理、權限、持久化、介面及測試皆完成，才可標為交付。
- 模擬測試、僅存在 API、僅保存設定、單元測試全通過，均不能單獨代表正式能力完成。
- 每個需求 ID 在 PR 與驗收紀錄中對應證據；不以推估百分比回報完成度。
- 本地驗證、隔離 GCP 整合驗證、Teams／BU UAT 分開記錄，不互相替代。

## 2. 全部工作對照與優先級

P0：正式營運必要條件；P1：本次完整交付必要條件；P2：本次亦納入，但排在可靠性之後。

| ID | 面向／優先級 | 實作項目 | 階段 | 主要驗收 |
|---|---|---|---|---|
| F01 | 功能 P0 | 真實 RAG Eval 接線 | PR-3 | 指定 manifest 實際執行、真實 trace／用量 |
| F02 | 功能 P0 | 來源預覽與下載 ACL | PR-2 | 跨部門／租戶／撤權皆不能越權 |
| F03 | 功能 P0 | 歷史來源精準對版 | PR-2 | 原版本缺失不替換成新版本 |
| F04 | 功能 P1 | 真實 Agent sandbox／多輪評估 | PR-3 | 真實 planning + 隔離工具 + 實際軌跡 |
| F05 | 功能 P1 | 發布 Gate 強制串接 | PR-4 | 所有啟用入口不能繞過 Gate |
| F06 | 功能 P1 | 排程到期派工與補償 | PR-4 | 重啟後仍執行且不重複邏輯 Run |
| F07 | 功能 P1 | GCP 私有原始檔引用 | PR-2 | 多 instance 與歷史原檔可用 |
| F08 | 功能 P1 | 原檔頁碼／段落定位 | PR-2 | 支援格式精準定位、不支援時明示 |
| F09 | 功能 P1 | BU 完整工作流程與 UX 修正 | PR-5 | 負評至發布再至成效可完成 |
| A01 | 架構 P0 | Eval／Gate／Fixture 持久化 | PR-1 | 重啟不遺失、tenant 隔離 |
| A02 | 架構 P0 | 並行寫入／版本衝突 | PR-1 | 雙請求與雙 instance 無 lost update |
| A03 | 架構 P1 | 持久化背景派工 | PR-1 | lease、checkpoint、取消與恢復 |
| A04 | 架構 P1 | 文件共用授權層 | PR-2 | 各入口使用同一授權決策 |
| A05 | 架構 P1 | 營運資料新鮮度契約 | PR-4 | 各頁呈現截至時間／延遲／失敗 |
| A06 | 架構 P2 | 來源直接索引與有界快取 | PR-2 | 查來源不掃所有 releases |
| A07 | 架構 P2 | 大型前端頁面拆分 | PR-5 | 行為不退步、責任可獨立驗證 |
| A08 | 架構 P2 | 後端大型模組拆分 | PR-2、PR-5 | router／service／adapter 邊界清楚 |
| A09 | 架構 P1 | 接線與部署邊界測試 | 全階段 | 真實 app、重啟、並行、Gate、ACL |

## 3. 整體設計與共同契約

### 3.1 建議部署組成

- 現有 API 服務：授權、資料查詢、提交工作、查看結果；不在 HTTP 請求內跑長評估。
- Firestore：Eval、Gate、Fixture、Job、Schedule、SourceRecord 與版本／稽核索引。沿用既有專案的 GCP 儲存方向。
- 私有 GCS：不可變原檔、衍生文件、source map、release artifacts 與大型遮罩 trace；資料庫只存引用及摘要。
- 獨立 worker：處理評估、排程派工與恢復。建議以 Cloud Tasks 觸發有界工作單位、Cloud Scheduler 觸發到期掃描；長工作拆至 case／side／attempt，避免把整個 Run 綁在單次 HTTP。
- 若工作不能在選定執行平台時限內完成，改採可續跑批次或 Cloud Run Job；實作前核對當時平台限制，禁止靜默截斷工作。
- 本地保留 FILE／MEMORY adapter；production 不允許 Eval／Gate／Fixture 使用 MEMORY 或本機 FILE。

### 3.2 共同規則

所有業務資料有 tenantId；需 BU 範圍者加 ownerUnitId／owner scope。tenant 取自已驗證身分，不能信任 request 自填。伺服器時間以 UTC 儲存，介面依使用者時區顯示。

可修改資源有 revision／etag；更新須帶 expectedRevision，衝突回 409 並保留使用者輸入。不可變版本及決策以新紀錄追加，不覆寫歷史結果。

命令型 API 接受 Idempotency-Key，範圍為 tenant＋actor＋action；相同 key 與不同 payload 回 409。資料修改與 outbox 在同一交易寫入；外部派工由 outbox 重試，避免資料已提交但工作未派送。

外部佇列允許至少一次投遞，系統保證一個邏輯工作只接受一次完成結果；不宣稱 LLM 呼叫可達 exactly-once。崩潰後重試可能產生額外費用，需保留 attempt 與未知用量狀態。

### 3.3 主要新增／強化物件

| 物件 | 必要內容 |
|---|---|
| ExecutionJob | tenantId、jobId、runId、logicalKey、state、attempt、leaseOwner／Until、heartbeatAt、checkpointRef、cancelRequestedAt、lastError、revision |
| SourceRecord | sourceRefId、tenantId、documentId、versionId、releaseId、chunkId、artifactRef、contentHash、locatorRef、mappingStatus、createdAt |
| ArtifactRecord | artifactId、bucket／object／generation、sha256、mimeType、size、kind、scanStatus、retentionClass；儲存位置不直接回傳 BU |
| SourceLocator | pageIndex、pageLabel、sectionPath、paragraphId、可選 bbox＋座標系、sheet／cellRange、slideIndex、parserVersion、mappingConfidence |
| EvalSchedule | tenant／scope、timezone、規則、nextDueAt、misfirePolicy、targetSelector、budget、enabled、revision |
| FreshnessMetadata | eventWatermark、materializedAt、servedAt、lagSeconds、status、lastSuccessfulSyncAt、jobId；可未知，不以零代替 |
| GateDecision | policyVersion、suiteVersions、targetManifestHash、runIds、resultDigest、decision、expiresAt、exceptions、actor／time |

## 4. PR-1：可靠儲存與工作執行基礎

覆蓋 A01、A02、A03、A09。先完成本階段再讓正式評估產生重要決策。

### 4.1 Repository 與遷移

- EvalCase、Revision、SetVersion、Run、CaseExecution、Review、GatePolicy／Decision／Exception、ToolFixture／Version、Schedule 均有持久化 adapter。
- 使用每資源紀錄與可分頁索引，禁止將所有資料塞進單一 Firestore document 或整份 JSON 更新。
- repository 提供交易內 mutation／CAS，而不是 service 先讀整份狀態再覆蓋。讀寫租戶邊界在 repository 與 service 共同落實。
- 本地 FILE adapter 的完整讀－改－寫須置於同一跨 process 鎖內，或以 revision 拒絕過期快照。
- 遷移工具提供 dry-run、schema 檢查、備份、筆數／hash 對帳、可重跑與進度紀錄；未知 tenant 資料隔離，不自動公開。
- 切換前暫停相關寫入，完成最後增量與核對後切換；不做無交易保證的雙寫。切換後回復舊版也必須保持新資料可讀，禁止直接回到過期 JSON。

### 4.2 工作生命週期

`QUEUED → RUNNING → COMPLETED | FAILED | CANCELLED`；lease 過期可重新領取。Run 另可呈現 PARTIAL，但不得將部分結果視為整體通過。

領取工作使用交易；heartbeat 延長 lease；完成時檢查 fencing token，舊 worker 不得覆蓋新 worker。每個 case／side 保存 checkpoint 與 attempt。取消阻止新工作派送，對已送出的 provider 請求只做可支援的 best effort 取消，仍保存費用。

建立 Run API 回 202 與 runId／statusUrl；介面可輪詢、離頁及恢復。timeout、429／暫時性網路錯誤可有限退避重試；授權、manifest 不存在、契約錯誤不可無限重試。

### 4.3 驗收

- A01-T1：重啟 API／worker 後，題庫、Fixture、Gate、Schedule 與 Run 狀態保持。
- A02-T1：兩個獨立 instance 同時新增及更新，無遺失；相同 revision 的競爭更新僅一個成功。
- A03-T1：在派送前、provider 呼叫後、checkpoint 前故障，能恢復且不重複接受結果。
- A03-T2：取消、超預算、lease 過期均有可理解狀態與稽核；不存在永久 RUNNING。
- A09-T1：以 production 設定建立實際 app，暫存 repository 或缺少必要 adapter 必須啟動失敗。

## 5. PR-2：安全且精準的原檔來源追溯

覆蓋 F02、F03、F07、F08、A04、A06 及來源相關 A08。

### 5.1 原檔與版本

上傳先保存原始 bytes 至私有隔離區，完成格式／大小／掃描檢查後才可供授權下載，再產生 Markdown、圖片、chunk 與 source map。每個 document version 使用獨立 object key 並記錄 generation＋hash；同名上傳不覆寫舊版本。

release manifest 固定 documentVersion、artifact 與 chunk mapping。只有必要 artifact 與索引完整可讀才可發布。歷史回答保存不可變 sourceRefId，不保存短效 signed URL。

既有僅 MD／圖片的文件標示 ORIGINAL_NOT_PRESERVED；可補上經核對的同版原檔。不能將後補不同版本的文件當成歷史原檔，也不能從 Markdown 假造原檔。

### 5.2 精準匹配與狀態

- 完整身分只能精準解析對應 release／document／version／chunk；不因缺失回退至 active release。
- 舊資料缺身分可離線建立回填候選，保留依據、可信度與人工確認；未確認只能顯示 LEGACY_UNVERIFIED，不標 EXACT。
- 對外區分 AVAILABLE、INDEX_PENDING、ORIGINAL_NOT_PRESERVED、SOURCE_MISSING、MAPPING_UNAVAILABLE、LEGACY_UNVERIFIED；無權限回應採一致的安全錯誤，不洩漏受限文件名稱或存在性。
- 找不到 chunk 不以同 sourcePath 的第一段補上；同名文件不得當作唯一識別。

### 5.3 共用授權與 API

共用 `authorizeDocumentAccess(actor, documentVersion, action)`，涵蓋 tenant、owner scope、文件 ACL、目前授權及刪除／封存政策。查對話權限不等於查所有原文件權限。歷史回答可追溯版本，但不繞過使用者當下已撤銷的權限。

沿用 `GET /api/sources/{sourceRefId}` 與 `/file`；後端查 SourceRecord 並授權，再讀 GCS。以串流下載為預設，支援 PDF 預覽必要的 Range／Content-Type；避免整份大檔載入記憶體。下載檔名安全編碼，不直接呈現可執行上傳內容。

簽名 URL 若日後採用，僅於授權後短效簽發，不能存入對話或 trace；須明確接受有效期間內无法即時撤銷的取捨。本版預設後端串流。

SourceRecord 索引直接查詢，不遍歷 releases。快取須有容量／TTL，鍵含 tenant 與 immutable version；ACL 不使用會延後撤權的內容快取決策。audit 保存 actor、sourceRef、結果與時間，不記錄敏感全文或簽名 URL。

### 5.4 定位與 BU 呈現

- PDF：保存實體頁索引、印刷頁標籤與可用 bbox，預覽跳页并可高亮。
- DOCX／PPTX：保留原檔下載；若建立 PDF 預覽，記錄衍生關係及转换器版本，清楚標示預覽副本。無可靠映射時只提供章節／投影片與摘錄。
- XLSX：保存 sheet／cell range；Markdown：保存 heading／paragraph anchor。不支援精準定位時明示，不承諾所有格式均能頁面高亮。
- 人工編輯 MD 形成新衍生版本；若證據與原檔不再一致，標示 EDITED_DERIVATIVE，顯示實際回答依據與原始附件的差異。
- 來源卡顯示文件名、版本、定位與狀態；「開啟原檔」「查看回答依據」語意分明，失敗提供可採取的下一步。

### 5.5 驗收

- F02-T1：跨租戶、跨部門、已撤權使用者即使知道 sourceRefId，預覽／Range／下載都不能取得內容。
- F03-T1：刪除舊 release、替換同名文件、chunk 不存在，均不顯示新版本冒充舊來源。
- F07-T1：兩個 instance 不共享本機磁碟仍可讀同一原檔；下載 hash 與上傳原始 bytes 相同。
- F08-T1：PDF、Office 預覽、試算表、編輯後 MD、無原檔各一案例，定位或降級訊息符合實際。
- A06-T1：直接查一個 sourceRef 不列舉所有 releases；快取達上限後記憶體不持續增長。

## 6. PR-3：真實 RAG 與 Agent 品質評估

覆蓋 F01、F04，使用 PR-1 的 job 與 PR-2 的 artifact／ACL 契約。

### 6.1 執行模式與 manifest

- REAL_RAG：使用正式可重用的 retrieval／answer pipeline；不能使用固定回答、估造 tokens 或 keyword fallback 冒充正式檢索。
- AGENT_SANDBOX：執行正式 planning／Agent graph，工具替換成明確版本的 sandbox adapter，保留真正工具選擇與參數。
- OFFLINE_BENCHMARK：允許模擬，介面、匯出與 API 明示「不可作真實品質發布驗收」。
- REAL_RAG 缺正式 adapter、指定 artifact 或 provider 設定時預檢失敗，不靜默降級。
- manifest 固定程式revision、模型實際識別／參數、Prompt、release、embedding／retriever／reranker設定、ACL政策、工具／Fixture、runner／scorer／judge版本。不可解析的版本阻止執行。
- baseline 與 candidate 使用同一案例版本與測試身分，side 分開上下文；不向被測系統傳入 expected answer／criteria。Provider 無法固定模型快照時須標示限制，不宣稱完全可重現。

### 6.2 真實 trace、評分與費用

保存實際 evidence IDs、工具事件、turn、answer、耗時、provider requestId、用量與計價版本；敏感輸入先依政策處理，憑證不得進 trace。LLM 產生的文字不是工具實際執行證據。

deterministic 評分處理 ACL、禁止工具、必要結構及數值；語意正確性／groundedness 使用固定 judge 設定並支援人工覆核。judge 失敗為 UNDETERMINED，不自動通過。評分來源、理由、覆核與版本完整保留。

usage 不可得時記 UNKNOWN；估算費用與實際用量費用分開。預算同時計入 model、judge、retries；派送前交易預留額度，結束對帳，未知費用不得假裝為零。

### 6.3 Sandbox 與多輪

每 Run／side 隔離 conversation、memory、fixture state。工具 allowlist＋schema 驗證；正式寫入、派工、發信與通知不得通過 sandbox。工具回應可設定成功、timeout、拒絕、空資料及矛盾資訊。

記錄真實 tool arguments 與結果，依約束允許多條合法軌跡，不要求所有正確回答都有相同固定順序。persona 權限由測試 fixture 控制，不繼承操作評估者的管理者權限。

### 6.4 驗收

- F01-T1：以實際 app 建立 Run，驗證正式 retriever／answer adapter 被呼叫且套用目標 manifest；缺少 adapter 時 REAL_RAG 被拒。
- F01-T2：刻意使 candidate 檢索不到指定證據，結果能呈現退步；真實模型 canary 另在隔離環境驗證用量與 trace。
- F01-T3：檢查送往被測 pipeline 的輸入不含 golden answer／criteria。
- F04-T1：澄清、多輪代名詞、工具順序、錯誤參數、ACL、工具失敗與重試至少各一例。
- F04-T2：要求 sandbox 寄信／建立正式工單，不產生正式副作用，且可從 trace 驗證攔截。

## 7. PR-4：發布、排程與營運資料閉環

覆蓋 F05、F06、A05。不得在 PR-3 真實評估完成前對外宣告品質 Gate 已驗證線上能力。

### 7.1 發布 Gate

候選建置與正式 activation 分離。知識、FAQ、Prompt、模型及會改變執行行為的設定，凡存在可直接啟用入口都納入 activation inventory；API、CLI、部署腳本及 rollback 均受服務端發布規則約束。

Decision 綁定 tenant、完整 target manifest hash、policy version、suite versions、有效期限及結果 digest。啟用時重新確認目前候選與決策完全一致，在同一交易／CAS 更新 active pointer，避免檢查後換包。

REPORT_ONLY 記錄決策但不擋發布；ENFORCE 對缺少／過期／未完成／不符合模式的結果 fail closed。政策版本變更須重新決策。一般 rollback 需有效決策；紧急 rollback 走有時效、目標範圍、理由與授權者的 break-glass，完整稽核且不改原評估結果。

### 7.2 排程

每分鐘掃描到期排程；以 scheduleId＋scheduledAt＋tenant 作 logical key，交易建立唯一 Run／outbox。頻率以 timezone 解讀並保存 UTC due time，處理日光節約時間。

target selector 可指向「目前正式／指定候選」，但每次派工解析成不可變 manifest。預設禁止同 schedule 重疊；misfire 預設合併成一次最新補跑，介面標示漏過次數，可配置有限補跑上限。預算不足保存 SKIPPED_BUDGET，不無限重試。

### 7.3 新鮮度

事件發生、事件入庫、聚合完成、來源同步完成分開計時；寫入成功不等於報表更新成功。查詢 API 附 FreshnessMetadata，UI 顯示資料截至時間、正在更新、延遲或上次成功；未知時間不能顯示「即時」。

先保留 polling，頁面隱藏時暫停或降頻、錯誤退避、離頁釋放、避免舊回應覆蓋新篩選。是否使用 SSE 由量測決定，不列為完成前提。

已確認的初始驗收目標（依第 11 節）：正常負載下事件入庫至對話清單 p95 ≤ 30 秒，事件入庫至聚合頁 p95 ≤ 5 分鐘；排程 due 至開始派送 p95 ≤ 2 分鐘。長文件同步依工作狀態呈現，不套用同一 30 秒門檻。

### 7.4 驗收

- F05-T1：直接打 activation API、CLI、部署流程，均不能绕過 ENFORCE；candidate／policy 改變使旧決策失效。
- F05-T2：過期、部分結果、mock Run、例外到期、rollback 各有案例。
- F06-T1：雙 scheduler 同時掃描、重啟、佇列重送、漏跑、跨時區与預算不足，無重複邏輯 Run。
- A05-T1：以 correlationId 記錄事件到各頁時間，量測 p95；斷線與 worker 停止時介面不可顯示最新。

## 8. PR-5：BU 流程驗收與可維護性重構

覆蓋 F09、A07、A08。功能可靠性修正可先做必要介面，本階段整合最終工作流程。

### 8.1 頁面與模組責任

保留目前 BU 主導覽，不重新增加一套入口。品質驗收區以題庫、執行、結果為核心；Gate／排程依角色放管理頁籤或進階區。一般 BU 預設看到待處理與下一步，manifest／工具 trace 可展開。

`evaluations.js` 分拆為 cases、sets、runForm、runComparison、gateSettings、schedules；`knowledge.js` 分拆列表、編輯、版本、發布與來源；`issues.js` 分拆篩選列表、詳情與關聯動作。共用 API client、async state、表單 dirty state、table／pagination 與 return context。

`ops_reads.py` 按 conversations、sources、analytics 等資源拆 router；router 僅做輸入、授權與輸出，業務整合留 service。`document_service.py` 拆 upload／artifact、version、review、publication 的責任，不複製同一套交易與授權。

不以每檔行數作唯一標準；完成條件是各模組可獨立驗證、無循環依賴、無 duplicated auth／state、舊 URL 與資料契約相容。

### 8.2 BU 驗收場景

| 場景 | 操作路徑 | 成功條件 |
|---|---|---|
| UAT-01 負評改善 | 對話負評→案件→知識修訂→候選→評估→發布→成效 | 案件／版本／Run／發布雙向連結；不重填來源與問題 |
| UAT-02 回答追溯 | 來源 1→版本與摘錄→原檔對應位置→返回對話 | 保留原篩選與捲動；能理解回答依據 |
| UAT-03 來源不可用 | 舊版遺失、未保存原檔、無 mapping、無權限 | 狀態有原因與適當下一步，不出現空白來源區 |
| UAT-04 評估退步 | 建 Run→離頁→返回→看新增失敗→建立案件 | 工作不中斷；失敗原因與預期／實際可理解 |
| UAT-05 發布阻擋 | 評估未過→嘗試發布→修正→重跑→發布 | 清楚知道阻擋原因與所需行動，不靠工程師查 log |
| UAT-06 多人操作 | A、B 同改案例／文件 | 衝突提示保留輸入，可比較並重新提交 |
| UAT-07 資料延遲 | 對話新增、同步失敗、網路中斷 | 看得出資料截至何時，不因未更新誤認資料不存在 |

由至少 3 位具代表性的 BU 使用者，在無工程師逐步指導下操作；每場景記錄是否成功、耗時、返回次數、重複輸入與困惑點。首次測試建立基線，第二輪應消除阻斷；目標核心場景成功率 ≥ 90%，權限／誤發布類阻斷必須為 0。樣本小，結果僅作本次驗收，不泛化成全體使用者統計。

共通驗收：鍵盤可操作、焦點返回、錯誤不清空表單、狀態不僅靠顏色、窄桌面可完成任務、權限角色看不到不可執行的主要操作。以現有設計 tokens 為準。

## 9. 測試、效能、保留與部署

### 9.1 測試分層

| 層級 | 範圍 | 通過證據 |
|---|---|---|
| 單元／契約 | CAS、manifest、狀態機、locator、授權 | 按需求 ID 對應測試 |
| App integration | 實際 app factory、正式 adapter 接線、router→service→repository | 不只直接測 domain；缺失設定可被攔截 |
| 儲存／恢復 | 兩 process／instance、重啟、outbox、lease | 持久化資料核對、無遺失更新 |
| 隔離 GCP | 私有 GCS、Firestore、queue、worker、真實 provider canary | 脫敏 trace、費用、故障案例 |
| Teams／BU E2E | UAT-01～07、角色矩陣 | 操作紀錄、畫面與待修事項 |

整合與破壞性故障測試使用獨立 tenant／bucket／資料集，不改使用者現有營運資料。測試後檢查 git status，避免 fixture 或既有 data/ops 被測試污染。

### 9.2 效能與觀測

初始負載基準：1 萬案例、10 萬 execution、100 個歷史 release、100 萬 source records、20 位並行後台使用者。這是測試配置而非已證實容量；開工可依真實資料調整並記錄。

來源 metadata 與分頁清單 API 建議 p95 ≤ 1 秒（不含檔案傳輸／模型時間）；查詢以 cursor 分頁並驗證讀取成本。記錄 queue depth、最老待處理時間、lease 恢復次數、eval failure、source missing、ACL deny、freshness lag、Gate deny 與費用未知筆數。

### 9.3 保留與刪除

沿用已核准的 BU 保存政策，不在此另訂永久保存。建立 document version／artifact／source／Run／Gate 的 reference graph；有合法保存中的回答／決策引用時，清理工作先檢查保護規則。法定或政策要求刪除優先時，刪內容、留允許保存的 tombstone，介面明示已不可用，不能承諾永久追溯。

DB metadata、GCS objects 與索引分步清理有工作紀錄與重試；不可先刪索引導致 object 永遠無法追蹤。遷移與清理均有 dry-run、稽核與恢復演練。

### 9.4 部署與回復

每階段先在隔離環境驗證，再漸進開啟 feature flag。資料 schema 採向後相容增加欄位與雙版本讀取；不能靠退回映像恢復已刪資料。Gate 先 REPORT_ONLY 比對人工決策，經確認後再 ENFORCE；不能自動降低門檻以換取通過。

## 10. 相依順序與開工切片

1. PR-1：repository／migration → CAS／outbox → worker／recovery → app wiring tests。
2. PR-2：共用 ACL／SourceRecord → GCS artifact → 嚴格解析／原檔 → locator／UI／直接索引。
3. PR-3：manifest resolver → 真實 RAG adapter → 真實 Agent sandbox → scoring／用量／結果 UI。
4. PR-4：activation inventory／Gate → scheduler → freshness metadata／UI → 發布 E2E。
5. PR-5：責任拆分 → BU 實跑 → 修正中斷點 → 全流程回歸／交付。

每切片 PR 應能獨立 review，描述 problem／behavior、涉及需求 ID、遷移與驗證證據。不得把持久化、重構、UI 改版與所有新增流程一次塞入單一變更。

## 11. 已確認的實作決策

使用者已於 2026-09-11 明確確認「第 11 節沒問題」，以下八項決策均已確認，作為後續實作與驗收基準，無須重複確認相同決策。本次要求僅為更新文件，尚未開始程式實作；交付清單仍維持未完成。實作發現約束不符時提出具體替代與影響，不自行縮減功能範圍。

| 決策 | 已確認內容 |
|---|---|
| 正式儲存 | Firestore metadata＋私有 GCS artifacts；沿用現有 GCP 架構 |
| 工作執行 | durable outbox＋Cloud Tasks 有界工作＋Cloud Scheduler 到期掃描 |
| 原檔存取 | 後端授權串流，首版不依賴公開檔案或永久 URL |
| 精準定位 | PDF 優先精準定位；其他格式支援 locator／預覽副本與明確降級 |
| 發布模式 | 先 REPORT_ONLY，驗收後開 ENFORCE；緊急 rollback 有獨立稽核流程 |
| 新鮮度門檻 | 對話 p95 30 秒、聚合 p95 5 分鐘、排程派送 p95 2 分鐘 |
| 重構範圍 | 保留現有主要導覽與部署邊界，優先責任拆分與 BU 流程連續性 |
| 開發順序 | PR-1 → PR-2 → PR-3 → PR-4 → PR-5，A09 貫穿每階段 |

## 12. 最終交付清單

- [ ] F01～F09、A01～A09 各有實作／測試／驗收證據，未完成不得以「頁面存在」結案。
- [ ] production 設定、部署流程、migration、回復與故障 runbook 更新。
- [ ] 原始文件、來源權限、歷史版本與精準定位案例通過。
- [ ] 真實 RAG／Agent 評估、Gate 強制阻擋、排程及預算通過。
- [ ] 重啟、多 instance、並行寫入及取消／恢復通過。
- [ ] BU UAT-01～07 完成，阻斷問題修正並回歸。
- [ ] 明確記錄仍受 provider／格式／外部平台限制的行為，不將降級能力標成完整支援。
