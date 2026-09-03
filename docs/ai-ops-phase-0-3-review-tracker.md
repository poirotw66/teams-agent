# AI Ops Backoffice Phase 0–3：審查追蹤

日期：2026-09-03。初始審查基準：`9a9ccc0`。

本文件由主對話審查員維護，記錄可重現缺口、實作責任與驗收門檻；不是正式驗收證書。完整範圍仍以四份 Phase spec 為準，不以本文件列舉項目取代原規格。

## 協作與完成定義

- 實作者：使用者指定的 GPT-5.6 Terra，使用 Codex 原生子任務／subagent。
- 審查員：主對話；檢查差異、獨立重跑測試，未通過則退回實作者。
- 實作完成、局部測試通過、跨服務整合完成、LAB UAT、正式人工簽核分開記錄。
- 2026-09-03 產品決策：Phase 0 目前以 LAB 自驗通過作為完成門檻，可繼續 Phase 2；本次不要求 BU／IT／資安／法遵跨部門簽核。
- 歷史 LAB artifacts 保持 LAB 標示，不改稱外部正式核准；若未來 production governance 要求跨部門簽核，再重新開啟正式證據 gate。
- 不部署、不 push、不執行雲端寫入或代簽腳本；需要時另取得授權。
- 不刪改原 spec 的要求來讓現有程式看似完成。

## 第一批：身分與資料完整性

目前狀態：第一輪已交付、審查退回續修，尚未整合主工作樹。Codex 原生子任務「Phase 0–3 Terra 實作｜第一批安全與資料完整性」，thread `01a062ff-8b12-79f3-9caf-4b7ef673eda0`，工作樹 `/Users/cfh00896102/.codex/worktrees/9158/teams-agent`。已由 read_thread 確認正式交付，不再以建立請求推測執行狀態。

審查員在該工作樹獨立 focused suite：75 passed。實作者回報完整 suite 809 passed、8 skipped，已要求查明 skip 原因並補裝必要依賴重跑。續修重點：查詢時間窗截斷前的完整 relation ownership、conversation-scoped 關聯、真實 feedback emitter→查詢的安全可用性、JWKS refresh 上限及重清洗/immutable event 政策相容性。不得只補測試 fixture 的 turn ID 來證明正式 feedback 路徑有效。

| 編號 | 審查證據 | 修正與獨立驗收門檻 |
| --- | --- | --- |
| AUTH-01 | `entra_auth.py` 將整份 JWKS 傳給 `jwt.decode`。本機 RSA 簽章、合法 issuer/audience/expiry 與假 JWKS transport 重現 `TypeError: Expecting a PEM-formatted key.` | 正確選取可信 tenant 的簽章金鑰；輪替、過期、錯 audience/issuer/tenant、未知 kid、畸形 claim、JWKS 失敗均有真簽章測試；錯誤不得洩漏 token 或變成未捕捉例外。 |
| AUTH-02 | 未映射角色回傳 ANALYST，缺 owner claim 採用預設單位；正式環境存在 header/JWT 驗證關閉開關。 | 明確角色及 owner scope，無指派 fail closed；正式環境不容許開關繞過驗證；未知 auth mode 拒絕；保留明確隔離的 LAB 契約。 |
| SCOPE-01 | `filter_events_by_scope` 只要允許一個 issue，即允許整段 conversation。本機 actor owner=A，兩事件分屬 A/B、同 conversation 不同 turn，實際回傳 `[a,b]`，應只允許 A。 | 不繼承整段 conversation 權限；混合 owner 的全文不可洩漏；不同 tenant／未知 taxonomy 不可借用允許事件的 scope；涵蓋清單、detail、搜尋、統計、匯出與查詢時間窗。 |
| PAGE-01 | 兩個 Firestore store 使用額外讀取的下一筆作為 `start_after` cursor。以實際 repository 加本機 snapshot/query double，5 筆、每頁 2 筆，回傳 `[0,1,3,4]`，漏掉 2。 | 多頁無遺漏／重複；末頁、相同時間排序、invalid cursor、篩選條件一致性；後续仍需 emulator／實際服務驗證。 |
| STORE-01 | Operational 與 Audit Firestore append 均為 get-then-set，讀寫間沒有原子保護。此項目前為程式審查證據，非雲端競爭測試。 | 原子 append-only；同 ID 重試與 payload 衝突有明確契約；併發不得覆寫 audit；持久化錯誤不可被成功回覆掩蓋。 |
| CI-01 | CI 僅安裝 dev extra；既有 Entra 測試透過關閉驗簽測試。 | CI 實際安裝並執行必要簽章依賴，無安全測試 skip；完整測試與 lint 結果附命令及基準。 |

## 第二批：已啟動的獨立實作

### FAQ Domain

Terra 原生 subagent：Fermat，`01a06301-2b87-71a2-8b4f-f3ee926d80c2`。

寫入範圍限定為新的 FAQ domain 模組、對應測試與 domain 交接文件；不得同時改第一批 auth/store 或共用 API。

交付門檻：不可變版本、完整審核生命週期、雙人核准、能力與資料 scope、持久化與 etag、併發及冪等、audit 一致性、原子 active pointer、可稽核 rollback、active-only 讀取與固定答案契約。

這一批不包含 endpoint／UI／現有 FAQ runtime 接線；domain 通過不能宣稱 Phase 2 完成。

進行中程式的提前審查已回饋實作者（尚非最終交付判定）：

- Pydantic model 不適用 dataclasses.replace，生命週期轉移需實測。
- 修改 owner 時須檢查舊 owner，不能只驗證新 owner 而允許奪取其他單位 FAQ。
- 自我核准例外不能只靠呼叫者傳入一段理由；核准需與實際提交者分離，正式環境不可繞過。
- 重放已成功的 transition 應依冪等結果回傳，不能因狀態已轉移而拒絕；fingerprint 不能依新生隨機版本 ID。
- 生效時間與 active snapshot 一致性須驗證。
- 初稿 Firestore transaction 未啟動即使用；以真 SDK 與 AnonymousCredentials（無網路請求）驗證 transaction ID，重現 `Transaction not in progress`。fake client 不可容許正式 SDK 不接受的呼叫順序。

### 驗收證據契約

Terra 原生 subagent：Maxwell，`01a06302-380b-7010-a359-07afb0dda223`。

基準證據：`ai_ops_signoff_checklist.json` 四項批准的備註均為 LAB 自驗；`ai_ops_formal_acceptance_audit.json` 卻標記 `formalAcceptanceComplete=true`。這些檔案不能證明真正跨部門核准。

目前決策：本里程碑接受 LAB 自驗作為 Phase 0 完成證據，跨部門正式證據不阻擋 Phase 2。仍須明確區分 LAB 與正式證據，不覆寫歷史 artifacts；缺失、過期、未執行或失敗的技術 gate 仍不能被 approved 狀態蓋過。

進行中程式的提前審查已回饋：發生時間（executedAt／approvedAt／verifiedAt）與 expiresAt 不能套用同一「必須在未來」判斷；JSON 自稱 EXTERNALLY_VERIFIED 並不是可信驗證。schema 通過與可信來源核驗須分離，缺少可信驗證時不可標記正式完成。

## 事件可靠性：已重現、部分已派發

Terra 原生 subagent：Einstein，`01a06304-2185-7351-b08c-b20f475ad29b`，負責 EVENT-01、COST-01 與 emitter 自由文字的遮罩。EVENT-02 持久化投遞仍待另批處理。事件契約改變後，查詢層須另批接線，不能讓 request summary 與 per-call 被重複加總。

### EVENT-01：重建同一請求不具穩定身分

程式：`agent_service/operations/emitter.py` 的 `build_turn_events`。

以相同 request、correlation、conversation 與一個 Issue 連續呼叫兩次：event ID 列表不相同，turn ID 不相同。原因是每次生成 UUID，issue occurrence ID 又依賴該 UUID；但 turn.received ID 採固定 correlation，造成重送時部分事件去重、部分新生。

驗收須涵蓋整個 request 的重放，而不只是同一 Event 物件 append 兩次。需定義跨 tenant/request 的穩定身分、事件時間與 payload 契約；對重試與真正新 turn 做區分。

### EVENT-02：分析 sink 失敗後無法由重送補送

程式：`operations/stores/composite_store.py`。

以真 Memory primary 搭配第一次 append 失敗、之後可恢復的 sink，對同一事件 append 兩次；實際 sink 僅被呼叫一次，收到 0 筆。第二次 primary 回傳未新增，所以完全跳過 sink。

需持久化 delivery/outbox、逐 sink 成功狀態、重試與退避、隔離失敗、可觀測積壓與對帳；crash/restart 後可恢复。`asyncio.create_task` 或只記 warning 不等於交付保障。驗收需故障注入，不以平均低延遲替代不遺失要求。

### COST-01：逐次模型呼叫歸屬尚未完成

程式：`emitter.py` 把整個 request cost summary 放在單一 usage event，model/provider 取 collector 第一個模型。

需每次模型呼叫的 provider/model/component、各種 token、計價版本、來源、耗時與 scope；request total 不可和 per-call 相加重複計費。需多模型、多 issue、部分價格未知、重試、fallback 與 FX 版本的對帳測試。

## 持久化隱私邊界：已重現、已派發

Terra 原生 subagent：Lagrange，`01a06305-569e-7bb0-bc7a-fb9ce76bc7e0`。写入範圍限定 masking、ingestion、audit 及專用新增測試／文件，不與 emitter 修改重疊。

以合成字串驗證，沒有使用真實憑證：

- issue 描述帶有 `password=`，主訊息雖遮罩，`issue.classified.normalizedDescription` 仍保留合成機密。
- `build_audit_event.reason` 原文保留合成機密。
- `after.changes` 清單內的 `secret` 欄位未被遞迴清除。

驗收必須檢查完整 serialized event/audit、巢狀 dict/list/tuple、所有自由文字與錯誤路徑，不只檢查 messageMasked。Credential 不能因 reveal 模式被還原；計量數字（例如 totalTokens）不能被誤當機密刪除；重複清洗須穩定。對未知機密的偵測限制須誠實揭露。

第一輪交付獨立 privacy/backoffice/integration：52 passed，已修復合法密碼支援回答遭誤遮罩。仍退回補常見自然語言秘密值及 JSON-in-text 格式；同時要求新遮罩政策版本與來源政策 provenance，不可把新舊行為都標 v1。歷史資料尚未 backfill，不作已修正宣稱。

## 匯出生命週期：程式審查發現、待派發

`ExportJobService` 目前以單一 JSON 檔與程序內 lock 保存作業，啟動只載入、不恢復 QUEUED/RUNNING 執行；到期僅在讀取 COMPLETED job 時改狀態，未刪除下載內容。下載也允許其他 SYSTEM_ADMIN/AUDITOR，與 Phase 1 的申請者綁定需明確對齊。

需跨程序持久化工作佇列、租約／重試／重啟恢復、申請者及現行 scope 驗證、短效授權、主動到期刪除及完成/失敗稽核。這些是程式審查發現，尚未經多實例或實際到期故障測試，不標為已完成。

## 全範圍後續門檻

下列仍需逐條對照原 spec，未列於第一批或第二批不代表不做。

| Phase | 尚需完整驗證的範圍 |
| --- | --- |
| 0 | Taxonomy 治理與修正事件；完整事件契約、可靠投遞及逐呼叫成本；四類資料責任分離；憑證排除、遮罩／保存／TTL；認證、能力及 scope；audit；Terraform、環境隔離、監控、交接及效能；正式治理決策。 |
| 1 | 全期間篩選與 KPI 下鑽；user/assistant timeline；受保護 transcript 的真正授權解遮罩；成本與 FX；知識 Markdown/PDF 發布及 Portal 真正連線；品質／健康；持久化且請求者綁定的匯出與到期刪除；UI 狀態、效能、真 BU UAT。 |
| 2 | FAQ domain 接線與 UI；正反例及 taxonomy 資料集；品質候選、去重合併、owner 與 etag、補知識後觀察及結案證據；可解釋 Gap 排序及語意分群；可恢復同步作業与原子發布；預算政策、告警、通知去重與核准收件人；完整授權／稽核及回歸。 |
| 3 | Prompt/model/flag registry 及不可變版本；可重現 eval manifest 与硬性安全 gate；獨立核准、黏性 canary、原子啟用、fallback/rollback；provider allowlist 與 secret ref；權限治理與撤權；audit、資料治理及受限全域搜尋；UI、監控與正式核准。 |

原始規格：

- [Phase 0](ai-ops-backoffice-phase-0-foundation-spec.md)
- [Phase 1](ai-ops-backoffice-phase-1-operations-mvp-spec.md)
- [Phase 2](ai-ops-backoffice-phase-2-quality-loop-spec.md)
- [Phase 3](ai-ops-backoffice-phase-3-ai-governance-spec.md)

## 審查記錄要求

每次交付應附：基準及變更路徑、對應 spec 條款、實際測試命令與結果、反例測試、持久化／整合／UI 驗證範圍、仍待外部證據。不把單一測試或檔案存在推論成整個 requirement 已完成。完成標記必須由審查員在獨立驗證後更新。

## 本輪獨立驗證紀錄

以下為子實作仍在修改時的中間檢查，不是最終交付結果：

```sh
cd agent_service
uv run --extra portal --extra firestore --extra dev pytest -q \
  tests/test_ops_privacy_boundary.py tests/test_operations_phase0.py \
  tests/test_ai_ops_backoffice.py
```

結果：51 passed、2 failed、1 warning。

- `test_signoff_checklist_sync_preserves_approvals`：舊 `--sync path` 與新 `--output` 要求不相容，交由 Maxwell 處理相容／遷移；不得放寬正式信任 gate。
- `test_conversation_detail_includes_correlation_and_masking`：沒有密碼值的合法 VPN 回答被整段遮罩，交由 Lagrange 修正；不得把測試改成接受正常知識內容消失。

較早一次完整 suite 的 801 passed 是更早的工作樹狀態，不能覆蓋這次失敗，也不能作為最終新功能驗收。收到穩定交付後須重新跑完整測試。

## 用量限制中斷與續作檢查點

2026-09-03 已透過工具確認：四個原生 subagent 均以 usage-limit error 結束；安全子任務 `01a062ff-8b12-79f3-9caf-4b7ef673eda0` 的續修回合亦 failed，非持續執行中。未使用重置額度、購買額度或改用其他模型。所有未提交檔案與獨立工作樹保留，沒有將部分變更當作驗收完成。

中斷後主工作樹完整 suite 命令：

```sh
cd agent_service
uv run --extra dev --extra portal --extra firestore pytest -q
```

最新結果：826 passed、4 failed、1 warning（16.14 秒）。此結果取代較早的中間測試狀態，但不包含獨立安全工作樹的變更。

續作優先順序與歸屬：

1. Fermat：修復 FAQ `submit`/測試的 `source_type`、`source_correlation_id` 契約不一致；檢查来源資料应属于 test creation 还是 submission，勿盲目加參數或刪除来源需求。
2. Lagrange：完成已啟動的 v2 policy；事件與回饋的 `password SENSITIVE_MARKER` 兩個測試仍洩漏合成秘密。原 `test_operations_phase0` 新生成事件 hardcoded v1 須按新政策做最小契約更新，保留歷史 v1 fixtures，不降低遮罩要求。
3. Einstein：完成重送／payload conflict／durable timestamp 與每呼叫歸屬；再接線 QueryService，避免成本 coverage、request latency、summary-only usage 等被新事件格式破壞。
4. Maxwell：驗收證據工具的檔案已產生但執行中斷，不能視為交付。需獨立驗證 trusted verifier、所有必要 gates、timestamp、舊 CLI 相容與歷史 artifacts 不可被自動升格。
5. 安全子任務：完成前述拒絕條件／完整 relation provenance、JWKS 節流、SDK 例外與 extras 測試後才考慮整合。

審查員認可的 feedback 設計方向：由 server 解析已持久化、相同 tenant 的 turn/request provenance，取得 immutable issue occurrence/type 關聯；不能信任 client 自宣 owner/tenant。缺失或多義者可保存為隔離且受稽核的未歸屬 feedback，但正常產品流程必須補齊 provenance，不能把永久不顯示 feedback 當成 Phase 1 完成。此為續作契約，不代表已接線。

額度恢復後應沿用既有 agent/context 或明確交接其寫入範圍，先查終止狀態及 git diff，不盲目重開同範圍編輯者。先收斂上述失敗和整合，再推進原規格剩餘 Phase 0–3 項目；正式部署與人工簽核依舊需授權。

### 後續恢復檢查

之後讀取帳戶用量：5 小時窗 used 12%、每週窗 used 47%，未回報觸限。此為當次讀值，不保證未來可用性，也不代表使用了 reset；沒有可用 reset credit，未購買或兌換。

先僅恢復 Lagrange `01a06305-569e-7bb0-bc7a-fb9ce76bc7e0` 原 context，已觀察到新的實作修改。授權只收斂隱私尾項，並把 `test_operations_phase0` 的新產生事件政策預期從 v1 更新到 v2，保留历史 v1 fixtures；其他實作者仍未重新啟動，不可宣稱全部正在執行。

額外獨立檢查：`test_ops_acceptance_evidence.py` 6 passed；驗收工具與專用測試的 ruff 檢查有 19 項錯誤（均為 UP017），尚未完成整批驗收。需後續由 Maxwell 恢復處理，而非由審查員代改。

## 最新續作批次與獨立證據

主工作樹再次完整執行 `uv run --extra dev --extra portal --extra firestore pytest -q`：**828 passed、2 failed、1 warning，16.37 秒**。這是穩定收到隱私尾項後的檢查，不包含獨立安全工作樹，也不代表後續正在修改的版本已通過。

- FAQ `submit` 的來源參數契約仍不一致，已恢復 Fermat 修復並收斂先前 domain 審查。
- URL 中的合成 token 被 emitter 轉成 `documentId=doc-token-SENSITIVE_MARKER`，即使 title/sourcePath 已遮罩，完整 serialized event 仍漏出。已恢復 Einstein 修復來源到 ID 的資料流；同批允許接線 QueryService 的 usage/cost 聚合，避免 request summary 重複計費。
- 隱私 v2 尾項交付完成；歷史資料沒有 backfill。Lagrange 改接獨立 EVENT-02 批次：durable outbox、逐 sink 重試與 lease、runtime/settings 接線，以及 BigQuery 失敗回報。該 sink 原先吞下 row errors／例外，且記錄原始 errors；若不修，outbox 仍會誤判成功。
- Maxwell 恢復驗收契約批次；安全子任務在原獨立工作樹恢復，仍未整合。
- 新增 Terra 原生子任務 Nash `01a064fc-8195-7853-806e-9a1857df42f2`，限定 Terraform／環境模板及專用測試、文件。負責環境與部署階段分離、一年 retention、Portal 真正 URL 配置、BQ envelope/IAM 與 Terraform ownership drift。禁止雲端 apply/import、部署或提交；真實 plan 仍須另外驗證。

### ACCEPT-02：同一 target 不等於同一驗收證據

主審以既有 acceptance test fixtures、固定時間及明確 test-only verifier 獨立重現：

1. 在同一 gate ID 的成功紀錄前插入 `FAILED`、exit 1 紀錄，驗證回傳 `[]`；dict 建索引吞掉衝突。
2. 只更換 checklist 的 gate artifact references、保留 UAT 原紀錄，但 environment/commit 相同，驗證仍回傳 `[]`；未綁定實際證據 manifest。
3. `requiredReviewerRoles=[{}]` 導致 `TypeError: unhashable type: 'dict'`，不是可報告的 fail-closed validation error。

已交回 Maxwell：重複與畸形輸入拒絕、不可變證據 binding、可信決策驗證與 schema-valid 分離。Fake verifier 只測試控制流程，不是真實組織核准。

### EXPORT-02：到期狀態查詢仍可取得內容

以合成匯出 fixture、真 `ExportJobService` 與 `BackofficeQueryService.get_export_job`，在暫存目錄獨立重現：

- 已到期作業回傳 `status=EXPIRED`，但 `result` 與 `downloadContent` 仍包含合成內容。
- 原申請者變成 ANALYST 且 owner scope 改為另一單位，仍取得舊匯出。
- 不同 user 的 AUDITOR 亦可取得該內容。
- 重建服務後，到期內容仍在持久化資料中。

`GET /api/exports/{job_id}` 直接回傳這份 query 結果；只有 `/download` 檢查 COMPLETED，不能保護 status endpoint 的內容。既有 TTL 測試僅 assert EXPIRED，未驗證內容被移除。已派發 Terra 原生子任務 Euclid `01a064ff-21b2-7b02-a712-8e481338ad1b`；限定 export service/format、新持久化模組與專用測試，以及 API 的 export/lifespan 接線。QueryService 與 Einstein 需協調，不准同時覆寫。須同步修正 metadata/content 分離、requester/current scope 授權、主動 TTL 清除與重啟恢復，不能只更新狀態。

本次等待已核對上述六個原生 agent handles，均未回傳 terminal；主樹已觀察到 delivery、usage projection、FAQ adversarial tests 與 Terraform 新變更，安全獨立工作樹亦開始修改 QueryService。這些均為執行中狀態，不是驗收完成；收到穩定交付後才重跑整批測試。
