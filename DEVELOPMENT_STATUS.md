# DEVELOPMENT STATUS

> Last update: 2026-10-05 (Round 02). Detailed report: `logs/development/ROUND_02_DEVELOPMENT_REPORT.md`.
> All content is AI-generated and must be reviewed by a human before use (company policy).

## Phases

| Phase | Status | Notes |
|---|---|---|
| P1 Competition Engine | ✅ done | official rules config, RuleBook, derive-orders.v2 (Decimal), fees (4 rounding modes), Active Share (4 modes), compliance reports (PASS/FAIL/WARNING/UNKNOWN) |
| P1 D-Plan Validator | ✅ done | JSON Schema v4.2 + C1/C2/C6/C9/C11/C12/C13/C14, ID rules, coverage, action, filename, team, trade date, universe, lot, Active Share; C3/C4/C5/C7/C8/C10 = NOT_IMPLEMENTED |
| P2 NAV Simulator | ✅ done | VWAP fills, fees/tax, close NAV, accrued dividends, void+warning on violations, 5-day drift grace, 3 warnings → DQ, Active Share 2-day DQ, MDD both ways, turnover |
| P3 PIT Data Pipeline | ✅ core done | TWSE/TPEx prices + 三大法人 fetchers (live-tested), FinMind revenue, raw snapshots + manifest (sha256), HistoryStore, PITView + leakage canary, Live/Replay providers. MOPS/TAIFEX = stubs |
| P4 Quant Features | ✅ v1 | 12 features + market breadth; missing → NaN |
| P7 Baseline Portfolio | ✅ v1 | turnover-aware selection, tiered/equal weights, water-fill caps, lot feasibility, no-trade band, cash band, Active Share adjustment, fallback |
| P8 Risk + Compliance | ✅ v1 | pre-trade, post-trade estimate, ±5% stress; fallback if any FAIL |
| P9 Evidence Graph / D-Plan | ✅ v1 | graph → export (renumber) → validate; posture & funding_for derived; quant-only templates |
| P5 LLM | ⏸ interfaces/stubs only | `agent/llm/interfaces.py`, `schemas.py` (by design this round) |
| P10 Memory | ⏸ not started | |
| P11 Walk-forward | ✅ smoke | synthetic 24-day + real W5 (2026-08-31~10-02, 23 days) × 4 baselines |

## Tests
`.venv\Scripts\python.exe -m pytest` → **78 passed, 0 failed** (≈70–100 s; the 24-day synthetic e2e dominates).

## W5 replay (real TWSE/TPEx data, synthetic Active-ETF holdings), 23 trading days
| Method | Total return | MDD | Cum. turnover | Fees+tax | Violations |
|---|---|---|---|---|---|
| B0 score tiered | −2.21% | 7.28% | 400% | 1.01% | 0 |
| B1 score equal | −0.64% | 7.40% | 377% | 0.95% | 0 |
| B2 20d momentum | −1.50% | 9.15% | 478% | 1.23% | 0 |
| B3 5d institutional | +4.75% | 2.50% | 679% | 1.90% | 0 |
| Ref: EW 150 buy&hold (08/28→10/02 close) | +3.75% | – | – | – | – |
One window, not statistically meaningful; dividends not simulated (no corporate-action feed yet).

## Known Issues
1. **Turnover too high** (13–27%/day after day 1) → costs ~1–2% of NAV per month. Needs stronger hysteresis / min holding period / score smoothing (strategy work, next round).
2. Active-ETF holdings are **synthetic** → Active Share results are mechanism tests only.
3. No corporate-action data (TWT49U) → replay ignores dividends/stock splits.
4. Revenue availability is an assumption (10th of next month); no first-seen timestamps.
5. No overnight US/SOX/ADR/TAIFEX data; market view uses breadth only.
6. Live mode not exercised in a real 19:30–08:55 window; no submission module.
7. VWAP uses Decimal 28 significant digits; official rounding/precision of 成交均價 unknown (sub-cent differences).
8. `data/raw` is ~575 MB (TPEx dailyQuotes stores all securities) — consider compression.
9. Project is not a git repo → `code_version` = `pkg-sha256:<12 hex>` of agent/ + config/.

## Unconfirmed Rules (see `config/unconfirmed_rules.yaml`)
active_share_mode, cash_equal_25_allowed, fee_rounding_mode, no_trade_execution_mode, mdd_include_initial_nav, daily_last_submission_wins, official_settlement_source, first_trade_date, bugfix_during_competition_allowed, check_code_disposition, c12_estimate_includes_fees, stock_dividend_odd_shares, holdings_count_inclusive.
Evidence for NC-15: TWSE had no trading on 2025-10-24 (Fri, 光復節 observed for Sat 10/25) in our backfill → 2026-10-26 (Mon, for Sun 10/25) is plausibly a holiday too.

## Next Steps
1. Turnover/stability tuning of the baseline (rank smoothing, min holding days, higher swap margin) + multi-window evaluation (W1–W5).
2. Real Active-ETF holdings parsers (issuer sites) → replace synthetic benchmarks.
3. Corporate actions (TWT49U / TPEx) + MOPS revenue first-seen polling.
4. git init + clean-tree enforcement for `code_version`.
5. Live dry run (T-1 19:30 → T 07:30) and a submission mechanism once the organiser clarifies NC-1.
6. Then Phase 5 (LLM text writers / event extraction) behind the existing interfaces.
