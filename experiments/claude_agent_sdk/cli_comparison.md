# Claude Code CLI (subprocess) vs Claude Agent SDK — narrative use

Experiment only. **Not** a production architecture: `competition_day.py` must not shell out to `claude`.
Observed on Windows 11, Python 3.13.16, Claude Code 2.1.289, claude-agent-sdk 0.2.163, Chinese project path,
both locked down (`--bare --tools "" --setting-sources "" --permission-mode dontAsk --no-session-persistence`,
empty `CLAUDE_CONFIG_DIR`) and **without credentials** (no real model call was possible: no API key).

| aspect | CLI `claude -p --output-format json` | Agent SDK `query()` |
|---|---|---|
| Structured output | `--json-schema` flag; result object carries `structured_output` | `output_format={"type":"json_schema",...}`; `ResultMessage.structured_output` (typed) |
| Stdout noise | one JSON object on stdout; stderr empty in our run | parsed message stream; no stdout parsing in our code |
| Exit code | `1` on API/auth error (`terminal_reason: api_error`), JSON still printed | exceptions (`ProcessError`, `ResultError`, `CLINotFoundError`, `CLIJSONDecodeError`) + `ResultMessage.is_error` |
| Timeout | caller must kill the process tree | `anyio.fail_after` + SDK closes the transport; measured: LLMTimeout, no orphan `claude.exe` |
| Permission | same flags | same flags + typed options + `PreToolUse` hook callback (records attempts) + `can_use_tool` |
| Logging / usage | `usage`, `modelUsage`, `total_cost_usd`, `permission_denials` in the JSON | same fields typed on `ResultMessage` |
| Replay | we would hash prompt/response ourselves | same — our `LLMClient` logs every call; `ReplayProvider` replays by prompt hash |
| Windows quirks | npm `claude.cmd` shim works from a shell | SDK **refuses** `.cmd` shims: provider points `cli_path` at the native `claude.exe` inside the npm package |
| State written | `.claude.json` (+ backup) into `CLAUDE_CONFIG_DIR` | same; sandbox removed after each call (retrying delete) |
| Automation stability | OK, but argument quoting / encoding / process-tree handling is ours | better: typed errors, async cancellation, version check |

Conclusion: if Claude is used at all for narrative, the SDK is the better integration surface than a raw CLI
subprocess; both need an API key for an agent like ours. Neither is needed for the competition default.
