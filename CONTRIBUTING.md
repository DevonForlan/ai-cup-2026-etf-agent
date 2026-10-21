# Contributing

All work follows `docs/COLLABORATION_WORKFLOW.md`. Short version:

1. **Issue first** — use a template (FEATURE, BUG, OPS, RESEARCH, EXPERIMENT, DOCS, COMPETITION_RULE_CHANGE,
   SECURITY, TECH_DEBT, PROMOTION). Large work needs an Owner-approved Issue or Sprint.
2. **Branch** from `master`: `feat/<issue>-<topic>`, `fix/…`, `ops/…`, `research/…`, `docs/…`. Never commit daily
   work to `master`; never force push; never rewrite history.
3. **Implement + test** — targeted tests, then `python -m pytest -q`. If a change could touch decisions, run
   `scripts\ci\local_freeze_regression.py` locally (Quant v1 must stay identical).
4. **PR** with every section of `.github/PULL_REQUEST_TEMPLATE.md` (Problem, Design, Changes, Tests, Regression,
   Quant Freeze Impact, Experimental Results, Limitations, Risks, Follow-up, Backward Compatibility, Impact).
5. **CI must pass** (`ci.yml`). Fix the cause; never weaken or delete valid tests.
6. **ChatGPT review** → address blocking items (fix or rebut with evidence) → second review.
7. **Owner merges** (squash preferred). No auto-merge. Branch deleted after merge.

## Never commit

Credentials, tokens, cookies, sessions, `.env`, private keys, browser profiles / HAR files, screenshots of the
back office, raw market data (`data/history`, `data/raw`), DataPacks, submission receipts, runtime logs,
`sim_runs/`, `runtime/`. The secret scan (`scripts/ci/secret_scan.py`) runs on every PR.

## Investment behaviour

Selection, ranking, weights, rebalance, sizing, cash policy, thresholds, risk / regime logic and decision-changing
prompts are **investment behaviour**. They change only through an Owner-approved Promotion or Competition-rule
Issue, with the PR label `owner-approved-investment-change` and a before / after freeze comparison.
