"""Daily settlement = our replica of the organiser's settlement (辦法 §五, §六(四)(五)(十一)(十二)(十四)).

  * all orders fill (全數成交) at T-day VWAP = 成交金額 / 成交股數
  * buy fee 0.1425%, sell fee 0.1425% + tax 0.3% (rounding: assumption, NC-5)
  * NAV = Σ shares × close_T + cash   (accrued dividends kept aside until final NAV, 註1)
  * violation -> 1 warning/day, the day's trades are void, NAV from previous portfolio
  * weight breach caused by price drift: 5 trading days grace, warning on day 6 (註3)
  * 3 warnings -> DQ; Active Share < 20% on 2 consecutive days -> DQ (§六(十三))
Unconfirmed behaviours are driven by `Assumptions` and recorded in the output.
"""
from __future__ import annotations

from decimal import Decimal

from agent.config import Assumptions, D
from agent.engine.fees import buy_cost, sell_cost
from agent.engine.rules import RuleBook
from agent.sim.metrics import mdd_both
from agent.sim.models import DayMarket, Settlement


def _apply_corporate_actions(holdings: dict[str, int], mkt: DayMarket, a: Assumptions) -> tuple[dict, Decimal, list]:
    h = dict(holdings)
    accrued = Decimal(0)
    events = []
    for t, s in holdings.items():
        div = mkt.cash_dividend.get(t)
        if div:
            amt = Decimal(s) * D(div)
            accrued += amt
            events.append({"type": "cash_dividend_accrued", "ticker": t, "shares": s, "per_share": str(div), "amount": str(amt)})
        sd = mkt.stock_dividend_per_share.get(t)
        if sd:
            add = Decimal(s) * D(sd)
            add_i = int(add) if a.stock_dividend_odd_shares == "keep_exact" else int(add) // 1000 * 1000
            h[t] = s + add_i
            events.append({"type": "stock_dividend", "ticker": t, "added_shares": add_i})
    return h, accrued, events


def _nav(holdings: dict[str, int], closes: dict[str, Decimal], cash: Decimal) -> Decimal:
    return sum((Decimal(s) * D(closes[t]) for t, s in holdings.items()), Decimal(0)) + cash


def _violations(holdings, closes, cash, nav, rb: RuleBook, bought: set[str], drift_prev: dict[str, int]):
    r = rb.rules
    v = []
    drift = {}
    if cash < r.cash_min:
        v.append({"rule": "R_CASH_NEG", "msg": f"結算現金為負 {cash}"})
    cw = cash / nav if nav > 0 else Decimal(0)
    if cw > r.cash_max_weight or (cw == r.cash_max_weight and not rb.assumptions.cash_equal_25_allowed):
        v.append({"rule": "R_CASH_MAX", "msg": f"結算現金比 {float(cw):.4%} ≥ 25%"})
    n = len([t for t, s in holdings.items() if s > 0])
    if not (r.holdings_min <= n <= r.holdings_max):
        v.append({"rule": "R_COUNT", "msg": f"持股 {n} 檔不在 20–30"})
    bad = sorted(set(t for t, s in holdings.items() if s > 0) - rb.universe_set)
    if bad:
        v.append({"rule": "R_UNIVERSE", "msg": f"持有非 150 檔 {bad}"})
    for t, s in holdings.items():
        if s <= 0 or nav <= 0:
            continue
        w = Decimal(s) * D(closes[t]) / nav
        if w > r.max_weight(t):
            if t in bought:
                v.append({"rule": "R_WEIGHT_ADD", "msg": f"{t} 加碼後權重 {float(w):.4%} 超限"})
            else:
                drift[t] = drift_prev.get(t, 0) + 1
                if drift[t] > r.price_drift_grace_trading_days:
                    v.append({"rule": "R_WEIGHT_DRIFT", "msg": f"{t} 價格漂移超限已 {drift[t]} 日（寬限 5 日）"})
    return v, drift


def settle(prev: Settlement, orders: list[dict] | None, mkt: DayMarket, rb: RuleBook,
           assumptions: Assumptions | None = None, active_share_min: Decimal | None = None,
           buy_price_mult: Decimal | None = None, sell_price_mult: Decimal | None = None) -> Settlement:
    """buy/sell_price_mult: RESEARCH-ONLY slippage stress (e.g. 1.002 / 0.998). Official = None (pure VWAP)."""
    a = assumptions or rb.assumptions
    r = rb.rules
    mode = a.fee_rounding_mode
    closes = dict(prev.closes)
    closes.update({t: D(p) for t, p in mkt.close.items() if p is not None})

    base_h, accrued_today, ca_events = _apply_corporate_actions(prev.holdings, mkt, a)
    warnings: list[dict] = []
    executions: list[dict] = []
    submitted = orders is not None
    void = False
    fees = tax = traded = Decimal(0)
    new_h = dict(base_h)
    cash = prev.cash
    bought: set[str] = set()

    if not submitted:
        warnings.append({"rule": "NO_SUBMISSION", "msg": "當日未繳交 D-Plan（辦法 §六(十四)(1)）"})
        void = True
    else:
        over = [o["ticker"] for o in orders if o["side"] == "SELL" and int(o["shares"]) > base_h.get(o["ticker"], 0)]
        odd = [o["ticker"] for o in orders if int(o["shares"]) <= 0 or int(o["shares"]) % r.lot_size]
        if over or odd:
            warnings.append({"rule": "REJECTED", "msg": f"D-Plan 拒收（超賣 {over} / 非整張 {odd}）；"
                             "拒收是否等同未繳交未確認 NC-3，模擬視為未繳交"})
            void = True
        else:
            no_px = [o["ticker"] for o in orders if mkt.vwap(o["ticker"]) is None]
            if no_px and a.no_trade_execution_mode == "reject":
                warnings.append({"rule": "NO_TRADE_PRICE", "msg": f"{no_px} 當日無成交價，依假設 reject 當日全部交易"})
                void = True
                submitted = True
            else:
                for o in sorted(orders, key=lambda x: 0 if x["side"] == "SELL" else 1):
                    t, n = o["ticker"], int(o["shares"])
                    px = mkt.vwap(t)
                    if px is None:
                        executions.append({"ticker": t, "side": o["side"], "shares": n, "status": "SKIPPED_NO_TRADE"})
                        continue
                    if o["side"] == "BUY" and buy_price_mult is not None:
                        px = px * D(buy_price_mult)
                    if o["side"] == "SELL" and sell_price_mult is not None:
                        px = px * D(sell_price_mult)
                    val = Decimal(n) * px
                    traded += val
                    if o["side"] == "BUY":
                        f = buy_cost(val, r, mode)
                        cash -= val + f
                        fees += f
                        new_h[t] = new_h.get(t, 0) + n
                        bought.add(t)
                        executions.append({"ticker": t, "side": "BUY", "shares": n, "vwap": str(px),
                                           "value": str(val), "fee": str(f), "tax": "0", "status": "FILLED"})
                    else:
                        f, tx = sell_cost(val, r, mode)
                        cash += val - f - tx
                        fees += f
                        tax += tx
                        new_h[t] = new_h.get(t, 0) - n
                        executions.append({"ticker": t, "side": "SELL", "shares": n, "vwap": str(px),
                                           "value": str(val), "fee": str(f), "tax": str(tx), "status": "FILLED"})
                new_h = {t: s for t, s in new_h.items() if s != 0}

    if not void:
        nav = _nav(new_h, closes, cash)
        viol, drift = _violations(new_h, closes, cash, nav, rb, bought, prev.drift_tracker)
        if viol:
            warnings.extend(viol)
            void = True
    if void:
        # trades void -> previous portfolio (after corporate actions) valued at today's close
        executions = [dict(e, status="VOID") if e.get("status") == "FILLED" else e for e in executions]
        new_h, cash, fees, tax, traded = base_h, prev.cash, Decimal(0), Decimal(0), Decimal(0)
        nav = _nav(new_h, closes, cash)
        _, drift = _violations(new_h, closes, cash, nav, rb, set(), prev.drift_tracker)

    warning_count = prev.warning_count + (1 if warnings else 0)
    dq_reasons = list(prev.dq_reasons)
    if warning_count >= r.warnings_to_dq and "WARNINGS_3" not in dq_reasons:
        dq_reasons.append("WARNINGS_3")
    as_days = prev.active_share_breach_days
    if active_share_min is not None:
        as_days = as_days + 1 if D(active_share_min) < r.active_share_min else 0
        if as_days >= r.active_share_consecutive_days_dq and "ACTIVE_SHARE_2D" not in dq_reasons:
            dq_reasons.append("ACTIVE_SHARE_2D")

    hist = list(prev.nav_history) + [[mkt.date, str(nav)]]
    turnover = traded / prev.nav if prev.nav > 0 else Decimal(0)
    return Settlement(
        date=mkt.date, holdings=new_h, cash=cash, nav=nav,
        accrued_dividends=prev.accrued_dividends + accrued_today,
        fees=fees, tax=tax, cum_fees=prev.cum_fees + fees, cum_tax=prev.cum_tax + tax,
        orders=list(orders or []), executions=executions + ca_events, warnings=warnings,
        warning_count=warning_count, dq=bool(dq_reasons), dq_reasons=dq_reasons,
        nav_history=hist, mdd={k: str(v) for k, v in mdd_both([D(x[1]) for x in hist], prev.initial_nav if prev.initial_nav is not None else r.initial_cash).items()},
        turnover=turnover, cum_turnover=prev.cum_turnover + turnover, drift_tracker=drift,
        active_share_breach_days=as_days, trades_void=void, submitted=submitted,
        closes={t: closes[t] for t in new_h},
        assumptions={"fee_rounding_mode": mode, "no_trade_execution_mode": a.no_trade_execution_mode,
                     "cash_equal_25_allowed": a.cash_equal_25_allowed,
                     "stock_dividend_odd_shares": a.stock_dividend_odd_shares,
                     "rejected_dplan_counts_as_missing": True},
        initial_nav=prev.initial_nav,
        agent_state=dict(prev.agent_state or {}),
    )
