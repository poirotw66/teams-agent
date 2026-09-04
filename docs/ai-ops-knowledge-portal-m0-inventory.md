# M0 盤點交付物（整併契約凍結草案）

| 項目 | 內容 |
|---|---|
| 對應規格 | [ai-ops-knowledge-portal-consolidation-spec.md](ai-ops-knowledge-portal-consolidation-spec.md) |
| 狀態 | 工程草案；D01–D10 正式簽核前依規格第 20 節預設推進 |
| 日期 | 2026-09-04 |

## 1. 功能歸屬（唯一來源）

| 功能 | 唯一寫入來源 | 使用者入口（目標） | 決策 |
|---|---|---|---|
| 文件／草稿／附件／匯入 | Knowledge Portal service／repository | `/knowledge/documents*` | 移入共同 Shell；不複製正文 |
| 審核／發布／回退 | Portal lifecycle | `/knowledge/reviews`、`/releases` | 移入；BFF 不得略過狀態機 |
| FAQ | Backoffice FAQ domain | `/knowledge/faqs` | 保留；不另建 FAQ |
| 無答案／負評案件 | Quality domain | `/quality/cases*` | 延伸關聯；不另建案件系統 |
| 文件成效指標 | Ops events／query read model | 文件詳情「成效」分頁 | 唯讀組合 |
| Prompt／模型／評測 | Governance domain | AI 管理 | 不變 |
| 權限／稽核／成本 | Backoffice 管理模組 | 平台管理 | 不變 |

## 2. API／URL 對照（M1 起）

外部命名空間：`/api/knowledge/*` → 內部 Portal：`/api/*`（見規格第 10 節）。

| 外部 | 內部 | 備註 |
|---|---|---|
| `GET /api/knowledge/documents` | `GET /api/documents` | 強制經 BFF 授權 |
| `GET /api/knowledge/documents/{id}` | `GET /api/documents/{id}` | 垂直切片首選 |
| `PUT /api/knowledge/documents/{id}/draft` | `PUT /api/documents/{id}/draft` | 樂觀鎖保留 |
| …（API01–API30） | 對應 `/api/...` | `API31` bootstrap **不**經公開 BFF |
| 既有 `GET /api/knowledge` | Backoffice 成效清單 | **不相等**於 Portal documents；保留相容 |
| 既有 `GET /api/knowledge/{id}/performance` | Backoffice 成效 | 與 Portal 路徑隔離 |

相容期：`KNOWLEDGE_PORTAL_PUBLIC_URL` 僅供舊入口；新操作不得另開跨站產品頁。

## 3. 權限矩陣（工程預設，待 D03 簽核）

不以角色名稱一對一對換。Backoffice 角色 → 明示 `knowledge.*` capability；未映射拒絕。

| Persona／角色 | knowledge 能力（預設） | Portal 委派 role（僅內部 RBAC） |
|---|---|---|
| SYSTEM_ADMIN | 全部 knowledge.* | PLATFORM |
| KNOWLEDGE_ADMIN | read/create/edit/assets/validate/test/submit/review/publish/unpublish/rollback | MANAGER |
| SERVICE_OWNER | read + quality 關聯所需讀取 | CONTRIBUTOR（唯讀知識為主） |
| AUDITOR | read + audit.read | AUDITOR |
| AI_ADMIN／ANALYST | 無 knowledge 寫入（預設） | —（拒絕） |

正式環境：拒絕瀏覽器 `X-Portal-*`；BFF 以服務身分 + 簽署委派 envelope 呼叫 Portal。

## 4. 遷移／驗收案例（垂直切片優先）

1. 品質案件 → 開啟關聯文件（同源，無第二次登入）。
2. 讀取草稿詳情經 `/api/knowledge/documents/{id}`。
3. 偽造 `X-Portal-Role` 不能提升能力。
4. 跨 owner unit／猜 documentId → 404／403 一致政策。
5. Portal 不可用 → 知識區局部錯誤，其他後台模組可用。

## 5. 未決項（阻塞正式驗收，不阻塞本機 M1）

見規格 D01–D10。本輪實作採用：單租戶 trusted tenant、HMAC 委派、Portal 維持內部服務、HEADER 僅限 dev／test。
