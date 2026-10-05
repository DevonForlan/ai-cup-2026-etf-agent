# Final Operator Checklist（比賽日最後確認清單）

> 印出來放在桌上。每一行打勾才上傳。AI 產生內容，需人工審閱。

## 前一晚（T-1，送件窗口 19:30 起 — 以「T 的前一個日曆日」19:30 開始；週一的 D-Plan 要在週日晚上或週一早上做）
- [ ] T-1 的官方結算已依 `docs/OFFICIAL_SETTLEMENT_ENTRY_SOP.md` 雙重輸入、對帳 MATCH、`--confirm` 完成
- [ ] `config/ops.yaml market_holidays` 已含官方公布、會影響 T-1 的休市日（只填官方日期）
- [ ] 執行 `scripts\competition_dry_run.ps1 -Mode competition -TeamId TEAM_XXX -Date <T>`
- [ ] Console **最後 15 行**：`RUN STATUS : READY_TO_SUBMIT`、`MODE : COMPETITION`、**日期 = T**、**TEAM ID 正確**
- [ ] `FINAL ACTION` 是 `MARKED`（第一次）或 `KEPT_IDENTICAL`；若 `KEPT_DIFFERENT` → 看原因，必要時 `agent\ops\final.py replace-final`（需姓名 + 理由）
- [ ] `reports\ops_daily\<T>_OPERATOR_SUMMARY.md` 無 BLOCK；資料健康 PASS 或已理解的 WARN
- [ ] `agent\ops\healthcheck.py --date <T> --mode competition` → 不是 BLOCKED

## 上傳（人工，主辦方平台）
- [ ] 打開 `submissions\<T>\FINAL_CANDIDATE.txt`：`UPLOAD THIS FILE` 路徑、檔名 `D-Plan_<TEAM>_<T>.json`
- [ ] **只上傳 `submissions\<T>\FINAL\` 裡那一個檔**；不要從 candidates\ 或 dplan_work\ 拿
- [ ] （建議）`certutil -hashfile <檔案> SHA256` = FINAL_CANDIDATE.txt 的 SHA256
- [ ] 截止時間 08:55 前；同日不要重複上傳（NC-10 未確認「最後一次為準」）
- [ ] 平台回執 / 截圖存 `submissions\<T>\receipt_<HHMM>.png`
- [ ] 記錄回執：`.venv\Scripts\python.exe -m agent.submission.receipt --date <T> --team-id TEAM_XXX --sha256 <sha> --method manual_web --receipt-id <平台編號> --official-status accepted --screenshot submissions\<T>\receipt_<HHMM>.png --confirmed-by "姓名"`
- [ ] 狀態為 `SUBMISSION_CONFIRMED`（只有 `READY_TO_SUBMIT` = **還沒交**）

## T 收盤後
- [ ] `scripts\archive_daily.ps1 -Date <T>`（內部結算 + 稽核索引）
- [ ] `reports\ops_daily\<T>_EOD.md` 無 Unresolved（或已處理）
- [ ] 主辦方結算公布後：SOP 輸入 T 的官方結算
- [ ] `scripts\backup_competition_state.ps1`，複製到第二位置

## 絕對不要
- 不要上傳任何 DRY-RUN / HISTORICAL 檔（banner 會寫 `DO NOT UPLOAD`）
- 不要手改 D-Plan、FINAL、archive、settlement JSON
- 不要在比賽期間改 `config\strategy_quant_v1.yaml` 或程式（NC-9 未確認）
- 不要把 API key 放在 `.env` 以外的地方，不要貼進對話或 log
