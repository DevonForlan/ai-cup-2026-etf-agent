# Official test-period DataPacks（封測）

人工從競賽後台下載的**測試** DataPack：`<YYYYMMDD>/<原檔名>__<sha前12碼>.json` 與 `__inventory.json`（欄位清單 + 唯讀驗證）。用 `python -m agent.submission.official_test datapack --file ... --date T` 寫入。

- 不會匯入比賽用的 `data\official_datapack\`、`data\settlement\`。主辦方會在比賽前清除測試資料。
- 內容已 gitignore（只追蹤本 README）。
