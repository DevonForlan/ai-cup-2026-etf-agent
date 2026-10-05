# Data Availability Matrix（Round 06）

> AI 產生內容，需人工審閱。時間為台北時間；「可用時間」是我們 PIT 規則使用的時間（`config/data_sources.yaml availability`），不是官方 SLA。
> 失敗處理一律：抓取失敗 → store probe（已存的列）→ CACHED（DEGRADED）或 FAILED/STALE；**絕不**用過期的關鍵行情硬算。

| 資料 | 權威來源 | 可用時間（T-1 資料） | 重要度 | 失敗時 fallback | 失敗影響 |
|---|---|---|---|---|---|
| TWSE 個股收盤 / 成交 | TWSE 證交所（官方 OpenData / 網站） | T-1 約 14:30 後 | **CRITICAL** | store 已有 T-1 → CACHED（L2）；否則 BLOCK | 無 T-1 收盤 → 無法依 derive-orders 計股數 → **不產 D-Plan** |
| TPEx 個股收盤 / 成交 | TPEx 櫃買中心 | T-1 約 14:30 後 | **CRITICAL** | 同上 | 同上 |
| 三大法人（TWSE / TPEx） | TWSE / TPEx | T-1 約 15:00–16:30 | IMPORTANT | store probe；缺 → WARN | 法人特徵缺失（v1 權重低），D-Plan 照產（L2） |
| 主動 ETF 持股（30 檔） | 各投信官網（非統一官方格式） | 各家不同，多為 T-1 晚間 / T 早上 | IMPORTANT | latest → 重試 → 前 3 個公布日 → **STALE_FALLBACK**（沿用已存持股，標示，不偽造今日） | Active Share 以較舊持股計算；>3 交易日 STALE（WARN），>10 日 preflight BLOCK |
| MOPS 月營收 first-seen | 公開資訊觀測站 | 每月 1–10 日陸續公布 | OPTIONAL | 沿用法定截止日可用時間 | 營收因子以較保守時間生效 |
| MOPS 重大訊息 | 公開資訊觀測站 | 即時 | OPTIONAL | 跳過 | 僅敘事 / 事件（v1 不使用） |
| TAIFEX 台指期夜盤 | 期交所 | T 約 05:05 | OPTIONAL | store probe；缺 → WARN | 隔夜特徵缺失（v1 不使用於選股） |
| S&P 500 / NASDAQ / NASDAQ-100 | FRED（St. Louis Fed） | T 約 05:30（可能延遲） | OPTIONAL | store probe | 同上 |
| 費城半導體 SOX | Yahoo（非官方 API） | T 約 05:30 | OPTIONAL | store probe | 同上；ToS 風險已知 |
| TSM ADR | Yahoo（非官方 API） | T 約 05:30 | OPTIONAL | store probe | 同上 |
| USD/TWD | 中央銀行 | T-1 約 17:00 | OPTIONAL | store probe | 同上 |
| 除權息 / 減資（公司行動） | TWSE / TPEx 公告 | 預告於除權息日前 | IMPORTANT | 沿用已存公告；失敗 WARN | 結算股利 / 配股估計可能落後 → 對帳時人工確認（NC-7） |
| 官方結算（持股 / 現金 / NAV） | 主辦方（方式未確認，NC-1） | 未知（預期 T 傍晚） | **CRITICAL**（competition） | 無；人工 SOP 輸入 | 未確認 → competition BLOCK |
| 交易日曆 / 休市日 | TWSE 休市日公告 | 年度公告 | **CRITICAL**（間接） | 過去休市由 store 推得；未來休市需填 `ops.yaml market_holidays` | 未登記的休市日會使 T-1 行情看似過期 → BLOCK（保守） |

## 實測（Round 05–06）
- 全來源即時抓取：Round 05 dry run B 10/10 OK（165 s，ETF 108 s）。
- ETF：Round 06 實測 27/30 最新抓取成功；**中信（CTBC）3 檔 00983A、00995A、00406A 最新與前 3 日查詢皆回空** → STALE_FALLBACK（沿用 10/01–10/02 已存持股）。需要追查發行商端點。
- ETF 並行（4 workers）與循序資料完全相同，2.9× 快（288 s → 100 s）；設定 `etf_fetch.max_workers: 3`。
- 細節：`reports/source_reliability.csv`、`reports/round06_etf_reliability.csv`、`reports/round06_etf_parallel.json`。
