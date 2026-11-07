"""Pure, deterministic entry / exit planning for the tactical sleeve (no I/O). Money in Decimal; sizes in whole lots.

Entry : sell tech pro rata to ~target_rotation_nav_pct of NAV_{T-1}, buy the spec's non-tech names with equal TWD weight.
Exit  : restore every touched ticker to its recorded pre-entry share count (idempotent: a restored book gives no orders).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from agent.config import D

Q6 = Decimal("0.000001")


class PlanError(RuntimeError):
    pass


@dataclass
class EntryPlan:
    sells: dict[str, int]
    buys: dict[str, int]
    pre_entry: dict[str, int]           # touched ticker -> shares before entry
    targets: dict[str, int]             # touched ticker -> shares after entry
    sold_value: Decimal
    bought_value: Decimal
    rotated_nav_pct: float
    tech_pct_before: float
    tech_pct_after: float
    notes: list[str] = field(default_factory=list)


def _lots(x: Decimal, lot: int, rounding=ROUND_HALF_UP) -> int:
    return int((x / lot).to_integral_value(rounding=rounding)) * lot


def tech_weight(holdings: dict[str, int], closes: dict, nav: Decimal, tech: set[str]) -> Decimal:
    return sum((Decimal(s) * D(closes[t]) for t, s in holdings.items() if t in tech), Decimal(0)) / D(nav)


def plan_entry(body: dict, sector_map: dict, prev_h: dict[str, int], closes: dict, nav: Decimal, universe: set[str],
               *, lot: int, buy_fee: Decimal, sell_fee: Decimal, sell_tax: Decimal) -> EntryPlan:
    forbidden = {str(x) for x in body.get("forbidden_tickers", [])}
    buy_names = [str(b["ticker"]) for b in body["buy_names"]][: int(body.get("max_new_names", 6))]
    bad = [t for t in buy_names if t in forbidden or t not in universe]
    if bad:
        raise PlanError(f"buy names outside the official universe / forbidden: {bad}")
    nav = D(nav)
    tech_labels = set(body["tech_sector_labels"])
    tech_idx = {t for t, s in sector_map.items() if s in tech_labels}
    # odd-lot holdings cannot be traded with whole-lot orders -> leave untouched
    cand = {t: s for t, s in prev_h.items() if t in tech_idx and s > 0 and s % lot == 0}
    if not cand:
        raise PlanError("no tradable tech holdings")
    for t in list(cand) + buy_names:
        if closes.get(t) is None:
            raise PlanError(f"missing T-1 close for {t}")
    target_val = D(body["target_rotation_nav_pct"]) * nav
    min_val = D(body["min_sell_nav_pct_per_name"]) * nav
    names = sorted(cand)
    sells: dict[str, int] = {}
    for _ in range(12):                                   # drop tiny sells, re-scale, until stable
        tv = sum((Decimal(cand[t]) * D(closes[t]) for t in names), Decimal(0))
        ratio = min(target_val / tv, Decimal(1))
        sells = {t: min(_lots(Decimal(cand[t]) * ratio, lot), cand[t]) for t in names}
        small = [t for t in names if sells[t] * D(closes[t]) < min_val]
        if not small:
            break
        names = [t for t in names if t not in small]
        if not names:
            raise PlanError("every tech sell is below the minimum order size")
    sells = {t: q for t, q in sells.items() if q > 0}
    gross = sum((Decimal(q) * D(closes[t]) for t, q in sells.items()), Decimal(0))
    net = gross * (1 - sell_fee - sell_tax)
    per = net / len(buy_names) / (1 + buy_fee)
    maxw = D(body.get("max_weight_per_new_name", 0.05))
    buys: dict[str, int] = {}
    for t in buy_names:
        px = D(closes[t])
        if prev_h.get(t, 0) % lot != 0:
            raise PlanError(f"{t}: odd-lot holding cannot be increased")
        sh = min(_lots(per / px, lot, ROUND_FLOOR), _lots(maxw * nav / px, lot, ROUND_FLOOR))
        if sh <= 0:
            raise PlanError(f"{t}: zero-lot buy")
        buys[t] = sh
    spent = sum((Decimal(q) * D(closes[t]) for t, q in buys.items()), Decimal(0))
    touched = sorted(set(sells) | set(buys))
    pre = {t: int(prev_h.get(t, 0)) for t in touched}
    tgt = {t: pre[t] - sells.get(t, 0) + buys.get(t, 0) for t in touched}
    after = {t: s for t, s in prev_h.items() if s > 0}
    after.update(tgt)
    after = {t: s for t, s in after.items() if s > 0}
    tb = float(tech_weight(prev_h, closes, nav, tech_idx))
    ta = float(tech_weight(after, closes, nav, tech_idx))
    return EntryPlan(sells, buys, pre, tgt, gross, spent, float(gross / nav), tb, ta,
                     [f"sold {len(sells)} tech names, bought {len(buys)} non-tech names"])


def plan_exit(pre_entry: dict[str, int], prev_h: dict[str, int], *, lot: int, scale: float = 1.0) -> dict[str, int]:
    """Target shares for every touched ticker whose holding differs from its recorded pre-entry count.
    scale < 1 moves only that fraction of each gap (whole lots, toward zero)."""
    out: dict[str, int] = {}
    for t, pre in sorted(pre_entry.items()):
        cur = int(prev_h.get(t, 0))
        if cur == pre or cur % lot != 0:
            continue
        gap = pre - cur
        moved = int((Decimal(abs(gap)) * D(scale) / lot).to_integral_value(rounding=ROUND_FLOOR)) * lot
        if moved == 0:
            continue
        out[t] = cur + (moved if gap > 0 else -moved)
    return out


def weights_for_targets(targets: dict[str, int], prev_h: dict[str, int], closes: dict, nav: Decimal,
                        lot: int) -> tuple[dict[str, Decimal], set[str]]:
    """target_w / no_trade for agent.portfolio.constructor._finalize. A traded name gets a weight half a lot above its
    target so derive-orders.v2 (floor to whole lots) lands exactly on the wanted share count."""
    nav = D(nav)
    w: dict[str, Decimal] = {}
    no_trade: set[str] = set()
    for t, s in prev_h.items():
        if s > 0 and (t not in targets or targets[t] == s):
            no_trade.add(t)
            w[t] = (Decimal(s) * D(closes[t]) / nav).quantize(Q6, rounding=ROUND_FLOOR)
    for t, ts in targets.items():
        if t in no_trade or ts == prev_h.get(t, 0):
            continue
        if ts > 0:
            w[t] = ((Decimal(ts) + Decimal(lot) / 2) * D(closes[t]) / nav).quantize(Q6, rounding=ROUND_FLOOR)
    return w, no_trade
