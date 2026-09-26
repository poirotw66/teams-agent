# Vertex AI 雙後端操作手冊（2026-09-24）

> 本手冊對應規格第 11.3 節。**不要**把 `global` 當成已核准資料區域。Lab Cloud Run（Agent／Portal／Converter／Backoffice）已於 2026-09-24 切到 VERTEX_AI。Agent 現行工作樹映像 ready revision 是 `teams-rag-agent-00054-677`（tag `eba3c8e-wt`，digest `sha256:fcf1dca186f72a946ae09bc6e85a0538aa964ff08bf8906b16f0f1a4e85e997c`）。Lab FOLLOW_CLOUD active release 已是 `release-8535419976b4`（`embeddingBackend=VERTEX_AI`，location `us`，3072 維）。**Production 未切**。完整 Terraform plan 的 BigQuery／ingestion-bucket drift 不要當後續「只切 Vertex」來套用。`deploy-gcp.sh` 對**既有** Agent 改走 image + `--update-env-vars`：保留 live `KNOWLEDGE_RELEASE_MODE=PORTAL`、現行 release pointer、File Search option A，同時仍寫入 VERTEX_AI／HYBRID 並卸載 Gemini key。首次建立才會用腳本預設（AUTO／`release-19072ac9a1e2`／`gemini-2.5-flash`）。
>
> 重試只處理暫時性錯誤（逾時、429、短暫 5xx）。**不要**重試 403、設定錯誤、向量 provenance 不符或 PDF Vision 未完成。

## 快速辨識

| 症狀／error class | 含義 | 立即動作 |
|---|---|---|
| `missing_api_key` | `DEVELOPER_API` 缺少 `GEMINI_API_KEY`／`GOOGLE_API_KEY` | 補 key 或改選 `VERTEX_AI`。**不可**自動改走 Vertex |
| `missing_adc` | Vertex 找不到 Application Default Credentials | Cloud Run 確認已綁定使用者管理 SA。本機：`gcloud auth application-default login --impersonate-service-account=SA_EMAIL` |
| `configuration_conflict` | Vertex 程序環境殘留 Gemini／Google API key | 先 `unset GEMINI_API_KEY GOOGLE_API_KEY`。Vertex 不得載入 `.env` 內的 key |
| `iam_403` | 目標 Vertex project 拒絕目前 SA | 在**模型所在 project** 授予呼叫者 SA `roles/aiplatform.user`（或經核准的更小 custom role）。**不要**改回 API key |
| `model_or_location_unavailable`（404／400） | 模型 ID、location 或 API 版本不可用 | 核對 `VERTEX_AI_CHAT_LOCATION`／`EMBEDDING_LOCATION`／`PDF_LOCATION` 是否為 BU 核准值。**不要**用 Cloud Run `asia-east1`。未核准占位 `global` 在 Terraform／BU deploy／Vertex 啟動時會被拒絕 |
| `unsupported_param_400` | 模型拒絕 `temperature`／`top_p`／`top_k` 等參數 | Vertex 的 Gemini 3.8 Flash 會去掉取樣參數。Developer API 維持原行為。不要為了過關改成另一個未驗證模型 |
| `quota_429` | 配額或速率用盡 | 有限退避後重試；持續 429 要升 quota 或降載。**不要**改走另一個後端 |
| 向量 provenance 不符 | 舊 release 缺 `embeddingBackend`／location／dimensions，或與目前後端不一致 | **拒絕載入**，不要改用稀疏搜尋假裝成功。為 Vertex 建新的不可變 release 再切 active pointer |
| PDF Vision 403／429／逾時 | 轉檔身分、模型或配額失敗 | 需要 Vision 的發佈必須失敗並停止。**不可**讓 `auto` 靜默改成 `legacy_text` |

## ADC 失效

1. 確認程序是 `GEMINI_API_BACKEND=VERTEX_AI`，且沒有 Gemini／Google API key。
2. Cloud Run：服務必須使用 Terraform／deploy 綁定的 SA，且**不要**設定 `GOOGLE_APPLICATION_CREDENTIALS`。
3. 本機：用 impersonation 重建 ADC，然後 `gcloud auth application-default print-access-token`。
4. 撤銷本機 ADC：`gcloud auth application-default revoke`。

## 向量維度或後端不符

1. 查 release provenance：`embeddingBackend`、`embeddingModel`、`embeddingVertexLocation`、`embeddingDimensions`。
2. 舊 Developer API release 缺欄位時，**不能**只因 model ID 相同就給 Vertex 用。
3. 依規格第 5.1 節重建 Vertex release，經驗收後才切 active pointer。
4. Developer API 環境仍可載入該模式的舊 release。

Lab 實測（2026-09-24）：`release-652fb6146104` 有 model／66 向量／3072 維但缺 backend／location；Vertex `HybridIndex.load` 拒絕（不得改走稀疏搜尋）。不可對該檔補 stamp。Portal `reindex_all_published`（現行工作樹，增量因 provenance mismatch 不 reuse）寫出 `release-8535419976b4`：`embeddingBackend=VERTEX_AI`、`embeddingVertexLocation=us`、3072、66/66。同一 Vertex loader 可載入。Firestore pointer 與 Agent FOLLOW_CLOUD 已對齊該 release（09:46:14 UTC auto-sync，`chunks=66`，HYBRID）。Vertex Embedding 2 的 `embedContent` 一次只能一個 content；批次必須 `batch_size=1`。舊 release GCS 保留為 `ROLLED_BACK`。

## PDF Vision

1. 模式只看 `GEMINI_API_BACKEND`，不看 key 是否存在。
2. Vertex 需要顯式 `VERTEX_AI_PDF_LOCATION` 與 converter SA ADC。
3. Portal 的 `PDF_CONVERTER_ENGINE=gemini_vision` 介面不變；provenance 的 `conversion_gemini_backend` 必須標示 `DEVELOPER_API` 或 `VERTEX_AI`。
4. Vision 未完成時阻擋發佈，不要降級成純文字。
5. Lab 現行 converter 是 `teams-pdf-converter-00008-zrb`（同一映像 `eba3c8e-vertex-vision2`，`GEMINI_MODEL=gemini-3.8-flash`）。最小 fixture 在 `tests/fixtures/pdf-vision/`（`selectable-text.pdf`、`scan-like.pdf`、`simple-table.pdf`、`mixed-text-image.pdf`）。四份 live `POST /api/v1/convert-pdf` 皆 HTTP 200，`generateContent` 對 `us` `gemini-3.8-flash` 皆 200（不是 404），markdown 含標記原文。不要把 `gemini-flash-latest` 寫回 Vertex `us`。

## File Search（選項 A）

Vertex 部署必須同時關閉 sync 與 parity。正式查詢維持 `HYBRID`。Developer API 環境仍可用既有 File Search store。Vertex 不得用 SA 或殘留 key 呼叫 `fileSearchStores/...`。

## 驗收與回退

- Live Vertex smoke：僅在程序環境已有明確 `VERTEX_AI_PROJECT`、`VERTEX_AI_CHAT_LOCATION`、`VERTEX_AI_EMBEDDING_LOCATION` 時執行 `scripts/vertex_sa_smoke.py`。缺少任一變數就略過，不算成功。不要用 `gcloud` 預設 project，也不要為了 smoke 載入 API key。
- BU 回退首選同樣使用 Vertex SA 的舊 revision／release。程式保留 Developer API **不代表** BU 可切回 key。
- 告警標籤用角色、模型、project／location、SA、error class。不要放個資或原始提示。

## Lab 安全切換序列（import → re-plan → apply → smoke）

> Lab 已於 2026-09-24 依此序列完成 import + targeted apply + gcloud Portal／Backoffice 補丁。`global` 仍是未核准占位。  
> **不要**對 leftover key IAM 跑 `terraform destroy -target`：該圖會連 Adapter／Portal。用 `gcloud secrets remove-iam-policy-binding`，必要時再 `terraform state rm`。不要把 pointer 切回缺 provenance 的 Developer API release。Lab 現行相容 release 是 `release-8535419976b4`。

在 `infra/terraform`、lab backend `infra/environments/poc/backend.hcl`、tfvars `project_id=itr-aimasteryhub-lab`／`region=asia-east1`：

```bash
# 0) 只讀確認 live converter digest／URL，與 tfvars pin 一致。不要改 image。
PROJECT=itr-aimasteryhub-lab
REGION=asia-east1
gcloud run services describe teams-pdf-converter \
  --project="${PROJECT}" --region="${REGION}" \
  --format='value(status.latestReadyRevisionName,spec.template.spec.containers[0].image)'
# Portal Vision URL 仍是 https://teams-pdf-converter-jt7pjdeeoa-de.a.run.app
# Live converter ready revision 是 teams-pdf-converter-00008-zrb
# （tag eba3c8e-vertex-vision2，digest sha256:6c00f9f11a93f9f8a756c9ed9fadcb9f9b1dbd6ce28282d82a6fb005ace683a3，
#  GEMINI_MODEL=gemini-3.8-flash）。
# Terraform pdf_converter_image 已 pin 同一 live digest
# sha256:6c00f9f11a93f9f8a756c9ed9fadcb9f9b1dbd6ce28282d82a6fb005ace683a3
# （poc terraform.tfvars.example + 本機 terraform.tfvars）。不要為了對齊而去套用 BigQuery drift。

# 1) Import-first。未 import 就 apply 會 *create* 已存在的 teams-pdf-converter。
terraform -chdir=infra/terraform init \
  -backend-config=../environments/poc/backend.hcl -input=false -reconfigure
terraform -chdir=infra/terraform import 'google_service_account.pdf_converter[0]' \
  "projects/${PROJECT}/serviceAccounts/teams-pdf-converter@${PROJECT}.iam.gserviceaccount.com"
terraform -chdir=infra/terraform import 'google_cloud_run_v2_service.pdf_converter[0]' \
  "projects/${PROJECT}/locations/${REGION}/services/teams-pdf-converter"
terraform -chdir=infra/terraform import \
  'google_cloud_run_v2_service_iam_member.portal_invokes_pdf_converter[0]' \
  "projects/${PROJECT}/locations/${REGION}/services/teams-pdf-converter roles/run.invoker serviceAccount:teams-knowledge-portal@${PROJECT}.iam.gserviceaccount.com"

# 2) 立刻 re-plan。套用前必須全部成立：
#    - converter / Portal / Agent / Backoffice 是 in-place update，不是 create/replace
#    - Portal 維持 gemini_vision + live converter URL
#    - 各 Gemini 呼叫者：GEMINI_API_BACKEND=VERTEX_AI，無 GOOGLE_API_KEY
#    - google_secret_manager_secret.google_api_key 為 no-op（不銷毀資源）
#    - File Search sync/parity = false/false
#    - 若 plan 仍要重建 BigQuery operational_events 或新建 ingestion bucket，那是範圍外 drift，不要當成「只切 Vertex」
terraform -chdir=infra/terraform plan -input=false -no-color

# 3) Lab 已 targeted apply Vertex API／aiplatform.user／Agent／Converter。
#    Portal／Backoffice 用 gcloud --update-env-vars（Portal 加 --remove-secrets=GOOGLE_API_KEY）。
#    不要套用完整 plan（BigQuery replace、ingestion bucket、Backoffice token／timeout）。
#    套用後 describe 確認無 key 掛載。Ready revisions（2026-09-24 Agent 工作樹映像後）：
#    teams-rag-agent-00054-677、teams-knowledge-portal-00042-bmj、
#    teams-pdf-converter-00008-zrb、teams-ai-ops-backoffice-00055-qf4
#    Portal 映像：teams-knowledge-portal:eba3c8e（現行工作樹；VERTEX_AI、無 key、
#    File Search A off、gemini_vision + https://teams-pdf-converter-jt7pjdeeoa-de.a.run.app）。
#    Converter 00008-zrb 為 env-only pin GEMINI_MODEL=gemini-3.8-flash
#    （同一映像 eba3c8e-vertex-vision2）；env 是 VERTEX_AI／us／無 GOOGLE_API_KEY。
#    Agent 映像：teams-rag-agent:eba3c8e-wt（現行工作樹；image-only deploy，
#    未用 --set-env-vars；env 與 00053-jdp 相同：PORTAL／HYBRID／File Search
#    gemini-3.5-flash-lite／GCS pointer／VERTEX_AI／us／無 key mount）。

# 4) Smoke：只在 *程序環境* 已有明確三變數、且未注入 GEMINI_API_KEY／GOOGLE_API_KEY 時執行。
#    不要從 .env、gcloud 預設 project、terraform global 或 ADC quota project 推導。
# unset GEMINI_API_KEY GOOGLE_API_KEY
# export GEMINI_API_BACKEND=VERTEX_AI
# export VERTEX_AI_PROJECT=...          # BU 核准值
# export VERTEX_AI_CHAT_LOCATION=...    # BU 核准值，不是 asia-east1 或未核准 global
# export VERTEX_AI_EMBEDDING_LOCATION=...
# python3 scripts/vertex_sa_smoke.py
```

`deploy/deploy-gcp.sh`／`deploy-portal.sh`／`deploy-backoffice.sh` 現在會卸載現有 `GOOGLE_API_KEY`／`GEMINI_API_KEY` 掛載並檢查 `VERTEX_AI`。缺顯式 `VERTEX_AI_PROJECT`、空白 location 或未核准占位 `global` 時會立刻失敗，不會從 `PROJECT_ID`／`project_id` 推導。`--set-env-vars` 不會清掉 secret mount；Agent 既有 revision 走 `deploy_cloud_run_preserving_runtime`（image + `--update-env-vars` + `--remove-secrets`），Portal／converter 仍把 `--remove-secrets` 寫進同一 update，避免 VERTEX_AI+key 過渡 revision。既有 Agent 不會用腳本預設覆蓋 PORTAL／release pointer／File Search。Backoffice 在 Portal 接線後會再 assert。未卸載就部署會讓 Vertex 程序因殘留 key 而 fail closed。這些腳本仍**不要**在未核准時執行。

## Lab eval／Audit Logs（2026-09-24）

- Frozen 3-case L3 subset 已對 `release-8535419976b4` 用 Vertex ADC／`us`／無 key 跑完：報告 `data/eval/reports/rag-l3-v3-blind-subset-vertex-release-8535419976b4.json`。answerAccuracy 0.67、citationPrecision 0.89、ACL leakage 0、Total P95 6208 ms。與 Developer API `release-713b5b02dfc2` 的 1.00／1.00 比較**無效**（不同 release；Vertex 不能載入 713，Developer API 不能載入 853）。未重跑、未改 judge。
- 156-case frozen L3 **已跑完**（exit 0，約 535 s）：同一命令，報告 `data/eval/reports/rag-l3-v3-blind-full-live-vertex-release-8535419976b4.json`。853 分數：answer 92.95%、citation P 95.62%、citation R 95.83%、ACL leakage 0、Total P95 4667 ms、failureCount 14。provenance `VERTEX_AI`／lab／`us`／無 API key。沒有同 release 156-case 基線；與規格 2.4／`release-4f49088db9ca` 比較**無效**。
- project-level DATA_ACCESS：IAM `auditConfigs` 已開。查詢用 `_AllLogs`。**已引用** Agent SA：`teams-rag-agent@itr-aimasteryhub-lab.iam.gserviceaccount.com`／`PredictionService.GenerateContent`／`2026-09-24T10:24:15.947668623Z`（chat `vertex-sa-audit-20260924T102408Z`）。**已引用** Converter SA：`teams-pdf-converter@itr-aimasteryhub-lab.iam.gserviceaccount.com`／`PredictionService.GenerateContent`／`gemini-3.8-flash`／`2026-09-24T10:43:25.110507349Z`。**已引用** Backoffice SA：`teams-ai-ops-backoffice@itr-aimasteryhub-lab.iam.gserviceaccount.com`／`PredictionService.GenerateContent`／`gemini-3.8-flash`／`2026-09-24T11:04:27.667092863Z`（inline `REAL_RAG` `run_5c60ec7f9a3e`；同 run 11:04:32Z 第二筆）。Portal SA 列仍缺：`import-pdf` 只呼叫 converter；未 reindex。`AI_OPS_WORKERS_ENABLED=false`，未另建 worker fleet。list-valued `answer.content` 的 `.lower()` crash **已修**：`00055-qf4`（tag `eba3c8e-content`）上 `run_5be59fbc0b1a` HTTP 202／`COMPLETED`，兩側 `COMPLETED`／`HALLUCINATION`（answer 為 string；**沒有** `'list' object has no attribute 'lower'`）。這**不是**品質通過，也**不是** 156-case 閘門。
- live PDF Vision：converter `00008-zrb` 對 `tests/fixtures/pdf-vision/{selectable-text,scan-like,simple-table,mixed-text-image}.pdf` 四次 `POST /api/v1/convert-pdf` 皆 HTTP 200（ZIP markdown `**Model:** gemini-3.8-flash`，各含標記原文）。Portal `import-pdf?async_mode=sync` 匯入 `scan-like.pdf` HTTP 200，`conversion_engine=gemini_vision`、`conversion_gemini_backend=VERTEX_AI`，未降成 `legacy_text`。Vertex `us` 對 `gemini-3.8-flash:generateContent` 回 200；log `Successfully extracted text from 1 pages`。未切 `release-8535419976b4`。§7 逾時／403／429 仍未跑。
- Terraform：`pdf_converter_image` 已 pin live `00008-zrb` digest。converter targeted plan 為 **No changes**（`lifecycle.ignore_changes` 含服務層 `scaling`）；**未套用**。BigQuery `operational_events` replace 與 ingestion bucket **未套用**。

Terraform 在 `deployment_phase` 為 `activate`／`full` 時同樣 fail closed：必須在 tfvars 寫入 `vertex_ai_project` 與核准的 chat／embedding location（Vision／converter 啟用時還要 `vertex_ai_pdf_location`）。不得把 `project_id` 當成 Vertex project，也不得寫 `global`。

