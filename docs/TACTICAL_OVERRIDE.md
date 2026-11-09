# TACTICAL_OVERRIDE_V1 — Owner-directed temporary rotation (Issue #43)

Owner directive 2026-11-08 (GitHub Issue #43, "FORCE_TEMPORARY_ROTATION"): reduce technology exposure for **one trading day** and hold a non-tech sleeve from the official 150-name universe, then return. The adverse research (`research/short_rotation/REPORT.md`, branch `research/43-short-rotation`: DO_NOT_ROTATE) stays in the audit trail; the Owner chose the experiment knowingly.

## What it is (and is not)
* A **separate** versioned override: `config/tactical_override_v1.yaml` (fingerprint = sha256 of the file) + `agent/tactical/override.py`.
* Frozen Quant v1 is untouched: `config/strategy_quant_v1.yaml` (sha256 `f34fa02e…`), `agent/features`, `agent/portfolio`, `agent/pipeline.py`, `agent/run_sim.py`, `agent/sim` have **no diff**. The override wraps `agent.pipeline.construct` for one `run_day` call inside `agent/competition_day.py` and always lets the frozen constructor run first.
* Only mode `competition` (scheduled production flow) applies it; `dry-run` / `historical` / simulations never do.

## Behaviour
| trade date | action |
|---|---|
| `entry_trade_date` (2026-11-09) | tech cluster scaled down by x % NAV (ladder 20 → 17 → 14 → 10 → 5 %, first size passing every guard), 6 pre-chosen non-tech names bought equal weight. Goes through the same `_finalize` legality pipeline as every Quant D-Plan (lots, caps, cash band, post-trade compliance, Active Share, stress) plus extra guards: 20–30 names, cash < 25 %, single-name caps, universe membership, official Active Share ≥ 15 %. If no size passes, the **untouched Quant result is returned** (fail closed) and the reason is recorded. |
| `exit_trade_date` (2026-11-10) and every later date | **expiry-first unwind**: if any sleeve name is held above the stored baseline, explicit reverse orders back to the stored pre-rotation lots (derived from the actual holdings, so a missed day, a partial fill or a re-run all work). A failed unwind is recorded as `TACTICAL_UNWIND_OVERDUE`, the Quant result is returned, and the next window retries; the sleeve is never silently extended or reported as unwound. |

2-day alternative: set `hold_trading_days: 2` and `exit_trade_date: '2026-11-11'` in the yaml (re-fingerprinted automatically).

## Rollback
One toggle: delete `config/tactical_override_v1.yaml` or set `enabled: false` (then deploy). Open sleeve positions are still visible to the stored `baseline_holdings`; to unwind anyway keep the file with `entry_trade_date` in the past and `exit_trade_date` = today.

## Evidence
Every activation writes `logs/tactical/<trade_date>_<ENTRY|UNWIND>.json` (version, fingerprint, attempts, sells/buys in shares, tech weight before/after, cash, holdings, Active Share, status, reason) and `summary["tactical_override"]` / `meta["tactical_override"]` in the daily run. `agent/ops/shared_state_tactical.py` (called from `shared_state_sync.sweep`, i.e. after every confirmed submission and every evaluation) publishes them to the `shared-state` branch under `shared_state/tactical/` with the FINAL SHA and the honest submission status (`NOT_CONFIRMED` until the portal evidence exists).

## Selection (as of 2026-11-06 close; no new research)
Eligible non-tech (outside the 7 electronics industries, 120-day correlation to the tech basket ≤ 0.55, ADV20 ≥ 0.5 bn TWD, |1-day move| < 5 %), composite = mean(rank of 5-day relative strength, rank of 60-day volatility, lower is better), ≤ 2 names per industry, top 6, equal weight: 2891 中信金, 2002 中鋼, 2618 長榮航, 5880 合庫金, 5871 中租-KY, 2912 統一超. 2753 / 1476 / 6865 are not in the official universe and are never used.

## V2 — TACTICAL_OVERRIDE_V2_TECH_LT10 (Issue #49, Owner mandate 2026-11-08)
Supersedes V1 for 2026-11-09: technology/electronics weight (same 7-industry cluster as #41-#43) must be **strictly below 10 % of total NAV**.
* Config `config/tactical_override_v2.yaml` (own version + fingerprint = file sha256); V1 config and V1 evidence stay untouched. `resolve_config()` uses V2 for every date it covers (entry date and the expiry-first unwind), V1 otherwise; deleting/disabling the V2 file makes V1 apply again.
* Construction (`build_entry_v2`, mechanical, no new research): the D-Plan allows at most 30 decisions, so the smallest tech positions stay untouched (no order), the next ones (cheapest lots) keep one-lot residuals so the book keeps >= 20-22 names, the rest are sold; 10 diversified non-tech names (selection from the #43 candidate table: steel, financials, shipping, food, leasing, retail, cement, biotech, gaming) are bought with per-name cap 8.5 %. First ladder step that passes `_finalize` + `_guards` (20-30 names, cash < 25 %, caps, universe, official Active Share >= 15 %) + the tech guard (< 10 % hard, <= 9 % design margin, no decision demoted) wins; otherwise the untouched Quant result is returned and **nothing is superseded**.
* Unwind (2026-11-10, expiry-first, from ACTUAL holdings): sleeve (V2 + V1 names) sold, tech restored to the stored baseline lots; the exact reverse plan is persisted in the ENTRY record (`unwind_plan`) before submission. Failure = `TACTICAL_UNWIND_OVERDUE`, retried next window.
* Supersession of the already SUBMISSION_CONFIRMED FINAL: `python -m agent.ops.tactical_supersede --date 2026-11-09 --authorization "Issue #49 ..."` (see module docstring): read-only portal check that the prior FINAL is confirmed, prior artefacts archived under `submissions/<T>/superseded/`, new candidate from the unchanged competition_day flow, promoted only through `candidate_gate`, submitted by the guarded auto_upload (SUBMISSION_CONFIRMED only from real portal evidence), state restored to the prior confirmed FINAL on any failure.
* Rollback: delete/disable `config/tactical_override_v2.yaml`.

## V2 exit = direct Frozen Quant v1 resume (Issue #49, Owner preference 2026-11-09)

`config/tactical_override_v2.yaml` carries `exit_mode: FROZEN_QUANT_RESUME`. From `exit_trade_date` (2026-11-10) the phase is `RESUME`:
`activate()` does **not** patch `agent.pipeline.construct`, so Frozen Quant v1 alone builds the D-Plan from the ACTUAL settled holdings
(all its legality gates, 30-order cap and Fallback-to-previous still apply). The V2 config keeps claiming every later date so the superseded
V1 config (whose unwind sleeve overlaps V2's buys) can never fire. One audit record `logs/tactical/<date>_RESUME_V2.json`
(`FROZEN_QUANT_RESUMED`, `decision_authority: FROZEN_QUANT_V1`) is written on the exit date only. The `unwind_plan` stored in the ENTRY record
remains audit data and is not executed. Rollback: set `exit_mode: EXPLICIT_UNWIND` (any other value) to restore the mechanical unwind.

## Shadow baseline (Issue #48)
`python -m agent.ops.shadow_baseline generate|compare --date T [--publish]`: untouched Frozen Quant v1 from the same settlement state and as-of,
written only under `logs/shadow/<T>/` (`SHADOW_BASELINE_NOT_FOR_SUBMISSION`, never under `submissions/`); `compare` settles baseline / V1 / V2 order
sets with `agent.sim.settle.settle` after the close.
