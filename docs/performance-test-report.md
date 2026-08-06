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
| 6 | 調整 Cloud Run concurrency | ⬜ 待正式壓測後決定 |
| 7 | 調整 CPU 與 Memory | ⬜ 待正式壓測後決定 |
| 8 | 調整外部服務 timeout | 部分：`TICKET_SERVICE_TIMEOUT_SECONDS`、`AGENT_API_TIMEOUT_SECONDS` 已可調 |
| 9 | 根據壓測結果決定是否需要 runtime 調整 | ⬜ **無數據前不得進行** |

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
    --concurrency 20 --requests 200
```

`--i-know-this-hits-a-real-service` 為必要旗標，避免誤壓生產環境。

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

### 3.3 Cloud Run 正式壓測

**TBD — 未執行。**

需要條件：已部署的 Agent Service URL、`AGENT_SERVICE_TOKEN`，以及對測試期間 API 成本的核准（依 3.2 的每查詢成本估算，200 次請求約 US$0.21）。

執行後應填入本表：

| 指標 | 目標 | 實測 |
|---|---|---|
| Throughput (req/s) | — | TBD |
| P50 / P95 / P99 延遲 | P95 < 5 s | TBD |
| 錯誤率 | < 1% | TBD |
| Cloud Run concurrency 設定 | — | TBD |
| CPU / Memory | — | TBD |

## 4. 結論

1. 目前**沒有任何數據支持更換 runtime 語言**。依 §2.1 與 §22，在 §16 第 6–8 項（Cloud Run concurrency、CPU/Memory、外部 timeout）調整完並重新量測之前，語言重寫不在討論範圍。
2. 現有 Python 架構在 dry-run 下 concurrency 8 無錯誤、P95 約 1.07 s；含 LLM 的真實 P95 約 3.31 s。延遲主要來自模型呼叫，而非框架——這進一步說明語言重寫不會是有效的優化手段。
3. §19 項目 22（「現有 Python 架構通過定義的效能測試」）目前為**部分達成**：harness 與基線數據已具備，Cloud Run 正式壓測待部署後補齊。
