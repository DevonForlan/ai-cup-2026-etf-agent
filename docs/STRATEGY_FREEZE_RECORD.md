# 策略凍結紀錄（Strategy Freeze Record）

> AI 產生內容，需人工審閱。比賽期間任何會影響決策的變更都必須在此留下紀錄。

## 凍結版本

| 項目 | 值 |
|---|---|
| 策略設定檔 | `config/strategy_quant_v1.yaml` |
| sha256 | `f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0` |
| 凍結 commit | `f4dfb66`（2026-10-05 07:42 +08:00，Round 03） |
| 內容摘要 | HN_rev：revenue_yoy 0.7 + revenue_mom 0.3；第 1 天買進後持有；只做合規性調整；Template 敘事；無 LLM 訊號；Crash Guard 關閉 |
| 自動檢查 | `config/ops.yaml` `freeze.strategy_sha256`；preflight `strategy_freeze`、healthcheck `strategy`（competition 模式不符 → BLOCK） |

設定檔自凍結後**未修改**（`git log -- config/strategy_quant_v1.yaml` 只有 `f4dfb66`）。

## 凍結後的程式變更（影響決策路徑者）

| 日期 | commit | 類型 | 內容 | 對歷史回測的影響 | regression test |
|---|---|---|---|---|---|
| 2026-10-05 | `94216a2` | bug fix（Round 04） | Active Share 加總順序固定（set 順序造成非決定性） | v1 W5 NAV 與 Round 03 相同 | Round 04 tests |
| 2026-10-05 | `bfbe688`、`db2bf15`、`d30e1ac`、`ec4d0fb` | 新功能（預設關閉）/ fix | bounded fusion、Crash Guard 及其現金漂移修正、事件快取；v1 設定未啟用 | v1 無影響（W5 重現） | Round 04 tests |
| 2026-10-05 | `29db140` | 營運 | `run_day(as_of_override=…)`：營運時以實際時鐘為 PIT 截止；未設定時行為不變 | 回測不變 | tests/ops |
| 2026-10-05 | `d6a45ca` | bug fix（Round 05） | 前日組合因現金漂移 >25% 而不合法時，完整再平衡不再被「不交易區間」卡住；NO_TRADE 標的宣告目前權重（不再宣告 water-fill 目標造成假的 R_CASH_NEG） | W1–W5 逐位元相同（此路徑只在持有不合法時觸發） | `tests/portfolio/test_cash_drift_r05.py`（舊程式 3 項失敗） |
| 2026-10-05 | Round 06（`7af2bd7`…） | 營運 | 無決策路徑修改（`agent/portfolio`、`agent/features`、`agent/engine`、`agent/risk` 未變）；營運層：FINAL 凍結、結算輸入、資料新鮮度（休市感知）、ETF 重試 | W5 replay rehearsal 24 日 NAV 逐日 = baseline | tests/ops/test_round06*.py |

`code_version` 隨每個 commit 更新（`git:<sha>`），寫入每份 D-Plan `agent_metadata.code_version` 與 `run_metadata.json`。

## 營運層（不影響選股/權重）
Round 05 新增 `agent/ops/*`、`agent/competition_day.py`、`config/ops.yaml`、`scripts/*.ps1`：資料更新、對帳、preflight、打包、封存、截止保護。
其中會改變「是否產生 D-Plan」的只有 BLOCK 規則；不會改變 D-Plan 內容。

## 變更規則（比賽期間）
1. 只允許 bug fix（NC-9：比賽中修正是否允許尚未確認）；**不得**因績效調參。
2. 每個 fix：獨立 commit、regression test、在此表新增一列、重跑 W5 baseline 並記錄 NAV 是否相同。
3. 若必須改 `strategy_quant_v1.yaml`：同步更新 `config/ops.yaml` `freeze.strategy_sha256` 與本表，說明原因。
