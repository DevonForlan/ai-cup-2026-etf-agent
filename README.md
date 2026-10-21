# AI CUP 2026 玉山人工智慧公開挑戰賽 — Agent 基金經理人

Daily D-Plan (v4.3) agent for the 2026 E.SUN AI Challenge: a **frozen quantitative core (Quant v1)** selects a
25-name portfolio from the official 150-stock universe; an LLM only writes grounded narrative (template fallback).
Operations (prediction 19:30, evaluation 17:00, DataPack gate, submission window, receipts) live in `agent/ops` and
`agent/submission`. Research (factor, risk overlay) is kept separate and is not production.

> Private repository. AI-generated content must be reviewed by a human before use.

## Status

- Quant v1: **FROZEN** — strategy sha256 `f34fa02e…d2e0`, W5 NAV `1,014,240,575.839861741934859718`,
  24/24 decision hashes. See `CLAUDE.md` §2.
- Run mode: PRECOMPETITION (paper trading). Competition 2026-10-27 → 2026-11-27.
- Current state: `DEVELOPMENT_STATUS.md`, `reports/PRECOMPETITION_OPERATIONAL_READINESS.md`.

## Quick start (Windows)

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.venv\Scripts\python.exe -m pytest -q                          # synthetic fixtures, no network
.venv\Scripts\python.exe -m agent.ops.competition_preflight     # read-only readiness check
```

The market-data store `data/history` and all runtime outputs (logs, submissions, ledgers, DataPacks, receipts)
are local and gitignored. Freeze regression with local data: `scripts\ci\local_freeze_regression.py`.

## Collaboration

Owner + Claude Code + GitHub + ChatGPT review: `docs/COLLABORATION_WORKFLOW.md`, `CONTRIBUTING.md`, `CLAUDE.md`.
Competition-period changes: `docs/CODE_CHANGE_GOVERNANCE.md`. Daily operations: `reports/COMPETITION_OPERATION_SOP.md`.

## Layout

| Path | Content |
|---|---|
| `agent/` | data, features, portfolio (frozen), engine, dplan, ops, submission, llm, research helpers |
| `config/` | frozen strategy, competition rules, ops / LLM configs |
| `tests/` | unit + integration tests on synthetic fixtures |
| `research/` | research-only studies with pre-registered gates and negative results |
| `reports/`, `docs/` | reports, runbooks, governance |
| `scripts/ci/` | CI helpers (secret scan, quant freeze check, config validation, local freeze regression) |
| `automation/` | Windows Task Scheduler wrappers (19:30 / 17:00) |
