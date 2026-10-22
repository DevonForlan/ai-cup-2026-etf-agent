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

ACCEPTED 只來自歷史紀錄中帶有**設定好的官方接受字樣**（`auto_upload.accepted_markers`）的那一列。目前字樣清單為空，所以自動化永遠無法自稱 ACCEPTED。

### 4.3 Playwright driver

- 只建立介面。selector 必須在人工 E2E 觀察真實 DOM 後填入 `auto_upload.selectors`。
- 未填或未安裝 Playwright → `SELECTORS_NOT_CONFIGURED` / `PLAYWRIGHT_NOT_INSTALLED` → fail closed。
- 正式比賽前必須完成一次封測自動執行，並取得官方接受證據，Owner 才可開啟 `enabled`。

## 5. 待辦（依序）

1. 10/22 19:30 後：`official_test prepare`（目標 2026-10-23）→ 人工 E2E → 記錄。
2. 由 E2E 觀察：
   - 檢核 PASS / FAIL 原文
   - 送出後訊息
   - 歷史紀錄「已收件」等字樣
   - 是否有 submission id
   → 填 `receipt_format`、`accepted_markers`。
3. 若要自動化：
   - 安裝 Playwright（新依賴，需 PR）。
   - Owner 在 `data/browser_profiles/fundaiagent` 互動登入。
   - 依觀察的 DOM 填 selectors、實作 driver 方法。
   - 封測自動執行，取得官方接受證據。
   - Owner 開啟 `enabled`。
