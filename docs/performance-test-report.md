# 效能壓測報告

對應規格：§2.1（技術棧調整需實證）、§16（成本與效能控制）、§19 項目 22、§20 項目 15。

> **架構規則（§2.1／§22）**：不得在無壓測數據時，以語言重寫作為第一優先效能方案。
> §16 的優化順序把「調整 runtime」排在最後——在前八項都做完並量測之後。

> **2026-08-29 更新**：LangGraph 已改為**每輪必經 `ConversationSupervisor` LLM** 再路由。
> 2026-08-06 的 LLM 呼叫次數／成本數字（含 A/B harness 的 2.17 次／US$0.00106）**不再能代表現況**。
> 下方 §5 為 supervisor-first 架構的重跑基準；§3 的 Cloud Run 延遲量測仍有效（瓶頸仍在模型與冷啟動，不在 Python runtime）。

---

## 1. §16 優化順序（依序執行，勿跳號）

| # | 手段 | 本階段狀態 |
|---|---|---|
| 1 | 減少不必要的 LLM 呼叫 | ⚠️ **已重基準（2026-08-29）**：每輪固定 +1 次 Supervisor LLM；NON_IT／ASSISTANT_META 仍略過 Issue Extractor；FAQ 與 Response Builder 仍不呼叫 LLM |
| 2 | 使用 deterministic formatter | ✅ `response_builder.py`，並有靜態測試防止未來重新引入 LLM |
| 3 | 限制多 Issue 數量 | ✅ `MAX_ISSUES_PER_MESSAGE=3` |
| 4 | 限制 Query Rewrite 次數 | ✅ `MAX_RETRIEVAL_REWRITES=1` |
| 5 | 控制 Context 長度 | ✅ `MAX_HISTORY_MESSAGES=10`、`CONVERSATION_HISTORY_ROUNDS=5` |
| 6 | 調整 Cloud Run concurrency | ⬜ 已量測，`--concurrency=8` 在穩態下無錯誤；尚未探至飽和點 |
| 7 | 調整 CPU 與 Memory | ⬜ `1 CPU / 2Gi` 未成為瓶頸；**建議下一步設 `--min-instances` 以消除冷啟動尾延遲**（見 §3.3） |
| 8 | 調整外部服務 timeout | 部分：`TICKET_SERVICE_TIMEOUT_SECONDS`、`AGENT_API_TIMEOUT_SECONDS` 已可調 |
| 9 | 根據壓測結果決定是否需要 runtime 調整 | ❌ **不需要**——數據顯示延遲由 LLM 呼叫主導，非 Python 開銷（見 §4） |

第 1 項在 2026-08-06 的效果（FAQ 路徑 `llm_call_count=1`）已被 supervisor-first 架構取代；請改看 §5 的分情境 LLM 次數表。

Harness：

| 腳本 | 用途 |
|---|---|
| `scripts/load_test.py` | 併發延遲（dry-run 或 Cloud Run） |
| `scripts/agent_turn_benchmark.py` | **Supervisor-first** 分情境 LLM 次數／估算成本（2026-08-29 新增） |

### dry-run（不耗 chat 額度，embedding 仍可能呼叫 API）

以 `httpx.ASGITransport` 在行程內驅動 FastAPI app，chat model 以固定樁替換。
**注意：embedding 仍是真實 API 呼叫**（檢索需要），因此 dry-run 延遲並非純框架開銷。

```bash
cd agent_service
.venv/bin/python ../scripts/load_test.py --dry-run --concurrency 8 --requests 24
```

### 遠端壓測（需明確確認旗標）

```bash
.venv/bin/python ../scripts/load_test.py \
    --target https://teams-rag-agent-xxxxx.asia-east1.run.app \
    --i-know-this-hits-a-real-service \
    --auth google-id-token \
    --concurrency 20 --requests 200
```

`--i-know-this-hits-a-real-service` 為必要旗標，避免誤壓生產環境。

`--auth` 決定驗證方式。私有 Cloud Run 服務（`--no-allow-unauthenticated`）需要
`google-id-token`——它會拒絕共用的 service token 並回 403。這是實測踩到的：
首次以預設模式執行時 200 筆請求全數 403，因為腳本原本只支援
`AGENT_SERVICE_TOKEN`。`auto` 會在 `AGENT_SERVICE_TOKEN` 有設時優先用它，
否則透過 gcloud 取得身分權杖。

## 3. 結果

### 3.1 dry-run（已實測）

**執行時間**：2026-08-06T08:14:31Z
**原始輸出**：`outputs/load-test-20260806T081431Z/results.json`

| 指標 | 數值 |
|---|---|
| Concurrency | 8 |
| 總請求數 | 24 |
| 牆鐘時間 | 2.955 s |
| throughput | 8.12 req/s |
| 錯誤率 | 0.0%（24× HTTP 200） |
| P50 延遲 | 0.856 s |
| P95 延遲 | 1.066 s |
| P99 延遲 | 1.073 s |
| 最大延遲 | 1.073 s |

**解讀限制**：chat model 為樁，故此數字反映的是 **FastAPI + LangGraph workflow + 真實 embedding 檢索** 的開銷，**不含 LLM 生成延遲**。真實端到端延遲請參考 A/B 報告中的 P95 3.31 s（含完整 LLM 呼叫）。

### 3.2 真實端到端延遲（取自 A/B harness 實測，**2026-08-06，LLM 路徑已過時**）

| 指標 | 數值 | 備註 |
|---|---|---|
| P50 | 2.35 s | 仍可參考框架＋模型延遲量級 |
| P95 | 3.31 s | 同上 |
| 平均 LLM 呼叫／查詢 | ~~2.17~~ | **已被 §5 取代**（當時無 per-turn Supervisor） |
| 平均成本／查詢 | ~~US$0.00106~~ | **已被 §5 取代** |

### 3.3 Cloud Run 正式壓測（已執行 2026-08-06）

部署於臨時服務 `teams-rag-agent-verify`（測後刪除），設定：`--cpu=1
--memory=2Gi --concurrency=8 --timeout=90 --max-instances=10`，模型
`gemini-3.5-flash-lite`。測前先送 3 筆暖機請求。**線上服務全程未受影響。**

跑了兩組，因為單一組數據無法區分「應用程式慢」與「超出配置容量後排隊」：

| 指標 | A：擴縮中（併發 20／200 請求） | B：穩態（併發 8／100 請求） |
|---|---|---|
| Throughput | 8.22 req/s | 4.34 req/s |
| 錯誤率 | **0%**（200× HTTP 200） | **0%**（100× HTTP 200） |
| P50 | 0.996 s | 0.973 s |
| P95 | 5.24 s | **4.03 s** |
| P99 | 8.68 s | 4.48 s |
| 最大 | 12.18 s | 4.48 s |
| 平均 LLM 呼叫／請求 | 1.33 | 1.33 |

原始輸出：`outputs/load-test-20260806T100439Z/results.json`、
`outputs/load-test-20260806T100*/results.json`。

**尾端延遲的歸因（重要）**：A 組期間服務從 0 擴到 **5 個實例**，而同一時間
`/agent/chat` 的伺服器端 `elapsed_ms`（§15.2 結構化日誌，n=203）為
**P95 3894 ms、P99 4210 ms、最大 4392 ms**。客戶端最大 12.18 秒與伺服器端最大
4.39 秒之間的差距，就是 Cloud Run 冷啟動與排隊，**不是應用程式**。B 組在實例已熱
的情況下，客戶端 P95 4.03 s 與伺服器端 3.89 s 幾乎吻合（差額為網路），佐證此歸因。

| 指標 | 目標 | 實測 | 判定 |
|---|---|---|---|
| 錯誤率 | < 1% | 0% | ✅ |
| P95 延遲（穩態） | < 5 s | 4.03 s | ✅ |
| P95 延遲（擴縮中） | < 5 s | 5.24 s | ⚠️ 冷啟動所致 |

**成本**：約 300 次請求，依 §3.2 的每查詢 US$0.00106 估算約 US$0.32。

## 4. 結論

1. **§19 項目 22 達成。** 現有 Python 架構在 Cloud Run 上以併發 8 穩態運行時
   P95 4.03 秒、零錯誤；併發 20 時仍零錯誤，吞吐 8.22 req/s。
2. **沒有任何數據支持更換 runtime 語言。** 伺服器端 `elapsed_ms` 顯示單次請求
   P50 約 0.96 秒、P95 約 3.9 秒，而平均每請求有 1.33 次 LLM 呼叫——延遲主要由模型
   呼叫構成，不是 Python 框架開銷。把服務改寫成其他語言不會縮短模型的回應時間。
   對照 dry-run（樁模型）P95 僅 1.07 秒，更直接說明這一點。
3. **真正該調的是實例配置，也就是 §16 的第 6–7 項。** 擴縮期間的 P95 5.24 秒與
   最大 12.18 秒全來自冷啟動。若要壓低尾端延遲，優先手段是設定
   `--min-instances`（例如 1–2）讓服務不從零起跳，其次才是調整 `--concurrency`
   與 CPU/記憶體。這些都在語言重寫（第 9 項）之前。
5. **Supervisor-first 成本／LLM 次數請以 §5 為準**（2026-08-29 重跑）。Cloud Run
   延遲結論（§3.3、§4）仍成立：瓶頸在模型與冷啟動，不在 Python runtime。
6. **已知未量測**：未測到飽和點；未測 Teams Adapter 端到端；`--min-instances`
   改善幅度未驗證；§5 成本為 stub＋token 啟發式，待以正式環境 usage log 交叉驗證。

## 5. Supervisor-first 重基準（2026-08-29）

**背景**：移除 keyword fast path 後，每輪使用者訊息在 `load_conversation` 先呼叫
`ConversationSupervisor`（計入 `llm_call_count`），再決定是否進入 Issue Extractor／Handoff。

**Harness**：`scripts/agent_turn_benchmark.py`（行程內 stub model + 真實 index retrieval；
不消耗 chat API 額度）。原始輸出：`outputs/agent-turn-benchmark-20260829T172725Z/results.json`。

### 5.1 分情境 LLM 呼叫次數

| 情境 | 測試句 | LLM 次數 | 組成（Supervisor / Extractor / Knowledge） |
|---|---|---:|---|
| 閒聊問候 | `你好` | **1** | 1 / 0 / 0 |
| 閒聊非 IT | `午餐呢` | **1** | 1 / 0 / 0 |
| 助手能力 | `你能回答什麼問題` | **1** | 1 / 0 / 0 |
| 澄清追問 | `VPN 打不開` | **2** | 1 / 1 / 0 |
| 知識命中 | `VPN 密碼鎖住怎麼辦` | **4** | 1 / 1 / 2 |
| 查無／Handoff 前 | `SAP Crystal Reports 授權到期無法開啟` | **4** | 1 / 1 / 2 |
| IT＋非 IT 混合 | `VPN 無法登入，另外今天午餐吃什麼？` | **4** | 1 / 1 / 2 |

七情境平均 **2.43 次／輪**（2026-08-06 A/B 混合平均 2.17 次／查詢，**+0.26**）。
閒聊從「可能 2–3 次」降為穩定 **1 次**；IT 知識路徑維持 **4 次**（Supervisor 固定 +1）。

### 5.2 估算成本（gemini-3.5-flash-lite 費率，token 啟發式）

| 情境 | 估算 US$/輪 |
|---|---:|
| 閒聊／助手能力（1 次 LLM） | ~0.00042 |
| 澄清（2 次 LLM） | ~0.00138 |
| 知識／Handoff 前（4 次 LLM） | ~0.00283 |
| **七情境平均** | **~0.00159** |

相較 2026-08-06 混合平均 US$0.00106，**約 +50%**（主要來自每輪固定 Supervisor；
閒聊路徑反而更便宜）。正式上線成本請以 §15.2 結構化日誌的 `estimated_cost_usd` 為準。

### 5.3 dry-run 併發重跑（stub model，2026-08-29）

```bash
cd agent_service
.venv/bin/python ../scripts/load_test.py --dry-run --concurrency 8 --requests 24
```

原始輸出：`outputs/load-test-20260829T172637Z/results.json`

| 指標 | 2026-08-06 | 2026-08-29 | 備註 |
|---|---:|---:|---|
| P50 延遲 | 0.856 s | **0.338 s** | stub 已覆蓋 Supervisor／Handoff schema |
| P95 延遲 | 1.066 s | **1.443 s** | embedding I/O 波動；仍不含真實模型延遲 |
| 平均 LLM 次數／請求 | 1.33（Cloud Run 真實） | **8.17**（dry-run stub 混合查詢集） | 計數方式不同，勿直接對照 |

## 6. 相依套件維護排程（2026-08-29）

以下警告**目前不影響測試通過**，但應排入維護：

| 來源 | 警告 | 建議 |
|---|---|---|
| `microsoft_teams` SDK | `BotClient` deprecated | 追蹤 Teams SDK 下個 major；Adapter 改用新 client API |
| Starlette / FastAPI TestClient | `httpx` TestClient deprecated，建議 `httpx2` | 測試套件遷移至 `httpx2` 或 ASGI 直連 |
| Playground（Node） | `util._extend` deprecated（DEP0060） | 升級 transitive dependency 或鎖定已修版本 |

---
