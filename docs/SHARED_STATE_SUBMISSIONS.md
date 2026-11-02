# Shared State — submitted FINALs (Issue #31)

Every competition date that reaches **SUBMISSION_CONFIRMED** is published to the `shared-state` branch of this
repository so a reviewer (ChatGPT / Owner) can read the exact submitted plan from GitHub, without an upload.

## Layout (branch `shared-state`, never merged into `master`)

```
shared_state/daily_submissions/latest.json        pointer: trade_date, team_id, final_path, final_sha256,
                                                  submission_status, submitted_at, confirmed_at, synced_at, summary_path
shared_state/daily_submissions/<date>/FINAL.json  byte-exact copy of the submitted D-Plan (.gitattributes `-text`)
shared_state/daily_submissions/<date>/manifest.json   integrity evidence + idempotency key + supersession chain
shared_state/daily_submissions/<date>/summary.md  human summary (only fields present in the sources)
shared_state/daily_submissions/<date>/superseded/<sha8>/   earlier confirmed FINALs, kept for audit
```

Reader flow: read `latest.json` -> follow `final_path` -> verify SHA256 against `final_sha256` -> answer from the plan.

## Behaviour

- Trigger: `auto_upload` calls `shared_state_sync.sweep()` right after it emits `SUBMISSION_CONFIRMED` (19:30 and 07:30 runs).
  Manual: `python -m agent.ops.shared_state_sync [--date YYYY-MM-DD] [--root <production root>] [--no-push]`.
- Only `submissions/<date>/submission_state.json` = SUBMISSION_CONFIRMED with team `competition_team_id` and a FINAL whose
  SHA256 equals the state's `dplan_sha256` is published. TEAM_TEST / rehearsal plans never are.
- Idempotent on `trade_date | team_id | sha256`; a repeat makes no commit. A different confirmed FINAL for the same date
  is archived under `superseded/` and the chain is recorded in `manifest.json`; `latest.json` only moves forward.
- The production checkout is never touched: a dedicated worktree `<root>/.worktrees/shared-state` is used, so the
  `git_clean` preflight and the checked-out branch are unaffected.
- Downstream only: any failure is swallowed, written to `logs/shared_state/pending.json`, and retried by the next
  `sweep` (push: 3 attempts per run). It never changes, retries or replaces a submission and never escalates by itself.
- Not copied: receipts, screenshots, cookies, tokens, browser profile, DataPacks, logs.

Competition impact: Frozen Quant none; investment behaviour none; FINAL generation none; submission semantics none.
