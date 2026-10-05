# Round 07 Release Candidate（2026-10-05）

> AI 產生內容，需人工審閱。未建立 git tag。

| 項目 | 值 |
|---|---|
| **新 RC（PRODUCTION_CANDIDATE）** | **`4742d5a`** |
| 前一個 RC（Round 06，保留為參考，歷史未覆寫） | `83af462`（DRY_RUN_READY） |
| Round 06B 範圍 | `01bfba3`..`08769f5`（CLAUDE_CLI_EXPERIMENTAL_ONLY） |
| Round 07 commits | `dd98f4a` calendar · `c4fdcb5` CTBC 錯誤回報 · `ccc3fc7` 矛盾 gate · `635034a` FINAL 模式優先序 · `ee120ed` MOPS 研究 · `fb97dc5` Claude CLI production wiring · `f5c5072` 真實 CLI 回歸 · `e6929fd` docs · `4742d5a` readiness / release |
| Quant 修改 | **否**：`config/strategy_quant_v1.yaml`、`agent/portfolio`、`agent/features`、`agent/engine`、`agent/risk`、`agent/sim`、`agent/dplan/validator.py` 與 `83af462` 的 diff 為空 |
| 決策不變 | W5 replay NAV 1,014,240,575.839861741934859718 = baseline；24/24 日 decision_core_hash = Round 06；真實 2026-10-06 Claude = Template（`sha256:732a92f2…`） |
| LLM | Primary：Claude Code CLI 2.1.289（`--competition-profile prod`，NARRATIVE_LOCKED）；Fallback：Template（永久） |
| 授權 | AUTHORIZED_FOR_COMPETITION_USE — organization-managed Team account authorized by employer for company competition participation |
| Readiness | **DRY_RUN_READY**（語意不變）；`llm_runtime = CLAUDE_CLI_PRODUCTION_CANDIDATE` |
| Blockers（COMPETITION_READY） | NC-1 結算、NC-1 提交、NC-15 第一個比賽交易日（皆待主辦方） |
| Open NCs | NC-1（結算 / 提交）、NC-2、NC-3、NC-9、NC-10、NC-15（其餘不變，見 `docs/OPEN_NC_LIST.md`） |
| Tests | 417 passed / 0 failed（Round 06B 386 + Round 07 新增 31） |
| 真實 dry-run（RC） | `git:4742d5a` 2026-10-06 dry-run（真實時鐘、送件窗口內）：DRY_RUN_OK、L0、validation PASS、Claude 3 次 0 失敗、研究推論 4、decision_core_hash `732a92f2…` = Template |
| Security | `security_scan.py` PASS（3,939 檔）；補充掃描 0 token / cookie / OAuth / API key；既有 LOW 發現見正式報告 §18 |

每日指令：`docs/DAILY_COMMANDS.md`。詳細：`reports/ROUND_07_PRODUCTION_CANDIDATE_REPORT.md`。
