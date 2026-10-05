# ROUND 06 — Competition Rehearsal Report

日期：2026-10-05　｜　git：`dd99cef`（起點）→ `83af462`（release candidate）→ 本報告 commit　｜　依公司政策：AI 產生內容，需人工審閱。

> **一句話結論**：完整營運流程以 24 個交易日逐日彩排兩次（replay：NAV 逐日 = baseline；clock-sim：competition 模式、所有閘門啟用），皆 **24/24 PASS**。本輪新增結算人工輸入 SOP（雙重輸入 + 確認閘門）、提交介面 / 狀態機 / 回執、決策指紋與候選比對、FINAL 凍結、crash / lock 恢復、備份還原、斷網降級、資安掃描、發版驗證。演練中找到並修正 **6 個真問題**（見 §2）。Quant Core v1 決策路徑 **0 行修改**。阻擋項全為外部：NC-1、NC-15、API key → **DRY_RUN_READY**。

---

## 1. Baseline
- 開始時工作樹乾淨，267 tests 全過；W5 replay：NAV **1,014,240,575.839861741934859718**，0 違規 / 0 驗證失敗 / 0 fallback（`sim_runs/round06_baseline_quant_v1/`），與 Round 04/05 完全相同。
- 起始 commit `dd99cef chore: start round 06 competition rehearsal`。
- Round 06 對 `agent/portfolio`、`agent/features`、`agent/engine`、`agent/risk`、`agent/pipeline.py`、`agent/sim`、`agent/dplan`、`config/strategy_quant_v1.yaml` 的 diff：**空**。

## 2. Tests
**324 passed / 0 failed / 324 total**（+57）。新增：`tests/ops/test_round06.py`、`tests/ops/test_round06_tools.py` 與既有 ops 測試擴充：多日彩排 / ledger continuity、結算範本 / 驗證 / 雙重輸入 / 確認閘門、提交狀態機 / 回執 / schema、組織者回覆 adapter、決策指紋 / idempotency / 候選比對、replace-final、crash recovery（6 個中斷點）、stale lock、ETF 重試 / fallback、截止全時鐘、clock skew、休市新鮮度、T-1 可見性、窗口未開、他隊 FINAL、斷網降級、資安掃描、備份還原、readiness。

**本輪找到並修正的真問題（皆有 regression test）**
| # | 發現於 | 問題 | 修正 |
|---|---|---|---|
| 1 | 24 日 replay 彩排 | 09/25、09/28 休市，新鮮度以「工作日」計 → T-1 行情看似過期 → **BLOCK 09/29** | 以交易日計（歷史缺口 + `ops.yaml market_holidays`） |
| 2 | 彩排 | replay 時 preflight 的 ETF 新鮮度讀到交易日之後的資料 | 只看交易日前的資料 |
| 3 | 當日實資料演練 | MOPS 查詢未來日 → 退避重試耗 157 s | 不查未來日 |
| 4 | 斷網演練 | 同日他隊已凍結 FINAL 被當作本隊 FINAL 顯示 | REFUSED_OTHER_TEAM + BLOCK |
| 5 | 當日實資料演練 | 14:57 執行：T-1 行情已存但 15:00 才可用 → 量化視為缺資料 → fallback → 驗證失敗（原因不明確） | preflight `pit_t1_prices_visible` 明確 BLOCK |
| 6 | 當日實資料演練 | 窗口未開（T-1 19:30 前）執行 → C6 失敗才發現 | preflight `submission_window_open` 提前 BLOCK |
另：Round 05 的 manifest 鎖在 60 秒後**不論擁有者是否存活**都會刪除 → 改為 pid 感知、只回收已死程序的鎖並留證據。

## 3. 24-day dress rehearsal（`agent/ops/rehearsal.py`）
2026-08-28 → 2026-10-02（24 交易日，含 09/25、09/28 休市）。每日：資料健康 → 對帳 → preflight → Quant v1 → D-Plan → 驗證 → 送件包 → FINAL → 封存 →（clock-sim）回執 → T 結算 → 操作員 A/B 雙重輸入官方結算 → EOD 報告 → T+1。

| 模式 | 結果 | NAV | 其他 |
|---|---|---|---|
| replay（historical，決策時點 = T 07:00） | **24/24** | 最終 1,014,240,575.84，**每日 = baseline** | 對帳 23/23 MATCH；continuity 0 斷點 |
| clock-sim（competition 模式，T-1 日曆日 20:00） | **24/24** | 最終 1,014,240,575.84 | 每日 `SUBMISSION_CONFIRMED`（模擬回執）、MATCH、continuity OK |

Pass criteria（兩模式皆）：0 invalid D-Plan、0 unexpected fallback、0 覆寫、0 錯日期 / 錯隊伍、0 archive 碰撞、0 continuity break、0 缺 FINAL、0 hash mismatch、0 未處理例外、0 殘留 .partial。
每日輸出齊全：`logs/ops`、`submissions`、`archive`、`data/settlement`（internal / official / confirmation / reconciliation）、`reports/ops_daily`（OPERATOR_SUMMARY + EOD）、`audit`（COMPLETENESS 12/12）。
資料健康每日 WARN（L2）：歷史 store 缺部分 ETF 的早期持股（僅最新日發行商），為回放限制非營運問題；Active Share 在 08/28–08/31 因 ETF 歷史不足為 UNKNOWN（不使驗證失敗）。
細節：`reports/round06_rehearsal_daily.csv`（clock-sim）、`reports/round06_rehearsal_daily_replay.csv`、`reports/round06_rehearsal_summary.json`。

## 4. Settlement manual workflow
`agent/ops/settlement_entry.py` + `docs/OFFICIAL_SETTLEMENT_ENTRY_SOP.md` + 範本 `templates/settlement_official_template.csv/.json`。
檢查：日期 / 週末、檔內日期、ticker 格式、150 檔、重複、整數股數 ≥ 0、現金 ≥ 0、NAV > 0、NAV = Σ股數×收盤 + 現金、格式；`--verify-file` 雙重輸入（不一致 → DOUBLE_ENTRY_MISMATCH BLOCK）；確認紀錄 `YYYYMMDD_confirmation.json`（entered_at、source、operator、input sha256、snapshot reference、notes、confirmed）；官方檔確認後被改 → 確認失效。competition 模式未確認 → **BLOCK**。無 GUI、無瀏覽器自動化、無 OCR、無登入。

## 5. Submission adapter
`agent/submission/`：`SubmissionProvider`（prepare / submit / verify_receipt）、`ManualSubmissionProvider`（只 prepare；`submit()` 拋 `OfficialSubmissionUnavailable`）、`FutureOfficialAPISubmissionProvider`（全部拋出）、`receipt.py`（回執模型 + JSON schema + CLI）。沒有任何上傳、登入、猜測 endpoint。

## 6. Submission state machine
`NOT_READY → READY_TO_SUBMIT → SUBMITTED_UNVERIFIED / SUBMISSION_CONFIRMED / REJECTED / UNKNOWN`，允許的轉移表化；`SUBMISSION_CONFIRMED` 需回執 sha256 / 隊名 / 日期與 FINAL 吻合且平台 accepted + 回執編號。DRY-RUN FINAL 永遠不會 READY。已確認不得退回 READY。回執 append-only。

## 7. Soak test（`agent/ops/soak.py`，fixture store，同一 process）
100 次（其中 14 次刻意 crash，輪流 5 個中斷點）：**0 未預期例外、0 損毀輸出、0 非法覆寫、0 指紋漂移、0 殘留鎖**；殘留 .partial 6 個（皆為刻意 crash，≤ 14）。
記憶體 RSS：start 155.0 / median 159.1 / max 164.4 / end 161.5 MB（+8 MB，PASS）；handles 253 → max 274 → 244。
Runtime：無干擾那次 p50 1.40 s、末 10 次中位 1.51 s；第二次 p95 6.27 s 為與資安掃描（3,600 檔 I/O）同時執行的主機競爭（第 66–90 次尖峰），非累積退化。

## 8. Recovery test
中斷點 after_refresh / before_package / package_mid / before_archive / archive_mid + 刷新中（`SimulatedCrash`）：重跑皆 READY_TO_SUBMIT、新 run_id、FINAL 未損毀（若已標記則保持不變）、可見 candidate 皆完整、殘留只以 `.partial` 形式存在、結算帳未被污染。
Stale lock：只有「超過 120 s 且擁有者 pid 不存在」才回收，改名保留為 `.stale-*` 並寫 `lock_recovery.jsonl`；擁有者存活時絕不回收（LockTimeout）。

## 9. Idempotency
同日、同 git、同資料、同設定、同結算重跑：決策指紋相同、`compare_candidates` = IDENTICAL_DECISION，FINAL 不變（KEPT_IDENTICAL）。soak 100 次指紋 0 漂移。

## 10. Decision fingerprint
`decision_fingerprint` = hash(決策核心〔decisions ticker/action/target_weight、no-trade、orders、regime/stance/posture〕+ 策略設定 hash + 資料快照 hash + 結算 hash + code version)；不含 generated_at、run_id、敘事文字、agent_metadata。寫入 `run_metadata.json`、`FINAL_FREEZE.json`、FINAL banner。**Deterministic：是**。
`compare_candidates.py`：IDENTICAL_DECISION / NARRATIVE_ONLY_DIFFERENCE / DATA_DIFFERENCE / CONFIG_DIFFERENCE / CODE_DIFFERENCE / DECISION_DIFFERENCE（列出差異與原因；若無輸入變更則標示「非決定性，提交前調查」）。

## 11. Runtime SLA（內部門檻：quant / validation / package / archive < 10 s，refresh < 300 s）
| 情境 | p50 / p95 或實測 | 違反 |
|---|---|---|
| 彩排每日（無網路刷新） | clock-sim 5.5 / 6.2 s；replay 5.4 / 6.0 s | 0 |
| 當日實資料完整一日（10/06 dry-run） | 總 175 s：refresh 170 s（ETF 116 s）、量化 + D-Plan + 驗證 2.4 s、package 1.1 s、archive 0.4 s | 0 |

## 12. ETF reliability
最新抓取成功率 **27/30（90%）**；中信 3 檔（00983A、00995A、00406A）latest / 重試 / 前 3 個公布日皆回空 → **STALE_FALLBACK**（沿用 10/01–10/02 已存持股，manifest 明確標示，不偽造今日）。
循序 vs 並行（4 workers，實測）：資料**完全相同**、狀態相同、288 s → 100 s（2.9×）；設定 `etf_fetch.max_workers: 3`。實際 3 workers 一日 116 s（中信 3 檔重試佔主要時間）。
`reports/round06_etf_parallel.json`、`reports/round06_etf_reliability.csv`。

## 13. Source reliability（`reports/source_reliability.csv`，只計真實抓取，排除回放與模擬斷網）
| source | 嘗試 | 成功 | 失敗 | stale | fallback | 中位 / p95 延遲 s |
|---|---|---|---|---|---|---|
| twse_prices（CRITICAL） | 4 | 4 | 0 | 0 | 0 | 0.14 / 0.99 |
| tpex_prices（CRITICAL） | 4 | 3 | 0 | 1（14:24 尚未公布） | 0 | 0.76 / 2.27 |
| twse / tpex_institutional | 4 / 4 | 4 / 4 | 0 | 0 | 0 | 3.6 / 4.4 |
| etf_holdings | 4 | 4 | 0 | 0 | 4（中信 3 檔） | 116 / 123 |
| corporate_actions | 4 | 4 | 0 | 0 | 0 | 17.1 / 17.5 |
| mops_material_info | 4 | 3 | 1（未來日 bug，已修） | 0 | 0 | 8.6 / 157 |
| mops_revenue / taifex / us_market | 4 | 4 | 0 | 0 | 0 | 3.4 / 4.1 / 12.1 |
樣本少（一天的多次執行）；比賽前每日實跑會持續累積。`reports/DATA_AVAILABILITY_MATRIX.md` 列出每個來源的權威、可用時間、重要度、fallback、失敗影響。

## 14. Deadline simulation
| 時間 | 階段 | LLM | 資料更新 | FINAL |
|---|---|---|---|---|
| T-1 19:30 / 22:00、T 02:00 / 05:30 / 07:00 | NORMAL | 可 | 全部 | 可 |
| T 08:30 | RESTRICTED | 可（不重試） | 只關鍵 | 可 |
| T 08:44 | NO_LLM | 否 | 只關鍵 | 可 |
| T 08:45 / 08:46 / 08:51 / 08:54 | PACKAGE_ONLY | 否 | 否 | 可 |
| T 08:56 | PAST_CUTOFF | 否 | 否 | **不產生**（LATE_PAST_CUTOFF） |
全部為參數化 regression tests。另：窗口未開（T-1 日曆日 19:30 前）→ 提前 BLOCK（C6）；replace-final 截止後拒絕。

## 15. Backup / Restore
`scripts/backup_competition_state.ps1` / `agent/ops/backup.py`：config、settlement、observations、submissions、archive manifests、audit、logs/ops、daily reports、templates；**不含** `.env`、API key、data/history、data/raw；zip 內 manifest 逐檔 sha256；restore 驗證 hash、拒絕覆寫。
Restore drill（`agent/ops/restore_drill.py`）：備份 clock-sim 彩排狀態 → `git worktree add --detach` 乾淨 checkout → 還原到新資料夾 → 從乾淨 checkout 跑下一交易日 2026-10-05（competition 模式）→ **READY_TO_SUBMIT、對帳 MATCH、起點 = 還原的 10/02 帳、確實由 worktree 程式執行**；worktree 已移除，工作樹未動。**PASS**。

## 16. Network degraded test
實際資料：T-1（10/02）已在 store、所有來源斷線（`--offline`）→ 關鍵來源 CACHED → **DRY_RUN_OK / L2**；T-1（10/06）不在 store → **BLOCKED**（不使用過時關鍵行情）。fixture 版本同結果（tests）。

## 17. Security scan（`agent/ops/security_scan.py`）
掃描 3,694 檔（git 追蹤 + logs/llm + logs/ops + rehearsal + submissions + settlement）：**0 findings**；`.env` 未追蹤且在 .gitignore；四個 API key 環境變數皆 ABSENT。發現時只輸出檔案 / 行號 / 類型 / 遮罩值（測試確認完整 secret 不會出現在報告）。

## 18. Audit completeness
`audit/COMPLETENESS.json`：architecture、strategy freeze、prompts、configs、git SHA、daily runs、settlement ledger、reconciliation、D-Plan packages、FINAL freeze、receipt schema、archive manifests 驗證。
- 24 日彩排根目錄：**12/12 PASS**。
- 正式根目錄：11/12（`settlement_ledger` 缺：尚未有真實比賽日的內部結算，屬預期）。

## 19. Real LLM status
**REAL_LLM_STATUS = BLOCKED_NO_API_KEY**（GEMINI / GOOGLE / OPENAI / ANTHROPIC：process、User、Machine、`.env` 皆 ABSENT）。本輪未做任何 LLM replay；比賽維持 Template 敘事。設定步驟：`docs/REAL_LLM_SETUP.md`。

## 20. Remaining NC rules
未建立 `docs/ORGANIZER_CLARIFICATIONS.md` / `config/organizer_clarifications.yaml`（沒有主辦方回覆；adapter 預設全部 `unknown` → ASSUMPTION，範例：`templates/organizer_clarifications.example.yaml`）。
NC-1（結算 / 提交）、NC-2、NC-3、NC-4、NC-5、NC-6、NC-7、NC-8、NC-9（賽中改程式）、NC-10（同日多次提交）、NC-15（首日）、C12。
**新增待確認**：送件窗口「前一日 19:30」是日曆日或交易日（週一 D-Plan 的開窗時間）；比賽期間 TWSE 休市日（需官方日期填 `market_holidays`）。

## 21. Readiness（`agent/ops/readiness.py` → `reports/round06_readiness.json`）
**DRY_RUN_READY**。DEV_READY / DRY_RUN_READY 條件全數通過（tests、baseline、24 日彩排含 competition 模式、soak、資安、故障注入 17/17）；COMPETITION_READY 條件中「關鍵來源可靠」「最新真實 preflight 非 BLOCK」已通過，未過：NC-1 結算路徑、NC-1 提交路徑、NC-15。逐項：`reports/COMPETITION_READINESS_CHECKLIST.md`（v2，保留 Round 05 判斷）。

## 22. Recommended release SHA
**`83af462`**（`reports/ROUND_06_RELEASE_CANDIDATE.md`；`verify_release --smoke` PASS）。未建立 tag。
