"""TACTICAL_TECH_RISK_ADJUSTED_V1 helpers (Issue #68): technology regime, short-horizon signals, sub-sector buckets, risk-adjusted utility.

Pure functions over plain dicts so they are unit-testable; the only I/O is `load_market_frames` (read-only, PIT: rows dated before the
trade date only). Nothing here touches Frozen Quant v1 (agent/features, agent/portfolio, agent/pipeline.py stay frozen).
"""
from __future__ import annotations

import math
from decimal import Decimal


def load_market_frames(trade_date: str, store=None):
    """(prices, institutional, overnight) restricted to rows dated strictly before `trade_date` (what exists at the 19:30 run)."""
    from agent.data.loaders import HistoryStore
    store = store or HistoryStore()
    out = []
    for table in ("daily_prices", "institutional", "market_overnight"):
        try:
            df = store.load(table)
            df = df[df["date"].astype(str) < str(trade_date)]
        except Exception:  # noqa: BLE001  missing table -> that signal is simply unavailable
            df = None
        out.append(df)
    return tuple(out)


def _std(xs):
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    if len(xs) < 5:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def ticker_signals(prices, institutional, tickers, window: int = 20) -> dict[str, dict]:
    """Per ticker: ret5, ret20, rs5, rs20 (vs the median of all priced names), flow5 (5d net institutional shares / 5d traded shares),
    vol20 (20d std of daily returns), gap_max5 (largest |open / previous close - 1| in 5d), move_max5 (largest |daily return| in 5d)."""
    sig: dict[str, dict] = {}
    if prices is None or len(prices) == 0:
        return sig
    px = prices.sort_values(["ticker", "date"])
    data: dict[str, tuple] = {}
    for t, g in px.groupby("ticker"):
        c = [float(x) for x in g["close"].tolist()][-(window + 1):]
        o = [float(x) for x in g["open"].tolist()][-(window + 1):]
        v = [float(x) for x in g["volume"].tolist()][-5:]
        if len(c) < 6:
            continue
        r = [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1] > 0]
        data[str(t)] = (r, c, o, v)
    m5 = _median([d[1][-1] / d[1][-6] - 1 for d in data.values() if d[1][-6] > 0])
    m20 = _median([d[1][-1] / d[1][0] - 1 for d in data.values() if len(d[1]) >= window + 1 and d[1][0] > 0])
    flow = {}
    if institutional is not None and len(institutional):
        ins = institutional.sort_values(["ticker", "date"])
        for t, g in ins.groupby("ticker"):
            flow[str(t)] = float(g["total_net"].tail(5).sum())
    for t in tickers:
        if t not in data:
            continue
        r, c, o, v = data[t]
        r5 = c[-1] / c[-6] - 1 if c[-6] > 0 else None
        r20 = c[-1] / c[0] - 1 if len(c) >= window + 1 and c[0] > 0 else None
        gaps = [abs(o[i] / c[i - 1] - 1) for i in range(max(1, len(c) - 5), len(c)) if c[i - 1] > 0 and o[i] > 0]
        moves = [abs(x) for x in r[-5:]]
        traded = sum(v) or None
        sig[t] = {"ret5": r5, "ret20": r20, "rs5": None if r5 is None else r5 - m5, "rs20": None if r20 is None else r20 - m20,
                  "flow5": (flow[t] / traded) if (t in flow and traded) else None, "vol20": _std(r[-window:]),
                  "gap_max5": max(gaps) if gaps else None, "move_max5": max(moves) if moves else None}
    return sig


def _z(vals: dict[str, float | None]) -> dict[str, float]:
    xs = [v for v in vals.values() if v is not None and not math.isnan(v)]
    if len(xs) < 3:
        return {t: 0.0 for t in vals}
    m = sum(xs) / len(xs)
    s = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) or 1.0
    return {t: 0.0 if v is None or math.isnan(v) else max(-3.0, min(3.0, (v - m) / s)) for t, v in vals.items()}


def composite_score(signals: dict[str, dict], rank_of: dict[str, int], cfg: dict) -> dict[str, float]:
    """Cross-sectional composite z over the technology names: Frozen Quant rank (primary), 5d / 20d relative strength, institutional flow,
    20d realized volatility (lower is better), extreme gap / sharp move (penalty). Missing inputs count as neutral (0)."""
    w = {"quant_rank": 0.40, "rs5": 0.15, "rs20": 0.15, "flow5": 0.10, "vol20": 0.10, "gap": 0.10}
    w.update(cfg.get("score_weights") or {})
    names = list(signals)
    nr = max(rank_of.values()) if rank_of else 1
    zr = _z({t: (-(rank_of[t]) / nr if t in rank_of else None) for t in names})            # better (smaller) rank -> higher
    z5, z20 = _z({t: signals[t].get("rs5") for t in names}), _z({t: signals[t].get("rs20") for t in names})
    zf, zv = _z({t: signals[t].get("flow5") for t in names}), _z({t: signals[t].get("vol20") for t in names})
    ext = {t: max(signals[t].get("gap_max5") or 0.0, signals[t].get("move_max5") or 0.0) for t in names}
    zg = _z(ext)
    thr = float(cfg.get("sharp_move_threshold", 0.07))
    return {t: (w["quant_rank"] * zr[t] + w["rs5"] * z5[t] + w["rs20"] * z20[t] + w["flow5"] * zf[t]
                - w["vol20"] * zv[t] - w["gap"] * zg[t] - (0.5 if ext[t] >= thr else 0.0)) for t in names}


def classify_regime(prices, overnight, tech, cfg: dict) -> dict:
    """STRONG / NORMAL / DEFENSIVE from the data the repo has: SOX and Taiwan index-futures-night returns, technology breadth, the technology
    basket's 5d relative strength and its 20d realized volatility. Documented thresholds, not fitted to recent results.
    DEFENSIVE if any stress flag (high basket vol, weak breadth, SOX / futures-night drop); STRONG only if all four strength tests hold."""
    inp = {"sox_ret1": None, "sox_ret5": None, "txf_night_ret": None, "breadth_ma20": None, "breadth_up5": None,
           "tech_rs5": None, "tech_vol20": None}
    if overnight is not None and len(overnight):
        for sym, k1, k5 in (("SOX", "sox_ret1", "sox_ret5"), ("TXF_NIGHT", "txf_night_ret", None)):
            g = overnight[overnight["symbol"] == sym].sort_values("date")
            if len(g):
                inp[k1] = float(g["ret"].iloc[-1])
                if k5 and len(g) >= 6:
                    inp[k5] = float(g["close"].iloc[-1] / g["close"].iloc[-6] - 1)
    if prices is not None and len(prices):
        px = prices.sort_values(["ticker", "date"])
        up_ma = up5 = n = 0
        basket, market = [], []
        daily: dict[str, list] = {}
        for t, g in px.groupby("ticker"):
            c = [float(x) for x in g["close"].tolist()][-21:]
            if len(c) < 21:
                continue
            t = str(t)
            r5 = c[-1] / c[-6] - 1
            (basket if t in tech else market).append(r5)
            if t in tech:
                n += 1
                up_ma += c[-1] > sum(c[-20:]) / 20
                up5 += r5 > 0
                daily[t] = [c[i] / c[i - 1] - 1 for i in range(1, len(c))]
        if n:
            inp["breadth_ma20"], inp["breadth_up5"] = up_ma / n, up5 / n
            inp["tech_rs5"] = sum(basket) / len(basket) - _median(market)
            days = min(len(v) for v in daily.values())
            ew = [sum(v[len(v) - days + i] for v in daily.values()) / len(daily) for i in range(days)]
            inp["tech_vol20"] = _std(ew)
    th = {"vol_high": 0.020, "breadth_low": 0.45, "breadth_strong": 0.65, "sox_down": -0.02, "txf_down": -0.015}
    th.update(cfg.get("regime_thresholds") or {})

    def has(k):
        return inp[k] is not None
    defensive = [n for n, hit in (
        (f"tech_vol20>={th['vol_high']:.1%}", has("tech_vol20") and inp["tech_vol20"] >= th["vol_high"]),
        (f"breadth_ma20<{th['breadth_low']:.0%}", has("breadth_ma20") and inp["breadth_ma20"] < th["breadth_low"]),
        (f"sox_ret1<={th['sox_down']:.0%}", has("sox_ret1") and inp["sox_ret1"] <= th["sox_down"]),
        (f"txf_night<={th['txf_down']:.1%}", has("txf_night_ret") and inp["txf_night_ret"] <= th["txf_down"])) if hit]
    strong = [n for n, hit in (
        ("sox_ret5>0", has("sox_ret5") and inp["sox_ret5"] > 0),
        (f"breadth_ma20>={th['breadth_strong']:.0%}", has("breadth_ma20") and inp["breadth_ma20"] >= th["breadth_strong"]),
        ("tech_rs5>0", has("tech_rs5") and inp["tech_rs5"] > 0),
        (f"tech_vol20<{th['vol_high']:.1%}", has("tech_vol20") and inp["tech_vol20"] < th["vol_high"])) if hit]
    bands = {"STRONG": (0.90, 0.95), "NORMAL": (0.87, 0.92), "DEFENSIVE": (0.85, 0.88)}
    bands.update({k: tuple(v) for k, v in (cfg.get("bands") or {}).items()})
    if defensive:
        name, why = "DEFENSIVE", defensive
    elif len(strong) == 4:
        name, why = "STRONG", strong
    else:
        name, why = "NORMAL", strong
    lo, hi = bands[name]
    return {"regime": name, "band_min": lo, "band_max": hi, "reasons": why, "inputs": inp,
            "missing_inputs": [k for k, v in inp.items() if v is None]}


def bucket_map(cfg: dict, tech: set[str]) -> dict[str, str]:
    m = {str(t): b for b, names in (cfg.get("buckets") or {}).items() for t in names}
    return {t: m.get(t, "other_tech") for t in tech}


def bucket_weights(weights: dict, bmap: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t, w in weights.items():
        if t in bmap:
            out[bmap[t]] = out.get(bmap[t], 0.0) + float(w)
    return out


def utility(weights: dict, z: dict[str, float], sigma: dict[str, float], bmap: dict[str, str], cost: float, cfg: dict) -> dict:
    """U = H * (mu'w - gamma/2 * w'Sigma w) - cost.  mu_i = IC * sigma_i * z_i (technology names);  Sigma from per-name 20d volatility with a
    bucket-aware correlation (same sub-sector rho_in, other technology rho_x, technology vs non-technology rho_t, non-technology rho_n), so a
    portfolio that looks diversified by ticker count but sits in one risk factor is charged for it. Hyper-parameters are documented assumptions."""
    p = {"ic": 0.03, "horizon_days": 5, "gamma": 4.0, "rho_in": 0.75, "rho_x": 0.55, "rho_t": 0.30, "rho_n": 0.25, "default_sigma": 0.025}
    p.update(cfg.get("utility") or {})
    names = list(weights)
    w = {t: float(weights[t]) for t in names}
    sg = {t: sigma.get(t) or p["default_sigma"] for t in names}
    mu = sum(w[t] * p["ic"] * sg[t] * z.get(t, 0.0) for t in names if t in bmap)
    var = 0.0
    for a in names:
        for b in names:
            if a == b:
                rho = 1.0
            elif a in bmap and b in bmap:
                rho = p["rho_in"] if bmap[a] == bmap[b] else p["rho_x"]
            elif a in bmap or b in bmap:
                rho = p["rho_t"]
            else:
                rho = p["rho_n"]
            var += w[a] * w[b] * sg[a] * sg[b] * rho
    H = p["horizon_days"]
    return {"utility": H * (mu - p["gamma"] / 2 * var) - cost, "alpha": H * mu, "risk": math.sqrt(var), "cost": cost}


def trade_cost(orders, closes, nav, cfg: dict) -> tuple[float, float]:
    """(cost as a fraction of NAV, turnover as a fraction of NAV): broker fee, sell-side securities tax, VWAP slippage and a per-order drag."""
    c = {"fee": 0.001425, "sell_tax": 0.003, "slippage": 0.0010, "per_order": 0.00002}
    c.update(cfg.get("cost_model") or {})
    cost = turnover = 0.0
    n = 0
    for o in orders:
        notional = float(Decimal(int(o.shares)) * Decimal(str(closes[o.ticker])))
        cost += notional * (c["fee"] + c["slippage"] + (c["sell_tax"] if o.side == "SELL" else 0.0))
        turnover += notional
        n += 1
    return cost / float(nav) + c["per_order"] * n, turnover / float(nav)
