# Issue #43 — 1–2 trading-day forced non-tech rotation: PRE-REGISTRATION
Written 2026-11-07 (Sat) before any result of this study was computed. RESEARCH ONLY: nothing is deployed, submitted or traded. Frozen Quant v1 sha256 f34fa02e… is the control. #42's 5/10/24-day verdict is NOT reused: the horizon here is 1–2 days and is tested separately.

## 0. Schedule semantics (verified in logs/scheduled/history.jsonl and the runbook)
* The 11/06 19:30 run logged `SKIPPED NO_SUBMISSION_WINDOW_TONIGHT`; the window for trade date **Mon 2026-11-09** opens **Sun 11/08 19:30** and closes **Mon 11/09 08:55** (08:30 internal decision cut-off; last successful submission before 08:55 counts; ≤ 25 attempts). Information available = **Fri 11/06 close**. Orders execute at 11/09 VWAP.
* 1-day hold = buy 11/09 VWAP, sell 11/10 VWAP (exit order sits in the 11/10 D-Plan, window Mon 19:30 → Tue 08:55); 2-day hold = sell 11/11 VWAP (11/11 D-Plan). Outcome measured as NAV at the close of 11/10 (h = 1) / 11/11 (h = 2) versus the untouched frozen book. Nothing observed after 11/06 is used.
* Universe = `config/universe_150.csv` (identical to `research/competition/universe_150.csv`; official index says "150 檔未更新"); 2753, 1476, 6865 absent ⇒ excluded; fail closed on any mismatch.

## 1. Screening (PIT, at decision close d)
Eligible non-tech = in universe, sector ∉ TECH (7 TWSE electronics industries, as in #41/#42), **and** 120-day correlation of daily returns with the equal-weight TECH basket ≤ 0.55 (so a hardware/tech-linked "industrial" is not counted as a hedge by label), ADV20 ≥ 0.5 bn TWD, not limit-locked on d. Features: 1/2/3/5/10/20-day returns, relative strength vs EW-universe, 60-day volatility, tech beta, down/up capture vs TECH, ADV20, gap/limit-day frequency, corr to TECH.

## 2. Events (past data only)
Primary E1: EW-universe median daily return ≤ −1.5 % on day d (events ≥ 3 trading days apart, first kept); entry d+1 VWAP. Robustness: E2 ≤ −2 %, E3 ≤ −1 %, E4 TECH-EW ≤ −2.5 %, E5 2-day EW ≤ −3 %, and an unconditional control (every 4th day). DISCOVERY entries < 2025-07-01 ≤ OOS; RECENT ≥ 2026-07-01.

## 3. Candidates (equal weight within caps; N = min(6, 30 − current names) new names)
S1_RS5 **(primary)**: top N by 5-day return minus EW-universe 5-day return · S2_RS2: top N by 2-day relative return (resilient inside the sell-off) · S3_LOWVOL · S4_LOWBETA (lowest TECH beta) · S5_EWNT (all eligible, equal weight, ≤ 28 names) · S6 placebo random eligible names (20 seeds) · S7 cash only (to cash < 25 %) · S8 #42 basket (2412 + 5 most liquid non-tech). Sizes x ∈ {10, 20, 30, 40} % NAV sold pro rata from TECH. Constraints: 20–30 names, ≤ 10 % per name (2330 25 %), cash < 25 %, 1,000-share lots, official costs (fee 0.1425 % each way incl. the exit, tax 0.3 % on each sell), Active Share (official top-15 NAV method) ≥ 15 % vs every ETF with data.

## 4. Primary test, gate
Primary: S1_RS5 on E1 **OOS** events, x ∈ {10,20,30,40} × h ∈ {1,2} = 8 tests, mean excess return vs frozen (net of costs), sign-flip permutation p (events as units) with Holm; bootstrap 95 % CI of the mean.
To recommend ROTATE_1D / ROTATE_2D (for the chosen h and x) ALL must hold: G1 OOS mean excess > 0 and DISCOVERY mean > 0; G2 Holm p < 0.10; G3 beats S6 placebo, S7 cash-only and S5 EW non-tech at the same x, h; G4 hit rate ≥ 55 %; G5 leave-one-event-out sign unchanged; G6 RECENT slice same sign; G7 compliance (names, caps, cash, Active Share ≥ 25 % margin, participation ≤ 5 % of ADV20) PASS for the live proposal; G8 result holds under E2/E3/E4/E5 definitions with the same sign. Otherwise: SHADOW_ONLY if the only support is descriptive/control-like, else DO_NOT_ROTATE. The Owner-requested feasible alternatives are quantified regardless of the verdict. Multiple-testing: Holm over the 8 primary tests; all other rows are descriptive.
