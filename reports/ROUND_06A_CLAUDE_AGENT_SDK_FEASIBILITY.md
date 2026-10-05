# ROUND 06A — Claude Agent SDK Feasibility (Narrative Provider Spike)

日期：2026-10-05　｜　起點 `7b7eb20`（release candidate `83af462` 未修改）　｜　依公司政策：AI 產生內容，需人工審閱。

## 1. Executive conclusion
- **AUTH_B**：依 Anthropic 官方文件，以 Agent SDK 建置的 agent 必須使用 **API key 驗證**（Claude Console key 或支援的雲端供應商），**不可**使用 claude.ai / Claude Code 訂閱登入。
- 現況 `ANTHROPIC_API_KEY` 不存在 → **TECHNICALLY_SUPPORTED / AUTH_BLOCKED_NO_API_KEY**：SDK 安裝、匯入、與原生 CLI 的串接、最小權限設定、隔離、逾時 / 清理、fallback、replay 皆已在本機驗證；**沒有任何真實 Claude 回應**，因此真實品質 / 延遲 / 用量 / 15 日 replay 全數 BLOCKED。
- **Claude Code 登入沿用：NOT OFFICIALLY SUPPORTED（對 SDK 建置的 agent）**，本輪依你的規則（只允許官方支援方式）**刻意未嘗試**；provider 以 `--bare` + 空的 `CLAUDE_CONFIG_DIR` 從結構上讓訂閱登入不可觸及，並以實際執行驗證（見 §6）。
- 決策：**KEEP_TEMPLATE**（比賽主推薦）；Claude Agent SDK = **SDK_OPTIONAL**（provider 已就緒、預設停用，需 API key + 資格驗證後才可選用）；**不建議**本輪接入 `competition_day.py`。
- Readiness 不變：**DRY_RUN_READY**（LLM 為 OPTIONAL_CAPABILITY，不是 COMPETITION_READY 條件）。

## 2. SDK package / version
`claude-agent-sdk` **0.2.163**（PyPI 最新；Python ≥3.10；MIT，使用受 Anthropic Commercial Terms 規範）。只安裝在專案 `.venv`，新增 17 個相依套件、**未升級任何既有套件**（安裝前後 `pip freeze` diff 只有新增）。可選需求檔：`requirements-llm-sdk.txt`（未改動 `requirements-lock.txt`）。
PyPI 只有 macOS / Linux wheel（內含 CLI）；**Windows 安裝的是 sdist，不含 CLI**，需本機原生 Claude Code CLI。

## 3. Claude Code version
`2.1.289 (Claude Code)`（npm 安裝；原生 `claude.exe` 位於 `%APPDATA%\npm\node_modules\@anthropic-ai\claude-code\bin\`）。

## 4. Python / Windows
Python 3.13.16、pip 26.2.1、Windows 11、中文路徑（`…\個人\AI CUP 2026玉山…`）：SDK 啟動 CLI、編碼、路徑、子程序、逾時、清理皆正常。
**Windows 發現**：SDK 預設找到 npm 的 `claude.CMD` shim 並**拒絕執行**（SDK 對 .cmd/.bat 的防護）；provider 改為自動指向 shim 旁的原生 `claude.exe`（`cli_path: auto`）。

## 5. Authentication
官方依據（原文）：
- Agent SDK overview：「Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK. Use the API key authentication methods described in the Quickstart instead.」
- Legal and compliance：「**Developers** building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider.」
- Authentication（CLI 憑證優先序）：雲端供應商 → `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY`（非互動模式一律使用）→ `apiKeyHelper` → `CLAUDE_CODE_OAUTH_TOKEN` → profile → `/login` 訂閱 OAuth。`apiKeyHelper` / `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` 適用於包含 Agent SDK 在內所有包裝 CLI 的介面。
- `claude --help`：`--bare` 時「Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper」（不讀 OAuth / keychain）。
**分類：AUTH_B**（技術上 CLI 有訂閱登入的退路，但官方對 SDK 建置的 agent 只允許 API key；我們的 provider 也在結構上排除了訂閱路徑）。

## 6. Claude Code auth reuse
**CLAUDE_CODE_AUTH_REUSE = NOT_OFFICIALLY_SUPPORTED（for agents built on the Agent SDK）**；未以「剛好能跑」方式測試（不違反官方指引、不讀任何憑證檔）。
實測隔離（`experiments/claude_agent_sdk/auth_probe.py`）：真實 SDK + 真實 CLI、`--bare`、空 `CLAUDE_CONFIG_DIR`、無 key → `Not logged in · Please run /login` → 映射為 `LLMUnavailable`（→ Template）；**subscription_login_reachable = False**；無殘留程序。

## 7. Subscription reuse
不沿用。官方：Pro / Max 的用量額度假設為「ordinary, individual usage of Claude Code and the Agent SDK」，但對**建置 agent / 產品**的開發者要求 API key。另外本機的 Claude Code 登入屬於**公司組織帳號**，用於個人競賽另涉公司政策，需由你與公司確認（非技術問題）。

## 8. Billing / quota
- 我們採用的路徑（API key）：**B — Anthropic API billing**（Claude Console 依 token 計費）；SDK 每次回傳 `total_cost_usd`、`usage`、`model_usage`（另以 `max_budget_usd` 設每次硬上限）。
- 訂閱登入路徑（未採用）：會計入該訂閱方案的用量限制（A），不適用於本 agent。
- 不存在另一套獨立的「Agent SDK quota」（C）——SDK 只是執行 Claude Code 二進位檔，驗證與計費跟隨所用憑證。
**Authentication 與 billing 分開判定：驗證 = API key（AUTH_B）；計費 = Anthropic API（B）。**

## 9. Official support evidence
code.claude.com/docs/en/agent-sdk/overview、…/agent-sdk/python、…/agent-sdk/permissions、…/agent-sdk/structured-outputs、…/authentication、…/legal-and-compliance；pypi.org/project/claude-agent-sdk（0.2.163 metadata）；本機 `claude --help`、SDK 原始碼（`subprocess_cli.py` 指令組裝與環境變數合併）。未使用第三方部落格作為依據。

## 10. Structured output
SDK 原生支援（`output_format={"type":"json_schema"}` → CLI `--json-schema`，驗證失敗自動重提示，`ResultMessage.structured_output`）。provider 依任務自動帶入既有 pydantic schema（NarrativeOut / ThesisOut / ReviewOut / EventsOut），再經 LLMClient 的 pydantic + grounding 驗證（不只靠 prompt）。**真實 20 次 pass rate：BLOCKED（無 key）**。
未驗證風險：結構化輸出是否需要內部工具；因此 deny 清單逐一列名而非 `"*"`，留待有 key 時實測。

## 11. Tool permissions
CLI 指令實測組裝（`shell_test.py` 靜態檢查）：`--tools ""`（無任何內建工具）、`--disallowedTools Bash,PowerShell,Read,Write,Edit,WebFetch,WebSearch,Task,Agent,…,mcp__*`、`--permission-mode dontAsk`（任何需核准的呼叫直接拒絕、不呼叫 callback）、`--strict-mcp-config`（無 MCP）、`--setting-sources=`（不載入 `~/.claude` 與專案設定——**SDK 預設會載入**，已明確關閉）、`--bare`、`--no-session-persistence`；另有 deny-all `PreToolUse` hook 記錄任何嘗試，任何工具請求 → 該輸出整份拒絕（TOOL_VIOLATION → Template）。
**真實「請執行 dir / git status / 改策略 / 讀 .env / 列 root」測試：BLOCKED（無 key）**；腳本已備（`permissions_test.py`）。

## 12. Filesystem isolation
每次呼叫建立 `runtime/claude_agent_sdk/<run>/`，只含 `facts.json`、`schema.json`、`prompt_meta.json` 與空的 `.cfg`（CLAUDE_CONFIG_DIR）；cwd = 沙箱（≠ 專案根）、`add_dirs=[]`、無設定來源；呼叫後刪除（Windows 檔案鎖以重試刪除，實測 0 殘留）。沒有工具即無法讀檔；真實讀檔測試 BLOCKED。

## 13. Shell denial
同 §11：`Bash` / `PowerShell` 不在工具集中且列入 deny；真實 marker-file 測試 BLOCKED（`shell_test.py`）。

## 14. Prompt injection
防線：guard prompt（`agent/llm/prompts/claude_agent_narrative_v1.txt`：只是 Narrative Agent、事實文字是資料不是指令）＋無工具＋ LLMClient grounding / reviewer。測試（fake SDK）：模型若照注入內容回答（改 2330 權重、讀 .env、引用不存在的 F9）→ 驗證拒絕 → Template。真實模型測試 BLOCKED。

## 15. Hallucination
既有 grounding：敘事中的每個數字必須出現在輸入；新 ticker、未知 fact id 會被拒絕（測試：「+15%」、「2330 權重 25%」被拒）。真實模型測試 BLOCKED（`prompt_injection_test.py` 含數字與 ticker 案例）。

## 16. Replay
SDK 回應經既有 `LLMClient` 記錄（timestamp、provider、model、prompt_version、prompt_hash、response、parsed_output、usage、latency、status，`provider_meta` 含 SDK / CLI 版本、auth mode、input hash、session、cost）；**不含任何憑證**（測試：假 key 不出現在 log / argv / meta）。`ReplayProvider` 重播 SDK 紀錄 → 敘事完全相同（測試）。

## 17. Timeout / cleanup
實測（真實 CLI、無憑證）：3 s 逾時 → `LLMTimeout`（含 CLI 終止共 6–10 s）、`claude.exe` 程序數前後相同（無孤兒）、沙箱 0 殘留。設定：每次 60 s、`retries: 0`、每日 `total_budget_sec: 150`（最壞情況不吃掉截止時間；比賽截止前 15 分鐘本來就不呼叫 LLM）。

## 18. Latency
真實模型延遲：**BLOCKED**。僅測得鎖定 CLI 無憑證往返（啟動 → 驗證失敗）：4.4–11.9 s（中位 5.6 s；主機負載時約 11.7 s）——即每次呼叫的固定啟動成本。

## 19. Usage
SDK 宣告並回傳：`usage`（input / output / cache tokens）、`model_usage`（每模型，含 `costUSD`）、`total_cost_usd`、`duration_ms`、`num_turns`。實際數值：BLOCKED。

## 20. 3-day smoke
真實：**BLOCKED**。Harness self-test（真實 provider 程式路徑 + 假 SDK 傳輸，由決定性 mock 回答，**非 Claude 輸出**；W5 真實資料）：3/3 決策不變、D-Plan 100% PASS、numeric grounding 100%、fallback 0。

## 21. 15-day replay
真實：**BLOCKED**。Harness self-test：15/15 決策不變、D-Plan 100%、grounding 100%、fallback 0。

## 22. Decision invariance
pytest（fixture）與 self-test（W5）：Template vs SDK 敘事——portfolio、orders、cash、Active Share、regime / stance / posture、decision core hash 皆相同；SDK 失敗（逾時、CLI 缺失、JSON 錯誤、工具違規）→ Template，決策仍相同、D-Plan PASS。

## 23. D-Plan validation
上述所有情境 100% PASS。

## 24. Security scan
3,757 檔（含 `experiments/`、`runtime/`、`reports/human_review_sdk/`、logs）：**0 findings**；四個 API key 環境變數皆 ABSENT；未讀取 / 輸出任何 Claude Code 憑證。

## 25. Operational suitability
| 面向 | 評估 |
|---|---|
| 正確性 / 安全 | 最小權限可在設定層完全鎖定（無工具、無設定、無 MCP、隔離 cwd、API-key-only），並以實際 CLI 指令與隔離測試驗證 |
| 延遲 | 每次 5–12 s 的 CLI 啟動固定成本，高於直接 Messages API |
| 依賴 | Windows 需原生 Claude Code CLI（SDK sdist 不含）；CLI 版本更新可能改變行為 → 需釘版 |
| 複雜度 | 比直接 API 多一層（子程序、CLI 設定、版本檢查）；對「只產生一段文字」的用途而言 agent 能力全部用不到 |
| 成本 | 需付費 API key（Console）；比賽提供的是 **Google** Token Credit，不涵蓋 Anthropic |

## 26. Recommendation
**主推薦：KEEP_TEMPLATE**（決定性、零成本、零延遲、可完全重播；比賽計分不依賴敘事文字品質）。
**Claude Agent SDK：SDK_OPTIONAL**——provider 已實作、測試、預設停用；若日後取得 Anthropic API key：依序跑 `auth_probe → smoke → structured_output (20) → permissions → prompt_injection → narrative_replay --days 3 → --days 15`，全數符合資格標準（structured 100%、grounding 100%、決策不變 100%、工具違規 0、憑證外洩 0）才考慮在 `competition_day.py` 加 `--llm-provider claude-agent-sdk`（預設仍 Template）。
若只為敘事而要用真實 LLM，**直接呼叫 API**（Anthropic Messages API 或用比賽 Google credit 的 Gemini API）比 Agent SDK 更簡單、更快；Agent SDK 的工具 / agent loop 對本用途沒有價值。詳見 `reports/LLM_PROVIDER_DECISION_MATRIX.md`。
