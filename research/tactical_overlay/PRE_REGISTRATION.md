# Issue #14 — 24-day tactical overlay vs frozen Quant v1: pre-registration

> RESEARCH ONLY. Written and committed **before** any new result was computed (commit timestamp = evidence).
> No change to `config/strategy_quant_v1.yaml`, frozen paths, production scheduler, `run_mode`, submission or
> `auto_upload`. AI-generated research; human review required. Nothing here is investment advice.

## 0. Question

The competition ranks teams on ~24 trading days (2026-10-27 → 2026-11-27). Frozen Quant v1 ranks the 150-stock
universe by monthly-revenue YoY (0.7) / MoM (0.3), holds ~25 names and trades little. Is that horizon-appropriate,
and can a **tactical layer above the frozen core** (cash / tilt / timing / concentration) improve the chance of a
high rank without replacing the core selection?

## 1. Data (point-in-time)

- Local PIT store `data/history` (gitignored): `daily_prices` 2024-03-01 → 2026-10-22 (150-name universe),
  `institutional` (foreign / trust / dealer net), `monthly_revenue` (with `available_at`), `market_overnight`
  (SOX, NDX, SPX, IXIC, TSM ADR, TAIEX night futures, USD/TWD, with `available_at`).
- Optional public downloads (research only, never production): TWSE / TPEx ISIN industry labels (sector map);
  FRED daily series (US 10Y yield, WTI oil, broad USD index) if reachable. If not reachable → `DATA_UNAVAILABLE`.
- Event calendar: FOMC decision dates, US CPI and payroll release dates encoded from public schedules
  (documented in the code; treated as approximate).
- Not available as PIT history: news / geopolitical sentiment → evaluated qualitatively only (`DATA_UNAVAILABLE`).
- **Timing rule:** every signal for trade date T uses only data visible at T 07:00: Taiwan prices / flows through
  T-1 close; overnight US data via `available_at` ≤ T 07:00 (≤ 96 h old); revenue via `available_at`.

## 2. Windows (fixed now; never tuned on 2026-10-27 → 11-27, which is in the future)

- **NOV23**: the 23 non-overlapping 24-day windows of `research/factor_research/results/windows.json`
  (DISCOVERY R01–R11, VALIDATION R12–R17, HOLDOUT R18–R23). Primary inference set.
- **DENSE24**: fresh-start 24-trading-day windows starting every 6 trading days from 2024-07-01; last start such
  that the window ends ≤ 2026-10-22. DISCOVERY = start < 2025-07-01; OOS = start ≥ 2025-07-01. Overlapping
  → block bootstrap (block = 4 consecutive windows).
- **H60 / H120**: fresh-start 60 / 120-trading-day windows, starts every 24 trading days from 2024-07-01.
- Every window starts from initial cash (competition-faithful day-1 build).

## 3. Baseline and benchmarks

- **Frozen Quant v1**: `agent.run_sim.simulate(start, days=N, light=True)` with the frozen config, official costs
  (fee 0.1425% each side, tax 0.3% on sells). Cached NOV23 runs (`runtime/overlay_bt/BASE_V1__*`) are reused.
- **EW universe**: equal-weight 150-name close-to-close return over the same days (entry fee charged once).
- **Random portfolios**: 500 random 25-name equal-weight buy-and-hold portfolios per window (seed 14), entry fee
  and exit fee + tax charged → percentile of each strategy = **rank-like metric**; **top-decile hit** = percentile ≥ 90.

## 4. Horizon study (Part 1)

Per horizon (24 / 60 / 120): mean and median return, excess vs EW universe, hit rate (excess > 0), MDD, turnover,
cost, percentile vs random portfolios, top-decile and top-quartile hit rates, dispersion; per-day excess.
Signal decay: cross-sectional rank IC of the frozen revenue score vs forward 5 / 24 / 60 / 120-day returns.

**HORIZON_MISMATCH rule (fixed):**
- **HIGH** if DENSE24 hit rate < 55% **and** per-day excess at 60D or 120D ≥ 1.5 × the 24D per-day excess.
- **LOW** if DENSE24 hit rate ≥ 60% **and** 24D per-day excess ≥ 0.8 × max(60D, 120D per-day excess).
- **MEDIUM** otherwise.

## 5. Overlay families (Part 2) — parameters fixed now

All overlays act on the **frozen daily holdings** through a replay engine: same names (unless stated), weights
transformed, re-normalised to the frozen invested share, official caps (2330 ≤ 23.5%, others ≤ 9%, cash < 25%,
holdings 20–30), a trade happens only when |Δw| ≥ 0.25% NAV, official costs. Replay engine must first reproduce
the frozen NAV (gate R0: |window-return difference| ≤ 0.30 pp on NOV23, mean |daily NAV diff| ≤ 0.10%).
If R0 fails, overlays are run inside the frozen pipeline instead, or reported as not evaluable.

| Family | Variant a | Variant b |
|---|---|---|
| F1 market-regime cash | reuse the risk-overlay round (pre-registered, KEEP_BASELINE) | LOW_CASH: invested share raised to 97% when breadth ≥ 0.50, else frozen |
| F2 short-term momentum tilt | 20D return rank among holdings: top third ×1.25, bottom third ×0.75 | same with 60D |
| F3 foreign-flow tilt | 20D Σforeign_net / 20D Σamount rank tilt (×1.25 / ×0.75) | 5D version |
| F4 volatility | 50/50 blend of frozen and inverse-20D-vol weights | names in top 20D-vol quintile ×0.5 |
| F5 sector leadership | holdings in the top-3 sectors by 20D sector EW return ×1.25, bottom-3 ×0.75 | 60D version |
| F6 US lead / semis | semiconductor names ×1.2 if SOX 20D return > 0 else ×0.8 | TSM ADR 5D instead of SOX 20D |
| F7 macro-event de-risk | invested share −10% on the session before FOMC / CPI / payroll (US time), restored next day | −20% |
| F8 rates / USD / oil | USD/TWD 20D change > +1% → invested share −5% | US 10Y 20D change > +25 bp → −5% (if data) |
| F9 concentration (rank objective) | keep the 20 largest frozen holdings, re-normalise | 20 largest, weights ∝ frozen weight² |
| F10 news / geopolitics | `DATA_UNAVAILABLE` → qualitative only | — |

Discovery selection: per family, the variant with the higher DISCOVERY mean Δreturn goes to OOS. If both are
≤ 0 on DISCOVERY the family is marked *not carried* (its OOS numbers are still reported).

## 6. Gate (OOS only; all must hold for PROMOTION_CANDIDATE)

- **G1** mean NOV23-OOS Δreturn vs frozen v1 (after costs) ≥ +0.50 pp per window.
- **G2** paired wins ≥ 7 / 12 NOV23-OOS windows.
- **G3** DENSE24-OOS block-bootstrap (block 4, 2000 draws) one-sided 90% lower bound of mean Δ > 0.
- **G4** mean Δ > 95th percentile of 50 placebos (same action, random name assignment or random time shift).
- **G5** mean MDD not worse by > 1.0 pp and worst-window MDD not worse by > 2.0 pp.
- **G6** top-decile hit rate (vs random portfolios) ≥ frozen v1's.
- **G7** signal computable before the T-1 cutoff from available data; 0 compliance violations in replay.

Multiple testing: ~18 variants; results also reported with Holm-adjusted p-values (informative, not a gate).

## 7. Outcome mapping (fixed)

- **PROMOTION_CANDIDATE**: ≥ 1 overlay passes G1–G7. Even then: no production change without a separate
  Owner-approved PROMOTION Issue, frozen-pipeline implementation, regression and review.
- **ADD_ADVISORY_LAYER_ONLY**: no overlay passes, but ≥ 1 signal has OOS predictive evidence for 24D market /
  portfolio outcomes (signal study p < 0.05 with the same sign in DISCOVERY and OOS) → monitoring / narrative only,
  no effect on orders.
- **KEEP_FROZEN_ONLY**: otherwise.

Negative and inconclusive results are reported in full.
