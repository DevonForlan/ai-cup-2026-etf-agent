"""Portfolio / order compliance checks against OFFICIAL rules (strategy buffers are separate).

Rule IDs:
  R_COUNT, R_UNIVERSE, R_TSMC_CAP, R_OTHER_CAP, R_CASH_NEG, R_CASH_MAX, R_LOT, R_NO_SHORT,
  R_OVERSELL, R_ACTIVE_SHARE
"""
from __future__ import annotations

from decimal import Decimal

from agent.config import D
from agent.engine.active_share import ActiveShareResult
from agent.engine.models import Report, Status
from agent.engine.rules import RuleBook

SRC = {
    "R_COUNT": "比賽辦法 §六(八)、§六(十四)(3)",
    "R_UNIVERSE": "比賽辦法 §六(七)、§六(十四)(5)",
    "R_TSMC_CAP": "比賽辦法 §六(八)、§六(十四)(4)",
    "R_OTHER_CAP": "比賽辦法 §六(八)、§六(十四)(4)",
    "R_CASH_NEG": "比賽辦法 §六(四)、§六(十四)(2)",
    "R_CASH_MAX": "比賽辦法 §六(九)、§六(十四)(2)",
    "R_LOT": "比賽辦法 §六(十)；schema order.shares",
    "R_NO_SHORT": "比賽辦法 §六(十)",
    "R_OVERSELL": "指南 ⑥ C13",
    "R_ACTIVE_SHARE": "比賽辦法 §六(十三)",
}


def weights_from_holdings(holdings: dict[str, int], prices: dict[str, object],
                          cash) -> tuple[dict[str, Decimal], Decimal, Decimal]:
    """Returns (weights of NAV, nav, cash_weight). Shares × price + cash."""
    mv = {t: Decimal(int(s)) * D(prices[t]) for t, s in holdings.items() if int(s) != 0}
    nav = sum(mv.values(), Decimal(0)) + D(cash)
    if nav <= 0:
        return {t: Decimal(0) for t in mv}, nav, Decimal(0)
    return {t: v / nav for t, v in mv.items()}, nav, D(cash) / nav


def check_count(n: int, rb: RuleBook, rep: Report, label: str = "") -> None:
    r = rb.rules
    lo, hi = r.holdings_min, r.holdings_max
    inclusive = rb.assumptions.holdings_count_inclusive
    ok = (lo <= n <= hi) if inclusive else (lo < n < hi)
    edge = n in (lo, hi)
    if ok and edge:
        rep.add("R_COUNT", Status.PASS, f"{label}持股 {n} 檔位於邊界（端點含入為未確認假設 NC-6）",
                n, [lo, hi], SRC["R_COUNT"], assumption="holdings_count_inclusive")
    elif ok:
        rep.add("R_COUNT", Status.PASS, f"{label}持股 {n} 檔", n, [lo, hi], SRC["R_COUNT"])
    else:
        rep.add("R_COUNT", Status.FAIL, f"{label}持股 {n} 檔，不在 {lo}–{hi}", n, [lo, hi], SRC["R_COUNT"])


def check_weights(weights: dict[str, Decimal], rb: RuleBook, rep: Report, label: str = "") -> None:
    r = rb.rules
    for t, w in sorted(weights.items()):
        cap = r.max_weight(t)
        rid = "R_TSMC_CAP" if t == r.tsmc_ticker else "R_OTHER_CAP"
        if w > cap:
            rep.add(rid, Status.FAIL, f"{label}{t} 權重 {float(w):.4%} 超過上限 {float(cap):.0%}", w, cap,
                    SRC[rid], ticker=t)
    if not [c for c in rep.checks if c.rule_id in ("R_TSMC_CAP", "R_OTHER_CAP") and c.status == Status.FAIL]:
        mx = max(weights.values(), default=Decimal(0))
        rep.add("R_OTHER_CAP", Status.PASS, f"{label}個股權重皆未超限（最大 {float(mx):.4%}）", mx,
                {"2330": r.tsmc_max_weight, "other": r.other_max_weight}, SRC["R_OTHER_CAP"])


def check_cash(cash_weight: Decimal, cash: Decimal, rb: RuleBook, rep: Report, label: str = "") -> None:
    r = rb.rules
    if cash < r.cash_min:
        rep.add("R_CASH_NEG", Status.FAIL, f"{label}現金為負 {cash}", cash, r.cash_min, SRC["R_CASH_NEG"])
    else:
        rep.add("R_CASH_NEG", Status.PASS, f"{label}現金非負", cash, r.cash_min, SRC["R_CASH_NEG"])
    if cash_weight > r.cash_max_weight:
        rep.add("R_CASH_MAX", Status.FAIL, f"{label}現金比 {float(cash_weight):.4%} 超過 25%", cash_weight,
                r.cash_max_weight, SRC["R_CASH_MAX"])
    elif cash_weight == r.cash_max_weight:
        st = Status.PASS if rb.assumptions.cash_equal_25_allowed else Status.FAIL
        rep.add("R_CASH_MAX", st, f"{label}現金比恰為 25%（是否允許未確認 NC-6；採假設 "
                f"{rb.assumptions.cash_equal_25_allowed}）", cash_weight, r.cash_max_weight, SRC["R_CASH_MAX"],
                assumption="cash_equal_25_allowed")
    else:
        rep.add("R_CASH_MAX", Status.PASS, f"{label}現金比 {float(cash_weight):.4%} < 25%", cash_weight,
                r.cash_max_weight, SRC["R_CASH_MAX"])


def check_universe(tickers, rb: RuleBook, rep: Report, label: str = "") -> None:
    bad = sorted(set(tickers) - rb.universe_set)
    if bad:
        rep.add("R_UNIVERSE", Status.FAIL, f"{label}持有/交易非 150 檔標的 {bad}", bad, "universe_150",
                SRC["R_UNIVERSE"])
    else:
        rep.add("R_UNIVERSE", Status.PASS, f"{label}全部標的在 150 檔清單內", len(set(tickers)), 150,
                SRC["R_UNIVERSE"])


def check_lots_and_short(holdings: dict[str, int], rb: RuleBook, rep: Report, label: str = "") -> None:
    lot = rb.rules.lot_size
    neg = {t: s for t, s in holdings.items() if int(s) < 0}
    odd = {t: s for t, s in holdings.items() if int(s) % lot != 0}
    rep.add("R_NO_SHORT", Status.FAIL if neg else Status.PASS,
            f"{label}負持股 {neg}" if neg else f"{label}無空頭部位", neg or 0, 0, SRC["R_NO_SHORT"])
    # Odd shares may arise from stock dividends (NC-7) -> WARNING not FAIL for holdings.
    rep.add("R_LOT", Status.WARNING if odd else Status.PASS,
            f"{label}持股非千股倍數 {odd}（可能來自配股）" if odd else f"{label}持股皆為千股倍數",
            odd or 0, lot, SRC["R_LOT"])


def check_portfolio(holdings: dict[str, int], prices: dict[str, object], cash, rb: RuleBook,
                    label: str = "", name: str = "portfolio") -> Report:
    rep = Report(name)
    held = {t: int(s) for t, s in holdings.items() if int(s) != 0}
    w, nav, cw = weights_from_holdings(held, prices, cash)
    check_count(len(held), rb, rep, label)
    check_universe(held, rb, rep, label)
    check_weights(w, rb, rep, label)
    check_cash(cw, D(cash), rb, rep, label)
    check_lots_and_short(held, rb, rep, label)
    return rep


def check_target_weights(target_w: dict[str, object], rb: RuleBook, label: str = "目標",
                         name: str = "target_weights") -> Report:
    rep = Report(name)
    w = {t: D(x) for t, x in target_w.items() if D(x) > 0}
    check_count(len(w), rb, rep, label)
    check_universe(w, rb, rep, label)
    check_weights(w, rb, rep, label)
    cash_w = Decimal(1) - sum(w.values(), Decimal(0))
    check_cash(cash_w, cash_w, rb, rep, label)
    return rep


def check_orders(orders: list[dict], holdings: dict[str, int], rb: RuleBook, rep: Report | None = None) -> Report:
    rep = rep or Report("orders")
    lot = rb.rules.lot_size
    bad_lot = [o for o in orders if int(o["shares"]) <= 0 or int(o["shares"]) % lot != 0]
    rep.add("R_LOT", Status.FAIL if bad_lot else Status.PASS,
            f"委託股數非千股正整數倍 {[o['ticker'] for o in bad_lot]}" if bad_lot else "委託皆為千股正整數倍",
            len(bad_lot), lot, SRC["R_LOT"])
    over = [o["ticker"] for o in orders if o["side"] == "SELL" and int(o["shares"]) > int(holdings.get(o["ticker"], 0))]
    rep.add("R_OVERSELL", Status.FAIL if over else Status.PASS,
            f"賣出超過持股 {over}" if over else "無超賣", over or 0, "holdings", SRC["R_OVERSELL"])
    check_universe([o["ticker"] for o in orders], rb, rep, "委託")
    return rep


def check_active_share(res: ActiveShareResult, rb: RuleBook, target: Decimal | None = None,
                       rep: Report | None = None) -> Report:
    rep = rep or Report("active_share")
    lim = rb.rules.active_share_min
    detail = {"mode_used": res.mode_used, "min_by_mode": res.min_by_mode, "cash_term": res.cash_term,
              "missing_benchmarks": res.missing_benchmarks, "benchmarks_synthetic": res.benchmarks_synthetic,
              "data_date": res.benchmarks_data_date}
    if res.minimum_active_share is None:
        rep.add("R_ACTIVE_SHARE", Status.UNKNOWN, "無主動 ETF 持股資料，無法計算 Active Share", None, lim,
                SRC["R_ACTIVE_SHARE"], **detail)
        return rep
    m = res.minimum_active_share
    note = "（官方 W_i 定義未確認 NC-2；取所有解讀之最小值）" if res.mode_used == "UNKNOWN" else ""
    if res.mode_used == "OFFICIAL_TOP15_NAV":     # 辦法 1005 §六(十三) + 主辦方 2026-10-07 回覆
        note = f"（官方：雙方前 15 大聯集、占 NAV 權重；benchmark 現金項 {res.cash_term or '-'}）"
    if res.benchmarks_synthetic:
        note += "（benchmark 為合成資料）"
    if m < lim:
        st, msg = Status.FAIL, f"Active Share 最小值 {float(m):.2%} < 官方門檻 {float(lim):.0%}（{res.benchmark_ticker}）{note}"
    elif target is not None and m < target:
        st, msg = Status.WARNING, f"Active Share 最小值 {float(m):.2%} 低於策略目標 {float(target):.0%}（{res.benchmark_ticker}）{note}"
    else:
        st, msg = Status.PASS, f"Active Share 最小值 {float(m):.2%}（{res.benchmark_ticker}）{note}"
    if res.missing_benchmarks and st == Status.PASS:
        st = Status.WARNING
        msg += f"；缺 {len(res.missing_benchmarks)} 檔 ETF 持股資料"
    rep.add("R_ACTIVE_SHARE", st, msg, m, lim, SRC["R_ACTIVE_SHARE"], benchmark=res.benchmark_ticker, **detail)
    return rep
