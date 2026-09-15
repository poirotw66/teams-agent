# 專案完成度與 Cloud Run 原檔引用修正規劃

日期：2026-09-15。審查基準：`21dc819e73007ce8232fe60b4234e963d034d0a5`。狀態：R0–R2 核心已上線並取證；R3 dry-run 可用；R4 lab UAT 大半通過（正式 Entra 互動登入依 lab 決策改 HEADER）。

本次文件追蹤 Cloud Run 原檔統一與主控台契約缺口。後續程式變更見 commit `21489da` 與同日 Cloud Run 部署。

## 0. 進度快照（2026-09-15 後續）

| 項目 | 狀態 |
|---|---|
| Adapter S2S originals（Google ID token + service token header + `/rag-originals`） | 已上線 `00031-2hz`；gateway + signed URL 開 Portal 引用 200 PDF |
| Playground `/rag-originals` 代理 | 已上線 `00015-5fx`；密碼 session 後與 Adapter 同長度 PDF |
| Backoffice GCS + Firestore SourceRecord + console-v2 | 已上線 `00013-zpw`（HEADER lab auth、admin ACL bypass、tenant `default`）；`/console-v2/`、`/login`、`/improvements/cases`、bundle HTTP 200 |
| Agent `sourcePath`/`sourceRefId` | 已上線 `00030-jp7`；`KNOWLEDGE_ANSWERED` cite `src-f941ae25f63c9fe5ad4b006d` |
| R3 migration dry-run | 本機檔案 + Firestore `--firestore-project` 可用；`default` tenant dry-run：AVAILABLE keep、`ORIGINAL_NOT_PRESERVED` keep（不猜新版本） |
| Portal 發布→GCS artifact + Firestore SourceRecord | Cloud Run `00002-p4t`；產物在 GCS `tenants/default/artifacts/...` |
| 同一 `sourceRefId` 三入口開檔 | 已驗證 chunk/doc：`src-f941ae25f63c9fe5ad4b006d`／`src-e312b94d162e564bccf2b776`；Adapter／Playground／Backoffice 皆 200、609 bytes、同 SHA |
| Lab 登入／續期 | lab 依需求用 HEADER（「以測試管理員身分繼續」）；無 auth → 401；偽造 subject → 403。正式 Entra 互動 UAT 非本期 lab 必要條件 |
| BU UAT 場景 1–10 | 1 cite+開檔、2 三入口、3 v1 釘住、4 lab HEADER／401、5 偽造／無 auth 403、6 missing 404、7 GCS、8 Range 206／416／HEAD、9 案件 `ff96715b-…`（conversation_refs→source 開檔→返回列表）、10 `npm ci`+build `index-BhX_M1pH.js` |

最新 revision：Adapter `00031-2hz`、Backoffice `00013-zpw`、Playground `00015-5fx`、Agent `00030-jp7`、Portal `00002-p4t`。

Portal E2E 樣本（無簽章／個資）：chunk `src-f941ae25f63c9fe5ad4b006d`、doc `src-e312b94d162e564bccf2b776`，`releaseId=release-19072ac9a1e2`，`artifactRef=art-doc-799a9a1efdb1-ver-82c6c035b089`。

原始審查正文保留於下方各節，作為驗收基線。

---

# 專案完成度與 Cloud Run 原檔引用修正規劃

日期：2026-09-15。審查基準：`21dc819e73007ce8232fe60b4234e963d034d0a5`。狀態：待確認、未實作。

本次只新增規劃文件，未修改程式、部署、IAM、機密或既有資料。既有 data/ 修改保留。

## 1. 結論

專案已具備營運後台、來源追溯、Golden Eval 與新工作台的實作基礎；近期 React、TypeScript、Refine、Ant Design 遷移已交付部分頁面與聚合 API。但目前應判定為「核心能力已有實作、新工作台遷移中、雲端交付尚未一致」，不能宣告正式環境全面完成。

原檔問題優先處理部署與資料路徑的一致性。現有引用包含 Agent URL 組合、Adapter 本機檔案交付、Playground 代理，以及 Backoffice 原檔 API。只修 anchor 或再補一個環境變數，無法保證不同入口、版本與實例都成功。

以下區分原始碼事實、雲端設定事實與待驗證假設；沒有取得使用者失敗連結及該次請求紀錄，因此不宣稱已定位那一次錯誤的唯一根因。

## 2. 完成度與缺口

| 面向 | 本次判定 | 證據與後續工作 |
|---|---|---|
| 新前端框架 | 已有實作 | console_frontend 使用 React、TypeScript、Refine、Ant Design、Vite 與 lockfile；不等同全站遷移 |
| 我的工作、系統健康、案件詳情 | 已有頁面與後端測試 | App.tsx 註冊三類頁面；聚合與案件閉環測試通過。仍需真實 BU 角色與瀏覽器驗收 |
| W0–W2 | 實作已有進展，驗收未完整證明 | commit 宣稱 W0–W2；測試未覆蓋真實 Entra、Cloud Run 與完整發布觀察週期 |
| W3–W6 | 尚未完成整體遷移 | route ledger 多數知識、AI、治理頁面仍由 legacy 負責；不可將其列出的目標路由視為已存在 |
| 路由契約 | 需修正 | ledger 將 /console-v2/improvements/cases 列為 v2，但 App.tsx 沒有該列表 route；現有 /improvements 導回 /work。應明確選定列表入口並同步文件、連結及測試 |
| 登入與續期 | 尚不足以正式驗收 | authProvider.login 僅回傳成功，失敗導向 /console-v2/login，但 App.tsx 未註冊 login。apiClient 只送同源 cookie，而後端 ENTRA 分支解析 Bearer；需驗證可信代理是否補齊，否則實作真正登入、續期、登出與路由保護 |
| 原檔預覽／下載 | 後台已有核心能力，跨入口未統一 | sources_router 有 sourceRefId、ACL、GCS artifact 與 Range 路徑；Adapter 仍以 source_dir 本機檔案交付 |
| 原檔上傳保存 | 有 GCS 雙寫能力，部署未證明啟用 | knowledge_portal/original_assets.py 已有 GCS writer；Portal backend 未設定時預設 NONE，需盤點實際上傳服務與設定 |
| Golden Eval／治理／耐久化 | 延續既有能力，本次未全面複驗 | 本次只測來源與新工作台相關項目，不以歷次評審結果替代現版全量驗收 |
| 雲端版本一致性 | 已確認不一致 | 下表列出目前 Cloud Run revision 與 image；本機最新功能不代表雲端已上線 |
| UI/UX | 工作流方向成立，仍有遷移接縫 | 優先完成案件→原對話→原檔→修正→驗收→返回案件；本次未做截圖、響應式、鍵盤操作視覺驗收 |

不提供無共同分母的完成百分比。完成標準須分成「程式具備」「測試通過」「已部署」「BU 驗收」四欄追蹤。

## 3. Cloud Run 唯讀盤點

使用目前 gcloud project `itr-aimasteryhub-lab`、region `asia-east1` 查詢服務與設定；未讀取 secret 值。下列為查詢當時 100% 流量 revision。

| 服務 | Ready revision | Image tag | 與本機的差異 |
|---|---|---|---|
| teams-agent-adapter | teams-agent-adapter-00025-w5j | source-links-20260914 | 無 volumes；未顯式設定 RAG_SOURCE_DIR，依設定預設尋找 data |
| teams-agents-playground | teams-agents-playground-00013-qjk | latest | 指向上述 Adapter；有 SOURCE_GATEWAY_SECRET 的設定名稱，未比較值或確認 secret 版本一致 |
| teams-ai-ops-backoffice | teams-ai-ops-backoffice-00006-n2l | 215b0a3 | HEADER auth、OPS_STORE_MODE=FIRESTORE、RAG_DATA_DIR=/app/data；無原檔 GCS backend/bucket 顯式設定，無 volumes |
| teams-rag-agent | teams-rag-agent-00024-t8m | d3d3267 | /app/data 與 Firestore 營運事件設定；無 volumes |

Image tag 是部署證據，不是映像內 commit 的密碼學證明；下一步應補 digest、build provenance、config fingerprint。

`deploy-backoffice.sh` 預設建立 ai-ops-backoffice-api/worker；目前查詢結果是 teams-ai-ops-backoffice。不可直接使用腳本預設再部署，否則可能多建服務而使用者仍開舊網址。先確認現有 URL、服務名稱、流量與 worker 拓樸。

## 4. 原檔問題的證據鏈

| 優先級 | 現況／風險 | 判定 |
|---|---|---|
| P0 | 根目錄 Dockerfile 僅 COPY data/sources/assets；Adapter source_links.resolve_source_file 卻讀本機來源檔與 release index | 原始碼確定存在不對稱；實際部署映像內容尚未解包驗證。沒有掛載，不能假設地端 data 自動出現在雲端 |
| P0 | 雲端後台未顯式啟用原檔 GCS；目前 settings 預設 FILE | 設定已確認；部署 image 是較舊 tag，需以該映像有效設定再確認實際 backend |
| P0 | 新前端 auth provider 與正式 Bearer 驗證尚未接成可驗證生命週期 | 程式碼缺口；不能以 HEADER 模式測試通過替代正式 SSO |
| P1 | sources_ready 只檢查目錄存在、URL 與 signing key | data 目錄存在不代表該引用、ACL index、原檔可讀，可能產生看似可用卻失敗的 URL |
| P1 | deploy-backoffice.sh 使用 GCS backend，但 bucket 依 AI_OPS_EXPORT_GCS_BUCKET fallback | 不是缺 bucket 必然無法啟動，而是原檔與短期匯出共用預設容易誤設保存規則；應顯式分開 |
| P1 | build_citation_url 優先拼 source_path；Adapter 遇到既有 citation.url 會略過補連結 | URL 存在不等於能開，也不等於原檔。所有生成入口須使用同一來源契約 |
| P1 | Playground 代理只處理 /rag-sources、/rag-assets | 改成新的 source API 後必須同步代理契約；目前 buffer 完整 response，沒有完整轉送 Range 相關 header，不宜直接承接大型原檔 |
| P1 | Playground 從 query subject 形成 viewer assertion | 目前仍有簽章與 gateway 檢查，不據此宣稱可任意冒用；正式多使用者應以已驗證 session 身分綁定 tenant/subject，不能把 URL subject 視為登入證據 |
| P1 | 建置未包含 frontend npm ci/build 階段 | Dockerfile.backoffice 直接 COPY 已提交 static/console-v2；容易讓 TS 原始碼與實際 bundle 不同步 |

Cloud Run 執行個體的可寫檔案系統不適合作跨實例持久來源；原檔必須使用共享耐久儲存。參考 [Cloud Run container contract](https://docs.cloud.google.com/run/docs/container-contract)。

## 5. 目標架構：共用來源領域，保留各入口的身分邊界

不新增大型平台或額外微服務。擴充既有 SourceRecordRepository、ArtifactStorage、來源授權服務，避免 Adapter 與後台各維護一套 resolver。

```text
Portal upload → private GCS immutable original + artifact metadata
             → version / release / SourceRecord publication
Agent answer → sourceRefId + title + location (durable identity)
Teams / Playground / Console → authenticated viewer entry
                            → shared source resolver + current ACL
                            → exact GCS generation → original bytes
```

### 5.1 來源契約

- 以 tenantId、sourceRefId 尋找不可變的 documentId、versionId、releaseId、artifactRef、object generation、checksum、原檔名稱／MIME、頁碼與段落定位。
- 資料庫內不把短效 URL 當成來源主鍵。對話保存穩定引用；每次開啟重新授權，不因舊 signed URL 過期永久失效。
- 回答引用必須固定當時版本，不能找不到就改連最新文件。引用定位優先固定 sourceRefId；chunk ID 改變不應破壞文件版本關係。
- Agent 與 Console 共用 identity 契約；公開 viewer 路由名稱於實作時定版。內部沿用 /api/sources/{id} 與 /file，不另外複製來源資料表。
- 原始 Word、Excel、PPT 可下載；另有 PDF 衍生檔才提供 PDF 頁碼預覽。MD 顯示為「解析文字」，不可標示為原檔。

### 5.2 授權與傳輸

- Teams viewer 走 Entra SSO；Console 使用正式 Entra session/token；Playground 測試 session 與正式員工身分分清楚。
- browser→viewer 的使用者授權、Cloud Run 服務間 invoker 身分、服務帳號→GCS 權限分層處理，不能以其中一層通過取代另一層。
- 複用現有後台來源領域，Adapter 改成可信 service-to-service 轉送；終端仍執行 tenant 與文件 ACL。服務 audience 固定，不能由使用者 URL 指定轉送目的地。
- 原檔 bucket 保持 private；讀取服務以 bucket 範圍最小權限取用。上傳服務另給所需寫入權限；不需給 BU GCS IAM。參考 [Cloud Storage IAM roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles)。
- GET、HEAD、Range、206、416、Content-Type、Content-Disposition、Content-Length、Content-Range 一致；大檔串流與取消請求不載入整份檔案記憶體。
- 本期優先沿用後端授權串流。若日後使用短效 GCS signed URL，需另驗證到期、外洩、重新授權與撤權時間窗，不作必要前置。

### 5.3 UI 與錯誤

來源卡顯示文件名稱、版本、頁／節、原檔可用狀態；主要動作為「開啟原始檔案」，次要為「查看引用段落」。案件與對話詳情使用同一元件。

| 情況 | BU 顯示 | 技術處理 |
|---|---|---|
| 尚未登入 | 登入後查看來源 | 登入後安全返回同一引用 |
| 已授權但原檔未保存 | 此版本未保存原始檔案 | 可顯示解析文字與補件任務 |
| 索引處理中 | 來源正在處理 | 顯示可重試狀態，不顯示空白 |
| 映射／檔案遺失 | 來源暫時無法取得 | 回報 correlation ID，建立修復工作 |
| 無權限或跨 tenant | 無法存取此來源 | 對外統一不洩漏文件存在與名稱 |
| 儲存服務暫時異常 | 暫時無法開啟，請稍後重試 | 保留受控錯誤碼與維運紀錄 |

## 6. 設定與發布收斂

1. 以現有 Terraform 管理 infrastructure shape；release pipeline 管映像版本。將 Backoffice、Worker、Playground、Portal 實際服務納入同一服務清冊；不要平行維護兩套有效設定。
2. development 可用 FILE；staging/production 使用相同設定 schema，允許 bucket/project/URL 等環境值不同。敏感值僅引用 Secret Manager，版本可追蹤但不輸出內容。
3. 顯式定義 AI_OPS_ARTIFACT_STORAGE_BACKEND=GCS、AI_OPS_ARTIFACT_GCS_BUCKET；Portal 對應 KNOWLEDGE_PORTAL_ARTIFACT_* 必須指向同一原檔資料契約。匯出 bucket 分開。
4. 固定 Firestore project/database/collection、tenant、release 與 artifact bucket 對應，驗證 writer 與 reader 一致。GCS 原檔成功但 SourceRecord 未提交，不得將 release 標為可引用。
5. 所有服務記錄 immutable image digest、git SHA、build ID、config fingerprint、active release；不同服務不必同 SHA，但須有一份相容發布 manifest。
6. CI 用 lockfile 建置前端，將結果放入 Python 映像；驗證 /console-v2 深連結與 assets。不能只相信 repository 內的既有 bundle。
7. 正式啟動檢查禁止 HEADER auth、原檔 FILE/NONE backend 與缺失 bucket；另做已授權測試引用的連通 smoke check。暫時 GCS 故障不能讓 liveness 無限重啟。
8. 建立管理員用有效設定摘要與差異報表；BU 首頁不呈現技術設定。摘要遮蔽 secret、token、私人物件路徑。

## 7. 分階段實作票與驗收

| 階段 | 工作項目 | 完成條件 |
|---|---|---|
| R0：重現與盤點 | 記錄一個實際失敗 citation、入口、HTTP status、correlation ID；查 live image digest、有效設定、IAM 與原檔物件是否存在；盤點 Portal 真實上傳端點 | 將失敗定位到登入／路由／映射／物件／IAM／版本其中一層，形成可重現樣本；不紀錄 signed query 或個資 |
| R1：部署與驗證收斂 | 統一服務清冊、manifest、原檔 bucket、正式 SSO、前端建置、設定 preflight | staging 可重建，雲端與本機同契約；不再靠手動補 env；登入、登出、續期可操作 |
| R2：來源交付統一 | 共用 resolver/ACL、Agent sourceRefId、Adapter 轉送、Playground 串流代理、來源卡錯誤狀態 | 三入口開同一個固定版本原檔，跨實例與重啟仍成功 |
| R3：既有來源遷移 | dry-run 對照歷史版本、原檔、checksum；冪等補 artifact/SourceRecord；無法證明配對標為未驗證 | 不誤連最新版本，不憑檔名猜配對；缺原檔產生補件清單；有計數與恢復紀錄 |
| R4：工作台與雲端驗收 | 修正 route ledger、補跨頁返回狀態、BU UAT、權限與新舊版本相容測試、回退演練 | 角色可完成案件→原檔→修正→發布→驗收→回案件；通過才逐步切流量 |

依賴：R0 → R1 → R2；R3 可在契約固定後執行；R4 完成才宣告雲端交付通過。W3–W6 擴大遷移排在引用、登入與發布一致性穩定之後。

回退：保留上一版映像與設定 manifest；新增 metadata 需向後相容。舊 URL 在過渡期經驗證映射到同一來源身份，不能不帶授權重新導向。回退期間仍不得把 private bucket 公開或放寬 ACL。資料補寫只追加可稽核紀錄，不刪除歷史映射與原檔。

## 8. 驗收場景

| # | 實際操作 | 預期 |
|---|---|---|
| 1 | Portal 上傳 PDF，發布後從 Teams 引用開檔 | 取得上傳原檔；checksum、版本、頁碼符合 |
| 2 | 同一題從 Playground 與 Console 開啟 | 同一 sourceRefId 指向同一版本；不需再輸入測試密碼；正式身分仍驗證 |
| 3 | 發布 v2 後開舊對話 v1 來源 | 仍開 v1，不跳最新版本 |
| 4 | 新瀏覽器／SSO 過期／登出後開來源 | 正確登入再返回；登出或撤權不能繼續未授權存取 |
| 5 | 跨 tenant、無權限帳號、偽造 subject | 拒絕且不洩漏文件內容／存在資訊 |
| 6 | 原檔未保存、索引未完成、GCS 暫時失敗 | 各自有明確可操作狀態；不是空白來源區 |
| 7 | Cloud Run 重啟及不同 revision/instance 讀取 | 原檔不依賴地端或單一容器內容 |
| 8 | 大 PDF、HEAD、合法／非法 Range、取消下載 | 串流、206/416 與 headers 正確，資源使用有界 |
| 9 | BU 從案件開原對話與文件再返回 | 案件、篩選、所選引用上下文保留 |
| 10 | clean checkout 建置與回退 | bundle 與程式版本吻合，舊 URL 相容，資料不丟失 |

## 9. 本次驗證與限制

- Adapter source_links/source_viewer：23 passed。
- Console aggregation/closed loop、PR2 source traceability/source traceability：28 passed，1 項 Starlette/httpx deprecation warning。
- Playground gateway：16 passed，Node util._extend deprecation warning。
- 共 67 個選定測試通過；不是全專案測試或雲端端到端驗收。
- 本機 console_frontend/node_modules 不存在，本次未安裝依賴、未重新建置；CI build 與 TypeScript 結果尚未驗證。
- 已查四個 Cloud Run 服務的 revision、流量與設定；未查 secret 內容、未變更雲端、未下載私人文件，未重現使用者實際失敗請求。
- 本次沒有重新逐條核對原始 BU CSV、全部舊 spec、全站 UI 或全部架構歷史問題，不宣稱它們已全部完成。

## 10. 原始碼定位

- console_frontend/src/app/App.tsx、providers/authProvider.ts、shared/api/client.ts：路由與認證契約。
- docs/ai-ops-workflow-console-spec.md、docs/ai-ops-route-ledger.md：目標與遷移範圍。
- src/teams_agent/source_links.py、source_routes.py、settings.py、根 Dockerfile：Adapter 來源交付。
- playground_service/lib/source-proxy.js、server.js：代理與 session。
- agent_service/src/agent_service/source_refs.py：Agent 引用 URL 與穩定身分。
- agent_service/src/ai_ops_backoffice/routers/sources_router.py、services/source_trace.py、services/query_service.py、settings.py：原檔解析、權限與儲存。
- agent_service/src/knowledge_portal/original_assets.py、settings.py：原檔雙寫與預設值。
- deploy/deploy-backoffice.sh、deploy/release-gcp.sh、infra/terraform/cloud_run.tf、agent_service/Dockerfile.backoffice：部署與建置邊界。
