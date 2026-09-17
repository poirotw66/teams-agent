---
name: RAG Workflow Remediation
overview: "以可歸因的小步驟修正 #02 暴露的問題：先恢復可信基線與明確 query/budget contract，再依序完成安全、routing、retrieval、synthesis；Visual RAG 獨立驗證，最後執行 All-100、Helpdesk-96 與 AI-Ops-4 Baseline #03。"
todos:
  - id: phase0-tests
    content: 恢復 supervisor、workflow、knowledge 與 backend targeted tests
    status: completed
  - id: phase0-contracts
    content: 凍結
    status: completed
  - id: phase1-safety
    content: 移除 unsafe fallback、固定 backend、加入 canonical IDs 與安全 evaluation trace
    status: completed
  - id: phase2-routing
    content: 補 11 題 false-NOT_IT 與 answerability-aware retrieval probe
    status: completed
  - id: phase3-retrieval
    content: 實作 canonical document selection、chunk rerank 與 bounded facet retrieval
    status: completed
  - id: phase4-synthesis
    content: 實作單次 structured answerability、claim mapping、安全檢查與 FAQ provenance
    status: completed
  - id: phase5-visual
    content: 獨立實作與驗證 Visual RAG
    status: cancelled
  - id: phase6-baseline
    content: 重建 release 並執行三套 Baseline
    status: completed
isProject: false
---

# Golden #02 RAG 工作流修正計畫

## Phase 0：恢復可信基線

- 先恢復 supervisor、workflow、knowledge、backend targeted pytest，再修改 retrieval。
- 凍結 Baseline #02 question bank hash、artifact hashes 與 release ID。
- 保留現有 supervisor confidence、deterministic guards 與 `issue.description` 搜尋，不重做已完成行為。
- 定義 `raw_user_utterance`、`resolved_issue_query`、`search_query`、`facet_queries`；回答與 answerability 以不可變的 resolved issue 為準。
- 固定預設 request deadline 30 秒、共享 LLM budget 6、facet 上限 3、reretrieve 上限 1。

## Phase 1：安全與可重現性

- 移除 raw chunk fallback；不足或無效 citation 不得因 retrieval 高分改判成功。
- 搜尋必須使用 `ExecutionContext.selected_knowledge_backend`，request 途中切換 active backend 不得影響結果。
- 加入 governed canonical source ID／aliases／version precedence。
- Evaluation trace 只記錄 ACL 過濾後的 query layers、候選、分數、決策與 fallback path。
- 在生成前排除 test、placeholder、expired 與不適用內容。

## Phase 2：Routing 與 clarification

- 只針對 11 個 Helpdesk false-NOT_IT 案例補 domain policy 與 regressions。
- Deterministic guard 只阻止錯誤 `NOT_IT`，不直接宣告問題可回答。
- `NEED_MORE_INFO` 可先 retrieval probe；只有 entity 唯一、facet 明確、applicability 不衝突且必要欄位都有證據才直接回答。
- QB-057–059 必須避免因高分命中而回答錯誤產品。

## Phase 3：Retrieval

- Sparse index 納入 title、aliases、section、system 與 error code。
- 先做 canonical document selection，再在每份文件內做 chunk rerank；每份文件限制 chunk 數量，引用維持 chunk ID。
- ACL 必須早於 aggregation、trace 與 rerank。
- `facet_queries` 只拆單一 issue 的必要 facets，最多 3 個；最多一次 reretrieve；identifier 不得被 rewrite；不足 budget 退回 single query。
- 每個 retrieval 變更完成後立即跑 targeted Golden subset。

## Phase 4：Synthesis 與 FAQ

- 單次 structured generation 同時產生 `FULL/PARTIAL/NONE`、claims、chunk mapping、unknowns 與 applicability，再由程式 deterministic render。
- 簡單 FAQ／單一來源不增加 planner call；複雜問題也不得無條件多一次 LLM call。
- 加入 placeholder、stale date、unsafe setting 與跨 system／actor／issue-type 套用的 deterministic checks。
- Governed FAQ 必須帶 source/version/chunk provenance；legacy FAQ 無 provenance 時回退 knowledge retrieval。

## Phase 5：獨立 Visual RAG

- OCR/layout evidence、圖片 ACL/provenance、multimodal generation 與 Visual Golden subset 獨立交付。
- Visual RAG 不阻塞文字 RAG 的 Baseline #03。

## Phase 6：Baseline #03

- 保留 `All-100`、`Helpdesk-96`、`AI-Ops-4` 三個 suite；四題只以 membership 分流，不從歷史題庫刪除。
- 使用 immutable release，先跑 targeted subset 3 次，再跑完整 #03。
- 驗收：targeted pytest 100%；11 題不再 terminal false-NOT_IT；QB-057–059 不誤答產品；raw fallback、placeholder URL、未授權 trace 為 0；material claims 對應真實 chunk；corrected recall 不低於重算 #02；Helpdesk-96 acceptable rate 不下降；P95 latency 增幅不超過 15%；平均 LLM calls 維持 budget。

