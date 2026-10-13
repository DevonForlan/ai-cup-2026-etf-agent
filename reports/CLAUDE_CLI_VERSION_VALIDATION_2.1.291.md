# Claude Code CLI 版本驗證 — 2.1.291（維護更新，非新 Round）

> AI 產生內容，需人工審閱。Round 07 RC `4742d5a` 保留不變；本文件只把 2.1.291 加入已驗證版本。

## 結論
**2.1.291 has passed:** auth、structured smoke、grounding、full regression suite → 列為 validated version。
已驗證版本：`2.1.289`（Round 06B / Round 07 歷史紀錄，保留相容）、**`2.1.291`（目前驗證版本）**。
這**不代表**未來版本都支援：其他版本（例如 2.1.292+）仍顯示 `WARNING_VERSION_DRIFT`（不阻擋；Claude 失敗 → Template）。

## 1. Claude Code version
| 時間 | 版本 | 來源 |
|---|---|---|
| 2026-10-07 09:25 | **2.1.291** | 使用者手動執行 `round07_regression.py`（`experiments/claude_cli_runtime/results/round07_regression_2.1.291.json`） |
| 2026-10-13 09:4x | 2.1.296 | 本次維護時本機 `claude --version`（已自動更新；**未驗證**，preflight 顯示 `WARNING_VERSION_DRIFT`） |

## 2. Auth status（白名單四欄）
`loggedIn=true`、`authMethod=claude.ai`、`subscriptionType=team`、`apiProvider=firstParty`（2026-10-07 與 2026-10-13 相同）。

## 3–8. round07_regression 結果（2.1.291，2026-10-07）
| 項目 | 結果 |
|---|---|
| LLM 狀態 | `LLM: PRIMARY=claude-cli STATUS=READY FALLBACK=template` |
| version_check（當時） | `WARNING_VERSION_DRIFT`（當時只列 2.1.289）→ 本次更新後為 `VERSION_VALIDATED` |
| smoke latency | **32.1 s** |
| docs | **8** |
| accepted | **5** |
| rejected | **0** |
| calls | **1** |
| 任務 | `mops_research`（NARRATIVE_LOCKED：無工具、無 session、sandbox cwd；結構化 JSON schema 輸出；grounding 全數通過） |

## 9. Full pytest
`.venv\Scripts\python.exe -m pytest -o addopts="" -q` → **419 passed, 0 failed, 270.86 s**（Round 07 417 + 版本政策測試 2）。
涵蓋：結構化輸出解析、工具違規偵測（無 shell / 無寫入）、sandbox（不接觸 repo）、`--no-session-persistence`、grounding、逾時 → 終止程序樹 → Template、CLI 不存在 → DEGRADED。

## 10. Quant unchanged
- `config/strategy_quant_v1.yaml`、`agent/portfolio`、`agent/features`、`agent/engine`、`agent/risk`、`agent/sim`、`agent/dplan/validator.py`、`agent/ops/settle_internal.py`：與 `83af462`、`4742d5a` diff **0 檔**。
- strategy sha256 = `f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0` = `config/ops.yaml freeze.strategy_sha256`。
- W5 baseline（NAV 1,014,240,575.839861741934859718、24/24 decision_core_hash）與 Round 07 相同；本次變更只觸及版本檢查標籤與設定，不在決策路徑上。

## 11. Real-data dry-run（PRECOMPETITION_REAL_DATA_DRY_RUN）— 本次未通過，原因為資料來源
- 2026-10-13 09:45 真實 refresh：價量 / 法人（至 10-12）OK；`etf_holdings` STALE。
- `competition_day --date 2026-10-13 --mode historical --competition-profile prod --initial --clock 2026-10-12T20:00:00+08:00` → **BLOCKED**：`etf_holdings_freshness: 30 ETFs; oldest latest-date 2026-10-02 (11 days)`（規則：> 10 天 BLOCK，為 Active Share 安全規則，**未放寬**）。
- 原因：中信投信 00983A（10-02）、00995A / 00406A（10-05）公開 API 回應 `ResultCode=1`「Token 無效或過期，請重新開啟網頁」（白天；Round 07 夜間可正常取得）。未嘗試繞過或推測其他 endpoint。
- Claude 未被呼叫（BLOCK 發生在量化與敘事之前）；當時 LLM 狀態 `READY`，版本 2.1.296 → `WARNING_VERSION_DRIFT`。
- 待辦：今晚 19:30 後（10-14 送件窗口，真實時鐘）重跑；需 CTBC 恢復。

## 12. Production recommendation
- **2.1.291：VALIDATED**，維持 CLAUDE_CLI_PRODUCTION_CANDIDATE（primary claude-cli、fallback template）。
- 本機目前為 **2.1.296（未驗證）**：可照常使用（漂移只警告），但比賽前應對 2.1.296 重跑 `round07_regression.py`（1 auth + 1 smoke）+ full pytest 後再加入 `supported_versions`；或關閉 CLI 自動更新以固定版本。
- Readiness 不變：DRY_RUN_READY（NC-1 / NC-15 未確認）。
