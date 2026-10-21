# Risk Overlay — PIT Data Audit

> AI 產生內容，需人工審閱。研究用；只讀取既有合法公開資料（`data/history`），本輪沒有新增任何資料下載、登入或私有 API。

## 決策時點

T 日 07:00（與凍結 pipeline 的 `as_of = T 07:00+08:00` 相同）。成交在 T 日 VWAP，因此 T−1 收盤 → T 開盤的隔夜跳空**無法**由 T 日決策避開。

## 訊號

| 訊號 | 來源表 | 計算 | 可用時間 | PIT 處理 | 狀態 |
|---|---|---|---|---|---|
| market breadth（站上 MA20 比例） | daily_prices | universe 150 收盤 vs 20 日均 | T−1 15:00 後 | 算至 T−1 後 shift 1 日 | PIT_SAFE |
| EW trend 20D | daily_prices | 每日橫斷面**中位數**報酬累積指數（與 `agent/features/feature_engine.py` 相同） | 同上 | shift 1 | PIT_SAFE |
| EW drawdown 60D | daily_prices | 指數 / 60 日高點 − 1 | 同上 | shift 1 | PIT_SAFE |
| EW volatility 20D | daily_prices | 20 日標準差 × √252 | 同上 | shift 1 | PIT_SAFE |
| SOX / NDX / S&P 500 隔夜 | market_overnight | 前一美股交易日報酬 | available_at 05:30 | as-of ≤ T 07:00，超過 96 小時視為缺值 | PIT_SAFE |
| TSM ADR 隔夜 | market_overnight | 同上 | 05:30 | 同上 | PIT_SAFE |
| 台指期夜盤 | market_overnight | 夜盤收盤 vs 前日 | 05:05 | 同上 | PIT_SAFE |
| USD/TWD 5 日變動 | market_overnight（央行） | close / close(5 筆前) − 1 | 前一日 17:00 | 同上 | PIT_SAFE |

## 驗證

- **與正式 pipeline 對帳**：2024-08-05、2025-04-07、2025-04-09、2025-11-20、2026-03-10、2026-10-15 六個決策日，breadth / EW trend 20D / EW vol 20D / SOX / TSM / TXF 夜盤與 `fs.market` 的最大差異 ≤ 4e-16。
- 缺值：2024-07-01 起各訊號缺值率 0%，USD/TWD 5D 0.9%。缺值 → 該票不投（絕不因缺資料觸發 risk-off）。
- 過期保護：隔夜資料 > 96 小時視為缺值，避免連假時重複使用舊的急跌訊號。
- 10/15 案例另外檢查了紙上交易實際產生時間（2026-10-14 21:26）可見的資料：當時美股 10/14 盤與 10/15 05:05 夜盤**尚未公布**。

## 未使用

- 融資餘額、期貨未平倉、VIX：本輪沒有合法、PIT 可驗證的免登入歷史來源（與 Factor round 的 NOT_AVAILABLE 一致）。
- 任何未來資料或事後回填資料：未使用。
