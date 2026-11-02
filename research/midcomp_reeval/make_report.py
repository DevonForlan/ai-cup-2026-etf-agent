"""RESEARCH ONLY. Builds REPORT.md tables from results/*.csv (no numbers typed by hand in the tables)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
R = HERE / "results"


def mdtable(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join("" if (isinstance(v, float) and pd.isna(v)) else str(v) for v in r) + " |")
    return "\n".join(out)


def pct(s, d=2):
    return (s * 100).round(d)


def main() -> None:
    sa, sr = pd.read_csv(R / "summary_familyA.csv"), pd.read_csv(R / "summary_replay.csv")
    al = pd.concat([sa, sr])
    ct = pd.read_csv(R / "carry_table.csv")
    plc = json.load(open(R / "placebos.json"))
    gate = json.load(open(R / "gate_r0.json"))
    rs = pd.read_csv(R / "recovery_summary.csv")
    ex = pd.read_csv(R / "extra_robustness.csv")
    hy = pd.read_csv(R / "extra_f9b_by_half_year.csv")
    ap = pd.read_csv(R / "extra_actual_path.csv")

    def table(sample):
        d = al[al["sample"] == sample].copy()
        d["variant"] = d.variant.replace({"BASE": "BASE(=A100)"})
        d = d[d.variant != "A100"]
        o = pd.DataFrame({"variant": d.variant, "n": d.n, "median%": pct(d.median_ret), "mean%": pct(d.mean_ret), "hit%": pct(d.hit, 1),
                          "MDD%": pct(d.mdd_mean), "worst%": pct(d.worst_window), "CVaR10%": pct(d.cvar10), "turnover(xNAV)": d.turnover.round(2),
                          "cost(M TWD)": (d.cost / 1e6).round(2), "Top12%": pct(d.top12, 1), "Top30%": pct(d.top30, 1),
                          "ex_mean pp": pct(d.ex_mean), "ex_median pp": pct(d.ex_median), "better%": pct(d.ex_better, 0), "p": d.p_signflip.round(3)})
        return mdtable(o)

    carry = ct.copy()
    for c in ("oos_ex_mean_pp", "oos_ex_median_pp", "disc_ex_mean_pp", "ci95_lo_pp", "ci95_hi_pp"):
        carry[c] = carry[c].round(2)
    carry["p_signflip"], carry["p_holm"] = carry.p_signflip.round(3), carry.p_holm.round(3)
    for c in ("a_edge", "b_sig", "c_disc", "d_tail", "e_cost", "f_placebo", "g_viol", "PASS_ALL"):
        carry[c] = carry[c].map({True: "Y", False: "n"})
    rec = []
    for (b, s), g in rs.groupby(["band", "sample"], sort=False):
        d = pd.DataFrame({"strategy": g.strategy, "P(final>0)%": pct(g.P_final_gt0, 0), "P(beat base)%": pct(g.P_beat_base, 0),
                          "P(worse)%": pct(g.P_worse_than_base, 0), "mean final%": pct(g.mean_final), "median final%": pct(g.median_final),
                          "p10 final%": pct(g.p10_final), "worst final%": pct(g.worst_final), "mean worst-remaining dd%": pct(g.mean_rem_min),
                          "Top12%": pct(g.top12, 0), "Top30%": pct(g.top30, 0), "turnover": g.turnover.round(2)})
        rec.append(f"**Band {b} — {s} — n = {int(g.n_events.iloc[0])} events**\n\n" + mdtable(d))
    exo = ex[ex.variant.isin(["R1_F9b", "SENS top20,w^1", "SENS top20,w^3", "SENS top24,w^2", "C25_CONC", "R1_F1b"]) &
             ex["sample"].isin(["ALL", "DISCOVERY", "OOS", "OOS_first_half", "OOS_second_half"])].copy()
    exo = exo.round(2)
    apx = ap.copy().round(2)
    txt = f"""# REPORT — mid-competition strategy re-evaluation (Issue #14, round 2)

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
- Gate R0 (replay vs frozen daily NAV): mean |Δ| {gate['R0_mean_abs_diff_pp']:.6f} pp, max {gate['R0_max_abs_diff_pp']:.4f} pp → **PASS**.
  Cross-check on reality: the same engine on the actual start 2026-10-27 (5 trading days) gives −3.82 % / MDD 7.01 %, the
  official 11/02 figures (cumulative −3.82 %, MDD 7.01 %).
- Statistics: paired excess vs baseline per window; sign-flip permutation p (OOS), Holm over all 25 variants, block-bootstrap CI (block 4);
  placebos (20: time-shifted signals for D1–D4, name-shuffled for F2a / F3a / F9b).
- Top-12 / Top-30 proxy: share of windows whose return exceeds the 98.2nd / 95.5th percentile of a pool of 2 000 random long-only
  portfolios (k = 10/20/30/50). **Crude proxy**: real competitors are not random; read differences only.
- Returns here are daily-NAV returns (dividends receivable not accrued), identical for baseline and every variant.

## 2. Results — all 24-day windows (n = 90)
{table('ALL')}

## 3. Results — OOS only (n = 49)
{table('OOS')}

## 4. Pre-registered gates (OOS; a = edge ≥ +0.5 pp & median > 0, b = Holm p < 0.10 or CI > 0, c = DISCOVERY ≥ −0.3 pp, d = tail not worse > 1 pp, e = cost < 0.5 % NAV, f = placebo p < 0.10, g = 0 official-limit violations)
{mdtable(carry)}

Placebos (OOS subset): {json.dumps(plc)}

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
{mdtable(hy.round(2))}
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
{mdtable(exo)}
Sensitivity shows the same shape (top-20 w¹ / w³, top-24 w² all positive OOS, ≈ 0 in DISCOVERY); "top-15" is officially invalid
(< 20 names → violations) and is listed only to show the effect grows with concentration, i.e. it is risk-taking, not a free edge.

## 6. Mid-competition recovery test (baseline at −3 … −5 % on day 4–6)
Events are windows whose frozen cumulative return at close of day 4 / 5 / 6 is in the band (first such day). All strategies start
from the frozen book at that day. **n is small; no single row is evidence on its own** (pre-registered rule: n < 15 → not evidence).
{chr(10).join(rec)}

Reading: no alternative raises P(final > 0) over KEEP_FROZEN (53 % A-only, 62 % A+B). Re-rank (A5 / A1 / one-off) beats the baseline in
only 18–38 % of events and loses in 59–82 %; cash / drawdown triggers cut the worst-case a few pp but lower the median and P(final > 0);
tactical D4 is worse in 77–83 % of events. Concentration beats the baseline in ≈ 70 % of events (mean +0.4 … +0.5 pp) but does not
improve P(final > 0) or the downside. Top-12 proxy is ~0 for every strategy in every case; Top-30 proxy is highest for KEEP_FROZEN
(17.6–20.7 %) among the non-concentration strategies.

## 7. Actual competition path — post-hoc, n = 1, NOT used for any decision (10/27 → 11/02)
{mdtable(apx)}
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
"""
    (HERE / "REPORT.md").write_text(txt, encoding="utf-8")
    print(len(txt))


if __name__ == "__main__":
    main()
