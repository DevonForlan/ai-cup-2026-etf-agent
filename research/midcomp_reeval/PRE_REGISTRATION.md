# PRE-REGISTRATION — mid-competition strategy re-evaluation (Issue #14, round 2)

RESEARCH ONLY. No production file, `config/strategy_quant_v1.yaml` (sha256 `f34fa02e…d2e0`), FINAL, D-Plan or scheduler is
touched. Written and committed **before any result of this round exists**. The competition days 2026-10-27 → 11-02 are
**not** used for selection, tuning or thresholds; they appear only in a descriptive table (§7).

## 1. Baseline and data
- Baseline = frozen Quant v1 exactly (`rebalance_every=100`). Pipeline runs: real `agent.run_sim.simulate`, light mode,
  official costs, fresh start from cash, 24 trading days.
- Windows: the same 90 DENSE24 windows as round 1 (starts 2024-07-01 … 2026-09-10, step 6); DISCOVERY = start < 2025-07-01
  (41), OOS = start ≥ 2025-07-01 (49). Walk-forward rule: every parameter is fixed below; a variant is judged on OOS only,
  after DISCOVERY has been looked at to decide whether it is "carried" (same rule as round 1).
- Gate R0: the new replay engine's identity strategy must reproduce the frozen NAV (mean |Δ| of 24-day return ≤ 0.05 pp);
  otherwise the replay variants are not reported.

## 2. Families (each separate; nothing is mixed)
**A. Rebalance frequency** — real pipeline, only `turnover.rebalance_every` changed in an in-memory copy of the config:
A100 (baseline), A20, A10, A5, A3, A1. Costs / turnover come from the pipeline.

**B. Drawdown trigger** — replay on the frozen book; the portfolio's own NAV drawdown from its running peak (including
the initial 1e9) is checked at each close and acts from the next trading day. Thresholds −3 %, −5 %, −7 %.
- B_CASH_x: once triggered, hold invested share at 76 % (cash 24 %, below the official 25 % cap) for the rest of the window.
- B_RERANK_x: once triggered, switch once to the book of the daily-re-ranked run (A1) of that day and hold its shares.
6 variants.

**C. Rank-aware trigger** — proxy rank = percentile of the portfolio's cumulative return among a **heterogeneous pool of
random long-only portfolios** (k ∈ {10, 20, 30, 50} names, 250 each, equal weight, same start day, 0.1425 % buy cost), evaluated
from day 4. Trigger = percentile < 25 % (C25) or < 10 % (C10), once per window, acting next day:
C_RERANK (switch to A1 book), C_CASH (cash 24 %), C_CONC (top-20 names, w², i.e. round-1 F9b "concentrate when behind").
Both directions are tested on purpose: no assumption that "behind ⇒ more risk" is right. 6 variants.

**D. Tactical overlay (cash / regime)** — new, simple, public signals; all computed with data ≤ T-1 close (US overnight
`available_at` ≤ 07:00), as in round 1:
- D1: breadth(>20d MA) < 35 % **and** EW 20-day trend < 0 → cash 24 % while true (recomputed daily).
- D2: EW 20-day realised vol above its trailing-250-day 80th percentile → cash 24 % while true.
- D3: SOX 20-day return < −10 % → cash 24 % while true.
- D4: D1 ∨ D2 ∨ D3.
- Round-1 overlays re-used unchanged, no re-tuning: F1b, F2a (short-term RS tilt), F3a (foreign-flow tilt), F9b.
8 variants. Cash cap: every variant is clipped to cash < 25 % (official) — never above.

## 3. Metrics per variant (24-day windows)
median / mean return; hit rate (return > 0); MDD (mean and worst); worst window; turnover; transaction cost (TWD);
downside tail = mean of the worst 10 % windows (CVaR10); paired excess vs baseline per window (mean, median, % windows
better), OOS and DISCOVERY separately; sign-flip permutation p (two-sided, 20 000) on OOS excess, Holm-adjusted over all
variants; block-bootstrap 95 % CI on OOS mean excess.
**Top-12 / Top-30 proxy** = share of windows in which the window return is above the 98.2 nd / 95.5 th percentile
(12/659, 30/659) of the heterogeneous random pool *at the end of the same window*. This is a crude proxy (real teams are
not random) — only the *difference vs baseline* is read.

## 4. Mid-competition recovery test
Events: windows whose baseline cumulative return at some day k ∈ {4, 5, 6} is in [−5 %, −3 %] (first such k). Primary band as
requested; a secondary band [−6 %, −2 %] is reported for sample size. Strategies (state at k is the baseline book):
KEEP_FROZEN; A5 / A1 re-rank (switch to that run's book at k+1, frozen thereafter); drawdown trigger B_CASH_5 and
B_RERANK_5 forced at k; D4 overlay; rank-aware C25 variants. Outputs over the remaining days: P(final return > 0),
P(beat baseline), mean / median final return, Top-12 / Top-30 proxy, worst remaining-path loss (downside), with n shown.
No result with n < 15 events is treated as evidence on its own.

## 5. Decision rule (fixed before running)
- **PROMOTION_CANDIDATE** only if one variant (a) beats the baseline on OOS mean excess by ≥ +0.50 pp **and** OOS median
  excess > 0, (b) Holm-adjusted p < 0.10 or bootstrap CI excludes 0, (c) is not worse than the baseline on DISCOVERY by more
  than 0.30 pp, (d) does not increase CVaR10 or worst window by more than 1 pp, (e) turnover/cost increase < 0.5 % NAV,
  (f) is above its time-/name-placebos where applicable, (g) keeps 0 official-limit violations.
- **CHANGE_NOW** only if, in addition, the OOS edge is ≥ +1.5 pp with p < 0.01 in both halves of OOS **and** it can be
  deployed with a freeze regression before the next decision cutoff. (Not expected; stated for completeness.)
- otherwise **KEEP_FROZEN_ONLY**. Negative and inconclusive results are reported as such.

## 6. Overfit controls
Parameters fixed in this file; 90 overlapping windows (effective n smaller — blocks of 4 windows in the bootstrap); the
number of variants (A 5 + B 6 + C 6 + D 8 = 25) is declared, p-values are Holm-adjusted; placebos: time-shifted signals for
D1–D4, name-shuffled for F2a / F3a / F9b (50 each).

## 7. Descriptive only
The actual competition path (start 2026-10-27, through the latest history date) is shown for every variant with the
explicit label "post-hoc, n = 1, not used for any decision".
