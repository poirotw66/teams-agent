# Retrieval A/B Test 報告

對應規格：§8.3（Gemini File Search 僅作為候選 Adapter）、§18.7（Retrieval A/B Test）、§20 項目 14。

> **結論規則（§8.3／§18.7）**：A/B Test 完成並證明品質、成本或維運具有明顯優勢前，**Hybrid RAG 維持預設**。
> 目前狀態：**Hybrid 為預設（`KNOWLEDGE_SERVICE_MODE=HYBRID`）**。完整 30 案例 A/B 已於
> 2026-08-07 執行完畢——品質相當，但 Gemini 慢 2.1 倍，且（在該次 A/B 執行當下）缺 ACL 與
> 圖片對應（§17、§19-12），切換會造成功能退步。詳見第 4 節。
>
> **Task 17 更新**：第 4 節「缺口清單」中列出的 ACL、圖片對應、slug↔標題對照、成本量測
> 四項缺口，已在 Task 17（本次提交）實作並單元測試，見 `gemini_file_search.py`。本節與
> 第 4 節其餘敘述保留原 2026-08-07 執行當下的觀察（品質、延遲數字仍成立），但「不做
> ACL」「不對應圖片」等描述僅適用於 Task 17 之前的 adapter 版本，不適用於現況。這些功能
> **尚未對真實 File Search store 重新做端對端驗證**——見第 4 節缺口清單的最新狀態。

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

**執行時間**：2026-08-07T02:05:07Z
**設定**：兩個後端使用**同一個模型** `gemini-3.5-flash-lite`、同一組 30 案例、`top_k=4`
**原始輸出**：`outputs/retrieval-ab-test-20260807T020507Z/results.json`
**Gemini store**：19 份語料全數上傳（`ab-eval-20260807`，測後刪除）

| 指標 | Hybrid | Gemini File Search | 說明 |
|---|---|---|---|
| Answer Accuracy | 96.0% → **100.0%**（見下） | 100.0% (25/25) | Hybrid 初次失分 1 題，加規則後平手 |
| Recall@K | 100.0% (25/25) | **100.0% (25/25)**※ | ※ 原始計分 0%，見下方「計分假象」 |
| Groundedness | 100.0% (25/25) | 見下方說明 | 同一標題比對問題 |
| Citation Accuracy | 100.0% (25/25) | **100.0% (25/25)**※ | ※ 同上 |
| No-answer Accuracy | 100.0% (5/5) | 100.0% (5/5) | 兩者都正確拒答 |
| Error-code Accuracy | 100.0% (7/7) | 100.0% (7/7) | 平手 |
| ACL Accuracy | 100.0% (2/2) | 100.0% (2/2)❗ | ❗ **此指標無效**，見下方 |
| Image Match Accuracy | 100.0% (3/3) | **0.0% (0/3)** | Gemini adapter 未實作圖片對應 |
| P50 Latency | **2.38 s** | 5.31 s | Hybrid 快 2.2 倍 |
| P95 Latency | **3.20 s** | 6.81 s | Hybrid 快 2.1 倍 |
| 平均 LLM 呼叫／查詢 | 2.17 | **1.00** | Gemini 檢索與生成合併為一次呼叫 |
| 平均成本／查詢 | US$0.00106 | **未量測** | adapter 未回報 usage metadata |
| 錯誤數 | 0 | 0 | |

### Hybrid 唯一失分案例：`gitlab-unlock`（已修正）

初次執行時 Hybrid 的 Answer Accuracy 為 96%（24/25），唯一失分是
`gitlab-unlock`。原文同時記載「系統負責單位：資訊管理處 / 資訊架構部」與
「目前負責人：陳禹安」，Hybrid 只答了人名，Gemini 兩者都答。

**先確認是系統性缺陷還是隨機不穩定**：以同一 prompt 重跑 6 次，只有 4 次包含
負責單位——是**非決定性**，不是 prompt 完全沒涵蓋。加入規則 7（負責單位與負責人
兩者都要列出）後 6/6 全數包含。

以完整 30 案例驗證無回歸後採用（`outputs/retrieval-ab-test-20260807T022308Z/`）：

| 指標 | 規則 7 前 | 規則 7 後 |
|---|---|---|
| Answer Accuracy | 96.0% (24/25) | **100.0% (25/25)** |
| 其餘七項指標 | 100% | 100%（無回歸） |
| P95 Latency | 3.20 s | 3.01 s |

規則的理由寫在 prompt 裡：人員可能異動，單位才是穩定的求助對象——這是知識庫回答
品質的通則，不是為了通過單一測試案例而寫的特例。

### 計分假象：Gemini 的 0% 不是檢索失敗

Harness 原始輸出中 Gemini 的 Recall@K／Groundedness／Citation Accuracy 皆為 **0%**。
這是**標題對不上造成的假象，不是檢索失敗**。

證據：`vpn-455` 案例中 Gemini 回傳的來源是 `VPNQ&A.md`，而評估集期望的是
`VPN常見Q&A問答`——同一份文件，但前者是上傳時被迫使用的 ASCII slug（見
`docs/gemini-file-search-spike.md` 發現 1）。答案內容本身完全正確，Answer Accuracy
100% 也印證了檢索確實命中。

以 slug↔原始檔名對照重新計分後（19 份語料的 slug 無碰撞）：

```text
Gemini Recall@K  (slug-mapped): 25/25 = 100.0%
Gemini Citation  (slug-mapped): 25/25 = 100.0%
```

**這代表兩件事**：檢索品質確實與 Hybrid 相當；但引用層在沒有額外對照表的情況下
不可用，而 §19 項目 11 要求「回覆包含來源文件」，所以這是採用時必須先補的工。

### ACL 100% 是無效指標

兩個 ACL 案例都期望 `found=True`（因為語料目前全部標為 `all-employees`），因此
**一個完全不檢查權限的後端也會得到 100%**。`gemini_file_search.py` 中沒有任何一處
引用 `groups`——它不做 ACL。Hybrid 的 100% 有實質意義，Gemini 的沒有。

在語料補上真正受限的文件、且群組串接完成之前，這個指標無法用來比較兩者。

## 3. 對結果的誠實解讀

**100% 不代表生產品質。** 需要明確指出的限制：

1. **評估集由本專案依語料撰寫**，屬於「檢索能否找回正確文件」的驗證，存在天花板效應（ceiling effect）。真實使用者的提問會更口語、更含糊、更常跨文件，準確率必然低於此數字。
2. **語料規模小**（19 份文件／22 chunks）。在這個規模下 BM25 + embedding 幾乎不會選錯文件；語料成長到數百份後，此結果不保證成立。
3. **Answer Accuracy 以來源文件是否正確命中為準**，非人工逐字評估回答品質。
4. **ACL 僅 2 案例**，且語料目前全數標為 `all-employees`（見 `docs/knowledge-document-governance.md` 的決策說明），實際群組權限尚未串接。

因此本報告的正確用途是：**建立一條可重跑的基線**，讓語料擴充、參數調整或更換檢索後端時能量化比較，而不是宣稱系統已達生產級檢索品質。

## 4. 決策

**維持 `KNOWLEDGE_SERVICE_MODE=HYBRID`**，但理由與本報告前一版不同，必須據實更正。

### 需要更正的先前判斷

前一版（依 2026-08-06 的 4 份文件定性 spike）認為 Gemini File Search 的回答品質有
問題——會用模型通用知識補充公司流程。**那是在 adapter 尚未帶 system instruction 時
觀察到的**。補上之後（commit `b71602e`），30 案例的 Answer Accuracy 是 100%，
No-answer 與 Error-code 皆 100%，slug 對照後 Recall 與 Citation 也都 100%。

**就檢索與回答品質而言，Gemini File Search 與 Hybrid 相當，並沒有比較差。**
先前「spike 讓門檻變高」的說法，在品質這一面上是錯的，在維運面上仍然成立。

### 維持 Hybrid 的實際理由

1. **延遲**：Hybrid P50 2.38s／P95 3.20s，Gemini P50 5.31s／P95 6.81s。快 2.1 倍。
   對 Teams 互動體驗而言這是最直接有感的差異。
2. **已具備的能力會退步**：Gemini adapter 目前**不做 ACL**（§17 明訂不得將未授權文件
   送入回答），**不對應圖片**（§19 項目 12 要求圖片來源可正常顯示，Hybrid 100% 而
   Gemini 0%）。這兩項不是調參數，是要重寫的功能。
3. **引用需要額外對照層**：中文檔名無法直接上傳，slug 也無法直接當來源標題。
4. **成本未知**：adapter 未回報 usage metadata，無法與 Hybrid 的 US$0.00106/query 比較。

### 若要重啟採用評估，缺口清單

| 缺口 | 狀態（Task 17 之後） |
|---|---|
| ACL 強制（§17） | **已實作並端到端驗證**（2026-08-07）。`search()` 一律以 `file_search_acl.filter_for(user_context.groups)` 組出 `metadata_filter`；`enforce_acl=True` 為預設且無法被呼叫端傳入的 filter 繞過（兩者同時給定會 raise，而非靜默合成或丟棄 ACL 子句）。真實 store 驗證：受限文件對 `groups=['cs-team']` 可見、對 `groups=[]` **不可見**（found=False、零來源），公開文件對所有人可見。殘留風險：正確性仍在 adapter 程式碼內，且 `enforce_acl=False` 逃生口只有單元測試。 |
| 圖片來源對應（§19-12） | **已實作並端到端驗證**（2026-08-07）。adapter 接受 `registry: FileSearchDocumentRegistry`，用 slug↔本地文件記錄 join 出圖片（去重、順序穩定、`max_images` 上限對齊 Hybrid）。真實 store 驗證：總公司IP話機操作文件正確回傳 1 張圖，且引用顯示真實中文標題而非 ASCII slug。代價不變：文件層級歸屬，不如 Hybrid 的 chunk 層級精準。 |
| slug↔原始標題對照 | **已實作**（同一個 `registry` 也把 grounding chunk 的 slug 標題映成 `documents.py` 記錄的真實標題；未知 slug 會退化成顯示 slug 本身，不會拋例外）。 |
| 成本量測 | **已實作**：adapter 每次呼叫後以 `file_search_usage.extract_usage`/`estimate_cost` 解析 `usage_metadata`，經 `last_usage`/`last_cost_usd` 曝露並以 INFO 記錄一行結構化 log（含 correlation id）。仍只用單元測試涵蓋，尚未對真實 store 重新量測一組新的每查詢成本數字。 |
| 延遲改善 | 未知是否可控（單次呼叫已是最省的形式），Task 17 未處理。 |

以上四項功能缺口在 Task 17 已完成程式碼與單元測試，但都**沒有**重新對真實 File
Search store 做端對端驗證——本報告前面引用的延遲／成本數字仍是 Task 17 之前、
adapter 尚未接上這些模組時量到的舊數字，不能直接套用於已接線後的行為。若要重啟採用
評估，下一步是拿這個 adapter 對真實 store 重跑一次 A/B（`scripts/retrieval_ab_test.py`），
而不是再重寫功能本身。

### 重現方式

```bash
# 建立 store 並上傳全部語料（腳本會自動處理中文檔名）
python scripts/gemini_file_search_spike.py create-store --name ab-eval
python scripts/gemini_file_search_spike.py upload --store <store> data/sources/*.md

cd agent_service
export GEMINI_FILE_SEARCH_STORE=<store>
.venv/bin/python ../scripts/retrieval_ab_test.py \
    --eval-set ../data/eval/retrieval_eval_set.json \
    --backends hybrid,gemini --output-dir ../outputs
```

評估用的 store 已刪除——持久保存內部 IT 文件於 Google 端需要資安決策（見
`docs/gemini-file-search-spike.md` 發現 7）。上述兩行指令即可重建。
