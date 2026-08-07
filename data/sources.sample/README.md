# 範例知識語料（Sample corpus）

`data/sources/` 存放公司內部的真實知識文件，是 gitignored 的——所以剛
clone 下來的 repo **沒有任何語料**，`./start.sh` 會因為
`Source directory not found: .../data/sources` 而啟動失敗。

這個目錄提供一份可直接使用的假資料，讓本機開發、
`scripts/simulate_teams.py` 與 Agents Playground 測試不必先拿到內部文件：

```bash
cp -r data/sources.sample data/sources
```

`data/sources/` 已被 gitignore，所以複製過去之後不會被誤 commit。

要換回真實語料時，直接把內部文件放進 `data/sources/` 即可（可先刪掉這份
範例）。文件的 YAML front matter 規範見
[`../../docs/knowledge-document-governance.md`](../../docs/knowledge-document-governance.md)。
