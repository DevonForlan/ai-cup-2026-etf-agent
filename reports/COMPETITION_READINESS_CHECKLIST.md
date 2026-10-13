# Competition Readiness Checklist（2026-10-05，Round 05）

> AI 產生內容，需人工審閱。等級：**PASS** 已完成並驗證｜**WARN** 可用但有已知限制｜**BLOCKED** 未能完成或受外部條件阻擋。

## 總評：**DRY_RUN_READY**

| 等級 | 定義 | 狀態 |
|---|---|---|
| DEV_READY | 測試全過、baseline 不變、核心模組完成 | ✅ |
| DRY_RUN_READY | 一鍵流程可在演練中產生合法送件包；故障注入與截止保護驗證；手冊完成 | ✅ |
| COMPETITION_READY | 另需：正式提交與結算取得方式確認（NC-1）、真實窗口 competition 模式演練、首日確認 | ❌（NC-1 未確認 → 最高 DRY_RUN_READY） |

## 逐項

| # | 項目 | 等級 | 依據 / 說明 |
|---|---|---|---|
| 1 | Quant Core v1 | PASS | 凍結 `f4dfb66`，hash 檢查；W1–W5 replay 不變 |
| 2 | Competition Engine / Validator | PASS | 267 tests；D-Plan v4.2 schema + C-checks |
| 3 | NAV simulator | PASS | W5 NAV 1,014,240,575.84 與 Round 04 相同 |
| 4 | D-Plan 產生 | PASS | dry run A 與 baseline 委託相同 |
| 5 | 前日組合不合法時的處理（現金漂移） | PASS | `d6a45ca` 修正 + regression test |
| 6 | 資料：TWSE / TPEx 行情 | PASS | dry run B 實抓 OK；失敗 → BLOCK |
| 7 | 資料：法人 | PASS | 實抓 OK |
| 8 | 資料：ETF 持股 | WARN | 27/30 當日快照成功；3 檔當下回空（用前次資料）；5 檔發行商只提供最新日 → 必須每日抓；端點非官方文件化 |
| 9 | 資料：公司行動 | PASS | 實抓 OK |
| 10 | 資料：MOPS 營收 first_seen | PASS | append-only 帳 + PIT 過濾；時間戳 bug 已修並更正 |
| 11 | 資料：重大訊息、夜盤、美股、SOX、TSM、匯率 | WARN | 實抓 OK；Yahoo 非官方 API（OPTIONAL，失敗不阻擋） |
| 12 | 資料健康報告 | PASS | `logs/ops/<T>/data_health.json/.md` |
| 13 | Settlement：內部帳 | PASS | `settle_internal.py`；E2E 兩日測試 |
| 14 | Settlement：主辦方帳取得 | BLOCKED | NC-1：無公告方式；目前只能人工抄錄 JSON/CSV |
| 15 | Reconciliation | PASS | MATCH/MINOR/BLOCK + 人工 accept-official；不自動選邊 |
| 16 | Preflight | PASS | 20 項；competition 模式 BLOCK 規則經測試 |
| 17 | Deadline guard | PASS | dry run C 五階段 |
| 18 | Safe degradation L0–L3 | PASS | 每層需 validator PASS；L3 不假設合法 |
| 19 | LLM narrative（real） | BLOCKED | 無 API key；需使用者依 `docs/REAL_LLM_SETUP.md` 設定 |
| 20 | LLM 失敗回退 | PASS | timeout / 429 / invalid JSON → Template，D-Plan PASS |
| 21 | competition_day 一鍵流程 | PASS | A/B/C dry run；永不上傳 |
| 22 | Submission package | PASS | 全部必要檔 + manifest；不可覆寫 |
| 23 | FINAL_CANDIDATE | PASS | 唯一、醒目、錯隊名/日期/hash/驗證失敗拒絕；DRY-RUN 不顯示 upload |
| 24 | Archive | PASS | 唯讀、拒絕覆寫、manifest hash |
| 25 | Audit | PASS | `audit/` 索引（6 runs） |
| 26 | Healthcheck | PASS | HEALTHY/DEGRADED/BLOCKED 經測試 |
| 27 | Runbooks | PASS | 每日 / 緊急 / 凍結 / 自主性 / LLM 設定 |
| 28 | PowerShell 腳本 | PASS | 解析 0 錯誤、無 exit、未建排程 |
| 29 | Submission mechanism（上傳） | BLOCKED | NC-1 未公告；人工上傳 FINAL 檔 |
| 30 | 真實窗口演練（19:30–08:55，competition 模式） | WARN | 尚未進行；建議 10/26 前至少兩晚實跑（dry-run 模式） |
| 31 | Organizer unknowns | WARN | NC-1…NC-10、NC-15、C12 未確認（見報告 §18） |
| 32 | 首個交易日 | WARN | NC-15：10/26 或 10/27；`-Initial` 參數已備 |

---

# Checklist v2 — Round 06（2026-10-05）

> 上方 Round 05 判斷**保留不改**（歷史紀錄）。本節為 Round 06 重新評估。自動評分：`agent/ops/readiness.py` → `reports/round06_readiness.json`。

## 總評：**DRY_RUN_READY**（不變；NC-1 未確認 → 最高 DRY_RUN_READY）

## 逐項（Round 06）

| # | 項目 | R05 | R06 | 依據 |
|---|---|---|---|---|
| 1 | Quant Core v1（凍結） | PASS | PASS | hash = freeze；Round 06 決策路徑 0 行修改 |
| 2 | Competition Engine / Validator | PASS | PASS | 324 tests |
| 3 | NAV / ledger continuity | PASS | PASS | 24 日彩排每日 T 結算 = T+1 起點（持股 / 現金 / NAV / 股利 / agent_state / entry_date） |
| 4 | 24-day full dress rehearsal | — | **PASS** | replay 24/24（NAV 逐日 = baseline）；clock-sim（competition 模式）24/24 |
| 5 | 資料：TWSE / TPEx 行情 | PASS | PASS | 休市感知新鮮度（修正）；斷網時 store 已有 T-1 → CACHED，否則 BLOCK |
| 6 | 資料：ETF 持股 | WARN | WARN | 27/30 最新；中信 3 檔 STALE_FALLBACK（發行商端回空）；並行 3 workers |
| 7 | 資料：MOPS / 美股 / 夜盤 | WARN | WARN | OPTIONAL；MOPS 未來日查詢修正 |
| 8 | 官方結算取得 | BLOCKED | BLOCKED | NC-1；人工 SOP + 雙重輸入 + 確認閘門已就緒 |
| 9 | 官方結算人工輸入 SOP | — | PASS | `settlement_entry.py` + SOP 文件 + 測試 |
| 10 | Reconciliation | PASS | PASS | 24 日彩排每日 MATCH |
| 11 | Preflight | PASS | PASS | + clock skew、settlement_confirmed、ETF 新鮮度 PIT 修正 |
| 12 | Deadline guard | PASS | PASS | 19:30→08:56 全時鐘測試；08:56 不產 FINAL |
| 13 | Submission package | PASS | PASS | .partial 原子化；crash 不留壞檔 |
| 14 | FINAL_CANDIDATE | PASS | PASS | 凍結 + replace-final（人名 + 理由）；他隊 FINAL 不顯示（修正） |
| 15 | Submission adapter / state machine | — | PASS（介面） | Manual only；submit() 拋出 OfficialSubmissionUnavailable；回執模型 |
| 16 | Submission mechanism（實際上傳） | BLOCKED | BLOCKED | NC-1 |
| 17 | Decision fingerprint / candidate compare | — | PASS | 同輸入同指紋；6 類差異分類 |
| 18 | Archive | PASS | PASS | .partial 原子化、驗證 |
| 19 | Audit | PASS | PASS | `audit/COMPLETENESS.json` 12/12（rehearsal） |
| 20 | Soak | — | PASS | 100 次，0 例外、0 損毀、記憶體 +8 MB、handles 穩定 |
| 21 | Crash / lock recovery | — | PASS | 5 個中斷點 + 刷新中斷；pid 感知鎖回收 |
| 22 | Backup / restore drill | — | PASS | 乾淨 worktree + 還原 → 下一交易日 READY_TO_SUBMIT、對帳 MATCH |
| 23 | Network degraded | — | PASS | 實際資料：T-1 已存 → L2；T-1 缺 → BLOCK |
| 24 | Security scan | — | PASS | 0 findings |
| 25 | Release verification | — | PASS | `verify_release` + 暫存 worktree smoke |
| 26 | LLM narrative（real） | BLOCKED | BLOCKED | 無 API key |
| 27 | Organizer rules | WARN | WARN | NC-1…NC-10、NC-15、C12 未確認；新增疑點：送件窗口「前一日」= 日曆日或交易日 |
| 28 | 真實窗口 competition 演練 | WARN | WARN | 尚未在真實 19:30–08:55 以真實結算跑 |

## Round 05 → Round 06 delta
- 新增 PASS：24 日彩排、結算 SOP、提交介面 / 狀態機、指紋 / 比對、soak、crash / lock 恢復、備份還原、斷網、資安掃描、發版驗證。
- Round 06 修正的真問題：休市造成假 STALE BLOCK、ETF 新鮮度使用未來資料（replay）、MOPS 未來日重試浪費 157 s、他隊 FINAL 被顯示 / 保留。
- 等級不變：DRY_RUN_READY（阻擋項皆為外部：NC-1、真實 LLM key、首日 NC-15）。

## 2026-10-13 官方規則同步
- [x] 官網新版附件下載與比對（`research/official_updates/OFFICIAL_UPDATE_INDEX.md`）
- [x] D-Plan runtime 升級為官方 v4.3（`research/official_updates/DPLAN_VERSION_DIFF.md`）
- [x] Active Share 官方規則：前 15 大聯集、占 NAV、含現金（benchmark 現金 NEED_CONFIRMATION）、門檻 15%；內部安全目標 30% 另列
- [x] 首個交易日 2026-10-27、首次繳交窗口 10/26 19:30～10/27 08:55（NC-15 RESOLVED）
- [x] 重繳：08:55 前最後一次成功提交生效（NC-10 RESOLVED）；每日 25 次上限
- [x] DataPack 匯入（`agent/ops/datapack.py`）— 結算來源 NC-1（結算部分）RESOLVED
- [ ] NC-1 提交：平台上傳頁面 / 回執格式需登入後確認
- [ ] NC-3：C12 / C14 / 時間戳處置待主辦方說明
- [ ] 中信投信 ETF 持股（00983A / 00995A / 00406A）恢復更新（目前觸發 ETF 新鮮度 BLOCK）
- Readiness：DRY_RUN_READY（不變）
