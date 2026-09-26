# Vertex AI 遷移 P0 未決關卡（2026-09-24）

> 狀態：應用／基礎設施契約已依規格審計並補齊可自動化缺口；**lab Cloud Run 已切到 VERTEX_AI revision（無 Gemini key mount）**。  
> Lab Agent 現行工作樹映像為 `teams-rag-agent-00054-677`。Lab active knowledge pointer 已切到 Vertex-provenance release `release-8535419976b4`。`deploy-gcp.sh` 對既有 Agent 改走 image + `--update-env-vars`，不再覆蓋 live PORTAL／release pointer／File Search。3-case Vertex subset 與 `release-713b5b02dfc2` 基線的比較**無效**（不同 release；未重跑、未改 judge）。project-level `aiplatform` DATA_ACCESS `auditConfigs` **已啟用**；`_AllLogs` 已引用 Agent SA、Converter SA 與 Backoffice SA `data_access`（見下方）。live PDF Vision：converter `00008-zrb` 已 pin `GEMINI_MODEL=gemini-3.8-flash`（VERTEX_AI／`us`／無 key）。`tests/fixtures/pdf-vision/` 四份最小 fixture（selectable／scan-like／table／mixed）`POST /api/v1/convert-pdf` 皆 HTTP 200，markdown 含標記原文，`generateContent` 對 `gemini-3.8-flash` 回 200，**沒有** 404。Portal 匯入 `scan-like.pdf` HTTP 200、`VERTEX_AI`，未切 release。156-case frozen L3 **已跑完**（853：answer 92.95%、citation P 95.62%、ACL 0、Total P95 4667 ms）；與其他 release 全量基線比較**無效**。Production 未切。**不要**把舊 Developer API release 當成 Vertex 向量；Vertex 載入缺 provenance 的舊索引必須拒絕。
>
> **Production 尚未切換。** Lab／POC Agent／Portal／Converter／Backoffice 已是 VERTEX_AI。`pdf_converter_image` **已 pin** live `00008-zrb` digest `sha256:6c00f9f11a93…ace683a3`（example + 本機 tfvars）。converter targeted plan 現為 **No changes**（`lifecycle.ignore_changes` 含服務層 `scaling`）；**未套用**。完整 Terraform plan 的 BigQuery／ingestion-bucket drift **未套用**。
>
> 審計後仍屬程式契約、且已關閉的缺口：Teams Adapter／Backoffice worker／golden baseline 不再整份 `load_dotenv` 匯入 Gemini key；Backoffice Cloud Run 亦固定 `VERTEX_AI` 並授予 `roles/aiplatform.user`。`VERTEX_AI_PROJECT` 未設時，僅在 `GCP_PROJECT_ID`／`GOOGLE_CLOUD_PROJECT` 收斂成單一明確值才可對映；location 仍必須顯式設定。File Search 生產 `genai.Client` 在建構當下再次要求 Developer API 與非空 key；File Search 腳本／`file_search_supported()` 會 peek `.env` 後端，Vertex 不得偷偷用 key。Vertex 載入舊 release 缺 provenance 時拒絕，不以稀疏搜尋掩蓋。PDF Vision 匯入標示 `conversion_gemini_backend`。評測報告寫入 backend／project／location。操作手冊：[vertex-ai-operations-runbook-20260924.md](./vertex-ai-operations-runbook-20260924.md)。
>
> Vertex SA smoke：**`scripts/vertex_sa_smoke.py`**（實作於 `agent_service/src/agent_service/vertex_sa_smoke.py`）。預檢要求程序環境已有明確 project 與 chat／embedding location，並在偵測到 `GEMINI_API_KEY`／`GOOGLE_API_KEY` 時拒絕。不載入 `.env`。通過預檢後才用 `build_chat_model`／`build_embeddings` 發真實請求；略過與失敗皆非零結束。
>
> P3 plan 摘錄（無密鑰值）：[vertex-ai-p3-terraform-plan-evidence-20260924.md](./vertex-ai-p3-terraform-plan-evidence-20260924.md)

## 未決決策

| 關卡 | 建議 | 未執行原因 | 關閉前不可做的事 |
|---|---|---|---|
| File Search 選項 | 選 A：Vertex 部署只要求 HYBRID，Developer API 保留 File Search | **維持規格預設選 A**。本回合已依選 A 停用 Vertex sync／parity | 若 BU 改選 B，停止 Vertex 發佈並另寫 Vertex AI Search／RAG Engine 方案 |
| 資料處理區域 | Lab 已簽署：`us`（chat／embedding／PDF 皆同）。不可因 Cloud Run 在 `asia-east1` 就改寫模型 location | **已簽署 `us`**，已寫入 `agent_service/.env` 與 `infra/terraform/terraform.tfvars`。Vertex 專案亦已簽署為同 lab `itr-aimasteryhub-lab`（顯式值，不從 `project_id` 推導） | 未再簽署其他區域前，不要改寫成 `eu`／`global`／`asia-east1` |
| PDF Vision 是否與 Agent 同日切換 | 建議是；分階段時必須明確停止 Vision 匯入 | Converter／Portal 已同日切 VERTEX_AI 且保持 `gemini_vision`。2026-09-24 env-only 更新把 `GEMINI_MODEL` pin 成 `gemini-3.8-flash`（ready `00008-zrb`，同一映像 `eba3c8e-vertex-vision2`，digest `sha256:6c00f9f11a93f9f8a756c9ed9fadcb9f9b1dbd6ce28282d82a6fb005ace683a3`）。1-page：converter `POST /api/v1/convert-pdf` HTTP 200（ZIP markdown `**Model:** gemini-3.8-flash`，含 `Vertex Vision probe 20260924 IT Service Desk`）；Portal `import-pdf?async_mode=sync` HTTP 200、`conversion_engine=gemini_vision`、`conversion_gemini_backend=VERTEX_AI`，**沒有**降成 `legacy_text`。log：`gemini-3.8-flash:generateContent` HTTP 200、`Successfully extracted text from 1 pages`。這關閉 1-page 模型可用性。本回合補了最小 fixture（非大型語料）並在 live `00008-zrb` 跑完：`tests/fixtures/pdf-vision/selectable-text.pdf`、`scan-like.pdf`、`simple-table.pdf`、`mixed-text-image.pdf`。四份 `POST /api/v1/convert-pdf` 皆 HTTP 200；markdown 含各標記原文（scan-like 為 image-only 頁，log：`no extractable text, visual_structure(embedded_image)`）；`generateContent` 對 `us` `gemini-3.8-flash` 皆 **200、不是 404**。Portal `import-pdf?async_mode=sync` 匯入 `scan-like.pdf` HTTP 200、`gemini_vision`／`VERTEX_AI`，未降 `legacy_text`（OCR 把日期讀成 `20240924`，仍抽出 scan-like／IT Service Desk）。未切 `release-8535419976b4`。§7 逾時／403／429 仍未跑 | 不可讓 `auto` 靜默降成 `legacy_text` 假裝成功；不要把 `gemini-flash-latest` 寫回 Vertex `us` |
| Eval 是否獨立 project／SA | 建議獨立以隔離 quota／成本 | 未建立 eval project／impersonation；程式已接受 `VERTEX_AI_EVAL_*` | 未核准前不要把正式 ADC 當評測身分 |
| 向量是否可復用 | 預設不可復用；須通過固定樣本相容性實測 | Lab 已建新的不可變 Vertex release（見下方相容性證據）。3-case subset **已跑**；與 `713b5b02dfc2` 比較**無效**。156-case 全量 **已跑完**（見下方）。Top-K 重疊：**無效／未做**（沒有同 release 的 Developer API 對照；既有 `scripts/retrieval_ab_test.py` 是 Hybrid vs File Search，Vertex 模式 skip File Search，見下方） | 舊 Developer API release 缺 provenance，不得僅因 model ID 相同而共用；不可回寫假 provenance |

## P3 Terraform plan 與 lab 套用（2026-09-24）

操作者已核准 lab Cloud Run 切到 VERTEX_AI。Converter SA／Cloud Run／Portal invoker **已 import**。Post-import readonly plan：`22 to add, 6 to change, 5 to destroy`。Abort 關卡通過（Vision 保留、converter 是 in-place、location=`us`、API key **資源**不銷毀）。完整脫敏摘錄見 sibling evidence note。

| 項目 | 結果 |
|---|---|
| 後端 | `infra/environments/poc/backend.hcl` → `gs://itr-aimasteryhub-lab-terraform-state/poc/teams-agent` |
| 專案／區域 | `itr-aimasteryhub-lab`／`asia-east1`；Vertex project 同 lab；chat／embedding／PDF location=`us` |
| Init／plan | **成功**。Terraform v1.16.0。Post-import 摘要 `22 to add, 6 to change, 5 to destroy` |
| `google_secret_manager_secret.google_api_key` | **no-op，未銷毀**（secret id `teams-agent-google-api-key`）。`google-api-key` 亦仍在 |
| 已套用 | Vertex API、四個 SA 的 `roles/aiplatform.user`、Agent／Converter Terraform in-place revision、Portal／Backoffice 的 `gcloud --update-env-vars`（Portal 另 `--remove-secrets=GOOGLE_API_KEY`） |
| 未套用 | BigQuery `operational_events` 重建、ingestion bucket、Portal／Backoffice 的完整 Terraform env 收斂。converter targeted plan 現為 **No changes**（忽略服務層 `scaling`），**未套用**；`pdf_converter_image` pin 對齊 live digest，image 仍被 `ignore_changes` |
| Portal Vision | **live 仍是** `gemini_vision` + `https://teams-pdf-converter-jt7pjdeeoa-de.a.run.app` |
| File Search | 選 A：Portal sync／parity 已是 `false`／`false` |

## 現行 Cloud Run（lab，2026-09-24 Agent 工作樹映像後）

`gcloud run services describe`，project `itr-aimasteryhub-lab`，region `asia-east1`。`deploy-portal.sh` 已把**現行工作樹** Portal 打成 `teams-knowledge-portal:eba3c8e`。Agent **已**用 image-only `gcloud run deploy --image`（**沒有** `--set-env-vars`，也**沒有**跑 `deploy-gcp.sh`）換成現行工作樹 `teams-rag-agent:eba3c8e-wt`（digest `sha256:fcf1dca186f72a946ae09bc6e85a0538aa964ff08bf8906b16f0f1a4e85e997c`）。相對 `00053-jdp` 的 env／secret mounts **完全相同**（`KNOWLEDGE_RELEASE_MODE=PORTAL`、`KNOWLEDGE_SERVICE_MODE=HYBRID`、File Search model `gemini-3.5-flash-lite`、GCS bucket／prefix／tenant、VERTEX `us`、無 Gemini key、無 `GOOGLE_APPLICATION_CREDENTIALS`、仍掛 `TICKET_SERVICE_TOKEN`）。未套用 Terraform drift，未切 active release，未 commit／push。

| 服務 | Ready revision | Service account | `GEMINI_API_BACKEND` | `GOOGLE_API_KEY`／`GEMINI_API_KEY` 掛載 |
|---|---|---|---|---|
| `teams-rag-agent` | `teams-rag-agent-00054-677` | `teams-rag-agent@itr-aimasteryhub-lab.iam.gserviceaccount.com` | `VERTEX_AI` | 否 |
| `teams-knowledge-portal` | `teams-knowledge-portal-00042-bmj` | `teams-knowledge-portal@itr-aimasteryhub-lab.iam.gserviceaccount.com` | `VERTEX_AI` | 否 |
| `teams-pdf-converter` | `teams-pdf-converter-00008-zrb` | `teams-pdf-converter@itr-aimasteryhub-lab.iam.gserviceaccount.com` | `VERTEX_AI` | 否 |
| `teams-ai-ops-backoffice` | `teams-ai-ops-backoffice-00055-qf4` | `teams-ai-ops-backoffice@itr-aimasteryhub-lab.iam.gserviceaccount.com` | `VERTEX_AI` | 否 |

Portal File Search sync／parity 為 `false`／`false`，PDF engine 仍是 `gemini_vision` + `https://teams-pdf-converter-jt7pjdeeoa-de.a.run.app`。Converter `00008-zrb` 是 env-only 更新（同一映像 `eba3c8e-vertex-vision2`，digest `sha256:6c00f9f11a93f9f8a756c9ed9fadcb9f9b1dbd6ce28282d82a6fb005ace683a3`）；env 是 `VERTEX_AI`／`us`／`GEMINI_MODEL=gemini-3.8-flash`／無 key。Terraform `pdf_converter_image` **已 pin** 同一 live digest（`infra/environments/poc/terraform.tfvars.example` 與本機 `infra/terraform/terraform.tfvars`）。converter targeted plan 為 **No changes**（忽略服務層 `scaling`）；**未**套用（不要為了對齊 pin 去套用 BigQuery／bucket）。Agent 仍是 `KNOWLEDGE_SERVICE_MODE=HYBRID`。Backoffice `00055-qf4` 是 image-only（tag `eba3c8e-content`，digest `sha256:5451caf33016e0b1d5a5c12aa2e125b10ee39e521580fc554ee06407c401b2b3`）；Vertex `us`／無 key／`AI_OPS_WORKERS_ENABLED=false`／`RAG_MODEL=google_genai:gemini-3.8-flash` 與 `00054-6jb` 相同。Vertex project／chat／embedding／PDF location 皆為 `itr-aimasteryhub-lab`／`us`。Production 沒有對應 backend／project，也沒有任何 cutover。

## 本回合簽署與仍未執行

- Vertex 專案：**已簽署 same-lab** `itr-aimasteryhub-lab`。不從 `project_id` 推導。
- 資料區域：**已簽署 `us`**（chat／embedding／PDF）。Lab Cloud Run 已是 `GEMINI_API_BACKEND=VERTEX_AI`。本機／dev `.env` 不必跟著切。
- File Search：維持選 A。Portal live sync／parity 已關閉。
- Live Vertex smoke：**本機 ADC 已通過**（見下方「Smoke 結果」）。Cloud Run Agent SA、Converter SA 與 Backoffice SA 的 `data_access` **已出現**（見下方 Audit Logs）。Portal SA 列仍缺（`import-pdf` 只呼叫 converter）。
- **已** import converter SA／Cloud Run／invoker；**已** 針對 Vertex API／IAM／Agent／Converter 做 targeted apply；Portal／Backoffice 用 gcloud 補 Vertex env 並卸載 key。**已**用 `deploy-portal.sh` 部署現行工作樹 Portal（ready `00042-bmj`）。**已** image-only 部署現行工作樹 Agent（ready `00054-677`）。**已** image-only 部署 Vertex-patched converter，再 env-only pin `GEMINI_MODEL=gemini-3.8-flash`（ready `00008-zrb`）。**已**把 Terraform `pdf_converter_image` pin 對齊 live digest。**已**讓 converter `lifecycle.ignore_changes` 忽略服務層 `scaling`；targeted plan **No changes**，未套用。**已** image-only 部署 Backoffice `00055-qf4`（tag `eba3c8e-content`；list／dict Gemini `content` join 成 string）；Vertex env／`RAG_MODEL`／workers=false 未改。**未** 套用 BigQuery／bucket drift。**未** git commit／push。**Production 未切換。**
- Lab FOLLOW_CLOUD pointer **已**切到 `release-8535419976b4`（見下方 release 相容性證據）。Agent `00054-677` 仍載入同一 release（`/readyz`＋`/admin/knowledge-status`，10:02:51 UTC sync）。
- Cloud Audit Logs：project IAM **已寫入** `auditConfigs`（僅 `aiplatform.googleapis.com` 的 DATA_READ／DATA_WRITE；81 個 bindings 未改；etag `BwZcN9fGUaU=`）。**未**開 org-level audit，**未** enable Org Policy API。`_Default` sink 的 `kill-k8s-audit` 會丟掉所有 `cloudaudit.googleapis.com`；已另建 sink `aiplatform-data-access` 寫入 `_Default` bucket。`_Default` **view** 仍是 `NOT LOG_ID(.../data_access)`。查 `_AllLogs`。2026-09-24T10:24 再打 live Agent chat `vertex-sa-audit-20260924T102408Z`（HTTP 200、HYBRID、`release-8535419976b4`）與本機 `vertex_sa_smoke.py` 後，**已出現** Agent SA `data_access`（見下方）。
- Frozen eval：已跑文件化 3-case subset 與 156-case 全量（見下方）。對 `release-8535419976b4` 的分數**不得**與 Developer API `release-713b5b02dfc2`／`release-4f49088db9ca` 基線直接比。舊 Developer API `release-652fb6146104` 缺 provenance，Vertex `HybridIndex.load` **拒絕**；不得回寫假 provenance。
- `deploy-gcp.sh`：既有 Agent 改 `deploy_cloud_run_preserving_runtime` + `preserve_live_agent_knowledge_env`。後續可跑完整腳本而不覆蓋 live `KNOWLEDGE_RELEASE_MODE=PORTAL`、現行 release pointer、File Search model；仍 assert `VERTEX_AI`、卸載 Gemini key、`KNOWLEDGE_SERVICE_MODE=HYBRID`。

### Smoke 結果

2026-09-24 本機 ADC（`gcloud auth application-default`，account `weicyun@cathayholdings.com.tw`，project `itr-aimasteryhub-lab`）跑 `scripts/vertex_sa_smoke.py`。程序只設 `VERTEX_AI_PROJECT=itr-aimasteryhub-lab` 與 chat／embedding／PDF location `us`；`GEMINI_API_KEY`／`GOOGLE_API_KEY` 已 unset，未載入 `.env`。

stdout：`vertex_sa_smoke: live chat and embedding probes succeeded project_set=true chat_location=us embedding_location=us`（exit 0）。這只證明本機 ADC 可打 Vertex `us`；**不是** Cloud Run revision 切換，也**不是** import／apply 核准。

## 仍未關閉：P0／P3 殘項／P4／P5

| 階段 | 狀態 |
|---|---|
| P0 | Vertex 專案已簽署 same-lab `itr-aimasteryhub-lab`；資料區域已簽署 `us`。File Search 維持選 A。本機 ADC smoke 已通過。Lab Cloud Run 已切 VERTEX_AI。PDF 同日切換驗收／獨立 eval／向量復用仍未簽署。`global` 仍不可當成核准資料區域。 |
| P3 殘項 | Converter 已 import。Lab Agent／Portal／Converter／Backoffice 已是 VERTEX_AI 且無 key mount。Google API key **資源**保留。`pdf_converter_image` **已 pin** live `00008-zrb` digest（example + 本機 tfvars）。converter targeted plan 為 **No changes**（忽略服務層 `scaling`）。完整 Terraform plan 的 BigQuery／ingestion-bucket／Portal-Backoffice env 收斂 **仍未套用**。不可當成「只切 Vertex」。`terraform destroy -target` 不可用來清 key IAM（會連 Adapter／Portal）。 |
| P4 | Lab 已有 Vertex-provenance active release。3-case frozen L3 subset 已跑；與 `release-713b5b02dfc2` 的 1.00→0.67 比較**無效**。156-case 全量已對 `release-8535419976b4`／Vertex ADC／`us`／無 key **跑完**（見下方）。正式 Top-K 重疊：**無效**（無同 release／同後端對照；見下方）。 |
| P5 | Lab Agent／Portal revision 與 lab knowledge pointer 已切。Agent、Converter 與 Backoffice SA `data_access` 已引用。Portal SA 列仍缺（`import-pdf` 只呼叫 converter；未 reindex）。live Vision：1-page 加上 scan-like／table／mixed 已用 `gemini-3.8-flash` @ `us` 通過（`00008-zrb`，fixture 在 `tests/fixtures/pdf-vision/`）。§7 逾時／403／429 仍未跑。切換監控與 Production 仍未做。 |

## Lab release 相容性證據（2026-09-24）

Live Agent（`teams-rag-agent-00054-677`，映像 `eba3c8e-wt`，`KNOWLEDGE_SERVICE_MODE=HYBRID`，selection 預設 FOLLOW_CLOUD，GCS `itr-aimasteryhub-lab-knowledge-releases`，tenant `default`）：

| 項目 | 證據 |
|---|---|
| 切換前 active pointer | Firestore `knowledge_portal_config/active_release` = `release-652fb6146104` |
| 舊 index | `embeddingModel=google_genai:gemini-embedding-2`，66/66 vectors，dims 3072；**無** `embeddingBackend`／`embeddingVertexLocation` |
| Vertex 載入舊 release | `HybridIndex.load` 在 `GEMINI_API_BACKEND=VERTEX_AI`／location `us` 下 `compatible=False`，錯誤：`Configured embedding backend/model/location/dimensions do not match the built index... sparse-only search.` |
| 為何不補 stamp | 規格禁止把 Developer API 向量標成 Vertex。增量 reuse 對該 payload 回 `embedding_provenance_mismatch`（reused=0） |
| 語料規模 | 32 documents／66 chunks／約 34k chars（估 ~23k tokens）。完整重嵌成本遠低於一小時，走既有 Portal `reindex_all_published` |
| 新 release | `release-8535419976b4` PRODUCTION ACTIVE。GCS／manifest／Firestore：`embeddingBackend=VERTEX_AI`，`embeddingVertexLocation=us`，`embeddingDimensions=3072`，66/66，sha256 `63c58c5958a601b290198bed82ad95f0f8aca89245e4f1a9c015acc38b5f20d0` |
| Vertex 載入新 release | 同一 loader `LOAD_RESULT=loaded`；provenance `VERTEX_AI`／`us`／3072 |
| Live Agent | `00054-677`（10:02:58 UTC Ready）。`/admin/knowledge-status`：FOLLOW_CLOUD `IN_SYNC`，`alignedWithCloud=true`，`currentReleaseId=release-8535419976b4`，32 docs／66 chunks，`lastSuccessfulSyncAt=2026-09-24T10:02:51Z`。`/readyz`：`knowledgeReleaseId=release-8535419976b4`，sha256 `63c58c5958a601b290198bed82ad95f0f8aca89245e4f1a9c015acc38b5f20d0`，3072 維，`knowledgeMode=HYBRID` |
| 映像契約 | Cloud Build inspect `dedb2cc7-033e-4728-81ba-f66a25949212`：映像含 `gemini_clients.py` 與 `current_embedding_provenance`；`HybridIndex.load` 原始碼含 `Rebuild the release`／`sparse-only search`（`do not match the built index` 在映像與工作樹都是折行字串）。本機 ADC 對下載的 GCS index：新 release 載入成功；`release-652fb6146104` **拒絕** |
| 舊 release | GCS 物件仍在，Firestore `ROLLED_BACK`，供 Developer API 環境載入 |
| 向量觀察 | 新舊 66 條向量 bit-identical。增量路徑未 reuse；此為 Vertex Embedding 2 對同一文件／模型／3072 維的重嵌結果，不是改舊檔。**仍不能**用這點略過完整 frozen eval |
| ACL／citation | 32 docs／66 chunks 皆有 `allowed_groups` 與 `document_id`＋`source_path`。本 corpus 全是 `grp_public`，無法用拒看群組證明 leakage=0。先前已對 32-doc 公開語料打 live Agent `POST /agent/chat`（`00053-jdp`）。本回合改跑 frozen 3-case subset（見下） |

Vertex `embedContent` 對 Embedding 2 **一次只能一個 content**。publisher／query 批次已改為 Vertex `batch_size=1`（並在 API 拒絕批次時逐筆回退）。未套用 Terraform drift，未 commit／push，未把 Cloud Run 切回 Developer API。

## Frozen L3 subset（2026-09-24，比較無效；**不是 pass**）

文件化 3-case subset：`data/eval/reports/_tmp_l3_ans07_ver04_neg03_cases.json`（`frozen=true`，freezeVersion 5，datasetHash `31b8d928f2fd5a76fa261d49527483450067c1350e42b56ebeb431c62d038de6`）。本機 ADC、`GEMINI_API_BACKEND=VERTEX_AI`、project `itr-aimasteryhub-lab`、locations `us`、**無 API key**；`--index-path` 指向 GCS 下載的 `release-8535419976b4`。報告：`data/eval/reports/rag-l3-v3-blind-subset-vertex-release-8535419976b4.json`。先前 subset 基線是 Developer API／`release-713b5b02dfc2`（`rag-l3-v3-blind-subset-ans07-ver04-neg03.json`，commit `cd97e450`）。**規格 5.2：不得把不同 release 的結果當成同一基準。** Vertex 拒絕缺 provenance 的 `713b5b02dfc2`；Developer API 也不能 grandfather `embeddingBackend=VERTEX_AI` 的 `8535419976b4`。沒有合法同 release 對照，**未**重跑 3-case，**未**改 judge／prompt。

| 指標 | `713b5b02dfc2`（無效對照） | Vertex `release-8535419976b4` | 判定 |
|---|---:|---:|---|
| answerAccuracy | 1.00 | 0.67 | **無效比較**；853 本身 2 fail（見下） |
| citationPrecision | 1.00 | 0.89 | **無效比較** |
| citationRecall | 1.00 | 1.00 | 853 檢索完整 |
| retrievalEvidenceRecallAt4 | 1.00 | 1.00 | 非 batch_size／舊 index／拒載入 |
| groundedness | 1.00 | 1.00 | 持平 |
| aclLeakageCount | 0 | 0 | 持平（語料無 group-gated docs） |
| Total P95 (ms) | 6747 | 6208 | 未當成基線改善 |
| failureCount | 0 | 2 | 853 報告內失敗，不是遷移迴歸證明 |

失敗診斷（judge 未改）：

- `v3-blind-ans-07` ANSWER_OMISSION：`retrievalEvidenceRecall=1.0`，選到 FortiClient＋VPN Q&A，但答案寫 Ctrl+Alt+Delete 開機密碼，缺 mustContain `密碼到期`＋`改密碼`。同案在 Developer API／`713b5b02dfc2` 的較大 subset（`rag-l3-v3-blind-subset-live-2bb806b-release-713b5b02dfc2.json`）已經 ANSWER_OMISSION。屬生成／字面 mustContain，不是 Vertex 載入或 embedding batch 故障。
- `v3-blind-ver-04` BAD_CITATION：答案含 `新版簽章元件`／`國泰期貨`，`answer_evidence_recall=1.0`；多引了不在 `expectedSourceTitles` 的「樹精靈WEB…」，citationPrecision 2/3。taxonomy 在答案已覆蓋時只要 precision 低於 1 就標 BAD_CITATION。不是 refuse-old-index 或 prompt 後端分支。

156-case 全量基線（`docs/agentic-rag-production-optimization-implementation-spec-20260921.md`：answer 82.05%、citation P 87.50%、Total P95 4047 ms；以及 `release-4f49088db9ca` 的 96.79%／98.82%）**不是** `release-8535419976b4` 對照。853 全量分數見下方；比較**無效**。

## Audit Logs（2026-09-24，Agent／Converter／Backoffice SA `data_access` **已引用**）

project `itr-aimasteryhub-lab`：

- IAM `auditConfigs`：**已寫入**（`aiplatform.googleapis.com` DATA_READ＋DATA_WRITE）。`SetIamPolicy` ADMIN_ACTIVITY：`weicyun@cathayholdings.com.tw` @ 2026-09-24T10:12:52Z。寫入前後 bindings 仍是 81，未改角色。
- **未**開 org-level audit。**未** enable Org Policy API。
- `_Default` sink exclusion `kill-k8s-audit` 的 filter 含 `logName:"logs/cloudaudit.googleapis.com"`，會丟掉 DATA_ACCESS。另建 sink `aiplatform-data-access` → `_Default` bucket（filter：`LOG_ID(data_access)` 且 `serviceName=aiplatform.googleapis.com`）。
- `_Default` **view** 預設 `NOT LOG_ID(.../data_access)`。必須加 `--bucket=_Default --location=global --view=_AllLogs`。
- 上一回合 chat `vertex-sa-audit-20260924T101836Z` 後 `_AllLogs` 仍空。本回合再打 `POST /agent/chat` `vertex-sa-audit-20260924T102408Z`（`00054-677`，HTTP 200，HYBRID，`release-8535419976b4`）與本機 `scripts/vertex_sa_smoke.py`（exit 0，無 API key）。
- **已引用的 SA 列**（`_AllLogs`，`cloudaudit.googleapis.com/data_access`，`serviceName=aiplatform.googleapis.com`）：

```text
principalEmail=teams-rag-agent@itr-aimasteryhub-lab.iam.gserviceaccount.com
methodName=google.cloud.aiplatform.v1beta1.PredictionService.GenerateContent
resourceName=projects/itr-aimasteryhub-lab/locations/us/publishers/google/models/gemini-3.1-flash-lite
timestamp=2026-09-24T10:24:15.947668623Z
```

  同秒還有同一 SA 的 `EmbedContent`（`gemini-embedding-2` @ 10:24:15Z）與 `GenerateContent`（`gemini-3.8-flash` @ 10:24:09Z）。這是規格 10.2 對 **Agent Cloud Run SA** 的交叉佐證。
- 同一視窗另有本機 ADC principal `weicyun@cathayholdings.com.tw` 的 `EmbedContent`／`GenerateContent`（frozen eval／smoke），**不是** Cloud Run SA。
- **另已引用 Converter SA**（同一 `_AllLogs` 查詢，Vision probe 之後）：

```text
principalEmail=teams-pdf-converter@itr-aimasteryhub-lab.iam.gserviceaccount.com
methodName=google.cloud.aiplatform.v1beta1.PredictionService.GenerateContent
resourceName=projects/itr-aimasteryhub-lab/locations/us/publishers/google/models/gemini-3.8-flash
timestamp=2026-09-24T10:43:25.110507349Z
```

  這是 env-only pin `GEMINI_MODEL=gemini-3.8-flash` 後、converter `00008-zrb` 的 1-page probe。converter log 同期是 `POST https://aiplatform.us.rep.googleapis.com/.../gemini-3.8-flash:generateContent` **HTTP 200**，接著 `Successfully extracted text from 1 pages`／`Gemini Vision: 1 pages`。較早的 `gemini-flash-latest` 列（10:38:35Z／10:38:44Z／10:38:53Z）是 404 失敗窗，不要再當通過證據。
- **另已引用 Backoffice SA**（`_AllLogs`，inline `REAL_RAG` `run_5c60ec7f9a3e` 之後）：

```text
principalEmail=teams-ai-ops-backoffice@itr-aimasteryhub-lab.iam.gserviceaccount.com
methodName=google.cloud.aiplatform.v1beta1.PredictionService.GenerateContent
resourceName=projects/itr-aimasteryhub-lab/locations/us/publishers/google/models/gemini-3.8-flash
timestamp=2026-09-24T11:04:27.667092863Z
```

  同 run 還有第二筆 `GenerateContent`（同一模型 @ 11:04:32.722483572Z）。這是規格 10.2 對 **Backoffice Cloud Run SA** 的交叉佐證。Backoffice log 同期是 `POST https://aiplatform.us.rep.googleapis.com/.../gemini-3.8-flash:generateContent` **HTTP 200**（11:04:31Z 與 11:04:41Z）。該 run 兩側曾 `FAILED`／`UNEXPECTED_ERROR`（list-valued `answer.content`）。後續 `00055-qf4`／`run_5be59fbc0b1a` 已把 content join 成 string，兩側 `COMPLETED`／`HALLUCINATION`，**沒有** `.lower()` crash；不要當成品質通過或 156-case 閘門。
- Portal SA 的 `data_access` **仍缺**（2026-09-24 再查 `_AllLogs` 7d 仍是 `[]`）。原因見下一節，不是「env 沒設 VERTEX_AI」。

查詢（`--view=_AllLogs`）：

```bash
gcloud logging read \
  'logName="projects/itr-aimasteryhub-lab/logs/cloudaudit.googleapis.com%2Fdata_access" AND protoPayload.serviceName="aiplatform.googleapis.com" AND (protoPayload.authenticationInfo.principalEmail:"teams-rag-agent@" OR protoPayload.authenticationInfo.principalEmail:"teams-knowledge-portal@" OR protoPayload.authenticationInfo.principalEmail:"teams-pdf-converter@" OR protoPayload.authenticationInfo.principalEmail:"teams-ai-ops-backoffice@")' \
  --project=itr-aimasteryhub-lab --bucket=_Default --location=global --view=_AllLogs \
  --limit=8 --freshness=24h \
  --format='json(timestamp,protoPayload.authenticationInfo.principalEmail,protoPayload.methodName,protoPayload.serviceName,protoPayload.resourceName)'
```

## 156-case frozen L3（2026-09-24，**已跑完**；無同 release 基線）

文件化閘門：`data/eval/retrieval_eval_v3_blind.json`（`frozen=true`，freezeVersion 5，**156** test cases）。**沒有**把閘門縮成 3-case。exit 0，約 535 s。報告 `data/eval/reports/rag-l3-v3-blind-full-live-vertex-release-8535419976b4.json`。provenance：`VERTEX_AI`／`itr-aimasteryhub-lab`／`us`／`release-8535419976b4`／freezeVersion 5。

```bash
unset GEMINI_API_KEY GOOGLE_API_KEY GEMINI_EVAL_API_KEY GOOGLE_EVAL_API_KEY
export GEMINI_API_BACKEND=VERTEX_AI
export VERTEX_AI_PROJECT=itr-aimasteryhub-lab
export VERTEX_AI_CHAT_LOCATION=us
export VERTEX_AI_EMBEDDING_LOCATION=us
export VERTEX_AI_PDF_LOCATION=us
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=itr-aimasteryhub-lab
export GOOGLE_CLOUD_LOCATION=us
export KNOWLEDGE_RELEASE_CACHE_DIR="$(pwd)/data/knowledge_cache"
agent_service/.venv/bin/python scripts/run_rag_pipeline_eval.py \
  --eval-set data/eval/retrieval_eval_v3_blind.json \
  --split test --layer 3 --live-model \
  --index-path /tmp/release-8535419976b4/index/chunks.json \
  --release-id release-8535419976b4 \
  --output data/eval/reports/rag-l3-v3-blind-full-live-vertex-release-8535419976b4.json
```

啟動時先出現 Vertex `503 UNAVAILABLE` embedding 重試，隨後跑完整 156 案。`_AllLogs` 同期出現 `weicyun@cathayholdings.com.tw` 的 `EmbedContent`／`GenerateContent`（本機 ADC，無 API key）。

| 指標 | Vertex `release-8535419976b4` | 其他 release 基線 | 判定 |
|---|---:|---|---|
| caseCount | 156 | — | 閘門規模成立 |
| answerAccuracy | 92.95% | 規格 2.4：82.05%；`4f49088db9ca`：96.79% | **無效比較**；只報 853 |
| citationPrecision | 95.62% | 規格 2.4：87.50%；`4f49088db9ca`：98.82% | **無效比較** |
| citationRecall | 95.83% | — | 853 數字 |
| retrievalEvidenceRecallAt4 | 93.10% | — | 853 數字 |
| candidateEvidenceRecall@24 | 96.55% | — | 853 數字 |
| groundedness | 100% | — | 853 數字 |
| aclLeakageCount | 0 | — | 語料無 group-gated docs |
| hardNegativeAccuracy | 93.75% | — | 16 labeled |
| noAnswer F1 | 95.24%（40 TP／4 FP／0 FN） | — | 853 數字 |
| Total P95 (ms) | 4667 | 規格 2.4：4047 | **無效比較** |
| failureCount | 14 | — | ANSWER_OMISSION 6、NO_ANSWER_FALSE_POSITIVE 4、BAD_CITATION 3、EVIDENCE_NOT_PASSED_TO_GENERATOR 1 |

同 release 的 in-repo 156-case 基線**不存在**。既有全量基線是 Developer API／其他 release。**不得**與 853 直接比。3-case 853 分數仍是 answer 0.67／citation P 0.89，也**不能**當 156-case 品質通過。

## Portal／Backoffice 為何沒有 `data_access`（2026-09-24 再查）

`gcloud logging read` 同一 `_AllLogs` 查詢：Portal principal **0 列**；Backoffice principal **已引用**（見上方 11:04:27Z）。這不是 env 漏設：兩個服務 ready revision 都是 `GEMINI_API_BACKEND=VERTEX_AI`／`us`／無 Gemini key mount，且 Terraform 已授 `roles/aiplatform.user`。

| 服務 | 什麼時候才會打 Vertex | 本回合為何沒有列 |
|---|---|---|
| Portal `00042-bmj` | 發佈／reindex 的 `HybridIndex.add_embeddings()`（`publisher_index.py`）才會 `EmbedContent`。`import-pdf` 只呼叫 converter。`draft_retrieval.build_draft_index()` **不** `add_embeddings`；`search()` 在 `not has_vectors` 時跳過 query embed（`retrieval.py` `_resolve_query_vector`）。`/evaluate` 只做 chunk preview。 | 853 發佈 `lastSuccessfulSyncAt=2026-09-24T10:02:51Z`，**早於** IAM `auditConfigs` `SetIamPolicy` `2026-09-24T10:12:52Z`。之後沒有再發佈、未 `start-revision`、未 reindex。本回合 Portal `import-pdf` 匯入 `scan-like.pdf`（HTTP 200、`VERTEX_AI`），只呼叫 converter，**沒有** `EmbedContent`。Agent 仍載入 `release-8535419976b4`。 |
| Backoffice `00055-qf4` | `composition/backoffice_agent_adapters.py` 把 `build_chat_model` 接到 eval／judge。只有實際跑 evaluation run 且回答／judge 走到 model factory 才會 `GenerateContent`。 | live `AI_OPS_WORKERS_ENABLED=false`，**沒有** `teams-ai-ops-backoffice-worker` 服務。image-only 部署 tag `eba3c8e-content`（digest `sha256:5451caf33016e0b1d5a5c12aa2e125b10ee39e521580fc554ee06407c401b2b3`）；Vertex env／無 key／`RAG_MODEL`／workers=false **未改**。`invoke_chat_model_answer` 把 list／dict Gemini `content` join 成 string。HEADER `POST /api/evaluations/runs`（`execute_inline=true`），**沒有**啟用 workers、**沒有**新建 worker fleet。既有 1-case set `eval_set_7af7757ffdf1`／`setver_7a89df5b638b`（case `case_bee4d6c72b03`）**未** pin `release-8535419976b4`。`REAL_RAG` preflight **valid**。`run_5be59fbc0b1a` HTTP 202／`COMPLETED`（11:11:22–11:11:43Z），兩側 `COMPLETED`／`HALLUCINATION`（answer 為 string，有 `provider_request_id`；**沒有** `'list' object has no attribute 'lower'`）。Backoffice log 同期 `gemini-3.8-flash:generateContent` **HTTP 200**（`00055-qf4` @ 11:11:38Z）。`_AllLogs` 該 principal **已引用**（11:04:27Z／11:04:32Z）。這**不是** 156-case 閘門。 |

規格 10.2 對 Portal SA 的交叉佐證**仍缺**；Backoffice SA **已引用**。Portal 維持「只呼叫 converter」：本回合 `import-pdf` 沒有、也**不可**靠 reindex 去鑄新 release。要出現 Portal 列必須在 audit 開啟後再做一次真正的 `add_embeddings`（會另建 release）。Backoffice 1-case `run_5be59fbc0b1a` 已不再因 list `.lower()` 崩；兩側 `HALLUCINATION` 是品質／無 retrieved evidence，**不是** 156-case 閘門。未啟用 standing worker fleet。

## Top-K 重疊（規格 5.1）：無效，未假通過

規格要求固定文件／查詢在 **Developer API 與 Vertex** 比維度、距離／排序、Top-K 重疊。現況：

- Vertex 拒絕缺 provenance 的舊 Developer API release；Developer API 也不能 grandfather `embeddingBackend=VERTEX_AI` 的 `release-8535419976b4`。
- 沒有同 release、同語料的第二後端對照。
- 既有腳本 `scripts/retrieval_ab_test.py` 比的是 Hybrid vs Gemini File Search，**不是**雙後端。Vertex 模式 `_try_build_gemini_service` 直接 skip：`Gemini File Search is not supported on VERTEX_AI.`
- `scripts/run_rag_v2_shadow_eval.py` 的 `topk_overlap` 比的是同一 index 的 fusion 變體 A/B/C/D，也不是 Developer API vs Vertex。

因此正式 Top-K 重疊**無效／未跑**。沒有拿其他 release 分數假裝通過。

## 規格第 7 節 Vision 完整樣本

最小 fixture 現在在 `tests/fixtures/pdf-vision/`（builder：`build_vision_fixtures.py`，Pillow＋既有 raw PDF，無新依賴）：

| 檔案 | 頁面契約 | live `00008-zrb` `POST /api/v1/convert-pdf` | 抽出標記 | `generateContent` |
|---|---|---|---|---|
| `selectable-text.pdf` | 可選取文字、無 XObject | HTTP 200（10:53:06–10:53:10Z） | `Vertex Vision selectable 20260924 IT Service Desk` | `gemini-3.8-flash` **200**，非 404 |
| `scan-like.pdf` | image-only、pypdf 抽不到字 | HTTP 200（10:53:10–10:53:17Z）；log `no extractable text, visual_structure(embedded_image)` | `Vertex Vision scan-like 20260924 IT Service Desk` | 同上 **200** |
| `simple-table.pdf` | 文字表＋框線 | HTTP 200（10:53:17–10:53:21Z）；log `visual_structure(tabular_text)` | `Vertex Vision table 20260924 IT Service Desk`；markdown 表 Priority／Channel | 同上 **200** |
| `mixed-text-image.pdf` | 可選取文字＋嵌入圖 | HTTP 200（10:53:21–10:53:27Z）；log `visual_structure(embedded_image)` | `Vertex Vision mixed 20260924 IT Service Desk` 與 image badge | 同上 **200** |

四次 converter HTTP request 皆由 revision `teams-pdf-converter-00008-zrb` 回 200。Portal 只匯入 `scan-like.pdf`：`import-pdf?async_mode=sync` HTTP 200、`conversion_engine=gemini_vision`、`conversion_gemini_backend=VERTEX_AI`，未降 `legacy_text`。Agent `/readyz` 仍是 `release-8535419976b4`。§7 逾時／Vertex 403／429 樣本仍未跑。

## 關閉關卡後的下一步

1. Top-K 重疊仍無效，除非另建**同語料**的 Developer API 對照（或明確放棄跨後端復用）。156-case 853 分數已記錄，**不能**用其他 release 基線當通過。
2. selectable／scan-like／table／mixed Vision 已在 `00008-zrb` 關閉模型可用性。§7 還缺逾時／403／429。不要開 org-level audit，不要為了查詢而去 enable Org Policy API。Portal SA `data_access` 仍缺（不得為了 audit 去 reindex）。Backoffice SA 列已引用；list-valued `answer.content` 的 `.lower()` crash **已修**（`00055-qf4`／`run_5be59fbc0b1a` 兩側 `COMPLETED`／`HALLUCINATION`）。不要把 1-case 當 156-case 閘門。
3. `pdf_converter_image` pin 已對齊 live digest。converter targeted plan 為 **No changes**（忽略服務層 `scaling`）。BigQuery／ingestion bucket drift 仍另案。`deploy-gcp.sh` 已改為既有 Agent 不覆蓋 knowledge env。
4. Production 不在本次 lab backend 範圍內。
