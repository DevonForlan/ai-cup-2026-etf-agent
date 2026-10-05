# 13 — Claude Code CLI as a runtime LLM: official documentation review (Round 06B)

日期：2026-10-05　｜　只依 Anthropic 官方文件（code.claude.com/docs）與本機 `claude --help`（2.1.289）。AI 產生內容，需人工審閱。
Round 06A 的 Agent SDK 結論不直接沿用；本文件針對「本人已登入、未修改的 `claude` CLI 以 `claude -p` 被 Python 子程序呼叫」重新查證。

## 1. 官方對各功能的描述

| # | 項目 | 官方說明（摘要 / 原文） | 來源 |
|---|---|---|---|
| 1 | `claude -p` / `--print` | 「Add the `-p` flag to any `claude` command to run it non-interactively」；用於 scripts、CI；CLI reference：「Query via SDK, then exit」。headless 頁標題為「Run Claude Code programmatically — Use the Agent SDK to run Claude Code programmatically from the CLI」 | headless、cli-reference |
| 2 | `--output-format json / stream-json` | json：「structured JSON with result, session ID, and metadata」（含 `total_cost_usd`，為 client-side 估算）；stream-json：每行一個 JSON 事件，首個 `system/init` 列出 model、tools、MCP servers，最後一行 `result` | headless |
| 3 | `--json-schema` | 「Get validated JSON output matching a JSON Schema … (print mode only)」；結果在 `structured_output`；無效 schema 會直接報錯退出 | cli-reference、headless |
| 4 | `--tools` | 「Use `""` to disable all」；「The flag doesn't affect MCP tools; to deny those too, use `--disallowedTools "mcp__*"`」 | cli-reference |
| 5 | `--disallowedTools` | 「A bare tool name removes the matching tools from Claude's context: `"*"` removes every tool」 | cli-reference |
| 6 | `--permission-mode` | `dontAsk`：「denies every call that would otherwise prompt … useful for locked-down CI runs」；但「file reads in your working directories and the read-only command set」在無工具限制時仍可執行 → 必須配合 `--tools ""` | headless |
| 7 | `--bare` | 跳過 hooks、skills、plugins、MCP、auto memory、CLAUDE.md；「bare mode doesn't use your subscription login」，只用 `ANTHROPIC_API_KEY` / `apiKeyHelper`；「In bare mode Claude has access to the Bash, file read, and file edit tools」；「recommended mode for scripted and SDK calls, and will become the default for `-p` in a future release」 | headless |
| 8 | `--no-session-persistence` | 「sessions are not saved to disk and cannot be resumed. Print mode only」 | cli-reference |
| 9 | `--system-prompt` / `--system-prompt-file` | 取代整個預設系統提示；「Use a replacement flag when … a non-coding agent in a pipeline that no human watches」 | cli-reference |
| 10 | `--model` | alias 或完整模型名，覆蓋設定 | cli-reference |
| 11 | timeout / 結束 | exit 0 成功、非 0 失敗；run 內失敗（例如未驗證）以 result 印在 stdout；SIGTERM → exit 143、終止 Bash 子程序樹；`-p` 背景工作有 10 分鐘上限 | headless |
| 12 | `claude auth status` | 「Show authentication status as JSON … Exits with code 0 if logged in, 1 if not」；`authMethod` ∈ none / claude.ai / oauth_token / api_key / api_key_helper / third_party | cli-reference |
| 13 | `claude setup-token` | 「Generate a long-lived OAuth token for CI and scripts … Requires a Claude subscription」 | cli-reference、authentication |
| 14 | 訂閱 OAuth 在 script / CI | authentication：「For CI pipelines, scripts, or other environments where interactive browser login isn't available, generate a one-year OAuth token with `claude setup-token`」；「This token authenticates with your Claude subscription」 | authentication |
| 15 | legal-and-compliance | 見 §3 | legal-and-compliance |
| — | `--restricted`（本機 help + docs） | 「an evaluation harness drives `claude` on a shared machine and Claude Code must not run commands or read that machine's user and project settings」：移除執行指令的工具與 WebFetch、檔案工具限於工作目錄、只載入 managed settings 與 `--settings`、拒絕 bypassPermissions | cli-reference |
| — | `--safe-mode` | 不載入 CLAUDE.md、skills、plugins、hooks、MCP、auto memory；「Authentication, model selection, built-in tools, and permissions work normally」；managed policy 仍適用 | cli-reference |

**對本 PoC 的關鍵含義**：訂閱登入下不能用 `--bare`（bare 只用 API key），因此隔離必須改用 `--safe-mode` + `--restricted` + `--tools ""` + `--disallowedTools` + `--setting-sources ""` + `--strict-mcp-config` + `--no-session-persistence` + sandbox cwd + `--system-prompt-file`，並以 stream-json 的 `init` 事件實測工具清單（實測：只有內部 `StructuredOutput`、MCP 0）。

## 2. 使用情境分類

| 類別 | 說明 | 本輪 |
|---|---|---|
| A | 本人在本機互動使用自己的 Claude Code CLI | 研究 |
| B | Python 子程序呼叫本人已登入、未修改的 `claude` CLI | **PoC 實測** |
| C | `claude setup-token` 用於 script / CI | 只研究文件；**未建立 token** |
| D | 把訂閱憑證提供給其他使用者 | 禁止 |
| E | 建立產品替其他使用者路由 Claude 請求 | 禁止 |

## 3. Legal / Terms（legal-and-compliance 原文重點）
- 「**OAuth authentication** is intended exclusively for purchasers of Claude Free, Pro, Max, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications.」
- 「**Developers** building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication … Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users. … developers may not collect, store, or intermediate Claude.ai credentials or session tokens.」
- 「… Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription …」
- 「Advertised usage limits for Pro and Max plans assume ordinary, individual usage of Claude Code and the Agent SDK.」
- License：Team / Enterprise 使用者適用 **Commercial Terms**；Free / Pro / Max 適用 Consumer Terms。

## 4. 判定（只依官方文件；未明說者標 UNCLEAR）

| 類別 | 判定 | 依據 |
|---|---|---|
| PERSONAL_LOCAL_CLI_USE | **SUPPORTED** | OAuth 為「ordinary use of Claude Code」而設計；本人使用未修改的 binary |
| SCRIPTED_CLI_USE（本人、本機、本人帳號、不對外提供） | **SUPPORTED** | `claude -p` 為官方 scripts / CI 模式；`setup-token` 明示「for CI and scripts … Requires a Claude subscription」。注意：官方建議 scripted 呼叫用 `--bare`（只吃 API key），且 bare 將成為 `-p` 預設 → 未來版本可能改變訂閱登入的 scripted 行為 |
| COMPETITION_USE（以自動化 agent 參賽、每日產生投資文件） | **UNCLEAR** | 文件未說明「為比賽打造的自動化 agent」是否屬於「products or services that interact with Claude's capabilities」（該類應使用 API key）；另需符合比賽規則（未查得對 LLM 供應商的限制）|
| THIRD_PARTY_SERVICE_USE | **NOT_SUPPORTED** | 明文禁止替他人路由訂閱憑證、在自家產品提供 claude.ai 登入、收集 / 中介憑證 |

## 5. 本機帳號
`claude auth status`（只取白名單欄位）：`loggedIn=true`、`authMethod=claude.ai`、`subscriptionType=team`、`apiProvider=firstParty`、**ORG_MANAGED_ACCOUNT=true**（組織資訊未記錄）。Team 方案受該組織的 Commercial Terms 規範，且該組織另有使用政策 → **用於個人競賽前需取得公司授權**；本輪技術 PoC 不因此停止，但**不得標為 production approved**。
另觀察：在 `--system-prompt-file` 取代系統提示後，模型回答仍引用「公司政策」→ 組織的 managed 指示會被注入 CLI context，屬於我們無法控制的 prompt 成分（影響可重現性）。

## 6. 來源
code.claude.com/docs/en/headless、/cli-reference、/authentication、/legal-and-compliance、/agent-sdk/overview；`claude --help`（2.1.289）。
