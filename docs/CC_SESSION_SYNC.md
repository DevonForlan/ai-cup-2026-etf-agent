# Claude Code session sync to GitHub Shared State (Issue #55)

Terminal-only progress of a Claude Code (CC) session is published to the `shared-state` branch so a reader (ChatGPT, Owner) can see the
latest CC response without it first being summarised into an Issue comment.

## Layout (branch `shared-state`)
```
shared_state/cc_sessions/latest.json          newest session (small)
shared_state/cc_sessions/index.jsonl          one line per publish
shared_state/cc_sessions/<session-id>/transcript.md   readable turns: ## Turn N / ### User / ### Claude / ### Tool actions
shared_state/cc_sessions/<session-id>/events.jsonl    append-only machine events (USER_PROMPT, CLAUDE_RESPONSE, TOOL_ACTION, TOOL_RESULT,
                                                      TASK_NOTIFICATION, BACKGROUND_TASK_STATUS, API_ERROR, SCHEDULED_WAKEUP, PR_LINK, TURN_END, ...)
shared_state/cc_sessions/<session-id>/latest.json     same fields as the top-level latest.json
```
`latest.json` fields: session_id, turn, timestamp (Asia/Taipei), project (sanitised), status (RUNNING | WAITING_SCHEDULE | COMPLETED |
BLOCKED | ERROR), latest_user_prompt, latest_claude_response (+ _at), latest_tool_summary, pending_next_action, next_scheduled_check,
related_issues, related_prs, production_head, events, synced_at. "Turn N" = N-th completed response (Stop hook), the count the terminal shows.

## How to answer "CC 最新回應" (lookup order)
1. `shared_state/cc_sessions/latest.json` (compare `synced_at` with the clock: a stale value means CC is idle or the sync is pending)
2. `shared_state/cc_sessions/<session-id>/latest.json`
3. `<session-id>/transcript.md` / `events.jsonl` (tail)
4. related Issue / PR comments (`related_issues`, `related_prs`)
5. commits, `daily_submissions`, `daily_evaluations`, `tactical`, `shadow` Shared State

## How it runs
Source: the local CC transcript `~/.claude/projects/<project>/<session-id>.jsonl` (read-only, parsed incrementally by byte offset).
Hooks (project `.claude/settings.local.json`): `Stop`, `UserPromptSubmit`, `SubagentStop`, `SessionEnd`, `PostToolUse` (throttled) run
`python -m agent.ops.cc_session_sync hook`, which returns immediately and starts the real work as a detached process. Background-task
completions, wakeups and API errors are part of the transcript, so the next hook (or `sync`/`sweep`) captures them.
Manual: `python -m agent.ops.cc_session_sync sync --session <id> --force` ; `sweep` retries every pending publish ; `redact-test`.

## Never blocks, always catches up
Local files under `logs/cc_sessions/<session-id>/` are the durable queue. A GitHub/DNS failure leaves `pending_publish: true`; the next
sync publishes everything missed. The module imports nothing from the submission / scheduler / competition_day code and swallows every error.
Publishes are throttled (90 s). Git operations use the existing shared-state worktree helpers (fast-forward pushes only, never force).

## Hygiene
Redacted before anything is written (also locally): private keys, `sk-`/`ghp_`/`github_pat_`/AWS/Google/Slack keys, JWTs, Bearer/Basic,
`key=value` secrets, CLI flags (`--token X`), cookies, URL credentials, e-mail addresses; the Windows user name in paths becomes `<user>`.
`<system-reminder>` blocks, thinking blocks and API request blobs are never copied. Large tool outputs are clipped and replaced by
length + sha256. Operational error text (e.g. `ENOTFOUND`) is kept. No binary files, no raw tool output files.

## Rollback
Remove the hook entries from `.claude/settings.local.json`; delete `shared_state/cc_sessions/` on the branch if desired. No production
behaviour depends on this feature.
