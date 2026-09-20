# 專案架構複查：Phase-2 治理（非大拆）

> 複查日期：2026-09-21
> Git 基準：`666b84e`（working tree 含 Phase-2 governance 進行中變更）
> 前次文件基準：`fix/rag-ranking-contract-closeout@c3bc708`／舊複查結論已過時
> 範圍：Teams Adapter、Agent/RAG Runtime、Knowledge Portal、AI Ops Backoffice、React Console、composition、contracts、CI、評測可信度與觀測
> 性質：依目前原始碼、架構閘門與 live Layer-3 評測重新判定

---

## 1. 結論先行

目前狀態**已不是「架構爆炸、需要再大拆一次」**。CI、architecture ratchet、跨套件所有權邊界與 OpenAPI／前端 generated client 自動檢查均已就位。Backoffice、Portal 不再直接依賴 Agent runtime；主要套件無反向／循環依賴（`citation_asset_gateway` ↔ `teams_agent` 殘餘 SCC 已 allowlist，並以 importer-count ratchet 控管）。

因此**不建議**：

- 再做一次大規模目錄重組
- 現在拆成兩個 repo
- 更換向量資料庫
- 直接導入 GraphRAG
- 全流量啟用昂貴 reranker

現在進入 **第二階段治理**：維持現有架構，針對評測可信度、RAG 長尾延遲、領域規則與架構閘門涵蓋率做精準優化。

最值得投入的四件事：

1. **可信評測**（blind holdout + Layer-3 telemetry 完整）
2. **生成／relevance 延遲**（query-tier token budget、relevance LLM audit、TTFT）
3. **可配置知識關係**（淘汰硬編碼 evidence injection）
4. **Production observability**（集中式 SLI，而非 process-local counter）

---

## 2. 目前品質閘門（權威狀態）

| 驗證項目 | 結果 | 說明 |
|---|---:|---|
| Architecture ratchet | 通過 | 含 `citation_asset_gateway` package root；`operations_core`／CAG importer-count baselines |
| Production file size | 通過 | 無 >500 行 production source |
| New function size | 通過 | 無 >80 行新 Python function |
| Ownership edges | 通過 | Backoffice／Portal → Agent = 0；`ai_ops_backoffice→operations_core` ≤158；`agent_service→operations_core` ≤17；`teams_agent→citation_asset_gateway` ≤19 |
| OpenAPI / generated client / wire contracts | 通過 | 自動漂移檢查 |
| RAG + frontend monorepo | 適合 | 暫不拆庫 |

> 舊文件中的 confidence／query-tier regression、`run_retrieve` 82 行失敗，已在後續 closeout 修復；勿再當作現行 P0。

---

## 3. P0：評測可信度

### 3.1 Development vs Blind

| 集合 | 路徑 | 角色 |
|---|---|---|
| Development / regression | `data/eval/retrieval_eval_v2.json` | 可依實際輸出修正標籤；**不是**發布閘門 |
| Release holdout | `data/eval/retrieval_eval_v3_blind.json` + `retrieval_eval_v3_blind_protocol.json` | 凍結前填滿並第二人審核；`frozen=true` 後禁止因看結果改標 |

Blind coverage（2026-09-21，`freezeVersion=1`）：

- 156/156 slots 已填並凍結；`reviewerSignoff` 已簽署（獨立 corpus-only 審核 APPROVE_FREEZE）
- 數值覆蓋：answerable≥50、no-answer+hard-negative=50、multi-turn=20、typo/alias/short=20；source_scope／negative 齊備
- ACL：corpus 無 group-gated 文件，以 `acl_coverage_gap` 標註已知缺口；version 以 `related_document_discrimination` 覆蓋姊妹文件對照
- 凍結後禁止因看模型輸出改標；機械驗證：`scripts/validate_retrieval_eval_v3_blind.py`

### 3.2 Layer-3 telemetry

下列欄位曾在舊 live report 中常為零（flatten 前）：

- `candidateEvidenceRecallAt24` / `candidateRecallAt24`
- `fastPathRate` / `approxCacheHitRate`
- `avgFacetCount` / `avgBatchEmbeddingMs`

Eval 腳本已從 `RetrievalTrace` 重建 cand@24，並扁平化 L2 pipeline keys。新 live run 應驗證非零（cache hit 在冷啟動單次仍可能為 0，屬預期）。

---

## 4. P1：生成與 relevance 長尾（非 retrieval）

最新 live 量級（代表值）：

| 階段 | P50 | P95 |
|---|---:|---:|
| Retrieval | ~479 ms | ~713 ms |
| Relevance | ~0.2 ms | ~1.9 s |
| Generation | ~2.0 s | ~5.3 s |
| Total | ~2.5 s | ~6.0 s |

優化順序：

1. **Query-tier evidence budget**（已落地預設）：trivial 500／standard 800／hard 1200（`RAG_EVIDENCE_TOKEN_BUDGET_*`）
2. **Relevance LLM audit**：`rag_relevance_llm_calls`／`_flipped`／`_unchanged`／deterministic skips；trivial tier 跳過 LLM
3. **回答策略**：明確問題只答主情境；主要來源 2–3；延伸改追問（ANSWER_PROMPT rule 16）
4. **TTFT／queue／streaming／claim-repair**：觀測缺口，下一輪 dashboard

Injection retirement：

- Catalog：`data/ops/knowledge_relationships.json`
- Runtime loader：`agent_service.knowledge_relationships`
- Hardcoded markers 僅在 catalog 缺失時 fallback
- **Retirement metric**：blind set 在不啟用 injection 時仍通過後，才刪 catalog 與 fallback

---

## 5. P1／P2：架構閘門與 hotspot

已完成／進行中：

- `operations_core` importer-count ratchet（backoffice、agent_service）
- `citation_asset_gateway` 納入 `PACKAGE_ROOTS`／ownership／allowed residual cycle with `teams_agent`
- 不以「接近 500 行」為拆檔理由；後續 hotspot 報告應結合行數 × 近期修改 × 作者數 × fan-in

Observability：`rag_observability` 仍為 process-local；Cloud Run 多 instance 需 OTel／集中後端 export（P2）。

壓力測試：現行 concurrency 報告樣本過小；正式矩陣見 Phase-2 計劃（concurrency 1–32、≥5–10 分鐘）。

---

## 6. 建議工作順序（現行）

1. 填滿並第二人審核 `retrieval_eval_v3_blind`，再凍結
2. 重跑 Layer-3 live，確認 telemetry 欄位可觀測
3. Generation／relevance／TTFT dashboard
4. 依 tier 與 audit 數據擴大 deterministic relevance boundary
5. Portal 管理 knowledge relationships；blind 通過後移除 temporary inject
6. 正式 Cloud Run 壓力測試
7. P3：Teams bot client deprecated 升級期限追蹤

---

## 7. 最終判定

架構邊界與自動化看門已足夠支撐演進；**不需要結構性大重構**。在 blind holdout、生成長尾、可配置知識關係與 production SLI 完成前，不應以 v2 開發集上的 100% Acc／CiteP 作為發布依據，也不應啟用全流量 reranker 或 GraphRAG。
