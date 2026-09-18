# 專案架構重構後複審與持續優化計畫

> 複審日期：2026-09-18
> Git 基準：`main@0b3ce32`
> 前次基準：`main@641aaa7`
> 原始計畫：`docs/project-architecture-refactor-plan-20260918.md`
> 範圍：Teams Adapter、Agent/RAG Runtime、Knowledge Portal、AI Ops Backoffice、React Console、composition、contracts、CI 與部署拓樸
> Repository 決策：**維持 repo-ready modular monorepo；先把 RAG 與 frontend 做到可獨立交付，暫不拆成兩個 repositories。**

## 1. 執行摘要

本輪重構有實質成果，前次複審最嚴重的 architecture cycle、size gate 與 OpenAPI snapshot failure 已處理：

- `agent_service`、`ai_ops_backoffice`、`knowledge_portal` 不再反向 import `composition`。
- ASGI entry 已改由 `composition.agent_app`、`composition.backoffice_app` 與 `composition.portal_app` 組裝。
- architecture checker 新增 Tarjan SCC cycle detection，目前 package graph 無 cycle。
- reverse-import allowlist 目前為空，architecture check 通過。
- OpenAPI snapshots 現在一致，先前的 duplicate operation ID warnings 已消失。
- `src/teams_agent/contracts.py` 從 572 行降至 397 行，formatting 行為移至 `formatting.py`。
- `agent_service/extractor.py` 從約 979 行降至 802 行，heuristics 移至 360 行的具名模組。
- Knowledge、release、composition 與 portal regression tests 均通過。
- 全套 Agent Service tests 為 1,708 passed；Teams Adapter tests 為 213 passed。

但專案仍不能標示為「架構重構全部完成」，原因如下：

1. **Required CI 仍會失敗**：Teams Adapter Ruff 有 1 個錯誤；Agent Service Ruff 有 859 個錯誤，其中 production source 771 個、tests 88 個。
2. **Composition 已修正方向，但仍有 import-time side effects**：`composition/__init__.py` eager-import 三個 app modules，而各 module 都在 import 時執行 `app = create_*_app()`；啟動單一服務可能額外組裝其他服務。
3. **無 cycle 不等於 domain 邊界健康**：Backoffice 仍有 115 個檔案 import Agent implementation，Portal 仍有 18 個檔案 import Agent implementation。這些 edges 沒被列為 forbidden，因此 checker 會通過。
4. **Size baseline 不是單調 ratchet**：baseline 未在 shrink 後下修，`extractor.py` 可從 802 行重新長回 978 行而不失敗；`contracts.py` 可從 397 行長回 531 行而不失敗。
5. **HTTP/application/persistence 邊界仍有穿透**：Workbench router package 直接讀寫 JSON；source routers 與 bootstrap 仍讀取 private members。
6. **Repo-ready 目標尚未完成**：frontend 仍被 bake 進 Backoffice image，沒有 generated TypeScript client、獨立 frontend artifact/deploy 或跨版本 compatibility tests。
7. **Frontend 品質門檻仍偏低**：只有 2 個 regex-based tests，production bundle 仍是單一約 2.12 MB chunk，store 仍同時管理多個 domains 與 production mock defaults。

因此，目前最準確的狀態是：

> **主要循環與幾個高風險熱點已處理，架構治理開始可用；下一階段應從「拆檔」轉向「讓 CI 可信、讓邊界可執行、讓前後端可獨立交付」。**

## 2. 複審方法與限制

本次複審採用以下方法：

- 比對 `641aaa7..0b3ce32` 的實際變更。
- 執行 architecture、OpenAPI、wire-contract、Ruff、frontend build/test。
- 執行 Teams Adapter 與 Agent Service 全套 tests。
- 以 Python AST 統計 package dependency edges、檔案大小與函式大小。
- 檢查 composition、app factories、routers、bootstrap、settings、ports、Dockerfiles 與 CI workflow。
- 檢查 frontend store、API types、tests、bundle 與 legacy UI。

本文件的判定原則：

- 原始碼與測試是權威來源；文件中的 `Done` 不自動視為完成。
- 行數只代表風險訊號，不代表一定要拆分。
- 測試通過證明現有 assertions 通過，不代表 architecture boundary 已經正確。
- 本次只更新文件，未修改 production code、tests、baselines 或 generated assets。

## 3. 前次問題的複驗結果

| 前次問題 | 現況 | 判定 |
|---|---|---|
| Architecture ratchet failure | `check_architecture.py` 通過 | **已關閉** |
| OpenAPI snapshot drift | snapshots match | **已關閉** |
| Agent→Composition cycle | domain→composition imports 已移除 | **已關閉** |
| Backoffice→Composition cycle | 已改由 runtime hook/factory injection | **已關閉** |
| Checker 不偵測 SCC | 已加入 Tarjan SCC detection | **已關閉** |
| `contracts.py` 成長 | 572→397，formatting 抽出 | **已關閉** |
| `_handle_message()` 成長 | architecture gate 已恢復通過 | **已關閉** |
| `extractor.py` 巨型檔案 | 約 979→802 | **改善，未完成** |
| Workbench router persistence | JSON I/O 仍在 router package | **未處理** |
| Router private state | source routes/bootstrap 仍存在 | **未處理** |
| Backoffice/Portal→Agent imports | 115/18 importer files | **未處理** |
| Wire schema coverage | 仍只比對 Python 欄位名稱 | **未處理** |
| Generated TypeScript API client | 不存在 | **未處理** |
| Frontend behavioral tests | 仍只有 2 個 source-regex tests | **未處理** |
| Single frontend bundle | 仍約 2.12 MB | **未處理** |
| Legacy UI retirement | 約 18,097 LOC，kill switch 仍存在 | **部分改善** |
| Ruff required CI | Adapter 1 error；Agent 859 errors | **新的 P0** |

## 4. 量化現況

### 4.1 Production source

統計排除 tests、`node_modules`、static generated bundles、data、outputs、artifacts 與 caches。

| 指標 | 前次複審 | 現況 | 變化 | 判讀 |
|---|---:|---:|---:|---|
| Production source files | 553 | 561 | +8 | 新增具名模組與 composition entrypoints |
| Production LOC | 108,375 | 108,486 | +111 | 總量近乎持平 |
| >300 行檔案 | 117 | 116 | -1 | 中型模組密度仍高 |
| >500 行檔案 | 47 | 46 | -1 | 改善有限 |
| >800 行檔案 | 13 | 13 | 0 | 極端熱點未繼續下降 |
| >80 行 Python functions | 175 | 173 | -2 | 仍有大量流程型函式 |
| >150 行 Python functions | 53 | 52 | -1 | 改善有限 |
| >250 行 Python functions | 13 | 13 | 0 | 主要 orchestration 熱點未動 |

本輪不是無效重構：總 LOC 幾乎未增加，且 contracts/extractor 確實縮小。不過整體複雜度只小幅下降，下一輪不能只依靠檔案搬移。

### 4.2 主要改善

| 模組 | 前次 | 現況 | 判定 |
|---|---:|---:|---|
| `src/teams_agent/contracts.py` | 572 | 397 | formatting responsibility 已分離 |
| `src/teams_agent/formatting.py` | 不存在 | 212 | 新增 cohesive formatter module |
| `agent_service/extractor.py` | 約 979 | 802 | heuristics 與部分 invocation flow 已抽出 |
| `extractor_heuristics.py` | 不存在 | 360 | 純 heuristic policy 有明確位置 |
| `knowledge_portal/draft_assets.py` | 約 617 | 531 | asset validation 抽出 |
| `knowledge_portal/asset_validation.py` | 不存在 | 156 | validation boundary 改善 |
| `knowledge_bridge/routes.py` | 約 482 | 268 | route orchestration 縮小 |
| `routers/sources/file.py` | 約 240 | 107 | file streaming responsibility 分離 |

### 4.3 最大 production files

| 檔案 | 行數 | 建議方向 |
|---|---:|---|
| `governance_domain/eval_runtime.py` | 1,018 | Agent runtime adapter、sandbox、invocation 分離 |
| `evaluation_domain/repository.py` | 975 | port、serialization、File/Firestore adapters 分離 |
| `evaluation_domain/runner.py` | 973 | single-turn、multi-turn、comparison、checkpoint 分離 |
| `teams_agent/source_routes.py` | 916 | source serving、viewer auth、SSO/session 分離 |
| `quality_domain/service.py` | 902 | 依 use case 拆 application services |
| `evaluation_domain/gate_repository.py` | 884 | policy、decision、schedule persistence 分離 |
| `teams_agent/source_links.py` | 866 | resolver、signer、mapping 分離 |
| `faq_domain/service.py` | 865 | draft/review/activate/test use cases 分離 |
| `governance_routes.py` | 844 | 依 governance resource 拆 router registrar |
| `evaluation_domain/gate_service.py` | 821 | gate evaluation 與 activation coordination 分離 |
| `evaluation_domain/service.py` | 813 | command/query application services 分離 |
| `agent_service/extractor.py` | 802 | model invocation、normalization、fallback 分離 |

### 4.4 最大 functions

| Symbol | 行數 | 風險 |
|---|---:|---|
| `source_routes.py::create_source_router` | 703 | 單一 registrar 擁有過多 auth/session/source behaviors |
| `governance_routes.py::register_governance_routes` | 630 | HTTP surface 與 use cases 高度聚合 |
| `workers.py::install_background_runtime` | 554 | scheduling、lifecycle、dependencies 混合 |
| `BackofficeSettings.from_env` | 359 | env parsing 與全部 domain configuration 聚合 |
| `query_conversations.py::list_conversations` | 299 | query shaping、join、filter 混合 |
| `PortalSettings.from_env` | 286 | 同上 |
| `publisher.py::build_release` | 273 | release assembly 流程仍集中 |
| `generation_stage.py::generate_grounded_answer` | 270 | generation orchestration 仍過長 |
| `generation_retries.py::apply_generation_retries` | 261 | retry policies 仍以大型程序實作 |

## 5. 實際驗證結果

| 驗證 | 結果 |
|---|---|
| Architecture checker | **通過** |
| OpenAPI snapshots | **通過** |
| Wire-contract checker | **通過但有 warning**：`Citation.originalUrl` 只存在 Adapter |
| Architecture + release matrix tests | **15 passed** |
| Knowledge selection/generator/pipeline tests | **17 passed** |
| Portal/playground regression tests | **37 passed，1 warning** |
| Teams Adapter full pytest | **213 passed，4 warnings** |
| Agent Service full pytest | **1,708 passed，6 warnings** |
| Frontend tests | **2 passed**；僅為 source-regex smoke tests |
| Frontend TypeScript/Vite build | **通過**；單一 JS 約 2.12 MB、gzip 約 632.55 KB |
| Teams Adapter Ruff | **失敗**：1 個 unused import |
| Agent Service Ruff | **失敗**：859 errors |

Agent Service Ruff 分布：

| 範圍 | 數量 | 主要問題 |
|---|---:|---|
| Production source | 771 | 681 unused imports、47 import ordering、2 undefined names 等 |
| Tests | 88 | 47 unused imports、22 undefined names、13 import ordering 等 |

由於 `.github/workflows/ci.yml` 把兩個 Ruff steps 都列為 required job steps，目前不能宣稱 required CI 全綠。

## 6. 已完成且應保留的設計

### 6.1 Composition direction

`composition` 現在是 outward dependency root：

```text
composition
  -> agent_service
  -> ai_ops_backoffice
  -> knowledge_portal
```

Domain packages 不再 import `composition`，這是正確修正。`agent_service.main`、`ai_ops_backoffice.main`、`knowledge_portal.main` 也已指向 composed ASGI apps。

### 6.2 SCC cycle detection

Architecture checker 已不再只依賴手寫 reverse edges，也會對完整 package graph 執行 strongly connected component detection。這能防止不同路徑形成的新循環，應保留並增加 fixture tests。

### 6.3 Thin app factories

Agent、Portal、Backoffice 的 `create_app()` 仍維持薄層，主要 wiring 由 container、route registration 與 composition 負責。後續修正 import-time side effects 時，不應把 wiring 塞回 domain `api.py`。

### 6.4 Knowledge 與 release stages

Knowledge 已有 planner、retrieval、relevance、generation、grounding、citation 與 trace stages；Release 已有 explicit transitions、coordinator、activation、publish、rollback。下一步是縮窄 typed context/ports，不是再次全面搬檔。

### 6.5 Default React product path

30/30 ledger routes 已由 React `/console-v2` 接手，預設 `/` 與 `/legacy` 會 redirect 到 React UI；legacy shell 只在 kill switch 開啟時提供。這個產品路徑應保持。

## 7. P0：Required CI 目前失敗

### 問題

最新提交標題宣稱完成 architectural decoupling，但與 CI 相同的 Ruff commands 仍失敗：

- Adapter：`src/teams_agent/contracts.py` 有未使用的 `re` import。
- Agent Service：859 errors，包含 production source 的 2 個 `F821 undefined-name`。
- CI 在 Ruff 之後才執行 architecture、OpenAPI 與 pytest，因此 GitHub required job 會先失敗。

### 建議

1. 先處理 `F821`、mutable class defaults、loop capture 等可能影響 runtime correctness 的項目。
2. 再使用 Ruff safe fixes 處理 import ordering 與明確 unused imports。
3. 對 compatibility facade/re-export module 使用明確 `__all__`，不要靠大量 unused imports 維持 public API。
4. 將純 formatting cleanup 與 behavioral refactor 分開提交。
5. 在乾淨 checkout 執行 CI 全部 jobs，確認不是本機環境差異。

### 出口條件

- 兩個 Ruff commands exit 0。
- architecture、OpenAPI、wire、frontend、full pytest 同時通過。
- 不以擴大 Ruff ignore list 掩蓋 `F821` 或 dead imports。

## 8. P0：Composition 仍有 import-time side effects

### 問題

目前 `composition/__init__.py` eager-import：

- `composition.agent_app`
- `composition.backoffice_app`
- `composition.portal_app`
- `composition.agent_hooks`

而前三個 app modules 都在 module scope 執行 `app = create_*_app()`。此外三個 domain `api.py` 也各自保留 `app = create_app()`。

Python 載入 `composition.agent_app` 前會先執行 `composition/__init__.py`。因此啟動 Agent 時，可能同時 import 並組裝 Backoffice、Portal 以及未注入 dependencies 的 domain default apps。可能後果包括：

- 非目標服務解析額外 settings 與 filesystem paths。
- 建立重複 containers、repositories、lifespans 或 clients。
- import order 影響 runtime hook registration。
- 測試 import core factory 時意外建立 production-shaped global app。
- 啟動時間、記憶體與錯誤面擴大。

### 建議

1. `composition/__init__.py` 保持空白或只放 package docstring，不 re-export app factories。
2. ASGI module 每個只組裝一個 app，例如 `composition/agent_asgi.py`。
3. Domain `api.py` 只提供 `create_app()`；若需要 standalone app，放入獨立 `*_asgi.py`。
4. Hook/dependency registration 改成 factory arguments 或 typed container，不依賴 import order。
5. 新增測試：import 任一 ASGI entry 時，只建立該服務的 container。

### 出口條件

- import `composition.agent_app` 不載入 Backoffice/Portal app instances。
- domain factory import 不讀環境、建立目錄或連線外部服務。
- composition initialization 可重複且無全域順序依賴。

## 9. P1：Dependency graph 無循環，但 ownership 仍錯置

### 現況

AST 統計的跨 package importer files：

| Edge | Importer files | 判讀 |
|---|---:|---|
| `ai_ops_backoffice -> agent_service` | 115 | 過度依賴 Agent implementation |
| `knowledge_portal -> agent_service` | 18 | Knowledge ownership 仍放在 Agent namespace |
| `ai_ops_backoffice -> knowledge_portal` | 1 | bootstrap wiring residual |
| `agent_service -> platform_kernel` | 4 | 合理方向 |
| `ai_ops_backoffice -> platform_kernel` | 6 | 合理方向 |
| `knowledge_portal -> platform_kernel` | 3 | 合理方向 |

Backoffice 對 Agent imports 中，`agent_service.operations` 就出現在 100 個檔案。Portal 則直接依賴 `documents`、`target_manifest`、`release_gate`、`layout_chunking`、`knowledge_release` 等 Agent modules。

目前 checker 將這些視為允許 edges，所以「architecture checks passed」只代表沒有 forbidden/cyclic edge，不代表 ownership 已收斂。

### 建議 ownership

建立兩個 bounded shared packages，但避免把所有東西塞進 `platform_kernel`：

```text
operations_core
  ActorContext
  audit/event contracts
  masking contracts
  taxonomy/scope identifiers
  freshness metadata contracts

knowledge_core
  document/chunk/source identity
  target/release manifest
  citation/retrieval contracts
  release artifact contracts
  pure chunking policies
```

`platform_kernel` 只保留真正技術性且穩定的 ports/primitives。Agent runtime、Backoffice 與 Portal 都依賴 shared contracts；具體 adapters 由 composition 注入。

### Checker 改進

- 從 partial forbidden list 改成完整 allowed-edge matrix。
- 對目前允許但過大的 edges 建立 importer-count ratchet。
- `ai_ops_backoffice -> agent_service` 與 `knowledge_portal -> agent_service` 每個 PR 只能下降，不可增加。
- 最終只有明確 integration adapter 可以 import runtime implementation。

## 10. P1：Size baseline 不是單調 ratchet

目前 baseline 儲存歷史上限，而不是 current main 的最小值：

- `extractor.py` baseline 978，current 802。
- `contracts.py` baseline 531，current 397。

checker 只在 current 超過 baseline 時失敗。因此已縮小的檔案仍可重新增長到舊 baseline；這不符合 ratchet 的語意。

此外，`--write-baselines` 可直接用 branch 當前狀態覆寫基準，若 code 與 baseline 同一 PR 成長，reviewer 難以區分合理 waiver 與重新合法化。

### 建議

1. CI 從 default branch 讀 baseline/current metrics，比較 PR branch。
2. Shrink 自動成為新上限，不依賴人工執行 `--write-baselines`。
3. Growth 只能透過逐項 waiver：path、symbol、owner、reason、expiry、tracking issue、target size。
4. Waiver 到期自動失敗，不只在 Markdown 寫一個全域 review date。
5. 加入 regression test，驗證 978→802 後再長到 803 會失敗。

## 11. P1：HTTP、application 與 persistence 邊界未完成

### Workbench persistence

`ai_ops_backoffice/routers/workbench/persistence.py` 仍直接執行：

- `Path.read_text()`
- `Path.write_text()`
- `json.loads()` / `json.dumps()`

檔案雖小，但責任仍屬 repository/adapter，而不是 HTTP package。

### Private-state access

目前仍可觀察到：

- source routers 使用 `query_service._source_trace`。
- resolver 使用 `trace._active_release_id()`。
- resolver 直接存取 `source_repository` 與 `artifact_storage`。
- bootstrap 使用 `export_jobs._store_path`。
- bootstrap 使用 `existing_runtime._settings` 或 `query_service._runtime.settings`。

### 建議

1. 建立 typed `WorkbenchRepository`、`SourceQueryService`、`RuntimeSettingsView`。
2. Router 只做 request validation、authorization、application call、response mapping。
3. 所有 filesystem/database I/O 移至 adapters。
4. 禁止跨 module private-member access，納入 AST gate。
5. Source preview/file/resolve 共用 public source application service，避免各 route 自行拼裝。

## 12. P1：Contract governance 仍不足以支撐拆 repo

### Wire checker

`check_wire_contracts.py` 目前只檢查：

- 9 個 Python models 是否存在。
- 指定欄位名稱是否存在。

它不檢查 type、requiredness、default、alias、enum、nested schema、serialization 或 TypeScript consumers。`Citation.originalUrl` 仍只有 Adapter 定義，checker 只發 warning。

### OpenAPI snapshot

目前比前次更穩定，但仍有兩個限制：

1. `operationId` 由 snapshot script 依 method/path 重建，沒有保存 FastAPI 真實 operation ID。
2. Component snapshot 只保存 schema name、top-level type、required fields 與 property names，不保存 property types、formats、enums、nullable、items、refs 或 discriminators。

這能抓 route/schema inventory drift，不能可靠判斷 backward compatibility。

### 建議

1. 保存 canonical OpenAPI document 或使用專用 breaking-change diff。
2. 保留真實 operation IDs。
3. 從 OpenAPI 自動產生 TypeScript client/types。
4. CI 執行 generate 後要求 working tree clean。
5. 加入 consumer-driven contract tests，覆蓋 error payload、pagination、streaming、auth 與 frontend 實際使用 endpoints。

## 13. Repo-ready modular monorepo 複驗

### 13.1 決策維持不變

> **RAG backend 與 frontend 在 contract、build、test、artifact、deploy 上應可獨立；Git repository 目前維持單一。**

現在直接拆 repo 仍不合適，因為 API contract 與 shared ownership 尚未穩定。拆 repo 只會把 source coupling 變成跨 repo release coupling。

### 13.2 已具備的條件

- `console_frontend` 有獨立 `package.json`、lockfile、test/build commands。
- Agent、Portal、Backoffice 有不同 Dockerfiles 與 runtime entrypoints。
- deploy script 已能依路徑選擇部分 backend components。
- frontend build 已可從 TypeScript source 重現 production bundle。

### 13.3 尚未具備的條件

- Frontend 沒有獨立 Docker image；`Dockerfile.backoffice` 會 build frontend 後 bake 到 Python Backoffice image。
- 純 frontend 變更仍要求重建與部署 Backoffice image。
- Frontend DTO 為手寫：`shared/api/types.ts` 300 行、`workbench/types.ts` 112 行。
- 沒有 canonical generated TypeScript client package。
- 沒有 current/previous frontend/backend cross-version tests。
- `agent_service/pyproject.toml` 同一個 wheel 同時包含 Agent、Portal、Backoffice、kernel 與 composition。
- 三個 backend images 都 copy 整個 `agent_service/src` 並安裝同一個 package。
- Legacy UI/routes 還沒清除。

### 13.4 目標拓樸

```text
teams-agent/
├── apps/
│   ├── rag-api/
│   ├── backoffice-api/
│   ├── knowledge-portal-api/
│   └── console-web/
├── packages/
│   ├── api-contracts/
│   ├── knowledge-core/
│   ├── operations-core/
│   └── platform-kernel/
├── deploy/
└── integration-tests/
```

這是責任拓樸，不要求一次性移動目錄。先建立可獨立交付的 seams，再做機械式搬遷。

### 13.5 未來拆 repo 門檻

- Frontend 對 backend 的唯一依賴是版本化 API artifact。
- 前後端可獨立 checkout、install、build、test、deploy、rollback。
- API compatibility 與 generated-client freshness 是 required checks。
- 純 UI 變更不重建 backend image。
- 純 RAG implementation 變更在 API 不變時不重建 frontend。
- Legacy UI/runtime path coupling 已清除。
- 連續至少兩個 release cycles 大多數變更可獨立交付。
- 確實存在不同 team ownership、release cadence、access control 或多產品共用需求。

## 14. Frontend 現況

### 問題

1. `workbench/store.ts` 429 行，同時管理 dashboard、conversation、ticket、FAQ、document、gap。
2. Store constructor 立即呼叫 `loadAll()`，造成 import/lifecycle side effect。
3. Production store 以 `initialMockData` 初始化；API failure 可能留下看似有效的假資料。
4. `documentsApi.ts` 251 行，混合 import、polling、preview、review、publish、delete。
5. API DTO 至少有 412 行手寫 types，容易與 backend drift。
6. Tests 只有 2 個，且只是讀 `App.tsx` 文字後用 regex 驗證 routes/Refine wiring。
7. Build 產出單一約 2.12 MB JS，gzip 約 632.55 KB，超過 Vite 500 KB warning。
8. `CaseDetailPage.tsx` 780 行、`ChunkInspectorModal.tsx` 580 行。
9. Legacy JS 約 18,097 LOC，kill switch 仍可重新啟用。

### 建議

- Server state 改用 query cache；local UI state 與 domain commands 分離。
- Store 依 overview、conversation、knowledge、ticket 拆分。
- 移除 constructor fetch，由 provider/hook 明確啟動。
- Production 預設空 state + visible error；mock data 只由 demo/test adapter 注入。
- 使用 Vitest + React Testing Library 驗證 route guard、loading/error、citation、markdown、store mutations。
- Route-level dynamic imports，拆出 Ant Design-heavy chunks。
- 設 bundle budget：entry gzip <350 KB、單一 lazy chunk gzip <200 KB。
- 建立獨立 frontend image，由 CDN/static host 或 web container 提供；API URL 由 runtime config 注入。
- Legacy kill switch 加 usage telemetry 與刪除日期；一個 release cycle 無使用後移除。

## 15. RAG、Knowledge 與 Release 後續優化

### 15.1 Extractor

本輪把 heuristics 抽出是正確的，但 `extractor.py` 仍有 802 行。下一步應按責任拆分：

- structured model invocation adapter
- fallback/model-switch policy
- issue normalization
- extraction result assembly

不要再把所有 private constants re-import 回 facade；只 import 實際使用的 public policy functions/types。

### 15.2 Generation pipeline

`generate_grounded_answer()` 270 行、`apply_generation_retries()` 261 行。建議建立 typed `GenerationContext` 與 strategy chain：

```text
PrimaryGeneration
  -> CitationRepair
  -> GroundingRepair
  -> FallbackGeneration
  -> FinalValidation
```

每個 strategy 回傳 typed outcome 與 reason，不以 callback explosion 或 private-host forwarding 傳遞狀態。

### 15.3 Release workflow

保留 explicit transitions/compensation，不引入通用 workflow engine。下一步集中在：

- typed store/reload/pointer/catalog ports
- 移除 `object`、`Any`、`hasattr` orchestration
- Portal 不直接 import Agent release implementation
- failure matrix 加入 timeout、partial publish、stale pointer、idempotent retry

### 15.4 Settings

目前主要 settings files：

- Agent：498 行。
- Backoffice：488 行，`from_env()` 359 行。
- Portal：426 行，`from_env()` 286 行。

應拆成 immutable sections，例如 `RagModelSettings`、`KnowledgeSettings`、`StorageSettings`、`AuthSettings`、`WorkerSettings`。Service 只接收需要的 section，不傳整個 global settings object。

## 16. 其他治理問題

### Wildcard imports

Backoffice 仍有 15 個 `from ... import *`，集中於 example、prompt、quality、sync、budget domains。應以明確 `__all__` 與 explicit imports 取代，compatibility facade 才可例外。

### Oversized waivers

目前 waiver 仍以類別描述，沒有逐檔 owner、tracking issue、target size。應改成 machine-readable entries，並由 CI 驗證 expiry。

### Test topology

Tests 約 60,061 行，仍有多個巨型檔案：

- `test_ai_ops_backoffice.py`：2,616 行。
- `test_spec_gap_p0_p1_followups.py`：2,279 行。
- `test_workflow.py`：2,143 行。
- `test_phase1_reliability.py`：1,629 行。

不需要為行數立即拆測試；應在 domain boundary 穩定後，按 unit/application/contract/integration/acceptance 分類，縮小 mega fixtures 與 shared mutable setup。

## 17. 建議執行路線

### Phase A：恢復可信的 required CI

1. 修正 Adapter 1 個 Ruff error。
2. 修正 Agent production `F821` 與 correctness-related findings。
3. 清理 safe unused imports/import ordering。
4. 對 re-export facades 建立明確 `__all__`。
5. 在乾淨 checkout 執行所有 CI jobs。

**出口條件**：Ruff、architecture、OpenAPI、wire、frontend、full pytest 全綠。

### Phase B：消除 composition import side effects

1. 清空 `composition/__init__.py` eager imports。
2. 分離 factory modules 與 ASGI singleton modules。
3. Domain `api.py` 不建立 global default app。
4. Hook registration 改成 explicit dependencies。
5. 新增 single-service import/initialization tests。

**出口條件**：import 任一服務不組裝其他服務；factory import 無 I/O side effects。

### Phase C：讓 architecture ratchet 真正單調

1. Baseline-from-main comparison。
2. Shrink 自動成為新上限。
3. Per-symbol waiver schema 與 expiry enforcement。
4. Allowed-edge matrix + importer-count ratchet。

**出口條件**：已縮小檔案不能無聲回長；任何新增跨 domain import 都需明確允許。

### Phase D：收斂 shared ownership

1. 抽出 `operations_core`。
2. 抽出 `knowledge_core`。
3. Backoffice Agent runtime imports 集中到 `adapters/agent_runtime.py`。
4. Portal 不再 import Agent knowledge/release implementations。

**出口條件**：Backoffice/Portal→Agent imports 只存在於少量 integration adapters，並持續下降至零 implementation imports。

### Phase E：完成 application/persistence boundary

1. Workbench typed repositories。
2. Source public application service。
3. 移除 router filesystem I/O。
4. 移除跨 module private access。

**出口條件**：routers 不讀寫 filesystem/database，不存取 private members。

### Phase F：建立 repo-ready contract seam

1. Canonical OpenAPI breaking-change check。
2. Generated TypeScript client/types。
3. Consumer-driven contract tests。
4. Frontend/API cross-version compatibility matrix。

**出口條件**：frontend 不維護平行 DTO；API 不相容變更會被 CI 阻擋。

### Phase G：Frontend 獨立交付與 legacy removal

1. 獨立 frontend image/artifact/deploy/rollback。
2. Store 與 API modules 分 domain。
3. Behavioral component tests。
4. Route code splitting 與 bundle budget。
5. 移除 legacy UI/routes。

**出口條件**：純 UI 變更不建置 Backoffice Python image；legacy application LOC 為零。

### Phase H：殘餘巨型 domain 收斂

依風險順序：

1. `governance_domain/eval_runtime.py`
2. evaluation repository/runner/gate
3. `teams_agent/source_routes.py`
4. quality/FAQ services
5. `agent_service/extractor.py`
6. generation/retry functions
7. settings loaders
8. workers/background runtime

每個 PR 只處理一個 bounded behavior，必須以 characterization/contract tests 保護。

## 18. 建議 PR 切法

| PR | 內容 | 驗證 |
|---:|---|---|
| 1 | 修 Adapter Ruff + Agent production `F821` | Ruff targeted + relevant tests |
| 2 | Agent safe unused-import/import-order cleanup | Full Agent pytest + Ruff |
| 3 | Test Ruff cleanup | Full pytest + Ruff |
| 4 | Composition package/init side-effect removal | startup/import tests + architecture |
| 5 | Monotonic baseline-from-main ratchet | checker unit/regression tests |
| 6 | Full allowed-edge matrix + import-count ratchet | graph fixture tests |
| 7 | `operations_core` first slice | Agent + Backoffice contract tests |
| 8 | `knowledge_core` first slice | RAG + Portal release tests |
| 9 | Workbench repository boundary | HTTP/application tests |
| 10 | Source public query service | source route tests |
| 11 | Canonical OpenAPI diff | API compatibility fixtures |
| 12 | Generated TypeScript client | clean regeneration + frontend typecheck |
| 13 | Frontend behavioral test foundation | Vitest/RTL tests |
| 14 | Store split + production mock removal | store/component tests |
| 15 | Independent frontend artifact/deploy | image + smoke + rollback tests |
| 16 | Route code splitting + bundle budget | production build budget |
| 17 | Legacy UI/routes removal | E2E + deployment smoke |
| 18 | Repo-split readiness audit | clean checkout/path/dependency audit |

## 19. 更新後量化護欄

| 指標 | 門檻 |
|---|---:|
| Required CI | 100% green |
| Package SCC cycles | 0 |
| Domain→Composition imports | 0 |
| Import-time cross-service app creation | 0 |
| Backoffice→Agent importer files | 每個 ownership PR 必須下降；最終 implementation imports 為 0 |
| Portal→Agent importer files | 每個 ownership PR 必須下降；最終 implementation imports 為 0 |
| New production file | <=500 行 |
| New function | <=80 行 |
| Ratchet | current main shrink 自動成為新上限 |
| Router direct persistence | 0 |
| Cross-module private access | 0 |
| Wildcard imports | 0 |
| Handwritten duplicate frontend DTO | 0 |
| OpenAPI breaking changes | 未版本化時 0 |
| Frontend behavioral tests | route/auth/store/loading/error/citation/markdown |
| Frontend entry bundle | gzip <350 KB |
| Single lazy feature chunk | gzip <200 KB |
| Legacy UI LOC | 0 |
| Waiver | 每個 path/symbol 有 owner、expiry、issue、target |
| Repository split | 本階段不執行，只驗證 readiness |

## 20. 不建議做的事

- 不要因 Ruff errors 很多就把規則全部 ignore。
- 不要直接用 `--write-baselines` 接受成長。
- 不要只為降行數建立無語意的 `helpers2.py`。
- 不要把所有 shared code 都塞進 `platform_kernel`。
- 不要在 contract 未穩定前拆成兩個 repositories。
- 不要導入通用 workflow framework 取代已清楚的 release state transitions。
- 不要讓 frontend mock data 在 production API failure 時偽裝成真實資料。
- 不要在同一 PR 同時做 ownership 搬遷、API breaking change 與 UI redesign。

## 21. 最終判斷

本輪已經完成一個重要轉折：專案從「architecture checker 本身抓不到循環且 gates 為紅」進步到「循環已修、architecture/OpenAPI gates 可運作、完整測試通過」。這是實質成果。

但目前仍有三個不能忽略的事實：

1. Required Ruff CI 失敗，所以尚未具備可信的綠燈基準。
2. Composition 方向正確，但 import-time app construction 仍可能造成跨服務 side effects。
3. Backoffice/Portal 對 Agent implementation 的大量單向依賴仍存在；無 cycle 只代表 graph 是 DAG，不代表 bounded contexts 已正確。

下一個 milestone 應是：

> **先恢復 required CI 全綠並消除 composition import side effects；接著讓 architecture ratchet 單調、收斂 shared ownership；最後以 canonical OpenAPI/generated client 建立前後端獨立交付邊界。**

Repository 策略維持：

> **邏輯、contract、build、test、artifact 與 deployment 先拆開；Git repository 暫時不拆。**

當 frontend 與 RAG backend 已能獨立 checkout、建置、測試、部署、回滾，且連續兩個 release cycles 大多數變更不需協調發版時，再評估 physical repo split。到那時，拆 repo 應只是搬遷與 artifact distribution 變更，不應再是一場架構重寫。
