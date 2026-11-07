"""Hook: wrap agent.pipeline.construct for one run_day call. The frozen constructor ALWAYS runs first; the tactical layer
only replaces its result on the entry date (rotation) or when an open sleeve is due for unwinding (expiry first).

Fail closed: any problem on entry keeps the pure Frozen Quant v1 result. An exit that cannot be fully built is scaled
down and flagged TACTICAL_UNWIND_OVERDUE; if nothing legal exists the previous portfolio is held (never silently extended:
the flag + ledger state OVERDUE persist until holdings are restored).
"""
from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

from agent.config import D
from agent.tactical import ledger as LG
from agent.tactical import planner as PL
from agent.tactical.spec import load_spec


class Context:
    def __init__(self, trade_date: str, ops_cfg: dict, state_dir=None):
        self.trade_date = trade_date
        self.ops_cfg = ops_cfg
        self.state_dir = state_dir
        self.spec = load_spec(ops_cfg)
        self.outcome: dict = {"mode": "NONE", "applied": False, "trade_date": trade_date,
                              "spec_id": self.spec.id if self.spec else None,
                              "spec_fingerprint": self.spec.fingerprint if self.spec else None,
                              "pin_ok": self.spec.pin_ok if self.spec else None,
                              "pin_reason": self.spec.pin_reason if self.spec else "no tactical config"}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _finalize_targets(targets, prev_h, prev_cash, nav, closes, rb, cfg, etf_h, etf_meta, regime, stance, why,
                      cash_rng, info, notes, reason_code):
    from agent.portfolio.constructor import _finalize
    lot = rb.rules.lot_size
    w, no_trade = PL.weights_for_targets(targets, prev_h, closes, nav, lot)
    res = _finalize(w, no_trade, prev_h, prev_cash, nav, closes, rb, cfg, etf_h, etf_meta, regime, stance, why,
                    cash_rng, info, notes)
    if not getattr(res, "is_fallback", False):
        for p in res.plan:
            if p.action == "NO_TRADE":
                p.reason = "tactical_untouched"
        # verify the realised orders equal what was planned (lot arithmetic guard)
        got = {o.ticker: (o.target_shares) for o in res.orders}
        bad = {t: (got.get(t), v) for t, v in targets.items() if t in {o.ticker for o in res.orders} and got[t] != v}
        if bad or {o.ticker for o in res.orders} != {t for t, v in targets.items() if v != prev_h.get(t, 0)}:
            return None, f"order/target mismatch {bad}"
    return res, None


def _apply(ctx: Context, quant, scores, prev_h, prev_cash, nav, closes, rb, cfg, etf_h, etf_meta, regime_override):
    spec, td, out = ctx.spec, ctx.trade_date, ctx.outcome
    if spec is None:
        return quant
    sl = LG.load(ctx.state_dir, spec.id)
    lot = rb.rules.lot_size
    prev_h = {t: int(s) for t, s in prev_h.items() if int(s) > 0}
    nav = D(nav)
    rank_of = {}
    try:
        rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()}
    except Exception:  # noqa: BLE001
        pass
    base_info = {"kept": sorted(prev_h), "new": [], "dropped": [], "rank_of": rank_of, "tactical": {}}
    regime, stance = "neutral", "defensive"
    cash_rng = (0.0, 0.25)
    # ------------------------------------------------------------ EXIT (expiry first)
    if sl and sl.get("state") in LG.OPEN_STATES and td >= sl["exit_trade_date"] and (spec.body.get("unwind_even_if_disabled", True)):
        out.update(mode="EXIT", sleeve_state_before=sl["state"], exit_trade_date=sl["exit_trade_date"])
        if getattr(quant, "is_fallback", False):
            out.update(blocked="quant fallback (data); exit not built this run")
            sl["state"] = "OVERDUE" if td > sl["exit_trade_date"] else sl["state"]
            LG.save(ctx.state_dir, spec.id, sl)
            return quant
        pre = {t: int(v) for t, v in sl["pre_entry"].items()}
        full = PL.plan_exit(pre, prev_h, lot=lot, scale=1.0)
        if not full:                                   # nothing to unwind: restored (or never entered)
            entered = sl.get("entered_confirmed", False) or any(prev_h.get(t, 0) != v for t, v in pre.items())
            sl["state"] = "CLOSED_UNWOUND" if sl.get("unwind_built") else "CLOSED_NOT_ENTERED"
            sl["closed_at"], sl["closed_trade_date"] = _now(), td
            LG.save(ctx.state_dir, spec.id, sl)
            out.update(sleeve_state=sl["state"], note="holdings already equal pre-entry book; no unwind orders")
            return quant
        scales = [float(x) for x in spec.body.get("unwind_scales", [1.0, .75, .5, .25])]
        regime_t = ("neutral", "defensive", "戰術輪動還原：依帳本將輪動標的還原至輪動前股數", (0.0, 0.25))
        for sc in scales:
            tg = PL.plan_exit(pre, prev_h, lot=lot, scale=sc)
            if not tg:
                continue
            info = dict(base_info, tactical={"mode": "EXIT", "id": spec.id, "scale": sc,
                                             "exit_trade_date": sl["exit_trade_date"]})
            res, err = _finalize_targets(tg, prev_h, D(prev_cash), nav, closes, rb, cfg, etf_h, etf_meta, *regime_t,
                                         info, [f"TACTICAL EXIT {spec.id} scale={sc}"], "exit")
            if res is not None and not getattr(res, "is_fallback", False):
                complete = sc == 1.0
                sl.update(state="UNWIND_PLANNED" if complete else "OVERDUE", unwind_built=True, last_unwind_scale=sc,
                          unwind_orders={t: int(v) - int(prev_h.get(t, 0)) for t, v in tg.items()},
                          unwind_planned_for=td, updated_at=_now())
                if td > sl["exit_trade_date"] or not complete:
                    sl["state"] = "OVERDUE"
                LG.save(ctx.state_dir, spec.id, sl)
                out.update(applied=True, sleeve_state=sl["state"], unwind_scale=sc,
                           flag=("TACTICAL_UNWIND_OVERDUE" if sl["state"] == "OVERDUE" else None),
                           orders={t: int(v) - int(prev_h.get(t, 0)) for t, v in tg.items()})
                return res
        sl.update(state="OVERDUE", updated_at=_now(), overdue_reason="no legal unwind could be built")
        LG.save(ctx.state_dir, spec.id, sl)
        from agent.portfolio.constructor import FallbackToPreviousPortfolio
        out.update(applied=True, sleeve_state="OVERDUE", flag="TACTICAL_UNWIND_OVERDUE",
                   blocked="no legal unwind; previous portfolio held")
        return FallbackToPreviousPortfolio("TACTICAL_UNWIND_OVERDUE: no legal unwind could be built; holding")
    # ------------------------------------------------------------ ENTRY
    if td == spec.entry_date and spec.enabled and not (sl and sl.get("state") in LG.CLOSED_STATES):
        out["mode"] = "ENTRY"
        if getattr(quant, "is_fallback", False):
            out.update(blocked="Frozen Quant fell back (data incomplete); no rotation, frozen result kept")
            return quant
        try:
            ep = PL.plan_entry(spec.body, spec.sector_map, prev_h, closes, nav, set(rb.universe), lot=lot,
                               buy_fee=rb.rules.buy_fee_rate, sell_fee=rb.rules.sell_fee_rate,
                               sell_tax=rb.rules.transaction_tax_rate)
            info = dict(base_info, new=sorted(ep.buys), tactical={
                "mode": "ENTRY", "id": spec.id, "hold_days": spec.hold_days, "exit_trade_date": spec.exit_date,
                "rotated_nav_pct": round(ep.rotated_nav_pct, 4)})
            regime_t = ("neutral", "defensive",
                        f"戰術輪動（{spec.id}，Owner 指示）：短期減碼科技股約 {ep.rotated_nav_pct:.1%} NAV，"
                        f"轉入非科技標的，預計持有 {spec.hold_days} 個交易日，{spec.exit_date} 還原", (0.0, 0.25))
            res, err = _finalize_targets(ep.targets, prev_h, D(prev_cash), nav, closes, rb, cfg, etf_h, etf_meta,
                                         *regime_t, info, [f"TACTICAL ENTRY {spec.id}"], "entry")
            if res is None or getattr(res, "is_fallback", False):
                reason = err or getattr(res, "reason", "unknown")
                out.update(blocked=f"entry plan failed compliance: {reason}; frozen result kept")
                return quant
        except PL.PlanError as e:
            out.update(blocked=f"entry plan error: {e}; frozen result kept")
            return quant
        sleeve = {"id": spec.id, "spec_sha256": spec.sha256, "entry_trade_date": td, "hold_trading_days": spec.hold_days,
                  "exit_trade_date": spec.exit_date, "state": "PLANNED", "pre_entry": ep.pre_entry,
                  "sells": ep.sells, "buys": ep.buys,
                  "unwind_orders": {t: ep.pre_entry[t] - ep.targets[t] for t in ep.pre_entry},
                  "rotated_nav_pct": ep.rotated_nav_pct, "tech_pct_before": ep.tech_pct_before,
                  "tech_pct_after": ep.tech_pct_after, "price_basis": "T-1 close", "planned_at": _now()}
        LG.save(ctx.state_dir, spec.id, sleeve)
        fp = hashlib.sha256(json.dumps({"spec": spec.sha256, "sells": ep.sells, "buys": ep.buys}, sort_keys=True)
                            .encode()).hexdigest()
        out.update(applied=True, sleeve_state="PLANNED", sells=ep.sells, buys=ep.buys,
                   rotated_nav_pct=ep.rotated_nav_pct, tech_pct_before=ep.tech_pct_before,
                   tech_pct_after=ep.tech_pct_after, exit_trade_date=spec.exit_date,
                   tactical_fingerprint="sha256:" + fp, unwind_orders=sleeve["unwind_orders"])
        return res
    if not spec.enabled and td == spec.entry_date:
        out["blocked"] = f"overlay disabled: {spec.pin_reason}"
    return quant


@contextlib.contextmanager
def installed(ctx: Context):
    """Patch agent.pipeline.construct for the duration of one run_day call."""
    import agent.pipeline as P
    orig = P.construct

    def wrapped(scores, prev_holdings, prev_cash, nav_prev, closes_prev, rb, cfg, market, etf_holdings=None,
                etf_meta=None, method=None, holding_days=None, is_rebalance_day=True, regime_override=None,
                guard=None):
        quant = orig(scores, prev_holdings, prev_cash, nav_prev, closes_prev, rb, cfg, market, etf_holdings,
                     etf_meta, method, holding_days, is_rebalance_day, regime_override, guard)
        try:
            return _apply(ctx, quant, scores, prev_holdings, prev_cash, nav_prev, closes_prev, rb, cfg,
                          etf_holdings, etf_meta, regime_override)
        except Exception as e:  # noqa: BLE001  fail closed to the frozen result
            ctx.outcome.update(blocked=f"tactical error {type(e).__name__}: {e}; frozen result kept", applied=False)
            return quant

    P.construct = wrapped
    try:
        yield ctx
    finally:
        P.construct = orig
