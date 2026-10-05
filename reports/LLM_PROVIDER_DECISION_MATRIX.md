# LLM Provider Decision Matrix（Round 06A，2026-10-05）

> 只用於 **敘事文字**（market_view.logic / inference logic / counter_evidence）。投資決策永遠由 Quant Core v1 決定，任何 provider 都不能改變。
> AI 產生內容，需人工審閱。

| 項目 | Template（現行） | Claude Agent SDK | Anthropic API（Messages） | Gemini API |
|---|---|---|---|---|
| 需要 API key | 否 | **是**（ANTHROPIC_API_KEY；官方要求 SDK agent 用 API key） | 是 | 是（GEMINI / GOOGLE_API_KEY） |
| 可沿用 Claude Code 登入 | — | **否**（官方：SDK 建置的 agent 不得用 claude.ai 登入；provider 以 `--bare` 結構性排除） | 否 | 否 |
| 可沿用 Claude Code 訂閱額度 | — | **否** | 否 | 否 |
| 計費清晰度 | 無成本 | 清楚：Console 依 token；SDK 回報 `total_cost_usd` + `max_budget_usd` 硬上限 | 清楚：依 token（回應含 usage） | 清楚；**比賽提供 Google Token Credit**（需完成課程 / 兌換，見 `docs/REAL_LLM_SETUP.md`） |
| 結構化輸出 | 決定性 | 原生 JSON Schema（`--json-schema`）+ 我們的 pydantic / grounding | API structured outputs + 我們的驗證 | `responseMimeType=application/json` + 我們的驗證 |
| 工具控制 | 無工具 | 需主動鎖定（預設有 Bash / 讀寫檔 / 網路 / 載入 `~/.claude` 設定）；已鎖定並驗證指令列 | 無工具（除非自行提供） | 無工具（除非自行提供） |
| 檔案系統隔離 | 不適用 | 需沙箱 cwd + 空 config dir（已實作） | 不接觸檔案系統 | 不接觸檔案系統 |
| Replay | 完全決定性 | 有（LLMClient 記錄 + ReplayProvider） | 有（同一套） | 有（同一套） |
| 可稽核性 | 最高 | 高（版本、usage、session、無憑證） | 高 | 高 |
| 延遲 | ~0 | 高：每次另加 5–12 s CLI 啟動（實測） | 低（單一 HTTPS 請求；未實測） | 低（未實測） |
| 營運複雜度 | 最低 | 最高：Python SDK + 原生 CLI（Windows 無 wheel）+ 版本釘選 + 子程序清理 | 低（既有 REST adapter） | 低（既有 REST adapter） |
| 現況 | 運作中，全部測試 | 已實作、預設停用、**AUTH_BLOCKED_NO_API_KEY** | adapter 已有、未實測（無 key） | adapter 已有、未實測（無 key） |
| 比賽適用性 | **最高** | 低（為一段文字引入 agent runtime） | 中（需付費 key） | 中（有比賽 credit；需完成資格審查） |

## 推薦
**D. KEEP_TEMPLATE**（主推薦，比賽使用）。

附註（非主推薦）：
- **SDK_OPTIONAL**：Claude Agent SDK provider 保留為可選能力，取得 Anthropic API key 並通過 `docs` / 報告列出的資格測試前不啟用；即使通過也只建議作為選項，不作預設。
- 若未來想用真實 LLM 敘事，優先順序：**Gemini API（比賽 credit）≈ Anthropic API（直接呼叫）> Claude Agent SDK**——敘事只需單次文字生成，Agent SDK 的 agent loop / 工具在此是需要額外鎖住的風險面，且多出啟動延遲。

## Round 06B 補充：Claude Code CLI（本人登入，`claude -p`）
| 項目 | Claude Code CLI runtime |
|---|---|
| 需要 API key | 否（使用本人 claude.ai 登入；本機為 Team 組織帳號） |
| 官方支援程度 | 個人 / scripted 使用：SUPPORTED；比賽使用：UNCLEAR；替他人提供：NOT_SUPPORTED |
| 實測 | 20/20 schema、grounding 100%、0 工具違規、0 session 洩漏、3 / 15 日 replay 決策 100% 不變、Replay 完全重現 |
| 延遲 | p50 約 12–21 s / 次、thesis 最長 68 s（每日約 40–90 s） |
| 狀態 | 已實作、`--llm-provider claude-cli` 選用；預設 Template |
| 推薦 | **CLAUDE_CLI_EXPERIMENTAL_ONLY**（需公司授權 + 比賽使用 UNCLEAR） |
詳見 `reports/ROUND_06B_CLAUDE_CLI_RUNTIME_REPORT.md`。
