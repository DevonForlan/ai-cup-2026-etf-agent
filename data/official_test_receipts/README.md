# Official test-period receipts（封測）

每次人工測試上傳的官方回應紀錄：`<YYYYMMDD>/records.jsonl` 與證據截圖。用 `python -m agent.submission.official_test record-upload` 寫入。

- 只存官方回應文字、submission id、截圖、sha256。
- **絕不存** password、cookie、session token、任何 credential。工具偵測到這類字串會拒絕寫入。
- 內容為本機證據，已 gitignore（只追蹤本 README）。
- 封測資料不得混入比賽用的 `submissions\<T>\receipts.jsonl`。
