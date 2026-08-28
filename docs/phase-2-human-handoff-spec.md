# Phase 2：Human Handoff 與 Session Routing 規格

- 文件狀態：Draft v0.2
- 建立日期：2026-08-27
- 適用專案：Teams Agent Backend
- 階段目標：維持現有 Teams SDK 與 Adapter，在 Agent Service／LangGraph 中完成可展示、可持久化的 Handoff 後端流程

## 1. 背景

目前 PoC 已完成下列主要能力：

- Teams Bot 訊息接收與回覆
- AI Agent 問答流程
- FAQ 與 Hybrid RAG 查詢
- 無知識時拒絕捏造答案
- 工單建立前的明確確認流程
- Teams Adaptive Card 與 Feedback 按鈕
- Conversation Repository（Memory、File、Firestore）
- Cloud Run、IAM 與 Secret Manager 部署架構

下一階段的主要缺口是 Human-in-the-Loop（HITL）／Human Handoff。當 AI 無法處理問題，或使用者主動要求人工協助時，系統需要在工單與線上客服之間提供明確選擇，並管理人工介入期間的訊息路由與生命週期。

集團「通知中心」是建立於 Azure Bot SDK 之上的內部管理包裝。本專案將它視為外部訊息與客服群組通道，不把 Handoff 的業務狀態及決策權交由通知中心管理。

## 2. 目標

Phase 2 應完成：

1. AI 無法解決問題時，產生可供確認的 Case Summary。
2. 提供「建立工單」與「線上客服」雙路徑。
3. 建立並持久化 Handoff Case。
4. 使用者選擇線上客服後，建立 Demo Handoff Session。
5. Demo HUMAN 狀態下停止將使用者訊息送入 AI Workflow。
6. 保存 HUMAN 狀態下的使用者訊息，並回覆固定且明確標示為 Demo 的提示。
7. 使用者輸入 `/close` 後結束 Demo Session，恢復 AI 處理。
8. 所有狀態轉移具備身分驗證、冪等性與 audit event。

本階段不宣稱已完成真正的人工客服接手或雙向訊息 Relay；通知中心與 Teams proactive messaging 留待後續整合階段。

## 3. 非目標

以下項目不納入 Phase 2 的必要交付：

- 完整客服排班與 SLA 系統
- 獨立客服工作台
- 複雜自動派案演算法
- 語音或 Teams 以外的客服通路
- 完整知識庫管理後台
- 對話分析 Dashboard
- 文件品質 Dashboard
- 多個 Active Handoff Case 同時存在於同一 Teams Conversation
- 讓通知中心直接管理本專案的 Firestore Session 狀態
- 建立、重寫或取代集團既有通知中心
- 維護通知中心底層的 Azure Bot SDK、客服群組管理或客服派案實作
- 串接通知中心 API、callback 或 webhook
- 建立真正的客服群組或執行客服指派
- 修改目前 Teams Adapter、Teams SDK 接入或 Teams App Package
- Teams proactive messaging 與真正的客服訊息 Relay
- 建立公開或測試用的「模擬客服回覆 API」

知識庫管理、對話分析與文件品質分析規劃至 Phase 3。

## 4. 架構原則

### 4.1 責任邊界

本階段的 Agent Service／LangGraph 負責：

- 判斷是否提出 Handoff
- Case Summary 產生、修改與確認
- 工單／人工客服路徑選擇
- Handoff Case lifecycle
- Session routing
- 權限、安全、資料保存與 audit
- Demo HUMAN 狀態下的固定提示與訊息保存
- 後續通知中心整合所需的 domain boundary

通知中心是集團既有的外部系統，不屬於本專案的建置範圍，且 Phase 2 不與其 API 整合。後續正式整合時，通知中心負責：

- 建立人工客服群組
- 指派客服人員
- 傳送訊息至客服群組
- 接收客服訊息與指令
- 回報群組、指派與關閉事件
- 封裝 Azure Bot SDK 與 Teams conversation reference 等平台細節

### 4.2 邏輯架構

```text
Teams
  ↓
Teams Adapter
  ↓
Handoff Router / Orchestrator
  ├─ AI_AGENT → 現有 LangGraph／FAQ／RAG／Ticket Workflow
  └─ HUMAN_DEMO
       ├─ 保存使用者訊息
       └─ 回傳固定 Demo 提示
```

Phase 2 只在現有 Agent Service 中加入 Handoff domain module 與 LangGraph routing，不修改 Teams Adapter，也不新增獨立微服務。Teams 仍使用目前 `/agent/chat` request／response 路徑。

### 4.3 技術隔離

Phase 2 不加入通知中心 SDK、HTTP client 或 callback endpoint。Handoff domain 不得依賴通知中心內部使用的 Azure Bot SDK 型別或套件，確保後續能以獨立 Gateway 接上既有通知中心。

## 5. 交付範圍

### 5.1 Phase 2：Backend Demo MVP

- Handoff Case domain model
- Firestore Handoff Repository
- Case Summary 產生與確認
- 工單／線上客服雙路徑文字回覆；維持現有 Teams Adapter contract
- Session routing
- HUMAN Demo 固定提示與訊息保存
- `/close` 狀態轉移
- 同時啟用現有 Mock Ticket Service，完整展示工單／線上客服雙路徑
- 失敗恢復與錯誤降級
- 單元及整合測試

Phase 2 不建立公開測試 API 模擬客服回覆。自動化測試使用 in-process Fake／stub 驗證 Handoff domain 與狀態轉移，不增加正式 API surface。

### 5.2 後續整合階段（不屬於 Phase 2）

- 串接既有通知中心 API
- 客服群組建立與客服指派
- 雙向訊息 callback
- API authentication
- timeout、retry 與 idempotency
- notification event audit log
- 客服無人接手與 Session 逾時處理
- Feedback 持久化
- 基礎營運事件查詢

## 6. Handoff 觸發條件

符合下列任一條件時，系統可以提出 Handoff：

- RAG 結果為 `NO_KNOWLEDGE`
- 已達最大追問次數，仍無法取得必要資訊
- 使用者明確要求「真人客服」、「線上客服」或同義意圖
- AI／知識服務發生允許降級的服務錯誤
- 工單服務失敗後，使用者選擇改由人工協助

Handoff 觸發只建立提議，不得直接改為 HUMAN routing。使用者必須先確認摘要及選擇線上客服。Phase 2 選擇後進入 `HUMAN_DEMO`；後續正式整合才會建立客服群組。

## 7. 使用者流程

```text
AI 無法解決
→ 產生 Case Summary
→ 顯示摘要給使用者
→ 使用者確認、修改、繼續補充或取消
→ 使用者選擇：
   1. 建立工單
   2. 聯絡線上客服
→ 執行對應流程
```

Phase 2 透過現有 `AgentResponse.answer` 顯示下列文字選項，不要求新增 Adaptive Card action：

- `建立工單`
- `聯絡線上客服`
- `修改摘要`／`繼續補充`
- `取消`

後端以目前訊息文字辨識選擇，並依 conversation 中的 active `caseId` 載入 Case；不得接受自由文字指定其他 `caseId`、requester 或權限。若後續改為 Adaptive Card，仍須由後端重新載入並驗證 Case。

## 8. Domain Model

### 8.1 HandoffCase

```text
caseId: string
sessionId: string
tenantId: string
conversationId: string
requesterId: string
requesterName: string | null
status: HandoffStatus
providerMode: DEMO
summary: CaseSummary
createdAt: datetime
updatedAt: datetime
closedAt: datetime | null
version: integer
correlationId: string
```

### 8.2 CaseSummary

```text
issue: string
userNeed: string
conversationHighlights: string[]
attemptedSolutions: string[]
unresolvedReason: string
requestedOutcome: string
generatedAt: datetime
confirmedAt: datetime | null
confirmedBy: string | null
version: integer
```

工單與人工客服必須使用同一份已確認摘要，避免兩條路徑重新生成後產生不同內容。

若 LLM 摘要產生失敗，系統必須使用結構化模板產生 fallback summary，不得因模型不可用而阻止使用者建立工單或聯絡客服。

### 8.3 HandoffEvent

```text
eventId: string
caseId: string
eventType: string
actorType: USER | SYSTEM
actorId: string | null
occurredAt: datetime
payload: object
correlationId: string
```

Event payload 不得包含 secret；對話內容必須依資料最小化原則及 retention policy 保存。

### 8.4 HandoffRepository 決策

Phase 2 建立獨立 `HandoffRepository` Protocol，不把完整 Handoff lifecycle 塞入 `ConversationMessage`。Repository 沿用專案既有的三種執行模式：

- `MEMORY`：單元測試與本機快速測試
- `FILE`：單機開發與除錯
- `FIRESTORE`：Cloud Run Demo 與持久化驗收

Repository 至少提供：

```text
create_case(case)
get_case(case_id)
get_active_case(tenant_id, conversation_id, requester_id)
update_summary(case_id, summary, expected_version)
transition(case_id, from_status, to_status, expected_version)
close_case(case_id, requester_id, expected_version)
append_event(event)
```

設計規則：

- 同一個 `tenantId + conversationId + requesterId` 同時最多一個非終止 Case。
- 狀態轉移使用 transaction 或 optimistic concurrency control。
- Handoff routing 以 `HandoffRepository` 中的 active Case 為準。
- 使用者與固定提示的完整文字沿用現有 `ConversationRepository` 保存，不在 Handoff Repository 重複存一份。
- Handoff Event 只保存狀態、時間、actor、correlation ID 與必要 metadata，不保存完整訊息內容。

## 9. 狀態機

### 9.1 狀態

Phase 2 主要狀態：

```text
OFFERED
→ SUMMARY_REVIEW
→ DEMO_ACTIVE
→ CLOSED
```

例外及終止狀態：

```text
CANCELLED
FAILED
EXPIRED
ROUTED_TO_TICKET
```

### 9.2 狀態轉移

| 原狀態 | 動作／事件 | 新狀態 |
|---|---|---|
| 無 Case | AI 提出 Handoff | `OFFERED` |
| `OFFERED` | 產生並顯示摘要 | `SUMMARY_REVIEW` |
| `SUMMARY_REVIEW` | 使用者選擇線上客服 | `DEMO_ACTIVE` |
| `SUMMARY_REVIEW` | 使用者選擇建立工單 | `ROUTED_TO_TICKET` |
| `SUMMARY_REVIEW` | 使用者取消 | `CANCELLED` |
| `DEMO_ACTIVE` | 使用者傳送一般訊息 | 保持 `DEMO_ACTIVE`、保存訊息並回覆固定提示 |
| `DEMO_ACTIVE` | 原 requester 輸入 `/close` | `CLOSED` |
| 非終止狀態 | Session TTL 到期 | `EXPIRED` |

### 9.3 Routing Target

`AI_AGENT`／`HUMAN` 是由 Case 狀態推導的 routing target，不另存成可能與 Case lifecycle 不一致的第二份狀態。

| Case 狀態 | Routing Target |
|---|---|
| 無 Active Case | `AI_AGENT` |
| `OFFERED`、`SUMMARY_REVIEW` | `AI_AGENT` |
| `DEMO_ACTIVE` | `HUMAN_DEMO` |
| `CLOSED`、`CANCELLED`、`FAILED`、`EXPIRED`、`ROUTED_TO_TICKET` | `AI_AGENT` |

`DEMO_ACTIVE` 期間收到的訊息應保存至 Handoff Case／Conversation history，不得送進 AI Workflow，也不得假裝已傳送給真正客服。

## 10. Session 規則

- Phase 2 中，同一個 Teams conversation 同時最多存在一個非終止狀態的 Handoff Case。
- 每個 Case 必須具有獨立 `caseId`。
- `HUMAN_DEMO` routing 下的新訊息不得呼叫 LLM、FAQ 或 RAG。
- HUMAN Demo 訊息只寫入對應 Case／Conversation，並回覆固定 Demo 提示。
- Case 關閉後，下一則使用者訊息恢復 AI 處理。
- Cloud Run instance 重啟、scale-to-zero 或切換 instance 後，Handoff 狀態不得遺失。
- 狀態更新必須使用 transaction 或 optimistic concurrency control，避免重複選擇與平行請求造成錯誤轉移。
- Phase 2 先採 conversation-level routing；資料模型保留 `caseId`，以便未來演進為 issue-level Handoff。
- Demo Session timeout 設為可配置的 `HANDOFF_DEMO_TIMEOUT_HOURS`，預設 24 小時。
- `sessionExpiresAt` 控制何時將 Case 標記為 `EXPIRED` 並恢復 AI；它不刪除 Case 或對話紀錄。

### 10.1 Retention 與 Session timeout

Session timeout 與資料保存期限必須分開：

| 資料 | 建議期限 | 說明 |
|---|---:|---|
| Active Demo Session | 24 小時 | `sessionExpiresAt` 到期後轉為 `EXPIRED` 並恢復 AI，不刪除紀錄 |
| 完整對話訊息 | 兩年 | 依公司紀錄留存政策，由 Conversation Repository 保存 |
| Handoff Case／Summary | 兩年 | 依公司紀錄留存政策保存 |
| Handoff audit metadata | 兩年 | 依公司紀錄留存政策保存 |
| 附件 | 兩年 | 公司留存範圍包含附件；Phase 2 Demo 不新增附件 Relay，未來支援時必須套用相同政策 |

公司要求的兩年是資料 retention policy，不是 Session lifecycle timeout。Handoff 資料使用 `retentionExpiresAt` 表示兩年保存期限；若以 Firestore TTL policy 自動清除，TTL 只是執行 retention policy 的技術機制。

建議設定：

```text
HANDOFF_DEMO_TIMEOUT_HOURS=24
HANDOFF_RETENTION_DAYS=730
```

目前尚未確認公司是否有 legal hold、調查保全或其他禁止刪除條件。此項不阻擋 Phase 2 Demo；資料模型應允許 `retentionExpiresAt` 為空或延後，讓未來能暫停 Firestore TTL。Phase 2 不實作 legal hold 的管理 API、後台或操作流程。

## 11. 未來 Notification Center Contract（Phase 2 不實作）

本節只保留後續整合邊界，不是 Phase 2 交付項目。Phase 2 不建立 Gateway、HTTP client、callback endpoint 或公開測試 API。

### 11.1 專案內介面

```text
NotificationCenterGateway

create_case(case, summary, idempotency_key) -> ExternalCase
send_message(case_id, message, idempotency_key) -> ExternalMessage
close_case(case_id, reason, idempotency_key) -> CloseResult
```

未來 Gateway 與正式通知中心實作應遵守同一份 contract tests。

### 11.2 Outbound API 建議

```http
POST /human-cases
POST /human-cases/{externalCaseId}/messages
POST /human-cases/{externalCaseId}/close
```

每次請求至少包含：

- `caseId`
- `correlationId`
- `idempotencyKey`
- timestamp
- 經驗證的服務身分

### 11.3 Callback API 建議

```http
POST /integrations/notification-center/events
```

支援事件：

```text
case.created
case.assigned
message.received
case.closed
case.failed
```

Callback 至少包含：

- `eventId`
- `eventType`
- `caseId`
- `externalCaseId`
- `occurredAt`
- `correlationId`
- 事件內容
- 可驗證的簽章或服務身分

## 12. Demo 訊息行為與未來 Relay 目標

### 12.1 Phase 2：HUMAN Demo 固定提示

Phase 2 不執行真正的雙向 Relay。使用者選擇線上客服後，系統在原 Bot 私訊顯示：

```text
已進入真人客服模式（Demo）。

目前尚未串接通知中心。後續訊息會保存於 Handoff Case，
且不會交由 AI 自動回答。輸入 /close 可結束 Demo 人工服務。
```

`DEMO_ACTIVE` 期間收到一般訊息時，後端應保存訊息並固定回覆：

```text
您的訊息已加入人工客服案件（Demo）。
目前尚未串接通知中心，因此不會實際傳送給客服人員。
```

固定提示不得使用「客服已接手」、「訊息已送達客服」等會造成誤解的文字。

Phase 2 不提供模擬客服回覆 API。測試透過 in-process Fake／stub 驗證，不暴露測試能力至正式服務。

### 12.2 後續目標：Personal scope 同視窗 Relay

正式串接通知中心後，Handoff 入口限定於 Teams Personal scope。使用者留在原本的 Bot 私訊視窗，不加入後台客服群組：

- 通知中心建立只供客服處理的後台群組。
- 使用者訊息由 Handoff Router 經 NotificationCenterGateway 轉送至客服群組。
- 客服訊息由通知中心 callback 回傳，再由 Teams Adapter 主動送至原 Bot 私訊。
- 客服訊息在使用者端仍由 Bot 發送，因此畫面必須清楚標示 `真人客服｜客服名稱`，不得讓使用者誤以為是 AI 回覆。
- 人工處理期間，原 Personal conversation 保持 `HUMAN` routing，不呼叫 AI、FAQ 或 RAG。

此模式必須處理 message mapping、ordering、retry、deduplication、callback authentication 與 relay loop prevention。

### 12.3 正式 Handoff 狀態提示

使用者選擇線上客服後，系統先顯示「正在為您連線真人客服」，Case 進入 `CONNECTING`／`WAITING_AGENT`。只有收到通知中心的 `case.assigned` 事件後，才能顯示「已切換至真人客服」並進入 `ACTIVE`。

若通知中心建立群組或指派客服失敗，不得顯示已切換成功；系統應提供重試、取消或改建工單選項。

### 12.4 Channel／Group Chat scope

Channel 或 Group Chat 中不得直接切換整個 conversation 為 HUMAN，以免其他使用者訊息被轉送客服或在公開範圍揭露問題摘要。

在這些 scope 觸發 Handoff 時，Bot 只顯示前往 Personal scope 的按鈕或 deep link。使用者進入 Bot 私訊後，系統才建立或繼續 Handoff Case，並要求確認 Case Summary。

### 12.5 正式整合 Fallback

同視窗 Relay 的必要前提是既有通知中心提供客服訊息 callback、客服指派事件及訊息識別資訊。若正式 API 缺少其中任何能力，必須先由通知中心團隊補足 contract，或另行核准降級為「將使用者加入新客服群組」；不得在實作階段自行改變使用者流程。

## 13. `/close` 規格

Phase 2 Demo 中：

1. 只有建立該 Case 的原 requester 可在原 Bot Personal conversation 輸入 `/close`。
2. Handoff Orchestrator 驗證 trusted identity、conversation 與 `caseId`。
3. Case 由 `DEMO_ACTIVE` 轉為 `CLOSED`。
4. 系統回覆 Demo Session 已結束並恢復 AI routing。
5. `/close` 本身不得送入 AI；從使用者下一則訊息才恢復 AI Workflow。

重複 `/close` 必須為無副作用的成功回應。客服端 `/close` 與通知中心 callback 留待後續正式整合。

## 14. 失敗與恢復

| 情境 | 必要行為 |
|---|---|
| 摘要模型失敗 | 使用模板摘要 |
| 重複選擇線上客服 | 回傳既有 Case，不重複建立 Handoff Case |
| `DEMO_ACTIVE` 收到一般訊息 | 保存訊息、固定回覆 Demo 提示，不呼叫 AI |
| 非 requester 輸入 `/close` | 拒絕操作，不改變 Case 狀態 |
| Case version 衝突 | 拒絕過期 action，重新載入最新狀態 |
| Session 過期 | 關閉或標記 `EXPIRED`，恢復 AI 並留下 audit event |
| 服務重啟 | 從 Firestore 恢復 Case 與待處理訊息 |

## 15. 安全與治理

- 使用者身分只能來自 Teams／Entra trusted context。
- `caseId` 必須與 tenant、conversation 及 requester 綁定。
- 非 requester 不得修改或關閉 Demo Handoff Case。
- Log 不得包含 token、完整敏感對話或不必要個資。
- Handoff Case、message 與 event 必須設定 retention／TTL。
- Case Summary 進入 Demo HUMAN 狀態前必須經使用者確認。
- Case Summary 應排除密碼、access token、憑證與其他不應轉送的敏感資訊。
- 所有重要狀態改變必須建立 audit event。

## 16. Observability

所有 Handoff log 與 event 至少包含：

- `caseId`
- `sessionId`
- `correlationId`
- `eventType`
- `fromStatus`
- `toStatus`
- `elapsedMs`
- `errorType`（若有）

不得以完整使用者訊息作為 log field。Phase 2 應能量測：

- Handoff offer 數
- 使用者接受率
- Demo Handoff 啟用數
- Demo Handoff 關閉率
- Handoff 後改建工單比例

## 17. Feedback 與營運事件

現有 Teams 👍／👎 Feedback 行為維持不變。Feedback 持久化不屬於 Phase 2；Phase 2 只建立 Handoff audit events，供後續階段分析：

- FAQ hit
- RAG hit
- no-answer
- handoff offered
- handoff accepted
- ticket selected
- handoff closed
- handoff message saved

Phase 2 僅交付事件資料與必要查詢介面，不交付完整 Dashboard。

## 18. 非功能需求

### 18.1 一致性

- Case 狀態轉移必須為原子操作。
- 建立、關閉與重複提交必須具備冪等性。

### 18.2 可用性

- 摘要 LLM 故障不得阻止工單或 Demo Handoff 入口。
- Demo Handoff 不得依賴任何外部通知中心服務。

### 18.3 相容性

- 不破壞現有 `/agent/chat`、streaming、Feedback 與 Ticket 行為。
- Echo mode 不強制啟用 Handoff。
- Handoff 關閉後必須能繼續使用原 Conversation context。

## 19. 驗收標準

- [ ] `NO_KNOWLEDGE` 可顯示工單／客服雙路徑。
- [ ] 使用者主動要求真人客服時可進入相同流程。
- [ ] 未經使用者確認不得進入 `DEMO_ACTIVE`。
- [ ] 使用者可確認、修改或取消 Case Summary。
- [ ] 工單與客服使用相同的已確認摘要。
- [ ] Demo 環境啟用 Mock Ticket Service，選擇建立工單可取得 mock ticket ID。
- [ ] 選擇工單後 Case 進入 `ROUTED_TO_TICKET`，不誤記為人工客服完成。
- [ ] 重複選擇只建立一個 Handoff Case。
- [ ] `HUMAN_DEMO` routing 下的訊息不呼叫 AI、FAQ 或 RAG。
- [ ] `HUMAN_DEMO` 訊息會保存並回覆固定 Demo 提示。
- [ ] 固定提示不宣稱已有真人接手或訊息已送達客服。
- [ ] 原 requester 輸入 `/close` 後 Case 關閉並恢復 AI routing。
- [ ] 非 requester 不能關閉 Case。
- [ ] Cloud Run 重啟後 Handoff 狀態仍存在。
- [ ] 競爭操作不會產生兩個 Active Case。
- [ ] 所有流程均具有 `caseId` 與 `correlationId`。
- [ ] Log 不包含憑證與完整敏感對話。
- [ ] 原有 FAQ、RAG、Ticket、Conversation、Feedback 測試無 regression。
- [ ] 不新增通知中心 client、callback endpoint 或模擬客服回覆 API。

## 20. 建議實作順序

1. 建立 Handoff domain model、狀態機及 repository contract。
2. 實作 Handoff Repository 與 concurrency control。
3. 實作 Case Summary 與 deterministic fallback template。
4. 實作 Handoff Router，確保 `HUMAN_DEMO` 訊息不進 AI。
5. 以現有 AgentResponse／Teams Adapter contract 回傳雙路徑文字提示。
6. 實作固定 Demo 提示與訊息保存。
7. 實作 requester `/close`、失敗恢復與 audit event。
8. 執行 regression、安全與雲端驗收。

## 21. Spec 定版前待確認

已定案：

- Handoff 正式入口限定於 Personal scope。
- 使用者留在原 Bot 私訊視窗，由系統與後台客服群組進行雙向 Relay。
- Channel／Group Chat 只引導使用者前往 Personal scope，不切換整個 conversation。
- 本專案只串接集團既有通知中心，不負責建立、重寫或維護通知中心本體。
- Phase 2 不串接通知中心 API，也不修改 Teams Adapter／Teams SDK 接入。
- Phase 2 只修改 Agent Service／LangGraph 與其後端持久化。
- `HUMAN_DEMO` 保存訊息並回覆固定提示，不提供模擬客服回覆 API。
- 使用獨立 `HandoffRepository` Protocol，並提供 Memory／File／Firestore 實作。
- 完整對話文字只保存於既有 Conversation Repository，不在 Handoff Repository 重複保存。
- Demo Session timeout 預設 24 小時，設定名稱為 `HANDOFF_DEMO_TIMEOUT_HOURS`。
- Handoff 紀錄依公司政策保存兩年，`HANDOFF_RETENTION_DAYS=730`。
- 公司兩年留存範圍包含附件；Phase 2 Demo 不新增附件功能，未來支援時沿用相同 retention policy。
- 摘要修改採「繼續補充後重新產生」，不要求新的可編輯 Adaptive Card。
- Demo 驗收限定 Personal scope；Channel／Group Chat deep link 延後至 Adapter 整合階段。
- Demo 同時啟用現有 Mock Ticket Service。
- 使用 deterministic parser 辨識建立工單、線上客服、繼續補充、取消與 `/close`。

非 Phase 2 Demo 阻擋項目、正式上線前確認：

1. 公司是否有 legal hold 或延後刪除機制要求。

以上問題確認後，將本文件更新為 Phase 2 Spec v1.0，再進入功能實作。
