# Official Portal E2E + Automated Submission Feasibility（Issue #4）

> AI 產生內容，需人工審閱。Quant v1 未變。本工具不登入、不讀 cookie / token / 密碼、不猜私有 API；自動上傳預設關閉。

## 1. 已確認資訊

### 1.1 Owner 人工確認

| 項目 | 值 |
|---|---|
| 正式 Team ID | `TEAM_11442`（`config/ops.yaml team.competition_team_id`） |
| 文件繳交頁 | `https://fundaiagent.esun-ai-challenge.tw/docs`（`submission.portal_url`；`ui_status: AVAILABLE`） |
| D-Plan | 單一 JSON，≤ 2 MB（`submission.max_upload_bytes`） |
| 每日上限 | 25 次（`submission.official_daily_limit`） |
| 流程 | 上傳檔案 →「檢核結果」→ 通過才出現「送出繳交」→ 下方「歷史繳交紀錄」；同頁「下載資料包」 |
| 時間窗 | T−1 19:30 ～ T 08:55 |

### 1.2 公開前端程式確認（未登入、未呼叫任何 API，2026-10-22）

- 「FundAiAgent — 參賽者前台」是單頁應用。路由與標籤：
  - `overview` 投組儀表板
  - `data` 每日數據
  - `docs` **文件繳交**
  - `checks` 合規狀態
  - `perf` 排行榜
  - `login` 參賽者登入
- 認證是 SSO + 瀏覽器 session cookie，搭配 `csrftoken` cookie → `X-CSRFToken` header，打私有 `/api`；401 時轉 `/api/auth/login`。
- **沒有**參賽者 API token / API key / swagger / openapi 文件。
- 官方錯誤訊息（原文）：
  - `window_closed`「目前不在繳交時間內，本次未送出。」
  - `rehearsal_closed`「目前不在開賽前試繳期間內，檢核未執行。」
  - `attempt_limit`「今日繳交次數已用盡，**已收件的版本不受影響**。」
  - `file_too_large`、`size_mismatch`、`upload_not_found`、`not_in_team`、`disqualified`、`auth_loop`
- 每日狀態模型：`attemptsUsed`、`attemptsRemaining: 25`。

## 2. 狀態機（沿用既有，細分官方階段）

```
NOT_GENERATED → GENERATED → VALIDATED → READY_FOR_UPLOAD
  → FILE_UPLOADED → SERVER_VALIDATED（檢核結果明確 PASS）→ SUBMITTED（已按送出繳交）
  → ACCEPTED（官方證據：submission id 或歷史紀錄原文）/ REJECTED（官方拒絕或檢核 FAIL）
  （另：SUBMISSION_UI_UNAVAILABLE、SUBMISSION_WINDOW_CLOSED）
```

- FILE_UPLOADED、SERVER_VALIDATED、SUBMITTED **永遠不會**自動變成 ACCEPTED。
- `receipt.has_acceptance_evidence` 要求：`official_status = accepted`，且有官方 receipt / submission id **或**歷史紀錄原文（`history_entry`）。
- 操作者口頭確認（`--official-confirmation`）不算證據。
- 已 ACCEPTED 之後的上傳若被拒、處理中，**不會覆蓋**已生效版本。這與官方原文「已收件的版本不受影響」一致。
- receipt 欄位：
  - 基本：trade_date、team_id、filename、sha256
  - 時間：generated / validated（status 推導）、uploaded_at、server_validated_at、submitted_at、accepted_at
  - 結果：submission_id（可為 null）、server_validation_result、receipt_text、history_entry
  - 證據：evidence_files、status、failure_reason

## 3. 封測 D-Plan 與人工 E2E

1. **產生**：19:30 後執行 `python -m agent.submission.official_test prepare`。
   - 自動判斷目標交易日：08:55 前為今天，否則下一交易日。
   - 只能在 T−1 19:30 ～ T 08:30 之間產生；窗口外直接 BLOCKED，不會產生時間戳不合法的檔案。
   - Quant v1、template 敘述、初始資金（官方測試帳戶在取得測試 DataPack 前視為初始資金）。
   - 輸出在隔離的 `data/official_test_runs/<T>/`，不碰紙上交易的 `submissions/`。
   - 檔名 `D-Plan_TEAM_11442_<T>.json`。
2. **本機驗證（§10，全部 PASS 才是 READY_FOR_MANUAL_TEST_UPLOAD）**：
   - 檔案：json_parse、schema、team_id、trade_date、filename、file_size（≤ 2 MB）。
   - 內容：ticker、numeric、whole_lot。
   - 合規：holdings 20–30、2330 ≤ 25%、其他 ≤ 10%、cash < 25%、Active Share ≥ 15%。
   - 完整性：quant_fingerprint、D-Plan / order 一致（competition validator）、no_manual_override（FINAL sha 與產生時相同）。
   - 結果寫在 `reports/official_test/<T>/TEST_SUBMISSION_PACKAGE.md|json`。
3. **人工 E2E**（Owner 操作 UI，不得修改 D-Plan 投資內容）：
   1. 開後台、核對頁面的交易日。
   2. 選檔、上傳，讀「檢核結果」。
   3. PASS 才按「送出繳交」。
   4. 查看「歷史繳交紀錄」，逐字抄錄並截圖。
   5. 每一步記錄：

      ```
      python -m agent.submission.official_test record-upload --date T --sha256 ... --stage file_uploaded|server_validated|submitted|accepted|rejected --validation-result PASS|FAIL --history-entry "<歷史紀錄原文>" [--submission-id X] --message "<原文>" --evidence <截圖> --operator "姓名"
      ```

   6. 截圖與回執本體留在本機（gitignored）；git 只保存 package metadata、hash、摘要。
4. **DataPack**：送出成功後，在同頁「下載資料包」，存入 `data/official_test_datapack/`，再執行 `python -m agent.submission.official_test datapack --file ... --date <T+1> --team-id TEAM_11442`。只做唯讀驗證，不混入正式 `data/official_datapack/`。

## 4. 自動上傳可行性

**`AUTOMATION_FEASIBILITY = BROWSER_AUTOMATION_FEASIBLE`（條件式、尚未驗證）**

| 選項 | 判定 |
|---|---|
| A. 官方公開 / 文件化 API | **無**。前端使用 SSO session + CSRF 的私有 `/api`。直接呼叫等於抽取 session、偽造 CSRF、使用未公開 endpoint，禁止 |
| B. 一般瀏覽器自動化 | **可行，但未驗證**。頁面是標準 SPA（檔案選取 → 檢核 → 送出 → 歷史）。用 Owner 互動登入過的瀏覽器 profile 操作同一 UI，不讀 cookie、不打 API |
| C. 僅人工 | 在 B 驗證前的現況 |

已實作 `agent/submission/auto_upload.py`，**預設關閉**，任何情況都 fail closed。

### 4.1 Safety gate（全部要過）

- `auto_upload.enabled: true` 且 `method: browser`。
- run_mode 是 COMPETITION，或明確指定 `--official-test`。PRECOMPETITION 的紙上 FINAL 永遠不可上傳。
- **人工 E2E 已取得官方接受證據**（`manual_e2e_completed`；自動化自己的紀錄不算）。
- Team ID：檔案、設定都是 TEAM_11442。
- 狀態是 READY_FOR_UPLOAD / FILE_UPLOADED / SERVER_VALIDATED。
  - ACCEPTED → `ALREADY_ACCEPTED`。
  - SUBMITTED → 等待證據，不重送。
- 檔案：本機驗證 PASS、Quant freeze PASS、sha / 檔名 / 交易日一致、≤ 2 MB。
- 時間：窗口內；08:30 後只能上傳**既有** FINAL（不產生決策）；08:55 起禁止送出，執行中跨過 08:55 也會停。
- 自動嘗試次數 < `max_automated_attempts`（3，遠低於官方 25）；官方剩餘次數讀不到或為 0 → 停。

### 4.2 執行時 fail closed

以下情況都會停止，絕不亂按送出：

- 登入狀態不明。
- 頁面日期或 Team 不符。
- 歷史紀錄已有本檔「已收件」→ 回 `ALREADY_ACCEPTED`。
- 檢核結果 UNKNOWN。
- 任何 UI 例外。
- 送出後歷史紀錄出現多筆相符（歧義）。

ACCEPTED 只來自歷史紀錄中**唯一一列**符合本檔且帶有官方接受字樣（`config/portal_adapter.yaml` 的 `history_accepted`，狀態須為 CONFIRMED_REAL_E2E）。目前字樣仍是 `PENDING_REAL_E2E_WORDING`，所以自動化永遠無法自稱 ACCEPTED；逾時或歧義 → `SUBMITTED_UNVERIFIED` + `MANUAL_CHECK_REQUIRED`。

### 4.3 Playwright driver（`agent/submission/portal_driver.py`）

- 依賴：`requirements-portal.txt`（playwright 1.55.0，可選安裝，CI 不需要）。使用系統 Microsoft Edge（`channel="msedge"`），不下載瀏覽器。
- Profile：`data/browser_profiles/fundaiagent`（gitignored）。Owner 用一般方式在此 profile 登入；程式**不填帳密、不讀 cookie / storage / token、不呼叫 /api、不繞 SSO / MFA / CAPTCHA**。
- 未登入（網址在 `/login`、`/sso`，或出現「參賽者登入」）→ `LOGIN_REQUIRED`，fail closed。
- 介面 `PortalDriver`：open_portal / check_login / read_page_state / read_team_id / read_trade_date / read_window_status / read_attempts / read_history / read_strategy_document_status / upload_file / wait_for_server_validation / read_validation_result / submit / read_submit_result / verify_acceptance / capture_evidence / close。
- 正式比賽前必須完成一次封測自動執行，並取得官方接受證據，Owner 才可開啟 `enabled`。

## 5. Selector inventory（`config/portal_adapter.yaml`）

- 所有 selector 與官方字樣只在此檔。順序 role → label → accessible name → stable visible text → stable data-* / id → CSS；不用絕對 XPath、nth-child、像素 / 螢幕座標。
- 每個項目都有 primary（第一個 strategy）、fallback（其餘）、`source`（證據）、`confidence`。
- 狀態：CONFIRMED_REAL_E2E / CONFIRMED_PUBLIC_BUNDLE / OWNER_OBSERVED_LABEL / GENERIC_CANDIDATE / PENDING_WINDOW_ONLY / PENDING_REAL_E2E_SELECTOR / PENDING_REAL_E2E_WORDING。
- 動作政策：COMPETITION 的上傳 / 送出只能用 CONFIRMED_REAL_E2E；`--official-test` 可用 OWNER_OBSERVED_LABEL / GENERIC_CANDIDATE；PENDING_* 一律不可用。
- 字樣比對為逐字子字串；PASS 與 FAIL 同時或都沒出現 → UNKNOWN。
- 目前狀態：

| 類別 | 項目 |
|---|---|
| CONFIRMED_PUBLIC_BUNDLE | 文件繳交 nav、參賽者登入、目前不在繳交時間內；5 個官方錯誤字樣 |
| OWNER_OBSERVED_LABEL | 檢核結果、送出繳交、歷史繳交紀錄、下載資料包 |
| GENERIC_CANDIDATE | JSON file input |
| PENDING_REAL_E2E_SELECTOR（登入後即可確認） | upload area / button、歷史列、頁面交易日、Team ID、次數、ETF 策略文件狀態 |
| PENDING_WINDOW_ONLY（只有窗口內 / 上傳或送出後才出現） | 檢核 PASS / FAIL marker 與字樣、送出確認 modal 與按鈕、送出成功字樣、accepted / rejected 歷史 marker 與字樣 |

- 唯讀探索：`python -m agent.submission.portal_driver discover [--wait-login N]` → `data/portal_discovery/<ts>/page_state.json`（gitignored，網址去除 query string；擷取 role / accessible name / id / data-* / 表格 / alert，不讀表單值）。
- 唯讀實測：`python -m agent.submission.portal_driver readonly-test` → `PORTAL_READONLY_REAL_TEST = PASS | FAIL`。
- 2026-10-23 實測：19:07 開啟 profile 等待 Owner 登入 30 分鐘，未登入 → `LOGIN_REQUIRED`；19:38 readonly-test → FAIL（LOGIN_REQUIRED，fail closed，未上傳 / 未送出）。

## 6. 營運流程（全部預設關閉）

| 項目 | 實作 |
|---|---|
| 排程 | 沿用 19:30 工作（不新增高頻排程，StartWhenAvailable）。COMPETITION FINAL PASS 後進 `submission_stage`；追趕執行若已有 FINAL（READY_FOR_UPLOAD / FILE_UPLOADED / SERVER_VALIDATED / SUBMITTED）→ 只上傳 / 續傳 / 驗證同一 FINAL；ACCEPTED 不碰。PRECOMPETITION → `NOT_APPLICABLE_PRECOMPETITION`；auto-upload 關閉 → `MANUAL_UPLOAD_REQUIRED`。 |
| Gate | 本機驗證 17 項（json / schema / ticker / numeric / team / date / 檔名 / 大小 / 整張 / 檔數 / 2330 / 其他 / 現金 / Active Share / Quant / 委託一致 / 未手改）全部存在且 PASS；缺任一項 → `LOCAL_VALIDATION_UNKNOWN` fail closed。 |
| 送出前複查 | 登入仍有效、頁面 Team / 日期、FINAL SHA 未變、檢核仍 PASS、無非預期 modal、< 08:55。 |
| 檢核 | PASS → 送出；FAIL → REJECTED；UNKNOWN → FAIL_CLOSED；逾時 → `MANUAL_CHECK_REQUIRED: VALIDATION_TIMEOUT`。 |
| 重試 | 同 trade_date / 檔名 / SHA 才可重試；SHA 不同 → `DIFFERENT_SHA_RETRY_BLOCKED`。自動上限 3、官方 25；FILE_UPLOADED / SERVER_VALIDATED 頁面仍 PASS → 不重傳；SUBMITTED 只驗證。 |
| 人工備援 | `MANUAL_UPLOAD_REQUIRED.json`：trade_date、Team、完整路徑、檔名、SHA、大小、本機驗證、狀態、portal / login 狀態、自動 / 官方次數、截止時間與剩餘分鐘、可直接複製的記錄指令。 |
| 證據 / 稽核 | 截圖 + 頁面文字（本機，gitignored）；`audit.jsonl` 含 generated / validated / uploaded / server_validated / submitted / accepted 時間、attempt、結果、歷史列、submission id、原文、portal 狀態、截圖與文字路徑。 |
| 訊號 | 14 個：LOGIN_REQUIRED、READY_FOR_UPLOAD、AUTO_UPLOAD_RUNNING、FILE_UPLOADED、SERVER_VALIDATED、SUBMITTED、SUBMISSION_ACCEPTED、REJECTED、MANUAL_UPLOAD_REQUIRED、WARNING 0800 / 0815 / 0845、DATAPACK_REQUIRED、WINDOW_CLOSED。 |
| DataPack 交接 | `handoff --date T`：team_id、as_of、schema、NAV、cash、holdings、freshness、SHA256 全 PASS → `DATAPACK_READY`；缺 / 過期 → `DATAPACK_REQUIRED`；不符 → `DATAPACK_INVALID`。**不退回紙上帳本**。 |
| latest_status | 再加 datapack_status、next_action。 |

## 7. 下一個有效窗口與 REAL_E2E

- `python -m agent.submission.e2e_plan` → `reports/REAL_E2E_PLAN.json`、`docs/REAL_E2E_RUNBOOK.md`。
- T = **2026-10-27**（比賽第一個交易日；10/26 休市）；窗口 2026-10-26 19:30 → 2026-10-27 08:55；檔名 `D-Plan_TEAM_11442_2026-10-27.json`。
- `E2E_PREPARATION_STATUS = WAITING_FOR_DECISION_WINDOW`：窗口未開，不可合法產生該日決策，**不預先偽造**。
- T 是比賽日：`run_mode` 需由 Owner 切成 COMPETITION（Owner 決定，Claude Code 不切）。

只能由 Owner / 窗口內完成：

1. Owner 在 `data/browser_profiles/fundaiagent` 正常登入 → `discover` + `readonly-test`（PASS）→ PENDING_REAL_E2E_SELECTOR 升級。
2. 窗口內人工上傳 → 檢核 → 送出 → 歷史 → 唯讀擷取 → PENDING_WINDOW_ONLY 升級（只改 `portal_adapter.yaml`）。
3. 記錄官方接受證據；結算後 DataPack 交接。
4. 之後才可提出 `ENABLE_AUTO_UPLOAD_RECOMMENDATION`，由 Owner 核准開啟 `enabled`。
