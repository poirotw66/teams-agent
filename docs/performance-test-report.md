# 效能壓測報告

對應規格：§2.1（技術棧調整需實證）、§16（成本與效能控制）、§19 項目 22、§20 項目 15。

> **架構規則（§2.1／§22）**：不得在無壓測數據時，以語言重寫作為第一優先效能方案。
> §16 的優化順序把「調整 runtime」排在最後——在前八項都做完並量測之後。

---

## 1. §16 優化順序（依序執行，勿跳號）

| # | 手段 | 本階段狀態 |
|---|---|---|
| 1 | 減少不必要的 LLM 呼叫 | ✅ FAQ 走純查表不呼叫 LLM（§7.3）；Response Builder 不呼叫 LLM（§5.3）；`MAX_LLM_CALLS_PER_REQUEST` 上限由共用的 `LlmCallCounter` 強制 |
| 2 | 使用 deterministic formatter | ✅ `response_builder.py`，並有靜態測試防止未來重新引入 LLM |
| 3 | 限制多 Issue 數量 | ✅ `MAX_ISSUES_PER_MESSAGE=3` |
| 4 | 限制 Query Rewrite 次數 | ✅ `MAX_RETRIEVAL_REWRITES=1` |
| 5 | 控制 Context 長度 | ✅ `MAX_HISTORY_MESSAGES=10`、`CONVERSATION_HISTORY_ROUNDS=5` |
| 6 | 調整 Cloud Run concurrency | ⬜ 已量測，`--concurrency=8` 在穩態下無錯誤；尚未探至飽和點 |
| 7 | 調整 CPU 與 Memory | ⬜ `1 CPU / 2Gi` 未成為瓶頸；**建議下一步設 `--min-instances` 以消除冷啟動尾延遲**（見 §3.3） |
| 8 | 調整外部服務 timeout | 部分：`TICKET_SERVICE_TIMEOUT_SECONDS`、`AGENT_API_TIMEOUT_SECONDS` 已可調 |
| 9 | 根據壓測結果決定是否需要 runtime 調整 | ❌ **不需要**——數據顯示延遲由 LLM 呼叫主導，非 Python 開銷（見 §4） |

第 1 項的效果可在實測中觀察到：一則同時包含 FAQ 命中與非 IT 問題的訊息，`llm_call_count=1`——FAQ 路徑完全不耗用模型呼叫。

## 2. 方法

Harness：`scripts/load_test.py`，兩種模式。

### dry-run（不耗 API 額度）

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

### 3.2 真實端到端延遲（取自 A/B harness 實測）

| 指標 | 數值 |
|---|---|
| P50 | 2.35 s |
| P95 | 3.31 s |
| 平均 LLM 呼叫／查詢 | 2.17 |
| 平均成本／查詢 | US$0.00106 |

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
4. **已知未量測**：未測到飽和點（未探至錯誤率上升的併發量）；未測 Teams Adapter
   端到端（本次只壓 Agent Service）；`--min-instances` 的實際改善幅度未驗證。
