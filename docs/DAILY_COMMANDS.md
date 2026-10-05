# 每日指令（比賽日，Windows PowerShell）

> 只要照順序貼上。`T` = 交易日（例 `2026-10-27`），`TEAM_XXX` = 主辦方給的隊伍 ID。
> 指令都不含 `exit`，視窗不會被關掉。程式**永遠不會自動上傳**；上傳由人工完成。
> Claude CLI 失敗（未登入、額度用完、逾時、JSON 錯、版本不同、找不到 CLI）→ 自動改用 Template 敘事，D-Plan 照常產生，**不用處理**。

## 1. 進入專案
```powershell
Set-Location "$env:USERPROFILE\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽"
```

## 2. Preflight（含 Claude 版本 + 登入檢查）
```powershell
powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1 -Date 2026-10-27 -Mode competition -CompetitionProfile prod
```
看最後一行：`LLM: PRIMARY=claude-cli STATUS=READY FALLBACK=template` → Claude 可用；
`STATUS=DEGRADED` → 這次用 Template 敘事（不影響決策、不阻擋）。`PREFLIGHT: BLOCK` 才需要處理（見 `docs\EMERGENCY_RUNBOOK.md`）。

## 3. 執行比賽日（19:30 後；一個指令）
```powershell
powershell -ExecutionPolicy Bypass -File scripts\competition_dry_run.ps1 -Mode competition -TeamId TEAM_XXX -Date 2026-10-27 -CompetitionProfile prod
```
（等同 `.venv\Scripts\python.exe agent\competition_day.py --date 2026-10-27 --team-id TEAM_XXX --mode competition --competition-profile prod`）

## 4. 檢查 FINAL
```powershell
Get-Content submissions\20261027\FINAL_CANDIDATE.txt -Encoding UTF8
Get-Content logs\ops\20261027\operator_summary.txt -Encoding UTF8 -Tail 16
```
必須同時看到：`READY TO SUBMIT`、`MODE COMPETITION`、正確 `TEAM ID`、`TRADE DATE`、`VALIDATION : PASS`。

## 5. 上傳（人工）
到主辦方平台上傳 `FINAL_CANDIDATE.txt` 上寫的那一個檔案（`submissions\20261027\FINAL\D-Plan_TEAM_XXX_2026-10-27.json`），截止 **T 日 08:55**。
回執畫面截圖存成 `submissions\20261027\receipt_HHMM.png`。

## 6. 記錄回執
```powershell
.venv\Scripts\python.exe -m agent.submission.receipt --date 2026-10-27 --team-id TEAM_XXX --sha256 <FINAL 的 SHA256> --method manual_web --receipt-id <平台編號> --official-status accepted --screenshot submissions\20261027\receipt_HHMM.png --confirmed-by "姓名"
```

## 7. 官方結算（T 日收盤後、主辦方公布後）
```powershell
.venv\Scripts\python.exe agent\ops\settlement_entry.py --template
# ↑ 產生空白範本 templates\settlement_official_template.csv；複製成 A / B 兩份，由兩人分別依官方畫面填寫
.venv\Scripts\python.exe agent\ops\settlement_entry.py --date 2026-10-27 --file <A.csv> --verify-file <B.csv> --operator "姓名" --source "官方後台 庫存明細 2026-10-27 HH:MM" --snapshot-ref "evidence\20261027_HHMM.png"
.venv\Scripts\python.exe agent\ops\settlement_entry.py --date 2026-10-27 --file <A.csv> --verify-file <B.csv> --operator "姓名" --source "官方後台 庫存明細 2026-10-27 HH:MM" --snapshot-ref "evidence\20261027_HHMM.png" --confirm
powershell -ExecutionPolicy Bypass -File scripts\archive_daily.ps1 -Date 2026-10-27
```
細節：`docs\OFFICIAL_SETTLEMENT_ENTRY_SOP.md`（官方結算格式 NC-1 仍未確認，先用人工輸入）。

---
- 第一個比賽日加 `-Initial`（從初始現金開始）。2026-10-26 為 TWSE 休市日（官方行事曆）；主辦方的第一個交易日仍待確認（NC-15）。
- 不想用 Claude：拿掉 `-CompetitionProfile prod` 即為純 Template（決策完全相同）。
- 換 FINAL（需理由與姓名）：`.venv\Scripts\python.exe agent\ops\final.py replace-final --date 2026-10-27 --team-id TEAM_XXX --run-id <run_id> --reason "原因" --operator "姓名"`。
