# Issue #43 — 1–2 trading-day forced non-tech rotation (Mon 2026-11-09): REPORT

**Decision: DO_NOT_ROTATE** (the Owner-requested feasible alternatives are quantified below). Research only: no production change, no D-Plan, no submission, no trade. Frozen Quant v1 sha256 `f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0` unchanged. Pre-registration (`PRE_REGISTRATION.md`) was committed before any result. This is a new 1–2-day test, not a reuse of #42.

## 1. Facts and schedule
* Official universe verified: `config/universe_150.csv` == `research/competition/universe_150.csv`, 150 names; official index: "150 檔未更新"; 2753 / 1476 / 6865 are absent (excluded, fail-closed).
* As of **2026-11-06 close**: NAV 806,915,359 (recomputed from DataPack holdings + 11/06 closes; identical to the evaluation report), cash 18.39 %, 24 names, TECH 78.3 % of NAV, EW-universe median return on 11/06 = −4.8 % (the E1 sell-off signal is on).
* Schedule (history.jsonl: the 11/06 19:30 run logged `SKIPPED NO_SUBMISSION_WINDOW_TONIGHT`): the window for trade date **Mon 11/09** is **Sun 11/08 19:30 → Mon 11/09 08:55** (08:30 internal decision cut-off, 25 attempts, last successful submission before 08:55 counts). Information = Fri 11/06 close; execution at 11/09 VWAP. A 1-day hold exits in the **11/10** D-Plan (window Mon 19:30 → Tue 08:55, sell at 11/10 VWAP); a 2-day hold exits in the **11/11** D-Plan. The result of Monday can never be acted on for Monday. All times Asia/Taipei.

## 2. Screening (as of 11/06; `results/ranked_candidates_20261106.csv`, `excluded_nontech_20261106.csv`)
Eligible non-tech = in universe, not one of 7 electronics industries, 120-day correlation to the TECH basket ≤ 0.55, ADV20 ≥ 0.5 bn TWD, not limit-locked: **28 names** (19 more carry a non-tech label but were excluded as tech-linked / illiquid). Top by 5-day relative strength: 6446 藥華藥 (+22.8 pp vs EW, but vol60 3.7 %, 20 % of days beyond ±5 %, +7.2 % on 11/06 ⇒ gap/limit risk), 2618 長榮航, 2886 兆豐金, 2880 華南金, 2891 中信金, 5871 中租-KY, 2002 中鋼, 5880 合庫金, 2884 玉山金, 1216 統一. The Owner's illustrative names (2412, 3045, 4904, 2912, 5903 …) are in the file with all features (1/2/3/5/10/20-day returns, relative strength, vol, tech beta / correlation, down / up capture, ADV20, big-move frequency).

## 3. Event study (PIT; 1-day and 2-day; VWAP entry / exit; costs on both legs)
E1 (primary) = EW-universe daily median ≤ −1.5 %: 35 events (11 DISCOVERY, **24 OOS**, 8 RECENT); robustness E2 (≤ −2 %, 23 events), E3 (≤ −1 %, 58), E4 (TECH ≤ −2.5 %, 28), E5 (2-day ≤ −3 %, 21); unconditional control 130 entries.

**Primary (S1_RS5 = top-6 by 5-day relative strength; OOS; mean excess vs the untouched frozen book, pp; Holm over 8 tests):**

| x NAV | 1d mean | 1d 95 % CI | 1d Holm p | 2d mean | 2d Holm p | cost (round trip) |
|---|---|---|---|---|---|---|
| 10 % | −0.28 | −0.40…−0.17 | 0.001 | −0.24 | 0.092 | 0.117 % |
| 20 % | −0.51 | −0.73…−0.27 | 0.002 | −0.47 | 0.079 | 0.234 % |
| 30 % | −0.73 | −1.09…−0.39 | 0.001 | −0.70 | 0.058 | 0.351 % |
| 40 % | −0.96 | −1.42…−0.50 | 0.002 | −0.92 | 0.032 | 0.468 % |

Significant in the wrong direction; hit rate 17–25 %. Gross of costs the excess is also negative (x = 30 %: −0.38 pp 1d, −0.35 pp 2d). DISCOVERY and RECENT slices are negative at every size; leave-one-event-out ranges −0.81…−0.67 (1d) and −0.85…−0.56 (2d) at x = 30 % (never positive); all five event definitions and the control agree (S1_RS5 x = 30 %: −0.43…−0.83 pp). After these sell-offs the frozen book on average rises (+0.58 % next day, +0.56 % over 2 days in OOS), so a tactical sleeve gives up the rebound and the sleeve baskets do not rebound more.

Comparators at x = 30 % (OOS, 1d / 2d mean pp): S2 2-day-resilient −0.70/−0.72; S3 low-vol −0.58/−0.59; S4 low-beta −0.63/−0.58; S6 random eligible names −0.60/−0.60; S7 cash-only (limited by cash < 25 %) −0.41/−0.38; S8 the #42 basket −0.62/−0.63. The pre-registered momentum choice S1 was worse than random names and worse than cash-only. G3 fails.

## 4. Gate verdicts (pre-registered)
G1 FAIL (OOS and DISCOVERY negative) · G2 FAIL (p < 0.10 but negative) · G3 FAIL (worse than placebo and cash-only) · G4 FAIL (hit 17–25 %) · G5 sign stable (stably negative) · G6 FAIL (RECENT negative) · G7 PARTIAL: Active Share, caps, names, cash pass but participation reaches 5.5 % of ADV20 at x = 30 % (limit 5 %) and 7.3 % at x = 40 % · G8 robust (negative under every definition). ⇒ **DO_NOT_ROTATE**; not SHADOW_ONLY either, because the evidence is adverse rather than merely inconclusive.

## 5. If the Owner overrides: exact feasible alternatives (`live43.py`, `results/live_whatif43.csv`, `orders_x20.json`, `orders_x30.json`)
Constraints: 24 names ⇒ at most 6 new names; ≤ 10 % per name; cash < 25 %; lots of 1,000 shares; fee 0.1425 % + 0.3 % sell tax on every leg (entry and exit). Feasible maximum x ≈ 50 % (x = 60 % puts a new name at 10.01 % > cap).

| x | tech after | cash after | names | max new-name wt | Active Share min (ETF) | round-trip cost | round-trip turnover | max ADV20 participation |
|---|---|---|---|---|---|---|---|---|
| 10 % | 67.7 % | 18.4 % | 30 | 1.8 % | 42.5 % (00985A) | 0.124 % | 42 % | 1.9 % |
| 20 % | 58.0 % | 18.4 % | 30 | 3.4 % | 41.5 % (00985A) | 0.237 % | 81 % | 3.7 % |
| 30 % | 47.8 % | 18.3 % | 30 | 5.1 % | 44.8 % (00985A) | 0.356 % | 122 % | 5.5 % |
| 40 % | 38.0 % | 18.3 % | 30 | 6.7 % | 47.7 % (00984A) | 0.471 % | 161 % | 7.3 % |

Control Active Share 45.6 % (20 of 30 ETFs have real holdings); floor 15 %. Quantities in the JSON files are priced at the 11/06 close and must be re-derived at the 11/09 07:30 run.
Example x = 20 %: sell 2337 76,000 / 2344 59,000 / 2347 91,000 / 2360 6,000 / 2376 34,000 / 2383 2,000 / 2408 22,000 / 2451 44,000 / 3081 3,000 / 3443 1,000 / 3661 3,000 / 3680 15,000 / 3702 106,000 / 4938 88,000 / 4979 17,000 / 5289 7,000 / 6187 6,000 / 6274 5,000 / 6669 5,000 / 6770 114,000 / 7734 4,000 / 7769 2,000 / 8299 5,000 shares; buy 6446 21,000 / 2618 626,000 / 2886 510,000 / 2880 558,000 / 2891 372,000 / 5871 267,000 shares.
Sleeve capture vs TECH (mean of the 6 names): down-capture ≈ 0.0, up-capture ≈ 0.28. Expected 1–2-day excess range (OOS, x = 20 %): mean −0.5 pp, 95 % CI −0.73…−0.08, worst event −1.5 pp (1d) / −2.6 pp (2d). The official simulator has no market impact; real liquidity risk is the participation column plus 6446's limit-up / gap behaviour.

## 6. Automatic expiry / reversion design (only if the Owner approves; NOT built or deployed)
Frozen Quant v1 is buy-and-hold (`rebalance_every = 100`), so it will not bring a tactical sleeve back by itself; the unwind must be explicit.
1. A separate versioned override file (own fingerprint; the Quant v1 yaml is untouched) holds {entry date 11/09, expiry = exit date 11/10 (1d) or 11/11 (2d), lot-sized sleeve, mirror exit orders}.
2. The unwind orders are generated in the same session as the entry and stored; the D-Plan of the exit date is built by the normal 19:30 flow and must contain them.
3. Fail-safe: any daily run with an open sleeve whose expiry ≤ trade date emits the unwind first, before any other decision; if the 19:30 run is late (the standby catch-up exists), the 07:30 morning flow does the same until 08:30.
4. If the exit window is missed, the next available window carries the unwind with priority; the sleeve is never silently extended; a missed unwind is logged `TACTICAL_UNWIND_OVERDUE` and surfaced in the daily evaluation and GitHub Shared State.
5. Stale quote / limit-up / limit-down: an unfillable leg is reported, never assumed filled; evaluation uses actual settlement, not the estimate.
6. Rollback = one flag removing the override plus the stored mirror orders. Submission-truth rules unchanged (`SUBMISSION_CONFIRMED` only on portal evidence).

## 7. Limitations
35 E1 events (24 OOS, 8 recent) with overlapping information across definitions; static-holding approximation of the frozen book from the Issue-#14 window books; proxy random-portfolio rank pool (not the real 659 teams), so rank figures are indicative; today's sector classification; 10 of 30 ETFs without holdings data; no spread / market-impact data (ADV20 and big-move frequency as proxies); the results describe the sell-off state, not a forecast for Monday.

## 8. Recommendation
DO_NOT_ROTATE: keep Frozen Quant v1 for 11/09. If the Owner still wants a tactical move, the least-bad measured option is cash-only (−0.4 pp, still negative) — not recommended either. Next step: ChatGPT cross-review; Owner action only if the Owner chooses to override, in which case x ≤ 20 % keeps participation below 5 % and the unwind design above must be built and tested first.
