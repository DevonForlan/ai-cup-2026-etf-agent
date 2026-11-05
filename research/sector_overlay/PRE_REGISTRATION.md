# Issue #41 — Sector-diversification overlay: PRE-REGISTRATION (written before any overlay result was computed)

RESEARCH ONLY. Frozen Quant v1 (sha256 f34fa02e…) is the control and is never written. Date: 2026-11-05.

## 0. Context and bias control
The question was prompted by a −15.65 % cumulative drawdown (11/05 electronics −3.6 %). Recent losses alone are NOT evidence.
The decision therefore rests on the 2025-01 … 2026-10 history windows (DISCOVERY < 2025-07-01 ≤ OOS), the same window sets as
Issue #14 (DENSE24 step 6 = set A, shifted set B). The 5 live days (n = 1) are reported post-hoc and never used to select.
Baseline descriptive fact (control, before overlays): TECH aggregate ≈ 72 % of NAV (≈ 78 % of invested capital) at window starts.

## 1. Definitions
TECH = TWSE industries {半導體業, 電腦及週邊設備業, 電子零組件業, 其他電子業, 通信網路業, 光電業, 電子通路業} from
`research/tactical_overlay/sector_map.csv` (ISIN list, fetched 2026-10-25). Non-TECH receivers = non-TECH names of the
*daily-rebalanced frozen book (A1)* (the Quant's own ranking, no discretionary picks), at most 28 names in total.
Timing: decisions use information ≤ close of T-1. Replay = `study.replay2` (official costs, trades at VWAP, 0.25 % threshold).

## 2. Candidates
| id | rule |
|---|---|
| A BASE | frozen buy-and-hold control |
| B_CAP55/60/65/70 | if TECH NAV share > cap: scale TECH to cap, excess pro rata to non-TECH receivers (A1 weights), 9 %/10 % caps via `lab.enforce` |
| C_BREADTH40 / C_BREADTH30 | only when TECH breadth (share of TECH names above their 20d MA, T-1) < 0.40 / 0.30: apply the 60 % cap |
| D_FLOOR30 / D_N8 | D_FLOOR30: non-TECH ≥ 30 % NAV; D_N8: ≥ 8 non-TECH names (≥ 2 % each) funded pro rata from TECH |
| E_HYBRID65 | cap 65 %; excess split 50 % non-TECH / 50 % cash (cash stays < 25 %) |
| P_CHASE (placebo) | shift 10 % NAV into the sector basket that outperformed over the last 5 days (chasing) |
| P_RANDOM_CAP (placebo) | same cap mechanism on a random 50 %-of-universe group, cap = 0.83 × its day-0 weight (5 seeds / window, mean) |

## 3. Primary metric and gates (all must hold to PROMOTE_V2; any failure ⇒ KEEP_CURRENT)
Primary: mean OOS excess return vs BASE over set A **and** set B (both), sign-flip permutation p (one-sided, Holm over the 11 candidates).
G1 OOS mean excess > 0 in A and B, median ≥ 0, better-window share ≥ 55 %.
G2 Holm-adjusted p < 0.10 in OOS (set A) and same sign in B.
G3 downside: OOS worst window and mean MDD not worse than BASE; at least one of them improves by ≥ 0.5 pp.
G4 beats both placebos (mean OOS excess above the placebo mean and above P_CHASE).
G5 cost / turnover: added cost ≤ 0.10 % of NAV per window; official violations = 0 in every window.
G6 regime robustness: same sign in each calendar half-year with ≥ 3 windows and in the most recent 6 windows (2026H2 slice).
G7 concentration: TECH share falls to ≤ cap on average; Active Share on the live 11/05 book (official function, real ETF holdings) must stay ≥ 40 % (competition requirement 30 %).
G8 recovery test: P(NAV back to the pre-drawdown peak within 24 d | drawdown ≥ 5 %) not worse than BASE.
Mixed evidence ⇒ KEEP_CURRENT; optionally forward shadow only. A small reversible risk-control is preferred to a rewrite.
Negative / insignificant results are kept in the report. Sensitivity of caps is reported, never used to re-select after seeing OOS.
