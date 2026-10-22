# Shadow Metrics — foreign_5 / rev_3m_yoy（research-only）

> AI 產生內容，需人工審閱。研究用；`config/strategy_quant_v1.yaml`、production scheduler、competition_day、DataPack integration、正式 prediction logic 均未修改；未 commit。

工具：`research/risk_overlay/shadow_metrics.py`（手動執行；不被任何 production 腳本呼叫）。每個交易日 T：v1 分數 vs v1 + 0.2 × 候選，記錄排名差、top-25 變動、次日（VWAP T → 收盤 T）與 5 日（VWAP T → 收盤 T+4）報酬差。**不影響**正式 D-Plan、BUY / SELL、Quant v1、paper ledger、scheduler。

輸出：`research/risk_overlay/results/shadow_log.csv`、`reports/shadow_metrics/shadow_YYYY-MM-DD.json`。

## 回填 2026-09-01～2026-10-15（30 個交易日；5 日報酬可得 26 日）

| 指標 | foreign_5 | rev_3m_yoy |
|---|---|---|
| 分數 Spearman vs v1（平均） | 0.973 | 0.994 |
| top-25 重疊（平均） | 21.2 | 24.7 |
| 次日報酬差（平均，pp） | +0.02 | +0.01 |
| 5 日報酬差（平均，pp） | +0.33 | -0.01 |
| 5 日報酬差 > 0 的天數 | 20/26 | 2/26 |

5 日報酬重疊（相鄰日共用 4 天），樣本極小，僅供累積紀錄，不能作為決策依據。rev_3m_yoy 幾乎不改變 top 25（與 v1 高度重疊）。

建議用法：每天 17:00 評估後手動執行 `--from <當日>`。若要排入排程，需另行核准（本輪未修改任何 scheduler）。
