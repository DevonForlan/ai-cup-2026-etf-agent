# Issue #41 — Sector-diversification overlay: REPORT

**Recommendation: KEEP_CURRENT.** V2 not created. Production, Frozen Quant v1 (sha256 f34fa02e…), D-Plans: unchanged.

Method: `PRE_REGISTRATION.md` (committed before any result). Replays: 90 windows in set A (DENSE24, 41 DISCOVERY / 49 OOS) and 90 in set B (40 / 50), official costs, 5 random-group placebo seeds per window. Code `study41.py`, `analyze41.py`; data `results/*.csv`.

## Result (OOS, mean excess return vs frozen buy-and-hold, percentage points per 24-day window)
| candidate | A mean | A better % | A worst window (base −22.2) | A mean MDD Δ | B mean | recent-6 mean |
|---|---|---|---|---|---|---|
| B_CAP55 | −1.38 | 18 | −19.4 | −0.76 | −1.34 | −1.92 |
| B_CAP60 | −1.13 | 16 | −19.0 | −0.63 | −1.12 | −1.86 |
| B_CAP65 | −0.89 | 16 | −19.4 | −0.50 | −0.84 | −1.66 |
| B_CAP70 | −0.69 | 16 | −20.3 | −0.34 | −0.60 | −1.32 |
| C_BREADTH40 | −0.29 | 12 | −22.0 | −0.14 | −0.40 | −0.66 |
| C_BREADTH30 | −0.12 | 10 | −22.2 | −0.08 | −0.13 | −0.46 |
| D_FLOOR30 | −1.03 | 16 | −19.1 | −0.53 | −0.98 | −1.90 |
| D_N8 | −0.00 | 29 | −22.5 | −0.05 | −0.03 | −0.08 |
| E_HYBRID65 | −1.19 | 12 | −19.1 | −0.84 | −1.14 | −1.53 |
| P_CHASE (placebo) | −0.68 | 14 | −21.8 | −0.06 | −0.66 | −0.96 |
| P_RANDOM_CAP (placebo) | −0.09 | 43 | −22.7 | +0.02 | −0.01 | −0.14 |

(sign-flip p of the negative means < 0.01 in both sets; DISCOVERY means are also negative: −0.10 … −0.23 pp.)

## Gate verdicts
- **G1 FAIL (decisive):** every candidate has a *negative* OOS mean excess in both sets, median ≤ 0, better-window share 10–29 % (< 55 %). Each cap/floor variant gives up ≈ 0.7–1.4 pp per window for a ≈ 0.3–0.8 pp lower MDD.
- G2 FAIL (significant in the wrong direction). G3 partial: caps / floor / hybrid improve the *worst window* by ≈ 2–3 pp and mean MDD by 0.3–0.8 pp (a real tail benefit), but the 2026H2 recent-6 slice shows a *worse* worst window (−5.9 vs −4.2) — the benefit is not regime-stable.
- G4: placebo P_CHASE (−0.68) behaves like the milder caps, i.e. most of the cost is just "selling the book's own highest-ranked names"; P_RANDOM_CAP ≈ 0 shows the loss is specific to the TECH sleeve being where the Quant's alpha is.
- G5: cost add 0.02–0.12 % NAV per window (OK); official violations: D_N8 3 windows, E_HYBRID65 4 windows (B) ⇒ excluded.
- G6 FAIL: negative in every calendar half-year (2024H2 … 2026H2), most negative in 2026H1/H2 (−1.0 … −1.8 pp for B_CAP60/70, D_FLOOR30, E).
- G7/G8 (live Active Share, recovery after −5 % drawdown): not evaluated — the pre-registered G1 gate had already failed; evaluating further after the fact would only invite cherry-picking.
- Caveat: sector map is today's ISIN classification applied to the full history (not point-in-time); caps are binding in ~80–100 % of windows because the frozen book holds ≈ 72 % of NAV in TECH.

## Post-hoc, n = 1 (never used to select)
The 5 live days 10/27–11/02: every cap/floor variant was +0.44 pp better (−3.38 % vs −3.82 %), E_HYBRID65 +0.85 pp. This is the same tail benefit seen in the worst windows, but one short drawdown window cannot overturn 90 + 90 windows in which the same rule loses on average. 11/05 (electronics −3.6 %, our NAV −6.14 % that day) is exactly the kind of day where a cap helps, and the evidence says such days are paid for by the other days.

## Decision
KEEP_CURRENT. No v2, no PR to production, no rollback needed. Optional later (not started): forward **shadow** of B_CAP70 / E_HYBRID65 for tail-risk observation only — no production effect.
