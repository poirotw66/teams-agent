---
name: RAG Workflow Remediation
overview: "分階段修正 #02 暴露的 scope routing、retrieval、synthesis、安全與評估可觀測性問題；先消除可確定的流程錯誤，再重建知識版本並執行 #03。四題 AI Ops／corpus governance 題目會移出 Helpdesk suite，避免扭曲產品準確率。"
todos:
  - id: eval-boundaries
    content: 拆分 AI Ops 題目、加入 canonical source IDs、evaluation trace 與 backend pinning
    status: pending
  - id: routing-clarification
    content: 修正 Helpdesk scope routing 並實作 retrieve-before-clarify
    status: pending
  - id: retrieval-planning
    content: 保留 original query，加入 title-aware indexing、document rerank 與 bounded multi-query retrieval
    status: pending
  - id: governed-synthesis
    content: 實作 evidence-scoped answer plan、partial answerability 與安全政策檢查
    status: pending
  - id: faq-visual
    content: 補齊 FAQ provenance 與授權 visual evidence 路徑
    status: pending
  - id: verify-baseline-03
    content: "重建 release，跑 targeted regressions，再執行並記錄 Helpdesk Baseline #03"
    status: pending
isProject: false
---

# Golden #02 RAG 工作流修正計畫

## 1. 先修正評估邊界與可觀測性

- 將 QB-010、QB-090、QB-099、QB-100 移至獨立 AI Ops Golden suite；Helpdesk suite 保留相同題庫版本與變更紀錄。
- 為題庫來源加入 canonical source ID 與 aliases，取代易誤判的顯示標題相似度；修正 M365、CRM、XQ 等 12 題「recall=0 但 PASS」的量測問題。
- 在 evaluation-only response 記錄 original query、rewrite query、候選文件與 sparse/dense/fused scores、rerank／拒絕理由、fallback path 和實際 backend；不放入一般回應或公開 logs。
- 在 `[knowledge_backends.py](agent_service/src/agent_service/knowledge_backends.py)` 與 `[workflow_clarification.py](agent_service/src/agent_service/workflow_clarification.py)` 每 request 只解析並固定一次 backend，修正 evaluation override，確保後續 HYBRID／Gemini A/B 可重現。

## 2. 修正 scope routing 與過早 clarification

- 在 `[extractor.py](agent_service/src/agent_service/extractor.py)` 建立明確的 Helpdesk answerable-domain policy，涵蓋公司系統、錯誤碼、權限／服務申請、支援窗口、診斷、資料保護及安全設定；授權仍由文件 ACL 獨立控制。
- 對命名系統、錯誤碼及強 IT 訊號增加 deterministic post-extraction guard，避免 QB-044、QB-060、QB-068、QB-074、QB-076、QB-079、QB-080、QB-085、QB-087–089 被錯判 `NOT_IT`。
- 修改 `[workflow_issue_processing.py](agent_service/src/agent_service/workflow_issue_processing.py)`：`NEED_MORE_INFO` 先執行低成本 retrieval probe；只有沒有單一高信心文件或候選跨產品衝突時才提問。以 QB-057–059 作回歸案例。
- 保持真正非 IT 問題的 fail-closed 行為，避免單純擴大關鍵字造成越權檢索。

## 3. 重建 retrieval 與 query planning

- 在 `[knowledge.py](agent_service/src/agent_service/knowledge.py)` 將 `_RetrievalState.query` 拆成不可變的 `original_query` 與可變的 `search_query`；rewrite 只影響檢索，relevance 與回答永遠使用原始問題及其限制語。
- 在 `[retrieval.py](agent_service/src/agent_service/retrieval.py)` 將 canonical title、aliases、section path、系統名稱和 error codes 納入 sparse index；保留 exact identifier boost，避免通用詞主導結果。
- 改為 document-level candidate aggregation 與逐文件 rerank，不再以「整包 context 有一段相關」就把全部文件送入生成；加入 canonical-version precedence 與來源去重。
- 對多意圖／多來源問題先拆成有限子查詢，採 adaptive top-k 與文件多樣性；每個必要 facet 未被覆蓋時只允許 bounded reretrieve，不無限擴張。
- 針對 QB-005、QB-013、QB-019、QB-029、QB-073、QB-093、QB-097 驗證錯誤來源消失；QB-020、QB-070 驗證不再混入不適用來源。

## 4. 加入 evidence-scoped answer planning 與安全政策

- 在 `[knowledge.py](agent_service/src/agent_service/knowledge.py)` 的生成階段先產生結構化 answer plan：requested facets、known facts、unknowns、negative constraints、claim-to-chunk mapping、applicability；再渲染繁中答案。
- 將 answerability 明確分成 `FULL`、`PARTIAL`、`NONE`：保留可支持部分並列出未知事項，只有完全無證據才走 `NO_KNOWLEDGE`。
- 移除 `_deterministic_grounded_answer` 的 raw-chunk 回傳路徑；citation 格式錯誤先 bounded retry，仍失敗則回安全的 partial／no-answer，不直接貼文件。
- 在文件 metadata／release validation 加入 lifecycle、applicability、authoritative rank、test/placeholder、stale/expired、unsafe-setting 標記。生成前排除不適用內容。
- 加入 deterministic policy checks：禁止輸出測試／占位 URL；聯絡方式、政策與操作步驟不得跨 system、actor、issue type 或時效範圍套用。覆蓋 QB-002、QB-017、QB-020、QB-045、QB-048、QB-070、QB-077、QB-094。

## 5. 補齊 FAQ 與 Visual Evidence 路徑

- 在 `[contracts.py](agent_service/src/agent_service/contracts.py)`、FAQ repository 與 `[workflow_issue_processing.py](agent_service/src/agent_service/workflow_issue_processing.py)` 為 governed FAQ 保存 canonical source/version/chunk provenance；無 provenance 的 legacy FAQ 回退 knowledge retrieval，不輸出不可稽核答案。
- 對已授權圖片建立結構化 visual evidence／multimodal input，回答模型必須實際接收圖片或 OCR/layout evidence；缺圖時明示限制。以 QB-029、QB-060、QB-087、QB-097、QB-098 驗證。

## 6. 測試、發布與 #03 驗證

- 新增 routing、retrieve-before-clarify、original-query preservation、per-document rerank、partial answerability、安全 metadata、FAQ provenance、backend pinning 與 visual-evidence 測試；沿用 pytest、Ruff 與現有型別檢查。
- 重建 index／release artifact，確認新 metadata、canonical IDs 與 embedding model 一致，再以 immutable release 執行。
- 先跑針對性 regression：11 題 false-NOT_IT、QB-057–059、7 題 wrong-source、raw fallback、placeholder URL、cross-source contamination；全部符合預期後才跑完整 Helpdesk #03。
- #03 使用新 Agent/Judge pipeline，記錄 Agent/Judge latency、完整 retrieval trace、HYBRID backend；Gemini File Search 另做獨立 A/B，不混入主 baseline。
- 驗收條件：answerable cases 不再因 `NOT_IT`／不必要 clarification 終止；raw excerpt 與測試 URL 為 0；所有 material claims 有適用範圍正確的 chunk 支持；targeted regression 全部通過或有明確 partial/unknown；完整結果保留版本、hash 與限制說明。

