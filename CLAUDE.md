# CLAUDE.md — instructions for Claude Code in this repository

AI CUP 2026 玉山人工智慧公開挑戰賽 — **Agent 基金經理人**. Each trading day the agent produces a D-Plan
(v4.3 JSON) for a 150-stock universe: a frozen quantitative core decides tickers / weights / orders; an LLM
(Claude CLI, template fallback) only writes grounded narrative. Competition: 2026-10-27 → 2026-11-27.

## 1. Roles

| Role | Responsibilities | Never |
|---|---|---|
| **Owner** | product direction, Issue / Sprint approval, research promotion, releases, investment-behaviour changes during the competition, third-party services, what data may go to GitHub, and every merge outside the LOW_RISK_OPS_AUTOMERGE exception | — |
| **Claude Code** | analyse Issues, design, implement, test, regression, debug, docs, branch / commit / push / PR, fix CI, answer reviews, reproducibility, change log; may self-review and merge only when every LOW_RISK_OPS_AUTOMERGE gate in §4 passes | force push, rewrite history, delete protected / release branches; merge when any LOW_RISK_OPS_AUTOMERGE gate is false or ambiguous |
| **ChatGPT** | independent reviewer / architect on GitHub PRs: architecture, diff, tests, regression, evidence, security / data exposure, reproducibility; blocking vs non-blocking comments; review recommendation | merge unless the Owner explicitly delegates a specific merge action |

Recommendations are separate: Claude Code → `READY_FOR_REVIEW / NOT_READY / BLOCKED`; ChatGPT →
`APPROVE / APPROVE_WITH_FOLLOW_UP / REQUEST_CHANGES / DO_NOT_MERGE`; Owner → `MERGE / DO_NOT_MERGE`.
For LOW_RISK_OPS_AUTOMERGE only, Claude Code may additionally record `SELF_REVIEW=PASS` and `SELF_MERGE=AUTHORIZED_BY_POLICY` after every gate passes.

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
- Normal path: **Issue → feature branch → implementation → tests → PR → ChatGPT review → Owner merge** (squash preferred; delete the branch after merge).
- Exception: **LOW_RISK_OPS_AUTOMERGE**. Claude Code may self-review and merge its own PR only when ALL gates below pass:
  1. Issue is already Owner-approved or clearly within an Owner-approved OPS scope;
  2. no frozen-path diff and Quant fingerprint unchanged;
  3. no investment behaviour, ranking, weights, rebalance, cash, order sizing, decision prompt/model change;
  4. no submission semantics, portal action policy, cutoffs/windows, attempt caps or success-definition change;
  5. no security/privacy/credential/auth/session/MFA/CAPTCHA policy change;
  6. no breaking API/schema, deployment architecture, destructive action, paid/third-party service, external data-source policy or competition-rule interpretation change;
  7. full pytest, validate, secret-scan and quant-freeze-check all PASS;
  8. PR is mergeable and current with `master`, production checkout is clean, and PR contains impact/rollback evidence.
  If any gate is false or ambiguous, Owner merge is still mandatory. Squash is preferred; no force push, no history rewrite.
- Never push daily work directly to `master`; merge through PRs only.
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

**Default: fail closed.** No portal upload or submission happens unless every condition below is met.

- **Never, under any approval:** login automation (the Owner logs in normally; the agent never types credentials),
  guessed or private APIs, cookie / token / CSRF / password / browser-storage extraction, SSO / MFA / CAPTCHA bypass.
- **Official API path:** the portal has no documented participant API. `OfficialPortalProvider` (extension point in
  `agent/submission/future_api.py`) stays `DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION` until an official mechanism
  exists and the Owner approves it.
- **Browser upload / submission of the human UI** (Owner-logged-in automation profile) is allowed when:
  1. an Owner-approved Issue plus an Owner Decision recorded on GitHub authorizes the capability;
  2. Team ID, trade date and FINAL SHA match; local validation and compliance pass; 08:30 / 08:55 cutoffs and attempt
     caps hold; only the same FINAL SHA may be retried;
  3. the submit flow follows the Owner Decision of 2026-10-27 (Issue #20): **best-effort unattended submission**.
     Unknown modal wording, an unconfirmed confirmation dialog, or a minor selector change does not by itself require
     Owner intervention. The runner captures evidence, uses bounded exploration by visible text / role / button label /
     DOM structure, and retries only within configured caps. Before each retry it checks submission history / 「回看」;
     if the portal record matches the FINAL, stop and mark **SUBMISSION_CONFIRMED**;
  4. escalation to the Owner is reserved for login/session recovery that cannot be completed without credentials,
     MFA / CAPTCHA, Team ID or trade-date mismatch, portal unavailability, account permission problems, Quant freeze
     violations, or other security / destructive-operation boundaries. Do not escalate merely because a benign UI
     element has not been seen before;
  5. the portal shows no "ACCEPTED" word. Success is **SUBMISSION_CONFIRMED**: unique history row 已繳交 for T,
     Team and trade date match, 「回看」 content == the FINAL, and no rejection / 檢核 failure
     (`agent/submission/confirmation.py`). Never fabricate ACCEPTED.
- **Competition operating priority:** minimize Owner time and prefer unattended best-effort operation over
  mission-critical conservatism. A single failed submission, bounded retry, or even a missed competition day is an
  acceptable operational outcome; preserve evidence and continue on the next available run instead of creating an
  unnecessary manual gate.
- Organisation policy: no customer data, credentials or confidential documents; AI-generated content is reviewed by a
  human before use.

## 10. ChatGPT review loop

PR stays OPEN (draft → ready for review). Blocking comments: fix or give a concrete technical rebuttal. Non-blocking: fix now, open a follow-up Issue, or record why not. After fixes: push to the same branch, wait for CI, and reply per item (review item → resolution → file → commit → test result).

For normal PRs, Owner merge remains required. For a PR that qualifies for **LOW_RISK_OPS_AUTOMERGE**, Claude Code may perform its own final review, record every gate result in the PR, and merge after all required checks are green. Self-review is not permission to waive a gate. If classification or risk is ambiguous, escalate to Owner instead of merging.


## 11. COMPETITION_HIGH_AUTONOMY — Owner Decision 2026-11-05

For the remainder of AI CUP 2026, this section supersedes conflicting human-approval requirements in §§1, 4, 5, 7 and 10 for competition work.

Claude Code is authorised to complete the normal competition engineering loop end-to-end without waiting for Owner or ChatGPT review:
**Issue → branch → implement/research → test → PR → self-review → CI → self-merge → production deploy → verify → rollback if needed → evidence → close**.

This autonomy covers technical, operational, data, scheduler, observability, model/prompt and investment-strategy work. PRs remain required for auditability, but may be created, reviewed and merged in the same Claude Code session. Claude Code should minimise repeated approval loops and complete as much safe work as possible in one round.

### Strategy changes

Recent losses alone are not evidence for a strategy change. Claude Code may autonomously create and promote a new strategy version (v2+) only when it preserves Quant v1 as an immutable baseline and records a new fingerprint, pre-registers the change where practical, compares against production with OOS/rolling windows, includes costs/turnover/compliance/Active Share, tests drawdown recovery/recent regimes and simple/placebo baselines, documents before/after behaviour, preserves rollback, and passes the repository test/validation/security gates. Never overwrite Quant v1 history.

When evidence is mixed, prefer the smallest reversible risk-control change over a wholesale strategy rewrite.

### Hard boundaries that remain

Claude Code must still never extract credentials/cookies/tokens/session/MFA material, bypass login/MFA/CAPTCHA, use guessed/private/unauthorised APIs, perform illegal or clearly unauthorised actions, incur paid third-party costs or financial commitments without Owner approval, delete/rewrite audit history, force-push protected/release branches, weaken tests/compliance checks, fabricate evidence/submission success/settlement, expose confidential/customer data, or knowingly violate competition rules.

If a competition-rule ambiguity could reasonably cause disqualification and there is no clearly compliant conservative path, escalate to Owner. Otherwise choose the conservative compliant path, record the reasoning, and continue.

### Self-merge and deployment gates

Before self-merge: PR current/mergeable, targeted tests PASS, full pytest PASS (unless a documented unrelated environment-only suite failure is proven), validate PASS, secret scan PASS, version/freeze gate PASS, no unresolved blocking review, and impact/rollback evidence present.

After merge: production checkout clean, pull latest master, verify production HEAD == origin/master, verify schedulers point to production root, run smoke checks, verify relevant Shared State/submission/evaluation outputs, and automatically roll back the just-deployed change if an objective regression is detected and rollback is safe.

Owner may override or revoke this mode at any time. Otherwise it remains active until the competition ends.
