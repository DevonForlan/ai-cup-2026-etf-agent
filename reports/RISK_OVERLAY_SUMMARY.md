# Risk Overlay Research — Summary

> AI 產生內容，需人工審閱。研究用，不是正式文件或投資建議。`config/strategy_quant_v1.yaml`、production scheduler、competition_day、DataPack integration、正式 prediction logic、competition mode 均未修改；未 commit / upload / submit。

## 結論

**RISK_OVERLAY_STATUS = KEEP_BASELINE**。不建立 `config/strategy_risk_overlay_candidate.yaml`。

- 8 個事前固定的 rule-based overlay 全部未通過預先登錄的 gate（`research/risk_overlay/ACCEPTANCE_GATE.md`）。
- OOS（12 窗）平均報酬**全部低於** Quant v1：−0.06～−0.47 pp / 窗。
- 平均 MDD 只降 0.2～0.5 pp，未達「≥ 0.5 pp 且 CI 上界 < 0」。
- 同結構 placebo（同樣的去槓桿，但時點隨機平移）本身就讓 MDD 降約 0.33 pp。真實訊號只多降約 0.12 pp。
- 07:00 可見的隔夜急跌訊號，在 VWAP 成交前已大多反映在開盤跳空；之後 5 日平均反而反彈。

## 設計

- Baseline：Quant Core v1（Revenue YoY 0.70 / MoM 0.30），選股不變。
- Overlay 只改變現金 / 曝險：在研究 worker 中把交易集中於最大持股，再交給凍結的 `_finalize` 做官方檢查。不換股、不使用 LLM。
- 10 個 PIT 訊號票：breadth、EW trend 20D、EW drawdown 60D、EW vol 20D、SOX、NDX、S&P 500、TSM ADR、台指夜盤、USD/TWD 5D。
- 5 種觸發：SLOW / FAST / VOL / VOTE / GRADED。
- 4 種動作：A 提高現金 12–16%；B 暫停新增；C 降曝險 15–19% + 高波動上限；D 分級。
- 共 8 個候選；23 窗（DISCOVERY 11 / VALIDATION 6 / HOLDOUT 6）。

## 主要數字（OOS 12 窗，官方成本）

| 策略 | 平均報酬 | 平均 MDD | 最差 1D | 最差 5D | CVaR95 | 週轉（day1 後） | 費稅/窗 | Gate |
|---|---|---|---|---|---|---|---|---|
| Quant v1 | 9.04% | 7.90% | −6.91% | −12.47% | −3.64% | 0.054 | 1.50M | baseline |
| A_SLOW | 8.90% | 7.64% | −6.35% | −11.48% | −3.52% | 0.114 | 1.68M | FAIL（R1 R4） |
| A_FAST | 8.76% | 7.61% | −6.88% | −12.24% | −3.48% | 0.196 | 1.93M | FAIL（R1 R3） |
| A_VOL | 8.81% | 7.59% | −6.38% | −11.50% | −3.53% | 0.091 | 1.60M | FAIL（R1 R4） |
| A_VOTE | 8.65% | 7.67% | −6.37% | −11.47% | −3.50% | 0.177 | 1.85M | FAIL（R1 R3 R4 R5 R6） |
| B_VOTE | 8.98% | 7.92% | −6.91% | −12.47% | −3.65% | 0.059 | 1.52M | FAIL（R1 R2 R3） |
| C_FAST（primary） | 8.66% | 7.43% | −6.82% | −11.94% | −3.41% | 0.253 | 2.08M | FAIL（R1 R3 R4 R5 R6 R7） |
| C_VOTE | 8.57% | 7.56% | −6.32% | −11.36% | −3.45% | 0.234 | 2.01M | FAIL（R1 R3 R4 R5 R6 R7） |
| D_GRADED | 8.75% | 7.42% | −6.34% | −11.41% | −3.42% | 0.152 | 1.78M | FAIL（R1 R3 R4 R6） |

- 合規：違規 0、驗證失敗 0、fallback 0。C 動作在急跌中被動漂移到 22.2% 現金，越過研究緩衝 22%；官方上限 25% 未違規。
- Active Share：最低 0.29（≥ 0.20）。
- 成本壓力：cost ×1.5 與 +20 bp 下，Δ 報酬幾乎不變。

完整數字見 `research/risk_overlay/RISK_OVERLAY_OOS_REPORT.md`。

## 10/15 案例

- 10/14 07:00 與紙上流程實際產生時間（10/14 21:26）都**沒有**任何 risk-off 訊號。
- 只有在 10/15 07:00 才可見 SOX −4.3%、TSM −3.4%、夜盤 −1.75%。
- 即使當天早上依 overlay 賣出 7–10% NAV，也只少虧約 0.04–0.06% NAV（−5.65% → −5.59%）。
- 原因：當日 −5.65% 中有 −4.76% 是開盤跳空。

詳見 `research/risk_overlay/CASE_STUDY_2026-10-15.md`。

## Shadow metrics

`research/risk_overlay/shadow_metrics.py` 記錄 foreign_5 / rev_3m_yoy 的排名差、top-25 變動、次日 / 5 日報酬差。

- 已回填 2026-09-01～10-15，共 30 日。
- 純研究，不影響 D-Plan、BUY / SELL、Quant v1。
- 未排入任何 scheduler。

## Multiple testing

| 項目 | 數量 |
|---|---|
| 訊號票 | 10 |
| 觸發規則 | 5 |
| 動作 | 4 |
| 候選 | 8 |
| placebo | 2 組 × 20 次位移 |
| 主回測 | 207 筆（169 筆實際模擬；38 筆 overlay 未啟動，與 v1 逐位相同） |
| 成本壓力 | 216 筆 |
| placebo 回測 | 480 筆 |
| 機制測試 | 3 筆（R08，Discovery） |

- OOS 只有 12 窗、4 個 crash 窗，統計檢定力不足。
- 即使如此，方向一致：所有 overlay 都降低報酬。

## 建議

1. 正式比賽維持 Quant v1 原本曝險（含其既有 breadth regime 現金政策），不加 overlay。
2. 不再為 risk overlay 調參。可交易的訊號必須在前一晚 19:30 之前可見；07:00 之後才可見的訊號大多已反映在開盤價。
3. 若要繼續研究風險，方向應改為**事前**曝險：例如前一晚已知的高波動 / 事件日。這需要新的 gate 與核准。

## 報告

`research/risk_overlay/`：

- ACCEPTANCE_GATE.md
- RISK_OVERLAY_DATA_AUDIT.md
- RISK_OVERLAY_SIGNAL_REPORT.md
- RISK_OVERLAY_OOS_REPORT.md
- CASE_STUDY_2026-10-15.md
- SHADOW_METRICS.md
- results/
