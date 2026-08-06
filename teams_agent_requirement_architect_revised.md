# Microsoft Teams IT 智能助手 POC
## 架構優化版系統開發需求

> 文件定位：本文件為既有 BU 需求的架構優化版本。  
> 核心原則：保留既有 Python、Microsoft 365 Agents SDK Python、LangGraph、Hybrid RAG 與 Cloud Run 雙服務架構，以最小改造完成可驗證的 IT 智能助手 POC。

---

# 1. 專案目標

建置一個運行於 Microsoft Teams 的企業內部 IT 智能助手，協助使用者：

1. 查詢 IT 常見問題。
2. 查詢企業內部 IT 知識文件。
3. 在問題描述不足時補充必要資訊。
4. 在知識庫無法解決時，詢問是否建立 IT 工單。
5. 查詢使用者自己的工單。
6. 保存必要的對話上下文，以支援連續問答。

本階段目標是驗證以下核心流程：

```text
Teams 使用者提問
→ 判斷是否屬於 IT 問題
→ 拆解最多三個獨立問題
→ FAQ 或知識庫回答
→ 資訊不足時追問
→ 無法解決時詢問是否建立工單
→ 回傳結果與來源
```

本階段不以建立完整客服平台、工單平台、知識管理後台或營運分析系統為目標。

---

# 2. 架構決策

## 2.1 保留既有技術棧

本專案維持以下既有技術：

- Runtime：Python 3.11
- Teams Agent Framework：Microsoft 365 Agents SDK Python
- Workflow Framework：LangGraph
- Teams Adapter Hosting：aiohttp
- Agent Service Hosting：FastAPI
- AI Model：Gemini
- 預設 Knowledge Backend：既有 Hybrid RAG
- 部署環境：Google Cloud Run
- 雲端機密管理：Google Secret Manager
- Teams 回覆：文字與 Adaptive Card
- 圖片存取：既有短效簽章 URL 機制

不得僅因「Node.js 可能適合高併發」而重寫既有 Python 服務。

技術棧是否調整，應根據以下實證：

- 壓力測試結果
- 必要功能缺口
- 維運團隊能力
- SDK 支援狀況
- 實際效能瓶頸

## 2.2 保留雙服務架構

```text
Microsoft Teams
      │
      ▼
Azure Bot Service
      │
      ▼
Public Teams Adapter
Microsoft 365 Agents SDK Python
      │ Cloud Run IAM
      ▼
Private LangGraph Agent Service
      │
      ├─ FAQ
      ├─ Hybrid RAG
      ├─ Optional Gemini File Search
      ├─ Conversation Repository
      └─ Ticket Service Adapter
```

Teams Adapter 與 Agent Service 應維持責任分離：

### Teams Adapter

負責：

- 接收 Teams Activity
- 驗證 Connector JWT
- 取得 Teams 與 Entra 使用者資訊
- 清除 Bot Mention
- 呼叫 Agent Service
- 產生 Teams 回覆與 Adaptive Card
- 圖片簽章與尺寸處理
- 錯誤降級

### Agent Service

負責：

- 對話上下文
- 問題拆解
- IT 問題判斷
- FAQ
- 資訊追問
- 知識檢索
- 工單流程
- 回覆組裝
- 執行紀錄

---

# 3. 設計原則

## 3.1 業務能力優先於指定產品

需求應描述系統需要具備的能力，不應將特定語言、資料庫或託管檢索產品直接視為唯一實作。

## 3.2 外部服務透過介面隔離

以下能力須透過 Interface 或 Adapter 封裝：

- Knowledge Service
- Conversation Repository
- Ticket Service
- User Directory Service

LangGraph Workflow 不得直接依賴特定資料庫、檢索產品或工單系統。

## 3.3 POC 不建立未驗證的未來平台能力

本階段不因「未來可能使用」而預先建立：

- 完整 Issue Repository
- 完整案件生命週期
- 工單催辦平台
- FAQ 管理後台
- 知識庫管理後台
- 多 Agent Framework
- Approval Framework
- 企業級營運報表
- 正式高可用與災難復原

---

# 4. 核心功能範圍

## 4.1 IT 問題判斷

系統應判斷使用者問題是否屬於企業 IT 支援範圍。

IT 問題例如：

- 內部系統無法登入
- VPN 問題
- Outlook 或 Microsoft 365 問題
- 電腦與周邊設備異常
- IT 權限申請
- 公司系統操作流程
- 工單建立或查詢

非 IT 問題不應送入企業知識庫查詢。

### 全部為非 IT 問題

回覆：

```text
我目前專門協助處理公司 IT 問題。
請描述使用的系統、功能或錯誤訊息，我會協助你確認。
```

### IT 與非 IT 混合

- 處理 IT 問題。
- 對非 IT 問題簡短說明不在服務範圍。
- 不應靜默忽略使用者提出的內容。

---

## 4.2 多問題拆解

一則訊息最多處理三個獨立 Issue。

```dotenv
MAX_ISSUES_PER_MESSAGE=3
```

例如：

```text
VPN 無法登入，Outlook 一直要求重新登入，另外今天天氣如何？
```

應拆解為：

1. VPN 無法登入：IT
2. Outlook 重複登入：IT
3. 天氣：非 IT

每個 IT Issue 可分別進行 FAQ、追問或知識查詢。

不得因單一 Issue 需要追問或處理失敗，而停止其他 Issue。

超過三個 Issue 時，應請使用者優先選擇最需要處理的問題。

---

## 4.3 Issue 資料模型

POC 階段 Issue 為 Workflow 暫態資料，不建立獨立 Issue Repository。

```python
class Issue:
    id: int
    description: str
    is_it: bool
    readiness: str
    missing_info: list[str]
    route: str
    faq_key: str | None
    ticket_action: str | None
```

### Readiness

只使用：

- `READY`
- `NEED_MORE_INFO`
- `NOT_IT`

### Route

只使用：

- `FAQ`
- `KNOWLEDGE`
- `TICKET`
- `NOT_IT`

### 處理結果

另以 result type 表示：

- `FAQ_ANSWERED`
- `KNOWLEDGE_ANSWERED`
- `NO_KNOWLEDGE`
- `NEED_MORE_INFO`
- `TICKET_CREATED`
- `TICKET_FOUND`
- `FAILED`

不使用單一 Status 同時表達問題狀態與處理結果。

---

# 5. LangGraph Workflow

## 5.1 Workflow 節點

```text
Teams Message
      │
      ▼
Load Conversation
      │
      ▼
Extract Issues
      │
      ▼
Filter IT Issues
      │
      ▼
Process Issues
  ├─ FAQ
  ├─ Ask More Info
  ├─ Knowledge Search
  └─ Ticket Operation
      │
      ▼
Deterministic Response Builder
      │
      ▼
Save Conversation
      │
      ▼
Teams Response
```

## 5.2 Workflow State

```python
class AgentState(TypedDict):
    request: AgentRequest
    correlation_id: str
    user: UserContext
    conversation: ConversationContext
    issues: list[Issue]
    issue_results: list[IssueResult]
    final_response: str
```

## 5.3 回覆組裝不得再呼叫 LLM

Response Builder 應使用 Python deterministic template。

不得另外呼叫 LLM 進行：

- 段落重寫
- 來源整理
- FAQ 改寫
- 工單結果潤飾

避免：

- 修改原始答案
- 遺漏來源
- 增加延遲
- 增加 token 成本
- 產生未提供內容

---

# 6. Issue Extractor

## 6.1 職責

Issue Extractor 只負責：

1. 拆解最多三個問題。
2. 判斷是否為 IT 問題。
3. 判斷是否具有足夠資訊。
4. 選擇高階 Route。
5. 提供最少必要的 missingInfo。

Issue Extractor 不負責：

- 判斷問題是否已真正解決
- 維護 Issue Lifecycle
- 自由產生大量企業 Intent
- 產生 FAQ 答案
- 產生工單類別 ID
- 直接建立工單

## 6.2 結構化輸出

輸出必須使用 Pydantic schema 驗證。

```json
{
  "issues": [
    {
      "id": 1,
      "description": "使用者無法登入 VPN",
      "isIT": true,
      "readiness": "NEED_MORE_INFO",
      "missingInfo": [
        "使用的 VPN 應用程式名稱",
        "畫面顯示的錯誤訊息或錯誤碼"
      ],
      "route": "KNOWLEDGE",
      "faqKey": null,
      "ticketAction": null
    }
  ]
}
```

## 6.3 追問限制

每個 Issue 最多追問兩項資訊。

優先順序：

1. 系統或應用程式名稱
2. 錯誤訊息或錯誤碼
3. 發生問題的功能
4. 問題發生前的操作
5. 是否可重現

不得詢問：

- 密碼
- 驗證碼
- Access Token
- Secret
- 員工編號
- 非必要個人資料

使用者補充資訊後，系統應重新載入對話並執行 Issue Extractor。

---

# 7. FAQ

## 7.1 FAQ 適用範圍

FAQ 僅用於：

- 答案固定
- 不需文件檢索
- 高頻且流程穩定
- 不需要依使用者條件變化

例如：

- 密碼重設入口
- IT 服務時間
- VPN 安裝入口
- 固定聯絡窗口

## 7.2 FAQ 不建立大型 Intent Taxonomy

FAQ 使用少量明確的 `faqKey`。

```json
{
  "id": "FAQ_001",
  "faqKey": "PASSWORD_RESET",
  "enabled": true,
  "answer": "請至公司密碼管理入口進行密碼重設。"
}
```

Issue Extractor 僅能從已配置的 FAQ Key 中選擇。

無法明確對應時：

```text
faqKey = null
route = KNOWLEDGE
```

## 7.3 FAQ Service

FAQ Service 僅負責：

- 依 faqKey 取得固定答案
- 檢查是否啟用

FAQ Service 不得：

- 呼叫 LLM
- 做語意相似度
- 改寫 FAQ
- 自行生成內容

---

# 8. Knowledge Service

## 8.1 Knowledge Service Interface

```python
class KnowledgeService(Protocol):
    async def search(
        self,
        query: str,
        user_context: UserContext,
    ) -> KnowledgeResult:
        ...
```

```python
class KnowledgeResult:
    found: bool
    answer: str
    sources: list[Source]
    images: list[SourceImage]
    backend: str
```

## 8.2 預設使用既有 Hybrid RAG

預設實作：

```text
HybridKnowledgeService
```

保留既有：

- BM25
- Embedding Search
- Top-K
- Minimum Score
- Query Rewrite
- Relevance Check
- Grounded Answer
- Citation
- Source Image
- ACL
- Tenant Allowlist

```dotenv
KNOWLEDGE_SERVICE_MODE=HYBRID
```

## 8.3 Gemini File Search 僅作為候選 Adapter

新增：

```text
GeminiFileSearchKnowledgeService
```

但本階段不得直接取代 Hybrid RAG。

Gemini File Search 第一階段只做技術 Spike：

- 建立 Store
- 上傳少量測試文件
- 執行中文查詢
- 取得來源
- 測試 metadata filter
- 測試文件刪除
- 比較錯誤碼與專有名詞命中能力

只有在 A/B Test 證明其品質、成本或維運具有明顯優勢後，才考慮設為預設。

本階段不要求完整 File Search 文件同步平台。

## 8.4 回答原則

Knowledge Service 必須：

- 只根據知識庫內容回答
- 找到答案時列出來源
- 找不到答案時明確表示未命中
- 文件衝突時指出衝突
- 不得使用模型一般知識補充企業流程
- 不得編造文件、網址、電話或操作步驟

---

# 9. 知識文件治理

每份知識文件建議包含：

```yaml
title: VPN 登入問題
owner: IT Infrastructure
version: "1.2"
effectiveDate: 2026-07-01
reviewDate: 2026-10-01
audience:
  - all-employees
```

系統應保留：

- 文件名稱
- 文件版本
- 文件擁有者
- 生效日期
- 檢視日期
- 可見對象

文件品質、版本與權限治理，優先級高於替換檢索產品。

---

# 10. Conversation Context

## 10.1 Conversation 目的

Conversation 只用於：

- 連續問答
- 使用者補充資訊
- 工單確認
- 最近對話上下文

不作為完整客服案件管理系統。

## 10.2 設定

```dotenv
CONVERSATION_TIMEOUT_HOURS=24
CONVERSATION_HISTORY_ROUNDS=5
MAX_HISTORY_MESSAGES=10
```

超過 Timeout 後建立新 Conversation。

## 10.3 Repository Interface

```python
class ConversationRepository(Protocol):
    async def find_conversation(...)
    async def create_conversation(...)
    async def save_message(...)
    async def get_recent_messages(...)
```

本階段可先使用既有環境核准的儲存方式。

不得因 BU 指定 MongoDB 而直接將 MongoDB 視為唯一選擇。

資料庫選型應考量：

- 公司核准狀況
- Cloud Run 網路可達性
- 資料落地政策
- 資料保存期限
- 維運能力
- 成本

本機或測試可使用 Fake Repository。

---

# 11. 工單整合

## 11.1 Ticket Service Interface

```python
class TicketService(Protocol):
    async def get_ticket_items(...)
    async def create_ticket(...)
    async def list_tickets_by_requester(...)
    async def get_ticket(...)
```

本階段不要求工單催辦。

## 11.2 Ticket Service 模式

只需支援：

```text
DISABLED
HTTP
```

```dotenv
TICKET_SERVICE_MODE=HTTP
TICKET_SERVICE_BASE_URL=https://example.internal
```

Agent 不應判斷後端是 Mock 或正式工單系統。

## 11.3 建立工單條件

只有以下情況可詢問是否建立工單：

- 知識庫未命中
- 文件內容不足以解決
- 使用者操作後仍未解決
- 使用者主動要求建立工單

未經明確確認，不得建立工單。

明確確認例如：

- 請幫我建立工單
- 好，幫我開單
- 我要報修

以下不視為確認：

- 還是不能用
- 好像需要找人
- 可能要報修
- 不知道怎麼辦

## 11.4 建立工單資料

工單資料至少包含：

- requesterId
- requesterName
- requesterEmail
- title
- description
- ticketItemId
- priority

requesterId、姓名與 Email 必須來自可信任的 Teams／Entra context，不接受使用者在對話中自由指定。

若無法取得必要身分資料，應停止建立並回覆明確錯誤。

## 11.5 POC 限制

- 同一輪最多建立一張工單
- 不支援一次建立多張工單
- 不支援催辦
- 不支援取消
- 不支援補件
- 不支援跨使用者查詢

---

# 12. 使用者身分

每次收到 Teams 訊息時，應取得可用的：

- Teams User ID
- Entra Object ID
- Display Name
- Email（若權限允許）

Email 若無法直接取得，可透過 User Directory Service 封裝 Microsoft Graph 查詢。

不得要求使用者提供：

- 密碼
- 驗證碼
- Token
- Secret
- 其他認證資訊

---

# 13. 回覆格式

## FAQ

```text
問題：Outlook 一直要求重新登入

處理方式：
請重新登入 Microsoft 365 帳號。

來源：
FAQ
```

## Knowledge

```text
問題：VPN 錯誤 691

處理方式：
依照知識文件，請先確認帳號密碼是否已更新……

來源：
- vpn-guide.md
```

## Need More Info

```text
為了協助確認 VPN 問題，請補充：

1. 使用的是哪一個 VPN 應用程式？
2. 畫面顯示什麼錯誤訊息或錯誤碼？
```

## 非 IT

```text
天氣問題不在此 IT 助手的服務範圍。
```

---

# 14. Feedback

每次 FAQ 或 Knowledge 回答後，應提供簡單回饋：

```text
這個回答有解決你的問題嗎？
👍 已解決
👎 未解決
```

Feedback 用於評估：

- FAQ 解決率
- RAG 解決率
- 未命中率
- 文件缺口
- 錯誤回答
- 是否需要建立工單

POC 階段 Feedback 的優先級高於建立完整 Issue Lifecycle。

---

# 15. Logging 與 Observability

## 15.1 Correlation ID

每次 Teams Request 建立一個 Correlation ID，並傳遞至：

- Teams Adapter
- Agent Service
- LangGraph State
- Knowledge Service
- Ticket Service
- Repository

不得在 Node 間重新產生。

## 15.2 記錄內容

至少記錄：

- Correlation ID
- Conversation ID
- User ID
- Issue 數量
- Issue Route
- FAQ 是否命中
- Knowledge Backend
- Knowledge 是否命中
- 是否追問
- 是否建立工單
- 執行時間
- 錯誤類型
- LLM 呼叫次數

不得記錄：

- API Key
- Token
- 密碼
- 驗證碼
- 完整敏感對話
- 完整 Stack Trace 至 Teams

---

# 16. 成本與效能控制

```dotenv
MAX_ISSUES_PER_MESSAGE=3
MAX_RETRIEVAL_REWRITES=1
MAX_HISTORY_MESSAGES=10
MAX_LLM_CALLS_PER_REQUEST=5
```

優化順序：

1. 減少不必要的 LLM 呼叫
2. 使用 deterministic formatter
3. 限制多 Issue 數量
4. 限制 Query Rewrite 次數
5. 控制 Context 長度
6. 調整 Cloud Run concurrency
7. 調整 CPU 與 Memory
8. 調整外部服務 timeout
9. 根據壓測結果決定是否需要 runtime 調整

不得在無壓測數據時，以語言重寫作為第一優先效能方案。

---

# 17. 安全需求

系統必須：

- API Key 僅由 Secret Manager 或環境變數提供
- 不記錄 Token、密碼或驗證碼
- 不向使用者回傳完整 Stack Trace
- 不允許查詢其他使用者的工單
- 不將未授權文件送入回答
- 不讓文件中的指令覆蓋系統規則
- 不透露 System Prompt
- 不使用模型一般知識補充公司流程

---

# 18. 測試需求

## 18.1 Issue

- 單一 IT 問題
- 多個 IT 問題
- IT 與非 IT 混合
- 全部非 IT
- 超過三個 Issue
- 資訊不足
- 不得要求密碼或 Token

## 18.2 FAQ

- FAQ 命中
- FAQ 未命中
- Disabled FAQ
- FAQ 不呼叫 LLM
- FAQ 答案不被改寫

## 18.3 Knowledge

- Hybrid RAG 命中
- Hybrid RAG 未命中
- 回答包含來源
- 無來源時不捏造
- 錯誤碼命中
- 文件衝突
- ACL 正確
- 圖片來源正確

## 18.4 Conversation

- Conversation Timeout
- 最近 N 輪
- 不同 User 隔離
- 不同 Conversation 隔離
- 補充資訊後重新抽取 Issue

## 18.5 Ticket

- 未確認不得建立
- 明確確認後建立
- 身分資訊來自 Entra context
- 查詢自己的工單
- 不得查詢他人工單
- Ticket API timeout
- Ticket API error

## 18.6 Security

- 文件 Prompt Injection
- 使用者要求 System Prompt
- 未授權文件查詢
- 使用者要求模型自行補充
- Log 不包含敏感資訊

## 18.7 Retrieval A/B Test

比較：

- HybridKnowledgeService
- GeminiFileSearchKnowledgeService

評估：

- Answer Accuracy
- Recall@K
- Groundedness
- Citation Accuracy
- No-answer Accuracy
- Error-code Accuracy
- ACL Accuracy
- Image Match Accuracy
- P95 Latency
- 單次成本
- 維運複雜度

A/B Test 完成前，Hybrid RAG 維持預設。

---

# 19. POC 驗收標準

以下完成即視為 POC 通過：

1. Teams 可正常與 Agent 對話。
2. Teams Adapter 與 Agent Service 可部署至 Cloud Run。
3. 可取得可信任的使用者識別資訊。
4. 可載入最近對話上下文。
5. 可拆解最多三個 Issue。
6. 可判斷 IT 與非 IT 問題。
7. FAQ 命中時回覆固定答案。
8. 資訊不足時提出最多兩個必要問題。
9. 資訊完整時可執行 Hybrid RAG。
10. 回答只根據知識內容。
11. 回覆包含來源文件。
12. 圖片來源可正常顯示。
13. 無知識時不捏造。
14. 未經確認不建立工單。
15. 使用者確認後可呼叫 Ticket API。
16. 可查詢目前使用者自己的工單。
17. 可保存必要的 Conversation Context。
18. 多 Issue 不互相阻塞。
19. 每次請求具有 Correlation ID。
20. 回答後可收集使用者回饋。
21. 具備安全、錯誤與 Prompt Injection 測試。
22. 現有 Python 架構通過定義的效能測試。

以下不列入 POC 必要驗收：

- Node.js 重寫
- Microsoft 365 Agents SDK JavaScript
- Gemini File Search 正式取代 Hybrid RAG
- 完整 Issue Repository
- 完整 Issue Lifecycle
- 工單催辦
- Production Ticket Service 實作
- FAQ 後台
- 知識庫後台
- Multi-Agent
- Approval
- 完整 CI/CD
- 高可用與災難復原

---

# 20. 交付項目

1. 更新後 Python 原始碼
2. Microsoft 365 Agents SDK Python Teams Adapter
3. LangGraph Agent Workflow
4. Issue Extractor
5. FAQ Repository 與 FAQ Service
6. Hybrid Knowledge Service
7. Gemini File Search Spike Adapter
8. Conversation Repository Interface
9. Ticket Service HTTP Adapter
10. Deterministic Response Builder
11. Feedback 機制
12. Logging 與 Correlation ID
13. 單元測試與整合測試
14. Retrieval A/B Test 報告
15. 效能壓測報告
16. Dockerfile
17. `.env.example`
18. README
19. Cloud Run 部署說明
20. Teams App 設定與測試說明

---

# 21. 開發優先順序

## 第一階段：核心對話能力

- Conversation Context
- Issue Extractor
- IT Filter
- FAQ
- Need More Info
- Hybrid RAG
- Deterministic Response Builder

## 第二階段：工單與回饋

- Ticket Service Adapter
- 建立工單確認流程
- 查詢自己的工單
- Feedback

## 第三階段：品質與比較

- Security Test
- Prompt Injection Test
- Gemini File Search Spike
- Retrieval A/B Test
- 效能壓測

## 第四階段：正式化評估

根據 POC 結果決定：

- 是否採用 Gemini File Search
- 是否導入持久化資料庫
- 是否需要更多工單能力
- 是否需要後台
- 是否需要正式監控
- 是否需要擴充人工作業流程

---

# 22. 架構結論

本專案應以既有可運作架構為基礎，優先完成可驗證的業務價值。

不因未量化的效能假設重寫語言，不因單一雲端產品取代已完成且可控的檢索能力，也不因未來可能需求而在 POC 階段建立完整平台。

POC 的成功標準是：

```text
能理解
能檢索
能追問
能拒答
能開單
能追蹤
能量化成效
```

而不是：

```text
用了多少新框架
建立多少 Repository
串接多少未驗證產品
```
