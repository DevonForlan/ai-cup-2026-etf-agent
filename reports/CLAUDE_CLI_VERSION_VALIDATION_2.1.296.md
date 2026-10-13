# Claude Code CLI 版本驗證 — 2.1.296（2026-10-13）

> AI 產生內容，需人工審閱。維護作業：只把 2.1.296 加入已驗證版本，runtime 架構不變（NARRATIVE_LOCKED、primary claude-cli、fallback template）。

**2.1.296 has passed:** auth、structured smoke、grounding、Template fallback / decision invariance（測試）、full regression suite、真實資料完整 dry-run（排程情境與手動）。
這**不代表**未來版本都支援；其他版本（例如 2.1.297+）仍顯示 `WARNING_VERSION_DRIFT`（不阻擋）。
已驗證版本：`2.1.289`（歷史）、`2.1.291`（2026-10-07）、**`2.1.296`（2026-10-13，目前本機版本）**。

| 項目 | 結果 |
|---|---|
| `claude --version` | 2.1.296 (Claude Code)，native |
| auth（白名單四欄） | loggedIn=true、authMethod=claude.ai、subscriptionType=team、apiProvider=firstParty → READY |
| round07_regression（1 auth + 1 structured `mops_research`） | 2026-10-13 21:54：docs 3、accepted 3、rejected 0、calls 1、failed 0、latency 13.6 s（`experiments/claude_cli_runtime/results/round07_regression_2.1.296.json`） |
| 排程情境（Task Scheduler `AI_CUP_Precompetition_DryRun_1930`，21:24） | 完整真實 dry-run PASS：Claude READY、grounding PASS、D-Plan v4.3 PASS |
| 手動真實 dry-run（交易日 2026-10-14，22:02） | DRY_RUN_OK、L0；Claude 3 次呼叫 0 失敗、研究推論 3（grounding 全過）；官方 Active Share 41.10%；每日合規摘要全 PASS |
| decision invariance | 2026-10-14 真實資料：Claude 與 Template decision_core_hash 相同（`sha256:eee42d45…`）；W5 24/24 日與 baseline 相同 |
| Template fallback | 測試：CLI 不存在 / 未登入 / 逾時 / bad JSON / usage limit / 工具違規 → Template，D-Plan 照常（tests/llm、tests/ops/test_round07.py） |
| full pytest | 449 passed, 0 failed（168 s） |
| 安全 | 未讀取 token / cookie / credential；只讀 `claude auth status` 四欄 |
