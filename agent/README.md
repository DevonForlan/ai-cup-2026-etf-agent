# MVP-0 Quant / Deterministic Agent Core

AI CUP 2026 玉山「Agent 基金經理人」參賽 Agent 的確定性核心。本版**不呼叫任何 LLM**；LLM 角色只有 interface 與 template 實作（Phase 5 再接）。

## Architecture

```
data/history (PIT tables, available_at)          data/raw/YYYYMMDD (raw + manifest.json, sha256)
        │                                                ▲
        ▼                                                │ fetchers (TWSE / TPEx / FinMind)
PITView(as_of = T 07:00 +08:00)  ── blocks rows with available_at > as_of or date > T
        │
        ▼
features/feature_engine  (150 檔 × 12 features + market breadth; missing → NaN)
        ▼
portfolio/ranking        (percentile ranks × config weights → score/rank)
        ▼
portfolio/constructor    (turnover-aware selection → tiered weights → strategy caps → lot feasibility
        │                 → no-trade band → cash band → Active Share → orders → pre/post/stress checks)
        │                 => TargetPortfolio  |  FallbackToPreviousPortfolio  (never half-legal)
        ▼
engine/orders            (derive-orders.v2, Decimal floor)
        ▼
dplan/builder → graph    (Evidence Graph: Source → Fact → Signal/MarketView → Inference → Decision → Order)
dplan/posture, funding   (C12 posture and C14 funding_for are DERIVED from orders)
        ▼
dplan/exporter           (reachable nodes only, renumber S1../O1../I1../D1..; {{fact:*}} placeholders → IDs)
        ▼
engine/validate_dplan    (JSON Schema v4.2 + semantic C1/C2/C6/C9/C11/C12/C13/C14, ID, coverage, ...)
        ▼
sim/settle               (VWAP fills, fees/tax, close NAV, accrued dividends, warnings/void/DQ, MDD)
```

| Package | Content |
|---|---|
| `agent/config.py` | Loads `config/competition.yaml` (official rules), `strategy.yaml` (buffers), `unconfirmed_rules.yaml` (unknowns + assumptions) |
| `agent/engine/` | rules (RuleBook), fees, orders (derive-orders.v2), active_share (4 modes), compliance, validate_dplan, models (CheckResult PASS/FAIL/WARNING/UNKNOWN/NOT_IMPLEMENTED) |
| `agent/sim/` | settle, metrics (MDD both ways), calendar, models (Settlement JSON) |
| `agent/data/` | http (rate limit, retry), manifest, loaders (HistoryStore parquet), normalizers, pit (PITView), providers (Live/Replay share one interface), fetchers/ |
| `agent/features/` | momentum, relative_strength, volume, volatility, institutional, revenue, feature_engine |
| `agent/portfolio/` | ranking, baseline (regime, selection, weights, water-fill), constructor, decisions |
| `agent/dplan/` | graph, builder, exporter, posture, funding |
| `agent/llm/` | interfaces (EventExtractor, MarketNarrator, ThesisWriter, Reviewer + Template providers), schemas (pydantic) |
| `agent/pipeline.py` | one trading day, shared by `run_daily.py` and `run_sim.py` |
| `agent/tools/` | `backfill.py` (historical download), `make_fixture.py` (synthetic data / synthetic ETF holdings) |

## Setup (Windows)

```bat
C:\Users\devon.tseng\AppData\Local\Programs\Python\Python313\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
(`requirements-lock.txt` = exact versions used in round 2.) Python 3.13 is not on PATH; always call `.venv\Scripts\python.exe`.

## Commands

```bat
:: tests
.venv\Scripts\python.exe -m pytest

:: historical data (resumable; ~2.5 s/request; TWSE+TPEx prices + 三大法人 + FinMind revenue)
.venv\Scripts\python.exe agent\tools\backfill.py --start 2025-09-01 --end 2026-10-02 --revenue

:: synthetic active-ETF top-10 holdings (FLAGGED synthetic) into the real store
.venv\Scripts\python.exe agent\tools\make_fixture.py --etf-only --history data\history

:: one day (replay); without --prev-settlement it starts from 1,000,000,000 cash
.venv\Scripts\python.exe agent\run_daily.py --date 2026-10-02 --mode replay --team-id TEAM_TEST

:: one day continuing from a settlement
.venv\Scripts\python.exe agent\run_daily.py --date 2026-10-02 --mode replay --prev-settlement sim_runs\<run>\settlement\2026-10-01.json

:: walk-forward simulation (W5) — one method or all baselines
.venv\Scripts\python.exe agent\run_sim.py --start 2026-08-31 --end 2026-10-02 --method B0_score_tiered
.venv\Scripts\python.exe agent\run_sim.py --start 2026-08-31 --end 2026-10-02 --all-baselines

:: synthetic fixture run
.venv\Scripts\python.exe agent\tools\make_fixture.py --out tests\fixtures\synthetic
.venv\Scripts\python.exe agent\run_sim.py --start 2026-10-26 --end 2026-11-27 --history <fixture-store> --fixture

:: validate any D-Plan (context = previous settlement facts)
.venv\Scripts\python.exe -m agent.engine.validate_dplan D-Plan_TEAM_043_2026-10-27.json --context tests\fixtures\ex_context_043.json
```

Live mode (`--mode live`) fetches T-1 TWSE/TPEx data first and uses wall-clock timestamps; it has **not** been exercised in a real 19:30–08:55 window yet and has no submission module.

## Configuration

| File | Content | Rule |
|---|---|---|
| `config/competition.yaml` | Official rules only (25%/10%/cash<25%/20–30/AS 20%/fees/lot/25 submissions/grace 5 days) | Never put strategy margins here |
| `config/strategy.yaml` | Buffers (24–27 names, 2330 ≤23.5%, others ≤9%, cash 5–12%, AS target 30%), score weights, tiers, turnover controls, regime thresholds | Changing it changes `code_version` |
| `config/unconfirmed_rules.yaml` | `unconfirmed:` raw unknowns (never treated as confirmed) + `simulation_assumptions:` values used for now | Override per run (e.g. `--fee-rounding`) |
| `config/data_sources.yaml` | PIT availability times, endpoints, HTTP limits | Assumptions, not official |
| `config/universe_150.csv`, `active_etf_list.csv` | Copied from `research/competition/` (extracted from official PDFs) | — |

## Rule assumptions (current `simulation_assumptions`)

| Unknown (NC) | Assumption used | Where |
|---|---|---|
| Active Share W_i definition (NC-2) | `UNKNOWN` → compute NAV_WEIGHT / TOP10_NORMALIZED / FULL_PORTFOLIO, gate on minimum | `engine/active_share.py` |
| Cash exactly 25% (NC-6) | not allowed | compliance, settle |
| Holdings 20/30 inclusive (NC-6) | inclusive | compliance |
| Fee rounding (NC-5) | exact (no rounding); `round_half_up/floor/ceil` available | `engine/fees.py` |
| No trade price on T (NC-4) | `skip` that order; `reject` = void the day | `sim/settle.py` |
| Rejected D-Plan (NC-3) | counts as not submitted (warning) | `sim/settle.py` |
| C-code dispositions (NC-3) | every known C failure = FAIL in our validator; message says disposition unconfirmed | `validate_dplan.py` |
| C12 estimate with fees? | without fees (posture range covers both) | `dplan/posture.py` |
| MDD incl. initial NAV (NC-8) | report both | `sim/metrics.py` |
| Stock dividends (NC-7) | keep exact odd shares | `sim/settle.py` |
| Settlement source (NC-1) | our own settlement JSON | `pipeline.py` |
| First trade date (NC-15) | not hard-coded; calendar from data | `sim/calendar.py` |

## Known unknowns / limitations
- Official C3/C4/C5/C7/C8/C10 and `verify_dplan.py` are not public → reported as `NOT_IMPLEMENTED`.
- Active-ETF holdings are **synthetic** (template top-10). Active Share numbers are therefore only a mechanism test.
- No corporate-action data feed yet (TWT49U not wired) → historical replay ignores dividends; simulator logic is tested with fixtures.
- Monthly revenue availability is assumed = 10th of next month 23:59 (no per-company publish timestamps yet).
- No overnight US / SOX / ADR / TAIFEX night-session data (market view uses universe breadth only).
- No submission module (upload mechanism unknown).
- Replay metadata uses a simulated clock (run at T 07:00); `fetched_at` is omitted in replay because real fetch times are after the historical trade date.

## Testing
`pytest` (see `tests/`): engine (orders/fees/Active Share/compliance), dplan (schema + semantic, EX42/EX43, edge cases), sim (3-day golden reconciled to the cent, rounding modes, voiding, warnings→DQ, drift grace, Active Share 2-day DQ, no-trade price), data (PIT filtering, leakage canary, real raw-response parsers), features, portfolio, end-to-end (1-day closed loop + full 24-day synthetic competition).

## Output files

| Path | Content |
|---|---|
| `out/D-Plan_<team>_<date>.json` | daily D-Plan (`run_daily.py`) |
| `logs/runs/YYYYMMDD/` | features/, scores/, evidence_graph.json, id_map.json, validation.json, portfolio_reports.json (incl. PIT reads) |
| `data/raw/YYYYMMDD/<source>/` + `manifest.json` | raw responses with url, fetched_at, content_as_of, available_at, sha256, parser_version, authority |
| `data/history/*.parquet` | normalized PIT tables |
| `sim_runs/<run_id>/` | strategy/competition/unconfirmed config snapshots, dplan/, settlement/, validation/, logs/, daily.csv, summary.json |

## Round 03 additions

```bat
:: competition run (blocked if agent/ or config/ has uncommitted changes)
.venv\Scripts\python.exe agent\run_daily.py --date 2026-10-02 --mode replay --config config\strategy_quant_v1.yaml --competition

:: 24-day simulation of Quant Core v1
.venv\Scripts\python.exe agent\run_sim.py --config config\strategy_quant_v1.yaml --start 2026-08-28 --days 24
:: research-only stress
.venv\Scripts\python.exe agent\run_sim.py --config config\strategy_quant_v1.yaml --start 2026-08-28 --days 24 --cost-mult 1.5 --slippage 0.002 --light

:: data
.venv\Scripts\python.exe agent\data\fetchers\etf_holdings.py --all            :: real active-ETF holdings (run daily)
.venv\Scripts\python.exe agent\data\fetchers\corporate_actions.py --start 2024-03-01 --end 2026-10-02
.venv\Scripts\python.exe agent\data\fetchers\revenue_dates.py --observe        :: MOPS first-seen (run daily, 1st-12th)
.venv\Scripts\python.exe agent\data\overnight.py --start 2024-03-01 --end 2026-10-02 --taifex

:: research
.venv\Scripts\python.exe agent\research\evaluate.py --random-only
.venv\Scripts\python.exe agent\research\evaluate.py --batch main2 --workers 12
.venv\Scripts\python.exe agent\research\sensitivity.py --ids HN_rev,HN_full,HN_trend
.venv\Scripts\python.exe agent\research\evaluate.py --batch sens --extra reports\sensitivity_strategies.yaml --groups sensitivity
.venv\Scripts\python.exe agent\research\analyze.py --inputs reports\leaderboard_main2.csv reports\leaderboard_sens.csv reports\leaderboard_stress.csv
.venv\Scripts\python.exe agent\research\active_share_report.py --run sim_runs\quant_v1_W5_full
.venv\Scripts\python.exe agent\tools\benchmark.py --date 2026-10-02 --config config\strategy_quant_v1.yaml
```

Turnover controls (`turnover:` in strategy YAML): `score_ema_alpha`, `entry_rank`, `hold_rank`, `min_holding_days`,
`extreme_exit_rank`, `swap_score_margin`, `rebalance_threshold` (alias `no_trade_band`), `turnover_penalty_lambda`,
`turnover_cost_score_units`, `rebalance_every`, `max_new_names_per_day`, `max_daily_changes`. Round-02 configs keep working.
Strategy state (score EMA, entry dates) is carried in `Settlement.agent_state` (our own book, not official).
Odd-share holdings (stock dividends) are locked as NO_TRADE because derive-orders.v2 would emit a non-lot order (NC-7).
Feature cache: `data/cache/features/<FEATURE_VERSION>_<table-fingerprint>/` (safe to delete).

## Round 04 additions (LLM layer, Crash Guard)

```bat
:: LLM narrative with the deterministic mock (no API); real providers need .env + config/llm.yaml model id
.venv\Scripts\python.exe agentun_daily.py --date 2026-10-02 --config config\strategy_quant_v1.yaml --narrative llm --llm-provider mock
:: replay previously logged LLM responses (no API calls)
.venv\Scripts\python.exe agentun_daily.py --date 2026-10-02 --config config\strategy_quant_v1.yaml --narrative llm --llm-provider replay
:: evaluation
.venv\Scripts\python.exe agentesearch\llm_eval.py --provider mock --windows W5,W1 --days 10
.venv\Scripts\python.exe agentesearch\evaluate.py --r04 --batch r04 --workers 10
.venv\Scripts\python.exe agentesearch\event_study.py --runs "sim_runsound0304\L2_events0__W*__official"
.venv\Scripts\python.exe agent	ools\llm_runtime_benchmark.py --start 2026-09-15 --days 10 --latency 3
.venv\Scripts\python.exe agent\dataetchers\material_info.py --dates-from reports\windows.json --lookback 10
```
Rules enforced in code: the LLM never produces target_weight / shares / orders / cash / Active Share / NAV /
fees / posture / funding_for; tickers, sources and fact ids come only from program-provided lists; every
number must be grounded in the input; failures fall back to templates / no adjustment. Strategy YAML may
contain an `llm:` block (merged over config/llm.yaml) and `crash_guard: {enabled: true}`.

## Round 05 additions (operational readiness)

```
scripts\competition_dry_run.ps1 -TeamId TEAM_TEST [-Date 2026-10-27] [-Mode dry-run|competition|historical] [-Initial]
scripts\refresh_daily.ps1 | scripts\preflight.ps1 | scripts\archive_daily.ps1
.venv\Scripts\python.exe agent\competition_day.py --date 2026-10-27 --team-id TEAM_TEST --mode dry-run
.venv\Scripts\python.exe agent\ops\healthcheck.py --date 2026-10-27 --mode competition
.venv\Scripts\python.exe agent\ops\reconcile.py --date 2026-10-26 [--accept-official --confirmed-by NAME]
.venv\Scripts\python.exe agent\ops\llm_review.py --llm-config config\llm_narrative_v1.yaml --days 15
```
The agent never uploads: it produces `submissions\YYYYMMDD\FINAL_CANDIDATE.txt` + `FINAL\D-Plan_<team>_<date>.json`
for a human to upload (submission mechanism NC-1 unconfirmed). See `docs\COMPETITION_DAILY_RUNBOOK.md`.

## Round 06 additions (rehearsal, reliability)

```
python agent\ops\rehearsal.py --start-date 2026-08-28 --days 24 --mode replay|clock-sim
python agent\ops\settlement_entry.py --date D --file A.csv --verify-file B.csv --operator NAME --source SRC [--confirm]
python agent\ops\final.py show|prepare|replace-final --date D ...
python -m agent.submission.receipt --date D --team-id T --sha256 S --receipt-id R --official-status accepted --confirmed-by NAME
python agent\ops\compare_candidates.py <pkgA> <pkgB>
python agent\ops\soak.py --iterations 100 | security_scan.py | readiness.py [--run-tests] | verify_release.py --sha S [--smoke]
python agent\ops\backup.py backup|restore|verify ;  restore_drill.py --state <rehearsal dir> --next-date D
python agent\competition_day.py ... --offline      (no network: store probes only)
```
