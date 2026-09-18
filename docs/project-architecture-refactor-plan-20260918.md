# 專案架構審查與重構執行計畫

> 審查日期：2026-09-18  
> Git 基準：`main@313c61a`，並包含審查當下工作目錄內尚未提交的變更  
> 範圍：Teams Adapter、Agent Service、Knowledge Portal、AI Ops Backoffice、React Console、測試與建置邊界  
> 性質：架構審查與漸進式重構計畫；不主張改寫語言、框架或立即拆分 repository

## 1. 結論摘要

目前的主要問題不是單純「檔案太長」，而是多個架構邊界已經失效：

1. **套件依賴形成循環**：`agent_service` 會匯入 `ai_ops_backoffice`，同時 `ai_ops_backoffice` 大量匯入 `agent_service`。核心執行期、治理後台與評估工具因此無法獨立演進。
2. **組裝層吸收商業邏輯**：FastAPI `create_app()`、`register_*_routes()` 不只註冊 route，也建立 repository、解析 storage mode、讀寫 JSON、處理授權、轉換資料與協調流程。
3. **God object 已形成**：`HybridKnowledgeService`、`ReleaseService`、多個 Backoffice service 同時承擔 orchestration、policy、persistence、fallback、稽核與序列化。
4. **前端處於雙軌維護**：舊版 static UI 約 22,995 行，React Console 約 9,510 行；既有 route ledger 也顯示多數功能仍在 migration 中。
5. **契約由人工複製維護**：Adapter 與 Agent Service 各自定義相似 request/response DTO，React 又維護第三套 TypeScript types，存在靜默漂移風險。
6. **現有 CI 能抓語法與行為回歸，抓不到架構退化**：沒有依賴方向、檔案成長、函式複雜度、OpenAPI 相容性或已建置 bundle 一致性的檢查。

建議的總方向是：**保留現有部署拓樸，先把 `agent_service/` 整理成有明確依賴方向的 modular monolith，再逐步拆解巨型檔案。** 不應直接拆成更多微服務，也不應以一次性大改寫處理。

## 2. 盤點基準

### 2.1 Production source 規模

以下統計排除測試、`node_modules`、generated static bundle、data、outputs 與 artifacts：

| 區域 | 檔案數 | 約略 LOC | >300 行 | >500 行 | >800 行 |
|---|---:|---:|---:|---:|---:|
| Teams Adapter (`src/teams_agent`) | 21 | 6,782 | 11 | 5 | 2 |
| Agent Runtime (`agent_service/src/agent_service`) | 110 | 26,797 | 26 | 12 | 2 |
| Knowledge Portal | 38 | 11,402 | 16 | 6 | 2 |
| AI Ops Backoffice | 153 | 45,492 | 56 | 29 | 13 |
| React Console | 43 | 9,553 | 9 | 4 | 1 |
| **合計** | **365** | **100,026** | **118** | **56** | **20** |

單一檔案超過 500 行已有 56 個，表示這不是只修兩三個熱點即可結束的問題；需要先建立依賴規則與成長煞車，再分批重構。

### 2.2 最大風險熱點

| 檔案 | 行數 | 觀察到的主要責任 |
|---|---:|---|
| `agent_service/src/agent_service/knowledge.py` | 2,838 | query planning、retrieval、ranking、scenario policy、LLM relevance、generation、grounding、citation、trace、fallback |
| `agent_service/src/ai_ops_backoffice/routers/workbench_router.py` | 1,295 | request model、JSON persistence、dashboard aggregation、conversation、FAQ、document、ticket、simulation routes |
| `agent_service/src/knowledge_portal/services/release_service.py` | 1,063 | lock、idempotency、release build、gate、activation、reload、rollback、audit、pointer mutation |
| `agent_service/src/ai_ops_backoffice/governance_domain/eval_runtime.py` | 1,019 | eval runtime、model wiring、sandbox、agent workflow construction |
| `agent_service/src/ai_ops_backoffice/api.py` | 989 | dependency construction、repository selection、worker wiring、error handlers、static UI、routes |
| `agent_service/src/knowledge_portal/api.py` | 985 | app factory、auth、lifespan、error mapping，以及幾乎全部 Portal endpoints |
| `agent_service/src/agent_service/extractor.py` | 979 | prompt、intent heuristics、model invocation、fallback、issue normalization |
| `agent_service/src/ai_ops_backoffice/evaluation_domain/repository.py` | 976 | 多種 repository 行為與序列化 |
| `agent_service/src/ai_ops_backoffice/evaluation_domain/runner.py` | 974 | run orchestration、single/multi-turn execution、comparison、checkpoint、persistence |
| `console_frontend/src/features/triage/components/ConversationStream.tsx` | 954 | markdown normalization、policy data、citation lookup、API fetch、drawer、message rendering |
| `console_frontend/src/shared/api/workbenchStore.ts` | 799 | 全站 domain state、mock fallback、API client、mutation、loading 與 subscription |
| `src/teams_agent/source_routes.py` | 917 | source serving、viewer auth、SSO callback、session、HTML response 與 redirects |

部分單一函式本身已大於合理的檔案大小，例如：

- `register_workbench_routes()`：1,184 行，約 217 個分支節點。
- `knowledge_portal.create_app()`：926 行。
- `register_analytics_routes()`：780 行。
- `ai_ops_backoffice.create_app()`：714 行。
- `create_source_router()`：703 行。
- `HybridKnowledgeService._generate()`：539 行。

這代表只把 class 搬到新檔案不會改善可維護性；必須先拆責任與資料流。

## 3. 架構問題與重構方向

### P0：解除 domain package 的雙向依賴

#### 證據

靜態 import 盤點顯示：

- `ai_ops_backoffice -> agent_service`：200 個 imports，分布於 88 個檔案。
- `agent_service -> ai_ops_backoffice`：13 個 imports，分布於 6 個檔案。
- `knowledge_portal -> agent_service`：35 個 imports，分布於 16 個檔案。
- `knowledge_portal -> ai_ops_backoffice`：5 個 imports，分布於 3 個檔案。

特別是 `agent_service/prompt_runtime.py`、`release_gate.py`、`faq.py` 反向依賴 Backoffice domain；Backoffice 又直接依賴 Agent 的 operations、extractor、retrieval、graph 與 usage。這已形成真正的 package cycle，而非單純共用 utility。

#### 目標

建立單向依賴：

```text
agent_protocol        platform_kernel
      ^                 ^    ^    ^
      |                 |    |    |
teams_adapter    agent_runtime  knowledge_portal  ai_ops_backoffice
                       ^              ^                 ^
                       +------- composition root -------+
```

- `agent_protocol`：只放跨 process 的 request/response schema、enum 與 serialization contract，不放商業邏輯或 database code。
- `platform_kernel`：只放真正跨 domain 且穩定的型別／ports，例如 `ActorContext`、audit contract、masking contract、target manifest identity。不得變成新的雜物區。
- 各 domain 只依賴 protocol/kernel，不互相匯入 repository 或 service implementation。
- 需要呼叫另一個 domain 時，在 consumer 端定義 port，由最外層 composition root 提供 adapter。

#### 具體替換

- `agent_service.prompt_runtime -> ai_ops_backoffice.governance_domain`：改成 `GovernanceProvider` port；Backoffice implementation 在 composition root 注入。
- `agent_service.release_gate -> ai_ops_backoffice.evaluation_domain`：把 gate decision contract 移到 kernel，Agent/Portal 只呼叫 `ReleaseGateChecker`。
- `knowledge_portal.source_record_publish -> ai_ops_backoffice.services.source_repository`：改成 `SourceCatalogWriter` port，不直接操作 Backoffice repository。
- Backoffice 若要執行真實 Agent evaluation，依賴 `AgentEvaluationRuntime` port；實作可以包住 Agent runtime，但 domain model 不得匯入 Agent 私有 class。

#### 驗收條件

- `agent_service`, `knowledge_portal`, `ai_ops_backoffice` 之間沒有雙向 import。
- 加入 architecture test，明確列出允許的 package edges；違規時 CI 失敗。
- 所有 integration wiring 集中在 composition root，不使用 domain 內的 late import 迴避循環。

### P0：讓組裝層只負責組裝

#### 問題

`ai_ops_backoffice/api.py` 目前在 `create_app()` 內選擇 File/Firestore repositories、建立各 domain services、組 evaluator、workers、bridge、error handlers 與 UI routes。`knowledge_portal/api.py` 和多個 `register_*_routes()` 也有同樣情況。

`workbench_router.py` 更直接含 `_load_json_safe()`、`_save_json_safe()` 與多個跨 domain 聚合流程。HTTP 邊界、application use case 與 persistence 因而無法分開測試。

#### 目標結構

```text
ai_ops_backoffice/
  bootstrap/
    container.py          # 建立 application dependencies
    repositories.py       # FILE/FIRESTORE adapter selection
    workers.py            # background runtime wiring
  http/
    app.py                # FastAPI metadata, middleware, router inclusion
    dependencies.py       # actor/correlation/idempotency dependencies
    error_handlers.py
    routers/
      workbench_overview.py
      workbench_conversations.py
      workbench_faqs.py
      workbench_documents.py
      workbench_tickets.py
      workbench_simulation.py
  application/
    workbench/
      overview.py
      conversations.py
      documents.py
      tickets.py
```

Router 應只做四件事：解析 request、授權 dependency、呼叫 use case、映射 response/error。不得直接讀寫 JSON、取得另一個 service 的 private attribute，或組複雜 dashboard 資料。

現有 `analytics_router.py`、`sources_router.py`、`quality_routes.py` 直接存取 `query_service._metrics`、`query_service._source_trace` 等 private members，應由明確的 public query interface 取代。

#### 驗收條件

- `create_app()` 控制在約 100 行內。
- 單一 router module 控制在 250 行內；單一 route handler 原則上不超過 40 行。
- repository mode selection 只存在 bootstrap/provider 層。
- router tests 不需建立真實 filesystem/Firestore，即可用 fake use case 驗證 HTTP contract。

### P0：拆解 Hybrid Knowledge pipeline，但保留 facade

#### 問題

`HybridKnowledgeService` 約 1,957 行 class body，`_generate()` 單一方法 539 行。它同時包含：

- query facet planning 與 rewrite；
- retrieval cache 與 parallel search；
- ACL/filtering、跨情境隔離與 hard-coded product heuristics；
- relevance decision；
- prompt construction 與 LLM invocation；
- citation mapping、claim repair、security policy overlay；
- answerability、fallback、trace 與 timing。

這使任何 retrieval 調整都可能影響生成、安全、citation 或 evaluation trace。

#### 目標結構

保留 `KnowledgeService.search()` 對外介面與 `HybridKnowledgeService` facade，內部改為 pipeline collaborators：

```text
agent_service/knowledge_pipeline/
  models.py               # RetrievalState 與 stage result
  planner.py              # facet query / rewrite policy
  retriever.py            # index access、cache、timings
  candidate_policy.py     # ACL、scenario isolation、document/chunk selection
  relevance.py            # deterministic + model relevance decision
  generator.py            # structured answer generation
  grounding.py            # claim/citation validation and repair
  policy_overlay.py       # security policy advisory
  trace.py                # RetrievalTrace assembly
  service.py              # facade orchestration
```

每個 stage 接受 immutable input、回傳明確 result，不直接修改其他 stage 的 internal state。Hard-coded scenario/product rules應轉成具名 policy table 並有獨立測試，不應散落在 retrieval 與 generation 邏輯中。

#### 遷移順序

1. 先以現有 golden/evaluation tests 建立 characterization baseline。
2. 先抽純函式：citation、grounding、scenario policy、query planning。
3. 再抽 I/O stage：retriever、LLM relevance、generator。
4. 最後將原 class 縮成 orchestration facade；外部 import 與設定保持相容。

#### 驗收條件

- `service.py` facade 小於 300 行，各 stage 小於 500 行。
- 每個 stage 可用純 fake dependency 單元測試。
- golden baseline、citation、ACL、temporal claim、policy advisory 與 LLM budget 行為不變。
- 重構 PR 不同時調整 ranking/prompt 品質；演算法變更另案處理。

### P1：把 ReleaseService 改成明確的 release workflow

#### 問題

`ReleaseService` 同時管理 application use case 與 deployment transaction。`_activate_release()` 內含 build、authorization、release gate、SourceRecord persistence、舊 release deactivation、active pointer、Agent reload、失敗補償與 audit。這是一個跨儲存體、跨服務的 saga，但目前以單一方法和例外分支隱式實作。

#### 目標結構

```text
knowledge_portal/release/
  commands.py             # Publish/Rollback/Promote commands
  service.py              # public application facade
  coordinator.py          # explicit state transition orchestration
  builder.py              # manifest/artifact build
  gate.py                 # ReleaseGateChecker port usage
  activation_store.py     # active pointer + release state port
  agent_reload.py         # reload client port
  source_catalog.py       # source persistence port
  transitions.py          # allowed state machine
```

建議明確定義 `READY -> DEPLOYING -> ACTIVE`、`GATE_BLOCKED`、`RELOAD_FAILED`、`ROLLED_BACK` 等轉移，並把 compensation 寫成可測的 transition，而不是分散在 `try/except`。現階段不必導入通用 workflow engine；具名 coordinator 已足夠。

#### 驗收條件

- 每個外部 side effect 都有 port 與 contract test。
- 任一步驟失敗後，release status、active pointer、舊 release 與 audit 的結果可預測。
- publish、rollback、promote 共用同一套 transition rules，不複製流程。

### P1：整理 Backoffice domain 與 repository 邊界

#### 問題

- 多個 domain service 超過 700–900 行。
- `quality_domain`、`example_domain`、`prompt_domain`、`budget_domain` 等使用 `import *`，隱藏真正依賴。
- File/Firestore implementation、serialization、authorization、audit 與 business rule 常落在同一檔。
- `BackofficeQueryService` 被當成 service locator，router 再存取其 private members。
- governance 依賴多個 mixin，雖然檔案被拆開，state 與 method ownership 仍集中在巨型 service 上；這是「物理拆檔」，不是責任拆分。

#### 重構原則

- 每個 bounded context 採一致的 `models / ports / application / adapters` 結構，但不要建立過度通用的 CRUD base class。
- repository protocol 只描述 domain 需要的操作；File 與 Firestore 放在 `adapters/`。
- authorization/audit 放在 application command handler 邊界，不複製到每個 repository。
- 移除 wildcard imports，所有跨 module dependency 明列。
- 拆除 service locator；route 直接注入所需的窄介面。
- governance 依 use case 分成 prompt、model、flag、policy、role、search/audit services，共用的 hashing/masking 保持純函式。

### P1：收斂設定與啟動流程

四個主要 settings class 合計約 290 個欄位；`BackofficeSettings.from_env()` 單一方法 359 行，還接受多組別名與 fallback。這讓服務真正需要哪些設定、哪些只屬於特定 worker/domain 很難判斷。

建議：

- 拆成 `HttpSettings`、`AuthSettings`、`StorageSettings`、`KnowledgeBridgeSettings`、`EvaluationSettings`、`WorkerSettings` 等 immutable section。
- env alias/legacy fallback 集中在 loader，不散落在 domain。
- 啟動時產生 redacted effective-config summary，明確標示來源與 deprecated keys。
- 對 legacy env keys 設定移除期限；不要永久累加 fallback。
- web process 與 worker process 只載入自己需要的 section。

### P1：前端以 feature boundary 完成遷移

#### 問題

- 舊 static UI 約 22,995 行仍由 FastAPI 掛載；React Console 約 9,510 行，route ledger 顯示 migration 尚未完成。
- `workbenchStore.ts` 管理全部 dashboard、conversation、ticket、FAQ、document、gap state，也包含 mock fallback、API mutation 與 subscription。
- `ConversationStream.tsx` 同時處理 markdown parser、policy fixture、citation resolution、remote fetch 與 UI。
- React package 沒有 unit test script；目前 CI 只做 TypeScript build。`agent_service/tests/frontend` 驗證的是 legacy/static navigation，不能保護 React components 與 store。
- production bundle 被提交至 Python static directory；若 image build 未從 lockfile 重建，TypeScript source 與實際部署 bundle 可能不同步。

#### 目標結構

```text
console_frontend/src/
  features/
    conversations/
      api.ts
      models.ts
      store.ts
      markdown.ts
      citationResolver.ts
      components/
    knowledge/
    tickets/
    dashboard/
  shared/
    api/client.ts
    auth/
    ui/
```

- Store 依 feature 拆分；全域只保留 session、auth 與極少數 navigation state。
- `ConversationStream` 拆成 `MessageList`、`MessageBubble`、`CitationDrawer`、`PolicyAdvisory`；markdown normalization 與 citation resolution 變成純函式。
- Security policy 顯示資料由後端 contract 或共用 generated schema 提供，不在 component 中硬編日期與完整政策文字。
- 新增 React unit/component tests，至少覆蓋 markdown、citation、store mutation、loading/error state 與 route guard。
- Docker/CI 由 `console_frontend/package-lock.json` 重建 bundle。若 bundle 必須提交，CI 必須重建並檢查 `git diff --exit-code`；較佳做法是在 multi-stage image build 產出，不將 hash bundle 當 source 維護。
- 依 `docs/ai-ops-route-ledger.md` 的 W3–W5 順序逐頁遷移；每完成一頁就移除對應 legacy implementation 與測試，不長期雙寫。

### P1：建立單一 wire contract 來源

`src/teams_agent/contracts.py` 與 `agent_service/contracts.py` 都定義 `AgentRequest`、`AgentResponse`、`Citation`、`AgentImage`、`IssueResult` 等型別；前者使用 dataclass 與手動 payload parsing，後者使用 Pydantic，React 又有獨立 TypeScript interface。

建議採兩層做法：

1. Python 跨 process 契約移至小型 `agent_protocol` package，Adapter 與 Agent Service 共用；domain-only models 留在 Agent 內。
2. HTTP API 以 OpenAPI/JSON Schema 為單一來源，產生 TypeScript types；CI 檢查 generated output 是否最新。

如果短期不能新增 package，至少加入 schema compatibility tests：Agent 產生的 response 必須能被 Adapter parser 接受，並對 optional/required fields、enum 與 alias 做 snapshot。

### P2：調整測試拓樸，而不是只拆 test file

測試檔也有明顯集中：`test_ai_ops_backoffice.py` 2,616 行、`test_spec_gap_p0_p1_followups.py` 2,279 行、`test_workflow.py` 2,069 行。大型測試本身不是 production 風險，但通常代表 fixture 與行為邊界不清楚。

建議建立以下層次：

- `unit/domain`：純 policy、state transition、mapping。
- `unit/application`：use case + fake ports。
- `contract/adapters`：File/Firestore、HTTP clients、OpenAPI/schema compatibility。
- `integration/http`：FastAPI router、auth、error mapping。
- `integration/workflows`：RAG、release、evaluation orchestration。
- `acceptance`：少量 end-to-end business scenarios。

共用 fixture 只提供穩定 builder/fake，不建立可以任意 mutate 全系統 state 的 mega fixture。將 spec 編號保留在 test name/marker，不以單一「spec gap」檔案持續累積所有回歸。

## 4. 建議的目標邊界

### 4.1 Repository 與 deployment 不先拆

保留目前服務：

- Teams Adapter
- Agent Runtime
- Knowledge Portal
- AI Ops Backoffice / workers
- React Console build

這次重構先處理 source dependency 與 application boundary。只有在獨立 scaling、security boundary、release cadence 或 failure isolation 有實際證據時，才評估拆 repository 或新增服務。

### 4.2 依賴規則

1. Domain model 不依賴 FastAPI、Firestore、filesystem、HTTP client 或其他 domain implementation。
2. Application service 可依賴 domain model 與 ports。
3. Adapters 實作 ports，可依賴外部 SDK。
4. HTTP/worker handlers 只呼叫 application service。
5. Composition root 是唯一知道 concrete implementation 的位置。
6. 跨 process 使用 wire DTO；wire DTO 不直接充當內部 domain entity。
7. 禁止跨 module 存取 `_private_member`。

## 5. 漸進式執行路線

### Wave 0：停止繼續惡化

1. 新增 `scripts/check_architecture.py` 或等價工具：
   - 阻擋新的跨 domain 反向依賴。
   - 禁止新增 >500 行 production source file。
   - 現有超標檔案採 ratchet：可縮小、不可增長；允許有期限的 waiver。
   - 對單一函式 >80 行提出失敗或明確 waiver。
2. 產生 endpoint/OpenAPI snapshot，記錄所有 public routes、status codes 與主要 schemas。
3. 對 Knowledge、Release、Workbench 加 characterization tests。
4. 記錄 legacy UI 到 React route 的一對一 migration ledger 與 owner。

**出口條件**：新 PR 不再製造新的巨型檔案或 dependency cycle；後續拆檔有行為基準。

### Wave 1：切開 shared kernel 與 composition roots

1. 建立 `agent_protocol` 與最小 `platform_kernel`。
2. 把 Actor/audit/masking/release-gate/source identity 等 contract 從 Agent implementation 中移出。
3. 將 Agent 對 Backoffice 的 governance/gate dependency 改成 ports。
4. 將 Backoffice 與 Portal 的 concrete repository 建立移至 bootstrap providers。
5. 縮小三個 FastAPI `create_app()`。

**出口條件**：三個 domain package 依賴方向可由 CI 驗證；app factory 只做組裝。

### Wave 2：拆 HTTP 與 Workbench application layer

1. 依 overview、conversation、FAQ、document、ticket、simulation 拆 `workbench_router.py`。
2. 將 JSON/file 操作移入 repository adapter。
3. 把 aggregation 與 mutation 移到 application use cases。
4. 拆 `analytics_router.py`、`governance_routes.py`、`source_routes.py`；移除 private member access。
5. 每搬一組 routes 就用 OpenAPI snapshot 與 integration tests 驗證相容。

**出口條件**：沒有超過 250 行的 router，handler 不含 persistence/business branching。

### Wave 3：拆 Knowledge 與 Release 核心流程

1. 先抽 pure policies，再抽 I/O stages。
2. 保留原 facade 與 method signatures，逐 stage 轉接。
3. 將 release activation 明文化為 state transitions 與 compensations。
4. golden/evaluation/release failure tests 每個 PR 都執行，不同時變更 prompt 或 ranking。

**出口條件**：`knowledge.py` 與 `release_service.py` 不再是主要 implementation；facade 僅負責 orchestration。

### Wave 4：完成 React feature 化與 legacy UI 退場

1. 拆 `workbenchStore` 與 `ConversationStream`。
2. 建立 React unit/component test pipeline。
3. 依 route ledger 遷移 W3–W5。
4. 每完成一個 route family，刪除相對應 legacy JS/CSS、redirect 特例與舊測試。
5. 將 frontend build 納入 image build 或加入 bundle freshness check。

**出口條件**：單一路由只有一套 active implementation；舊 UI 不再被正常產品路徑載入。

### Wave 5：收尾與治理

1. 依新 test topology 拆大型測試檔。
2. 移除 deprecated env aliases、dead adapters、過渡 facade 與 waiver。
3. 更新 README 的「two-service split」描述，使其與實際四個 runtime entrypoints 和 BFF/worker 拓樸一致。
4. 將 architecture checks、schema checks、frontend tests 納入 required CI。

## 6. 建議 PR 切法

每個 PR 應保持可部署、可回滾，避免同時搬檔與改行為：

| PR | 內容 | 主要驗證 |
|---:|---|---|
| 1 | Architecture ratchet、import rules、OpenAPI snapshot | CI 自身測試、現有 tests |
| 2 | `agent_protocol` 與 Adapter/Agent schema compatibility | Adapter + Agent contract tests |
| 3 | `platform_kernel` contracts；移除第一批反向 imports | architecture test |
| 4 | Backoffice bootstrap/container 與 error handlers | app startup + route snapshot |
| 5 | Workbench overview/conversation routes + use cases | HTTP integration tests |
| 6 | Workbench FAQ/document/ticket/simulation routes | HTTP + repository contract tests |
| 7 | Portal app/router 拆分 | Portal integration tests |
| 8 | Knowledge pure policies/planner/grounding extraction | golden + retrieval tests |
| 9 | Knowledge retriever/generator extraction | golden + budget/deadline tests |
| 10 | Release state machine/coordinator | publish/rollback/failure matrix |
| 11 | React feature stores + tests | typecheck + component tests |
| 12+ | 依 route ledger 逐 family 遷移 legacy UI | route E2E + bundle check |

## 7. 量化護欄

這些數值應作為 ratchet，不要第一天就要求所有 legacy code 一次合格：

| 指標 | 新程式碼目標 | 舊程式碼策略 |
|---|---:|---|
| Production source file | <= 500 行 | 超標檔案不得增長，逐 Wave 降低 |
| Router module | <= 250 行 | 依 route family 拆分 |
| Route handler | <= 40 行 | 超標先抽 use case/mappers |
| 一般 function/method | <= 80 行 | 需要例外時留下具期限 waiver |
| Application service | <= 400 行 | 依 use case 拆，不以 mixin 假拆分 |
| 跨 domain private access | 0 | 先加 public port，再移除 |
| Domain dependency cycles | 0 | Wave 1 完成後設 required check |
| 手寫重複 wire DTO | 0 | 以 protocol/schema generation 取代 |

行數不是設計品質的唯一指標，但在本專案可作為有效的早期警報。真正驗收仍是責任單一、依賴單向、行為可獨立測試。

## 8. 風險與避免方式

| 風險 | 避免方式 |
|---|---|
| 搬檔時偷偷改變 RAG 品質 | 結構 PR 與演算法 PR 分開；固定 golden baseline |
| 大量 import move 造成循環或啟動失敗 | 先建立 ports/kernel，再移 consumer；每步做 app startup test |
| Release 重構破壞補償流程 | 先把現有成功/失敗狀態矩陣寫成 characterization tests |
| React 與 legacy UI 長期雙寫 | route ledger 每頁指定唯一 owner 與 removal PR |
| Shared kernel 變成新 god package | 只允許穩定 contract/pure policy；禁止 service locator 與 infrastructure |
| 為了共用而建立過度抽象 base class | 優先窄 port 與 composition；至少兩個真實 consumer 才抽共用實作 |
| 一次 PR 變更太大，無法 review | 以 endpoint family 或 pipeline stage 為單位，保持 contract 不變 |

## 9. 明確不建議的做法

- 不建議因檔案過大直接改寫成另一種語言或 framework。
- 不建議先拆更多微服務；目前 source boundary 尚未穩定，拆服務只會把循環依賴變成網路耦合。
- 不建議只依 class/mixin 把同一份 mutable state 分散到更多檔案。
- 不建議建立一個通吃所有 domain 的 generic repository/service base class。
- 不建議一次搬完整個 `agent_service/src`；應維持 facade，逐 stage/use case 替換。
- 不建議在重構 PR 同時調整 prompts、ranking threshold、UI flow 或 API response shape。
- 不建議只靠行數 KPI；若拆完仍跨 module 讀 private state，架構問題仍未解決。

## 10. 完成定義

此重構計畫完成時，應同時滿足：

1. Domain package dependency graph 無循環，且 CI 可驗證。
2. FastAPI app factory 與 routers 不包含 repository selection 或主要商業流程。
3. Knowledge 與 Release 流程由具名 stage/use case 組成，可單獨測試與替換。
4. Adapter、Agent 與 React 的 wire schemas 有單一來源或自動 compatibility check。
5. React Console 成為唯一 active UI；legacy static route family 已退場。
6. Production source 不再新增 >500 行檔案，既有超標檔案完成 ratchet 清零或有明確例外理由。
7. OpenAPI、golden evaluation、release failure matrix、frontend component tests 與 architecture checks 都是 required CI。
8. README、route ledger、部署建置方式與真實 runtime topology 一致。

## 11. 建議立即開始的第一步

第一個 implementation milestone 不應直接拆 `knowledge.py`。應先完成 Wave 0 與 Wave 1 的最小骨架：

1. 加入 architecture ratchet 與 API snapshot。
2. 建立 `ReleaseGateChecker`、`GovernanceProvider`、`SourceCatalogWriter` 三個 ports。
3. 解除 `agent_service -> ai_ops_backoffice` 的反向 imports。
4. 把 Backoffice `create_app()` 的 repository/service construction 搬到 bootstrap container。

這會先切斷最危險的依賴，再讓後續每一個巨型檔案可以在穩定邊界內逐步縮小。
