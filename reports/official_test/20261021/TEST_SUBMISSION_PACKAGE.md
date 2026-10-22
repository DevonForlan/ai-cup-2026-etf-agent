# TEST_SUBMISSION_PACKAGE — 2026-10-21

> 官方封測用。**只有 status = READY_FOR_MANUAL_TEST_UPLOAD 才可人工上傳。** 本工具不登入、不上傳、不提交。AI 產生內容，需人工審閱。

- **Status**: `BLOCKED_TEAM_ID_NOT_CONFIGURED`（TEAM_ID_NOT_CONFIGURED: official Team ID not set in config/ops.yaml team.competition_team_id）
- Trade date: 2026-10-21
- Official Team ID: -（TEAM_ID_NOT_CONFIGURED）
- FINAL D-Plan: `C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽\submissions\20261021\FINAL\D-Plan_TEAM_TEST_2026-10-21.json`
- File name / team in file / date in file: D-Plan_TEAM_TEST_2026-10-21.json / TEAM_TEST / 2026-10-21
- SHA256: `sha256:8033d95516043abc901adf7e387bf3ec12359415646f0712c916da20fbafcb03`（verified: True）
- Schema version: 4.3；mode: dry-run；generated_at: 2026-10-20T20:19:26.689978+08:00
- Validation report: True（C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽\submissions\20261021\candidates\20261020_201926_git23f2428-dirty\validation_report.json）
- Local checks: schema PASS, ticker PASS, numeric PASS
- Quant fingerprint: `sha256:f34fa02e924011b2…`（frozen: True）
- Submission status（internal）: SUBMISSION_WINDOW_CLOSED
- Official receipt format: PENDING_PORTAL_VALIDATION

## Upload checklist（人工）

- [ ] Status = READY_FOR_MANUAL_TEST_UPLOAD（Team ID 已設定且檔內 team_id 相符）
- [ ] 從 `submissions\<T>\FINAL\` 取檔；檔名 = `D-Plan_<TEAM>_<T>.json`
- [ ] `certutil -hashfile <檔案> SHA256` = 上方 SHA256
- [ ] 後台顯示的交易日 / Team ID 與檔案一致
- [ ] 上傳後**逐字**複製官方回應、截圖存 `data\official_test_receipts\<T>\`
- [ ] `python -m agent.submission.official_test record-upload ...` 記錄結果（不要貼 cookie / token / 密碼）
