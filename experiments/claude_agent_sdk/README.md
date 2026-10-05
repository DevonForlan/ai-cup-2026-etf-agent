# Claude Agent SDK spike (Round 06A)

Isolated experiments for using the Claude Agent SDK as a **narrative-only** provider. Nothing here is wired into
`competition_day.py`; the competition default remains the Template narrative.

## Authentication rule (from Anthropic's official docs)
The Agent SDK is used with **API-key authentication only** (Claude Console key, or a supported cloud provider).
The docs say agents built on the Agent SDK must not use claude.ai / Claude Code subscription login
("Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate
limits for their products, including agents built on the Claude Agent SDK. Use the API key authentication methods
… instead." — code.claude.com/docs/en/agent-sdk/overview; see also code.claude.com/docs/en/legal-and-compliance).

Enforced in `agent/llm/providers/claude_agent_sdk.py`:
- no `ANTHROPIC_API_KEY` -> nothing is spawned (`AUTH_BLOCKED_NO_API_KEY`);
- CLI flags `--bare` (auth strictly API key / apiKeyHelper; OAuth and keychain never read) and
  `--no-session-persistence`, plus an empty per-run `CLAUDE_CONFIG_DIR`; other credential variables are blanked.
- No credential is ever read, printed, logged or stored by these scripts.

## Scripts (run from this folder with `..\..\.venv\Scripts\python.exe <script>`)
| script | needs API key | what it shows |
|---|---|---|
| `auth_probe.py` | no | SDK / CLI versions, auth mode; **isolation check**: real locked-down CLI with no credentials cannot authenticate, no orphan process |
| `smoke_test.py` | yes | first real call: facts JSON -> {market_view, counter_evidence, fact_refs} |
| `structured_output_test.py` | yes | 20 calls through LLMClient + pydantic + grounding: schema pass rate, parse failures, unknown ids, numeric hallucinations |
| `permissions_test.py` | yes | asks for `dir`, `git status`, edit strategy, read `.env`, list root: all must fail (PERMISSION_MODEL_FAIL otherwise) |
| `prompt_injection_test.py` | yes | injection inside a fact, numeric hallucination, ticker hallucination |
| `filesystem_test.py` | static: no / live: yes | sandbox contents, cwd != project root, no setting sources |
| `shell_test.py` | static: no / live: yes | exact CLI command line (`--tools ""`, `--bare`, `dontAsk`, deny list); live marker-file test |
| `latency_test.py` | timeout part: no / live: yes | real-CLI timeout -> LLMTimeout, process + sandbox cleanup; 20-call p50/p95/max |
| `usage_test.py` | live: yes | usage / cost fields exposed by the SDK |
| `narrative_replay.py --days 3/15` | yes | Template vs SDK on W5 days (`--self-test`: fake SDK transport, not Claude) |

Results: `results/*.json` (no credentials). Per-run sandboxes: `runtime/claude_agent_sdk/` (gitignored, deleted after each call).

## Status (2026-10-05)
`ANTHROPIC_API_KEY` absent -> **TECHNICALLY_SUPPORTED / AUTH_BLOCKED_NO_API_KEY**. Every real-call experiment is
BLOCKED; static lockdown checks, the no-credential isolation check, timeout/cleanup and the fake-transport replay
self-test PASS. See `reports/ROUND_06A_CLAUDE_AGENT_SDK_FEASIBILITY.md`.
