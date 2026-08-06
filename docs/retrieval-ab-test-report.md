# Retrieval A/B Test 報告

對應規格：§8.3（Gemini File Search 僅作為候選 Adapter）、§18.7（Retrieval A/B Test）、§20 項目 14。

> **結論規則（§8.3／§18.7）**：A/B Test 完成並證明品質、成本或維運具有明顯優勢前，**Hybrid RAG 維持預設**。
> 目前狀態：**Hybrid 為預設（`KNOWLEDGE_SERVICE_MODE=HYBRID`）**，Gemini File Search 尚未取得可比較數據，因此不具備變更預設的依據。

---

## 1. 方法

- Harness：`scripts/retrieval_ab_test.py`
- 評估集：`data/eval/retrieval_eval_set.json`（30 案例）
- 兩個後端跑**同一組**評估集：`HybridKnowledgeService`（§8.2）與 `GeminiFileSearchKnowledgeService`（§8.3）
- 計分層為純函式（`score_*`、`percentile`、`aggregate`），由 `agent_service/tests/test_ab_harness.py` 單元測試涵蓋，與 I/O 層分離
- 成本沿用 `agent_service/src/agent_service/usage.py` 既有的 token／計價邏輯，不另建第二套價目表

### 執行方式

```bash
cd agent_service
.venv/bin/python ../scripts/retrieval_ab_test.py \
    --eval-set ../data/eval/retrieval_eval_set.json \
    --output-dir ../outputs
```

未設定 `GEMINI_FILE_SEARCH_STORE` 時，只跑 Hybrid 並明確標示跳過。

### 評估集組成（30 案例）

| 類型 | 案例數 | 說明 |
|---|---|---|
| 一般知識查詢 | 25 | 期望命中特定來源文件 |
| 應答為「查無資料」 | 5 | 量測 No-answer Accuracy，含語料中確實不存在的 VPN Error -619 |
| 錯誤碼查詢 | 7 | -455、-8、-200、12029、OTP、license 等，皆取自語料實際內容 |
| ACL 案例 | 2 | 同一查詢在有／無群組下的可見性 |
| 含圖片文件 | 3 | 對應 `data/assets/` 下實際存在的圖片 |

錯誤碼均取自語料實際文字，未自行編造不存在的錯誤碼。

## 2. 結果

**執行時間**：2026-08-06T08:13:10Z
**設定**：`model=google_genai:gemini-3.5-flash-lite`、`embedding=google_genai:gemini-embedding-2`、`top_k=4`、`min_score=0.08`
**原始輸出**：`outputs/retrieval-ab-test-20260806T081310Z/results.json`

| 指標 | HybridKnowledgeService | GeminiFileSearchKnowledgeService |
|---|---|---|
| Answer Accuracy | **100.0%** (25/25) | TBD — 未執行 |
| Recall@K | **100.0%** (25/25) | TBD — 未執行 |
| Groundedness | **100.0%** (25/25) | TBD — 未執行 |
| Citation Accuracy | **100.0%** (25/25) | TBD — 未執行 |
| No-answer Accuracy | **100.0%** (5/5) | TBD — 未執行 |
| Error-code Accuracy | **100.0%** (7/7) | TBD — 未執行 |
| ACL Accuracy | **100.0%** (2/2) | TBD — 未執行 |
| Image Match Accuracy | **100.0%** (3/3) | TBD — 未執行 |
| P50 Latency | 2.35 s | TBD |
| P95 Latency | 3.31 s | TBD |
| 平均 LLM 呼叫／查詢 | 2.17 | TBD |
| 平均成本／查詢 | **US$0.00106** | TBD |
| 本次總成本 | US$0.0318（30 案例） | — |
| 錯誤數 | 0 | — |
| 維運複雜度 | 索引在本地建置（`rag-index`），無外部儲存體需依賴；語料與 index 皆在 repo 控制下 | 需管理外部 File Search Store、文件上傳與刪除生命週期 |

### Gemini File Search 側的狀態

本 harness 執行時 `GEMINI_FILE_SEARCH_STORE` 未配置，依設計跳過。

§8.3 的技術 spike 已於 **2026-08-06 實際執行完畢**（完整結果見
`docs/gemini-file-search-spike.md`），但那是 4 份文件的定性探測，**不是**同一組
30 案例的評分，因此上表 Gemini 欄位維持 TBD 而非填入不可比的數字。

Spike 中足以影響採用決策的發現：

1. **語料無法直接上傳**——`upload_to_file_search_store` 把檔案路徑放進 HTTP
   header，非 ASCII 會拋 `UnicodeEncodeError`。19 份文件全為中文檔名，全數失敗。
   需先轉存為 ASCII 檔名，且轉出的 slug 幾乎不具辨識度（「金控入口網密碼變更方式.md」
   → `doc-41c1698e7c60.md`）。
2. **引用品質較差**——grounding chunk 只回 ASCII slug 當 title，`uri` 與
   `document_name` 皆為 `None`，必須另外查 metadata 才能對回原始文件。Hybrid 直接
   回傳真實文件標題與 chunk id。
3. **預設回答違反 §8.4**——會用模型通用知識補充公司流程。這是設定問題：補上自訂
   `system_instruction` 後即正確拒答。若採用，adapter 必須自帶 system instruction。
4. **維運面**——store 生命週期無歸屬慣例（同一把金鑰下已累積 54 個他用 store），
   且會在 Google 端留存內部文件的持久副本，需資安決策。

正面發現：metadata filter 運作正確、錯誤碼 -455 探測命中正確、文件刪除可用
（需 `force=True`）。

## 3. 對結果的誠實解讀

**100% 不代表生產品質。** 需要明確指出的限制：

1. **評估集由本專案依語料撰寫**，屬於「檢索能否找回正確文件」的驗證，存在天花板效應（ceiling effect）。真實使用者的提問會更口語、更含糊、更常跨文件，準確率必然低於此數字。
2. **語料規模小**（19 份文件／22 chunks）。在這個規模下 BM25 + embedding 幾乎不會選錯文件；語料成長到數百份後，此結果不保證成立。
3. **Answer Accuracy 以來源文件是否正確命中為準**，非人工逐字評估回答品質。
4. **ACL 僅 2 案例**，且語料目前全數標為 `all-employees`（見 `docs/knowledge-document-governance.md` 的決策說明），實際群組權限尚未串接。

因此本報告的正確用途是：**建立一條可重跑的基線**，讓語料擴充、參數調整或更換檢索後端時能量化比較，而不是宣稱系統已達生產級檢索品質。

## 4. 決策

依 §8.3／§18.7，變更預設檢索後端需要 A/B 證據。目前 Gemini File Search 側完全沒有數據，**維持 `KNOWLEDGE_SERVICE_MODE=HYBRID`**。

技術 spike 已完成，其結果讓「切換」的門檻變高而非變低：語料上傳需要額外的轉檔層、
引用需要額外的對照層、grounding 需要自帶 system instruction，這三項都是 Hybrid 目前
不需要的工。

下一步若仍要評估切換，順序為：
1. ~~完成技術 spike~~（已於 2026-08-06 完成）
2. 建立長期 store 並補上 ASCII 轉檔與 slug↔標題對照，設定
   `GEMINI_FILE_SEARCH_STORE` 後重跑本 harness 取得同組 30 案例的分數
3. 比較上表全部指標，特別關注 §18.7 明列的 Error-code Accuracy、ACL Accuracy、Image Match Accuracy——這三項是既有 Hybrid 已具備、而 File Search 需證明不退步的能力
4. 一併評估維運複雜度與資料落地政策
