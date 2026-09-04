# AI 資訊客服營運後台與知識營運介面整併工程規格

| 項目 | 內容 |
|---|---|
| 文件版本 | 1.0 |
| 建立日期 | 2026-09-04 |
| 文件狀態 | 工程提案；供需求確認、派工、驗收及交接使用，非已完成實作聲明 |
| 適用專案 | teams-agent |
| 對外產品名稱 | AI 資訊客服營運後台 |
| 整併對象 | AI Ops Backoffice 與 Knowledge Portal 的操作入口、身分權限及知識工作流程 |
| 本文件產出範圍 | 僅規格文件；不修改應用程式、不執行資料搬移、不變更雲端部署 |
| 里程碑命名 | M0–M4；不取代原後台 Phase 0–3 功能規格 |

## 1. 決策摘要

將「知識營運介面」納入「AI 資訊客服營運後台」，形成一個登入入口、一套導覽、一套操作身分，以及可追蹤的服務品質改善流程。

採取 **單一前端 + 後台 API 整合層 + 既有知識領域服務**。保留 Knowledge Portal 已有的文件、草稿、附件、審核及發布邏輯，不複製成第二套知識資料庫，也不以重寫 Agent 或 RAG 作為前提。

整併的完成標準不是把兩個 port 改成同一個數字，而是 BU 人員不需要知道兩個服務存在，即可完成知識維護。內部仍可使用不同 port、程序或部署服務。

優先完成一條垂直流程：**品質案件 → 文件草稿 → 試問 → 審核發布 → 確認客服實際生效 → 返回案件追蹤**，再移轉其餘頁面。

## 2. 現況與問題依據

以下為程式碼觀察，不代表已驗證正式環境的網域、IAM 或部署狀態。

| 現況 | 程式依據 | 整併影響 |
|---|---|---|
| Backoffice 與 Portal 各有 FastAPI app、首頁及 static 資源 | `agent_service/src/ai_ops_backoffice/api.py`、`agent_service/src/knowledge_portal/api.py` | 目前是兩套 UI shell，不是同一後台中的兩個模組 |
| Backoffice 預設 port 8092 | `agent_service/src/ai_ops_backoffice/main.py` | 可作為整併後本機主要入口 |
| Portal 程式預設 port 8090；本機驗證腳本使用 8091 避免 Mock Ticket 衝突 | `agent_service/src/knowledge_portal/main.py`、`scripts/verify_local_portal.sh` | 不能只把 8090／8091 差異認定為 bug，應統一啟動與設定契約 |
| Backoffice 的 Portal URL 預設為 8091，文件／品質相關操作有另開 Portal 入口 | `agent_service/src/ai_ops_backoffice/settings.py`、`static/js/main.js` | 使用者被迫跨產品操作，流程上下文可能中斷 |
| Portal 有獨立 session、導覽與角色處理 | `agent_service/src/knowledge_portal/static/js/session.js` | 搬入頁面之前必須處理身分及權限，而非只移植 HTML |
| Portal API client 使用 `/api/documents` 絕對路徑及身分 headers | `agent_service/src/knowledge_portal/static/js/api.js` | 單純加路徑前綴或反向代理會遇到路由與身分問題 |
| 兩個服務的文件 API 職責不同，且存在 `/api/documents` 命名重疊 | 兩個服務的 `api.py` | 新整合 API 必須避開碰撞，不能依路由註冊順序決定語意 |
| PortalActor 有 user、role、owner units，但未包含 tenant_id | `agent_service/src/knowledge_portal/models.py` | 整併時必須補上可信租戶範圍，不能直接假定兩服務隔離一致 |
| 品質領域已有 document_ids／faq_ids 及關聯操作 | `agent_service/src/ai_ops_backoffice/quality_domain.py` | 應延伸既有關聯與證據鏈，不另建一套品質案件 |

### 2.1 需要解決的使用者問題

1. 不清楚「文件成效頁」和「文件編輯頁」是否為同一份知識。
2. 從品質問題進入知識編輯後，容易失去原案件與對話背景。
3. 同一人可能在不同介面看到不一致的角色、選單及可執行動作。
4. 文件發布成功不等於 Agent 已使用新版本，使用者缺少明確的生效狀態。
5. BU 交接需記住兩個網址、兩套操作方式及不同錯誤訊息。

### 2.2 不應誤判的事項

- 不同內部服務或 port 本身並非架構錯誤；對使用者暴露割裂的產品流程才是本案重點。
- 本案不是將所有服務合併成單一 Python 程序，也不要求更換前端框架。
- 現有權限不等同全面四眼審核：Portal 的 MANAGER／PLATFORM 及 relaxed workflow 有自審例外；REVIEWER 的自審限制有條件。是否改變政策須獨立核准。
- 本文件不宣稱原 Phase 0–3 已全部完成，也不以新增規格代替功能驗證。

## 3. 目標、範圍與非目標

### 3.1 必達目標

| ID | 要求 | 完成判定 |
|---|---|---|
| G01 | 單一產品入口 | BU 從一個網址完成文件、FAQ、品質案件及治理操作 |
| G02 | 單一操作身分 | 知識模組不要求第二次登入、不顯示獨立角色切換器 |
| G03 | 單一工作上下文 | 案件與文件、版本、試問及發布結果可雙向追蹤 |
| G04 | 功能不退化 | 第 10 節全部現有 Portal 能力都有遷移、限制或維運歸屬 |
| G05 | 權限可驗證 | UI、BFF、領域服務均遵守 capability 與資料範圍契約 |
| G06 | 可部署及回退 | 有環境設定、IaC 變更清單、切換腳本規格及演練證據 |
| G07 | 非 IT 人員可操作 | 代表性 BU 使用者不需輸入文件 ID、API URL 或 token 即完成核心流程 |

### 3.2 納入範圍

- 統一導覽、路由、登入、角色呈現、錯誤與通知。
- 文件清單、匯入、草稿編輯、附件、驗證、試問、審核、發布、下架與版本回退。
- 文件內容與成效呈現整合；保留兩者各自資料來源。
- 品質案件與文件／FAQ 的關聯、處理證據、待辦與觀察流程。
- 內部 API adapter、服務身分、租戶／單位隔離、稽核與非同步作業狀態。
- 本機啟動、部署設定、舊連結相容、UAT、交接及舊 UI 退場。

### 3.3 不納入範圍

- 重寫 LangGraph、意圖分類、handoff router、檢索或模型推理架構。
- 將所有資料搬入同一 repository，或以後台 read model 取代知識來源。
- 新增一套 FAQ、審核引擎、派工平台或企業 IAM。
- 全面修改原有審核制度、保存期限、模型計費政策。
- 將營運後台嵌入 Teams；Teams 保持員工使用 AI 客服的入口。
- 在本輪工程加入與整併無關的視覺重設計或前端框架遷移。

## 4. 目標架構與邊界

```text
BU／營運人員
  │ 單一 HTTPS origin／單一登入
  ▼
AI 資訊客服營運後台
  ├─ 共用 Shell：導覽、身分、通知、錯誤、返回上下文
  ├─ 既有 Backoffice APIs：FAQ、品質、治理、成本、稽核
  └─ /api/knowledge/*：受控 BFF／Knowledge adapter
          │ 服務身分 + 已驗證的使用者委派身分
          ▼
      Knowledge 領域服務（內部）
          ├─ 文件／草稿／附件／審核 repository
          └─ 發布流程 → 發布成果／檢索索引 → Agent 實際載入

Teams 員工客服入口 → 既有 Agent；不經過營運 UI 執行一般客服對話
```

### 4.1 組件責任

- **前端 Shell**：導覽、共用 session、路由、可用操作呈現、通知、表單未儲存防護；不負責最終授權。
- **BFF**：驗證登入、解析權限、輸入驗證、限定路由轉接、錯誤轉換、關聯 ID、操作狀態與跨領域查詢組合。
- **Knowledge adapter**：封裝內部 URL、認證、timeout、multipart、錯誤與契約版本；不接受瀏覽器指定任意目的 URL。
- **Knowledge 領域服務**：知識狀態轉移、內容與附件儲存、審核及發布的一致性與最終授權。
- **Quality domain**：改善案件、文件／FAQ 關聯、驗證證據及結案判定。
- **Agent／索引服務**：對目前生效版本提供可驗證資訊；後台不得以「發布請求成功」推定已載入。

### 4.2 不採用的方案

| 方案 | 不採用原因 |
|---|---|
| iframe 包裝 Portal | 仍有兩套 session、導覽與錯誤處理；跨模組流程與可及性難以一致 |
| 只把 Portal 改成後台外部連結 | 沒有解決操作割裂、上下文及權限問題 |
| 只統一 port／反向代理首頁 | API、附件與 static 絕對路徑仍可能碰撞，未完成產品整合 |
| 重建一套文件 repository | 形成雙寫、版本分歧及發布責任不清 |
| 第一階段合併全部程序 | 放大故障範圍與部署風險，並非單一入口的必要條件 |

## 5. 領域所有權與資料來源

| 資料／功能 | 唯一寫入責任 | 整併後呈現 | 禁止事項 |
|---|---|---|---|
| 文件、草稿、圖片、匯入 | Knowledge 既有服務／repository | 知識營運文件頁 | 在 Backoffice read model 直接改正文 |
| 文件審核、發布、下架、版本回退 | Knowledge lifecycle | 待審／版本頁 | 由 BFF 略過狀態機直接改發布狀態 |
| FAQ | Backoffice 既有 FAQ 領域 | 知識營運 FAQ 頁 | 為整併再建第二套 FAQ |
| 品質案件、候選問題、內容關聯 | 既有 Quality domain | 服務品質與我的待辦 | 用文件發布狀態取代案件狀態 |
| 文件成效與營運指標 | 既有事件／read model | 文件詳情成效分頁 | 把統計索引當內容主檔 |
| Prompt、模型、評測與治理 | 既有治理領域 | AI 管理 | 在 Portal 再實作治理功能 |
| 身分與群組 | 企業身分來源及後台授權設定 | 共用使用者／能力資訊 | 相信瀏覽器自行傳入角色 |
| 稽核 | 各來源記錄原事件，後台整合查閱 | 平台管理／操作歷程 | 合併時遺失事件來源或真實操作者 |

原有 ID 保留，不因 UI 路由或產品命名改變而重新建立文件、案件或版本。跨領域關聯應記錄 tenant、資料類型及 ID，不能假設不同領域的裸 ID 永不重複。

## 6. 資訊架構與頁面規格

以下為目標路由，不代表目前已存在。採同一套 router；由既有前端架構決定 hash 或 history 實作，但分享連結與伺服器 fallback 必須一致。

| 工作區 | 頁面／建議路徑 | 主要使用者工作 |
|---|---|---|
| 知識營運 | `/knowledge/tasks` | 查看待補件、待審、發布失敗、待驗證及本人處理案件 |
| 知識營運 | `/knowledge/documents` | 查找、新增、匯入文件；依權限及狀態篩選 |
| 知識營運 | `/knowledge/documents/:documentId` | 檢視內容、草稿、驗證、版本、成效及關聯案件 |
| 知識營運 | `/knowledge/faqs` | 使用既有 FAQ 能力，保留其發布契約 |
| 知識營運 | `/knowledge/reviews` | 審核內容差異、測試證據及退回原因 |
| 知識營運 | `/knowledge/releases` | 檢視發布版本、實際生效狀態、比較與回退 |
| 知識營運 | `/knowledge/validation` | 試問與測試紀錄，清楚區分草稿及正式版本 |
| 服務品質 | `/quality/cases`、`/quality/cases/:caseId` | 未解答／負評處理、知識關聯、改善追蹤 |
| 服務品質 | 既有對話與回饋頁 | 查看授權範圍內的對話及品質訊號 |
| AI 管理 | 既有 Prompt、模型、評測、範例與開關頁 | 維持既有功能，將導覽責任集中至 Shell |
| 平台管理 | 既有角色、稽核、成本、預算、健康與資料政策頁 | 維持既有能力與權限 |

### 6.1 共用互動要求

1. 所有核心知識操作留在同一分頁，不出現第二套產品標題、登入區或側邊欄。
2. Breadcrumb 顯示「知識營運／文件／文件名稱」；從品質案件進入時保留「返回案件」動作。
3. 文件名稱為主要辨識資訊，ID 放在可複製的進階資訊區，不要求 BU 手工輸入。
4. 畫面至少包含 loading、empty、error、permission denied、not found、stale、unsaved 狀態。
5. 權限不足時不得僅以灰色按鈕代替說明；提供「需要哪些權限／聯絡哪個角色」的可理解訊息。
6. 儲存中、匯入中、發布中有可追蹤狀態；重新整理後可恢復查詢，不把瀏覽器記憶體當唯一進度來源。
7. 離開未儲存草稿需提醒；版本衝突顯示目前版本及重新載入／複製本地內容選項，不靜默覆寫。
8. 成功通知描述實際結果：「草稿已儲存」「審核已送出」「發布完成，等待客服載入」，不用統一「操作成功」。
9. 以鍵盤可完成主要操作，焦點可見；對話框開關恢復焦點；表單錯誤可被輔助技術讀取。
10. 操作上下文可攜帶 caseId、documentId 與允許的 return route；後端重新驗證其可見性，URL 不得攜帶完整對話、token 或敏感個資。

### 6.2 文件詳情分頁

| 分頁 | 必備內容 |
|---|---|
| 內容與草稿 | 正式版本、目前草稿、負責單位、作者、最後修改時間、編輯與附件 |
| 驗證與試問 | 格式檢查、阻擋問題、測試問題、命中片段、來源、結果與受測版本 |
| 審核與版本 | 差異、意見、核准／退回、發布紀錄、生效狀態及授權回退入口 |
| 使用成效 | 查詢／引用／回饋指標、統計時間、資料更新時間；不可編輯正文 |
| 關聯案件 | 來源案件、改善證據、狀態、返回案件動作 |

## 7. 端到端流程與狀態要求

### 7.1 品質案件改善

1. 營運人員開啟案件，檢視允許範圍內的問題、對話、既有知識與回饋。
2. 選擇「關聯既有文件」「建立文件草稿」或「維護 FAQ」；建立前先檢查既有關聯，降低重複建立。
3. 關聯建立成功後顯示文件名稱與狀態；若文件建立成功但關聯失敗，顯示可重試的部分成功，不再建立第二份文件。
4. 編輯與試問時保留案件背景；模型產生的建議內容仍是草稿，不能自動發布。
5. 草稿驗證通過後依既有審核流程送審。檢查失敗需提供可修正的欄位及說明。
6. 核准後由有發布權限者發布。記錄 draft revision、versionId、releaseId 與操作 ID。
7. 等待索引／Agent 確認生效；超時轉成待處理，不顯示已完成改善。
8. 使用正式版本執行原問題與代表性改述測試，保留 testRunId 及實際載入的 releaseId。
9. 案件負責人確認證據後轉入觀察或結案；發布事件本身不得直接結案。
10. 測試失敗或後續負評時保留／重開案件，沿用既有案件而非自動大量建立重複案件。

### 7.2 一般文件維護

- 新增／匯入 → 確認解析結果 → 編輯草稿與附件 → 驗證 → 草稿試問 → 送審 → 發布 → 生效確認。
- 已發布文件開始修訂時保留正式版本服務；修改草稿不得立即污染正式 RAG。
- 退回補件必須顯示意見、對應版本與可執行下一步。
- 放棄草稿、下架、刪除文件是不同動作；沿用領域服務限制，UI 不合併成單一「刪除」。

### 7.3 發布及回退狀態呈現

將領域原有 release 狀態與下游生效狀態分開呈現。以下是整合層的顯示語意，不要求覆寫原有 enum。

| 顯示狀態 | 判定依據 | 使用者下一步 |
|---|---|---|
| 建置中 | 領域發布流程仍進行 | 查看進度；不可重複發起同版本發布 |
| 發布失敗 | 領域回報失敗 | 查看安全化錯誤、修正或重試 |
| 已發布，等待生效 | 發布成果完成，但缺少指定服務版本確認 | 等待／查看同步進度 |
| 已生效，待驗證 | 目標 Agent／索引已確認版本 | 執行正式試問 |
| 已驗證 | 正式測試通過，受測版本符合目標 | 進入觀察或人工結案 |
| 生效失敗／未知 | 下游拒絕、逾時或無法確認 | 維運處理，不可假設成功 |
| 已回退 | 回退已由領域確認；另列下游是否生效 | 重做正式試問、重新評估關聯案件 |

若 Agent 有多個服務副本，生效判定需涵蓋正式流量可能到達的副本，或以可驗證的統一版本路由保證；不能只用一次隨機命中代表全部完成。

## 8. 身分、權限與隔離契約

### 8.1 外部登入與內部委派

建議採後台統一 Entra 登入，BFF 保有伺服器端 session；瀏覽器使用 Secure、HttpOnly cookie，不持有內部服務 token。Cookie 採符合登入流程的 SameSite 設定，所有變更操作需 CSRF token／Origin 驗證。正式環境只接受 HTTPS。

若 M0 確認既有驗證架構必須使用 browser bearer token，可改採該模式，但須記錄 ADR、限定 audience、處理更新與登出、禁止把 token 放入 URL，且同樣不得接受用戶自行宣告角色。

內部呼叫必須同時具備：

1. **服務身分**：證明呼叫者是核准的 BFF，例如部署平台 IAM／服務憑證。
2. **使用者委派身分**：短效、可驗證的 actor envelope，含 issuer、audience、subject、tenant、owner units、capabilities、issuedAt、expiresAt、jti、correlationId。
3. 知識服務驗證兩者的來源與綁定，拒絕錯誤 audience、過期或未簽署資料；簽章金鑰不交給前端。
4. 服務 token 與使用者 token 必須使用不同且明確的傳遞契約，不能同時競爭同一個 Authorization header。
5. 對重放敏感的寫入，搭配短效委派、操作冪等鍵及必要的 jti 防重放；不以記錄 jti 取代業務冪等性。

正式模式下 BFF 必須移除外部 `X-Portal-*` 身分 headers；Portal 不得信任瀏覽器直送的 role、user 或 owner units。HEADER／DEMO 模式僅限明確隔離的本機環境，正式設定錯誤時拒絕啟動或拒絕請求，不降級為 Demo 管理者。

### 8.2 Capability 與 persona

下表為產品操作能力分組，不是將 Backoffice 角色名稱直接轉換成 Portal 角色的自動規則。

| Persona | 可授權能力 | 限制 |
|---|---|---|
| 知識編輯者 | 文件讀取、新增、草稿編輯、附件、驗證、試問、送審 | 僅授權 tenant／單位／資源，不預設有發布權 |
| 知識審核者 | 文件讀取、差異及測試查閱、審核決策 | 遵循核准的自審與資料範圍政策 |
| 知識管理者 | 管理草稿、發布、下架、版本回退 | 高風險動作確認、原因及稽核不可省略 |
| 品質營運者 | 案件處理、關聯知識、追蹤改善 | 關聯案件不自動取得文件編輯或發布權 |
| 稽核人員 | 授權範圍內唯讀查閱及稽核 | 不因角色排序取得任何寫入能力 |
| 平台管理者 | 技術設定及核准的維運操作 | 技術管理與業務發布是否兼任須明確授權 |

最小 capability 集合：`knowledge.read`、`knowledge.create`、`knowledge.edit`、`knowledge.assets.write`、`knowledge.validate`、`knowledge.test`、`knowledge.submit`、`knowledge.review`、`knowledge.publish`、`knowledge.unpublish`、`knowledge.rollback`、`knowledge.delete`、`knowledge.audit.read`。案件操作沿用既有品質領域能力。

前端由受信任的 session／capabilities API 取得「可執行動作」。BFF 與領域服務仍逐次驗證 capability、tenant、owner unit、資源狀態及版本；不得只驗證使用者具有某個角色。

### 8.3 現有政策與調整界線

- 現有 Portal 的 MANAGER／PLATFORM／AUDITOR／REVIEWER 在文件可見性規則中有較廣的讀取範圍。跨單位範圍應明確列入遷移矩陣，不以 UI 隱藏代替後端限制。
- Contributor 現有「單位符合或本人建立」規則不可繞過 tenant 限制。
- MANAGER／PLATFORM 自審例外及 relaxed workflow 是否保留，由 BU 流程負責人與資安共同於 M0 核准。未核准前不可宣稱本案已導入全面職務分離。
- 不同服務同名角色不保證語意相同；未映射角色預設無權，不自動升級。
- SYSADMIN／AUDITOR 若有跨租戶需求，必須為獨立、明示、可稽核的 scope；不得由一般角色名稱推導跨租戶存取。

### 8.4 Tenant 與資料範圍遷移

1. M0 確認部署是否單租戶，以及各資料來源的 tenant 決定方式。
2. 單租戶部署可先以服務端固定且受管理的 deployment tenant 補足上下文，禁止從任意 request query/header 決定 tenant。
3. 多租戶共用儲存上線前，須將 tenant 加入權威資料／repository 查詢契約與複合唯一性；BFF filter 不足以作為隔離。
4. 無法確認歸屬的歷史資料進入待分類清單，不預設公開給所有單位。
5. 文件、附件、審核、版本、試問、搜尋及統計都需驗證 scope；修改 URL 或猜測 ID 不得讀到外部資料。
6. 無權且可能洩漏資源存在性的請求，以一致的 404 回覆；不回傳他單位文件名稱或筆數。

## 9. API 整合規格

### 9.1 Namespace 與 adapter

- 新增外部 namespace `/api/knowledge/*`；既有 Backoffice `/api/documents` 在相容期維持原職責。
- BFF 只轉接第 10 節明列端點；禁止任意 path／host proxy。
- 內部 Portal 可暫保留既有路徑，由 adapter 明確映射，不要求同時大改兩端所有路由。
- 建議以獨立模組處理 adapter、schemas、auth 與 routes，避免將所有邏輯塞入既有 `api.py`。
- 瀏覽器不得收到內部服務 URL、服務憑證或原始內部 exception。
- 長作業採作業資源查詢，BFF 不以延長所有請求 timeout 解決發布／評測問題。

### 9.2 請求與並發

| 項目 | 契約 |
|---|---|
| correlation | 接受格式合格的 correlation ID，否則產生；所有下游與稽核沿用 |
| 版本控制 | 更新與狀態變更帶 expected revision／If-Match；adapter 對應既有 version 契約，不移除樂觀鎖 |
| 冪等 | 建立、匯入、送審、發布、回退及跨領域作業使用 Idempotency-Key；領域提交端持久保存結果 |
| 冪等範圍 | tenant + actor + operation + key；同 key 同 payload 回既有結果，不同 payload 回 409 |
| 冪等保存 | 預設至少 24 小時，且不短於作業最長生命期；M0 按既有排程最大重試窗口確認 |
| 重試 | 讀取可有限重試；寫入僅在具持久冪等契約時重試；未知結果先查操作狀態 |
| 分頁 | 各 list endpoint 有界限與穩定排序；BFF 不為組合頁無限制掃描整個資料集 |
| timeout | 分離連線、讀取與長作業；具取消與部分失敗呈現，不讓知識故障拖垮其他模組 |
| 上傳 | 使用 multipart／streaming；不得把大檔轉成 JSON base64 才送到 Portal |

### 9.3 統一錯誤格式

以下為目標契約範例，不是既有 API 回應聲明：

```json
{
  "error": {
    "code": "KNOWLEDGE_VERSION_CONFLICT",
    "message": "這份文件已被更新，請重新載入後再儲存。",
    "retryable": false,
    "correlationId": "corr-20260904-001",
    "details": {
      "documentId": "doc-001",
      "expectedRevision": 7,
      "currentRevision": 8
    }
  }
}
```

| HTTP | 類型 | 前端處理 |
|---|---|---|
| 400／422 | 輸入或驗證失敗 | 定位欄位與阻擋原因，保留輸入 |
| 401 | 尚未登入／session 過期 | 重新登入；不自動重送高風險動作 |
| 403 | 操作權限不足 | 顯示所需能力，不提示可繞過方式 |
| 404 | 不存在或不可揭露的資源 | 一致的無法存取畫面 |
| 409 | 版本／狀態／冪等衝突 | 顯示衝突與安全恢復選項 |
| 413／415 | 檔案過大／類型不允許 | 顯示實際設定上限與支援類型 |
| 429 | 過量請求 | 尊重 Retry-After；不密集輪詢 |
| 502／503／504 | 下游故障或逾時 | 顯示服務暫不可用、操作 ID、查詢結果入口 |

內部 stack trace、storage path、簽名 URL、完整敏感對話與 token 不得出現在 error details。驗證訊息保留可行動資訊，但需經安全化處理。

### 9.4 非同步操作

新增整合層操作資源 `/api/knowledge/operations/{operationId}`，僅供操作本人或明示授權者查詢。長作業回 202 及 operationId／statusUrl；同步完成可回原成功狀態。

操作至少記錄 `PENDING`、`RUNNING`、`SUCCEEDED`、`FAILED`、`RECONCILIATION_REQUIRED`，以及 tenant、actor、target、result reference、safe error、建立與更新時間。瀏覽器離線不取消已提交發布；操作結果未知不等於失敗。

## 10. 現有 Portal 功能遷移清單

除特別註明外，新外部路徑為「將下列 `/api/` 換成 `/api/knowledge/`」，HTTP method 與 resource ID 保留。這是完整端點映射規則，不將健康檢查或舊首頁當成業務 API 轉接。

| ID | Method | 現有路徑 | 整併後歸屬／注意事項 |
|---|---|---|---|
| API01 | GET | `/api/dashboard` | 知識工作區摘要；不可成為第二套全站首頁 |
| API02 | GET | `/api/documents` | 文件清單；強制 scope 與分頁 |
| API03 | POST | `/api/documents/import-pdf` | 匯入 PDF，保留解析結果與附件處理 |
| API04 | POST | `/api/documents/import-markdown` | 匯入 Markdown，清理不安全內容 |
| API05 | POST | `/api/documents/{document_id}/start-revision` | 從正式版建立修訂，保留冪等與版本檢查 |
| API06 | GET | `/api/documents/{document_id}/draft/assets` | 草稿附件清單 |
| API07 | POST | `/api/documents/{document_id}/draft/assets` | 附件上傳；streaming、大小與內容驗證 |
| API08 | DELETE | `/api/documents/{document_id}/draft/assets/{filename}` | 附件刪除；檢查草稿狀態與引用 |
| API09 | GET | `/api/documents/{document_id}/draft/assets/{filename}` | 同源、授權的附件預覽／下載 |
| API10 | POST | `/api/documents/{document_id}/draft/asset-ref` | 附件引用操作；限制外部來源與路徑 |
| API11 | POST | `/api/documents` | 建立文件；保留原 ID 與 owner |
| API12 | GET | `/api/documents/{document_id}` | 文件詳情資料來源 |
| API13 | GET | `/api/reviews/pending` | 我的待辦及待審列表 |
| API14 | POST | `/api/documents/{document_id}/discard-draft` | 放棄草稿；不同於刪除正式文件 |
| API15 | POST | `/api/documents/{document_id}/unpublish` | 下架及下游生效追蹤 |
| API16 | DELETE | `/api/documents/{document_id}` | 刪除；沿用領域狀態限制並稽核 |
| API17 | PUT | `/api/documents/{document_id}/draft` | 儲存草稿；必須處理版本衝突 |
| API18 | POST | `/api/documents/{document_id}/validate` | 草稿驗證；保留 blocking／warning 差異 |
| API19 | POST | `/api/documents/{document_id}/submit-review` | 送審；綁定當時草稿 revision |
| API20 | POST | `/api/reviews/{review_id}/decision` | 核准／補件／拒絕；驗證審核政策 |
| API21 | POST | `/api/documents/{document_id}/publish` | 發布；高風險、冪等、追蹤生效 |
| API22 | POST | `/api/releases/rollback` | 回退發布版本；確認影響及理由 |
| API23 | GET | `/api/releases` | 版本清單；依核准能力呈現 |
| API24 | GET | `/api/releases/compare` | 版本比較；對兩個版本均授權 |
| API25 | GET | `/api/audit-events` | 整合稽核來源，保留原事件 ID |
| API26 | GET | `/api/documents/{document_id}/test-cases` | 文件測試題目 |
| API27 | POST | `/api/documents/{document_id}/test-cases` | 建立測試題；保留來源案件參考 |
| API28 | GET | `/api/documents/{document_id}/test-runs` | 測試歷程與受測版本 |
| API29 | POST | `/api/documents/{document_id}/draft-search` | 草稿試問；清楚標示非正式版本 |
| API30 | POST | `/api/documents/{document_id}/test-cases/{test_case_id}/run` | 執行測試；保留測試／版本證據 |
| API31 | POST | `/api/admin/bootstrap-release-0001` | 維運限定，不提供一般 BFF 公開路由；以受控維運程序保留 |
| SYS01 | GET | `/healthz` | 保留各服務探針；不顯示敏感部署資訊 |
| SYS02 | GET | `/` | 舊 UI 退場／相容導向，不映射成知識 API |
| SYS03 | static | `/static/*` | 共用 Shell 資產建置；避免兩套同名路徑互相覆蓋 |

現有文件匯出、下載或深連結若在前端而非 API 裝飾器中產生，M0 必須透過實際 UI 流程補列清單。不得僅以本表端點全數有 handler 就宣稱功能完整。

## 11. 附件、內容呈現與同源安全

1. 附件列表、預覽、下載、上傳及刪除都經同一認證與 document scope，不以「知道 URL」作為授權。
2. 對 filename 正規化，拒絕路徑穿越、絕對路徑及編碼繞過；實際儲存 key 由服務端決定。
3. 限制大小、數量、MIME 與實際內容；M0 盤點現有上限，M1 將前端、BFF、服務及 ingress 設成一致值，不因整併默默放寬。
4. 不支援的主動內容不可 inline 執行；下載需適當 Content-Disposition、Content-Type、nosniff。
5. Markdown／HTML 預覽必須清理 script、危險 URL 及事件屬性。單一 origin 會放大 XSS 對其他後台模組的影響，需測試而非只依賴 CSS 隔離。
6. 外部圖片與附件引用若由服務端抓取，必須防 SSRF，限制協定、目的網域／網段、重新導向與大小；不得容許任意內網請求。
7. Blob preview URL 於切換文件或離開頁面時釋放；附件請求不得沿用過期 actor headers。
8. 快取敏感文件／附件時需 private／適當 no-store；禁止 CDN 用未包含授權範圍的 key 共用敏感回應。
9. CSP、frame 限制與安全 headers 由共用入口管理；不得為相容舊 UI 而全面允許任意 script。
10. 匯入失敗的暫存附件有可追蹤清理政策；清理不得刪除已提交草稿使用的資產。

## 12. 跨領域關聯、事件與一致性

### 12.1 關聯資料契約

延伸既有 quality case 的 document／FAQ 關聯，不取代原有欄位。新增證據參考採 additive schema，舊 reader 忽略新增欄位仍可運作。

以下為目標概念資料範例，實際欄位命名需對齊既有 model：

```json
{
  "schemaVersion": 1,
  "tenantId": "tenant-company",
  "qualityCaseId": "case-001",
  "knowledgeType": "DOCUMENT",
  "knowledgeId": "doc-001",
  "draftRevision": 8,
  "versionId": "version-003",
  "releaseId": "release-012",
  "testRunIds": ["test-draft-021", "test-live-022"],
  "effectiveReleaseId": "release-012",
  "verificationStatus": "VERIFIED",
  "linkedBy": "user-001",
  "correlationId": "corr-20260904-001"
}
```

尚未發布時，versionId／releaseId／effectiveReleaseId 為 null，testRunIds 可為空陣列。FAQ 使用自身版本契約，無對應 release 時明示不適用，不製造假的文件發布 ID。

測試通過必須綁定內容版本；草稿再次修改後，舊測試可留存但不得當作新草稿已通過的證據。回退也需重新判定原案件改善是否仍有效。

### 12.2 事件投遞

- 優先沿用專案既有可靠事件機制；若尚無「領域提交與事件持久化一致」保障，新增 transactional outbox 或等價持久機制。
- 事件至少包含 eventId、schemaVersion、source、eventType、tenant、aggregateId、aggregateVersion、actorId、occurredAt、correlationId、payload reference。
- 內容事件可涵蓋草稿儲存、送審、審核決策、發布完成／失敗、下架、回退及正式測試完成；不在事件中複製整段敏感對話。
- 採至少一次投遞，消費者以 eventId 防重，依 aggregateVersion 防止亂序事件覆蓋較新狀態。
- 有重試、失敗佇列、人工重送與 reconciliation；暫定每 5 分鐘補償一次，正式頻率依 M0 容量基準確認。
- 若儲存技術不支援跨項目交易，先持久記錄操作意圖與狀態，靠可重入作業及對帳收斂，不宣稱跨服務原子交易。

### 12.3 部分成功處理

| 情境 | 必須行為 |
|---|---|
| 文件建立成功，案件關聯失敗 | 顯示既有 documentId，僅重試關聯 |
| 領域已發布，BFF timeout | 查冪等結果／operation 狀態；不直接再發布 |
| 發布完成，品質 read model 未更新 | 文件顯示權威狀態，品質頁顯示更新延遲；由事件補償 |
| 正式試問失敗 | 不自動結案；保留失敗證據與修正入口 |
| Agent 尚未載入新 release | 顯示等待生效，不顯示已解決 |
| 權限在作業期間被撤銷 | 提交前重新授權；後續查詢按當前權限；已提交不可撤銷動作記錄真實狀態 |

## 13. 資料遷移與相容策略

1. 本案預設不搬移文件正文、附件與發布成果，先共享既有權威服務。
2. 需要新增 tenant、關聯證據或 operation 時採向後相容 schema；不得先刪除舊欄位。
3. 建立 migration manifest：資料類型、來源、數量、ID、版本、歸屬、異常清單及校驗結果。
4. 正式變更前執行唯讀盤點與 dry run；新增 metadata 寫入前建立可驗證備份。
5. tenant backfill 需經資料負責人確認；未分類資料 fail closed，不能猜測為公用。
6. 遷移後抽查與自動比對：文件／草稿／附件數量、發布引用、審核紀錄、品質關聯及原始 ID 不變。
7. 切換前後保持同一領域 single writer；新舊 UI 可在短期呼叫同一寫入服務，但禁止各自維護獨立資料副本。
8. 舊 client 未帶必要並發資訊時，需相容 adapter 或禁止該寫入，不能以最後寫入者勝出掩蓋衝突。
9. 回退 UI 不等於回復資料備份；新版本產生的合法資料須保留並可被回退版本安全讀取。
10. destructive schema cleanup 另立後續變更，待相容窗口結束及回退需求解除後才執行。

## 14. 工程里程碑與派工

M0–M4 是本次整併里程碑；既有 Phase 0–3 仍是功能範圍來源。各工作包可由同一人兼任，但每項交付需有實作者及獨立審查者。

### M0：現況盤點與契約凍結

| 工作包 | 內容 | 主責 | 交付與驗收 |
|---|---|---|---|
| M0-01 | 畫面、API、附件、下載、deep link 與使用者流程盤點 | 前端＋QA | 功能對照表，每項有保留／移入／維運限定決策 |
| M0-02 | 角色、capability、tenant／owner scope 與自審政策盤點 | 後端＋資安＋BU | 核准的映射矩陣及未映射拒絕案例 |
| M0-03 | 資料所有權、關聯及發布生效機制確認 | 後端 | 領域契約、資料字典、事件與 operation 設計 |
| M0-04 | 本機／雲端設定、IAM、入口與基準指標 | 平台＋QA | 環境矩陣、基準測試、切換／回退草案 |

進入條件：可取得目前程式及測試環境，明確指定 BU、技術、資安與平台窗口。

退出條件：第 20 節影響 M1 的決策已簽核，範圍與 API 契約可供前後端獨立開發；歸屬不明資料有隔離方案。

### M1：單一入口、授權與整合 API

| 工作包 | 內容 | 主責 | 交付與驗收 |
|---|---|---|---|
| M1-01 | Knowledge adapter 與受控 namespace | 後端 | API mapping、契約測試、錯誤轉換 |
| M1-02 | 統一 session／capabilities 與委派 actor | 後端＋平台 | 正式身分鏈、服務驗證、CSRF／token 測試 |
| M1-03 | tenant／owner scope 與資源授權 | 後端＋資安 | 跨租戶、跨單位、附件 IDOR、偽造 headers 均拒絕 |
| M1-04 | 並發、冪等、operation 及 timeout | 後端 | 重複提交、未知結果與失敗復原測試 |
| M1-05 | 首條垂直切片的最小 Shell 路由 | 前端 | 同源開啟案件及文件，無第二次登入 |

依賴：M0-02、M0-03、M0-04。退出條件：安全與 API 契約測試通過，單一身分可以完成授權範圍內的文件讀寫；不能僅以 fake actor 測試代替真實身分鏈。

### M2：知識功能完整納入共同介面

| 工作包 | 內容 | 主責 | 交付與驗收 |
|---|---|---|---|
| M2-01 | 共用導覽、文件詳情及角色呈現 | 前端 | 一套 Shell，無獨立 Portal 身分控制 |
| M2-02 | 新增、匯入、草稿、附件、預覽 | 前端＋後端 | API03–12、14、16–18 的完整 UI 流程 |
| M2-03 | 審核、發布、下架、版本比較與回退 | 前端＋後端 | 操作確認、錯誤與生效狀態完整 |
| M2-04 | 試問、測試題與執行紀錄 | 前端＋後端 | 草稿／正式版本清楚標示，測試綁定版本 |
| M2-05 | 路由、未儲存防護、可及性及全功能回歸 | 前端＋QA | 第 10 節逐項附測試結果，無遺漏能力 |

依賴：M1 契約完成。退出條件：一般知識維護不再另開 Portal；完整功能對照表無未處理項目。

### M3：品質改善流程與一致性

| 工作包 | 內容 | 主責 | 交付與驗收 |
|---|---|---|---|
| M3-01 | 案件與文件／FAQ 雙向關聯 | 後端＋前端 | 保留上下文、版本與改善證據，不重建品質領域 |
| M3-02 | 待辦整合與文件成效分頁 | 前端＋後端 | 可見性一致，統計有更新時間，不建立第二份正文 |
| M3-03 | 發布生效、事件、重試及 reconciliation | 後端＋平台 | 重複／亂序／中斷投遞後狀態可收斂 |
| M3-04 | 正式驗證、觀察與結案規則 | 後端＋BU＋QA | 發布不自動結案，失敗及回退可追蹤 |
| M3-05 | 跨來源稽核與操作追蹤 | 後端＋QA | 從案件到版本、發布及測試可追完整 correlation |

依賴：M2 核心流程可用；M3-01 的契約與垂直切片可在 M1 後先行。退出條件：第 7.1 節正常與失敗流程全部有端到端證據。

### M4：部署切換、驗收與舊介面退場

| 工作包 | 內容 | 主責 | 交付與驗收 |
|---|---|---|---|
| M4-01 | 啟動腳本、環境文件與 Terraform | 平台 | 單一對外入口、內部 IAM、health／monitoring 契約 |
| M4-02 | 舊連結轉換與 feature flags | 前端＋後端 | GET 安全導向；舊 POST 不以轉址重送 |
| M4-03 | 真實依賴整合驗證與 BU UAT | QA＋BU | 身分、儲存、附件、發布、Agent 生效均有證據 |
| M4-04 | 灰度、監控與回退演練 | 平台＋後端 | 指標可觀察，回退保留新資料且不降低安全 |
| M4-05 | 交接與關閉舊 UI 公開入口 | 平台＋BU | 教學、runbook、值班窗口、退場簽核 |

依賴：M1–M3 必要項完成。退出條件：第 22 節 DoD 全部通過；未經 BU／資安／平台簽核不得關閉唯一可用操作流程。

## 15. 測試與驗收矩陣

### 15.1 工程測試

| ID | 層級 | 情境 | 預期結果 |
|---|---|---|---|
| T01 | 契約 | 第 10 節全部端點 mapping | Method、路徑、schema、授權、錯誤與附件行為一致 |
| T02 | 安全整合 | 無登入、session 過期、錯誤 audience／issuer | 拒絕請求，不 fallback Demo |
| T03 | 安全整合 | 偽造 X-Portal-Role／User／Owner | 不能取得能力，稽核記錄可信 actor |
| T04 | 安全整合 | 跨 tenant／owner 讀寫文件及猜測附件 URL | 無資料洩漏或修改；回應符合不揭露政策 |
| T05 | 權限回歸 | Contributor、Reviewer、Manager、Auditor、Platform | 每個 capability 與核准自審政策吻合 |
| T06 | 安全整合 | CSRF、開放轉址、SSRF、Markdown XSS、路徑穿越 | 被拒絕或安全化，其他模組 session 不受影響 |
| T07 | 領域整合 | 並行儲存／審核／發布同文件 | 舊 revision 衝突，不能審核或發布錯誤版本 |
| T08 | 領域整合 | 同 idempotency key 重送及不同 payload 重用 | 只有一份結果；不同 payload 回衝突 |
| T09 | 故障注入 | Portal 已提交但 BFF 斷線 | 查得到原結果，不重複建文件／發布 |
| T10 | 前端 E2E | PDF／Markdown 匯入、圖片、草稿、送審、發布 | 全程同一 Shell，附件可預覽且不遺失 |
| T11 | 前端 E2E | 未儲存離開、重整、返回案件、權限不足 | 正確提示與恢復，不丟失已提交狀態 |
| T12 | 流程 E2E | 案件 → 草稿 → 試問 → 發布 → Agent 生效 → 正式驗證 | 證據完整，人工確認後才結案 |
| T13 | 事件整合 | 重複、亂序、失敗後重放事件 | 不重複通知／關聯，較新狀態不被覆蓋 |
| T14 | 流程 E2E | 發布成功但索引延遲／Agent 載入失敗 | 顯示等待或失敗，不標記問題已解決 |
| T15 | 領域回歸 | FAQ 維護與品質關聯 | 原領域功能不退化，不產生假文件版本 |
| T16 | 稽核整合 | 一次跨服務高風險操作 | actor、tenant、target、版本、結果、來源及 correlation 可追蹤 |
| T17 | 相容 E2E | 舊文件／審核／版本 GET 連結與舊寫入 URL | 導向正確資源；不因 POST redirect 產生誤提交 |
| T18 | 部署演練 | 灰度、服務故障、UI 回退 | 其他模組可用，新產生資料保留，安全邊界不降級 |
| T19 | 效能 | 既定併發、文件量與上傳負載 | 符合第 17 節基準，無無界聚合或 worker 阻塞 |
| T20 | 資料驗證 | 遷移前後 manifest 與抽查 | 文件、附件、版本、關聯及 ID 一致，例外有處置 |

測試分為純單元、fake adapter 契約、實際服務整合與 BU UAT。Fake 測試只驗證程式分支，不足以證明 Entra、平台 IAM、正式儲存或 Agent 生效。

若本機使用 FILE repository，而目標環境使用其他儲存實作，必須在目標儲存類型驗證並發、冪等、事件與查詢 scope。發布驗收至少包含實際下游依賴的一次完整測試。

### 15.2 BU UAT 腳本

| ID | 使用者情境 | 驗收判定 |
|---|---|---|
| U01 | 編輯者登入，查到本人負責文件，修改並送審 | 不需第二網址／登入；不用輸入技術 ID；能說明下一步由誰處理 |
| U02 | 從負評案件找到既有文件，修正後返回案件 | 系統保留關聯；不需重新搜尋原案件 |
| U03 | 匯入文件並修正解析／附件問題 | 能辨識阻擋錯誤並完成重試；不產生重複文件 |
| U04 | 審核者退回補件，編輯者修正再送審 | 意見與版本清楚，權限符合核准政策 |
| U05 | 管理者發布，遇到 Agent 尚未更新 | 能理解「已發布但未生效」，不誤判案件已解決 |
| U06 | 正式試問失敗後繼續改善 | 案件保留未完成，能找到受測版本及修正入口 |
| U07 | 稽核人員查閱發布與案件歷程 | 看得到授權紀錄，但不能修改知識或發布 |
| U08 | 原書籤導向新後台、帳號中途過期 | 能恢復到同一資源；高風險操作不被自動重送 |

由至少一名代表性知識維護者、一名審核／管理者參與；記錄完成率、卡點、誤操作、是否需工程師代操作。U01–U06 必須完成，不能以開發者示範代替 BU 驗收。

## 16. 開發、部署與切換

### 16.1 本機啟動

- 一個標準啟動指令啟動必要服務，輸出唯一建議操作網址 `http://127.0.0.1:8092`。
- Portal 內部 port 在整合模式明確設定為 8091；Mock Ticket 使用情況由腳本檢查，不依兩個模組不同預設猜測。
- 啟動前檢查 port 衝突及必要依賴；錯誤指出是哪個內部服務不可用。
- Agent 與 Teams adapter 的既有服務入口保持不變；不得為了整併破壞 Bot 測試流程。
- 開發模式明確顯示環境標籤；DEMO／HEADER 設定不能被正式部署默認繼承。

### 16.2 設定契約

下列為所需設定責任，名稱除既有項目外屬建議，實作時集中於 settings，禁止散落硬編碼。

| 設定責任 | 規格 |
|---|---|
| Public base URL | 只代表統一後台 HTTPS 入口，用於登入 callback 與正式連結 |
| Knowledge internal base URL | 僅 BFF 使用；不輸出到瀏覽器 bootstrap |
| `KNOWLEDGE_PORTAL_PUBLIC_URL` | 相容期僅用於舊入口處理；新操作不依它跨站開頁 |
| Auth mode／issuer／audience | 外部登入與內部委派分開；正式模式拒絕 HEADER／DEMO |
| Service identity／signing keys | 使用受控 secret／平台身分；有輪替與失效策略 |
| Deployment tenant／scope policy | 服務端受管理設定，與歷史資料分類一致 |
| Upload limits／timeouts | 前端、BFF、服務、ingress 一致；能在 UI 顯示限制 |
| Feature flags | 依環境／授權群組控制整併 UI、流程連動與舊 UI 入口；由伺服器生效 |
| Operation／event retry settings | 有界重試、退避、失敗佇列及補償頻率 |

### 16.3 Terraform 與平台變更

檢視並更新 `infra/terraform/ai_ops.tf`、`infra/terraform/variables.tf`、`infra/terraform/ai_ops_monitoring.tf` 與環境 inventory。

必要交付：

1. 統一公開入口、路由與登入 redirect URI 設定。
2. Portal 僅允許 BFF／核准維運身分到達與呼叫的 ingress／IAM；網路可達性與服務授權都需驗證。
3. 委派身分簽章／service credentials 的 secret 權限與輪替。
4. 各服務 liveness、readiness、依賴健康與 rollout 設定。
5. BFF 的資源、併發、上傳限制、timeout 與下游連線配置。
6. operation、事件失敗、知識 API 與 Agent 生效延遲的監控及告警。
7. Terraform validate、環境 plan 審查、部署後 smoke 證據；未執行 plan／apply 不得標記雲端交付完成。

readiness 要區分全站核心故障與知識依賴故障。Knowledge 暫不可用時其他後台模組應可使用，頁面顯示局部故障；不以 Portal 健康檢查失敗直接讓整個後台永久退出服務。

### 16.4 舊入口相容及退場

1. 相容窗口建議至少 14 天，起算點為正式 BU 驗收通過；實際期間由平台與 BU 在 M0 核准。
2. 舊 GET 文件、審核與版本連結轉換到新路由；登入後仍返回原資源，不能只導向首頁。
3. return URL 僅接受本站允許的路由，禁止任意外站轉址。
4. 舊 POST／PUT／DELETE 不以 301／302 轉址重送。相容期透過已授權 adapter 處理；停止支援後回明確升級錯誤／410。
5. 觀察舊入口流量、失敗及外部依賴，完成通知與書籤更新後關閉舊 UI 公開存取。
6. 需要保留維運 UI 時僅限私有、受核准且可稽核的 break-glass 存取，不作為 BU 日常入口。
7. 舊 UI 公開退場不代表刪除知識服務 API 或資料。

### 16.5 灰度與回退 Runbook

| 步驟 | 操作與檢查 | 回退措施 |
|---|---|---|
| R01 | 備份、manifest、相容性檢查與旗標預設關閉 | 停止切換，維持原流程 |
| R02 | 部署向後相容的服務／adapter，舊 UI 尚可用 | 回退 adapter；不回復已有合法資料 |
| R03 | 開放內部測試群組，執行 T02–T18 | 關閉新 UI 旗標，保留 operation 查詢與對帳 |
| R04 | 小範圍 BU 試用，核對錯誤、發布、生效及稽核 | 將未完成作業交由受控既有入口處理 |
| R05 | 全量切換並啟動相容窗口 | 必要時回退 UI 版本；驗證新 schema 可讀 |
| R06 | 窗口結束，停用舊 UI 公開入口 | 僅可恢復安全且經驗證的入口，不重啟不安全 HEADER 模式 |

立即停止擴大流量的條件：任何跨租戶／越權存取、資料遺失、重複發布、錯誤版本生效、無法追蹤高風險操作。一般效能／錯誤率條件見第 17 節。

若舊 UI 無法符合目前安全契約，不得用恢復舊 UI 作為回退方式；改為新 UI 唯讀／暫停知識寫入，透過受控維運流程完成修復。

## 17. 可觀測性與非功能驗收

### 17.1 指標與稽核

- API：依 route、method、status 分類的延遲、錯誤、timeout；避免用 documentId 作為高基數 metric label。
- 授權：拒絕原因分類、偽造 actor、tenant scope 不符；日志不寫 token 或完整敏感 payload。
- 作業：進行中數量、最大等待時間、重試次數、未知結果、失敗佇列及補償落差。
- 知識：發布成功／失敗、發布到生效耗時、正式驗證結果、回退事件。
- 流程：案件到草稿、送審、發布、驗證的耗時與中斷點。
- 舊入口：使用量、轉址錯誤、殘存 client，作為退場依據。
- 稽核必含真實 user、服務 actor、tenant、target、前後版本、action、outcome、時間、event source 與 correlation；高風險動作另記原因。

### 17.2 建議驗收門檻

以下為工程提案值，M0 需以既有環境與代表性資料量確認並記錄基準，不能當作目前效能實測結果。

| 項目 | 目標／處置 |
|---|---|
| 一般清單與詳情 API | 代表性負載下 p95 ≤ 2 秒；不含 LLM、檔案傳輸及發布 |
| BFF 額外處理延遲 | 本服務處理 p95 ≤ 200 ms，不含下游等待；超標分析而非只增大 timeout |
| 發布請求 | 需要長處理時先回 operation；不讓瀏覽器無狀態等待整段流程 |
| 發布到生效 | 超過 5 分鐘標示延遲並通知維運；實際承諾依索引批次週期於 M0 調整 |
| 事件補償 | 失敗可見，對帳後可收斂；不得靜默丟事件 |
| 整合錯誤率 | 灰度期 5xx 比基準增加 1 個百分點且持續 5 分鐘，停止擴大並調查 |
| 效能回退 | 同負載下 p95 較基準惡化逾 30% 且持續 10 分鐘，停止擴大並調查 |
| 安全／資料正確性 | 零容忍已知越權、跨租戶洩漏、資料遺失及重複發布 |

低流量時必須搭配實際失敗案例與合成 smoke，不以小樣本百分比單獨決定上線。所有門檻變更保留審查紀錄。

## 18. 風險與降低方式

| 風險 | 徵兆／影響 | 降低措施 |
|---|---|---|
| 誤把 UI 整併當權限等價 | 同一人進新介面突然可發布更多資料 | M0 矩陣、deny-by-default、後端負向測試 |
| Portal 缺少 tenant 上下文 | ID 正確就可讀跨租戶文件 | 可信 tenant、repository scope、歷史歸屬盤點 |
| API／static 路徑碰撞 | 文件請求回傳錯誤領域資料或 JS | 明確 namespace、共用資產管理、mapping 測試 |
| 單一 origin 放大 XSS | 文件預覽可操作整個後台 | Sanitization、CSP、HttpOnly、CSRF 與附件測試 |
| 重複建立／發布 | timeout 後使用者重按導致多筆資料 | 持久冪等、operation 查詢、部分成功恢復 |
| 發布與生效混淆 | 文件已發布但客服仍回舊答案 | 獨立顯示 release 與 loaded version，正式測試 |
| 文件與品質狀態分歧 | 案件標記完成但沒有有效證據 | 事件、對帳、版本綁定、人工結案 |
| 遷移時丟功能 | 只移文件 CRUD，遺漏附件／比較／回退 | 完整 API 表與 UI UAT 對照 |
| BFF 成為瓶頸／巨型模組 | 聚合阻塞所有後台請求 | 模組化 adapter、有界查詢、streaming、timeout 隔離 |
| 回退不可用 | 新 schema 使舊 UI 無法讀取 | Additive migration、回退演練、延後 destructive cleanup |
| 範圍膨脹 | 同時重寫 RAG、換框架、改審核制度 | 本規格非目標及獨立變更審核 |

## 19. 人力、順序與估算

| 里程碑 | 估計人日 | 主要依賴 |
|---|---:|---|
| M0 | 3–4 | 現況盤點、BU／資安決策 |
| M1 | 6–9 | 身分、API、scope 契約 |
| M2 | 7–11 | 核心 adapter 可用、頁面移入 |
| M3 | 5–9 | 關聯、事件、正式生效可觀測性 |
| M4 | 4–7 | 真實依賴驗證、IaC、UAT 與切換 |
| 合計 | **25–40 人日** | M0 後重新估算 |

這是工作量估算，不是承諾日曆天數。未包含企業 SSO 核准、網域／網路申請、資安排程等待及大量歷史資料人工分類。

建議工作線：一名前端、一名後端，平台／QA 依里程碑投入；技術審查者不僅驗收 UI，需審查授權、資料一致性與回退。

開發順序：M0 → M1 身分與 API → 首條案件／文件垂直切片 → M2 完整搬入與 M3 流程連動 → M4。前後端可依凍結契約平行，但正式 UI 不得先使用不安全的角色 headers 暫時上線。

若 M0 發現需要全新多租戶資料模型、替換既有認證、建立全新發布事件設施，應拆出明確增量估算，不將其默默包含在 25–40 人日中。

## 20. 決策清單與工程預設

以下是必須由對應負責人核准的工程決策，不是待開發者自行猜測的空白項目。未獲核准時依表列限制推進，不擴張權限或正式暴露服務。

| ID | 決策 | 建議預設 | 決策人／期限 | 未決影響 |
|---|---|---|---|---|
| D01 | 產品名稱與唯一網域 | AI 資訊客服營運後台，單一 origin | BU＋平台／M0 | 可開發相對路由，不設定正式 callback |
| D02 | 外部登入模式 | Entra＋BFF server session | IAM／資安／M0 | M1 真實登入整合不能驗收 |
| D03 | 角色映射與跨單位範圍 | 明示 capabilities、未映射拒絕 | BU＋資安／M0 | 不上線具有寫入能力的新角色 |
| D04 | 自審及 relaxed workflow | 盤點並明示既有例外，不因整併自動改政策 | BU 流程負責人＋資安／M0 | 不宣稱四眼審核；正式審核矩陣未簽核不得切換 |
| D05 | 租戶部署與歷史歸屬 | 單租戶固定 trusted tenant；多租戶需 repository 隔離 | 資料負責人＋後端／M0 | 未分類資料不可開放，多租戶正式上線受阻 |
| D06 | Portal 部署邊界 | 內部獨立服務，BFF 受控呼叫 | 平台＋技術負責人／M0 | 只做本機 adapter，不公開 Portal |
| D07 | Agent 生效確認機制 | 讀取可驗證 release／index version，不猜測 | Agent 負責人／M0 | 可開發發布頁，但 M3 改善閉環不能完成 |
| D08 | 高風險動作確認及理由 | 發布、下架、刪除、回退保留稽核與明確確認 | BU＋資安／M1 前 | 不簡化既有安全步驟 |
| D09 | 上傳、timeout、容量與效能門檻 | 不放寬現有限制；以第 17 節為基準提案 | 平台＋QA／M0 | 不進入容量／部署驗收 |
| D10 | 相容窗口與舊入口關閉 | 驗收後至少 14 天，先觀察再關閉 | BU＋平台／M0 定策略、M4 簽核 | 維持受控相容，不刪 API／資料 |

## 21. 預期修改範圍與參考文件

本節是後續實作定位，不表示本次已修改這些檔案。新模組名稱由實作時依現有結構決定。

| 位置 | 後續工程內容 |
|---|---|
| `agent_service/src/ai_ops_backoffice/api.py` | 掛載受控 knowledge routes、共用 session／error；保持 domain 邊界 |
| `agent_service/src/ai_ops_backoffice/settings.py` | internal URL、登入、delegation、旗標與限制設定 |
| `agent_service/src/ai_ops_backoffice/static/js/main.js` | 共用導覽、知識頁路由、品質上下文；拆分過大的 UI 模組 |
| `agent_service/src/ai_ops_backoffice/static/js/api.js` | 統一 client、CSRF／登入過期、錯誤、作業輪詢 |
| `agent_service/src/ai_ops_backoffice/quality_domain.py` | 延伸文件／FAQ 關聯及驗證證據 |
| `agent_service/src/knowledge_portal/api.py` | 內部委派驗證、scope、契約相容；不開放任意代理 |
| `agent_service/src/knowledge_portal/auth.py` | 分離可信委派與本機 HEADER 模式 |
| `agent_service/src/knowledge_portal/models.py` | tenant／actor 與向後相容資料契約 |
| `agent_service/src/knowledge_portal/rbac.py`、`role_capabilities.py` | 對齊已核准能力與資料範圍，不偷改審核政策 |
| `agent_service/src/knowledge_portal/static/js/main.js`、`api.js`、`session.js` | 可重用功能拆入共用 Shell，移除獨立 session 與絕對 API 假設 |
| `infra/terraform/ai_ops.tf`、`variables.tf`、`ai_ops_monitoring.tf` | 入口、內部服務授權、設定與監控 |
| `infra/ai-ops-environment-inventory.json` | 更新可驗證的環境責任及部署資訊 |
| `scripts/verify_local_portal.sh` | 與整合啟動模式／port 契約一致 |
| `scripts/ops_bu_walkthrough.py`、`ops_live_smoke.py`、`ops_uat_handoff.py`、`ops_backup_verify.py` | 擴充單一入口流程、驗收、交接與備份證據 |

既有功能規格：

- [Phase 0：基礎規格](ai-ops-backoffice-phase-0-foundation-spec.md)
- [Phase 1：營運 MVP](ai-ops-backoffice-phase-1-operations-mvp-spec.md)
- [Phase 2：品質閉環](ai-ops-backoffice-phase-2-quality-loop-spec.md)
- [Phase 3：AI 治理](ai-ops-backoffice-phase-3-ai-governance-spec.md)

若既有 Phase 規格與本文件在功能／權限政策上衝突，需形成 ADR 與需求變更記錄；本文件不自動覆蓋已核准的業務規則。

## 22. 最終完成定義與交接清單

只有以下全部具備證據，才能宣稱「整併完成」：

- [ ] BU 僅使用一個網址、一套導覽與一次登入即可完成核心知識工作。
- [ ] 第 10 節全部功能已映射到新 UI、內部 API 或受控維運程序，無未說明的能力遺失。
- [ ] 不再以另開 Portal 分頁作為一般文件維護的必要步驟。
- [ ] 文件正文、附件、草稿、審核與發布仍有唯一權威來源，沒有第二套正文寫入。
- [ ] 案件、文件／FAQ、內容版本、發布與測試證據可雙向追蹤。
- [ ] 發布、實際生效、正式驗證與案件結案為不同可辨識狀態。
- [ ] 正式環境不信任瀏覽器角色 headers，不暴露內部服務憑證或不安全 Demo 身分。
- [ ] tenant／owner 隔離、附件安全、並發與冪等測試全部通過。
- [ ] 審核、自審、發布及跨單位政策有 BU／資安簽核，不以新 UI 默認行為取代政策。
- [ ] 正常、拒絕、衝突、部分成功、下游失敗與回退流程均有測試結果。
- [ ] 目標儲存及正式身分鏈整合已驗證，非只有 fake／FILE 本機測試。
- [ ] Terraform／環境設定、smoke、監控、備份與回退演練證據可交付。
- [ ] 舊連結相容已驗證，舊 UI 公開退場經簽核，內部知識 API 不被誤刪。
- [ ] BU UAT 通過，有操作手冊、角色說明、常見錯誤處理與維運聯絡窗口。
- [ ] 交接包包含功能對照表、ADR、API 契約、授權矩陣、資料 manifest、測試報告、部署 runbook、回退紀錄及已知限制。

完成度應按上述可驗收交付計算；「頁面已搬過去」「兩個 port 都能開」「單元測試通過」都不能單獨代表整併完成。
