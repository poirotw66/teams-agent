# POC 驗收標準對照表（spec §19）

對應規格：`teams_agent_requirement_architect_revised.md` §19（POC 驗收標準）、§20（交付項目）。

- 最後更新：2026-08-07
- 測試執行結果：Agent Service `444 passed`、Teams Adapter `48 passed`（合計 492，0 failed / 0 xfail）
- 執行方式：

  ```bash
  cd agent_service && .venv/bin/python -m pytest tests -q   # Agent Service
  cd .. && .venv/bin/python -m pytest tests -q              # Teams Adapter
  ```

狀態標記說明：

| 標記 | 意義 |
|---|---|
| ✅ | 已完成且有自動化測試或實測紀錄佐證 |
| ⚠️ | 已完成，但有明確的限制或待辦，見備註 |
| ❌ | 未完成 |

---

## 1. 二十二項驗收標準

`agent_service/tests/test_integration_acceptance.py` 刻意以
`test_acceptance_<NN>_<slug>` 命名，讓每一項驗收標準都能反查到測試，不需要
靠猜。第 1、2、12、22 項本質上不是單元測試能驗的（真實 Teams 連線、實際
Cloud Run 部署、Teams 端圖片渲染、壓測），改以實測紀錄佐證。

| # | 驗收標準 | 狀態 | 佐證 |
|---|---|---|---|
| 1 | Teams 可正常與 Agent 對話 | ⚠️ | 已於 Teams 頻道完成 Agent API 模式端到端實測（README 專案狀態）。目前走 Dev Tunnel 路徑；雲端路徑待第 2 項的 endpoint 切換後複測 |
| 2 | Teams Adapter 與 Agent Service 可部署至 Cloud Run | ⚠️ | 兩個服務皆已部署於 `asia-east1`／`itr-aimasteryhub-lab`，Adapter→Agent 走 Cloud Run IAM identity token。**待辦：Teams Developer Portal 的 bot endpoint 尚未從 Dev Tunnel 切到 Cloud Run Adapter** |
| 3 | 可取得可信任的使用者識別資訊 | ✅ | `test_acceptance_03_trusted_user_identity_is_extracted_from_request`、`test_acceptance_03_incomplete_identity_is_not_trusted_for_tickets`；身分來自 Teams／Entra context，不接受對話中自行指定（§11.4） |
| 4 | 可載入最近對話上下文 | ✅ | `test_acceptance_04_loads_recent_conversation_context_across_turns`；`ConversationService` 同時套用 `MAX_HISTORY_MESSAGES` 與 `CONVERSATION_HISTORY_ROUNDS` 兩個上限 |
| 5 | 可拆解最多三個 Issue | ✅ | `test_acceptance_05_splits_up_to_three_issues_and_prioritizes_the_rest`；超過三個時請使用者指定優先項目（§4.2） |
| 6 | 可判斷 IT 與非 IT 問題 | ✅ | `test_acceptance_06_classifies_it_versus_non_it_issues`；混合情境下非 IT 問題會被簡短說明而非靜默忽略 |
| 7 | FAQ 命中時回覆固定答案 | ✅ | `test_acceptance_07_faq_hit_returns_the_fixed_answer_verbatim`；`tests/test_faq.py` 另有測試釘住「FAQ 不呼叫 LLM、答案不被改寫」（§7.3） |
| 8 | 資訊不足時提出最多兩個必要問題 | ✅ | `test_acceptance_08_asks_at_most_two_followup_questions`；`MAX_MISSING_INFO_PER_ISSUE=2` |
| 9 | 資訊完整時可執行 Hybrid RAG | ✅ | `test_acceptance_09_ready_issue_executes_knowledge_search`；`KNOWLEDGE_SERVICE_MODE=HYBRID` 為預設（§8.2） |
| 10 | 回答只根據知識內容 | ✅ | `test_acceptance_10_answer_grounded_only_in_retrieved_knowledge` |
| 11 | 回覆包含來源文件 | ✅ | `test_acceptance_11_reply_includes_source_citations` |
| 12 | 圖片來源可正常顯示 | ✅ | Teams 頻道實測：來源圖片透過 Adaptive Card 顯示成功（README 驗收清單）。簽章與尺寸邏輯由 `tests/test_media.py`、`tests/test_cards.py` 覆蓋 |
| 13 | 無知識時不捏造 | ✅ | `test_acceptance_13_no_knowledge_does_not_fabricate_an_answer` |
| 14 | 未經確認不建立工單 | ✅ | `test_acceptance_14_ticket_not_created_without_confirmation`；`confirmation.py` 明確區分「好，幫我開單」與「還是不能用」（§11.3） |
| 15 | 使用者確認後可呼叫 Ticket API | ⚠️ | `test_acceptance_15_ticket_api_called_after_explicit_confirmation`。**HTTP Adapter 已完成並測試，但未接過真實工單系統**；雲端目前為 `TICKET_SERVICE_MODE=DISABLED`。§19 已明列 Production Ticket Service 不在必要驗收範圍 |
| 16 | 可查詢目前使用者自己的工單 | ✅ | `test_acceptance_16_queries_current_users_own_tickets`；`tests/test_security.py::TestCrossUserTicketAccess` 驗證不可查他人工單 |
| 17 | 可保存必要的 Conversation Context | ✅ | `test_acceptance_17_conversation_context_is_saved`。**2026-08-07 已補上 Firestore 持久化**，見下方第 2 節 |
| 18 | 多 Issue 不互相阻塞 | ✅ | `test_acceptance_18_multiple_issues_do_not_block_each_other` |
| 19 | 每次請求具有 Correlation ID | ✅ | `test_acceptance_19_every_request_has_a_correlation_id`；全鏈路傳遞且不在 node 間重新產生（§15.1） |
| 20 | 回答後可收集使用者回饋 | ✅ | `test_acceptance_20_feedback_can_be_collected_after_an_answer`；Teams 端 👍/👎 Adaptive Card 由 `tests/test_cards.py` 覆蓋 |
| 21 | 具備安全、錯誤與 Prompt Injection 測試 | ✅ | `tests/test_security.py`（618 行）全數通過，0 xfail；詳見 [`security-test-report.md`](security-test-report.md) |
| 22 | 現有 Python 架構通過定義的效能測試 | ⚠️ | [`performance-test-report.md`](performance-test-report.md) §3.3：Cloud Run 穩態 P95 4.03s、零錯誤（2026-08-06）。**2026-08-29 §5** 重跑 LLM 次數／成本（Supervisor-first）。Runtime 不需重寫；待補 concurrency 飽和點與 `--min-instances` |

### 不列入 POC 必要驗收的項目（§19 後段）

以下皆**刻意未做**，符合 §3.3「POC 不建立未驗證的未來平台能力」：

Node.js 重寫、Teams SDK TypeScript、Gemini File Search 正式取代 Hybrid
RAG、完整 Issue Repository、完整 Issue Lifecycle、工單催辦、Production Ticket
Service 實作、FAQ 後台、知識庫後台、Multi-Agent、Approval、完整 CI/CD、高可用
與災難復原。

---

## 2. Conversation 持久化（2026-08-07 補完）

第 17 項在此之前有一個雲端環境才會出現的實質缺口：程式預設
`CONVERSATION_REPOSITORY_MODE=MEMORY`，而 Cloud Run 會 scale-to-zero 且最多
跑 3 個 instance——instance 回收後對話全失，同一段對話的前後兩輪也可能落在
不同 instance。`FILE` 模式一樣救不了，因為本機磁碟既不持久也不共用。

已新增 `FirestoreConversationRepository`（`CONVERSATION_REPOSITORY_MODE=FIRESTORE`），
躲在原本的 `ConversationRepository` Protocol 之後，**Workflow 一行未改**（§3.2）。
同一套行為測試會 parametrize 跑過 MEMORY／FILE／FIRESTORE 三種實作。

| 驗證項目 | 結果 |
|---|---|
| 三種實作共用的行為測試 | 全數通過 |
| 真實 Firestore 探針（`scripts/firestore_verification.py`） | **10/10 通過**，寫入 8 份文件並全數刪除，跑完 store 為空 |
| `(default)` database（`asia-east1`, native mode） | 已建立 |
| `expiresAt` TTL policy（`conversations`／`conversations_keys`／`messages`） | 已啟用 |
| Agent SA `roles/datastore.user` | 待下次 `deploy-gcp.sh` 執行時套用 |

**真實驗證抓到一個 Fake 測試沒抓到的缺陷**：repository 原本用
`order_by("__name__", DESCENDING)` 讀訊息子集合，真實 Firestore 會以
`FAILED_PRECONDITION: The query requires an index` 拒絕——這版若直接上線，
**每一次讀取歷史對話都會失敗**，而當時的測試全綠。已改用一般欄位 `sortKey`
排序（Firestore 自動建立雙向單欄位索引），Fake 也同步改成會拒絕原寫法，並加
regression test 釘住。

設定與 GCP 佈建細節見 [`../deploy/README.md`](../deploy/README.md)。

---

## 3. §20 交付項目對照

| # | 交付項目 | 位置 |
|---|---|---|
| 1 | 更新後 Python 原始碼 | `src/`、`agent_service/src/` |
| 2 | Microsoft Teams SDK (Python) Teams Adapter | `src/teams_agent/` |
| 3 | LangGraph Agent Workflow | `agent_service/src/agent_service/workflow.py` |
| 4 | Issue Extractor | `agent_service/src/agent_service/extractor.py` |
| 5 | FAQ Repository 與 FAQ Service | `agent_service/src/agent_service/faq.py`、`data/faq.json` |
| 6 | Hybrid Knowledge Service | `agent_service/src/agent_service/knowledge.py` |
| 7 | Gemini File Search Spike Adapter | `agent_service/src/agent_service/gemini_file_search.py` |
| 8 | Conversation Repository Interface | `agent_service/src/agent_service/conversation.py` |
| 9 | Ticket Service HTTP Adapter | `agent_service/src/agent_service/ticket.py` |
| 10 | Deterministic Response Builder | `agent_service/src/agent_service/response_builder.py` |
| 11 | Feedback 機制 | `src/teams_agent/cards.py`、`agent_service/src/agent_service/api.py` |
| 12 | Logging 與 Correlation ID | `agent_service/src/agent_service/api.py` |
| 13 | 單元測試與整合測試 | `tests/`、`agent_service/tests/` |
| 14 | Retrieval A/B Test 報告 | [`retrieval-ab-test-report.md`](retrieval-ab-test-report.md) |
| 15 | 效能壓測報告 | [`performance-test-report.md`](performance-test-report.md) |
| 16 | Dockerfile | `Dockerfile`、`agent_service/Dockerfile` |
| 17 | `.env.example` | `.env.example`、`agent_service/.env.example` |
| 18 | README | `README.md`（English）、`README-TW.md`（繁中）、`agent_service/README.md`、`agent_service/README-TW.md` |
| 19 | Cloud Run 部署說明 | [`../deploy/README.md`](../deploy/README.md) |
| 20 | Teams App 設定與測試說明 | [`teams-app-setup.md`](teams-app-setup.md) |

二十項全數交付。

---

## 4. 待辦

依影響程度排序：

1. **將 Teams Developer Portal 的 bot endpoint 切到 Cloud Run Adapter**，並在雲端複測
   一次端到端（第 1、2 項）。純設定操作，不需改碼——這是目前唯一還卡住驗收
   標準的動作。
2. **下次部署時套用 Agent SA 的 `roles/datastore.user`**，Firestore 模式才會
   實際生效（`deploy-gcp.sh` 已內含）。
3. 若要驗證第 15 項到真實工單系統，設定 `TICKET_SERVICE_MODE=HTTP` 與
   `TICKET_SERVICE_BASE_URL`，並把 `TICKET_SERVICE_TOKEN` 放進 Secret Manager
   （§17：它是憑證，不可用純環境變數）。
4. 效能壓測補上 concurrency 飽和點量測，並評估 `--min-instances`（第 22 項）。
