# 09 賽前歷史模擬測試計畫（Historical Walk-Forward Competition Simulation）

> 目標：在 10/26 正式開賽前，用歷史交易日完整重演「24 日初賽」，驗證：規則正確性、資料時點正確性、提交可靠度、策略表現相對 baseline。
> 原則：**模擬器 = 主辦方結算規則的忠實複製**；Agent 每天只看得到「T-1 19:30 ～ T 08:55」當下可得的資料。

---

## 1. 測試視窗選擇

| 視窗 | 期間（建議） | 目的 |
|---|---|---|
| W1 同季節 | 2025/10/27–2025/11/28（24 交易日附近） | 同樣的 11 月事件結構（10 月營收 11/10 前、Q3 財報 11/14 前、MSCI 11 月審核） |
| W2 下跌/高波動 | 2025/03/24–2025/04/30（含 4 月關稅衝擊大跌） | 壓力測試：MDD、現金下限 25%、risk_off posture |
| W3 強多頭 | 2025/06–2025/07 或 2026 年任一強勢月 | 測試是否因保守而大幅落後 |
| W4 盤整 | 自選一段低波動月 | 測試 turnover 成本侵蝕 |
| W5 最近期 | 2026/08/31–2026/10/02 | 最接近正式比賽的市況與 universe |

**Universe 注意（survivorship）**：官方 150 檔是 2026/7 月底市值排名。對 2025 年的視窗，使用同一份 150 檔會產生「事後倖存/事後成長」偏差（2026 年市值大 = 2025 年後漲多的股票）。
- 主測：使用官方 150 檔（因為正式比賽就是這份名單），但**報告中明示此偏差**，並以 equal-weight 150 檔 baseline 對照抵銷。
- 輔測：自行重建「該視窗前一月底市值前 100 + 上櫃前 50」的 PIT universe 再跑一次，比較策略排名是否一致。

**LLM 記憶污染（look-ahead via pretraining）**：模型的 knowledge cutoff 若晚於測試視窗，LLM 可能「記得」後來的股價/新聞。對策：
- 優先選 cutoff 之後的視窗（W5）做 LLM 相關評估。
- 對較早視窗：LLM 元件改用匿名化輸入（隱去日期、股票名稱以代號替換）做 ablation；或只評估 quant-only 版本。
- 報告中把「quant-only」與「quant+LLM」分開列示。

## 2. 每日時間線（模擬日 T）

```
T-1 13:30  收盤
T-1 ~14:30 TWSE/TPEx 日成交資料（含成交金額、成交股數）可得
T-1 ~15:00–16:30 三大法人買賣超（T86 等）可得
T-1 ~21:00 融資融券
T-1 19:00  主辦方公布 T-1 結算淨值表（模擬器在此產出 settlement_{T-1}.json）
T-1 19:30  繳交窗口開啟 → Agent 可讀 settlement_{T-1}
T 04:00/05:00 美股收盤 / 台指期夜盤收盤
T 08:30–08:55 盤前試撮（可選用）
T 08:55  截止 → 模擬器鎖定 D-Plan（取最後一次「提交」）
T 13:30  收盤 → 取 VWAP_T = 成交金額/成交股數、close_T
T 19:00  模擬器結算：成交、費稅、NAV_T、違規檢查
```
各資料的實際發布時間需由資料管線記錄（見 taiwan_data_sources 研究筆記），模擬器以「發布時間 ≤ cutoff」過濾。

## 3. Data Cutoff 實作

- 目錄：`data/raw/YYYYMMDD/<source>/<file>` + `manifest.json`（每檔：url、fetched_at、content_as_of、published_at、sha256、parser_version）。
- **Replay 模式**：歷史回測時，資料先全量下載到 `data/history/`，再由 `PITView(as_of=T 08:55)` 產生「當天可見世界」的虛擬 `data/raw/YYYYMMDD/`；Agent 程式碼**只能**透過 PITView 存取資料（同一套程式在正式比賽時改接 live fetcher）。
- 規則：
  - 日線/法人：只用 ≤ T-1 的資料列。
  - 月營收：以 MOPS 實際公告時間戳為準（不是所屬月份）。
  - 財報：以公告日期，不是財報期間；不得使用事後重編數字。
  - 新聞：`published_at ≤ cutoff`；時區統一 +08:00。
  - 美股/ADR：T 日 04:00/05:00（美國 2026/11/1 結束夏令時間 → 美股收盤由台灣時間 04:00 變 05:00，自 11/3 台股交易日起適用）。
- **Leakage 測試**：在 PITView 加 assertion：任何讀取到 `timestamp > cutoff` 的 row 立即 raise；並寫「金絲雀測試」（故意放入未來資料，確認被擋）。

## 4. 成交與記帳（模擬器規格）

| 項目 | 規則 |
|---|---|
| 初始 | cash = 1,000,000,000；holdings = {} |
| 委託 | 由 D-Plan orders（derive-orders.v2：`floor(w × NAV_{T-1} / close_{T-1} / 1000) × 1000 − cur`） |
| 成交 | 全數成交；價格 = VWAP_T = 成交金額 / 成交股數（TWSE STOCK_DAY / TPEx 對應欄位） |
| 無成交（停牌） | 參數化：`skip`（委託不成交）/`reject`；預設 skip 並記錄（NC-4） |
| 手續費 | 0.1425% × 成交金額（買、賣） |
| 證交稅 | 0.3% × 賣出成交金額 |
| 四捨五入 | 參數化：不捨入 / 四捨五入至元 / 無條件捨去（NC-5）；報告各模式差異 |
| NAV | Σ shares × close_T + cash |
| 除息 | 不入現金，累積於 `accrued_dividends`，最終日加回（辦法註1） |
| 除權/分割 | 依市場實況調整股數（NC-7） |
| 違規檢查 | 現金 <0 或 >25%、檔數 ∉[20,30]、權重超限（加碼即警告 / 價格漂移 5 日寬限）、非 150 檔、未繳交 → 警告、當日交易無效、沿用前一日組合；累積 3 次 → 「DQ」 |
| Active Share | 對 30 檔主動 ETF 前 10 大（使用當時可得之持股揭露），多解讀計算，連續 2 日 <20% → 「DQ」 |
| MDD | 日 NAV 序列；同時計算「含期初 10 億」與「不含」兩版 |

**模擬器 golden test**：用手算的 3 日小案例（2–3 檔股票）逐元核對；用 D-Plan EX42 的數字重算委託股數。

## 5. Portfolio Rollover

- 結算結果 `settlement_T.json`（holdings、cash、NAV、accrued_dividends、warnings）是 T+1 Agent 的唯一持倉輸入（模擬「後台庫存明細」）。
- Agent 的自記帳與模擬器結算每日對帳；差異 > 0 即報錯（正式比賽時同理：自記帳 vs 主辦方結算）。

## 6. 提交可靠度測試（Submission Drills）

| 測試 | 方法 | 通過標準 |
|---|---|---|
| 準時性 | 在模擬「時鐘」下跑 24 日，記錄每日 run 時間 | 99% 日完成時間 < 07:30（保留 >80 分鐘緩衝） |
| LLM API 故障 | 注入 timeout/429/500/格式錯誤 | 降級路徑仍能產出合法 D-Plan（quant-only fallback） |
| 資料源故障 | 移除某資料源 | 有替代來源或以前一日資料標記 stale 並保守處理 |
| Schema/語意驗證 | 每日 D-Plan 通過 schema + C1–C14 自檢 | 100% |
| 重繳 | 同日多版提交 | 最後一版生效；≤25 次 |
| 時區/夏令時間 | 2026/11/1 美國夏令時間結束 | 美股資料正確對齊 |
| 假日 | 交易日曆 | 不在非交易日提交 |

## 7. 績效指標

| 指標 | 定義 |
|---|---|
| Final NAV / Total Return | 主要指標 |
| MDD | 日 NAV 峰谷 |
| Daily Volatility / Sharpe（參考） | 24 日樣本極小，只作參考 |
| Turnover | Σ\|交易金額\| / 平均 NAV（日與累計） |
| Transaction Cost | 手續費 + 稅總額，占初始本金 % |
| Hit Rate | 每日「買入/加碼」標的在之後 1/5 日超越 150 檔等權報酬的比例 |
| IC / Rank IC | 每日分數與次日/5 日報酬之 Spearman |
| Concentration | HHI、前 10 大權重、2330 權重 |
| Active Share | 對 30 檔 ETF 之最小值（多解讀） |
| Rule Violations | 警告次數、DQ 事件 |
| Submission Failures | 未在 08:55 前產出合法 D-Plan 的日數 |
| Cost/Token | LLM 成本/日 |
| Reproducibility | 用同一 snapshot + code_version 重跑，target_weight 差異 |

## 8. Baselines（必做）

| Baseline | 說明 |
|---|---|
| B0 Cash-min 0050-like | 依市值加權複製 150 檔前 30 檔，套用 25%/10% 上限，月不調整 |
| B1 等權 150→Top 30 市值 | 等權持有市值前 30 |
| B2 動能 | 20/60 日報酬排名前 25 檔等權，每週調整 |
| B3 法人籌碼 | 外資+投信 5 日淨買超排名 |
| B4 隨機 | 隨機選 25 檔（1000 次 Monte Carlo）→ 報酬分布，判斷策略是否顯著高於隨機 |
| B5 主動 ETF 平均 | 台股型主動 ETF 同期報酬（同時檢驗 Active Share 風險） |
| B6 Quant-only | 本系統關閉 LLM 元件 |
| B7 Full | Quant + LLM |

**判讀原則**：24 日樣本報酬的雜訊極大（單月個股報酬標準差 ~10%），單一視窗勝負不具統計意義 → 以多視窗 + 隨機 baseline 分布百分位評估；LLM 元件需在 W5 等無污染視窗上「比 quant-only 好或至少不更差」才保留。

## 9. 產出物

- `sim_runs/<run_id>/`：config、code_version、每日 D-Plan、settlement、validation report、LLM log、metrics.json、NAV 曲線圖。
- 比較報告：各 baseline 與版本之指標表。

## 10. 時程（建議，距開賽約 3 週）

| 週 | 內容 |
|---|---|
| 10/05–10/11 | Competition Engine + Simulator + golden tests；歷史資料下載（W1、W5） |
| 10/12–10/18 | Quant pipeline + baselines B0–B4 + D-Plan export/validator；W1/W5 quant-only 回測 |
| 10/19–10/23 | LLM 元件接入 + W5 測試 + 故障演練；ETF 策略說明文件由 Agent 產生（10/21 起繳交） |
| 10/24–10/25 | Dry run：以 live 資料實際跑 2 個早上（不提交或提交測試）、凍結 v1.0 code_version |
