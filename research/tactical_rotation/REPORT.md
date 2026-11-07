# Issue #42 — Tactical rotation out of tech (2753 / 1476 / 2412): REPORT

**Decision: DO_NOT_ROTATE.** Research only; no production, Frozen Quant v1 (sha256 f34fa02e…), D-Plan or submission was touched. Pre-registration: `PRE_REGISTRATION.md` (committed before any result).

## 1. Eligibility — decisive for two of the three names
The competition allows only the official 150-name list (`config/universe_150.csv`, "150 檔未更新" per the official-update index); holding a name outside it is a rule violation (`R_UNIVERSE` FAIL in `agent/engine/compliance.py`, server validation rejects it). **2753 八方雲集 and 1476 儒鴻 are not in the list** (nor is 6865); 2412 中華電 is. They cannot be bought under any evidence, and no price history for them exists in the PIT store, so they are reported INELIGIBLE and not simulated. Maximum feasible weights: 2753 = 0 %, 1476 = 0 %, 2412 = 10 % (single-name cap; 10 % of NAV ≈ 84 m TWD = 4.0 % of its 20-day ADV of 2.1 bn).

## 2. Method (summary)
Event study with the frozen book's holdings (A100 books of all Issue-#14 windows). Events = broad sell-off days (EW-universe median ≤ −2 %), entry next-day VWAP, h = 3/5/10/24 trading days; 16 events (6 DISCOVERY < 2025-07, 10 OOS, 3 RECENT ≥ 2026-07), plus an unconditional control (91 entry days). Rotation = sell TECH pro rata x % NAV (10/20/30/40), buy: T1 2412 only (cap-limited), T2 liquid non-tech basket, T3 2412 + basket, T4 low-vol, T5 financials, T6 random non-tech (20 seeds), T7 cash-only; official costs, 20–30 names, cash < 25 %, 10 % cap enforced (infeasible variants are excluded, e.g. T1 at 30 %: 20 % feasible). Rank percentile vs 300 random compliant portfolios per entry. Data: `results/*.csv`.

## 3. Results
Excess return of the rotated book vs the frozen book, **OOS events (n = 10), mean pp**:
| struct (x = 30 %) | 3d | 5d | 10d | 24d |
|---|---|---|---|---|
| T3 2412+basket | +0.05 | −0.54 | −1.17 | −2.26 |
| T2 basket | −0.12 | −0.65 | −1.22 | −2.18 |
| T1 2412 only (x = 20 %) | +0.22 | −0.39 | −1.38 | −2.40 |
| T4 low-vol | +0.32 | −0.42 | −1.46 | −2.45 |
| T5 financials | +0.09 | −0.49 | −1.39 | −2.30 |
| T6 random placebo | +0.25 | −0.51 | −1.53 | −2.53 |
| T7 cash-only | +0.17 | −0.34 | −1.19 | −1.99 |
Primary pre-registered test (T3, x ∈ {20,30,40}, h ∈ {5,10}, OOS): all six means negative; Holm-adjusted p 0.31–1.0. DISCOVERY and RECENT slices also negative at 10d and 24d. Control (all 91 days, h = 10): every structure significantly negative (−0.24 … −1.22 pp, p ≤ 0.001). After sell-offs the frozen book *rebounds* (+5.8 % over 10d, +10.0 % over 24d on average in OOS events), so any rotation forfeits participation. Leave-one-event-out for T3 x = 30 %, 10d: −1.60 … −0.68 pp (sign never flips).
Gate verdicts: G1 FAIL, G2 FAIL, G3 FAIL (T3 does not beat the cash-only or placebo at 10d/24d), G4 FAIL (hit rate ≤ 50 %), G5 not rescued, G6 FAIL (recent 10d/24d negative), G7 PASS (compliance), G8 FAIL (below).
The only positive pocket is 3-day excess for some structures (+0.05 … +0.4 pp) — far smaller than costs-plus-risk, p not significant, and reversed by 5d.

## 4. 2412 (name level, 2024-03 … 2026-11)
Annualised vol 12.2 % (TECH EW 32.0 %); beta to TECH −0.01, correlation −0.01; **down-capture −4 %, up-capture +0.8 %** (a pure diversifier that earns almost nothing when tech rebounds); worst day −5.6 %, MDD 9.2 %. Mean return on tech-down days +0.14 %. Its 20-day relative strength vs the EW universe is currently +38 % (unadjusted close; 3 ex-dividend dates in sample), i.e. buying it now is buying a momentum winner after its run, not a defensive discount. Liquidity: 4.0 % of ADV at the 10 % cap. Revenue/earnings and seasonal Q4 fundamentals were not modelled (no point-in-time fundamentals for names outside the PIT store; 2412 fundamentals are not a decision input given the result above). 2753/1476: not researchable under the data/eligibility rules.

## 5. Re-entry rule R (Task D, pre-registered)
Hold ≥ 3 days; re-enter TECH after 2 consecutive closes with TECH breadth > 0.5 and TECH 5d relative strength vs the universe > 0; staged 50 % / 100 %; time stop day 10. 24-day result vs frozen (pp, mean): OOS x = 30 % −1.38 (never re-enter: −2.40); DISCOVERY −0.44 (−0.43). R halves the loss but does not turn it positive; median re-entry day 7.5 (OOS). A rule that is still negative is not a reason to deploy.

## 6. Execution, compliance, cost (live book, DataPack 2026-11-05 holdings, NAV 843.5 m; script `live42.py`)
Control Active Share (official top-15 NAV method, 20 of 30 ETFs with real holdings) 45.6 %; after the tested rotations 37.9 % – 46.3 % (floor 15 %). Rotation x = 30 %: turnover 60 % of NAV, cost 0.175 % NAV (0.059 % for x = 10 %), names 30 (limit 30), cash 17.4 %, tech weight 79 % → 54 % (T3), max participation 2.0 % of ADV. The official simulator has no market impact; real-market impact is not modelled (low participation). T1 alone cannot absorb a 20–40 % sale (10 % cap ⇒ cash would exceed 25 %).

## 7. Limitations
Only 16 sell-off events (10 OOS, 3 recent) ⇒ low power; sign consistency across control (91 entries), discovery and OOS is the stronger evidence. Static-holding approximation, proxy ranks (not the real 659-team distribution), today's sector classification, no fundamentals, 10 of 30 ETFs lacked holdings data for Active Share (min over the 20 available).

## 8. Recommendation
DO_NOT_ROTATE. No tactical override, no v2, no PR to production, no trade. If the Owner still wants an observation, the cheapest option is a forward **shadow** of T3 (2412 + liquid non-tech basket, x = 20 %) tracked daily — not a deployment. Any future ask to include 2753 or 1476 requires an organiser-announced change to the 150-name list first.
