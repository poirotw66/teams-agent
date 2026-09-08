# FAQ 與知識文件內容類型說明（知識營運）

## 一句話

- **FAQ（固定答案）**：啟用後落檔保存，Agent **原樣回覆**，不進 RAG。
- **知識文件**：審核發布後進索引，供 **RAG 檢索引用**。
- 兩者可 **手動標相關**；**不會自動互抄內文**。

## 何時用哪一種

| 用 FAQ | 用知識文件 |
|---|---|
| 答案短、必須一字不差 | SOP／手冊／長文 |
| 高頻標準流程 | 需引用段落、多來源 |
| 要快速啟停 | 問題說法多變、靠語意檢索 |

## FAQ 落檔

- 主檔：`AI_OPS_FAQ_STORE_PATH`（預設 FILE：`data/ops/phase2/faqs.json`）
- 啟用／回復匯出：`AI_OPS_FAQ_ARTIFACT_DIR`（預設 `data/ops/phase2/faq-artifacts/{faqKey}/`）
  - `v{n}-{versionId}.md` / `.json`
  - `ACTIVE.md`（目前啟用版）
- 這些檔案是 **稽核／交接用**，**不是** Knowledge RAG source。

## 正式環境

- Agent：`FAQ_RUNTIME_MODE=GOVERNED`（只讀 ACTIVE 版本；不回退 `data/faq.json`）
- 品質案件改善時，依決策指引選 FAQ 或文件；兩邊都要時先做主路徑，再手動關聯。
