# Official Test E2E Runbook（官方封測端到端流程）

> 封測期間使用。測試資料會在正式比賽前被主辦方清除。Agent 只產生、驗證、記錄；**登入、上傳、送出、下載全部人工**。Quant v1 凍結，不因封測結果調整。AI 產生內容，需人工審閱。

## 1. 流程

| Step | 誰 | 動作 | 指令 / 位置 | 通過條件 |
|---|---|---|---|---|
| 1 | Agent | 產生 test D-Plan（19:30 排程或 08:30 前 catch-up） | `submissions\<T>\FINAL\` | FINAL 存在 |
| 2 | Agent | 本機驗證：schema / ticker / numeric / compliance / Active Share | `validation_report.json`；package 的 `local_checks` | 全部 PASS；Active Share ≥ 15%（目標 30%） |
| 3 | Agent | READY_FOR_UPLOAD + TEST_SUBMISSION_PACKAGE | `python -m agent.submission.official_test package --date T` → `reports\official_test\<T>\TEST_SUBMISSION_PACKAGE.md` | status = `READY_FOR_MANUAL_TEST_UPLOAD`（Team ID 已設定且與檔內一致；否則 `BLOCKED_TEAM_ID_NOT_CONFIGURED`，**不上傳**） |
| 4 | 人工 | 登入 esun-ai-challenge.tw → 我的活動 → 進入活動 → 競賽活動後台 | （可在 URL 設定後用 `python -m agent.submission.portal --open` 只開頁面） | 看到上傳頁 |
| 5 | 人工 | 上傳 package 指定的那一個檔案；先核對 sha256 | `certutil -hashfile <檔> SHA256` | sha256 一致 |
| 6 | 人工 | 逐字抄錄官方回應、截圖 | `data\official_test_receipts\<T>\` | — |
| 7 | 人工 | 記錄結果 | `python -m agent.submission.official_test record-upload --date T --sha256 ... --result accepted/rejected/pending/unknown/ui_unavailable --message "<原文>" [--submission-id X] [--official-confirmation] --evidence <截圖> --operator "姓名"` | `sha256_matches_package = true` |
| 8 | Agent | 映射內部狀態（§3）。**只有官方證據足夠才是 ACCEPTED** | records.jsonl 的 `mapped_internal_state` | — |
| 9 | 官方 | 交易日結算 | — | — |
| 10 | 人工 | 下載 DataPack | 後台「下載資料包」 | — |
| 11 | Agent | 封存 + 欄位盤點 + 唯讀驗證（**不匯入比賽鏈**） | `python -m agent.submission.official_test datapack --file <檔> --date <T+1> --team-id X` → `data\official_test_datapack\<T+1>\` | validation PASS 或已理解的 STALE |
| 12 | Agent / 人工 | 核對官方 holdings / cash / NAV / trade date / 執行結果（`prev_day_orders`）/ 合規 vs 上傳的 D-Plan | inventory JSON + D-Plan orders | 差異都有官方原因（作廢、無價等） |
| 13 | Agent | 下一交易日起點必須是官方 DataPack | COMPETITION 模式：DataPack gate（`DATAPACK_MISSING` / `STALE` / `INVALID` → BLOCKED；不 fallback） | 封測期間 run_mode 仍是 PRECOMPETITION：只做步驟 11 的驗證，不切換 |

正式比賽（COMPETITION）時，步驟 7 改用比賽用 receipt：

```
python -m agent.submission.receipt --date T --team-id ... --sha256 ... --official-status ... --receipt-id ... --accepted-at ... --receipt-text "<原文>" --filename ... --evidence <截圖> --confirmed-by "姓名"
```

步驟 11 改為把 DataPack 放進 `data\official_datapack\`，由 19:30 gate 驗證、匯入。

## 2. 每次保留的證據（不存 password / cookie / session token / credential）

| 項目 | 位置 |
|---|---|
| D-Plan sha256 + 本機驗證 | `reports\official_test\<T>\TEST_SUBMISSION_PACKAGE.json` |
| 上傳時間、官方結果原文、submission id、截圖 | `data\official_test_receipts\<T>\records.jsonl` + 截圖 |
| DataPack 原檔（含 sha 的檔名）、欄位盤點、驗證 | `data\official_test_datapack\<T>\` |
| 對帳結果、下一日起點 | `reports\official_test\<T>\`（人工補充） |

`record-upload` 偵測到 cookie、token、password 類字串時會拒絕寫入。

## 3. 官方 UI / 回執 → 內部狀態（沿用既有狀態機，不另建）

| 官方畫面 / 回執（待封測確認實際字樣） | 內部狀態 | 條件 |
|---|---|---|
| 上傳完成 / Upload completed（沒有編號、沒有「生效 / 接受」字樣） | `UPLOADED` | 證據不足以視為接受 |
| 驗證失敗 / 格式錯誤 / 作廢 | `REJECTED` | 附原因 |
| 上傳成功 + 官方 submission id，或明確「已接受 / 已生效 / 提交成功」 | `ACCEPTED` | 需有 id，或 `--official-confirmation`（畫面明確顯示接受） |
| 處理中 / 待驗證 | `UPLOADED` | 之後再補記錄 |
| 後台沒有上傳功能 / 維護中 | `SUBMISSION_UI_UNAVAILABLE` | 不算 Agent failure |
| 08:55 後 | `SUBMISSION_WINDOW_CLOSED` | 無 ACCEPTED / UPLOADED / REJECTED 證據時 |

`OFFICIAL_RECEIPT_FORMAT = PENDING_PORTAL_VALIDATION`：收到實際回執後才確定欄位，不猜。

多次上傳的規則（有回歸測試）：

- 08:55 前**最後一次成功**的提交生效，不等於最後一次上傳。
- 之後被拒或處理中的上傳**不會覆蓋**已 ACCEPTED 的提交。這是本輪修正：之前會丟出 `InvalidTransition`。
- 狀態檔會同時顯示 `last_upload_status` 與 `submission_id`（生效那一份），以及 `uploads_today`。
- 每日 25 次上限計數。

## 4. DataPack 流程（目前假設 vs 待確認）

| 項目 | 目前假設（DataPack 規格書 v4.3 範例） | 封測確認 |
|---|---|---|
| A. 下載位置 | 後台「文件繳交」→「下載資料包」 | [ ] |
| B. 檔名 | 未規定（ManualFileProvider 掃描資料夾內所有 *.json，依 team / trade_date / generated_at 選最新） | [ ] |
| C. schema / version | `doc_type: DataPack`；`schema_version` "3.0"（範例）/ 規格 4.3 | [ ] |
| D. 欄位 | `account.{nav_tradable, cash, aum, cash_ratio_tradable, holdings_count, receivable_cash}`、`holdings[].{code, shares, receivable_shares, close_price, tradable_weight}`、`as_of_date`、`trade_date`、`compliance.{violations, notices, incidents}`、`prev_day_orders.{outcome, void_reasons, excluded_codes}`、`missing`、`generated_at` | [ ] **範例中沒有：Active Share、費用 / 稅、逐筆成交明細** |
| E. 下載時間 | 約 19:00 後 | [ ] |
| F. 同日多版本 | 可能（以 `generated_at` 最新者為準） | [ ] |
| G. 最新版本判斷 | `generated_at` 最大者；`missing` 不含 `prev_settlement` | [ ] |

`OfficialPortalProvider` 維持 `DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION`，不實作自動下載。

## 5. Auto-upload feasibility

**`AUTO_UPLOAD_FEASIBILITY = D. NOT_ENOUGH_INFORMATION`**

| 問題 | 目前所知 |
|---|---|
| 官方 API | 未公告；規則與 Email 只描述人工上傳 |
| 明確 upload endpoint | 無。後台是 SSO 轉入的獨立系統，網址與介面只在登入後可見 |
| CSRF / session | 經 SSO 交接（`/sso/authorize/` → redirect_url），後台必定依賴登入 session。是否有 CSRF 未知 |
| MFA / CAPTCHA | 未知（待人工確認 §1 #3） |
| 能否可靠取得 receipt | 未知（待確認回執格式與歷史頁） |
| 能否判斷 ACCEPTED | 未知（待確認是否有 submission id / 生效標示） |

- 即使之後確認有 web endpoint，自動化也需要保存或重用登入 session。這屬於本專案禁止的 credential 處理，必須有**官方明確提供的機制**並另行核准。
- 本輪不實作任何 upload。
