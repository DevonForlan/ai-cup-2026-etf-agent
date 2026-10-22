# Competition Go / No-Go Checklist（2026-10-26 判定）

> AI 產生內容，需人工審閱。10/26（休市日）上午由操作者逐項確認並簽名。第一個送件窗口是 10/26 19:30～10/27 08:55。
>
> 自動檢查：`.venv\Scripts\python.exe -m agent.ops.competition_preflight --trade-date 2026-10-27`（只讀，不切換任何設定）。

## 判定規則

| 判定 | 條件 |
|---|---|
| **GO** | 所有項目 ✔ |
| **GO_WITH_WARNINGS** | 沒有 ✘，但有已理解並記錄的 ⚠（例如 Claude 版本漂移 → template fallback 可用） |
| **NO_GO** | 任何一項 ✘（例如 Team ID 未設定、凍結 hash 不符、D-Plan 驗證失敗、排程缺失） |

## 檢查表

「2026-10-16 現況」為本輪 rehearsal 時的狀態；10/26 需重新確認。

| # | 項目 | 檢查方式 | 通過條件 | 2026-10-16 現況 | 10/26 |
|---|---|---|---|---|---|
| 1 | Team ID | preflight `team_id` | `config/ops.yaml team.competition_team_id` = 主辦方正式 Team ID（非 placeholder；P-1 已實作） | ✘ **TEAM_ID_NOT_CONFIGURED** | [ ] |
| 2 | Run mode | `config/ops.yaml run_mode` | GO 決策後由人工改為 `COMPETITION`（工具不自動切換） | ⚠ PRECOMPETITION（預期） | [ ] |
| 3 | Trading calendar | preflight `trading_calendar` / `trade_date` | ops.yaml 與官方 TWSE 行事曆一致；10/27 = DAY 1 | ✔ 18 個休市日一致 | [ ] |
| 4 | Official universe | `config/universe_150.csv` | 150 檔、與官方清單一致 | ✔ 150 | [ ] |
| 5 | Quant fingerprint | preflight `frozen_quant_fingerprint` + W5 重跑 | sha256 `f34fa02e…d2e0`；W5 NAV 1,014,240,575.839861741934859718；24/24 decision hash | ✔ | [ ] |
| 6 | Claude runtime | preflight `claude_cli_auth` | READY；版本漂移 = ⚠（fallback 已驗證） | ⚠ READY，2.1.301 不在 pinned 清單 | [ ] |
| 7 | D-Plan v4.3 | preflight `dplan_schema` + rehearsal | schema v4.3；rehearsal D-Plan schema / ticker / numeric PASS | ✔ | [ ] |
| 8 | DataPack | `datapack_status --mode COMPETITION --trade-date 2026-10-27` / `2026-10-28` | 10/27 = INITIAL_CAPITAL READY；10/28 起缺檔必須 BLOCKED；Portal provider DISABLED | ✔ gate 測試 19/19 PASS | [ ] |
| 9 | ETF benchmark | preflight `etf_benchmark_freshness` | 30 檔、最舊 ≤ 3 日 = ✔；≤ 10 日 = ⚠ | ⚠ 最舊 6 日（10/13） | [ ] |
| 10 | Active Share | preflight `active_share_source` + rehearsal | 30/30 ETF 有實際持股；rehearsal Active Share ≥ 15%（目標 30%） | ✔ 46.95% | [ ] |
| 11 | Schedulers | preflight `scheduler:*` | 兩個工作都 Ready、IgnoreNew、StartWhenAvailable、上次結果 0 | ✔ | [ ] |
| 12 | Logs | preflight `writable:*` | submissions / logs / archive 可寫 | ✔ | [ ] |
| 13 | Disk | preflight `disk_space` | ≥ 5 GB | ✔ 86.8 GB | [ ] |
| 14 | Latest tests | `.venv\Scripts\python.exe -m pytest` | 全部 PASS | ✔（見 readiness 報告） | [ ] |
| 15 | Dry-run | `experiments\precompetition_e2e_rehearsal.py` 或 19:30 實跑 | DRY_RUN_OK、validation PASS、Claude 不改決策 | ✔ | [ ] |
| 16 | No unexpected git diff | `git status` / preflight `git_clean` | 比賽模式需乾淨工作樹（未 commit 的研究檔需先處理） | ✘ 有未 commit 檔案（等待使用者決定 commit） | [ ] |
| 17 | 重複程序 | preflight `duplicate_processes` | logical runs ≤ 1 / 種類 | ✔ | [ ] |
| 18 | 行情完整性 | preflight `market_data_freshness`（P-2 coverage gate） | T−1 COMPLETE：TWSE 與 TPEx 各 ≥ 95%、持股全部有價 | ✔（10/16 TWSE 曾漏抓，已補） | [ ] |
| 19 | Active Share 來源 | preflight `active_share_gate`（P-5） | 30/30 官方主動 ETF 有持股、最舊 ≤ 10 日（COMPETITION 否則 BLOCK） | ⚠ 最舊 6 日 | [ ] |

## 2026-10-16 暫定判定：**NO_GO**

阻擋項：

- #1 Team ID 未設定。
- #16 工作樹不乾淨：competition 模式的 preflight 會 BLOCK 未 commit 的變更。

兩者都需要使用者決策，工具不會自動處理。

## 簽核

- 判定：GO / GO_WITH_WARNINGS / NO_GO：__________
- 操作者：__________　時間：2026-10-26 ____:____
- 備註（WARN 項目與理由）：__________
