# Risk Overlay — Pre-registered Acceptance Gate

> 研究用。寫於 2026-10-16，在任何 overlay 組合回測執行**之前**。之後不修改；若必須修改，另立新版本並在報告中揭露。AI 產生內容，需人工審閱。
>
> 已知事前資訊（揭露）：上一輪 `research/factor_research/results/regime_timing.csv` 已看過各訊號與「次日 / 次 5 日 EW 報酬」的時間序列相關；本輪觸發門檻參考 Round 04 Crash Guard 預設值與常見文獻值，**不依該表調參**。

## 1. 範圍

- Baseline = Quant Core v1（`config/strategy_quant_v1.yaml`，FROZEN）。選股、權重、下單、NAV 計算完全不變。
- Overlay 只改變**組合曝險 / 現金**（以既有 Crash Guard 的等比例縮放程式 `_guard_scale` 執行，不換股），只在研究 worker 程序中注入；不進個股分數；不使用 LLM。
- 訊號全部 PIT：T 日 07:00 決策只用 `available_at ≤ T 07:00` 的資料（價量至 T−1 收盤；美股 / ADR / 夜盤 / 匯率依 available_at，且資料時間需在 96 小時內，過期視為缺值）。

## 2. 訊號（二元票，每日 PIT 計算）

| 票 | 條件 |
|---|---|
| v_breadth | 站上 MA20 比例 < 0.35 |
| v_trend | EW 指數 20 日報酬 < −5% |
| v_dd | EW 指數相對 60 日高點回撤 < −10% |
| v_vol | EW 指數 20 日年化波動 > 30% |
| v_sox | SOX 隔夜 ≤ −3% |
| v_ndx | NDX 隔夜 ≤ −2% |
| v_spx | S&P 500 隔夜 ≤ −1.5% |
| v_tsm | TSM ADR 隔夜 ≤ −3% |
| v_txf | 台指期夜盤 ≤ −1.5% |
| v_fx | USD/TWD 5 日變動 ≥ +1%（台幣貶值） |

「EW 指數」定義 = 與正式 pipeline `fs.market` 相同的 universe 每日**中位數**報酬累積指數（`agent/features/feature_engine.py`），以便逐值對帳（定義釐清，於任何回測前加入）。

## 3. 觸發規則（升級立即；降級需連續 2 日低於目前等級，一次一級）

| 觸發 | RISK_OFF 條件 |
|---|---|
| SLOW | (v_trend 且 v_breadth) 或 v_dd |
| FAST | v_txf 或 (v_sox 且 v_tsm) |
| VOL | v_vol 或 v_dd |
| VOTE | 票數 ≥ 3（共 10 票） |
| GRADED | 票數 ≥ 2 → CAUTION；≥ 4 → RISK_OFF |

## 4. 動作（全部軟性；官方現金 < 25% 永遠優先，現金 > 20% 時一律回補）

| 動作 | CAUTION | RISK_OFF | 每日去槓桿上限 | 其他 |
|---|---|---|---|---|
| A 提高現金 | 8–12% | 12–16% | 10% NAV | — |
| B 限制新增 | 不降曝險 | 不降曝險 | — | 暫停新增持股 |
| C 部分降曝險 | 10–14% | 15–19% | 15% NAV | 高波動（前 20%）個股權重上限 6% |

回到 NORMAL 後：現金高於 v1 區間上緣 + 2% 時，以每日 10% NAV 上限回補到 v1 區間；其餘日子與 v1 完全相同（不觸發時結果應與 v1 逐位相同）。

## 5. 候選（8 個，事前固定）

A_SLOW、A_FAST、A_VOL、A_VOTE、B_VOTE、C_FAST、C_VOTE、D_GRADED（GRADED 觸發；CAUTION 用 A 的 8–12%，RISK_OFF 用 C 的 15–19% / 15% / 6%）。

## 6. 期間與窗型

- 與上一輪相同的 23 個連續 24 交易日窗：DISCOVERY 11、VALIDATION 6、HOLDOUT 6；OOS = VALIDATION + HOLDOUT（12 窗）。
- 窗型（只用 EW 指數，與策略無關）：**CRASH** = 窗內 EW 報酬 ≤ −5% 或 EW 窗內最大回撤 ≥ 8%；**BULL** = 非 CRASH 且 EW 報酬 ≥ +5%；其餘 **SIDEWAYS**。
- **主要候選**：只用 DISCOVERY 選出——DISCOVERY 平均 ΔMDD 最負、且 DISCOVERY 平均 Δret ≥ −0.50 pp 者。其餘候選照常報告，但不能因 OOS 結果改選。

## 7. Gate（OOS 12 窗、官方成本、與 v1 同窗 paired；全部需通過）

| # | 條件 |
|---|---|
| R1 MDD | OOS 平均 ΔMDD ≤ −0.50 pp，且 bootstrap 95% CI 上界 < 0 |
| R2 尾部 | OOS 平均 Δworst_1d ≥ 0 且 平均 Δworst_5d > 0（較不負） |
| R3 Crash | OOS CRASH 窗 ≥ 2 個，且其平均 Δret ≥ 0、平均 ΔMDD < 0；OOS CRASH 窗 < 2 → 本項無法判定（→ 不可能 CANDIDATE_FOUND） |
| R4 Bull | OOS BULL 窗平均 Δret ≥ −0.50 pp |
| R5 Net return | OOS 平均 Δret ≥ −0.30 pp，且 bootstrap 95% CI 下界 ≥ −1.00 pp |
| R6 週轉 / 成本 | post-day1 週轉 ≤ v1 + 0.30 NAV / 窗；費稅 ≤ v1 × 1.5；成本 ×1.5 與 +20 bp 下 R5 平均條件仍成立 |
| R7 合規 | 違規 0、驗證失敗 0、fallback 0、任何日結算現金 < 22% |
| R8 Active Share | 每窗最小 Active Share ≥ 0.20（官方 15–20% 以上，含緩衝），無違規日 |
| R9 PIT | 所有使用的訊號為 PIT_SAFE（見 RISK_OVERLAY_DATA_AUDIT） |
| R10 Placebo | 同結構 placebo：把候選的每日狀態序列在 2024-07～2026-10 交易日曆上循環平移（保留觸發天數與連續長度），20 個固定種子位移（偏移 ≥ 20 日）。候選 OOS 平均 ΔMDD 必須**低於** placebo 分佈的第 5 百分位（即優於 95% placebo），且 OOS 平均 Δworst_5d 高於 placebo 中位數 |

- R10 只需對「R1–R9 全通過」者與主要候選執行；其他候選若算得起也執行並報告。
- 結論規則：
  - **CANDIDATE_FOUND**：至少一個候選 R1–R10 全通過 → 才建立 `config/strategy_risk_overlay_candidate.yaml`（仍只是 candidate）。
  - **KEEP_BASELINE**：證據顯示 overlay 傷害報酬或沒有改善尾部（例如 R1 / R2 方向相反、或 R5 明顯失敗）。
  - **INSUFFICIENT_EVIDENCE**：方向有改善但未過 R1/R3/R10 的統計門檻，或 OOS CRASH 窗不足。

## 8. Multiple testing

記錄：訊號數、觸發數、動作數、候選數、placebo 次數、總回測次數。OOS 12 窗；CRASH 窗數量預期很少 → 預期統計檢定力不足時，報告必須寫明 INSUFFICIENT_STATISTICAL_POWER。

## 9. Amendment 1（2026-10-16，任何 DISCOVERY / OOS 結果產生前；僅以 R08 一窗做機制測試）

1. **執行方式**：既有 `_guard_scale` 對所有持股等比例縮放，但凍結的下單規劃器會忽略單檔 < 0.2% NAV 的變動，導致 1–4% NAV 的去槓桿完全沒有下單（機制測試中 RISK_OFF 14 天 0 筆委託）。改為研究端執行：同樣的現金目標與每日上限，但把交易**集中在權重最大的持股**（每檔約 ≥ 0.25% NAV），再交給既有 `_finalize` 做官方檢查、Active Share 與壓力測試。不換股。
2. **現金區間只增不減**：overlay 現金區間 = [max(overlay 下限, v1 當日下限), max(overlay 上限, v1 當日上限)]，上限再截在 19%。避免 v1 自身的 breadth regime 已持較多現金時，overlay 反而降低現金。
3. 其餘（訊號、門檻、候選、gate R1–R10）不變。
