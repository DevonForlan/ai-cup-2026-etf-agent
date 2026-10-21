# Factor Research / Quant Candidate v2 — Summary

> AI 產生內容，需人工審閱。研究用，不是正式文件或投資建議。`config/strategy_quant_v1.yaml`、production scheduler、DataPack integration、competition mode 均未修改；未 commit / upload / submit。

## 結論

**FACTOR_RESEARCH_STATUS = INSUFFICIENT_EVIDENCE → 建議維持 Quant v1（凍結）。不建立 `config/strategy_quant_candidate_v2.yaml`。**

- 預先定義的 13 項 gate（`research/factor_research/ACCEPTANCE_GATE.md`，結果前寫定、未修改）字面上有 3 個通過：`foreign_5`、`rev_3m_yoy`、`rev_3m_yoy+foreign_5`。
- 但純雜訊 placebo 因子（權重 0.2）在相同 OOS 窗平均也「改善」+0.70 pp（p95 +1.24 pp）；三者皆未超過 placebo p95，扣除 placebo 後的超額 +0.17～+0.39 pp，permutation p 0.50–0.69。
- 改善集中在 VALIDATION（2025-07～2026-01 多頭），DISCOVERY 幾乎為 0（組合為負）。OOS 只有 12 個 24 日窗 → INSUFFICIENT_STATISTICAL_POWER。
- 依使用者指示「沒有明確通過 gate 不要強迫產生 Candidate v2」：通過字面 gate 但無法與雜訊區分，不算明確通過。

## Quant v1 基準

IC5 +0.048（t 2.63；DISC +0.025 / VAL +0.097 / HOLD +0.037）。W1–W5 重現：+5.38% / −10.58% / +31.53% / −4.76% / +1.71%。OOS 12 窗隨機基準百分位中位 66.7。

## 全部因子

| 因子 | 家族 | PIT | IC5 | t | ΔIC DISC | ΔIC VAL | ΔIC HOLD | corr(v1) | OOS Δret（pp） | 分類 |
|---|---|---|---|---|---|---|---|---|---|---|
| rev_yoy | revenue | PIT_SAFE | +0.053 | 2.76 | +0.001 | +0.001 | +0.000 | +0.94 | - | V1_COMPONENT |
| rev_mom | revenue | PIT_SAFE | +0.009 | 1.11 | +0.006 | +0.003 | -0.001 | +0.57 | - | V1_COMPONENT |
| rev_yoy_accel | revenue | PIT_SAFE | +0.008 | 0.63 | +0.003 | -0.004 | +0.004 | +0.42 | +0.46 | SCREEN_PASS_GATE_FAIL |
| rev_mom_accel | revenue | PIT_SAFE | -0.006 | -0.55 | +0.005 | +0.001 | -0.000 | +0.31 | +0.76 | SCREEN_PASS_GATE_FAIL |
| rev_consec_yoy_pos | revenue | PIT_SAFE | +0.040 | 2.67 | +0.001 | +0.000 | +0.002 | +0.63 | +0.41 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| rev_yoy_slope6 | revenue | PIT_SAFE | +0.034 | 2.60 | -0.002 | +0.004 | +0.002 | +0.45 | +0.59 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| rev_yoy_stab6 | revenue | PIT_SAFE | -0.027 | -1.71 | +0.000 | -0.003 | +0.000 | -0.39 | +0.46 | SCREEN_PASS_GATE_FAIL |
| rev_3m_yoy | revenue | PIT_SAFE | +0.056 | 2.93 | +0.003 | +0.002 | +0.003 | +0.79 | +0.87 | GATE_PASS_NOT_DISTINGUISHABLE_FROM_PLACEBO |
| rev_ttm_yoy | revenue | PIT_SAFE | +0.034 | 1.80 | +0.002 | -0.004 | +0.003 | +0.58 | +0.19 | SCREEN_PASS_GATE_FAIL |
| rev_yoy_vs_trend | revenue | PIT_SAFE | +0.027 | 2.09 | -0.002 | +0.003 | -0.002 | +0.53 | +0.79 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| foreign_5 | institutional | PIT_SAFE | +0.043 | 3.87 | +0.009 | +0.012 | +0.004 | +0.06 | +0.98 | GATE_PASS_NOT_DISTINGUISHABLE_FROM_PLACEBO |
| foreign_20 | institutional | PIT_SAFE | +0.023 | 2.24 | +0.005 | +0.006 | -0.006 | +0.08 | +1.22 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| trust_5 | institutional | PIT_SAFE | -0.005 | -0.57 | +0.004 | -0.002 | -0.001 | +0.02 | +0.78 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| trust_20 | institutional | PIT_SAFE | +0.009 | 0.38 | +0.002 | +0.000 | -0.009 | +0.03 | +0.20 | SCREEN_PASS_GATE_FAIL |
| dealer_20 | institutional | PIT_SAFE | +0.009 | 0.58 | +0.005 | -0.005 | -0.001 | -0.04 | +0.24 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| inst_total_20 | institutional | PIT_SAFE | +0.026 | 1.98 | +0.004 | +0.004 | -0.001 | +0.08 | +0.67 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| foreign_accel | institutional | PIT_SAFE | +0.028 | 2.83 | +0.004 | +0.009 | +0.008 | +0.00 | +0.37 | SCREEN_PASS_GATE_FAIL |
| mom_20 | trend | PIT_SAFE | +0.027 | 0.80 | +0.002 | +0.005 | -0.001 | +0.16 | +0.23 | SCREEN_PASS_GATE_FAIL |
| mom_60 | trend | PIT_SAFE | +0.020 | 0.65 | -0.000 | -0.018 | +0.002 | +0.21 | +0.95 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| mom_60_skip5 | trend | PIT_SAFE | +0.021 | 0.74 | -0.001 | -0.017 | +0.002 | +0.20 | +1.20 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| reversal_5 | trend | PIT_SAFE | +0.003 | 0.29 | +0.004 | -0.010 | +0.001 | -0.07 | +0.56 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| dist_52w_high | trend | PIT_SAFE | +0.026 | 0.98 | +0.003 | +0.005 | +0.002 | +0.15 | -0.07 | SCREEN_PASS_GATE_FAIL |
| ma60_dist | trend | PIT_SAFE | +0.027 | 0.98 | -0.002 | +0.008 | -0.003 | +0.19 | -0.16 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| trend_consistency | trend | PIT_SAFE | +0.025 | 1.58 | +0.006 | +0.001 | -0.003 | +0.18 | -0.01 | SCREEN_PASS_GATE_FAIL |
| lowvol_20 | risk | PIT_SAFE | -0.047 | -1.73 | -0.001 | +0.017 | +0.002 | -0.28 | +0.74 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| low_downside_vol | risk | PIT_SAFE | -0.032 | -1.35 | -0.002 | +0.012 | +0.003 | -0.21 | +0.80 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| low_beta_60 | risk | PIT_SAFE | -0.052 | -1.84 | -0.002 | +0.020 | +0.004 | -0.29 | +0.59 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| low_idio_vol_60 | risk | PIT_SAFE | -0.035 | -1.34 | -0.003 | +0.017 | +0.001 | -0.29 | +0.65 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| low_mdd_60 | risk | PIT_SAFE | -0.017 | -0.79 | -0.001 | +0.003 | +0.002 | -0.10 | +0.51 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| size_value_20 | liquidity | PIT_SAFE | +0.026 | 1.04 | -0.003 | +0.006 | +0.003 | +0.31 | -0.00 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| illiquidity | liquidity | PIT_SAFE | +0.002 | 0.48 | +0.002 | +0.000 | -0.002 | -0.17 | +1.43 | SCREEN_PASS_GATE_FAIL |
| abnormal_volume | liquidity | PIT_SAFE | -0.007 | -0.46 | +0.002 | -0.006 | +0.006 | +0.03 | +0.38 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| earnings_yield | valuation | PIT_SAFE | -0.008 | -0.36 | +0.011 | -0.013 | -0.004 | -0.26 | -0.48 | SCREEN_PASS_GATE_FAIL |
| book_to_price | valuation | PIT_SAFE | -0.030 | -1.26 | +0.005 | -0.001 | -0.002 | -0.37 | +0.04 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| div_yield | valuation | PIT_SAFE | -0.018 | -0.83 | +0.009 | -0.020 | -0.001 | -0.30 | -0.57 | REJECTED_SCREEN (NO_INCREMENTAL_VALUE) |
| roe_proxy | quality | PIT_SAFE | +0.018 | 1.08 | +0.008 | -0.009 | -0.004 | +0.22 | -0.37 | SCREEN_PASS_GATE_FAIL |
| eps_ttm_growth | quality | PIT_SAFE | +0.035 | 2.19 | +0.004 | -0.000 | +0.002 | +0.37 | +0.22 | SCREEN_PASS_GATE_FAIL |
| mops_count_5 | event | PIT_CONDITIONAL | +0.014 | 0.32 | +0.001 | +0.000 | +0.000 | - | -0.04 | REJECTED_PIT |

未取得（NOT_AVAILABLE，見 FACTOR_DATA_AUDIT.md）：毛利率、營益率、季 ROE/ROA、現金流、負債比、融資融券、借券、處置/注意股、除權息事件全歷史等——無合法、PIT 可驗證的免登入歷史來源。

## Gate 候選明細（OOS 12 窗，官方成本）

| 策略 | OOS Δ | 95% CI | DISC/VAL/HOLD Δ | MDD 平均 (v1) | 最差窗 (v1) | post-day1 週轉 (v1) | 費稅 (v1) | Active Share 最小 | Sortino 中位 (v1) | CVaR95 1d (v1) | 隨機百分位 (v1) | 違規 | 敏感度 ×0.8–×1.2 | 成本壓力 ×1.5 / +20bp | 超 placebo |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F_foreign_5 | +0.98 | [+0.05, +1.78] | +0.02/+1.45/+0.52 | 7.39% (7.90%) | -20.78% (-21.64%) | 0.058 (0.054) | 1,511,036 (1,501,761) | 0.318 | 4.53 (3.78) | -3.48% (-3.64%) | 76.0 (66.7) | 0 | +0.72…+0.92 | +0.98 / +0.98 | +0.28 pp, p=0.586 |
| F_rev_3m_yoy | +0.87 | [+0.36, +1.45] | +0.06/+1.03/+0.72 | 7.75% (7.90%) | -21.24% (-21.64%) | 0.038 (0.054) | 1,444,956 (1,501,761) | 0.320 | 3.87 (3.78) | -3.62% (-3.64%) | 76.4 (66.7) | 0 | +0.76…+0.88 | +0.88 / +0.88 | +0.17 pp, p=0.693 |
| A_REV3M+FOREIGN5 | +0.96 | [+0.17, +1.73] | -0.30/+1.17/+0.75 | 7.77% (7.90%) | -20.93% (-21.64%) | 0.048 (0.054) | 1,479,039 (1,501,761) | 0.318 | 4.15 (3.78) | -3.62% (-3.64%) | 75.9 (66.7) | 0 | +0.70…+0.99 | +0.96 / +0.96 | +0.39 pp, p=0.5 |

## 特別檢查

- **rev_3m_yoy**：最強單因子 IC5（+0.056），但與 v1 分數相關 0.79（REDUNDANT）。字面 gate 通過；扣除 placebo 後 +0.17 pp，p=0.69。
- **foreign_5**：與 v1 低相關（0.06，互補），IC5 t 3.87，ΔIC 三期皆正。字面 gate 通過；扣除 placebo 後 +0.28 pp，p=0.59。最值得在比賽期間以影子（paper）方式持續觀察。
- **foreign_accel**：ΔIC 三期皆正，但組合 OOS +0.37 pp、HOLDOUT −0.36 pp → G1/G2 失敗。
- **dist_52w_high**：ΔIC 三期皆正，但組合 OOS −0.07 pp → G1 失敗、敏感度 FRAGILE。
- **估值**：earnings_yield（OOS −0.48 pp）、roe_proxy（−0.37 pp）、eps_ttm_growth（+0.22 pp，G1/G5 失敗）皆不通過；book_to_price、div_yield 未過 DISCOVERY 篩選。value 因子在此期間 IC 為負。另需新增 fetcher（G13 CONDITIONAL）。
- **illiquidity**：OOS +1.43 pp 且超過 placebo p95，但 G2（成本壓力資料未齊）與 G5（ΔIC HOLDOUT 為負）失敗，與 size 相關 −0.80，屬小型股暴露，不採用。
- **regime timing**：夜盤台指 / 美股隔夜報酬與次 5 日等權報酬正相關（0.16–0.27）——屬曝險 / 現金決策，不屬選股因子，本輪不納入。

## Multiple testing

- 38 個 IC 測試因子（36 候選 + 2 個 v1 成分）× 3 期 × 3 horizon。
- 1,948 次組合回測：83 個非基準、非 placebo 策略設定；15 個 placebo 設定；官方成本 1,756 次，cost ×1.25 / ×1.5 / +10bp / +20bp 各 48 次。
- 在 83 個設定中挑出最佳者，選擇偏誤可輕易產生 +1 pp / 窗量級的「改善」；placebo 對照已直接量化此效應。
- 只有 12 個 OOS 窗（且高度受同一行情驅動）→ **INSUFFICIENT_STATISTICAL_POWER**。

## 建議

1. 維持 Quant v1（Revenue YoY 0.70 / MoM 0.30）凍結，不建立 Candidate v2。
2. 比賽期間可在 daily paper 報告中以「影子」記錄 foreign_5 / rev_3m_yoy 的排序差異（僅研究，不影響下單），累積更多 OOS 窗後再評估。
3. 若未來重新評估，以 placebo p95 作為必要條件（建議寫入下一版 gate，需另行核准）。

## 報告索引

`research/factor_research/`：ACCEPTANCE_GATE.md、FACTOR_LITERATURE_REVIEW.md、FACTOR_DATA_AUDIT.md、FACTOR_IC_REPORT.md、FACTOR_ABLATION_REPORT.md、FACTOR_SENSITIVITY_REPORT.md、FACTOR_OOS_REPORT.md；原始結果 `research/factor_research/results/`。
