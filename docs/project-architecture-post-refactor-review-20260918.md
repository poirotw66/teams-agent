# 重構後專案架構複審與持續優化計畫

> 複審日期：2026-09-18  
> Git 基準：`main@641aaa7`，並納入複審期間工作目錄內尚未提交的變更  
> 原始計畫：`docs/project-architecture-refactor-plan-20260918.md`  
> 範圍：Teams Adapter、Agent Runtime、Knowledge Portal、AI Ops Backoffice、React Console、architecture governance 與 CI  
> 結論：**重構方向正確且已有顯著成果，但原計畫的完成定義尚未全部達成；目前應視為「主要熱點拆解完成、邊界收斂進行中」，不宜標示 Wave 0–5 全部完成。**

## 1. 執行摘要

這次重構不是無效的「把一個大檔切成很多小檔」。幾個最危險的熱點確實已被改善：

- `knowledge.py` 從 2,838 行縮成 89 行 facade，主要行為移至 `knowledge_hybrid.py` 與 `knowledge_pipeline/`。
- `workbench_router.py` 從 1,295 行縮成 10 行 compatibility shim，routes 依功能拆分。
- `ReleaseService` 從 1,063 行縮成 288 行，release transitions、activation、publish、rollback 已有具名模組。
- Backoffice `api.py` 從 989 行降到 60 行；Portal `api.py` 從 985 行降到 57 行。
- `ConversationStream.tsx` 從 954 行降到 114 行。
- React route ledger 已標示 30/30 routes 由 `/console-v2` 接手，production image 也改由 multi-stage build 從 TypeScript source 產生 bundle。
- architecture ratchet、OpenAPI snapshot、wire compatibility、golden tests、release matrix 與 frontend job 已被加入 CI。

然而，複審也發現四個必須先處理的事實：

1. **目前 CI 不是綠的**：architecture ratchet 與 OpenAPI snapshot 都失敗。
2. **新的 composition cycle 未被 architecture check 偵測**：`agent_service -> composition -> agent_service`，以及 Backoffice wiring 與 composition 之間也存在反向關係。
3. **domain 邊界仍高度耦合**：Backoffice 有 224 個 imports 指向 Agent、Portal 有 37 個 imports 指向 Agent；目前只是消除了部分反向 import，尚未做到各 domain 只依賴 ports/kernel。
4. **部分「Done」是形式完成**：Workbench persistence 仍在 router package、wire checker 不檢查型別與 TypeScript、frontend tests 只有兩個 source-regex smoke tests、legacy UI 仍保留約 23,000 行。

因此，下一階段不應繼續大規模拆檔，而應集中處理：

1. 恢復 required CI 全綠。
2. 修正 composition root 的依賴方向與 architecture checker 漏洞。
3. 把共用 operations/knowledge 能力移出 `agent_service` 私有命名空間。
4. 完成 HTTP/application/persistence 邊界。
5. 把 RAG backend 與 frontend 建成立即可獨立建置、測試、部署的 workspace，並以 OpenAPI generated client 作為唯一整合邊界。
6. 將 schema、frontend test 與 legacy removal 從「有機制」提升為「真正可防回歸」。

Repository 策略採用 **repo-ready modular monorepo**：RAG 系統與前端在責任、contract、build、test、artifact、deploy 上立即分離，但目前保留在同一個 repository。待 API 與團隊 ownership 穩定且符合拆分門檻後，才進行不改產品行為的 repository 搬遷。

## 2. 複審方法與限制

本次複審採用：

- 原始重構計畫的完成定義逐項驗收。
- Python AST 統計檔案、函式與 package imports。
- 檢查 FastAPI app factories、bootstrap、routers、ports 與 adapters。
- 檢查 Knowledge pipeline、Release workflow 與 React feature split。
- 執行 architecture、OpenAPI、wire-contract、frontend build/test 與關鍵 characterization tests。
- 檢查 CI、Docker build、route ledger、architecture baselines 與 waivers。

限制：

- 本次未執行完整 58,000+ 行 Python test suite；已執行架構與主要重構邊界的針對性測試。
- 行數與 import 數量是風險訊號，不單獨等同設計品質。
- 工作目錄在複審期間存在尚未提交的程式碼與 governance data 變更；本文件只記錄狀態，不修改或回復它們。

## 3. 重構前後量化比較

### 3.1 Production source

統計排除 tests、`node_modules`、static generated bundle、data、outputs、artifacts 與 `__pycache__`。

| 指標 | 重構前 | 現況 | 變化 | 判讀 |
|---|---:|---:|---:|---|
| Production source files | 365 | 553 | +188 | 拆分與新功能造成，單獨不視為退化 |
| Production LOC | 100,026 | 108,375 | +8,349 | 功能成長與 compatibility layers 使總量增加 |
| >300 行檔案 | 118 | 117 | -1 | 中型模組密度幾乎未下降 |
| >500 行檔案 | 56 | 47 | -9 | 有改善，但仍有大量 residuals |
| >800 行檔案 | 20 | 13 | -7 | 高風險巨型檔案明顯下降 |
| >80 行 Python functions | 未建立可比基準 | 175 | — | 仍是主要維護風險 |
| >150 行 Python functions | 未建立可比基準 | 53 | — | 多數集中在 evaluation、governance、settings、workflow |
| >250 行 Python functions | 未建立可比基準 | 13 | — | 尚未達成原 80 行目標 |
| >250 行 router modules | 原先多個巨型 registrar | 3 | — | HTTP 拆分成效良好，但未清零 |

總 LOC 上升並不否定這次重構。真正的改善在於極端熱點下降、app factory 變薄、路由與流程有明確名稱。問題在於中型複雜度仍大量存在，且部分切分仍共享原本的私有 state。

### 3.2 主要熱點前後

| 原熱點 | 重構前 | 現況 | 判定 |
|---|---:|---|---|
| `agent_service/knowledge.py` | 2,838 | facade 89；`knowledge_hybrid.py` 438；pipeline 分散於 20+ modules | **顯著改善，仍需降低 callback/private-host 耦合** |
| `workbench_router.py` | 1,295 | shim 10；功能 routes 已拆 | **檔案完成拆分，但 persistence 仍留在 HTTP package** |
| `ReleaseService` | 1,063 | facade 288；release package 2,000+ LOC | **流程具名化成功，ports 尚未完全落地** |
| Backoffice `api.py` | 989 | 60 | **達標** |
| Portal `api.py` | 985 | 57 | **達標** |
| `ConversationStream.tsx` | 954 | 114 | **達標** |
| `workbenchStore.ts` | 799 | compatibility export 5；implementation 429 | **改善，但仍是全域 mega-store** |
| `source_routes.py` | 917 | 917 | **未處理** |
| `eval_runtime.py` | 1,019 | 1,019 | **未處理** |
| `extractor.py` | 約 979 | 約 979 | **未處理** |

### 3.3 現況最大 production 檔案

| 檔案 | 約略行數 | 下一步 |
|---|---:|---|
| `ai_ops_backoffice/governance_domain/eval_runtime.py` | 1,019 | 把 Agent runtime adapter 與 sandbox construction 分離 |
| `agent_service/extractor.py` | 979 | 拆 deterministic intent policy、model adapter、normalizer |
| `evaluation_domain/repository.py` | 976 | 分開 domain port、serialization、File/Firestore adapters |
| `evaluation_domain/runner.py` | 974 | 拆 single-turn、multi-turn、comparison、checkpoint |
| `teams_agent/source_routes.py` | 917 | 拆 source serving、viewer auth、SSO callback、session routes |
| `quality_domain/service.py` | 903 | 依 use case 拆 application services |
| `evaluation_domain/gate_repository.py` | 885 | 分離 gate policy、decision、schedule persistence |
| `teams_agent/source_links.py` | 867 | 分離 resolver、URL signer、source mapping |
| `faq_domain/service.py` | 866 | 依 draft/review/activate/test use cases 拆分 |
| `governance_routes.py` | 845 | 仍有 630 行 registrar；依 governance resource 拆 routers |

## 4. 原完成定義逐項驗收

| 原完成定義 | 狀態 | 複審結論 |
|---|---|---|
| 1. Domain dependency graph 無循環且 CI 可驗證 | **未達成** | 原先 Agent→Backoffice cycle 已移除，但新增 Agent→Composition→Agent cycle；checker 未禁止所有 domain→composition edges |
| 2. App factory/router 不含 repository selection 或主要商業流程 | **部分達成** | 三個 app factory 已達標；Workbench routes 仍直接讀寫 JSON，source routes 仍讀 private state |
| 3. Knowledge/Release 由具名 stage/use case 組成 | **大致達成** | 模組與 tests 已建立；但 facade/host/callback 與 direct Agent imports 顯示 ports 尚未完全收口 |
| 4. Wire schema 有單一來源或自動 compatibility check | **部分達成** | 有 checker，但只比 Python 欄位名稱；不檢查型別、requiredness、enum、alias、nested schema 或 TypeScript |
| 5. React 是唯一 active UI，legacy 已退場 | **部分達成** | 預設產品路徑已是 React；legacy 約 23,000 行仍可由 kill switch 啟用，尚未刪除 |
| 6. 不再新增 >500 行檔案，residuals 完成 ratchet/例外治理 | **未達成** | ratchet 存在但目前失敗；47 個 >500 行檔案、175 個 >80 行函式；waiver 類別過於寬鬆 |
| 7. Architecture/schema/frontend/golden/release checks 為 required CI | **形式達成、實際紅燈** | jobs 已加入，但 architecture 與 OpenAPI 當前失敗；frontend test 只做 source regex |
| 8. README、route ledger、build 與 runtime topology 一致 | **部分達成** | runtime 表與 route ledger 已更新；但 README 宣稱「domain 不反向 import 且 CI enforce」與實際不符 |

## 5. 已完成且應保留的設計

### 5.1 薄 app factory

三個主要 app factories 已縮至約 51–60 行。這是正確方向：

- Backoffice 使用 `bootstrap.container`、`error_handlers`、`register_routes`。
- Portal 使用 `bootstrap.container` 與分組 routers。
- Agent route registration 本身維持簡單。

後續修正 composition cycle 時應保留這個特性，不要把 wiring 再塞回 `api.py`。

### 5.2 Knowledge pipeline 拆分

目前已有 planner、retrieval、relevance、generation、grounding、citation、trace 等具名模組，並新增文件選擇與 generator policy tests。這已讓純 policy 能獨立測試，也是本次重構最有價值的成果之一。

下一步應是收斂介面，而不是再次重新命名或搬檔。

### 5.3 Release state transitions

Release 已有 `transitions.py`、`coordinator.py`、`activation.py`、publish/rollback/promote modules 與 failure matrix tests。原本隱藏在單一方法內的 compensation 分支已較可見。

應保留 explicit state transition，不引入通用 workflow framework。

### 5.4 React route ownership與 production build

- route ledger 已列出 30/30 React-owned routes。
- `/` 預設 redirect 到 `/console-v2/dashboard`。
- `Dockerfile.backoffice` 已使用 `npm ci` + `npm run build` 的 multi-stage build。

這三項解決了「source 與 production bundle 不一致」的主要風險。後續應補 bundle freshness 或直接停止提交 hash bundle，而不是回到人工 copy。

## 6. 目前最重要的架構問題

### P0-1：Required CI 當前失敗

#### Architecture ratchet

實際執行結果：

```text
[FILE_GREW] src/teams_agent/contracts.py 531 -> 572 lines
[FUNC_GREW] src/teams_agent/agent.py::_handle_message 123 -> 127 lines
```

對應 `test_architecture_wave0.py` 也因此 1 failed、11 passed。

不建議直接執行 `--write-baselines` 把成長合法化。應先：

1. 將 Adapter response parsing/formatting 從 `contracts.py` 移至 `wire_parsing.py` 或 `response_parser.py`。
2. 把 `_handle_message()` 的 progress/error/render branches 拆成具名 use cases。
3. 只有在檔案確實縮小後才更新 baseline。

#### OpenAPI snapshot

實際執行結果：

- baseline：213 Backoffice routes。
- current：215 routes。
- 新增 `GET /legacy` 與 `GET /legacy/` 未更新 snapshot。
- FastAPI 同時警告兩組 duplicate operation IDs：source file GET/HEAD、knowledge proxy multi-method route。

應先判定 `/legacy` 是否為正式支援 contract。若是，補安全與 redirect tests 後更新 snapshot；若不是，不應將 emergency route 加入 public API surface。

Duplicate operation IDs 必須修正，否則 OpenAPI client generation 可能覆寫 methods。建議為每個 method 使用獨立 handler 或明確且唯一的 `operation_id`。

### P0-2：Composition root 方向錯誤，形成新循環

現況 import graph 包含：

```text
agent_service -> composition
composition -> agent_service

ai_ops_backoffice -> composition
composition -> ai_ops_backoffice

ai_ops_backoffice -> knowledge_portal
composition -> knowledge_portal
```

具體來源：

- `agent_service/api.py` 在 `create_app()` 內匯入並執行 `composition.agent_hooks.install_agent_hooks()`。
- `composition/agent_hooks.py` 再匯入 Agent 與 Backoffice implementations。
- `ai_ops_backoffice/bootstrap/wiring.py` 匯入 `composition.portal_app` 以建立 in-process Portal。

Composition root 的正確方向應是 composition 匯入 domains；domain 不得回頭匯入 composition。

#### 建議目標

```text
composition.agent_app
  -> agent_service.create_core_app(dependencies)
  -> backoffice adapters

composition.portal_app
  -> knowledge_portal.create_core_app(ports)
  -> backoffice adapters

composition.backoffice_app
  -> ai_ops_backoffice.create_core_app(container)
  -> optional in-process portal app
```

具體修正：

1. 新增 `composition/agent_app.py`，由它安裝 hooks／建立 adapters，再呼叫 Agent core app factory。
2. `agent_service/api.py` 不匯入 composition；它只接受已建立的 runtime dependencies。
3. `agent_service/main.py` 的 uvicorn target 改指向 `composition.agent_app:app`。
4. in-process Portal 應由 `composition/backoffice_app.py` 建立後注入 Backoffice，不由 Backoffice bootstrap 匯入 composition。
5. architecture checker 禁止所有 domain packages 指向 composition。

### P0-3：Architecture checker 只阻擋部分 edges，無法證明「無循環」

目前 `FORBIDDEN_EDGES` 遺漏：

- `agent_service -> composition`
- `ai_ops_backoffice -> composition`
- `knowledge_portal -> composition`
- `ai_ops_backoffice -> knowledge_portal`
- 大量 `ai_ops_backoffice -> agent_service`
- 大量 `knowledge_portal -> agent_service`

因此 baseline allowlist 為空，不代表 dependency graph 無循環，只代表預先列出的少數 forbidden edges 沒有被使用。

建議把 checker 改為：

1. 先建立完整 package graph。
2. 用 strongly connected components 偵測任何 cycle。
3. 定義完整 allowed-edge matrix，而不是只定義少數 forbidden edges。
4. composition 可依賴所有 domains；任何 domain 都不得依賴 composition。
5. domain-to-domain 只允許明確的 integration adapter package，且需逐 edge 說明。
6. CI 將目前 graph 輸出成可 review 的 JSON/DOT artifact。

### P0-4：架構文件宣稱全部 Done，與實際狀態不符

`docs/architecture/README.md` 目前將 Wave 0–5 全部標示 Done，README 也宣稱 domain 之間不可反向 import 且 CI 已 enforce。依本次複審，這兩項陳述不成立。

建議狀態調整為：

| Wave | 建議狀態 |
|---|---|
| 0 Architecture ratchet | **Implemented / currently failing** |
| 1 Kernel + composition | **Partial：ports 已有，composition direction 待修** |
| 2 HTTP / workbench | **Partial：routes 已拆，persistence boundary 待修** |
| 3 Knowledge + Release | **Substantially complete：ports/facades 尚待收口** |
| 4 React ownership | **Default path complete / legacy removal pending** |
| 5 Governance | **Partial：gates 已建立，但 coverage 與 baseline policy 不足** |

## 7. Domain 邊界仍未收斂

### 7.1 Backoffice 對 Agent 內部實作依賴過深

目前 `ai_ops_backoffice -> agent_service` 約 224 個 imports，分布於 115 個檔案。其中：

- `agent_service.operations.*`：156 imports／100 files。
- `agent_service.extractor`：12 imports／12 files。
- 另有 usage、graph、settings、knowledge、workflow、ticket、handoff、retrieval 等 implementation imports。

這表示 Backoffice 仍把 Agent package 當 shared kernel 與 runtime library。雖然 Agent 不再直接 import Backoffice domain implementation，但兩者仍無法真正獨立演進。

#### 建議

- 將 Actor、audit、masking、operational events、taxonomy、scope 等真正共用的 operations domain 移到獨立 `operations_core` package，而不是全部塞進 `platform_kernel`。
- Backoffice evaluation 對真實 Agent workflow 的依賴集中到單一 `adapters/agent_runtime.py`；evaluation domain 只依賴 `AgentEvaluationRuntime` port。
- `build_chat_model`、Agent settings、workflow/handoff/ticket internals 不應散落在 Backoffice domain。
- `platform_kernel` 保持小型 contract package，不接收 repository、service locator 或 runtime builders。

### 7.2 Portal 對 Agent knowledge implementation 的所有權錯置

目前 `knowledge_portal -> agent_service` 約 37 個 imports，分布於 18 個檔案，主要包括：documents、chunking、retrieval、release artifacts、target manifest、source refs 與 artifact storage。

這些能力本質上同時被 knowledge authoring 與 runtime consumption 使用，不應由 Agent package單方面擁有。

建議建立 `knowledge_core`：

- documents/front matter/layout parsing；
- chunking profiles；
- release artifact/manifest identity；
- source identity contract；
- retrieval index contract；
- knowledge release pointer abstractions。

Agent Runtime 與 Knowledge Portal 都依賴 `knowledge_core`，避免 Portal 匯入 Agent implementation。

## 8. HTTP、Application 與 Persistence 邊界

### 8.1 Workbench 仍在 router package 直接存取 filesystem

雖然 routes 已拆檔，但以下仍位於 `routers/workbench/`：

- `persistence.py` 的 `load_json_safe()`／`save_json_safe()`。
- `context.py` 直接載入 state、tickets、chunks。
- FAQ、ticket、document、simulation routes 直接呼叫檔案 helper。

這是物理拆檔完成、邏輯邊界未完成。

建議：

```text
application/workbench/
  ports.py                 # WorkbenchStateRepository, TicketRepository, FaqRepository
  overview.py
  conversations.py
  documents.py
  tickets.py

adapters/workbench/
  file_state_repository.py
  file_ticket_repository.py
  portal_document_gateway.py

routers/workbench/
  ...                      # 只解析/授權/呼叫 use case/映射 response
```

Application layer 不應接受十多個裸 `Callable`；應接受有型別的窄 ports。

### 8.2 Router 仍存取 private state

目前 source routes 仍使用：

- `query_service._source_trace`
- `trace._active_release_id()`
- `query_service._source_trace.source_repository`

Bootstrap 也仍讀取 `_freshness_tracker`、`_runtime.settings`、`export_jobs._store_path` 等 private members。

建議建立：

- `SourceTraceQuery` public interface。
- `MetricsCatalog` interface。
- `FreshnessQuery`／`FreshnessRecorder` interfaces。
- `ExportJobAuthorizationStore` 明確 dependency。

禁止 router 與 bootstrap 直接讀 private members，並在 architecture/lint check 中掃描跨 module `._name` access。

## 9. Knowledge pipeline 後續優化

### 已改善

- facade、planner、retriever、relevance、generation、grounding、citation 與 trace 已具名分離。
- 文件選擇與 generator policy 有獨立 tests。
- `knowledge.py` 不再是 2,838 行 implementation。

### 尚存問題

1. `knowledge_hybrid.py` 仍有約 438 行，超過原 facade <300 的目標。
2. `_HybridGenerationHost` 透過大量 private method 回呼 facade，stage 尚未真正依賴穩定 port。
3. `run_search_loop()` 使用大量 callable parameters，型別與資料流難以閱讀。
4. `apply_generation_retries()` 265 行，將 false-NONE、error coverage、procedure coverage、visual evidence 四種策略放在同一函式。
5. `generate_grounded_answer()` 279 行，仍是新的局部 god function。
6. Pipeline modules 已被直接寫入 oversized-function baseline，代表 ratchet 沒有阻止重構過程新增 >80 行函式。

### 建議方向

- 定義 `KnowledgePipelineContext`，封裝 model、budget、citation、image、trace ports，取代 10+ callback parameters。
- 將 retry 行為拆成 `GenerationRetryPolicy` 列表，每個 policy 實作 `should_retry()` 與 `retry()`。
- `GenerationHost` 使用正式 Protocol，不接受 `Any`，也不依賴 `HybridKnowledgeService` private methods。
- 將 mutable `stage_timings_ms` 從 frozen dataclass 中抽離，避免表面 immutable、內部 mutable。
- 先維持 ranking/prompt 結果不變；介面重構與品質調整分開。

## 10. Release workflow 後續優化

### 已改善

- Release facade 降至 288 行。
- activation、publish、rollback、promote、sync、queries、transitions 已拆分。
- failure matrix 能驗證 reload compensation 的關鍵分支。

### 尚存問題

1. `release/activation.py` 約 491 行，仍集中多個 side effects。
2. `AgentReloadPort` 已定義，但 facade 仍傳遞裸 `notify_reload` callable。
3. `ActivationStorePort` 使用 `object` 與 `hasattr/model_copy`，domain type safety 不足。
4. release package 仍直接 import `agent_service.knowledge_release`、`release_gate`、`target_manifest`。
5. `ports.py` docstring 明確寫著「will adopt in later slices」，與 architecture README 宣稱 Wave 3 Done 不一致。
6. failure matrix 主要覆蓋 decision helpers 與 promote compensation，尚未完整覆蓋 build/gate/source persistence/pointer/audit 每一步的失敗結果。

### 建議方向

- `ReleaseWorkflowDependencies` 聚合 typed store、builder、gate、source catalog、reload、pointer、clock、audit ports。
- `ActivationStorePort` 回傳 `ReleaseRecord`，不要使用 `object`/`hasattr`。
- 使用 `AgentReloadPort` 與 `ActiveReleasePointerPort`，移除裸 callbacks。
- target manifest/release pointer 移至 `knowledge_core`，Portal 不再 import Agent。
- 擴充 failure matrix：build fail、gate blocked、source write fail、pointer write fail、reload fail、compensation reload fail、audit fail。

## 11. Contract 與 OpenAPI governance

### 11.1 Wire checker 覆蓋不足

目前 checker 通過，但有：

```text
WARN: Citation: adapter-only fields not on agent ['originalUrl']
```

它只驗證九個 Python model 的欄位名稱是否存在，沒有驗證：

- field type；
- required/optional；
- enum/Literal；
- default；
- alias；
- nested model；
- serialization/deserialization 行為；
- TypeScript types。

`originalUrl` warning 應有明確決策：加入 Agent contract、從 Adapter 移除，或標示為 Adapter-derived field；不應永久保留 warning。

### 11.2 OpenAPI snapshot 過度簡化

目前 schema inventory 只保存 schema name、type、required 欄位名與 property names；route inventory 還自行產生 stable operation ID，因此無法偵測 FastAPI 真實 duplicate operation IDs。

建議：

- snapshot 實際 OpenAPI operationId、security schemes、parameters、request/response media types。
- schema snapshot保留 property type、format、enum、nullable、items、refs 與 discriminator。
- 以 backward-compatibility diff 判定 breaking/non-breaking，而不是任何變更都要求重寫 snapshot。
- 由 OpenAPI 產生 TypeScript types，CI 執行 generate 後 `git diff --exit-code`。
- Adapter↔Agent Python 可採共用 `agent_protocol` package，或至少做真實 payload round-trip contract tests。

## 12. Frontend 現況與下一步

### 已改善

- `ConversationStream` 已拆成 message、citation、markdown、preview hook 等元件。
- `workbenchStore.ts` 舊路徑只保留 5 行 compatibility export。
- API calls 已按 conversations/documents/FAQ/tickets/overview 分檔。
- 30/30 route ownership 已切到 React。
- production Docker build 會從 lockfile 建置。

### 尚存問題

1. `workbench/store.ts` 仍有 429 行，保存 dashboard、conversation、ticket、FAQ、document、gap 的全部 state 與 mutations。
2. Store constructor 仍主動載入資料，增加測試與 lifecycle 控制難度。
3. `initialMockData` 仍直接參與 production store initialization，容易掩蓋 API failure。
4. `documentsApi.ts` 251 行，混合 import、polling、preview、review、publish、delete。
5. Frontend tests 只有 2 個，內容是讀取 `App.tsx` 原始文字後用 regex 驗證 routes/Refine wiring，不是 component tests。
6. Build 雖成功，但產出單一約 2.12 MB JS chunk，gzip 約 632 KB，Vite 發出 >500 KB warning。
7. Legacy static UI 約 23,000 行仍保留，kill switch 仍可啟用完整舊應用。

### 建議方向

- Store 依 domain 切成 `overviewStore`、`conversationStore`、`knowledgeStore`、`ticketStore`；或採 query cache，把 server state 與 local UI state 分開。
- 移除 constructor side effect，由 provider/hook 明確觸發 load。
- Mock data 只在明確 demo/test adapter 使用，production API failure 顯示 error state。
- 使用 Vitest + React Testing Library 測 route guard、loading/error、citation drawer、markdown、store mutations。
- Route pages 使用 `React.lazy()`/dynamic imports，拆出 Ant Design-heavy feature chunks。
- 設定 bundle budget，例如 entry gzip <350 KB、單一 lazy chunk gzip <200 KB，CI 超標失敗。
- Legacy kill switch 設定移除日期與 usage telemetry；連續一個 release cycle 無使用後刪除 `legacy-js`、legacy CSS/HTML/tests。

## 13. Repository 策略：Repo-ready modular monorepo

### 13.1 決策

**狀態：Accepted（2026-09-18）**

本專案採用以下原則：

> **把 RAG 系統與前端設計成隨時可以拆成兩個 repository，但現階段保留在同一個 repository。**

這裡的「不拆 repo」不代表維持現有耦合。RAG backend 與 frontend 必須先在 monorepo 內成為兩個可獨立交付的產品單元：

- 獨立 dependency manifest 與 lockfile。
- 獨立 build、test、lint、artifact 與 Docker image。
- 獨立 deployment、rollback 與版本識別。
- 只透過公開 HTTP API 與版本化 contract 整合。
- frontend 不 import、讀取或假設 Python implementation、repository、filesystem layout 或 pipeline private state。
- RAG implementation 在不改 API contract 時，不應要求 frontend 同步修改或發版。
- 純 UI 變更不應要求重新建置或部署 RAG backend。

### 13.2 為何現在不直接拆成兩個 repositories

目前直接拆 repo 會把尚未解決的程式內耦合轉換成發版與協作耦合：

- OpenAPI snapshot 尚未提供完整 backward-compatibility 保證，且目前仍有 duplicate operation IDs。
- frontend 尚未使用 generated API client 作為唯一 schema source。
- Backoffice、Portal 與 Agent implementation ownership 尚未收斂。
- legacy routes 與 legacy UI 尚未退場。
- composition direction、shared knowledge contracts 與 deployment topology 仍在調整。
- 多數重構仍需要跨 backend/frontend 的原子提交與整合驗證。

此時拆 repo 會增加跨 repo PR、版本 pinning、CI 發版順序、本機整合與 rollback 成本，但不會自動形成正確邊界。先在單一 repo 內完成可拆性，能保留原子變更能力，也能用同一套 CI 驗證 contract 與整合行為。

### 13.3 目標拓樸

以下是責任拓樸，不要求一次性搬動所有現有目錄；應透過小型 PR 逐步收斂：

```text
teams-agent/
├── apps/
│   ├── rag-api/                  # Python API composition and runtime
│   ├── backoffice-web/           # React application
│   └── knowledge-portal-web/     # React application, if retained separately
├── packages/
│   ├── api-contracts/            # Versioned OpenAPI and generated TypeScript client
│   ├── knowledge-core/           # Documents, chunks, citations, retrieval contracts
│   ├── operations-core/          # Actor, audit, masking, scope, taxonomy
│   └── platform-kernel/          # Small technical primitives only
├── deploy/
│   ├── rag-api/
│   ├── backoffice-web/
│   └── knowledge-portal-web/
└── integration-tests/            # Black-box API and deployed-system tests
```

允許的主要依賴方向：

```text
Frontend applications
        |
        | HTTP + generated TypeScript client
        v
RAG API / application services
        |
        v
knowledge-core / operations-core ports
        |
        v
Infrastructure adapters
```

禁止的依賴包括：

- frontend 直接依賴 backend source tree、Python models 或 generated runtime files。
- backend 依賴 frontend source、bundle 或 UI route ownership。
- frontend 手寫一份與 OpenAPI 平行演化的 API DTO。
- RAG domain 直接回傳 UI component 需要的 presentation-specific structure；應由 API presenter/DTO 轉換。
- 共用 package 同時包含 browser code 與 Python runtime implementation。
- 透過 repository-relative filesystem path 在前後端之間交換 runtime data。

### 13.4 Contract 與版本策略

`packages/api-contracts` 應是 repository 可拆性的核心 seam：

1. RAG API 輸出 canonical OpenAPI document。
2. CI 對 canonical OpenAPI 執行 backward-compatibility diff。
3. TypeScript client 與 types 由 OpenAPI 自動產生，不手動維護重複 DTO。
4. CI 重新產生 client 後要求 working tree 無差異。
5. frontend 只經 generated client 或其薄 application adapter 呼叫 backend。
6. breaking API change 必須使用明確版本策略、migration window 與 deprecation policy。
7. consumer-driven contract tests 覆蓋前端實際使用的 endpoints、error payload、pagination、streaming 與 auth behavior。

在 monorepo 階段，generated client 可以直接作為 workspace package 使用；未來拆 repo 時，再將相同 artifact 發佈到 private package registry。這能讓 repository 搬遷只改變 distribution mechanism，不改變應用程式邊界。

### 13.5 Build、CI 與部署隔離

CI 應形成三個層次：

| 層次 | 觸發範圍 | 必要驗證 |
|---|---|---|
| RAG backend | Python/backend/contracts 變更 | unit、architecture、OpenAPI、RAG integration、backend image build |
| Frontend | React/generated client 變更 | typecheck、component tests、bundle budget、frontend image build |
| Cross-system | contract、auth、streaming、deployment 變更 | generated-client freshness、contract tests、black-box E2E |

即使使用 path filters，required checks 不可因錯誤分類而被跳過。Contract 變更必須同時觸發 backend、client generation、frontend typecheck 與 cross-system tests。

部署面應具備：

- backend 與 frontend 分開的 immutable images。
- 獨立 health checks、version metadata、rollback target 與 release notes。
- frontend 透過設定注入 API base URL，不在 bundle 中綁定 repository 或 environment-specific backend implementation。
- 至少支援「新 frontend + 前一版 backend」與「前一版 frontend + 新 backend」的相容性 smoke tests。

### 13.6 未來拆 repo 的門檻

只有在下列條件持續成立後，才重新評估 physical repository split：

- frontend 對 backend 的唯一依賴是已版本化的 API contract/artifact。
- 前後端已可獨立 checkout、安裝、建置、測試、部署與 rollback。
- API compatibility、generated client freshness 與 consumer contract tests 均為 required checks。
- legacy UI、legacy routes 與 repository-relative runtime coupling 已清除。
- 連續至少兩個 release cycles 中，大部分前端與 RAG 變更可獨立交付。
- 確實存在不同 team ownership、release cadence、access control 或多產品共用 RAG API 的治理需求。
- 已定義跨 repo change protocol、package registry、版本政策、release ordering 與 incident ownership。

若只是希望「目錄看起來乾淨」或「大 repo 感覺太大」，不構成拆 repo 的充分理由。拆分應解決團隊與交付邊界，而不是代替模組化。

### 13.7 Repository split 執行方式

一旦達成門檻，拆分應是機械式搬遷，而不是第二次架構重寫：

1. 凍結並標記 canonical API contract 版本。
2. 將 generated TypeScript client 發佈至 private registry。
3. 先讓 frontend 在 monorepo 內改用 registry artifact，驗證不再依賴 workspace-relative source。
4. 以 history-preserving 工具抽出 frontend repository。
5. 建立跨 repo compatibility workflow 與 coordinated breaking-change 流程。
6. 驗證 build、deployment、rollback、observability 與 local development parity。

此決策的短期成本是必須建立更嚴格的 contract 與 CI；收益是未來可以選擇拆 repo，也可以在沒有額外協作成本的情況下長期維持 monorepo。

## 14. Architecture governance 本身需要修正

### 14.1 Baseline 可被任意重寫

`check_architecture.py --write-baselines` 會把當前狀態直接寫成新基準。若 code 與 baseline 在同一 PR 一起增加，CI 仍可通過。

建議：

- CI 從 default branch 取得 baseline，比較 current branch，而不是只信任 branch 內的 baseline。
- baseline increase 必須搭配逐項 waiver：owner、reason、expiry、removal issue。
- 自動允許 shrink；increase 需要特定 label/approval，而非單純重寫 JSON。
- 新增 regression test：驗證已知 cycle、domain→composition、private access、baseline rewrite 不會被放過。

### 14.2 Waiver 太寬

目前 waiver 以「evaluation/governance domains」等類別一次涵蓋大量檔案，沒有逐檔 owner 與具體 exit work item。這容易把技術債永久正常化。

建議 waiver schema：

```text
path
symbol（若為 function）
current_size
owner
reason
approved_at
expires_at
tracking_issue
target_size
```

### 14.3 Generated/cache hygiene

目前未追蹤 `__pycache__`，`.gitignore` 也正確忽略它們；這部分沒有 repository 污染問題。應持續讓檢查排除 caches 與 generated bundles，但 frontend bundle freshness 必須由 build 驗證。

## 15. 設定、wildcard imports 與測試拓樸

### 15.1 Settings 尚未收斂

四個主要 settings classes 約有：

- Agent：90 個 annotated fields。
- Backoffice：103 個。
- Portal：69 個。
- Adapter：35 個。

`BackofficeSettings.from_env()` 仍有約 367 行，Portal 約 286 行。原計畫的 settings section 拆分尚未執行。

建議以 domain section dataclasses 分拆，並讓 web/worker 只載入所需 section；legacy env aliases 加 deprecation warning 與移除版本。

### 15.2 Wildcard imports 仍存在

example、prompt、quality、sync、budget domains 仍有 15 個 `from ... import *`。這會隱藏 domain API、增加循環與 dead-code 難度。

建議逐 domain 建立明確 `__all__` 與 explicit imports，並在 Ruff 啟用對 wildcard import 的禁止，僅允許少數 compatibility facade 例外。

### 15.3 大型測試檔尚未拆分

目前仍有：

- `test_ai_ops_backoffice.py`：2,616 行。
- `test_spec_gap_p0_p1_followups.py`：2,279 行。
- `test_workflow.py`：2,143 行。
- 多個 1,000–1,600 行測試檔。

大型測試不是第一優先，但應在 domain 邊界穩定後按 unit/application/contract/integration/acceptance 重新分類，避免 mega fixtures 成為下一個耦合中心。

## 16. 建議執行路線

### Phase A：恢復可信的綠燈

1. 拆小 `teams_agent/contracts.py` 與 `_handle_message()`，讓 architecture ratchet 通過。
2. 決定 `/legacy` 是否正式 contract，修正 snapshot。
3. 修正兩組 duplicate OpenAPI operation IDs。
4. 將 architecture README 的 Wave 狀態改成複審後狀態。
5. 在乾淨 checkout 跑 required CI jobs。

**出口條件**：architecture、OpenAPI、wire、frontend、golden、release matrix 全部綠燈。

### Phase B：修正 composition 與 dependency graph

1. 建立 `composition.agent_app` 與 `composition.backoffice_app`。
2. 移除所有 domain→composition imports。
3. architecture checker 改用完整 allowed graph + SCC cycle detection。
4. 新增 cycle fixture tests，證明 checker 能抓到現在這種循環。

**出口條件**：composition 只向內依賴，domain graph 無 SCC cycle。

### Phase C：重定義 shared domain ownership

1. 建立 `operations_core`，移出 Actor/audit/masking/events/taxonomy/scope contracts。
2. 建立 `knowledge_core`，移出 documents/chunking/release artifacts/source identity。
3. 把 Backoffice evaluation 對 Agent runtime 的 imports 集中在一個 adapter。
4. 逐步禁止 Backoffice/Portal 直接 import Agent implementation。

**出口條件**：Backoffice 與 Portal 的 Agent imports 只存在於明確 integration adapters；一般 domain/application modules 為零。

### Phase D：完成 application/persistence boundary

1. 建立 typed Workbench repositories/gateways。
2. 移除 router package 的 JSON helpers。
3. 建立 public SourceTrace/Metrics/Freshness APIs。
4. 清除 router/bootstrap 跨 module private access。

**出口條件**：routers 不做 filesystem/database I/O，不讀 private members。

### Phase E：強化 pipeline 與 release ports

1. Knowledge retry strategies 拆成 policy chain。
2. 用 typed context/ports 取代 callback explosion 與 `_HybridGenerationHost` private forwarding。
3. Release 全面採用 typed store/reload/pointer/catalog ports。
4. 擴充 release failure matrix。

**出口條件**：facade <300 行、一般 stage function <80 行，且無 `Any/object/hasattr` side-effect orchestration。

### Phase F：建立 repo-ready 交付邊界

1. 產生 canonical OpenAPI 與 versioned TypeScript client。
2. frontend 移除手寫平行 DTO，只透過 generated client/application adapter 呼叫 API。
3. backend/frontend 建立獨立 build、test、image、deployment 與 rollback 流程。
4. 新增跨版本 compatibility 與 consumer-driven contract tests。
5. 以 CI path ownership 隔離一般變更；contract 變更仍強制執行全系統驗證。

**出口條件**：前後端可獨立 checkout/build/test/deploy；任一方在 contract 未改變時可獨立發版；repository 內不存在跨邊界 source/runtime path coupling。

### Phase G：前端與 legacy 收尾

1. 真正的 component/store tests。
2. 拆 server-state stores 與 route chunks。
3. 建立 bundle budget。
4. 經 telemetry 驗證後刪除 legacy UI。
5. OpenAPI generated TypeScript types 成為單一來源。

**出口條件**：legacy application code 為零、React tests 驗證行為而非 source text、bundle budget 通過。

### Phase H：殘餘巨型 domain 收斂

依風險順序：

1. `governance_domain/eval_runtime.py`
2. `agent_service/extractor.py`
3. evaluation repository/runner/gate
4. `teams_agent/source_routes.py`
5. quality/FAQ services
6. settings loaders
7. workers/background runtime
8. 大型 tests

每次只處理一個 bounded behavior，不與功能需求混合。

## 17. 建議 PR 切法

| PR | 內容 | 驗證 |
|---:|---|---|
| 1 | 修 architecture growth failures；拆 Adapter parser/handler | architecture + Adapter tests |
| 2 | `/legacy` contract 決策、OpenAPI snapshot、unique operation IDs | OpenAPI + route tests |
| 3 | `composition.agent_app`，移除 Agent→Composition | startup + architecture SCC test |
| 4 | `composition.backoffice_app`，移除 Backoffice→Composition | Backoffice/Portal integration tests |
| 5 | 完整 allowed-edge graph 與 baseline-from-main enforcement | checker unit tests |
| 6 | `operations_core` 第一批：Actor/audit/masking contracts | Backoffice + Agent tests |
| 7 | `knowledge_core` 第一批：manifest/artifacts/source identity | Portal + RAG tests |
| 8 | Workbench typed repository；移除 router JSON I/O | workbench HTTP/contract tests |
| 9 | SourceTrace public query interface；移除 private access | source route tests |
| 10 | Knowledge retry policy chain | golden + generator policy tests |
| 11 | Release typed ports + 完整 failure matrix | release tests |
| 12 | Canonical OpenAPI + generated TypeScript client | schema compatibility + clean regeneration |
| 13 | Frontend API adapters 全面改用 generated client | frontend typecheck + consumer contract tests |
| 14 | Backend/frontend 獨立 images、build 與 deployment metadata | independent build + compatibility smoke |
| 15 | Frontend Vitest/RTL + store split | component/store tests |
| 16 | Route-level code splitting + bundle budget | build budget check |
| 17 | Legacy UI 與 legacy routes removal | route E2E + deployment smoke |
| 18 | 驗證 repo-split readiness；不執行搬遷 | clean-checkout builds + dependency/path audit |

## 18. 更新後量化護欄

| 指標 | 下一階段門檻 |
|---|---:|
| Required CI | 100% green；不可用 baseline rewrite 掩蓋 failure |
| Package cycles | 0，由 SCC 檢查 |
| Domain→Composition imports | 0 |
| Backoffice/Portal→Agent imports | 每個 Phase 必須下降；最終僅 integration adapter 可存在 |
| 新 production file | <=500 行 |
| 新 function | <=80 行 |
| Router module | <=250 行；現有 3 個逐步清零 |
| Router direct persistence | 0 |
| Cross-module private access | 0 |
| Wildcard imports | 0 |
| Frontend behavioral tests | 覆蓋 routes、auth、stores、loading/error、citation/markdown |
| Frontend entry bundle | gzip <350 KB，其他 feature chunks lazy load |
| Legacy UI LOC | 下一個 release cycle 後歸零 |
| Waiver | 每個 path/symbol 有 owner、expiry、tracking issue |
| Frontend→Backend source imports | 0 |
| Handwritten duplicate API DTO | 0；使用 generated client/types |
| Independent build/test/image | RAG backend 與 frontend 各自通過 |
| Contract compatibility | breaking change 必須被 CI 阻擋或走明確版本流程 |
| Cross-version smoke | current/previous frontend 與 backend 組合通過 |
| Repository split | 本階段不執行；只驗證 readiness |

## 19. 本次實際驗證結果

| 驗證 | 結果 |
|---|---|
| `check_architecture.py` | **失敗**：1 個 oversized file growth、1 個 oversized function growth |
| Architecture + release matrix pytest | **11 passed, 1 failed**；失敗原因為 architecture gate |
| OpenAPI snapshot | **失敗**：Backoffice 213→215 routes；另有 duplicate operation ID warnings |
| Wire-contract checker | **通過但有 1 warning**：`Citation.originalUrl` 只存在 Adapter |
| Adapter contract tests | **23 passed** |
| Knowledge selection/generator tests | **7 passed** |
| Frontend tests | **2 passed**，但只驗證 source regex，不是 component behavior |
| Frontend TypeScript/Vite build | **通過**，但有 2.12 MB chunk-size warning |
| Full Python suite | 未執行 |

## 20. 最終判斷

目前架構已從「數個無法審查的超大型檔案」進步到「模組已拆、邊界尚未完全落實」。這是實質進展，不需要推倒重來。

但若直接把現況視為完成，新的風險會是：

- composition 變成隱性 service locator 與 import cycle；
- architecture baseline 變成可重寫的形式檢查；
- Backoffice/Portal 仍綁定 Agent internals；
- routes 雖拆檔，仍直接做 persistence；
- React route 雖完成，測試與 bundle/legacy 治理未完成。

Repository 邊界的決策是：

> **邏輯、contract、build、test 與 deployment 立即拆開；Git repository 暫時不拆。**

因此建議的下一個 milestone 是：

> **先讓 required CI 真正全綠，再修正 composition direction 與 full dependency graph；接著建立 generated API client 與獨立交付邊界，最後才處理 legacy removal、剩餘巨型 domain，以及是否真的需要拆 repo。**

這個順序能保留 monorepo 在重構期的原子提交與整合驗證優勢，同時確保未來拆 repo 時只需搬遷與改變 artifact distribution，不必再次重寫架構。
