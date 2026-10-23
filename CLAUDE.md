# CLAUDE.md — instructions for Claude Code in this repository

AI CUP 2026 玉山人工智慧公開挑戰賽 — **Agent 基金經理人**. Each trading day the agent produces a D-Plan
(v4.3 JSON) for a 150-stock universe: a frozen quantitative core decides tickers / weights / orders; an LLM
(Claude CLI, template fallback) only writes grounded narrative. Competition: 2026-10-27 → 2026-11-27.

## 1. Roles

| Role | Responsibilities | Never |
|---|---|---|
| **Owner** | product direction, Issue / Sprint approval, research promotion, **the only merge decision**, releases, investment-behaviour changes during the competition, third-party services, what data may go to GitHub | — |
| **Claude Code** | analyse Issues, design, implement, test, regression, debug, docs, branch / commit / push / PR, fix CI, answer reviews, reproducibility, change log | merge PRs, enable auto-merge, push daily work to `master`, force push, rewrite history, delete protected / release branches |
| **ChatGPT** | independent reviewer / architect on GitHub PRs: architecture, diff, tests, regression, evidence, security / data exposure, reproducibility; blocking vs non-blocking comments; review recommendation | merge |

Recommendations are separate: Claude Code → `READY_FOR_REVIEW / NOT_READY / BLOCKED`; ChatGPT →
`APPROVE / APPROVE_WITH_FOLLOW_UP / REQUEST_CHANGES / DO_NOT_MERGE`; Owner → `MERGE / DO_NOT_MERGE`.

## 2. Quant v1 is FROZEN

| Fingerprint | Value |
|---|---|
| `config/strategy_quant_v1.yaml` sha256 | `f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0` |
| W5 NAV (2026-08-28, 24 days) | `1,014,240,575.839861741934859718` |
| decision hashes vs `sim_runs/round06_baseline_quant_v1` | 24 / 24 identical |

Frozen paths: `config/strategy_quant_v1.yaml`, `agent/features/`, `agent/portfolio/`, `agent/pipeline.py`,
`agent/run_sim.py`, `agent/sim/`. Never change stock selection, ranking, Revenue YoY 0.70 / MoM 0.30 weighting,
target holdings, weights, rebalance policy, order sizing, cash policy, portfolio construction or Quant parameters
without an **Owner-approved Promotion or Competition-rule Issue** and the PR label
`owner-approved-investment-change`. If a fingerprint changes unexpectedly: **STOP**, do not open a
ready-for-review PR. Verify locally: `.venv\Scripts\python.exe scripts\ci\local_freeze_regression.py`
(needs `data/history`, which stays local). CI checks the hash and frozen-path diffs (`scripts/ci/quant_freeze_check.py`).

## 3. Architecture (short)

- `agent/data` fetchers, PIT store (`data/history`, local) · `agent/features` · `agent/portfolio` (frozen Quant)
- `agent/engine` official rules / validator / Active Share · `agent/dplan` D-Plan v4.3 export
- `agent/competition_day.py` one-command daily run · `agent/ops` scheduler (19:30 prediction, 17:00 evaluation),
  preflight, DataPack gate, market-coverage gate, Active Share gate, submission window (08:30 decision cutoff,
  08:55 close), Team ID (`config/ops.yaml team`) · `agent/submission` evidence-based status, receipts, portal
  (browser-open only), official-test tools · `agent/llm` Claude CLI narrative (never decisions)
- `research/` research only (factor, risk overlay) · `reports/` · `docs/` runbooks · `tests/` (synthetic fixtures)

## 4. Git / GitHub workflow

**Mandatory for every Claude Code session:** follow `docs/COLLABORATION_WORKFLOW.md` (§7 GitHub = Shared State: status comment after every substantive step, `agent:*` labels, blocker write-back, ChatGPT review handoff, redacted evidence) and `docs/CODE_CHANGE_GOVERNANCE.md` (§6 Owner Decision Required → `owner:decision`, merge boundary, no scope expansion). State that exists only in the session is `HANDOFF_INCOMPLETE`; a decision asked only in the session is `OWNER_DECISION_NOT_FORMALIZED`. At every major Owner-facing point, write the **exact** final response to `handoff/claude_sessions/` first and present that same text (§7.10); link it as `LATEST_CLAUDE_HANDOFF`.

- Repo: `DevonForlan/ai-cup-2026-etf-agent` (private), default branch `master`.
- **Issue → feature branch → implementation → tests → PR → ChatGPT review → Owner merge** (squash preferred;
  delete the branch after merge). Never push daily work to `master`; never force push; never rewrite history.
- Branches: `feat/<issue>-<topic>`, `fix/…`, `ops/…`, `research/…`, `docs/…`. One Issue per branch / PR;
  ≤ 2–3 parallel tracks (worktrees allowed for low-coupling tracks).
- PRs use `.github/PULL_REQUEST_TEMPLATE.md` (all sections; "tests passed" alone is not acceptable).
- Commits end with the attribution trailer given by the session. Never commit credentials, cookies, sessions,
  `.env`, raw market data, DataPacks, receipts or screenshots (see `.gitignore`).

## 5. Autonomy boundary

Within an Owner-approved Issue / Sprint, Claude Code decides implementation details and iterates
implement → test → diagnose → fix until CI passes. **Stop and ask the Owner** only for: product positioning,
breaking API / schema, deleting a verified capability, major architecture change, paid / third-party services,
unauthorised data, security / privacy policy, research that overturns a core assumption, **any investment-behaviour
change**, competition-rule ambiguity with DQ risk, unclear data ownership, or unclear Owner intent.

## 6. Testing and CI rules

- Run targeted tests, then `python -m pytest -q` (full suite; synthetic fixtures, no network) before a PR.
- CI (`.github/workflows/ci.yml`): secret scan, quant-freeze-check, syntax / import / config / schema, pytest.
- Never delete valid tests, lower acceptance criteria, hard-code expected results, skip / xfail real bugs, hide
  failures, remove security tests or tune benchmarks to look good. A changed test spec must be justified in the PR.

## 7. Research ≠ production

Factor research, risk overlays, ML, simulations are **RESEARCH ONLY**: Research Issue → research branch →
pre-registered gate → evidence report (negative / inconclusive results kept, placebo / null where relevant) →
ChatGPT review → Owner decision. Promotion to production needs a separate **Promotion Issue** with production
design, regression and a before / after freeze comparison. Never cherry-pick windows, change the test after seeing
results, call simulation production evidence, synthetic data real-world validation, or a current-universe backtest
PIT-safe live proof.

## 8. Competition-period governance

Never change strategy because of recent performance (a losing day, a limit-down stock, a larger MDD, a weak sector,
a bad paper run). Technical / operational fixes (parser, data source, timeout, auth, scheduler, submission / schema
format, DataPack / receipt parser) go through an Issue and record: timestamp, reason, Issue, files, diff, git SHA,
`code_version`, before / after behaviour, regression result, Quant fingerprint, D-Plan impact
(`docs/CODE_CHANGE_GOVERNANCE.md`). D-Plans, DataPacks, receipts and logs stay local; git keeps metadata / hashes.

## 9. Security

No login automation, no uploads / submissions, no guessed private APIs, no cookie / token / password extraction.
`OfficialPortalProvider` stays `DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION` until an official mechanism exists and
the Owner approves. Organisation policy: no customer data, credentials or confidential documents; AI-generated
content is reviewed by a human before use.

## 10. ChatGPT review loop

PR stays OPEN (draft → ready for review). Owner asks ChatGPT to review. Blocking comments: fix or give a concrete
technical rebuttal. Non-blocking: fix now, open a follow-up Issue, or record why not. After fixes: push to the same
branch, wait for CI, reply per item (review item → resolution → file → commit → test result), request a second
review. **No auto-merge. Owner merges.**
