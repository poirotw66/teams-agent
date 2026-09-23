# 專案架構複查：評測正確性與證據選擇（非大拆）

> 複查日期：2026-09-21
> Git 基準：`b7f3b61`（PR #17 merged；blind closeout + CAG cycle 消除）
> 前次文件基準：Phase-2 governance / `666b84e` 敘述已過時
> 範圍：Teams Adapter、Agent/RAG Runtime、Knowledge Portal、AI Ops Backoffice、React Console、composition、contracts、CI、評測 harness、證據選擇與 citation
> 性質：依目前原始碼、架構閘門與完整 156-case blind live 結果重新判定

---

## 1. 結論先行

目前狀態**已不是架構重構問題**，而是 **RAG 評測流程正確性** 與 **證據選擇／生成品質**。

CI、architecture ratchet、跨套件所有權邊界均已就位：

- Root / Agent / Scripts / Ruff / Architecture checker：全綠
- Frozen blind validator：通過
- `citation_asset_gateway → teams_agent`：0 importer（SCC allowlist 已清空）
- Monorepo 邊界足以支撐未來拆分；**現在不需要拆 repo**

因此**不建議**：

- 再做一次大規模目錄重組
- 現在拆成兩個 repo
- 更換向量資料庫
- 直接導入 GraphRAG
- 在候選召回已很高時先上 dedicated reranker

最值得投入的事（現行進度）：

1. ~~評測 harness 正確性~~（`priorTurn`、hardNegatives、L3 token-budget）— **已完成並重跑**
2. ~~候選→生成器 evidence drop trace~~ — **已完成**
3. **Citation precision**（source roles + query-aligned prune）— **已落地程式；待下一輪 live 驗證**
4. **Answer omission adjudicate** — **14 案已分類；10 案為 judge 字面落差、4 案為真正 generation omission**
5. 正式 Cloud Run load test（仍待）

---

## 2. 目前品質閘門（權威狀態）

| 驗證項目 | 結果 | 說明 |
|---|---:|---|
| Architecture ratchet | 通過 | CAG package root；operations_core／CAG importer-count；**無 package cycle allowlist** |
| Ownership edges | 通過 | `citation_asset_gateway→teams_agent` = 0；`teams_agent→citation_asset_gateway` ≤19 |
| Blind freeze | 通過 | `freezeVersion=2`；156/156 reviewed；`--require-frozen --index` |
| Full blind L2 / live L3 | 已執行 | harness 修正後報告：`*-b7f3b61-harness.json` |

---

## 3. Blind live 現況（156 cases）

### 3.1 修正 harness 前（歷史基線，勿再當發布依據）

| 指標 | 結果 | 判斷 |
|---|---:|---|
| Answer Accuracy | 82.05% | 含 multi-turn／指標未接通偏差 |
| Citation Precision | 87.50% | 額外引用偏多 |
| Total P95 | 4.05s | 速度已明顯改善（舊約 6s） |

失敗分類（舊 harness）：BAD_CITATION 22、ANSWER_OMISSION 16、EVIDENCE_NOT_PASSED_TO_GENERATOR 11、NO_ANSWER_FALSE_POSITIVE 1。

### 3.2 修正 harness 後（`rag-l3-v3-blind-full-live-b7f3b61-harness.json`）

| 指標 | 結果 | 判斷 |
|---|---:|---|
| Candidate Evidence Recall@24 | ~98% | 候選檢索仍很好 |
| Answer Accuracy | 83.97% | 仍未達發布水準；已排除 harness 假失敗部分 |
| Citation Precision | 88.68% | 仍偏多；source-role／AD-drop 待下一輪 live |
| Citation Recall | 100% | 很好 |
| Failure taxonomy | BAD_CITATION 22 / OMISSION 14 / EVIDENCE_NOT_PASSED 11 | 見 evidence-drop trace 與 omission adjudication |

Evidence-drop：`data/eval/reports/rag-l3-evidence-drop-trace-b7f3b61.json`  
Omission adjudication：`data/eval/reports/rag-l3-omission-adjudication-b7f3b61.json`

### 3.3 Source-role／judge flex 後（已完成 live）

| 報告 | 狀態 |
|---|---|
| L2 `rag-l2-v3-blind-full-roles-judge.json` | **完成**：Evidence Recall@4 93.1%；Document Hit@4 100%；Candidate@24 98.3%；hardNegativeAccuracy 61.9%；`retrievalOnlyNoAnswerProxy` F1 59.6%（23 FN，非 E2E gate） |
| L3 `rag-l3-v3-blind-full-live-roles-judge.json` | 初版 roles（含過剪 NA-FP） |
| L3 `rag-l3-v3-blind-full-live-roles-fix.json` | Latin／否定句／CJK title 修復 |
| L3 `rag-l3-v3-blind-full-live-packing.json` | **最新**：PRIMARY-first packing + 蘋果→iOS 別名 |

| 指標 | harness 後 | roles-fix | **packing（最新）** |
|---|---:|---:|---:|
| Answer Accuracy | 83.97% | 88.46% | **89.74%** |
| Citation Precision | 88.68% | 94.12% | **94.98%** |
| Citation Recall | 100% | 98.08% | **99.36%** |
| BAD_CITATION | 22 | 8 | 9 |
| ANSWER_OMISSION | 14 | 7 | 13（多為原 evidence-drop 改判／字面 omission） |
| EVIDENCE_NOT_PASSED | 11 | 10 | **3** |
| NO_ANSWER_FALSE_POSITIVE | 0 | 1 | **0** |
| single / multi-turn Acc | 84.6% / 80% | 90.4% / 75% | **91.2% / 80%** |
| hardNegativeAccuracy | 76.2% | 81.0% | **85.7%** |
| Total P95 | 4.50s | 3.90s | **3.33s** |

下一步主戰場：ANSWER_OMISSION（13）與殘餘 3 個 evidence drop；不必先上 reranker。

---

## 4. P0：評測 harness（已完成）

1. **Multi-turn**：`EvidenceLevelCase.prior_turn`；compose resolved retrieval query；報告拆 single／multi-turn accuracy
2. **Hard-negatives**：解析 `hardNegatives` 並傳入 `score_retrieval_case`
3. **Layer-3 token-budget**：`--token-budget` 可覆寫各 tier；報告記錄 `evidenceTokenBudgets`
4. **Layer-2 no-answer**：報告標 `retrievalOnlyNoAnswerProxy`，避免與 E2E no-answer 混淆

---

## 5. P1：證據選擇與 citation（已落地並 live 驗證）

候選召回已高（~98%），瓶頸仍在 selection → packing → generator。

已驗證：

- Stage-level evidence drop 分類
- `source_roles` + query-aligned prune + 非 AD 查詢丟 AD FAQ
- Answer evidence judge flex（**未改 frozen v2 labels**）
- Live：Answer Accuracy 86.5%；BAD_CITATION 17；OMISSION 7

殘餘風險：Citation Recall 略降、4 個 NO_ANSWER_FALSE_POSITIVE、multi-turn Acc 75%。下一步應針對 false-positive no-answer 與殘餘 omission，而非 reranker。

---

## 6. P2：漸進式架構與營運

- `operations_core` 高 fan-in（158）：facade + ratchet，不急大拆
- Knowledge relationships：納入 release manifest；request path 只做 ID lookup；A/B 後移除 fallback
- Observability：latency histogram、TTFT、SLO alert（上線治理，非架構阻塞）
- Cloud Run 壓力測試：concurrency 1–32、warm/cold、TTFT、P95/P99、timeout

---

## 7. 建議工作順序（現行）

1. ~~完成 harness 三項修正並重跑 156-case blind~~
2. ~~Stage-level evidence drop 追蹤~~
3. ~~Source roles + citation prune + live 驗證~~
4. ~~人工 adjudicate residual omissions~~
5. 追查 4 個 NO_ANSWER_FALSE_POSITIVE 與 multi-turn 75%
6. 再決定是否需要 reranker（目前仍不建議）
7. 正式 Cloud Run load test（本目標標為 later）
8. 維持本文件與 HEAD／blind 結果同步

---

## 8. 最終判定

架構邊界與自動化看門已足夠支撐演進；**不需要結構性大重構**。  
發布依據應是 **最新完整 blind live**（含 source-role／judge flex 後重跑），不是舊 82% 數字，也不是 v2 開發集分數。
