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

### Gemini File Search 未執行的原因

`GEMINI_FILE_SEARCH_STORE` 未配置，harness 依設計跳過並明確報告。要取得可比數據，需先依 `docs/gemini-file-search-spike.md` 完成 §8.3 的 spike 檢查清單（建立 store、上傳文件、中文查詢、metadata filter、文件刪除），再重跑本 harness。

## 3. 對結果的誠實解讀

**100% 不代表生產品質。** 需要明確指出的限制：

1. **評估集由本專案依語料撰寫**，屬於「檢索能否找回正確文件」的驗證，存在天花板效應（ceiling effect）。真實使用者的提問會更口語、更含糊、更常跨文件，準確率必然低於此數字。
2. **語料規模小**（19 份文件／22 chunks）。在這個規模下 BM25 + embedding 幾乎不會選錯文件；語料成長到數百份後，此結果不保證成立。
3. **Answer Accuracy 以來源文件是否正確命中為準**，非人工逐字評估回答品質。
4. **ACL 僅 2 案例**，且語料目前全數標為 `all-employees`（見 `docs/knowledge-document-governance.md` 的決策說明），實際群組權限尚未串接。

因此本報告的正確用途是：**建立一條可重跑的基線**，讓語料擴充、參數調整或更換檢索後端時能量化比較，而不是宣稱系統已達生產級檢索品質。

## 4. 決策

依 §8.3／§18.7，變更預設檢索後端需要 A/B 證據。目前 Gemini File Search 側完全沒有數據，**維持 `KNOWLEDGE_SERVICE_MODE=HYBRID`**。

下一步若要評估切換，順序為：
1. 依 `docs/gemini-file-search-spike.md` 完成技術 spike
2. 設定 `GEMINI_FILE_SEARCH_STORE` 後重跑本 harness
3. 比較上表全部指標，特別關注 §18.7 明列的 Error-code Accuracy、ACL Accuracy、Image Match Accuracy——這三項是既有 Hybrid 已具備、而 File Search 需證明不退步的能力
4. 一併評估維運複雜度與資料落地政策
