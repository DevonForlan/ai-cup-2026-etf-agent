# 待主辦方確認事項（NC list）— Round 07 重新整理（2026-10-05）

> 只有主辦方正式回覆才能關閉。Claude CLI 運作正常**不會**關閉任何 NC。
> 來源定義：`research/01_COMPETITION_RULES_EXTRACT.md` §12；程式 adapter：`agent/rules/organizer_clarifications.py`
> （無主辦方回覆設定檔 → 全部 unknown → 以保守假設執行）；設定：`config/unconfirmed_rules.yaml`。

| NC | 問題 | Round 07 狀態 | 目前做法（保守假設） | 阻擋 COMPETITION_READY |
|---|---|---|---|---|
| NC-1 結算 | 前日官方結算（持股 / 現金 / NAV）如何取得 | **OPEN** | `ManualFileSettlementProvider` + 雙重輸入 + 對帳；未來介面 `agent/submission/future_api.py` 只有骨架 | **是** |
| NC-1 提交 | 正式提交方式（平台 / API / 檔名 / 回執） | **OPEN** | prepare-only：產生 FINAL，人工上傳 + 記錄回執；不做瀏覽器自動化、不猜 API | **是** |
| NC-2 | Active Share 的 Wi 定義、Benchmark 資料日期 / 來源 | OPEN | 以發行商公開前 10 大持股計算，策略目標 30%（官方 20%），公式不改 | 否（以緩衝吸收） |
| NC-3 | C1–C14 各檢查碼為拒收或警告；拒收後可否重繳 | OPEN | 全部視為拒收：任何 FAIL → fallback；FAIL 仍在 → BLOCK | 否 |
| NC-9 | 比賽期間可否修 bug / 換 code_version | OPEN | 策略凍結；只有附證據 + 回歸測試 + 文件的營運 bug 修正 | 否 |
| NC-10 | 非 11/27 交易日是否以當日最後一次繳交為準 | OPEN | 每日只上傳一份 FINAL（凍結；換檔需 replace-final + 姓名 + 理由） | 否 |
| NC-15 | 主辦方的第一個比賽交易日 | **OPEN** | 見下方：TWSE 官方行事曆 10/26 休市，但主辦方未確認第一個交易日 | **是**（Day-1 時程） |

其他（NC-4 / 5 / 6 / 7 / 8 / 11 / 12 / 13 / 14、C12）維持 OPEN，做法不變（見 `config/unconfirmed_rules.yaml`）。

## NC-15 與官方市場行事曆（分開記錄）
- **official_market_calendar**（已確認的市場事實）：TWSE 2026 休市日（`config/trading_calendar_2026.yaml`，來源
  `https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&queryYear=115`，含 retrieved_at 與 sha256）：
  **2026-10-26（週一）休市**；2026-10-26 ～ 11-27 之間 TWSE 交易日共 **24 天**（10-27 ～ 11-27），與辦法「24 個交易日」及官方範例日期 2026-10-27 一致。
- **NC-15**（主辦方規則）：主辦方尚未正式說明第一個比賽交易日 → **仍 OPEN**。市場行事曆是證據，不等於主辦方確認。
- 準備：10-26（休市）與 10-27 兩種情境都可執行；第一天加 `--initial`。請向主辦方確認（建議附上 TWSE 行事曆連結）。

## 本輪關閉
- 無。（公司授權 Team 帳號、Claude CLI 比賽使用 = 公司內部授權事項，已記錄為 AUTHORIZED_FOR_COMPETITION_USE，不屬於 NC。）
