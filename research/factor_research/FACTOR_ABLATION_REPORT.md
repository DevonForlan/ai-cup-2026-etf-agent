# Factor Ablation Report

> AI 產生內容，需人工審閱。研究用；Quant v1（`config/strategy_quant_v1.yaml`）未修改。主要統計皆為官方成本、與 Quant v1 同窗 paired 比較。

Gate 計算性條件（G1/G3/G4/G5/G7–G11）只剩 `rev_3m_yoy`（營收）與 `foreign_5`（外資）兩個候選，故只做必要 ablation：
Revenue only（= Quant v1）／ v1 + rev_3m_yoy ／ v1 + foreign_5 ／ v1 + 兩者（各 0.2）。原計畫的家族組合（REV / INST / TREND / LIQ 共 9 組）因其成員已在計算性條件失敗、結果不可能改變 gate 結論而未執行（未修改 gate）。

| 策略 | DISC Δ | VAL Δ | HOLD Δ | OOS Δ 平均 | OOS Δ 中位 | OOS 95% CI | OOS 勝率 | 超出 placebo（pp）| permutation p |
|---|---|---|---|---|---|---|---|---|---|
| Revenue only（Quant v1） | 0 | 0 | 0 | 0 | 0 | - | - | - | - |
| v1 + rev_3m_yoy | +0.06 | +1.03 | +0.72 | +0.87 | +0.42 | [+0.36, +1.45] | 83% | +0.17 [-0.67, +0.98] | 0.693 |
| v1 + foreign_5 | +0.02 | +1.45 | +0.52 | +0.98 | +1.05 | [+0.05, +1.78] | 83% | +0.28 [-0.63, +1.26] | 0.586 |
| v1 + rev_3m_yoy + foreign_5 | -0.30 | +1.17 | +0.75 | +0.96 | +0.65 | [+0.17, +1.73] | 75% | +0.39 [-0.56, +1.45] | 0.5 |

Δ 單位：每窗報酬百分點（pp）。超出 placebo = 候選 Δ − 同窗 placebo 平均 Δ（單因子對 10 個單一雜訊因子；組合對 5 個雙雜訊因子）。

**結論**：兩因子組合不比各自單獨更好（OOS +0.96 pp vs +0.98 / +0.87 pp），在 DISCOVERY 反而為 −0.30 pp（11 窗僅 1 窗勝出）。所有改善只出現在 VALIDATION / HOLDOUT，而純雜訊因子在同期也有 +0.6～+0.7 pp。扣除雜訊後，三者都不顯著（p 0.50–0.69）。改善無法歸因於任何特定因子。
