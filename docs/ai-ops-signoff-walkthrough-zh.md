# AI Ops Backoffice 正式驗收簽核指南（LAB / 交接用）

本文件說明 Phase 0 / Phase 1 **正式驗收**時，四位簽核人各自要確認什麼。  
自動化測試已通過；簽核代表「對應角色同意此設計可交接／上線」。

**LAB 環境**：可由同一人代簽四項（需在 checklist 註明「LAB 自驗」）。  
**正式 Production**：建議仍由 BU、IT、資安／法遵、知識管理分別簽核。

---

## 簽核前共通準備

1. 打開 LAB 後台：https://teams-ai-ops-backoffice-jt7pjdeeoa-de.a.run.app  
2. 確認自動化驗收報告：`artifacts/ai_ops_uat_acceptance_report.json`（`automatedVerificationPassed: true`）  
3. 證據包：`python scripts/ops_signoff_evidence.py --report artifacts/ai_ops_signoff_evidence.json`

---

## 1. BU — 指標與 Issue 分類

**簽核項 ID：** `bu-taxonomy-metrics`  
**簽了代表：** 後台數字與問題分類，符合 BU 營運理解，敢用來做決策。

### 請確認

- [ ] Issue 分類名稱、層級、負責單位是否合理（例如 VPN、帳號、網路問題）  
- [ ] 未分類問題會進 `other.unclassified`，不會被丟棄  
- [ ] Dashboard KPI（對話數、Issue 數、負評、成本等）定義看得懂、口徑可接受  
- [ ] 點 KPI 可下鑽或看到指標定義說明  

### 建議查看

| 項目 | 位置 |
|------|------|
| Issue 分類表 | `data/ops/issue_taxonomy_v1.json` |
| 指標定義 | `data/ops/metrics_definitions_v1.json` |
| 後台實際畫面 | LAB URL → 總覽、Issue、品質模組 |

### 簽核指令（由 BU 代表執行）

```bash
python scripts/ops_signoff_approve.py \
  --checklist artifacts/ai_ops_signoff_checklist.json \
  --item bu-taxonomy-metrics \
  --by "您的姓名" \
  --notes "已確認 taxonomy 與 KPI 口徑符合 BU 需求（LAB）。"
```

---

## 2. IT — 基礎建設可交接

**簽核項 ID：** `it-terraform`  
**簽了代表：** GCP 資源、Terraform 狀態可維運接手，無未說明手工作業。

### 請確認

- [ ] Terraform plan 為 **No changes**（零 diff）  
- [ ] 環境清單完整：Cloud Run、Firestore、BigQuery、Log sink、Monitoring  
- [ ] 備份／復原 runbook 存在且指令可執行  
- [ ] LAB 使用 HEADER 測試身分；正式環境計畫切換 Entra SSO  

### 建議查看

| 項目 | 位置 |
|------|------|
| Plan 證據 | `artifacts/terraform-ai-ops-plan-evidence.txt` |
| 資源清單 | `infra/terraform/INVENTORY.md` |
| 環境 inventory | `infra/ai-ops-environment-inventory.json` |
| 維運手冊 | `docs/ai-ops-backoffice-runbook.md` |

### 簽核指令

```bash
python scripts/ops_signoff_approve.py \
  --checklist artifacts/ai_ops_signoff_checklist.json \
  --item it-terraform \
  --by "您的姓名" \
  --notes "已確認 Terraform zero-diff 與環境 inventory（LAB）。"
```

---

## 3. 資安／法遵 — 遮罩、保存、匯出、稽核

**簽核項 ID：** `security-masking-retention`  
**簽了代表：** 個資與敏感資料處理方式，符合公司政策。

### 請確認

- [ ] 未授權角色看不到未遮罩對話（403 或遮罩後內容）  
- [ ] 查看未遮罩對話需額外 capability 與 `unmask_reason`  
- [ ] 營運事件預設保存一年，到期可 purge  
- [ ] 匯出與畫面相同遮罩；Audit 寫入失敗時匯出被阻擋（fail-closed）  
- [ ] Credential 類資料不會出現在 Analytics／Audit  

### 建議查看

| 項目 | 位置 |
|------|------|
| 治理決策紀錄 | `data/ops/data_governance_decisions_v1.json` |
| 角色權限矩陣 | `data/ops/role_capability_matrix_v1.json` |
| 自動化測試 | 匯出 fail-closed、unmask step-up、retention purge（見 evidence 包） |

### 簽核指令

```bash
python scripts/ops_signoff_approve.py \
  --checklist artifacts/ai_ops_signoff_checklist.json \
  --item security-masking-retention \
  --by "您的姓名" \
  --notes "已確認遮罩、保存、匯出與 Audit 政策（LAB）。"
```

---

## 4. 知識管理 — Markdown / PDF 發布 UAT

**簽核項 ID：** `knowledge-portal-governance`  
**簽了代表：** 知識文件從 Portal 發布到 Backoffice 可見的流程，實際走過且可接受。

### 請確認（建議人工走一輪）

- [ ] 在 Knowledge Portal 建立或編輯 **Markdown** 文件 → 送審 → 發布  
- [ ] 匯入 **文字型 PDF**（非掃描）→ 發布；掃描 PDF 應被拒絕  
- [ ] Backoffice 知識成效／治理區塊可看到對應文件狀態  
- [ ] 自動化測試已覆蓋 portal→backoffice 整合（作為輔助證據）  

### 簽核指令

```bash
python scripts/ops_signoff_approve.py \
  --checklist artifacts/ai_ops_signoff_checklist.json \
  --item knowledge-portal-governance \
  --by "您的姓名" \
  --notes "已完成 Markdown 與 text PDF 發布 UAT（LAB）。"
```

---

## 全部簽完後 — 關閉正式驗收

```bash
# 1. 驗證四項皆 approved
python scripts/ops_signoff_checklist.py --validate artifacts/ai_ops_signoff_checklist.json

# 2. 跑最終 UAT handoff（含 --require-signoff）
cd agent_service
uv run python ../scripts/ops_uat_handoff.py \
  --gcp-project itr-aimasteryhub-lab \
  --live-url https://teams-ai-ops-backoffice-jt7pjdeeoa-de.a.run.app \
  --require-signoff
```

成功時 `artifacts/ai_ops_uat_acceptance_report.json` 會顯示：

- `automatedVerificationPassed: true`
- `formalAcceptanceComplete: true`

---

## LAB 自驗（一人代簽四項）

若僅為 LAB 工程交接、無正式四部門參與，可同一人依序執行上述四個 `ops_signoff_approve.py`，並在 `--notes` 註明「LAB 自驗」。

規格依據：`docs/ai-ops-backoffice-phase-0-foundation-spec.md` §17、`docs/ai-ops-backoffice-phase-1-operations-mvp-spec.md` §15。
