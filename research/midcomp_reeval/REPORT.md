# REPORT — mid-competition strategy re-evaluation (Issue #14, round 2)

**RESEARCH ONLY. No production change. Frozen Quant v1 (`f34fa02e…d2e0`) untouched; no FINAL / D-Plan / scheduler change.**
Pre-registration: `PRE_REGISTRATION.md` (commit `c0b0168`, written before any result). Code: `run_rebalance.py`, `study.py`,
`analyze_midcomp.py`, `extra.py`, `make_report.py`. Raw outputs: `results/*.csv`, `results/*.json`, `results/*.log`.

## 0. Conclusion
**KEEP_FROZEN_ONLY.** Of 25 pre-registered variants, 24 are negative or inconclusive out of sample. One (round-1 `R1_F9b`:
hold the top-20 names with weight w²) passes every pre-registered gate, but that is **not** a promotion case (§5).

## 1. Method (as pre-registered)
- 90 DENSE24 windows (24 trading days, step 6, 2024-07-01 … 2026-09-10): 41 DISCOVERY, 49 OOS (start ≥ 2025-07-01).
  An extension set B (90 windows shifted by 3 days) is used **only** for the recovery sample size; it overlaps A heavily (not independent).
- Family A: the real frozen pipeline (`agent.run_sim.simulate`, official costs), only `turnover.rebalance_every` changed in memory.
  Families B / C / D: replay engine on the frozen book (state-dependent policies, official fees / tax, caps, cash < 25 %).
- Gate R0 (replay vs frozen daily NAV): mean |Δ| 0.000012 pp, max 0.0003 pp → **PASS**.
  Cross-check on reality: the same engine on the actual start 2026-10-27 (5 trading days) gives −3.82 % / MDD 7.01 %, the
  official 11/02 figures (cumulative −3.82 %, MDD 7.01 %).
- Statistics: paired excess vs baseline per window; sign-flip permutation p (OOS), Holm over all 25 variants, block-bootstrap CI (block 4);
  placebos (20: time-shifted signals for D1–D4, name-shuffled for F2a / F3a / F9b).
- Top-12 / Top-30 proxy: share of windows whose return exceeds the 98.2nd / 95.5th percentile of a pool of 2 000 random long-only
  portfolios (k = 10/20/30/50). **Crude proxy**: real competitors are not random; read differences only.
- Returns here are daily-NAV returns (dividends receivable not accrued), identical for baseline and every variant.

## 2. Results — all 24-day windows (n = 90)
| variant | n | median% | mean% | hit% | MDD% | worst% | CVaR10% | turnover(xNAV) | cost(M TWD) | Top12% | Top30% | ex_mean pp | ex_median pp | better% | p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | 90 | 6.78 | 5.95 | 74.4 | 7.75 | -24.91 | -13.78 | 1.93 | 4.37 | 6.7 | 18.9 | -0.3 | -0.39 | 38.0 | 0.05 |
| A10 | 90 | 6.25 | 6.06 | 76.7 | 7.85 | -25.89 | -14.24 | 1.53 | 3.16 | 5.6 | 15.6 | -0.19 | -0.06 | 46.0 | 0.131 |
| A20 | 90 | 6.6 | 6.11 | 77.8 | 7.85 | -25.28 | -14.24 | 1.5 | 3.08 | 5.6 | 14.4 | -0.14 | -0.03 | 36.0 | 0.178 |
| A3 | 90 | 6.0 | 5.82 | 75.6 | 7.83 | -25.48 | -13.99 | 1.78 | 3.92 | 7.8 | 14.4 | -0.43 | -0.3 | 33.0 | 0.006 |
| A5 | 90 | 5.89 | 5.89 | 77.8 | 7.85 | -26.14 | -14.07 | 1.66 | 3.55 | 7.8 | 13.3 | -0.36 | -0.31 | 41.0 | 0.011 |
| BASE(=A100) | 90 | 6.29 | 6.25 | 78.9 | 7.78 | -25.28 | -14.11 | 0.98 | 1.47 | 5.6 | 14.4 | 0.0 | 0.0 | 0.0 |  |
| B_CASH_3 | 90 | 5.76 | 5.57 | 74.4 | 7.2 | -22.27 | -12.53 | 1.1 | 2.03 | 3.3 | 12.2 | -0.68 | -0.54 | 18.0 | 0.0 |
| B_CASH_5 | 90 | 5.83 | 5.75 | 76.7 | 7.35 | -22.14 | -12.7 | 1.07 | 1.92 | 3.3 | 13.3 | -0.5 | 0.0 | 17.0 | 0.0 |
| B_CASH_7 | 90 | 6.21 | 5.99 | 77.8 | 7.45 | -23.25 | -13.08 | 1.03 | 1.73 | 3.3 | 11.1 | -0.25 | 0.0 | 12.0 | 0.014 |
| B_RERANK_3 | 90 | 6.44 | 6.1 | 77.8 | 7.76 | -23.78 | -13.96 | 1.16 | 2.05 | 5.6 | 12.2 | -0.15 | 0.0 | 28.0 | 0.061 |
| B_RERANK_5 | 90 | 6.41 | 6.12 | 77.8 | 7.77 | -22.55 | -13.97 | 1.19 | 2.15 | 5.6 | 14.4 | -0.13 | 0.0 | 19.0 | 0.086 |
| B_RERANK_7 | 90 | 7.07 | 6.14 | 77.8 | 7.73 | -24.18 | -13.94 | 1.15 | 2.0 | 5.6 | 13.3 | -0.11 | 0.0 | 11.0 | 0.154 |
| C10_CASH | 90 | 5.77 | 6.08 | 76.7 | 7.47 | -22.14 | -12.81 | 1.03 | 1.69 | 5.6 | 14.4 | -0.17 | 0.0 | 8.0 | 0.11 |
| C10_CONC | 90 | 6.1 | 6.34 | 77.8 | 7.78 | -25.88 | -14.26 | 1.21 | 2.14 | 5.6 | 15.6 | 0.09 | 0.0 | 14.0 | 0.14 |
| C10_RERANK | 90 | 6.2 | 6.23 | 77.8 | 7.71 | -22.36 | -13.7 | 1.01 | 1.57 | 5.6 | 14.4 | -0.01 | 0.0 | 13.0 | 0.799 |
| C25_CASH | 90 | 5.75 | 5.96 | 75.6 | 7.23 | -22.14 | -12.13 | 1.05 | 1.81 | 5.6 | 13.3 | -0.29 | 0.0 | 17.0 | 0.044 |
| C25_CONC | 90 | 6.15 | 6.41 | 76.7 | 7.77 | -25.88 | -14.07 | 1.35 | 2.58 | 6.7 | 15.6 | 0.16 | 0.0 | 29.0 | 0.044 |
| C25_RERANK | 90 | 6.16 | 6.07 | 76.7 | 7.77 | -22.36 | -14.04 | 1.05 | 1.7 | 5.6 | 13.3 | -0.18 | 0.0 | 16.0 | 0.054 |
| D1_BREADTH_TREND | 90 | 6.15 | 5.97 | 74.4 | 7.59 | -23.35 | -13.75 | 1.27 | 2.36 | 5.6 | 13.3 | -0.27 | -0.11 | 9.0 | 0.0 |
| D2_VOL | 90 | 6.18 | 5.59 | 77.8 | 7.44 | -23.24 | -13.76 | 1.07 | 1.81 | 3.3 | 10.0 | -0.66 | 0.0 | 8.0 | 0.0 |
| D3_SOX | 90 | 6.21 | 6.09 | 78.9 | 7.6 | -25.27 | -14.04 | 1.11 | 1.87 | 4.4 | 12.2 | -0.16 | 0.0 | 6.0 | 0.002 |
| D4_ANY | 90 | 6.04 | 5.56 | 74.4 | 7.32 | -23.47 | -13.12 | 1.23 | 2.32 | 3.3 | 12.2 | -0.69 | -0.46 | 9.0 | 0.0 |
| R1_F1b | 90 | 6.3 | 6.37 | 77.8 | 8.0 | -26.07 | -14.48 | 1.07 | 1.69 | 5.6 | 17.8 | 0.12 | 0.1 | 68.0 | 0.003 |
| R1_F2a | 90 | 6.1 | 6.29 | 75.6 | 7.99 | -25.35 | -14.33 | 1.97 | 4.47 | 5.6 | 18.9 | 0.04 | -0.04 | 47.0 | 0.633 |
| R1_F3a | 90 | 6.51 | 6.06 | 76.7 | 7.78 | -26.03 | -14.18 | 1.71 | 3.7 | 5.6 | 14.4 | -0.18 | -0.23 | 32.0 | 0.004 |
| R1_F9b | 90 | 6.75 | 6.71 | 76.7 | 8.01 | -25.9 | -14.27 | 1.84 | 4.08 | 8.9 | 23.3 | 0.46 | 0.45 | 63.0 | 0.001 |

## 3. Results — OOS only (n = 49)
| variant | n | median% | mean% | hit% | MDD% | worst% | CVaR10% | turnover(xNAV) | cost(M TWD) | Top12% | Top30% | ex_mean pp | ex_median pp | better% | p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | 49 | 10.28 | 9.55 | 87.8 | 7.56 | -21.06 | -8.77 | 1.9 | 4.32 | 0.0 | 12.2 | -0.1 | -0.03 | 49.0 | 0.652 |
| A10 | 49 | 10.18 | 9.52 | 87.8 | 7.68 | -21.86 | -9.19 | 1.47 | 3.01 | 0.0 | 8.2 | -0.13 | -0.06 | 49.0 | 0.514 |
| A20 | 49 | 10.19 | 9.59 | 89.8 | 7.71 | -21.38 | -9.23 | 1.47 | 3.07 | 0.0 | 8.2 | -0.06 | -0.14 | 37.0 | 0.736 |
| A3 | 49 | 9.85 | 9.29 | 89.8 | 7.64 | -21.56 | -9.02 | 1.73 | 3.83 | 0.0 | 8.2 | -0.36 | -0.31 | 41.0 | 0.104 |
| A5 | 49 | 9.85 | 9.29 | 89.8 | 7.69 | -21.81 | -9.11 | 1.61 | 3.47 | 0.0 | 4.1 | -0.36 | -0.33 | 41.0 | 0.065 |
| BASE(=A100) | 49 | 9.98 | 9.65 | 87.8 | 7.67 | -22.23 | -9.16 | 0.97 | 1.45 | 0.0 | 8.2 | 0.0 | 0.0 | 0.0 |  |
| B_CASH_3 | 49 | 8.42 | 8.53 | 87.8 | 7.03 | -19.47 | -8.21 | 1.1 | 2.08 | 0.0 | 4.1 | -1.11 | -0.74 | 8.0 | 0.0 |
| B_CASH_5 | 49 | 8.42 | 8.77 | 87.8 | 7.24 | -19.74 | -8.33 | 1.09 | 2.0 | 0.0 | 6.1 | -0.88 | -0.29 | 16.0 | 0.0 |
| B_CASH_7 | 49 | 9.64 | 9.15 | 87.8 | 7.35 | -20.49 | -8.54 | 1.04 | 1.79 | 0.0 | 4.1 | -0.49 | 0.0 | 10.0 | 0.002 |
| B_RERANK_3 | 49 | 10.22 | 9.52 | 87.8 | 7.62 | -22.23 | -9.1 | 1.16 | 2.07 | 0.0 | 4.1 | -0.13 | 0.0 | 31.0 | 0.326 |
| B_RERANK_5 | 49 | 10.22 | 9.5 | 87.8 | 7.68 | -22.55 | -9.33 | 1.22 | 2.25 | 0.0 | 8.2 | -0.15 | 0.0 | 20.0 | 0.157 |
| B_RERANK_7 | 49 | 9.94 | 9.43 | 85.7 | 7.64 | -22.65 | -9.36 | 1.19 | 2.15 | 0.0 | 6.1 | -0.22 | 0.0 | 12.0 | 0.101 |
| C10_CASH | 49 | 8.91 | 9.23 | 87.8 | 7.44 | -19.23 | -8.8 | 1.02 | 1.67 | 0.0 | 8.2 | -0.41 | 0.0 | 2.0 | 0.007 |
| C10_CONC | 49 | 10.64 | 9.91 | 89.8 | 7.65 | -20.73 | -9.16 | 1.2 | 2.13 | 0.0 | 10.2 | 0.26 | 0.0 | 24.0 | 0.006 |
| C10_RERANK | 49 | 9.98 | 9.56 | 87.8 | 7.62 | -22.23 | -9.18 | 1.01 | 1.59 | 0.0 | 8.2 | -0.09 | 0.0 | 12.0 | 0.195 |
| C25_CASH | 49 | 8.91 | 8.94 | 87.8 | 7.24 | -19.23 | -8.17 | 1.05 | 1.8 | 0.0 | 6.1 | -0.7 | 0.0 | 10.0 | 0.001 |
| C25_CONC | 49 | 10.22 | 10.07 | 89.8 | 7.63 | -20.73 | -8.71 | 1.34 | 2.58 | 0.0 | 10.2 | 0.42 | 0.0 | 41.0 | 0.001 |
| C25_RERANK | 49 | 9.95 | 9.31 | 85.7 | 7.68 | -22.23 | -9.27 | 1.05 | 1.7 | 0.0 | 6.1 | -0.34 | 0.0 | 10.0 | 0.008 |
| D1_BREADTH_TREND | 49 | 9.98 | 9.35 | 87.8 | 7.66 | -22.68 | -9.98 | 1.22 | 2.2 | 0.0 | 6.1 | -0.3 | 0.0 | 2.0 | 0.0 |
| D2_VOL | 49 | 9.52 | 8.77 | 87.8 | 7.27 | -20.57 | -9.08 | 1.07 | 1.85 | 0.0 | 4.1 | -0.88 | -0.48 | 4.0 | 0.0 |
| D3_SOX | 49 | 9.98 | 9.51 | 87.8 | 7.5 | -20.75 | -8.99 | 1.05 | 1.7 | 0.0 | 6.1 | -0.14 | 0.0 | 4.0 | 0.051 |
| D4_ANY | 49 | 9.92 | 8.84 | 87.8 | 7.15 | -19.59 | -8.63 | 1.11 | 1.98 | 0.0 | 6.1 | -0.8 | -0.4 | 6.0 | 0.0 |
| R1_F1b | 49 | 10.46 | 9.89 | 87.8 | 7.91 | -22.85 | -9.56 | 1.06 | 1.67 | 0.0 | 12.2 | 0.24 | 0.22 | 82.0 | 0.0 |
| R1_F2a | 49 | 10.56 | 9.79 | 87.8 | 7.95 | -21.91 | -9.28 | 1.93 | 4.4 | 2.0 | 16.3 | 0.14 | 0.32 | 57.0 | 0.299 |
| R1_F3a | 49 | 10.37 | 9.49 | 87.8 | 7.59 | -21.69 | -8.82 | 1.71 | 3.75 | 0.0 | 8.2 | -0.16 | -0.24 | 43.0 | 0.149 |
| R1_F9b | 49 | 10.77 | 10.51 | 89.8 | 7.96 | -21.02 | -8.73 | 1.85 | 4.19 | 0.0 | 20.4 | 0.86 | 0.76 | 76.0 | 0.0 |

## 4. Pre-registered gates (OOS; a = edge ≥ +0.5 pp & median > 0, b = Holm p < 0.10 or CI > 0, c = DISCOVERY ≥ −0.3 pp, d = tail not worse > 1 pp, e = cost < 0.5 % NAV, f = placebo p < 0.10, g = 0 official-limit violations)
| variant | oos_ex_mean_pp | oos_ex_median_pp | disc_ex_mean_pp | p_signflip | p_holm | ci95_lo_pp | ci95_hi_pp | a_edge | b_sig | c_disc | d_tail | e_cost | f_placebo | g_viol | PASS_ALL |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | -0.1 | -0.03 | -0.54 | 0.652 | 1.0 | -0.64 | 0.45 | n | n | n | Y | Y | Y | Y | n |
| A10 | -0.13 | -0.06 | -0.27 | 0.514 | 1.0 | -0.57 | 0.27 | n | n | Y | Y | Y | Y | Y | n |
| A20 | -0.06 | -0.14 | -0.24 | 0.736 | 1.0 | -0.39 | 0.38 | n | n | Y | Y | Y | Y | Y | n |
| A3 | -0.36 | -0.31 | -0.52 | 0.104 | 1.0 | -0.93 | 0.1 | n | n | n | Y | Y | Y | Y | n |
| A5 | -0.36 | -0.33 | -0.35 | 0.065 | 0.717 | -0.8 | 0.02 | n | n | n | Y | Y | Y | Y | n |
| B_CASH_3 | -1.11 | -0.74 | -0.17 | 0.0 | 0.001 | -1.8 | -0.55 | n | Y | Y | Y | Y | Y | n | n |
| B_CASH_5 | -0.88 | -0.29 | -0.05 | 0.0 | 0.001 | -1.42 | -0.4 | n | Y | Y | Y | Y | Y | n | n |
| B_CASH_7 | -0.49 | 0.0 | 0.03 | 0.002 | 0.039 | -0.94 | -0.11 | n | Y | Y | Y | Y | Y | n | n |
| B_RERANK_3 | -0.13 | 0.0 | -0.18 | 0.326 | 1.0 | -0.4 | 0.11 | n | n | Y | Y | Y | Y | Y | n |
| B_RERANK_5 | -0.15 | 0.0 | -0.11 | 0.157 | 1.0 | -0.31 | 0.07 | n | n | Y | Y | Y | Y | Y | n |
| B_RERANK_7 | -0.22 | 0.0 | 0.02 | 0.101 | 1.0 | -0.47 | 0.04 | n | n | Y | Y | Y | Y | Y | n |
| C10_CASH | -0.41 | 0.0 | 0.13 | 0.007 | 0.097 | -0.69 | -0.15 | n | Y | Y | Y | Y | Y | n | n |
| C10_CONC | 0.26 | 0.0 | -0.12 | 0.006 | 0.088 | 0.14 | 0.44 | n | Y | Y | Y | Y | Y | Y | n |
| C10_RERANK | -0.09 | 0.0 | 0.08 | 0.195 | 1.0 | -0.22 | 0.04 | n | n | Y | Y | Y | Y | Y | n |
| C25_CASH | -0.7 | 0.0 | 0.21 | 0.001 | 0.018 | -1.12 | -0.27 | n | Y | Y | Y | Y | Y | n | n |
| C25_CONC | 0.42 | 0.0 | -0.16 | 0.001 | 0.011 | 0.23 | 0.65 | n | Y | Y | Y | Y | Y | Y | n |
| C25_RERANK | -0.34 | 0.0 | 0.01 | 0.008 | 0.104 | -0.64 | -0.08 | n | n | Y | Y | Y | Y | Y | n |
| D1_BREADTH_TREND | -0.3 | 0.0 | -0.24 | 0.0 | 0.001 | -0.56 | -0.1 | n | Y | Y | Y | Y | n | n | n |
| D2_VOL | -0.88 | -0.48 | -0.39 | 0.0 | 0.001 | -1.52 | -0.41 | n | Y | n | Y | Y | n | n | n |
| D3_SOX | -0.14 | 0.0 | -0.18 | 0.051 | 0.61 | -0.33 | 0.04 | n | n | Y | Y | Y | n | n | n |
| D4_ANY | -0.8 | -0.4 | -0.55 | 0.0 | 0.001 | -1.46 | -0.29 | n | Y | n | Y | Y | n | n | n |
| R1_F1b | 0.24 | 0.22 | -0.02 | 0.0 | 0.003 | 0.12 | 0.38 | n | Y | Y | Y | Y | Y | Y | n |
| R1_F2a | 0.14 | 0.32 | -0.08 | 0.299 | 1.0 | -0.25 | 0.5 | n | n | Y | Y | Y | Y | Y | n |
| R1_F3a | -0.16 | -0.24 | -0.21 | 0.149 | 1.0 | -0.47 | 0.16 | n | n | Y | Y | Y | Y | Y | n |
| R1_F9b | 0.86 | 0.76 | -0.03 | 0.0 | 0.004 | 0.43 | 1.33 | Y | Y | Y | Y | Y | Y | Y | Y |

Placebos (OOS subset): {"D1_BREADTH_TREND": {"actual_oos_ex_subset": -0.0029845650361978037, "placebo_mean": -0.0035782081002979985, "placebo_p": 0.35}, "D2_VOL": {"actual_oos_ex_subset": -0.00836346758109284, "placebo_mean": -0.0036036257441092365, "placebo_p": 1.0}, "D3_SOX": {"actual_oos_ex_subset": -0.0012330776918578756, "placebo_mean": -0.0021138285878931668, "placebo_p": 0.3}, "D4_ANY": {"actual_oos_ex_subset": -0.0075109123877391505, "placebo_mean": -0.006004066918030327, "placebo_p": 0.75}, "R1_F2a": {"actual_oos_ex_subset": 0.002046867769119367, "placebo_mean": -0.014929650637630654, "placebo_p": 0.0}, "R1_F3a": {"actual_oos_ex_subset": -0.0013796258280293872, "placebo_mean": -0.014891758796348704, "placebo_p": 0.0}, "R1_F9b": {"actual_oos_ex_subset": 0.011644688027122867, "placebo_mean": -0.017724128210077777, "placebo_p": 0.0}}

Reading: the cash / de-risk variants (B_CASH, C_CASH, D1–D4) mostly lower MDD and the worst window a little but **cost
return** (−0.1 … −1.1 pp OOS; 8 of 9 have Holm p ≤ 0.10 in the *negative* direction) — the sample is dominated by up-windows. Higher rebalance frequency is
**worse** monotonically (A3 / A5 −0.36 pp OOS, higher cost, p 0.07–0.10; A1 −0.30 pp over all windows, p 0.05; A20 / A10 ≈ −0.1 pp,
n.s.). Re-rank on drawdown / rank (B_RERANK, C_RERANK) is n.s. or negative. Tactical D-overlays are negative and not better than
their time-shift placebos. The only positive families are **concentration** variants (R1_F9b, C25_CONC, C10_CONC) and a tiny
F1b (+0.24 pp, +0.14 pp in round 1) — see §5.

## 5. Why `R1_F9b` is not a promotion case
`R1_F9b` passes gates a–g (OOS +0.86 pp mean / +0.76 pp median, p < 0.001, Holm 0.004, CI [+0.43, +1.33], placebo 0/20). The
pre-registered rule is "PROMOTION_CANDIDATE **only if** …" (necessary, not sufficient). It is rejected for these reasons:

1. **Not independent evidence.** `F9b` was found post-hoc in round 1 on exactly these OOS windows (round-1 report: "OOS +0.73 pp,
   DISCOVERY −0.03 pp, not carried"). Passing the same OOS again is not a new test. Re-using round-1 overlays "unchanged" in the
   pre-registration did not state this contamination; it is stated here.
2. **Regime-dependent, not stable.** DISCOVERY edge −0.03 pp; by half-year the edge is concentrated in the two strong up-half-years:
| src | half | n | ex_mean_pp | better_pct | base_mean_pp |
|---|---|---|---|---|---|
| A | 2024H2 | 21 | 0.18 | 57.14 | 1.2 |
| A | 2025H1 | 20 | -0.24 | 40.0 | 3.22 |
| A | 2025H2 | 21 | 1.3 | 90.48 | 10.5 |
| A | 2026H1 | 19 | 0.8 | 73.68 | 10.84 |
| A | 2026H2 | 9 | -0.03 | 44.44 | 5.15 |
| B | 2024H2 | 21 | -0.04 | 42.86 | 1.42 |
| B | 2025H1 | 19 | 0.05 | 47.37 | 4.24 |
| B | 2025H2 | 21 | 1.33 | 85.71 | 10.7 |
| B | 2026H1 | 20 | 0.69 | 70.0 | 10.99 |
| B | 2026H2 | 9 | 0.0 | 44.44 | 4.28 |
   Current regime (2026H2, n = 9): −0.03 pp — no benefit. The concentration idea mainly amplifies the up-trend (baseline +10 %/window
   in 2025H2 / 2026H1) and is flat in 2024H2, 2025H1, 2026H2.
3. **No help after a drawdown.** Recovery test (§6): P(final > 0) 47 % vs 53 % (A, n = 17) and 59 % vs 62 % (A+B, n = 29); mean worst
   remaining drawdown −4.8 % vs −4.9 % (no protection); worst final −21.0 % vs −22.2 %.
4. **Actual path.** Same-engine replay on the live path (10/27 → 11/02, post-hoc, n = 1): F9b −4.04 % vs frozen −3.82 %.
5. **Costs / risk.** Turnover +0.87×NAV (0.98 → 1.84), cost +≈2.6 M TWD (+0.26 % NAV), mean MDD +0.23 pp, worst window (all) −25.9 % vs −25.3 %.
6. **It is a portfolio-construction change** (weights, holdings count) under the frozen paths, needing an Owner-approved Promotion Issue,
   freeze regression and a transition trade (~0.9–1.8×NAV turnover) on an already-held book, with ~19 trading days left. Expected
   net benefit ≈ 0.46 pp (all windows) × 19/24 minus transition cost 0.26 % ≈ +0.1 pp, far inside noise.

Robustness / sensitivity of the concentration idea (reported, never used to choose; A = primary windows, B = shifted extension):
| src | variant | sample | n | ex_mean_pp | ex_median_pp | better_pct | p_signflip | turnover_add | cost_add_pct_nav | mdd_add_pp | worst_pp | base_worst_pp | top30_x | top30_base | viol_windows |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | R1_F9b | ALL | 90 | 0.46 | 0.45 | 63.33 | 0.0 | 0.86 | 0.26 | 0.23 | -25.9 | -25.28 | 23.33 | 14.44 | 0 |
| A | R1_F9b | DISCOVERY | 41 | -0.03 | -0.09 | 48.78 | 0.88 | 0.83 | 0.24 | 0.15 | -25.9 | -25.28 | 26.83 | 21.95 | 0 |
| A | R1_F9b | OOS | 49 | 0.86 | 0.76 | 75.51 | 0.0 | 0.89 | 0.27 | 0.29 | -21.02 | -22.23 | 20.41 | 8.16 | 0 |
| A | R1_F9b | OOS_first_half | 24 | 1.19 | 1.15 | 87.5 | 0.0 | 0.84 | 0.26 | 0.24 | 0.47 | -0.02 | 37.5 | 8.33 | 0 |
| A | R1_F9b | OOS_second_half | 25 | 0.55 | 0.74 | 64.0 | 0.09 | 0.93 | 0.29 | 0.35 | -21.02 | -22.23 | 4.0 | 8.0 | 0 |
| A | C25_CONC | ALL | 90 | 0.16 | 0.0 | 28.89 | 0.04 | 0.38 | 0.11 | -0.01 | -25.88 | -25.28 | 15.56 | 14.44 | 0 |
| A | C25_CONC | DISCOVERY | 41 | -0.16 | 0.0 | 14.63 | 0.04 | 0.38 | 0.11 | 0.03 | -25.88 | -25.28 | 21.95 | 21.95 | 0 |
| A | C25_CONC | OOS | 49 | 0.42 | 0.0 | 40.82 | 0.0 | 0.38 | 0.11 | -0.05 | -20.73 | -22.23 | 10.2 | 8.16 | 0 |
| A | C25_CONC | OOS_first_half | 24 | 0.39 | 0.0 | 37.5 | 0.0 | 0.29 | 0.09 | 0.03 | 0.89 | -0.02 | 16.67 | 8.33 | 0 |
| A | C25_CONC | OOS_second_half | 25 | 0.45 | 0.0 | 44.0 | 0.02 | 0.46 | 0.14 | -0.12 | -20.73 | -22.23 | 4.0 | 8.0 | 0 |
| A | R1_F1b | ALL | 90 | 0.12 | 0.1 | 67.78 | 0.0 | 0.09 | 0.02 | 0.22 | -26.07 | -25.28 | 17.78 | 14.44 | 0 |
| A | R1_F1b | DISCOVERY | 41 | -0.02 | 0.0 | 51.22 | 0.71 | 0.09 | 0.02 | 0.2 | -26.07 | -25.28 | 24.39 | 21.95 | 0 |
| A | R1_F1b | OOS | 49 | 0.24 | 0.22 | 81.63 | 0.0 | 0.09 | 0.02 | 0.24 | -22.85 | -22.23 | 12.24 | 8.16 | 0 |
| A | R1_F1b | OOS_first_half | 24 | 0.28 | 0.23 | 95.83 | 0.0 | 0.05 | 0.01 | 0.13 | -0.02 | -0.02 | 16.67 | 8.33 | 0 |
| A | R1_F1b | OOS_second_half | 25 | 0.19 | 0.22 | 68.0 | 0.07 | 0.13 | 0.03 | 0.34 | -22.85 | -22.23 | 8.0 | 8.0 | 0 |
| A | SENS top20,w^1 | ALL | 90 | 0.21 | 0.21 | 55.56 | 0.05 | 0.85 | 0.25 | 0.17 | -25.33 | -25.28 | 21.11 | 14.44 | 0 |
| A | SENS top20,w^1 | DISCOVERY | 41 | -0.2 | -0.34 | 26.83 | 0.08 | 0.9 | 0.26 | 0.13 | -25.33 | -25.28 | 24.39 | 21.95 | 0 |
| A | SENS top20,w^1 | OOS | 49 | 0.56 | 0.64 | 79.59 | 0.0 | 0.81 | 0.25 | 0.21 | -21.96 | -22.23 | 18.37 | 8.16 | 0 |
| A | SENS top20,w^1 | OOS_first_half | 24 | 0.67 | 0.62 | 83.33 | 0.0 | 0.81 | 0.25 | 0.19 | 0.46 | -0.02 | 25.0 | 8.33 | 0 |
| A | SENS top20,w^1 | OOS_second_half | 25 | 0.46 | 0.68 | 76.0 | 0.09 | 0.81 | 0.25 | 0.23 | -21.96 | -22.23 | 12.0 | 8.0 | 0 |
| A | SENS top20,w^3 | ALL | 90 | 0.58 | 0.56 | 60.0 | 0.0 | 0.97 | 0.3 | 0.27 | -26.43 | -25.28 | 22.22 | 14.44 | 0 |
| A | SENS top20,w^3 | DISCOVERY | 41 | 0.06 | -0.07 | 43.9 | 0.78 | 0.87 | 0.26 | 0.19 | -26.43 | -25.28 | 26.83 | 21.95 | 0 |
| A | SENS top20,w^3 | OOS | 49 | 1.02 | 0.98 | 73.47 | 0.0 | 1.06 | 0.33 | 0.33 | -20.43 | -22.23 | 18.37 | 8.16 | 0 |
| A | SENS top20,w^3 | OOS_first_half | 24 | 1.45 | 1.59 | 83.33 | 0.0 | 0.97 | 0.3 | 0.24 | 0.77 | -0.02 | 33.33 | 8.33 | 0 |
| A | SENS top20,w^3 | OOS_second_half | 25 | 0.61 | 0.77 | 64.0 | 0.1 | 1.15 | 0.36 | 0.42 | -20.43 | -22.23 | 4.0 | 8.0 | 0 |
| A | SENS top24,w^2 | ALL | 90 | 0.35 | 0.24 | 62.22 | 0.0 | 0.2 | 0.06 | 0.17 | -25.9 | -25.28 | 21.11 | 14.44 | 0 |
| A | SENS top24,w^2 | DISCOVERY | 41 | 0.14 | -0.02 | 48.78 | 0.18 | 0.13 | 0.04 | 0.09 | -25.9 | -25.28 | 24.39 | 21.95 | 0 |
| A | SENS top24,w^2 | OOS | 49 | 0.53 | 0.46 | 73.47 | 0.0 | 0.25 | 0.08 | 0.23 | -21.37 | -22.23 | 18.37 | 8.16 | 0 |
| A | SENS top24,w^2 | OOS_first_half | 24 | 0.82 | 0.77 | 87.5 | 0.0 | 0.21 | 0.07 | 0.15 | 0.09 | -0.02 | 29.17 | 8.33 | 0 |
| A | SENS top24,w^2 | OOS_second_half | 25 | 0.25 | 0.18 | 60.0 | 0.15 | 0.29 | 0.09 | 0.32 | -21.37 | -22.23 | 8.0 | 8.0 | 0 |
| B | R1_F9b | ALL | 90 | 0.47 | 0.32 | 60.0 | 0.0 | 0.84 | 0.26 | 0.22 | -19.28 | -18.57 | 22.22 | 16.67 | 0 |
| B | R1_F9b | DISCOVERY | 40 | 0.0 | -0.12 | 45.0 | 0.98 | 0.8 | 0.24 | 0.19 | -19.28 | -18.57 | 25.0 | 22.5 | 0 |
| B | R1_F9b | OOS | 50 | 0.84 | 0.73 | 72.0 | 0.0 | 0.88 | 0.27 | 0.24 | -17.15 | -17.46 | 20.0 | 12.0 | 0 |
| B | R1_F9b | OOS_first_half | 25 | 1.27 | 1.04 | 88.0 | 0.0 | 0.82 | 0.25 | 0.17 | 1.95 | 1.79 | 28.0 | 12.0 | 0 |
| B | R1_F9b | OOS_second_half | 25 | 0.4 | 0.27 | 56.0 | 0.12 | 0.94 | 0.29 | 0.31 | -17.15 | -17.46 | 12.0 | 12.0 | 0 |
| B | C25_CONC | ALL | 90 | 0.12 | 0.0 | 30.0 | 0.16 | 0.42 | 0.13 | 0.05 | -19.33 | -18.57 | 18.89 | 16.67 | 0 |
| B | C25_CONC | DISCOVERY | 40 | -0.17 | 0.0 | 20.0 | 0.07 | 0.42 | 0.12 | 0.06 | -19.33 | -18.57 | 25.0 | 22.5 | 0 |
| B | C25_CONC | OOS | 50 | 0.35 | 0.0 | 38.0 | 0.0 | 0.43 | 0.13 | 0.05 | -17.43 | -17.46 | 14.0 | 12.0 | 0 |
| B | C25_CONC | OOS_first_half | 25 | 0.57 | 0.0 | 44.0 | 0.0 | 0.37 | 0.11 | 0.04 | 1.63 | 1.79 | 20.0 | 12.0 | 0 |
| B | C25_CONC | OOS_second_half | 25 | 0.12 | 0.0 | 32.0 | 0.45 | 0.48 | 0.15 | 0.07 | -17.43 | -17.46 | 8.0 | 12.0 | 0 |
| B | R1_F1b | ALL | 90 | 0.21 | 0.15 | 70.0 | 0.0 | 0.1 | 0.03 | 0.2 | -19.31 | -18.57 | 18.89 | 16.67 | 0 |
| B | R1_F1b | DISCOVERY | 40 | 0.04 | 0.04 | 55.0 | 0.56 | 0.12 | 0.03 | 0.2 | -19.31 | -18.57 | 22.5 | 22.5 | 0 |
| B | R1_F1b | OOS | 50 | 0.34 | 0.26 | 82.0 | 0.0 | 0.09 | 0.02 | 0.21 | -17.62 | -17.46 | 16.0 | 12.0 | 0 |
| B | R1_F1b | OOS_first_half | 25 | 0.36 | 0.39 | 96.0 | 0.0 | 0.07 | 0.01 | 0.16 | 1.79 | 1.79 | 16.0 | 12.0 | 0 |
| B | R1_F1b | OOS_second_half | 25 | 0.32 | 0.21 | 68.0 | 0.0 | 0.12 | 0.03 | 0.25 | -17.62 | -17.46 | 16.0 | 12.0 | 0 |
| B | SENS top20,w^1 | ALL | 90 | 0.21 | 0.25 | 55.56 | 0.03 | 0.83 | 0.25 | 0.15 | -18.89 | -18.57 | 20.0 | 16.67 | 0 |
| B | SENS top20,w^1 | DISCOVERY | 40 | -0.2 | -0.25 | 35.0 | 0.1 | 0.85 | 0.25 | 0.14 | -18.89 | -18.57 | 20.0 | 22.5 | 0 |
| B | SENS top20,w^1 | OOS | 50 | 0.54 | 0.56 | 72.0 | 0.0 | 0.81 | 0.25 | 0.16 | -17.81 | -17.46 | 20.0 | 12.0 | 0 |
| B | SENS top20,w^1 | OOS_first_half | 25 | 0.71 | 0.74 | 84.0 | 0.0 | 0.78 | 0.24 | 0.1 | 1.53 | 1.79 | 24.0 | 12.0 | 0 |
| B | SENS top20,w^1 | OOS_second_half | 25 | 0.37 | 0.5 | 60.0 | 0.06 | 0.83 | 0.25 | 0.22 | -17.81 | -17.46 | 16.0 | 12.0 | 0 |
| B | SENS top20,w^3 | ALL | 90 | 0.64 | 0.62 | 63.33 | 0.0 | 0.97 | 0.29 | 0.25 | -19.73 | -18.57 | 23.33 | 16.67 | 0 |
| B | SENS top20,w^3 | DISCOVERY | 40 | 0.15 | -0.01 | 50.0 | 0.48 | 0.85 | 0.25 | 0.21 | -19.73 | -18.57 | 27.5 | 22.5 | 0 |
| B | SENS top20,w^3 | OOS | 50 | 1.03 | 0.85 | 74.0 | 0.0 | 1.06 | 0.33 | 0.27 | -16.87 | -17.46 | 20.0 | 12.0 | 0 |
| B | SENS top20,w^3 | OOS_first_half | 25 | 1.59 | 1.06 | 88.0 | 0.0 | 0.96 | 0.3 | 0.2 | 2.25 | 1.79 | 28.0 | 12.0 | 0 |
| B | SENS top20,w^3 | OOS_second_half | 25 | 0.47 | 0.15 | 60.0 | 0.17 | 1.16 | 0.36 | 0.34 | -16.87 | -17.46 | 12.0 | 12.0 | 0 |
| B | SENS top24,w^2 | ALL | 90 | 0.37 | 0.27 | 67.78 | 0.0 | 0.2 | 0.06 | 0.18 | -19.21 | -18.57 | 21.11 | 16.67 | 0 |
| B | SENS top24,w^2 | DISCOVERY | 40 | 0.15 | 0.14 | 57.5 | 0.17 | 0.13 | 0.04 | 0.12 | -19.21 | -18.57 | 25.0 | 22.5 | 0 |
| B | SENS top24,w^2 | OOS | 50 | 0.54 | 0.45 | 76.0 | 0.0 | 0.26 | 0.08 | 0.22 | -17.39 | -17.46 | 18.0 | 12.0 | 0 |
| B | SENS top24,w^2 | OOS_first_half | 25 | 0.88 | 0.87 | 88.0 | 0.0 | 0.22 | 0.07 | 0.16 | 1.75 | 1.79 | 20.0 | 12.0 | 0 |
| B | SENS top24,w^2 | OOS_second_half | 25 | 0.2 | 0.11 | 64.0 | 0.29 | 0.29 | 0.09 | 0.29 | -17.39 | -17.46 | 16.0 | 12.0 | 0 |
Sensitivity shows the same shape (top-20 w¹ / w³, top-24 w² all positive OOS, ≈ 0 in DISCOVERY); "top-15" is officially invalid
(< 20 names → violations) and is listed only to show the effect grows with concentration, i.e. it is risk-taking, not a free edge.

## 6. Mid-competition recovery test (baseline at −3 … −5 % on day 4–6)
Events are windows whose frozen cumulative return at close of day 4 / 5 / 6 is in the band (first such day). All strategies start
from the frozen book at that day. **n is small; no single row is evidence on its own** (pre-registered rule: n < 15 → not evidence).
**Band primary[-5,-3] — A only (pre-registered windows) — n = 17 events**

| strategy | P(final>0)% | P(beat base)% | P(worse)% | mean final% | median final% | p10 final% | worst final% | mean worst-remaining dd% | Top12% | Top30% | turnover |
|---|---|---|---|---|---|---|---|---|---|---|---|
| KEEP_FROZEN | 53.0 | 0.0 | 0.0 | 1.25 | 0.01 | -6.78 | -22.23 | -4.9 | 0.0 | 18.0 | 0.98 |
| FOLLOW_A5(rerank 5d) | 41.0 | 18.0 | 82.0 | 0.34 | -0.9 | -7.08 | -21.85 | -4.98 | 0.0 | 6.0 | 1.68 |
| FOLLOW_A1(rerank daily) | 41.0 | 29.0 | 71.0 | 0.71 | -1.18 | -7.41 | -20.94 | -4.74 | 0.0 | 12.0 | 1.97 |
| HOLD_A1_BOOK(one-off rerank) | 47.0 | 29.0 | 59.0 | 1.04 | -0.56 | -6.77 | -22.23 | -4.87 | 0.0 | 6.0 | 1.07 |
| DD_TRIGGER_CASH(cash 24%) | 41.0 | 29.0 | 71.0 | 0.37 | -0.77 | -6.72 | -19.23 | -4.08 | 0.0 | 6.0 | 1.13 |
| TACTICAL_D4 | 41.0 | 12.0 | 76.0 | 0.55 | -0.9 | -7.13 | -19.59 | -4.33 | 0.0 | 6.0 | 1.24 |
| R1_F9b(concentrate) | 47.0 | 71.0 | 29.0 | 1.73 | -0.36 | -7.22 | -21.02 | -4.84 | 6.0 | 24.0 | 1.82 |
| RANK_C25_RERANK | 47.0 | 24.0 | 47.0 | 1.05 | -0.01 | -6.98 | -22.23 | -4.79 | 0.0 | 12.0 | 1.04 |
| RANK_C25_CASH | 41.0 | 35.0 | 53.0 | 0.6 | -0.49 | -6.26 | -19.23 | -4.01 | 0.0 | 12.0 | 1.11 |
| RANK_C25_CONC | 41.0 | 47.0 | 41.0 | 1.47 | -0.54 | -7.4 | -20.73 | -4.68 | 6.0 | 18.0 | 1.71 |
**Band primary[-5,-3] — A+B (sample-size extension) — n = 29 events**

| strategy | P(final>0)% | P(beat base)% | P(worse)% | mean final% | median final% | p10 final% | worst final% | mean worst-remaining dd% | Top12% | Top30% | turnover |
|---|---|---|---|---|---|---|---|---|---|---|---|
| KEEP_FROZEN | 62.0 | 0.0 | 0.0 | 2.16 | 1.59 | -5.47 | -22.23 | -4.79 | 0.0 | 21.0 | 0.98 |
| FOLLOW_A5(rerank 5d) | 52.0 | 24.0 | 76.0 | 1.26 | 0.3 | -5.79 | -21.85 | -4.86 | 0.0 | 7.0 | 1.67 |
| FOLLOW_A1(rerank daily) | 52.0 | 38.0 | 62.0 | 1.84 | 1.29 | -6.01 | -20.94 | -4.66 | 0.0 | 17.0 | 1.96 |
| HOLD_A1_BOOK(one-off rerank) | 55.0 | 24.0 | 62.0 | 1.85 | 1.42 | -5.47 | -22.23 | -4.74 | 0.0 | 10.0 | 1.04 |
| DD_TRIGGER_CASH(cash 24%) | 55.0 | 21.0 | 79.0 | 1.24 | 0.62 | -5.48 | -19.23 | -3.94 | 0.0 | 3.0 | 1.12 |
| TACTICAL_D4 | 55.0 | 10.0 | 83.0 | 1.35 | 1.0 | -6.03 | -19.59 | -4.21 | 0.0 | 7.0 | 1.27 |
| R1_F9b(concentrate) | 59.0 | 69.0 | 31.0 | 2.5 | 0.64 | -5.73 | -21.02 | -4.7 | 7.0 | 24.0 | 1.82 |
| RANK_C25_RERANK | 59.0 | 24.0 | 41.0 | 2.03 | 1.52 | -5.74 | -22.23 | -4.64 | 0.0 | 14.0 | 1.02 |
| RANK_C25_CASH | 55.0 | 24.0 | 62.0 | 1.49 | 0.65 | -5.29 | -19.23 | -3.92 | 0.0 | 10.0 | 1.11 |
| RANK_C25_CONC | 55.0 | 41.0 | 45.0 | 2.25 | 0.59 | -6.03 | -20.73 | -4.62 | 3.0 | 21.0 | 1.69 |
**Band secondary[-6,-2] — A only (pre-registered windows) — n = 25 events**

| strategy | P(final>0)% | P(beat base)% | P(worse)% | mean final% | median final% | p10 final% | worst final% | mean worst-remaining dd% | Top12% | Top30% | turnover |
|---|---|---|---|---|---|---|---|---|---|---|---|
| KEEP_FROZEN | 56.0 | 0.0 | 0.0 | 1.36 | 0.02 | -8.09 | -25.28 | -5.35 | 0.0 | 12.0 | 1.0 |
| FOLLOW_A5(rerank 5d) | 52.0 | 28.0 | 72.0 | 0.61 | 0.27 | -8.37 | -26.16 | -5.38 | 0.0 | 4.0 | 1.64 |
| FOLLOW_A1(rerank daily) | 52.0 | 36.0 | 64.0 | 0.91 | 0.01 | -8.81 | -25.16 | -5.26 | 0.0 | 12.0 | 1.9 |
| HOLD_A1_BOOK(one-off rerank) | 52.0 | 28.0 | 52.0 | 1.34 | 0.02 | -8.08 | -22.36 | -5.16 | 0.0 | 8.0 | 1.03 |
| DD_TRIGGER_CASH(cash 24%) | 44.0 | 28.0 | 72.0 | 0.35 | -0.49 | -7.94 | -22.14 | -4.6 | 0.0 | 4.0 | 1.15 |
| TACTICAL_D4 | 44.0 | 12.0 | 68.0 | 0.77 | -0.36 | -8.23 | -23.47 | -4.79 | 0.0 | 4.0 | 1.3 |
| R1_F9b(concentrate) | 52.0 | 68.0 | 32.0 | 1.83 | 0.38 | -8.71 | -25.9 | -5.27 | 4.0 | 20.0 | 1.84 |
| RANK_C25_RERANK | 52.0 | 20.0 | 48.0 | 1.33 | 0.02 | -8.23 | -22.36 | -5.13 | 0.0 | 8.0 | 1.02 |
| RANK_C25_CASH | 44.0 | 28.0 | 64.0 | 0.6 | -0.43 | -7.22 | -22.14 | -4.53 | 0.0 | 8.0 | 1.14 |
| RANK_C25_CONC | 48.0 | 52.0 | 40.0 | 1.61 | -0.11 | -8.76 | -25.88 | -5.27 | 4.0 | 16.0 | 1.76 |
**Band secondary[-6,-2] — A+B (sample-size extension) — n = 48 events**

| strategy | P(final>0)% | P(beat base)% | P(worse)% | mean final% | median final% | p10 final% | worst final% | mean worst-remaining dd% | Top12% | Top30% | turnover |
|---|---|---|---|---|---|---|---|---|---|---|---|
| KEEP_FROZEN | 67.0 | 0.0 | 0.0 | 2.25 | 1.82 | -6.12 | -25.28 | -4.61 | 0.0 | 15.0 | 1.0 |
| FOLLOW_A5(rerank 5d) | 60.0 | 35.0 | 65.0 | 1.64 | 0.53 | -6.38 | -26.16 | -4.62 | 2.0 | 6.0 | 1.62 |
| FOLLOW_A1(rerank daily) | 58.0 | 44.0 | 56.0 | 1.99 | 1.45 | -6.39 | -25.16 | -4.52 | 2.0 | 15.0 | 1.9 |
| HOLD_A1_BOOK(one-off rerank) | 62.0 | 25.0 | 48.0 | 2.13 | 1.53 | -6.12 | -22.36 | -4.49 | 0.0 | 10.0 | 1.01 |
| DD_TRIGGER_CASH(cash 24%) | 60.0 | 19.0 | 81.0 | 1.25 | 0.79 | -5.71 | -22.14 | -3.89 | 0.0 | 2.0 | 1.15 |
| TACTICAL_D4 | 58.0 | 12.0 | 71.0 | 1.64 | 1.03 | -6.37 | -23.47 | -4.12 | 0.0 | 4.0 | 1.28 |
| R1_F9b(concentrate) | 62.0 | 58.0 | 42.0 | 2.5 | 1.53 | -6.09 | -25.9 | -4.57 | 4.0 | 21.0 | 1.85 |
| RANK_C25_RERANK | 60.0 | 19.0 | 42.0 | 2.11 | 1.56 | -6.36 | -22.36 | -4.46 | 0.0 | 10.0 | 1.04 |
| RANK_C25_CASH | 60.0 | 19.0 | 65.0 | 1.47 | 0.81 | -5.77 | -22.14 | -3.93 | 0.0 | 8.0 | 1.13 |
| RANK_C25_CONC | 62.0 | 48.0 | 35.0 | 2.43 | 1.9 | -6.42 | -25.88 | -4.53 | 2.0 | 17.0 | 1.68 |

Reading: no alternative raises P(final > 0) over KEEP_FROZEN (53 % A-only, 62 % A+B). Re-rank (A5 / A1 / one-off) beats the baseline in
only 18–38 % of events and loses in 59–82 %; cash / drawdown triggers cut the worst-case a few pp but lower the median and P(final > 0);
tactical D4 is worse in 77–83 % of events. Concentration beats the baseline in ≈ 70 % of events (mean +0.4 … +0.5 pp) but does not
improve P(final > 0) or the downside. Top-12 proxy is ~0 for every strategy in every case; Top-30 proxy is highest for KEEP_FROZEN
(17.6–20.7 %) among the non-concentration strategies.

## 7. Actual competition path — post-hoc, n = 1, NOT used for any decision (10/27 → 11/02)
| variant | ret_pct | mdd_pct | pool_pctile | fired_day |
|---|---|---|---|---|
| A100 | -3.82 | 7.01 | 29.45 |  |
| A20 | -3.82 | 7.01 | 29.45 |  |
| A10 | -3.82 | 7.01 | 29.45 |  |
| A5 | -3.82 | 7.01 | 29.45 |  |
| A3 | -3.91 | 7.09 | 25.45 |  |
| A1 | -4.41 | 7.63 | 11.55 |  |
| BASE | -3.82 | 7.01 | 29.45 | -1.0 |
| B_CASH_3 | -3.89 | 7.08 | 26.05 | 4.0 |
| B_RERANK_3 | -3.83 | 7.01 | 28.8 | 4.0 |
| B_CASH_5 | -3.89 | 7.08 | 26.05 | 4.0 |
| B_RERANK_5 | -3.83 | 7.01 | 28.8 | 4.0 |
| B_CASH_7 | -3.82 | 7.01 | 29.45 | -1.0 |
| B_RERANK_7 | -3.82 | 7.01 | 29.45 | -1.0 |
| C25_RERANK | -3.82 | 7.01 | 29.45 | -1.0 |
| C25_CASH | -3.82 | 7.01 | 29.45 | -1.0 |
| C25_CONC | -3.82 | 7.01 | 29.45 | -1.0 |
| C10_RERANK | -3.82 | 7.01 | 29.45 | -1.0 |
| C10_CASH | -3.82 | 7.01 | 29.45 | -1.0 |
| C10_CONC | -3.82 | 7.01 | 29.45 | -1.0 |
| D1_BREADTH_TREND | -4.19 | 7.1 | 15.9 | -1.0 |
| D2_VOL | -3.82 | 7.01 | 29.45 | -1.0 |
| D3_SOX | -4.08 | 6.99 | 19.45 | -1.0 |
| D4_ANY | -4.08 | 6.99 | 19.45 | -1.0 |
| R1_F1b | -3.82 | 7.01 | 29.1 | -1.0 |
| R1_F2a | -3.74 | 6.83 | 32.6 | -1.0 |
| R1_F3a | -3.87 | 6.99 | 27.0 | -1.0 |
| R1_F9b | -4.04 | 7.14 | 20.5 | -1.0 |
"-3.82" is the frozen result; no variant would have changed the day materially; the rank-aware triggers did not even fire.

## 8. Limitations / negative results kept
- Bull-heavy sample (2025H2 / 2026H1); few down-window events (n = 17 / 29). Overlapping windows (effective n ≪ 90).
- Random-pool rank proxy; the real leaderboard (659 teams) is unknown, and rank-aware rules are untestable against real competitors.
- Replay uses frozen daily books; "re-rank" = adopting the A1 / A5 pipeline book (not a fully path-consistent counterfactual).
- US overnight signals (D3) need a pre-08:30 run; round-1 data limits apply (current sector labels, approximate event dates).
- No variant of A / B / D and no rank-aware variant is better than the baseline; concentration is the only positive signal and is
  contaminated + regime-dependent.

## 9. Recommendation
**KEEP_FROZEN_ONLY** for the remaining competition. Optional research follow-up (no order impact): a pre-registered forward *shadow*
run of `top-20 / w²` alongside the live FINAL, evaluated only after ≥ 20 forward trading days, with a regime-conditional pre-registered
hypothesis. If it ever proceeds it needs a Promotion Issue, `owner-approved-investment-change`, freeze regression and a before / after freeze
comparison — none of which is started here.

No production file, config, FINAL, D-Plan, scheduler or Frozen Quant fingerprint was changed by this study.
