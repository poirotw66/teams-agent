# Retrieval A/B Test 報告

對應規格：§8.3（Gemini File Search 僅作為候選 Adapter）、§18.7（Retrieval A/B Test）、§20 項目 14。

> **結論規則（§8.3／§18.7）**：A/B Test 完成並證明品質、成本或維運具有明顯優勢前，**Hybrid RAG 維持預設**。
> 目前狀態：**Hybrid 為預設（`KNOWLEDGE_SERVICE_MODE=HYBRID`）**。
>
> **Task 18 更新（2026-08-07）**：Task 17 把 ACL、圖片對應、slug↔標題對照、成本量測四個模組接上
> `GeminiFileSearchKnowledgeService`，但當時只用單元測試與零星手動探測驗證，沒有對真實 store 重新跑
> 完整 30 案例。本次任務把這件事做完：建立全新 store、以
> `scripts/gemini_file_search_spike.py upload` 上傳全部 19 份語料（含 ACL metadata）、對兩個後端重
> 跑同一組 30 案例，並另外跑一個**專用的 ACL 驗證探測**（見第 2.3 節）——因為 30 案例評估集裡的兩個
> ACL 案例，語料現況下兩者都預期「找得到」，不足以證明系統真的擋掉未授權存取。跑完即刪除所有本次
> 建立的 store。詳見第 2 節。

---

## 1. 方法

- Harness：`scripts/retrieval_ab_test.py`
- 評估集：`data/eval/retrieval_eval_set.json`（30 案例）
- 兩個後端跑**同一組**評估集：`HybridKnowledgeService`（§8.2）與 `GeminiFileSearchKnowledgeService`（§8.3）
- 計分層為純函式（`score_*`、`percentile`、`aggregate`），由 `agent_service/tests/test_ab_harness.py` 單元測試涵蓋，與 I/O 層分離
- 成本沿用 `agent_service/src/agent_service/usage.py` 既有的 token／計價邏輯（Hybrid）與 `file_search_usage.py`（Gemini，Task 17 新增），不另建第二套價目表
- Task 18 起，harness 額外做兩件事（`scripts/retrieval_ab_test.py::_try_build_gemini_service`／`_run_gemini_case`）：
  1. 從本地索引建立 `FileSearchDocumentRegistry` 並傳入 `GeminiFileSearchKnowledgeService`，讓引用標題與圖片可以正確 join 回真實文件記錄，而不再停留於 ASCII slug。
  2. 把每個案例的 `groups` 帶進 `UserContext`（與 Hybrid 相同做法），並記錄 `service.last_cost_usd`，讓 ACL 路徑與成本量測真正被跑到，而不是預設值。

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
| ACL 案例 | 2 | 同一查詢在有／無群組下的可見性——**見下方 2.3 節「此欄位為何不足採信」** |
| 含圖片文件 | 3 | 對應 `data/assets/` 下實際存在的圖片 |

錯誤碼均取自語料實際文字，未自行編造不存在的錯誤碼。

## 2. 結果

**執行時間**：2026-08-07T03:20:43Z
**設定**：兩個後端使用**同一個模型** `gemini-3.5-flash-lite`、同一組 30 案例、`top_k=4`
**原始輸出**：`outputs/retrieval-ab-test-20260807T032043Z/results.json`
**Gemini store**：19 份語料全數上傳到一個全新建立的 store，A/B 執行完畢後刪除（見 2.4 節）

### 2.1 §18.7 指標對照表

| 指標 | Hybrid | Gemini File Search | 說明 |
|---|---|---|---|
| Answer Accuracy | 100.0% (25/25) | 100.0% (25/25) | 平手 |
| Recall@K | 100.0% (25/25) | 100.0% (25/25) | 平手；Task 17 之後引用標題已是真實中文標題，不再需要 slug 對照才能計分 |
| Groundedness | 100.0% (25/25) | 100.0% (25/25) | 平手 |
| Citation Accuracy | 100.0% (25/25) | 100.0% (25/25) | 平手 |
| No-answer Accuracy | 100.0% (5/5) | 100.0% (5/5) | 兩者都正確拒答 |
| Error-code Accuracy | 100.0% (7/7) | 100.0% (7/7) | 平手 |
| ACL Accuracy（30 案例欄位） | 100.0% (2/2) | 100.0% (2/2) | ⚠️ **此欄位不足以比較兩者**，見 2.3 節 |
| Image Match Accuracy | 100.0% (3/3) | **100.0% (3/3)** | Task 17 接上 registry 後首次量到；此前為 0% |
| P50 Latency | **3.00 s** | 5.71 s | Hybrid 快 1.9 倍 |
| P95 Latency | **4.07 s** | 7.15 s | Hybrid 快 1.76 倍 |
| 平均 LLM 呼叫／查詢 | 2.17 | **1.00** | Gemini 檢索與生成合併為一次呼叫 |
| 平均成本／查詢 | **US$0.001059** | US$0.001804 | Gemini 貴約 1.7 倍（`tool_use_prompt_token_count` 把整份檢索內容計入輸入 token，見 `file_search_usage.py`） |
| 總成本（30 案例） | US$0.0318 | US$0.0541 | |
| 錯誤數 | 0 | 0 | |

八項品質指標（Answer／Recall／Groundedness／Citation／No-answer／Error-code／ACL 30 案例欄／Image）
兩個後端全部 100%，數字本身沒有區分度——這是本報告刻意不畫圖表比較它們的原因（見 README 該節「為
何只畫延遲與成本」）。真正有區分度、且對決策有意義的是延遲與成本，見下方圖表。

### 2.2 圖片對應：Task 17 接線後首次端對端量到

Gemini 的 Image Match Accuracy 這次是 100%（3/3），不是靠 harness 端補的對照表，而是
`GeminiFileSearchKnowledgeService` 本身透過 `registry: FileSearchDocumentRegistry` 把 grounding
chunk 的 slug（例如 `大州系統_功能無法點選`）join 回本地索引記錄到的圖片清單。三個含圖片案例的實際
回傳：

```text
daizhou-cant-click:    大州系統_功能無法點選/p01.png
daizhou-first-setup:   大州首次使用設定/p01.png, 大州首次使用設定/p02.png
hq-ip-phone-panel:     總公司IP話機操作/p02.png
```

與 Hybrid 回傳的圖片路徑一致。代價與先前報告一致：File Search 只回傳「哪一份文件」被引用，不回傳
「哪一個 chunk」，所以圖片對應是文件層級（一份文件的全部圖片都可能被附上），不像 Hybrid 能精準到
chunk。

### 2.3 ACL：30 案例欄位不足採信，改用專用探測

`data/eval/retrieval_eval_set.json` 的兩個 ACL 案例（`cs-vpn-acl-open`、`cs-vpn-acl-other-group`）
**都預期 `expectedFound=true`**，因為語料庫目前每一份文件都是 `audience: all-employees`（見
`docs/knowledge-document-governance.md` 的治理決策——目前系統尚未把真實群組串進使用者的
`groups`，把任何文件設為受限會讓一般查詢直接失敗，因此暫不這麼做）。

結果：**一個完全不檢查權限的後端，一樣會在這兩個案例拿到 100%。** 30 案例 ACL 欄位本身無法告訴
你「Gemini 到底有沒有做權限過濾」——這是 §8.3 舊報告已經指出的問題，Task 18 沒有改變這個事實，因
為改變它需要修改語料庫（不在本任務範圍內，見任務邊界）。

因此改用 `scripts/acl_verification.py` 做**專用**驗證：在一個獨立、用完即刪的 store 裡，直接上傳
一份 `allowed_groups=['cs-team']` 的受限文件與一份公開文件（皆為腳本自建的合成內容，不動
`data/sources/**`），然後**透過 `GeminiFileSearchKnowledgeService.search`（真實 adapter，不是手
刻 filter）**分別以 `groups=['cs-team']` 與 `groups=[]` 查詢，檢查回傳的來源標題與答案內容。

實測結果（2026-08-07，執行後 store 已刪除）：

| 檢查項目 | 結果 |
|---|---|
| `groups=['cs-team']` 能看到受限文件 | ✅ PASS |
| `groups=[]` 看不到受限文件的來源標題（無內容洩漏） | ✅ PASS |
| `groups=[]` 對受限查詢的回答內容不包含受限文件才有的內容 | ✅ PASS |
| `groups=[]` 能看到公開文件 | ✅ PASS |

四項全部通過。**注意一個過程中的假訊號**：第一次執行時，`groups=[]` 查詢受限問題的 `found` 是
`True`（不是預期的 `False`），原因不是 ACL 漏洞，而是這個探測店裡只有兩份極小文件，`top_k=4` 下
File Search 在受限文件被 `metadata_filter` 擋掉後，把僅存的公開文件（內容完全不相關）當作唯一候
選來源附上——`found` 布林值在文件數極少時不是判斷洩漏與否的可靠訊號，真正該檢查的是「受限文件的
標題／內容有沒有出現在無權限使用者看到的結果裡」，改用這個判準後結果穩定通過。這個現象本身也是
一個維運提醒：`found` 的語義會隨語料規模改變，不能只看這一個欄位。

**這代表**：`file_search_acl.py` 的 ACL 強制機制對一個「有真正受限文件」的語料庫是有效的，這是
Task 17 程式碼加上 Task 18 端對端驗證的結論。但這**不等於**現有 30 案例評估集的 ACL 欄位有意
義——語料庫治理決策（全部 `all-employees`）沒有改變，所以那個欄位在語料擴充或群組串接完成之前，
仍然無法用來比較兩個後端。

### 2.4 上傳腳本 ACL 附加路徑：首次真實使用

`scripts/gemini_file_search_spike.py upload` 的 `--index-path` ACL 附加邏輯（讀取
`data/index/chunks.json` 的 `allowed_groups`，轉成 `grp_*` metadata）先前只做過 `--dry-run`。
Task 18 是第一次真實上傳：19 份文件全數成功（`list-documents` 逐一確認 `custom_metadata` 都正確
附上 `grp_public`，因為現有語料全部 `allowed_groups=[]`）。

**過程中的一個操作性教訓**：第一次嘗試上傳時，因為外層 shell 逾時（非腳本本身的問題）在完成前被
中斷，此時已有 16 份文件上傳成功。重跑整個 `upload` 指令會把這 16 份文件**重複上傳**一次（腳本
不會檢查 store 內是否已存在同名文件），造成同一份文件在 store 裡出現兩筆記錄。這不影響 harness
的計分（citation 標題以 `dict.fromkeys` 去重），但持久使用時若上傳流程中斷重試，需要先
`list-documents` 確認、或先整個刪除 store 再重來，否則 store 內容會漂移。本次已刪除受影響的
store，改用全新 store 乾淨上傳一次，最終結果不受影響。這點記錄進第 4 節缺口清單。

## 3. 對結果的誠實解讀

**100% 不代表生產品質。** 需要明確指出的限制：

1. **評估集由本專案依語料撰寫**，屬於「檢索能否找回正確文件」的驗證，存在天花板效應（ceiling effect）。真實使用者的提問會更口語、更含糊、更常跨文件，準確率必然低於此數字。
2. **語料規模小**（19 份文件）。在這個規模下 BM25 + embedding、以及 File Search 的檢索都幾乎不會選錯文件；語料成長到數百份後，此結果不保證成立。
3. **Answer Accuracy 以來源文件是否正確命中為準**，非人工逐字評估回答品質。
4. **30 案例 ACL 欄位仍然不足採信**（見 2.3 節）——語料目前全數標為 `all-employees`，這是既有治理決策，不是本次任務的缺口，但報告中沿用這個欄位會誤導讀者，因此另外跑了專用探測並將其結果與 30 案例欄位分開陳述。
5. **ACL 專用探測用的是合成文件**，不是真實語料，且探測店只有兩份文件——探測驗證的是「機制在有受限文件時是否生效」，不是「現有 19 份語料的存取控制現狀」（現況是全部公開）。

因此本報告的正確用途是：**建立一條可重跑的基線**，讓語料擴充、參數調整或更換檢索後端時能量化比較，而不是宣稱系統已達生產級檢索品質。

## 4. 決策

**維持 `KNOWLEDGE_SERVICE_MODE=HYBRID`**。

### 就品質而言，兩者相當

八項品質指標（Answer／Recall/Groundedness/Citation/No-answer/Error-code/ACL 案例欄/Image）
Hybrid 與 Gemini File Search 全部 100%。Task 17 接上的 ACL、圖片、標題對照、成本量測四個模組，
Task 18 已對一個全新的 19 文件真實 store 重新驗證，結論不變：**檢索與回答品質上，Gemini File
Search 不比 Hybrid 差**，此前「Gemini 缺圖片對應」的觀察已經是 Task 17 之前 adapter 版本的舊
狀態，不適用於現況。

### 維持 Hybrid 的實際理由

1. **延遲**：Hybrid P50 3.00s／P95 4.07s，Gemini P50 5.71s／P95 7.15s，慢 1.8～1.9 倍。這是目前
   兩者之間**唯一**還存在、且沒有被 Task 17/18 解決的量化差距，對 Teams 互動體驗是最直接有感的
   項目。單次呼叫已是 Gemini File Search 最精簡的呼叫形式（1 次 LLM 呼叫 vs. Hybrid 的 2.17
   次），延遲差距推測來自 File Search 服務本身的檢索時間，不是可以靠調整 harness 或 prompt 解決
   的問題。
2. **成本略高**：平均每查詢 US$0.001804 vs. Hybrid 的 US$0.001059，貴約 1.7 倍——差距不大，但
   方向對 Hybrid 有利。
3. **30 案例 ACL 欄位對現有語料無鑑別力**：即使 Task 18 用專用探測證明了機制本身有效（2.3 節），
   語料治理決策（全數 `all-employees`）代表**目前生產環境中沒有任何案例真正測試到 ACL
   在真實內容上的行為**——這是語料與群組串接（§12）尚未就緒的既有限制，兩個後端都受影響，不是
   Gemini 特有的缺口，但也代表「切換後端」不會讓這個限制自動消失或惡化。
4. **維運複雜度**：中文檔名無法直接上傳（需 ASCII slug 中介層）、圖片對應停留在文件層級（不像
   Hybrid 精確到 chunk）、上傳流程若中斷重試會在 store 內留下重複文件（2.4 節），需要額外的操
   作紀律。這些不是「品質差」，而是「多一層要維護的機制」。

### 若要重啟採用評估，下一步

品質層面的缺口已經在 Task 17/18 補完並驗證。剩下真正阻擋切換的是**延遲**與**成本**這兩個可量化但
未必可解的差距，以及 ACL 在真實受限語料上的行為（一旦語料治理決策改變、群組串接完成）需要用真實
文件重跑，而不是依賴本次的合成探測。除此之外，本報告不再列出「尚待實作」的功能缺口——ACL、圖片對
應、引用標題、成本量測四項均已實作並以真實 store 端對端驗證。

### 重現方式

```bash
# 建立 store 並上傳全部語料（腳本會自動處理中文檔名與 ACL metadata）
python scripts/gemini_file_search_spike.py create-store --name ab-eval
python scripts/gemini_file_search_spike.py upload --store <store> data/sources/*.md

cd agent_service
export GEMINI_FILE_SEARCH_STORE=<store>
.venv/bin/python ../scripts/retrieval_ab_test.py \
    --eval-set ../data/eval/retrieval_eval_set.json \
    --backends hybrid,gemini --output-dir ../outputs

# 專用 ACL 驗證（自己建立、上傳、刪除合成文件與 store，不影響上面的 store）
.venv/bin/python ../scripts/acl_verification.py

# 用完後務必刪除 A/B 用的 store
python ../scripts/gemini_file_search_spike.py delete-store --delete --store <store>
```

評估用的 store（A/B 用與 ACL 探測用，共 4 個）皆已於本次執行後刪除——持久保存內部 IT 文件於
Google 端需要資安決策（見 `docs/gemini-file-search-spike.md` 發現 7）。上述指令即可重建。
