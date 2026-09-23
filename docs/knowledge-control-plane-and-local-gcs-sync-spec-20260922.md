# 雲端正式知識來源與地端測試快照同步規格

> 狀態：實作規格，非已完成功能。範圍限知識庫、服務目錄與 RAG；工單、對話及其他 Console 營運資料不在本次搬遷範圍。

## 1. 目標與邊界

- 地端與雲端都以 `/console-v2/` 為唯一知識操作介面，但**操作環境必須分明**：雲端 Console 管理正式 Portal；地端 Console 預設管理本機測試工作區。需要從地端操作正式雲端發布時，必須明確切換至雲端連線並通過正式身分、RBAC 與審核，不得把地端測試發布誤送至正式環境。
- Firestore 是雲端正式文件版本、審核、服務目錄工作流程、release 狀態及 active release 指標的權威來源；私有 GCS bucket 是雲端原檔、圖片與不可變 release artifact 的權威來源。地端保有獨立的測試資料與索引，並可從雲端正式 release 做**單向同步**；本機測試變更不自動回寫雲端。
- 地端 Agent 設為 `KNOWLEDGE_RELEASE_STORE_MODE=GCS` 時，GCS 表示**同步的上游來源**，不是每次地端問答的即時資料庫。同步器把雲端 active release 的問答所需 artifact 拉到指定本機資料夾並驗證；Playground 的地端 Agent 從本機快照載入 RAG，問答期間不必連 GCP。
- 雲端發布不等於地端立刻生效。地端自動或手動同步後，顯示來源 release、同步時間與本機 loaded release；尚未同步或雲端暫時不可用時，地端仍可用最後一版已驗證的本機快照**做測試**，但必須明顯標示「可能落後雲端」，不得宣稱與正式環境一致。

```text
雲端 console-v2 → 雲端 Backoffice／Portal → Firestore + GCS → 正式 Agent
                                              │
                                              └→ 單向同步已發布 release
                                                       ↓
地端 console-v2 → 本機測試工作區 → 本機鏡像／sandbox → 地端 Agent → Playground
                         └─ 明確切換雲端連線時，才操作正式 Backoffice API
```

## 2. Console 與發布流程

1. 將草稿版本編修、原檔與圖片管理、audience／ACL、驗證與試問、審核差異及決議、發布、release 比較、Agent 生效狀態、同步重試及回滾完整納入 `console-v2`。舊 `/knowledge-ui` 在過渡期只導向對應的新頁面，不保留第二條獨立寫入流程。地端與雲端使用相同 UI，但地端測試工作區和雲端正式工作區使用不同後端與明顯不同的環境標示。
2. 地端測試操作只寫本機 sandbox。地端 Console 若切換雲端正式工作區，所有操作都經雲端 API、正式個人身分、伺服器端 RBAC、職責分離及稽核；不得以瀏覽器自填的 `X-Backoffice-*` header 或 demo／relaxed workflow 取得正式發布權限。此安全門檻完成前，不開放地端正式寫入。
3. 企業服務目錄是獨立治理資料，包含服務 ID、正式名稱、別名、負責單位、適用對象及所連結的文件版本。每個可發布項目至少連結一份已核准且可檢索的文件。目錄經草稿、審核與發布，與文件、索引、ACL 一起封裝在**同一個**不可變 release；不得在 Python 規則、prompt 和文件中各自維護另一份權威清單。
4. 發布使用既有 release 狀態機及 gate。每次操作記錄操作者、理由、idempotency key、預期舊 active release、目標 release 與結果；並發發布或回滾時，過期請求回 `409`，不得覆蓋較新的操作。

## 3. GCS 模式的地端同步契約

### 3.1 設定與檔案範圍

沿用 `KNOWLEDGE_RELEASE_CACHE_DIR` 作為**指定同步根目錄**，預設為 `RAG_DATA_DIR/knowledge_cache`；不新增意思重疊的目錄環境變數。GCS 模式另需 GCS bucket／prefix、Firestore project／database、tenant，以及具唯讀權限的地端同步身分。提供 `KNOWLEDGE_RELEASE_SYNC_INTERVAL_SECONDS`，預設 `300` 秒，限制為正整數，並提供 Console「立即同步」。同步在背景執行，**不放在 Playground 的每次問答路徑上**。

同步目錄採 `<KNOWLEDGE_RELEASE_CACHE_DIR>/tenants/<tenantId>/releases/<releaseId>/`，且只由同步器管理；本機草稿與 sandbox release 必須放在**另一個**目錄，不能修改鏡像。預設只同步問答所需的 manifest、`index/chunks.json`、引用的 `sources/`、回答會用到的 `assets/`、服務目錄及 ACL artifact；原始 PDF／DOCX 等 `original/` 不預設下載，查看原檔走授權 API。不得把 GCS bucket 的全部物件下載到地端，也不得下載未發布的草稿或其他 tenant 的資料。既有 `<cache>/<releaseId>` 格式僅供過渡讀取；完成新版本驗證後切換至 tenant-scoped 目錄。

目前 GCS 載入路徑僅下載 manifest 與索引；實作時須擴充 release manifest 的**runtime artifact inventory**（相對路徑、generation、大小、SHA-256），並讓發布端在最後寫入 manifest 前列出完整問答必需物件。舊 manifest 缺少 inventory 時，不得宣稱「問答快照已完整同步」；必須經受控重建／重新發布，或明確標示舊版僅有索引。服務目錄與索引的 schema 版本也需由 manifest 固定。

### 3.2 自動同步與切換

1. 啟動時、背景輪詢及手動同步時，從 Firestore 讀取雲端 active release 指標與目標 release 紀錄；確認 tenant、`PRODUCTION` purpose、狀態、bucket、manifest generation、索引 generation 及 hash。`KNOWLEDGE_ACTIVE_RELEASE_ID` 可讓本機測試釘選已同步的指定版本；釘選時仍可下載新版本，但不得自動切換 Playground 的 loaded release。
2. 目標版本不同時，在同步根目錄內建立該版本的暫存目錄，依 manifest inventory 及固定 generation 下載缺少的物件；相同 release 的已驗證檔案可重用。限制路徑只能落在 tenant／release 目錄下，拒絕 `..`、絕對路徑、符號連結與跨 tenant 參照；下載檔案不賦予執行權限。
3. 核對每個物件的大小與 SHA-256、manifest 本身的固定 generation、索引統計、embedding 模型／維度、ACL 與服務目錄引用。任何缺檔或不符都使**整個目標 release 失敗**，不得以混合新舊檔案繼續。
4. 驗證完成後，將暫存目錄原子更名為唯讀鏡像目錄。若 Playground 選擇「跟隨雲端鏡像」，離線建立新索引、來源映射、服務目錄及知識後端，再以單次快照指標切換；若選擇「釘選版本」或「本機 sandbox」，只更新鏡像，不改變正在測試的版本。進行中的請求維持其原先固定的 release；新請求使用目前明確選定的已驗證本機快照。同步程序以單實例鎖／去重避免重複下載。
5. 本機只清理由同步器建立、未被任何進行中請求或釘選測試引用的舊鏡像；保留最近兩個已驗證 release 供診斷。不得清理使用者指定根目錄下的其他檔案，也不得把本機鏡像或 sandbox 自動回寫 GCS。雲端正式回滾更新 Firestore active 指標；地端跟隨模式於下次同步後切換，本機釘選／sandbox 模式保持原樣並顯示差異。

### 3.3 不一致與故障政策

地端是**測試環境**：每次問答只讀目前選定的本機已驗證快照，不讀 Firestore 或 GCS。雲端控制平面暫時不可用、同步失敗或新版本未下載完成時，保留最後一版已驗證本機快照供測試，顯示同步失敗與版本落後；不得自動退回未驗證的 `FILE` repository 或 bundled JSON，也不得顯示「與正式環境相同」。沒有任何已驗證本機快照時，知識問答不可用。此政策不改變雲端正式 Agent 既定的 fail-closed 要求；兩者不得共用含糊的環境旗標。

同步器應回報 `cloudActiveReleaseId`、`mirroredReleaseId`、`loadedReleaseId`、`selectionMode`（`FOLLOW_CLOUD`／`PINNED`／`LOCAL_SANDBOX`）、`syncState`（`IN_SYNC`／`DOWNLOADING`／`VALIDATING`／`FAILED`／`CONTROL_UNAVAILABLE`）、`lastSuccessfulSyncAt`、檔案數及驗證 hash。`console-v2` 將「雲端最新」、「本機已同步」與「Playground 正在使用」分開顯示；只有三者相等且驗證成功，才顯示「目前與雲端正式知識版本一致」。本機有檔案不構成同步或生效證明。

## 4. Agent 路由與回答

- 工單、轉人工等確定性意圖仍優先。服務目錄命中只用來否決過早的 `NON_IT`，不直接強制走 `KNOWLEDGE` 或產生答案；不確定的企業用語做受 ACL 限制的檢索。
- 只有目前已載入 release 的可信來源足以支持答案時才回答；找不到來源時說明無法確認、請求澄清或轉人工，不把「查無依據」誤寫成「不屬於 IT」。
- 每次回答與稽核記錄 loaded release ID、`selectionMode`、同步時間、服務目錄版本、檢索來源及 ACL 決策，便於追查地端與雲端的差異。本機 sandbox 答案不得標記為正式雲端答案。

## 5. 遷移、驗收與實作順序

1. 先完成正式認證、RBAC、Portal 部署設定稽核及 GCP 唯讀身分。盤點本機與雲端文件 ID／內容 hash；本機獨有內容只匯入雲端草稿，再審核發布，不自動覆蓋雲端資料。
2. 補齊 `console-v2` 與服務目錄治理，擴充 release inventory；確保 GCS manifest 最後上傳、release 物件不可覆寫，並以既有 gate 發布。
3. 實作地端 GCS 問答 artifact 單向同步、驗證、跟隨／釘選／sandbox 選擇、原子切換與狀態 API，再切換地端 Agent 設定。本機測試工作區保留獨立的 `FILE` 資料與 release，但不能在「雲端鏡像」模式下靜默 fallback。`chunks.json` 可以繼續作為 GCS 內受版本控制的索引 artifact；是否換向量資料庫另依規模、延遲與成本實測決定。
4. 驗收：地端與雲端 Console 可看到相同雲端 active release，但地端明確另顯示 mirrored 與 loaded release；地端鏡像的 manifest、索引、來源、回答所需圖片及服務目錄與 GCS 指定 generation／hash 一致。雲端發布後，跟隨模式於背景同步完成時無須重啟即可追上；釘選與 sandbox 模式不得被覆蓋。GCP 中斷時地端可繼續使用最後已驗證快照並標示落後；沒有快照則拒絕知識問答。另測失敗下載、校驗錯誤、磁碟不足、同時發布、ACL、跨 tenant 與舊版進行中請求。
5. 路由回歸涵蓋座位搬遷各種說法、首輪／有上下文、TurnPlanner 開／關、工單查詢、混合問題與真正範圍外問題。已發布且有權限的服務問題不得在檢索前被錯拒；沒有證據不得編造答案。

## 6. 現況差距

> 更新（2026-09-22，**§5.4 sync + §5.5 live routing 已過；整體目標仍未完成**）：ADC 對 `itr-aimasteryhub-lab` 可用。active／mirrored／loaded=`release-f4aaa7aada1a`（inventory 完整、`alignedWithCloud=true`）。§5.5 live `/agent/chat` **18/18** + TurnPlanner ALL side **5/5**（見 §6.3）。**仍缺且阻擋整體完成**：live Entra 正式寫入端到端（§6.1）；次要：live Firestore 多實例 catalog 草稿、雲端正式路徑打通後清理規則／prompt 殘留權威清單（§6.2）。

現有 `KNOWLEDGE_RELEASE_STORE_MODE=GCS` 已能依 Firestore release reference，依 runtime inventory 將問答所需 artifact 鏡像至 tenant-scoped cache，並在 FOLLOW_CLOUD 於完整 QA 快照驗證後熱切換 loaded release（PINNED／LOCAL_SANDBOX 拒絕覆寫）。缺 inventory 的舊 manifest 標 `indexOnlyMirror`／`behindCloud`，不得標示 aligned；校驗失敗為 `FAILED` 且不 silent fallback 至 FILE／bundled。

### 6.1 §2 正式寫入安全門檻（部分完成）

- **已落地（fail-closed）**：Backoffice 生產環境預設拒絕瀏覽器 `X-Backoffice-*`（需 `AI_OPS_BACKOFFICE_ALLOW_HEADER_AUTH` break-glass）；Portal 生產環境同樣拒絕瀏覽器 `X-Portal-*`（需 `KNOWLEDGE_PORTAL_ALLOW_HEADER_AUTH`），並強制 `effective_relaxed_workflow() == False`。正式路徑應使用 Entra 或簽名 BFF delegation。
- **已落地（工作區分離 + 切換 UX + 重啟持久化）**：`AI_OPS_KNOWLEDGE_WORKSPACE_MODE`（`LOCAL_SANDBOX`／`CLOUD_FORMAL`）為 bootstrap 預設。`GET/PUT/DELETE /api/knowledge-workspace`（SYSTEM_ADMIN／KNOWLEDGE_ADMIN）：PUT 寫入 runtime + `<OPS>/knowledge_workspace.json`；`create_app` 啟動時若檔案有效則覆寫優先於 env；DELETE 清除覆寫並回到 env 預設。console-v2 **Header Segmented** 與知識頁 banner 可切換／重設（「覆寫」標示）。切至 CLOUD **不**自動開放正式寫入（ENTRA + 關閉 relaxed + `AI_OPS_KNOWLEDGE_CLOUD_FORMAL_WRITES`）；capabilities 剝除 formal write caps；持久化**不**繞過 formal gate。毀損覆寫檔 fail-closed 回 env／in-process 預設。
- **仍缺**：live Entra 正式寫入端到端驗收。

### 6.2 §2.3 獨立服務目錄治理

- **已落地（FILE + FIRESTORE + SoD 分離）**：Portal catalog API + BFF + console-v2 UI；可插拔 draft store（FIRESTORE 多實例／FILE 本機）。Approve 使用獨立能力 `knowledge.catalog.approve` 與 `ensure_can_approve_catalog`（不等於 `knowledge.publish`／文件發布）；submitter≠approver；非 relaxed 時另擋核准者＝連結文件最後發布者。PRODUCTION finalize 可強制 APPROVED catalog（`KNOWLEDGE_PORTAL_REQUIRE_APPROVED_CATALOG` 或 `require_dual_approval` + 非 relaxed）。
- **已落地（routing 權威）**：Agent `service_scope_evidence` 載入 release `catalog/service_catalog.json` 時以該 artifact 為唯一別名權威（不再合併硬編碼 static）；static 座位別名僅作無 overlay 的 FILE／sandbox 後備。
- **已落地（live GCS inventory sync + 進程熱切換）**：§6.4；Agent `POST /admin/knowledge-sync` 將 loaded 從 index-only 切至 `release-f4aaa7aada1a`。**仍缺**：live Firestore 多實例目錄草稿驗收；權威清單殘留於規則／prompt／文件需靠雲端正式路徑打通後清理。

### 6.3 §5 驗收與 §5.5 路由

- **已落地（偽 GCS 模擬）**：`test_knowledge_release_sync_acceptance.py` 覆蓋三欄對齊、PINNED／LOCAL_SANDBOX、失敗保留快照、**ENOSPC mid-download fail-closed（不 partial promote）**、無快照則知識問答 fail-closed。
- **已落地（§5.5 無 live Agent）**：`test_service_scope_evidence.py` 涵蓋座位別名／準則／聯繫單變體、TurnPlanner ALL／OFF（首輪與有上下文）、工單 hybrid、混合問題、真正範圍外、NO_KNOWLEDGE 不編造。
- **已落地（live 三欄對齊）**：真實雲端 active／mirrored／loaded = `release-f4aaa7aada1a`（Agent `/admin/knowledge-status`）。
- **已落地（§5.5 live Agent + ACL，2026-09-22）**：對 loaded `release-f4aaa7aada1a`（`qaSnapshotComplete`／`alignedWithCloud`）跑 live `/agent/chat`：**18/18 PASS**（座位別名變體、VPN／Gitlab 已發布服務、工單 QUERY、座位+工單 hybrid、混合、真 OOS、NO_KNOWLEDGE 不編造／不誤標 NON_IT、有上下文座位 follow-up）。證據：`data/eval/reports/spec55-live-routing-release-f4aaa7aada1a.json`。主 stack `TURN_PLANNER_MODE` 預設 **OFF**（非 chat API 可切）；**ALL** 以同 release side Agent `:8010` 另驗 **5/5 PASS**（`spec55-live-turnplanner-ALL-release-f4aaa7aada1a.json`）。工單 QUERY 需 trusted requester（`entraObjectId`+email+displayName）；OOS 以「不屬於公司 IT 支援範圍」文案回覆且 `issueResults` 可為空。**未改閘門**；本輪無須修 code。

### 6.4 Live GCS／正式路徑 ops checklist（無密鑰）

**已寫入（gitignored，勿提交）**：`agent_service/.env.knowledge-gcs.local`。`start.sh` 偵測到該檔會匯出變數給 Agent。亦可：

```bash
set -a && source agent_service/.env.knowledge-gcs.local && set +a && ./start.sh
```

| 用途 | 環境變數 | lab 已知值（非密） |
|------|----------|-------------------|
| 啟用 GCS 鏡像模式 | `KNOWLEDGE_RELEASE_STORE_MODE` | `GCS` |
| Bucket／prefix | `KNOWLEDGE_RELEASE_GCS_BUCKET`／`…_PREFIX` | `itr-aimasteryhub-lab-knowledge-releases`／`knowledge-releases` |
| Tenant | `KNOWLEDGE_RELEASE_TENANT_ID` | `default` |
| Cache | `KNOWLEDGE_RELEASE_CACHE_DIR` | `../data/knowledge_cache` |
| 選擇模式 | `KNOWLEDGE_RELEASE_SELECTION_MODE` | `FOLLOW_CLOUD` |
| Firestore | `KNOWLEDGE_RELEASE_FIRESTORE_*` | project `itr-aimasteryhub-lab`，database `(default)`，config `knowledge_portal_config`／releases `knowledge_releases` |
| 地端身分 | ADC | 本機已驗證可讀／可寫 GCS＋Firestore（principal `weicyun@cathayholdings.com.tw`；scratch upload／doc 後刪除） |

**一輪 sync 證據（2026-09-22，對齊後）**：active=`release-f4aaa7aada1a`（前版 `release-713b5b02dfc2` 已 ROLLED_BACK）；tenant 鏡像含 catalog／ACL／inventory；`qaSnapshotComplete=true`、`alignedWithCloud=true`、三欄 ID 一致（FOLLOW_CLOUD）。重建路徑：ADC 寫入 lab GCS＋Firestore（非 LOCAL_SANDBOX→GCS；雲端 Portal 對本機帳號無 `run.invoker`）。後續常態發布仍應走已部署 Portal finalize（需先部署含 inventory 的 Portal 映像）。

驗收觀察：`GET /api/agent/knowledge-status` 的 `cloudActiveReleaseId`／`mirroredReleaseId`／`loadedReleaseId`／`alignedWithCloud`／`indexOnlyMirror`；Console Releases「立即同步」。
