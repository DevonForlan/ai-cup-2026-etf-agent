# Official DataPack Integration（官方資料包介接）

> AI 產生內容，需人工審閱。依據：`research/official_updates/DataPack_規格書_v4.3.md`（官網 2026-10-12）。
> **Official portal auto-download: PENDING_REAL_DATAPACK_AVAILABILITY**（目前不登入、不下載、不猜 URL / API、不讀 cookie）。

## 1. DataPack purpose
主辦方系統在每個交易日結算後產生的 JSON：本隊 `as_of_date`（前一交易日）收盤結算後的 `account`（cash、nav_tradable、
receivable_cash…）、`holdings`（code、shares、receivable_shares、close_price）、`prev_day_orders`（executed / voided…）與
`compliance`。正式比賽中，下一交易日的 Agent **以 DataPack 為持股 / 現金 / NAV 的唯一依據**（D-Plan v4.3 `target_weight`
分母 = `account.nav_tradable`；委託推導用資料包前日持股與淨值）。

## 2. Precompetition behavior（目前）
- `config/ops.yaml run_mode: PRECOMPETITION`；19:30 排程：`datapack_status = NOT_REQUIRED`。
- 起點：paper ledger（`data/paper_ledger/`）→ `settlement_source = PRECOMPETITION_PAPER_LEDGER`；沒有前日 paper 結算 →
  `INITIAL_CAPITAL`。DataPack 不存在是正常情況，不 BLOCK。所有結果標示 `PRECOMPETITION_PAPER_RUN`。

## 3. Competition behavior（已實作並測試，尚未啟用）
```
Expected previous trading day（config/trading_calendar_2026.yaml，非日曆日 - 1）
→ Locate latest official DataPack（ManualFileProvider：data/official_datapack/*.json，本隊、該交易日、最新 generated_at）
→ Validate（validate_official_datapack）
→ Freshness（as_of_date = 預期前一交易日）
→ Settlement state（匯入既有官方結算檔 data/settlement/<as_of>_official.json + confirmation；與內部帳對帳）
→ Agent / Quant → Orders → D-Plan
```
- 缺檔 → `BLOCKED / DATAPACK_MISSING`；日期不對或結算尚未產生 → `BLOCKED / DATAPACK_STALE`；格式 / 數值錯誤 → `BLOCKED / DATAPACK_INVALID`。
- **禁止 fallback**：不得改用 paper ledger、內部結算、估計持股、前一次 prediction 或重建組合。`competition_day` 在 competition
  模式下即使有內部結算，沒有 DataPack 也不會用它當起點（`REFUSED: internal settlement without official DataPack`）。
- 第一個交易日（`first_trade_date` 2026-10-27）：`--initial`（初始資金由辦法規定）。若當天已有資料包（`as_of_date` null、全現金），
  也會驗證；之後任何一天 `--initial` 都不能繞過 DataPack。
- 中繼資料：`competition_day_summary.json` 與 package `run_metadata.json` 的 `settlement_source`
  （`OFFICIAL_DATAPACK` / `PRECOMPETITION_PAPER_LEDGER` / `INITIAL_CAPITAL`）、`settlement_date`、`datapack_file`、
  `datapack_schema_version`、`datapack_validation`、`datapack_freshness`（賽前可為 null）。

## 4. Folder path
| 用途 | 路徑 |
|---|---|
| 正式 DataPack（只放主辦方檔案） | `data\official_datapack\`（`config/ops.yaml paths.official_datapack_dir`；`*.json` 不進 git） |
| 測試 fixture（官方範例 + synthetic 錯誤檔） | `tests\fixtures\datapack\` |
| 匯入後的官方結算 / 原檔副本 | `data\settlement\<日期>_official.json`、`data\settlement\datapack\` |
synthetic / mock / paper ledger / 測試檔**不得**放進 `data\official_datapack\`（測試會檢查）。

## 5. Validation（`agent/ops/datapack.py validate_official_datapack`）
JSON 可讀；`doc_type = DataPack`；`schema_version` 在 `config/competition.yaml datapack.supported_schema_versions`
（規格書範例為 "3.0"、規格書版本 4.3）；team_id / trade_date 相符；`as_of_date` 存在且 = 預期前一交易日（null 只允許第一個交易日）；
`missing` 含 `prev_settlement`（account / holdings 為 null）→ STALE，**null 不當空手**；nav_tradable 數值 > 0；cash 數值 ≥ 0；
holdings 為陣列、代號格式、shares / receivable_shares 為非負整數、重複代號；`holdings_count` 一致；
NAV 恆等式 `nav_tradable = cash + Σ shares × close_price`（容差 1 元）。`prev_day_orders.outcome = voided`、
`compliance.violations` 以 warning 呈現（結算本身仍是官方事實）。只檢查規格書實際存在的欄位。

## 6. Freshness gate
`DATAPACK_FRESHNESS_GATE`：產生 T 的 D-Plan → 要求 DataPack `as_of_date = previous_trading_day(T)`（官方 TWSE 行事曆）。
例：T = 2026-10-28 → 2026-10-27；T = 2026-10-27 → 第一個交易日（10-26 休市）；T = 2026-10-12 → 2026-10-08（10-09 休市）。

## 7. Failure handling
| 情況 | 狀態 | 操作 |
|---|---|---|
| 找不到 | BLOCKED / DATAPACK_MISSING | 登入後台「文件繳交」→「下載資料包」，存入 `data\official_datapack\`，重跑 |
| 結算尚未產生（`missing: prev_settlement`）/ 日期過舊 | BLOCKED / DATAPACK_STALE | 稍後重新下載（官方 19:00 後更新） |
| 解析 / 數值錯誤 | BLOCKED / DATAPACK_INVALID | 重新下載；仍失敗 → 聯絡主辦方（不手動改檔） |
| 前日委託作廢 / 違規 | WARN（照常使用結算） | 依 `void_reasons` / incidents 檢查 |
查詢：`.venv\Scripts\python.exe -m agent.ops.datapack_status`（`--mode COMPETITION --trade-date 2026-10-28` 可模擬正式日）。

## 8. Current downloader status（`agent/ops/datapack_downloader.py`）
| Provider | 狀態 |
|---|---|
| `ManualFileProvider` | **ENABLED** — 只掃描 `data\official_datapack\`，不要求人工輸入持股 / 現金 / NAV |
| `OfficialPortalProvider` | **DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION** — 呼叫只回 `DOWNLOAD_NOT_CONFIGURED`；不登入、不猜 URL / API、不用 cookie |

## 9. Future portal automation procedure（真實 DataPack 出現後；本輪不做 D3 / D4）
| Phase | 內容 |
|---|---|
| D1 | 第一份真實 DataPack 出現後，操作者手動下載一份 |
| D2 | 驗證 file name、內容、schema、日期、後台行為（`datapack_status`、`validate_official_datapack`） |
| D3 | 向主辦方確認官方 portal 是否允許合法程式化下載（書面） |
| D4 | 獲准後才實作 `OfficialPortalProvider`（只用官方文件化方式；不 reverse engineer、不繞過 CSRF） |
| D5 | end-to-end：portal → download → validation → settlement state → Agent → D-Plan |
