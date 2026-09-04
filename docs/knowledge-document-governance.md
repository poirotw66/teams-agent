# 知識文件治理（Knowledge Document Governance）

本文件說明 `data/sources/*.md` 知識文件的 YAML front matter 規範，對應需求書 §9「知識文件治理」與 §8.4「回答原則」。目的是讓每份知識文件具備可追溯的擁有者、版本、生效／檢視日期與可見範圍，而不只是純文字內容。

## 1. Front Matter 欄位

每份 `data/sources/*.md` 文件的檔案最上方，**可選擇性**加上以 `---` 包裹的 YAML 區塊，範例：

```markdown
---
title: VPN 登入問題
owner: IT Infrastructure
version: "1.2"
effectiveDate: 2026-07-01
reviewDate: 2026-10-01
audience:
  - all-employees
---

# VPN 登入問題

...文件內文...
```

支援欄位（僅接受以下欄位，出現其他未知欄位會在建索引時直接報錯，以避免欄位打錯字而被忽略）：

| 欄位 | 說明 | 必填 | 備註 |
|---|---|---|---|
| `title` | 文件標題 | 否 | 若省略，系統會沿用文件內文第一個 `# 標題`（與舊文件相容） |
| `owner` | 文件擁有者／負責單位 | 否 | 例如 `IT Infrastructure`、`IT Service Desk` |
| `version` | 文件版本 | 否 | 請用字串（加引號），例如 `"1.0"`，避免被 YAML 解析成數字 |
| `effectiveDate` | 生效日期 | 否 | `YYYY-MM-DD` |
| `reviewDate` | 下次檢視日期 | 否 | `YYYY-MM-DD` |
| `audience` | 可見對象清單 | 否 | 見下方「audience 與 ACL 的對應」 |

沒有 front matter 的文件會維持現有行為：標題取自內文第一個 `#` 標題，`owner`/`version`/`effectiveDate`/`reviewDate`/`audience` 皆視為未設定（`metadata` 為 `None`），檢索與回答邏輯完全不受影響。

Front matter 區塊在建立索引時會被完整移除，**不會**出現在切片內容（chunk content）中，因此也不會流入 LLM 回答或引用來源文字。

## 2. audience 如何對應到既有的 ACL（`allowed_groups`）

檢索層（`agent_service/src/agent_service/retrieval.py`）原本就用 `DocumentChunk.allowed_groups` 做權限過濾：若清單非空，使用者的 `groups` 必須與其有交集才能看到該文件；清單為空則代表「對所有人開放」。

`audience` 的對應規則：

- `all-employees` 是「開放給所有人」的標記，**不會**被寫入 `allowed_groups`（等同於現行「沒有 audience＝對所有人開放」的行為）。
- 若 `audience` 中出現除了 `all-employees` 以外的值（例如 `branch-cs-team`），這些值會被寫入 `allowed_groups`，之後只有 `groups` 內含相同名稱的使用者才能檢索到該文件。
- 若文件同時存在 `data/metadata.json` 中設定的 `allowedGroups`，該設定優先於 front matter 的 `audience`（向後相容既有機制）。

### 目前語料庫的決策：分公司 CS 團隊 VPN 權限列表

`分公司CS團隊VPN連線可使用權限列表.md` 內容明顯只適用於分公司 CS 團隊，理論上應該設定較嚴格的 `audience`（例如 `branch-cs-team`）。但目前：

1. 既有評估資料集（`outputs/rag-evaluation-2026073*`）中有一筆測試題目預期在**未帶 groups（預設空白）**的情況下也能命中此文件；
2. 目前系統與前端尚未把「分公司 CS 團隊」這個群組串接進使用者的 `groups` 來源（Teams `user.groups` 目前多為空陣列）。

若直接限制此文件的 `audience`，會讓它在預設（無 groups）查詢路徑下完全無法被檢索到，等於直接讓既有評估案例失敗、也讓一般使用者問「VPN 權限」相關問題時得不到答案。因此本次治理作業**保留該文件 `audience: [all-employees]`**，暫不做群組限制，待未來使用者身分（§12）與群組來源正式串接後，再評估是否收斂為受限 audience。此決策同時記錄於程式測試 `test_chunk_markdown_maps_restrictive_audience_to_allowed_groups`（驗證機制本身可正確運作），與本文件中。

## 3. 如何新增一份知識文件

1. 在 `data/sources/` 新增一個 `.md` 檔案（檔名建議與標題一致）。
2. 在檔案最上方加入 front matter，至少建議填寫 `title`、`owner`、`version`、`effectiveDate`、`reviewDate`、`audience`。
3. 內文維持現有格式（`# 標題`、`## 正文（canonical）` 等區段），不需要額外標記。
4. 若文件僅供特定群組使用，於 `audience` 填入該群組代碼（非 `all-employees`），並確認呼叫端（Teams Adapter／Agent Service）已能提供對應的 `groups`，否則該文件將對所有使用者不可見。
5. **ASCII slug 不可撞名**：Gemini File Search 會把檔名中的非 ASCII 字元剝掉後當 upload slug。若兩個檔名只差在中文（例如 `VPN國外….md` 與 `VPN跳板….md`），會撞成同一個 `VPN.md`。`rag-index` 會在建索引時自動檢查並拒絕；請改成含可區分英文的檔名（例如 `VPN-jumpbox-….md`）。
6. 重建索引（見下一節）。

## 4. 如何重建索引

索引由 `agent_service/src/agent_service/indexer.py` 的 `build_index()` 產生，對應套件 entry point `rag-index`：

```bash
cd agent_service
.venv/bin/rag-index
# 或
.venv/bin/python -m agent_service.indexer
```

行為說明：

- 讀取 `RAG_DATA_DIR`（預設 `../data`）底下 `sources/*.md`，解析 front matter 與內文，產生切片（chunk）。
- 若環境變數 `RAG_EMBEDDING_MODEL` 有設定（且對應的 API Key，例如 `GOOGLE_API_KEY`，可用），會呼叫該 embedding 模型產生向量，索引同時支援稀疏（BM25）＋稠密（向量）混合檢索。
- 若 `RAG_EMBEDDING_MODEL` 未設定，索引僅包含稀疏檢索所需資訊，可在完全離線、無 API Key 的情況下建置。
- 產出寫入 `RAG_INDEX_PATH`（預設 `../data/index/chunks.json`），檔案結構為 `{"version", "embeddingModel", "chunks": [...]}`，每個 chunk 除原有欄位外，會多一個可選的 `metadata` 物件（`title`/`owner`/`version`/`effective_date`/`review_date`/`audience`）。
- 舊版（無 `metadata` 欄位）的索引檔仍可被目前程式碼正常讀取，`metadata` 會是 `None`，不影響檢索與回答。

## 5. 品質與治理優先順序

依需求書 §9，文件品質、版本與權限治理的優先順序高於更換檢索產品本身。新增或修改知識文件時，請優先確保：

- `owner` 與 `reviewDate` 正確，以利日後排定文件覆核；
- `audience` 反映真實可見範圍，避免造成資訊外洩或誤導使用者；
- 內文本身不包含 front matter 洩漏、不捏造流程或聯絡方式（見 §8.4 回答原則）。
