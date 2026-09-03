# AI Ops Backoffice 里程碑與正式驗收簽核指南

本文件說明 SYSTEM_ADMIN 最終核准前要查看的四類證據。
自動化測試已通過；管理員核准代表同意本階段可交接。

**Phase 1 里程碑**：依 2026-09-03 產品決策，SYSTEM_ADMIN 是最高權限，由 Justin 做一次最終核准，不另要求各部門分別簽核。
**正式 Production**：沿用單一 SYSTEM_ADMIN 核准，但啟用時仍須依 production 規則提供 v2 外部驗證證據。

---

## 簽核前共通準備

1. 打開 LAB 後台：https://teams-ai-ops-backoffice-jt7pjdeeoa-de.a.run.app  
2. 確認自動化驗收報告：`artifacts/ai_ops_uat_acceptance_report.json`（`automatedVerificationPassed: true`）  
3. 證據包：`python scripts/ops_signoff_evidence.py --report artifacts/ai_ops_signoff_evidence.json`

---

## 1. BU 證據 — 指標與 Issue 分類

**證據紀錄 ID：** `bu-taxonomy-metrics`
**確認目標：** 後台數字與問題分類符合營運理解，可用來做決策。

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

---

## 2. IT 證據 — 基礎建設可交接

**證據紀錄 ID：** `it-terraform`
**確認目標：** GCP 資源、Terraform 狀態可維運接手，無未說明手工作業。

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

---

## 3. 資安／法遵證據 — 遮罩、保存、匯出、稽核

**證據紀錄 ID：** `security-masking-retention`
**確認目標：** 個資與敏感資料處理方式符合公司政策。

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

---

## 4. 知識管理證據 — Markdown / PDF 發布 UAT

**證據紀錄 ID：** `knowledge-portal-governance`
**確認目標：** 知識文件從 Portal 發布到 Backoffice 可見的流程，實際走過且可接受。

### 請確認（建議人工走一輪）

- [ ] 在 Knowledge Portal 建立或編輯 **Markdown** 文件 → 送審 → 發布  
- [ ] 匯入 **文字型 PDF**（非掃描）→ 發布；掃描 PDF 應被拒絕  
- [ ] Backoffice 知識成效／治理區塊可看到對應文件狀態  
- [ ] 自動化測試已覆蓋 portal→backoffice 整合（作為輔助證據）  

---

## SYSTEM_ADMIN 最終核准

```bash
# 1. 審閱四類證據後，只記錄一次管理員核准
python scripts/ops_signoff_approve.py \
  --checklist artifacts/ai_ops_signoff_checklist.json \
  --item phase1-admin-final-approval \
  --by "Justin" \
  --notes "SYSTEM_ADMIN 已審閱 Phase 1 技術與治理證據。"

# 2. 驗證管理員核准
python scripts/ops_signoff_checklist.py \
  --validate-phase1-milestone artifacts/ai_ops_signoff_checklist.json
```

里程碑驗證成功時會顯示：

- `Phase 1 milestone approval validation passed (approver: Justin).`

---

## 權限原則

SYSTEM_ADMIN 是後台最高權限，能力集合涵蓋所有其他角色。四類領域紀錄供管理員審閱，不是四個獨立人工 gate；現有 checklist 已由 Justin 完成一次最終核准。技術 gate 仍必須通過，不能由管理員手動略過。

規格依據：`docs/ai-ops-backoffice-phase-0-foundation-spec.md` §17、`docs/ai-ops-backoffice-phase-1-operations-mvp-spec.md` §15。
