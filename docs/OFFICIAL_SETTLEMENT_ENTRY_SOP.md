# 官方結算人工輸入 SOP（Official Settlement Entry）

> AI 產生內容，需人工審閱。NC-1（官方結算取得方式）未確認：目前假設主辦方只提供 Web 後台。
> **禁止**：瀏覽器自動化、OCR 自動化、自動登入、爬取後台。只允許「人看畫面 → 人填檔案 → 程式驗證」。
> 官方結算只能設定「下一個交易日的起始持股 / 現金 / NAV」，**不能**改任何策略參數。

## 時機
交易日 T 收盤、主辦方公布 T 的結算後（預期 T 傍晚），**在 T+1 的一鍵流程之前**完成。
competition 模式下，T 的官方結算沒有「已確認」紀錄 → preflight `settlement_confirmed` = BLOCK，系統不會產生 T+1 的 D-Plan。

## 步驟

| # | 動作 | 指令 / 產物 |
|---|---|---|
| 1 | **看官方庫存**：登入官方後台（人工），開「庫存明細 / 淨值」頁。截圖存 `data\settlement\evidence\YYYYMMDD_HHMM.png`（不要截到帳密） | 截圖 |
| 2 | **填 CSV（A）**：複製範本 `templates\settlement_official_template.csv` → `data\settlement\entry\YYYYMMDD_official_A.csv`，逐列填 `ticker,shares`（股數，不是張數），最後填 `__DATE__`、`__CASH__`、`__NAV__`、`__ACCRUED__`、`__WARNINGS__`（以 `;` 分隔，無則留空） | official_A.csv |
| 3 | **第二人（或隔 10 分鐘後同一人）獨立再填一次（B）**，不要複製 A | official_B.csv |
| 4 | **SHA256**（可選，系統也會記錄）：`certutil -hashfile data\settlement\entry\YYYYMMDD_official_A.csv SHA256` | 雜湊 |
| 5 | **匯入 + 雙重輸入比對**（先不加 `--confirm`）：<br>`.venv\Scripts\python.exe agent\ops\settlement_entry.py --date YYYY-MM-DD --file ...A.csv --verify-file ...B.csv --operator "姓名" --source "官方後台 庫存明細 YYYY-MM-DD HH:MM" --snapshot-ref "evidence\YYYYMMDD_HHMM.png"` | `DOUBLE_ENTRY_MATCH` 或 BLOCK（列出差異） |
| 6 | **對帳**：`.venv\Scripts\python.exe agent\ops\reconcile.py --date YYYY-MM-DD` | MATCH / MINOR_DIFFERENCE / BLOCK |
| 7 | **確認**：對帳 MATCH（或 MINOR 且已看過差異）→ 再執行步驟 5 並加 `--confirm --supersede-reason "confirm after reconcile"` | `YYYYMMDD_confirmation.json`（confirmed=true） |
| 8 | **才允許下一交易日跑**：`scripts\preflight.ps1 -Mode competition -Date <T+1>` 應顯示 `settlement_confirmed PASS` | preflight |

## 系統檢查（任一失敗 = BLOCK，不寫入任何檔案）
日期格式與週末、檔內 `__DATE__` 與 `--date` 一致、ticker 格式、是否在 150 檔清單、重複 ticker、股數為整數且 ≥ 0、現金 ≥ 0、NAV > 0、
`NAV = Σ 股數 × 當日收盤 + 現金`（誤差 ≤ `config/ops.yaml settlement_entry.nav_tolerance_rel`，store 有當日收盤時才檢查）、
雙重輸入不一致、操作者 / 來源未填、同日官方檔已存在（需 `--supersede-reason`，舊檔保留為 `_superseded_<時間>.json`）。
警告（不阻擋）：股數非 1000 倍數（配股零股，NC-7）、全現金。

## 確認紀錄 `data\settlement\YYYYMMDD_confirmation.json`
`entered_at`、`source`、`operator`、`input_file` / `input_file_sha256`、`verify_file_sha256`、`double_entry`、
`official_snapshot_reference`、`notes`、`official_json_sha256`、`confirmed`、`confirmed_at`。
官方 JSON 在確認後被修改 → `confirmed` 視為失效（hash 不符），competition 模式 BLOCK。

## 對帳 BLOCK 時
見 `docs/EMERGENCY_RUNBOOK.md` §B：系統不選邊；人工判斷後以 `reconcile.py --accept-official --confirmed-by` 明確採用官方帳。

## 狀態查詢
`.venv\Scripts\python.exe agent\ops\settlement_entry.py --status --date YYYY-MM-DD`
