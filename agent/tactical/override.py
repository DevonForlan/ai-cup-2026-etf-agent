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
CONFIG_PATH = ROOT / "config" / "tactical_override_v1.yaml"
MAX_NAMES, MIN_NAMES = 30, 20
OPERATIONAL_MODES = ("competition",)   # the scheduled production flow; dry-run / historical never apply the override
AS_FLOOR = Decimal("0.15")          # official Active Share floor (top-15 NAV method), each ETF
Q = Decimal("0.00000001")


def load_config(path: Path | str | None = None) -> dict | None:
    """Return the tactical config (+ `_fingerprint` = sha256 of the file bytes) or None if absent / disabled."""
    p = Path(path) if path else CONFIG_PATH
    try:
        raw = p.read_bytes()
        cfg = yaml.safe_load(raw.decode("utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not cfg.get("enabled") or cfg.get("version") != VERSION:
        return None
    cfg["_fingerprint"] = hashlib.sha256(raw).hexdigest()
    cfg["_path"] = str(p)
    return cfg


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


def sleeve_open(prev_h, tcfg) -> bool:
    base_sh = {str(t): int(s) for t, s in tcfg["baseline_holdings"].items()}
    return any(int(prev_h.get(str(t), 0)) > base_sh.get(str(t), 0) for t in tcfg["sleeve"])


def build_unwind(base, scores, prev_h, prev_cash, nav_prev, closes_prev, rb, cfg_q, market, etf_holdings, etf_meta, tcfg):
    tech = set(tcfg["reduce_tickers"])
    sleeve = {str(t) for t in tcfg["sleeve"]}
    base_sh = {str(t): int(s) for t, s in tcfg["baseline_holdings"].items()}
    rec = {"phase": "UNWIND", "attempts": [], "version": VERSION}
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
                "rank_of": rank_of, "guard_scale": True, "tactical": VERSION}
        txt = (f"戰術輪動回切 {VERSION}（Owner 指令 Issue #43）：持有期滿（預定 {tcfg['exit_trade_date']}），"
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


def is_active(trade_date: str, mode: str, *, config_path=None, modes=None) -> bool:
    """True when `activate` would install the wrapper for this run (used to keep the narrative template-based)."""
    tcfg = load_config(config_path)
    return bool(tcfg and phase_for(tcfg, trade_date) and mode in (modes or OPERATIONAL_MODES))


class Activation:
    def __init__(self, tcfg, trade_date, state_dir):
        self.tcfg, self.trade_date, self.state_dir = tcfg, trade_date, Path(state_dir)
        self.record: dict | None = None
        self.calls = 0

    def summary(self) -> dict | None:
        if self.tcfg is None:
            return None
        r = dict(self.record or {"status": "NOT_TRIGGERED"})
        r.update(version=VERSION, fingerprint=self.tcfg["_fingerprint"], trade_date=self.trade_date)
        return r

    def write(self) -> Path | None:
        s = self.summary()
        if not s or s["status"] == "NOT_TRIGGERED":
            return None
        self.state_dir.mkdir(parents=True, exist_ok=True)
        p = self.state_dir / f"{self.trade_date}_{s.get('phase', 'NA')}.json"
        s["recorded_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        p.write_text(json.dumps(s, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
        return p


@contextlib.contextmanager
def activate(trade_date: str, mode: str, *, config_path=None, state_dir=None, modes=None):
    """Patch `agent.pipeline.construct` for the duration of one run_day. A no-op when the override is absent, disabled,
    outside its dates, or the run mode is not an operational one. The patch is always restored."""
    import agent.pipeline as P
    modes = modes or OPERATIONAL_MODES
    tcfg = load_config(config_path)
    act = Activation(tcfg, trade_date, state_dir or (ROOT / "logs" / "tactical"))
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
            fn = build_entry if phase == "ENTRY" else build_unwind
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
