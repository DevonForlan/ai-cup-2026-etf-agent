"""TACTICAL_OVERRIDE_V1 — Owner-directed temporary rotation out of technology (Issue #43, Owner directive 2026-11-08).

Design (nothing under the frozen paths is edited; Frozen Quant v1 stays the default and the baseline):
  * `activate()` wraps `agent.pipeline.construct` for one `run_day` call. The frozen constructor always runs first.
  * ENTRY  (trade_date == entry_trade_date): the Quant result is replaced by a rotated target (technology cluster scaled
    down by x % NAV, a pre-chosen non-tech sleeve bought) and passed through the SAME `_finalize` legality pipeline
    (lots, caps, cash band, post-trade compliance, Active Share, stress). First size on the ladder that passes wins;
    if none passes, the untouched Quant result is returned (fail closed: never an invalid D-Plan) and the reason is recorded.
  * UNWIND (trade_date >= exit_trade_date and the sleeve is still held): expiry-first, explicit reverse orders back to the
    stored pre-rotation lots, derived from the ACTUAL holdings (so a missed day, a partial fill or a re-run all work).
    If the unwind cannot be produced it is recorded as TACTICAL_UNWIND_OVERDUE and retried in the next window;
    the sleeve is never silently extended or treated as unwound.
  * Rollback toggle: delete config/tactical_override_v1.yaml or set `enabled: false`.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path

import yaml

from agent.config import ROOT, D
from agent.portfolio import baseline as B
from agent.portfolio import constructor as K

VERSION = "TACTICAL_OVERRIDE_V1"
VERSION_V2 = "TACTICAL_OVERRIDE_V2_TECH_LT10"      # Issue #49: supersedes V1 for the same trade date (tech weight < 10 % NAV)
VERSIONS = (VERSION, VERSION_V2)
CONFIG_PATH = ROOT / "config" / "tactical_override_v1.yaml"
CONFIG_PATH_V2 = ROOT / "config" / "tactical_override_v2.yaml"
STATE_DIR = ROOT / "logs" / "tactical"
MAX_NAMES, MIN_NAMES = 30, 20
OPERATIONAL_MODES = ("competition",)   # the scheduled production flow; dry-run / historical never apply the override
AS_FLOOR = Decimal("0.15")          # official Active Share floor (top-15 NAV method), each ETF
Q = Decimal("0.00000001")


def load_config(path: Path | str | None = None) -> dict | None:
    """Return the tactical config (+ `_fingerprint` = sha256 of the file bytes) or None if absent / disabled."""
    p = Path(path) if path else CONFIG_PATH      # resolved at call time so tests can point it elsewhere
    try:
        raw = p.read_bytes()
        cfg = yaml.safe_load(raw.decode("utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not cfg.get("enabled") or cfg.get("version") not in VERSIONS:
        return None
    cfg["_fingerprint"] = hashlib.sha256(raw).hexdigest()
    cfg["_path"] = str(p)
    return cfg


def resolve_config(config_path=None, trade_date: str | None = None) -> dict | None:
    """An explicit path wins. Otherwise the newest version (V2) is used for every date it covers, else V1."""
    if config_path:
        return load_config(config_path)
    for p in (CONFIG_PATH_V2, CONFIG_PATH):           # module attributes: resolved at call time (tests patch them)
        c = load_config(p)
        if c is not None and (trade_date is None or phase_for(c, trade_date) is not None):
            return c
    return None


def _sleeve_names(tcfg: dict) -> set[str]:
    """Names that must be flat after the unwind: this version's sleeve plus any superseded version's sleeve."""
    return {str(t) for t in tcfg["sleeve"]} | {str(t) for t in tcfg.get("legacy_sleeve_names", [])}


def phase_for(cfg: dict, trade_date: str) -> str | None:
    if trade_date == str(cfg["entry_trade_date"]):
        return "ENTRY"
    if trade_date >= str(cfg["exit_trade_date"]):
        return "UNWIND"
    return None


def _closes(closes_prev, t):
    return D(closes_prev[t])


def _weights(prev_h, closes_prev, nav_prev):
    return {t: Decimal(s) * _closes(closes_prev, t) / nav_prev for t, s in prev_h.items() if int(s) > 0}


def _base_meta(base, market, cfg_q):
    if isinstance(base, K.TargetPortfolio):
        return base.regime, base.stance, base.regime_why, base.cash_range
    regime, stance, cash_rng, why = B.regime_from_market(market, cfg_q)
    return regime, stance, why, cash_rng


def _summarise(res, prev_h, closes_prev, nav_prev, tech, names):
    sells = {o.ticker: int(o.shares) for o in res.orders if o.side == "SELL"}
    buys = {o.ticker: int(o.shares) for o in res.orders if o.side == "BUY"}
    ew = res.est_weights
    before = _weights(prev_h, closes_prev, nav_prev)
    return {
        "sells": sells, "buys": buys,
        "orders": len(res.orders),
        "tech_weight_before": float(sum(v for t, v in before.items() if t in tech)),
        "tech_weight_after": float(sum(v for t, v in ew.items() if t in tech)),
        "cash_weight_after": float(res.est_cash / res.est_nav),
        "holdings_after": len(res.est_holdings),
        "max_weight_after": float(max(ew.values())) if ew else None,
        "weights_after": {t: round(float(v), 6) for t, v in sorted(ew.items(), key=lambda kv: -kv[1])},
        "weights_before": {t: round(float(v), 6) for t, v in sorted(before.items(), key=lambda kv: -kv[1])},
        "active_share_min": None if res.active_share is None or res.active_share.minimum_active_share is None
        else float(res.active_share.minimum_active_share),
        "active_share_benchmark": getattr(res.active_share, "benchmark_ticker", None),
        "est_nav": float(res.est_nav),
        "names": {t: (names.get(t) or "") for t in set(sells) | set(buys)},
    }


def _finalize(target_w, no_trade, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg_q, etf_holdings, etf_meta, base,
              market, notes, info):
    regime, stance, why, cash_rng = _base_meta(base, market, cfg_q)
    return K._finalize(target_w, no_trade, prev_h, D(prev_cash), D(nav_prev), closes_prev, rb, cfg_q, etf_holdings,
                       etf_meta, regime, stance, why, cash_rng, info, notes)


def _guards(res, rb):
    """Mandatory pre-submission guards on top of `_finalize`'s official post-trade checks."""
    if not isinstance(res, K.TargetPortfolio):
        return f"constructor fallback: {getattr(res, 'reason', '')[:200]}"
    n = len(res.est_holdings)
    if not (MIN_NAMES <= n <= MAX_NAMES):
        return f"holdings {n} not in {MIN_NAMES}-{MAX_NAMES}"
    if res.est_cash / res.est_nav >= rb.rules.cash_max_weight:
        return "cash >= official limit"
    for t, w in res.est_weights.items():
        if w > rb.rules.max_weight(t):
            return f"{t} weight {float(w):.4f} above the official single-name cap"
    if any(t not in rb.universe for t in res.est_holdings):
        return "holding outside the official 150-name universe"
    a = res.active_share
    if a is None or a.minimum_active_share is None:
        return "Active Share unavailable (fail closed)"
    if a.minimum_active_share < AS_FLOOR:
        return f"Active Share {float(a.minimum_active_share):.4f} below {float(AS_FLOOR)}"
    return None


def build_entry(base, scores, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg_q, market, etf_holdings, etf_meta, tcfg):
    tech = set(tcfg["reduce_tickers"])
    sleeve_raw = {str(t): Decimal(str(f)) for t, f in tcfg["sleeve"].items()}
    tot = sum(sleeve_raw.values())
    sleeve = {t: f / tot for t, f in sleeve_raw.items()}
    rec = {"phase": "ENTRY", "attempts": []}
    bad = [t for t in sleeve if t not in rb.universe or closes_prev.get(t) is None]
    if bad:
        rec.update(status="BLOCKED", reason=f"sleeve names not tradable / no price: {bad}")
        return base, rec
    cur_w = _weights(prev_h, closes_prev, D(nav_prev))
    tw = sum((v for t, v in cur_w.items() if t in tech), Decimal(0))
    if tw <= 0:
        rec.update(status="NOOP", reason="no technology holdings to reduce")
        return base, rec
    rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()} if "rank" in scores else {}
    names = {t: rb.universe[t]["name"] for t in rb.universe}
    for x in tcfg["rotation_nav_pct_ladder"]:
        x_eff = min(Decimal(str(x)), tw)
        target = dict(cur_w)
        for t in list(cur_w):
            if t in tech:
                target[t] = cur_w[t] * (1 - x_eff / tw)
        for t, f in sleeve.items():
            target[t] = target.get(t, Decimal(0)) + x_eff * f
        no_trade = {t for t in prev_h if t not in tech and t not in sleeve}
        new_names = [t for t in sleeve if t not in prev_h]
        txt = (f"戰術輪動 {VERSION}（Owner 指令 Issue #43）：臨時 {tcfg['hold_trading_days']} 個交易日降低科技曝險 "
               f"{float(x_eff):.1%} NAV，配置非科技 {len(sleeve)} 檔，預定 {tcfg['exit_trade_date']} 回切")
        info = {"kept": list(prev_h), "new": new_names, "dropped": [], "rank_of": rank_of, "guard_scale": True,
                "tactical": VERSION}
        res = _finalize(target, no_trade, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg_q, etf_holdings, etf_meta, base,
                        market, [txt], info)
        why = _guards(res, rb)
        rec["attempts"].append({"x_requested": float(x), "x_effective": float(x_eff), "result": "PASS" if why is None else why})
        if why is None:
            rec.update(status="APPLIED", x_effective=float(x_eff), version=VERSION, hold_trading_days=tcfg["hold_trading_days"],
                       exit_trade_date=str(tcfg["exit_trade_date"]),
                       sleeve={t: {"weight_of_rotation": float(f), "industry": tcfg.get("sleeve_industry", {}).get(t),
                                   "name": names.get(t)} for t, f in sleeve.items()},
                       **_summarise(res, prev_h, closes_prev, D(nav_prev), tech, names))
            return res, rec
    rec.update(status="BLOCKED", reason="no rotation size passed every guard; untouched Quant result kept (fail closed)")
    return base, rec


def _alloc(total: Decimal, rel: dict, cap: Decimal):
    """Split `total` over `rel` (relative weights) with a per-name cap (water-filling). None if it cannot be placed."""
    w, free, remaining = {}, dict(rel), total
    while free:
        s = sum(free.values())
        over = [t for t, v in free.items() if remaining * v / s > cap]
        if not over:
            w.update({t: remaining * v / s for t, v in free.items()})
            return w
        for t in over:
            w[t] = cap
            remaining -= cap
            del free[t]
        if remaining < 0:
            return None
    return w if remaining <= Decimal("0.0000001") else None


def _tech_guard(res, tech, tcfg) -> str | None:
    """Issue #49 hard target: technology weight (same 7-industry cluster as #41-#43) strictly below the target, on total NAV."""
    tmax = Decimal(str(tcfg["target_tech_weight_max"]))
    tguard = Decimal(str(tcfg.get("tech_guard_max", tmax)))
    tw = sum((w for t, w in res.est_weights.items() if t in tech), Decimal(0))
    if not tw < tmax:
        return f"technology weight {float(tw):.4%} not strictly below {float(tmax):.2%}"
    if tw > tguard:
        return f"technology weight {float(tw):.4%} above the design guard {float(tguard):.2%} (price-drift margin)"
    if any(p.reason == "decision_limit" for p in getattr(res, "plan", [])):
        return "a planned decision was demoted by the 30-decision limit"
    return None


def build_entry_v2(base, scores, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg_q, market, etf_holdings, etf_meta, tcfg):
    """TACTICAL_OVERRIDE_V2_TECH_LT10 (Issue #49): hard-cap technology below 10 % NAV, restructure into diversified non-tech.
    Construction is mechanical (config + T-1 closes): the smallest tech positions stay untouched, the next smallest keep a
    small residual (so the book still has >= target holdings with <= 30 orders), the rest are sold; the non-tech names of
    `sleeve` (priority order, relative weights) are bought with a per-name cap. Same `_finalize` + `_guards` as V1."""
    ver = tcfg["version"]
    tech = set(tcfg["reduce_tickers"])
    nav = D(nav_prev)
    rec = {"phase": "ENTRY", "attempts": [], "version": ver}
    names = {t: rb.universe[t]["name"] for t in rb.universe}
    rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()} if "rank" in scores else {}
    order_cap = int(tcfg.get("max_orders", 30))
    min_names = int(tcfg.get("target_holdings_min", 22))
    buy_cap = Decimal(str(tcfg.get("buy_weight_cap", 0.098)))
    lot = rb.rules.lot_size
    buy_all = [str(t) for t in tcfg["sleeve"]]
    bad = [t for t in buy_all if t in tech or t not in rb.universe or closes_prev.get(t) is None]
    if bad:
        rec.update(status="BLOCKED", reason=f"sleeve names not tradable / tech / no price: {bad}")
        return base, rec
    cur_w = _weights(prev_h, closes_prev, nav)
    tw0 = sum((v for t, v in cur_w.items() if t in tech), Decimal(0))
    if tw0 <= 0:
        rec.update(status="NOOP", reason="no technology holdings to reduce")
        return base, rec
    held_tech = sorted((t for t in cur_w if t in tech), key=lambda t: (cur_w[t], t))
    for step in tcfg["ladder"]:
        cash_t, u_max, n_buy = Decimal(str(step["cash_target"])), Decimal(str(step["untouched_max"])), int(step["n_buys"])
        buys = buy_all[:n_buy]
        rel = {t: Decimal(str(tcfg["sleeve"][t])) for t in buys}
        untouched, u = [], Decimal(0)
        for t in held_tech:                                  # smallest positions stay as they are (no order)
            if u + cur_w[t] <= u_max:
                untouched.append(t)
                u += cur_w[t]
            else:
                break
        rest = [t for t in held_tech if t not in untouched]
        nontech_held = [t for t in cur_w if t not in tech]
        nontech_final = set(nontech_held) | set(buys)
        b = max(0, min(len(rest), min_names - len(untouched) - len(nontech_final)))
        by_lot = sorted(rest, key=lambda t: (D(closes_prev[t]), t))           # cheapest lots keep the residual tiny
        partial = by_lot[:b]
        exits = [t for t in rest if t not in partial]
        n_orders = len(rest) + len(buys)                      # tech sells + non-tech buys (other held non-tech is untouched)
        att = {"cash_target": float(cash_t), "untouched_max": float(u_max), "n_buys": n_buy, "untouched": len(untouched),
               "partial": len(partial), "exits": len(exits), "orders_planned": n_orders}
        rec["attempts"].append(att)
        if n_orders > order_cap:
            att["result"] = f"planned orders {n_orders} > {order_cap}"
            continue
        resid_budget = Decimal(str(tcfg["tech_design_max"])) - u
        per = (resid_budget / len(partial)) if partial else Decimal(0)
        target = {}
        for t in untouched:
            target[t] = cur_w[t]
        for t in partial:                                    # at least one lot, never more than the position itself
            lot_w = D(closes_prev[t]) * lot / nav
            target[t] = min(max(per, lot_w * Decimal("1.05")), cur_w[t])
        for t in exits:
            target[t] = Decimal(0)
        resid = sum((target[t] for t in partial), Decimal(0))
        kept_nt = sum((cur_w[t] for t in nontech_held if t not in buys), Decimal(0))
        total_buy = (Decimal(1) - cash_t) - u - resid - kept_nt
        alloc = _alloc(total_buy, rel, buy_cap) if total_buy > 0 else None
        if alloc is None:
            att["result"] = "buy weights cannot be placed under the per-name cap"
            continue
        target.update({t: w.quantize(Q, rounding="ROUND_FLOOR") for t, w in alloc.items()})
        no_trade = set(untouched) | {t for t in nontech_held if t not in buys}
        new_names = [t for t in buys if t not in prev_h]
        txt = (f"戰術覆蓋 {ver}（Owner 指令 Issue #49）：臨時 {tcfg['hold_trading_days']} 個交易日將科技曝險由 "
               f"{float(tw0):.1%} 降至 10% NAV 以下，重組為非科技 {len(buys)} 檔，預定 {tcfg['exit_trade_date']} 回切")
        info = {"kept": list(prev_h), "new": new_names, "dropped": list(exits), "rank_of": rank_of, "guard_scale": True,
                "tactical": ver}
        res = _finalize(target, no_trade, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg_q, etf_holdings, etf_meta, base,
                        market, [txt], info)
        why = _guards(res, rb) or (_tech_guard(res, tech, tcfg) if isinstance(res, K.TargetPortfolio) else None)
        att["result"] = "PASS" if why is None else why
        if why is None:
            summ = _summarise(res, prev_h, closes_prev, nav, tech, names)
            ew = res.est_weights
            rec.update(status="APPLIED", version=ver, hold_trading_days=tcfg["hold_trading_days"],
                       exit_trade_date=str(tcfg["exit_trade_date"]),
                       target_tech_weight_max=float(tcfg["target_tech_weight_max"]),
                       nontech_weight_after=float(sum(v for t, v in ew.items() if t not in tech)),
                       sleeve={t: {"target_weight": float(ew.get(t, 0)), "name": names.get(t)} for t in buys},
                       untouched_tech=untouched, partial_tech=partial, exited_tech=exits, **summ)
            rec["unwind_plan"] = {                            # persisted BEFORE submission: exact reverse of this entry
                "trade_date": str(tcfg["exit_trade_date"]),
                "policy": "expiry-first; restore baseline lots from ACTUAL holdings",
                "sell_all": summ["buys"], "buy_back": summ["sells"],
                "restore_to_baseline_shares": {t: int(v) for t, v in tcfg["baseline_holdings"].items()}}
            return res, rec
    rec.update(status="BLOCKED", reason="no ladder step passed every guard; untouched Quant result kept (fail closed)")
    return base, rec



def sleeve_open(prev_h, tcfg) -> bool:
    base_sh = {str(t): int(s) for t, s in tcfg["baseline_holdings"].items()}
    return any(int(prev_h.get(str(t), 0)) > base_sh.get(str(t), 0) for t in _sleeve_names(tcfg))


def build_unwind(base, scores, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg_q, market, etf_holdings, etf_meta, tcfg):
    tech = set(tcfg["reduce_tickers"])
    sleeve = _sleeve_names(tcfg)
    base_sh = {str(t): int(s) for t, s in tcfg["baseline_holdings"].items()}
    ver = tcfg["version"]
    rec = {"phase": "UNWIND", "attempts": [], "version": ver}
    if not sleeve_open(prev_h, tcfg):
        rec.update(status="NOOP", reason="sleeve not open (nothing above the stored baseline)")
        return base, rec
    rank_of = {t: int(r) for t, r in scores["rank"].dropna().items()} if "rank" in scores else {}
    names = {t: rb.universe[t]["name"] for t in rb.universe}
    cur_w = _weights(prev_h, closes_prev, D(nav_prev))
    nav = D(nav_prev)
    for k in (Decimal(1), Decimal("0.97"), Decimal("0.94")):         # buy-back fraction ladder if cash would not allow 100 %
        target = dict(cur_w)
        for t in sleeve:
            target[t] = Decimal(0)
        for t, sh in base_sh.items():
            if t in tech or t in sleeve:
                if closes_prev.get(t) is None:
                    continue
                # +500 shares of head-room so the lot floor lands exactly on the stored lot count
                target[t] = (Decimal(sh) * k + Decimal(500)) * _closes(closes_prev, t) / nav if sh else Decimal(0)
        no_trade = {t for t in prev_h if t not in tech and t not in sleeve}
        info = {"kept": [t for t in prev_h if t not in sleeve], "new": [], "dropped": sorted(t for t in sleeve if prev_h.get(t)),
                "rank_of": rank_of, "guard_scale": True, "tactical": ver}
        txt = (f"戰術輪動回切 {ver}（Owner 指令 Issue #43）：持有期滿（預定 {tcfg['exit_trade_date']}），"
               "賣出非科技戰術部位並回補科技至輪動前張數")
        res = _finalize(target, no_trade, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg_q, etf_holdings, etf_meta, base,
                        market, [txt], info)
        why = _guards(res, rb)
        rec["attempts"].append({"buyback_fraction": float(k), "result": "PASS" if why is None else why})
        if why is None:
            rec.update(status="APPLIED", buyback_fraction=float(k), **_summarise(res, prev_h, closes_prev, nav, tech, names))
            return res, rec
    rec.update(status="UNWIND_OVERDUE", tactical_status="TACTICAL_UNWIND_OVERDUE",
               reason="unwind did not pass the guards; Quant result returned, sleeve NOT unwound, retry in the next window")
    return base, rec


def is_active(trade_date: str, mode: str, *, config_path=None, modes=None, prev_holdings=None) -> bool:
    """True when the override can change today's D-Plan (used to keep the per-decision narrative template-based).
    On an unwind date it is only active while the sleeve is actually open (holdings given), so ordinary later days keep
    the LLM narrative."""
    tcfg = resolve_config(config_path, trade_date)
    if not (tcfg and mode in (modes or OPERATIONAL_MODES)):
        return False
    ph = phase_for(tcfg, trade_date)
    if ph == "UNWIND" and prev_holdings is not None:
        return sleeve_open({t: int(s) for t, s in prev_holdings.items()}, tcfg)
    return bool(ph)


def config_rel(act) -> str:
    """Repo-relative posix path of the config this activation used (archived with the run)."""
    path = Path(act.tcfg["_path"]).resolve()
    try:
        return path.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


class Activation:
    def __init__(self, tcfg, trade_date, state_dir):
        self.tcfg, self.trade_date, self.state_dir = tcfg, trade_date, Path(state_dir)
        self.record: dict | None = None
        self.calls = 0

    def summary(self) -> dict | None:
        if self.tcfg is None:
            return None
        r = dict(self.record or {"status": "NOT_TRIGGERED"})
        r.update(version=self.tcfg["version"], fingerprint=self.tcfg["_fingerprint"], trade_date=self.trade_date)
        return r

    def write(self) -> Path | None:
        s = self.summary()
        if not s or s["status"] == "NOT_TRIGGERED":
            return None
        self.state_dir.mkdir(parents=True, exist_ok=True)
        suffix = "" if self.tcfg["version"] == VERSION else "_V2"          # V1 evidence files are never overwritten
        p = self.state_dir / f"{self.trade_date}_{s.get('phase', 'NA')}{suffix}.json"
        s["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        p.write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
        return p


@contextlib.contextmanager
def activate(trade_date: str, mode: str, *, config_path=None, state_dir=None, modes=None):
    """Patch `agent.pipeline.construct` for the duration of one run_day. A no-op when the override is absent, disabled,
    outside its dates, or the run mode is not an operational one. The patch is always restored."""
    import agent.pipeline as P
    modes = modes or OPERATIONAL_MODES
    tcfg = resolve_config(config_path, trade_date)
    act = Activation(tcfg, trade_date, state_dir or STATE_DIR)
    phase = phase_for(tcfg, trade_date) if tcfg else None
    if tcfg is None or phase is None or mode not in modes:
        yield act
        return
    orig = P.construct

    def wrapped(scores, prev_holdings, prev_cash, nav_prev, closes_prev, rb, cfg, market, etf_holdings=None,
                etf_meta=None, method=None, holding_days=None, is_rebalance_day=True, regime_override=None, guard=None):
        base = orig(scores, prev_holdings, prev_cash, nav_prev, closes_prev, rb, cfg, market, etf_holdings, etf_meta, method,
                    holding_days, is_rebalance_day, regime_override, guard)
        act.calls += 1
        prev_h = {t: int(s) for t, s in prev_holdings.items() if int(s) > 0}
        try:
            fn = (build_entry_v2 if tcfg["version"] == VERSION_V2 else build_entry) if phase == "ENTRY" else build_unwind
            res, rec = fn(base, scores, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg, market, etf_holdings, etf_meta, tcfg)
        except Exception as e:  # noqa: BLE001  fail closed: untouched Quant result, reason recorded
            res, rec = base, {"phase": phase, "status": "UNWIND_OVERDUE" if phase == "UNWIND" else "BLOCKED",
                              "reason": f"program error: {type(e).__name__}: {e}"[:300]}
            if phase == "UNWIND":
                rec["tactical_status"] = "TACTICAL_UNWIND_OVERDUE"
        act.record = rec
        return res

    P.construct = wrapped
    try:
        yield act
    finally:
        P.construct = orig
        try:
            act.write()
        except OSError:
            pass
