"""D-Plan v4.2 validator: JSON Schema (structural) + semantic checks (C-codes known from
schema/guide). Unknown official C-codes are reported as NOT_IMPLEMENTED, never assumed.

CLI:
  python -m agent.engine.validate_dplan <file.json> [--context ctx.json]
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import date as _date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import jsonschema

from agent.config import D
from agent.engine import compliance as C
from agent.engine.active_share import compute_official_active_share
from agent.engine.fees import buy_cost, sell_cost
from agent.engine.models import Report, Status
from agent.engine.orders import derive_order
from agent.engine.rules import RuleBook, load_rulebook

SRC_SCHEMA = "D-Plan.schema_v4.3.json"     # official 2026-10-12 (research/official_updates); v4.2 kept in repo root
SRC_GUIDE = "D-Plan_撰寫指南_v4.3.md"
UNKNOWN_CODES = ["C3", "C4", "C5", "C7", "C8", "C10"]
DISPOSITION_NOTE = "（拒收/警告處置未確認 NC-3）"


@dataclass
class ValidationContext:
    """Facts the server knows but the D-Plan does not carry."""
    prev_holdings: dict[str, int]
    prev_cash: Decimal
    closes_prev: dict[str, Decimal]
    prev_nav: Decimal | None = None
    submission_time: str | None = None        # ISO +08:00 (server receipt time)
    expected_team_id: str | None = None
    filename: str | None = None
    partial_portfolio: bool = False           # official examples are excerpts (_NOTE)
    etf_holdings: dict[str, dict] | None = None
    etf_data_date: str | None = None
    etf_synthetic: bool = False
    active_share_target: Decimal | None = None
    trading_days: set[str] | None = None

    @property
    def nav(self) -> Decimal:
        if self.prev_nav is not None:
            return D(self.prev_nav)
        return sum((Decimal(int(s)) * D(self.closes_prev[t]) for t, s in self.prev_holdings.items()),
                   Decimal(0)) + D(self.prev_cash)

    @classmethod
    def from_json(cls, path: Path | str) -> "ValidationContext":
        j = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(prev_holdings={k: int(v) for k, v in j["prev_holdings"].items()},
                   prev_cash=D(j["prev_cash"]),
                   closes_prev={k: D(v) for k, v in j["closes_prev"].items()},
                   prev_nav=D(j["prev_nav"]) if j.get("prev_nav") is not None else None,
                   submission_time=j.get("submission_time"),
                   expected_team_id=j.get("expected_team_id"), filename=j.get("filename"),
                   partial_portfolio=bool(j.get("partial_portfolio", False)),
                   etf_holdings=j.get("etf_holdings"), etf_data_date=j.get("etf_data_date"),
                   etf_synthetic=bool(j.get("etf_synthetic", False)))


@dataclass
class PostTradeEstimate:
    holdings: dict[str, int]
    cash: Decimal
    nav: Decimal
    buy_value: Decimal
    sell_value: Decimal
    fees: Decimal
    weights: dict[str, Decimal] = field(default_factory=dict)

    @property
    def net_flow(self) -> Decimal:
        return self.buy_value - self.sell_value

    @property
    def cash_ratio(self) -> Decimal:
        return self.cash / self.nav if self.nav else Decimal(0)


def estimate_post_trade(orders: list[dict], ctx: ValidationContext, rb: RuleBook,
                        include_fees: bool | None = None, exclude_decisions: set[str] | None = None) -> PostTradeEstimate:
    """Post-trade holdings/cash at T-1 close (what the server can compute at receipt)."""
    if include_fees is None:
        include_fees = rb.assumptions.c12_estimate_includes_fees
    h = dict(ctx.prev_holdings)
    cash = D(ctx.prev_cash)
    bv = sv = fees = Decimal(0)
    mode = rb.assumptions.fee_rounding_mode
    for o in orders:
        if exclude_decisions and o.get("decision_ref") in exclude_decisions:
            continue
        t, n = o["ticker"], int(o["shares"])
        px = D(ctx.closes_prev[t])
        v = Decimal(n) * px
        if o["side"] == "BUY":
            bv += v
            cash -= v
            h[t] = h.get(t, 0) + n
            if include_fees:
                f = buy_cost(v, rb.rules, mode)
                fees += f
                cash -= f
        else:
            sv += v
            cash += v
            h[t] = h.get(t, 0) - n
            if include_fees:
                f, tx = sell_cost(v, rb.rules, mode)
                fees += f + tx
                cash -= f + tx
    h = {t: s for t, s in h.items() if s != 0}
    nav = ctx.nav - fees
    w = {t: Decimal(s) * D(ctx.closes_prev[t]) / nav for t, s in h.items()} if nav > 0 else {}
    return PostTradeEstimate(h, cash, nav, bv, sv, fees, w)


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _id_seq(rep: Report, items: list, key: str, prefix: str) -> None:
    ids = [x.get(key) for x in items]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        rep.add("ID_UNIQUE", Status.FAIL, f"{prefix} ID 重複 {dup}", dup, "unique", SRC_GUIDE)
    nums = []
    for i in ids:
        m = re.fullmatch(prefix + r"([1-9][0-9]{0,2})", str(i))
        if not m:
            rep.add("ID_FORMAT", Status.FAIL, f"{prefix} ID 格式錯誤或補零：{i}", i, f"{prefix}1..{prefix}999", SRC_GUIDE)
        else:
            nums.append(int(m.group(1)))
    if nums and nums != list(range(1, len(nums) + 1)):
        rep.add("ID_SEQUENCE", Status.FAIL, f"{prefix} ID 未從 1 起連續遞增：{ids}", ids, "1..n", SRC_GUIDE)
    elif nums:
        rep.add("ID_SEQUENCE", Status.PASS, f"{prefix} ID 連續 {prefix}1..{prefix}{len(nums)}", len(nums), "1..n", SRC_GUIDE)


def validate_schema(doc: dict, rb: RuleBook, rep: Report) -> None:
    schema = json.loads(Path(rb.rules.schema_path).read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    errs = sorted(v.iter_errors(doc), key=lambda e: list(e.path))
    for e in errs[:50]:
        rep.add("SCHEMA", Status.FAIL, f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message[:200]}",
                None, None, SRC_SCHEMA)
    if not errs:
        rep.add("SCHEMA", Status.PASS, f"JSON Schema {Path(rb.rules.schema_path).stem.split('_')[-1]} 驗證通過", None, None, SRC_SCHEMA)


def validate_dplan(doc: dict, ctx: ValidationContext | None, rb: RuleBook | None = None) -> Report:
    rb = rb or load_rulebook()
    rep = Report("dplan_validation")
    validate_schema(doc, rb, rep)
    if "_NOTE" in doc:
        rep.add("INFORMAL_FIELD", Status.WARNING, "_NOTE 為範例用非正式欄位，正式提交建議省略", None, None, SRC_SCHEMA)

    S = doc.get("sources", []); O = doc.get("observations", []); I = doc.get("inferences", [])
    Dd = doc.get("decisions", []); NT = doc.get("no_trade_decisions", []); ORD = doc.get("orders", [])
    mv = doc.get("market_view", {}) or {}
    sid = {x.get("source_id") for x in S}; oid = {x.get("obs_id") for x in O}
    iid = {x.get("inf_id") for x in I}; did = {x.get("decision_id"): x for x in Dd}

    # ---- C1 reference integrity
    broken = []
    for o in O:
        broken += [f"{o.get('obs_id')}.source_ref→{r}" for r in o.get("source_ref", []) if r not in sid]
    broken += [f"market_view.basis_refs→{r}" for r in mv.get("basis_refs", []) if r not in oid]
    for i in I:
        broken += [f"{i.get('inf_id')}.premise_refs→{r}" for r in i.get("premise_refs", []) if r not in oid]
    for d in Dd:
        broken += [f"{d.get('decision_id')}.inference_refs→{r}" for r in d.get("inference_refs", []) if r not in iid]
        broken += [f"{d.get('decision_id')}.funding_for→{r}" for r in d.get("funding_for", []) or [] if r not in did]
    for n in NT:
        broken += [f"no_trade[{n.get('ticker')}].reason_refs→{r}" for r in n.get("reason_refs", []) if r not in iid]
    for o in ORD:
        if o.get("decision_ref") not in did:
            broken.append(f"order[{o.get('ticker')}].decision_ref→{o.get('decision_ref')}")
    if broken:
        rep.add("C1", Status.FAIL, f"引用斷裂/孤兒 {broken}（schema：孤兒決策→拒收）", broken, "all refs exist", SRC_SCHEMA)
    else:
        rep.add("C1", Status.PASS, "所有引用 ID 皆存在", 0, 0, SRC_SCHEMA)

    used_s = {r for o in O for r in o.get("source_ref", [])}
    used_o = set(mv.get("basis_refs", [])) | {r for i in I for r in i.get("premise_refs", [])}
    used_i = {r for d in Dd for r in d.get("inference_refs", [])} | {r for n in NT for r in n.get("reason_refs", [])}
    unused = sorted(sid - used_s) + sorted(oid - used_o) + sorted(iid - used_i)
    rep.add("UNUSED_NODES", Status.WARNING if unused else Status.PASS,
            f"未被引用的節點 {unused}" if unused else "無未被引用節點", unused or 0, 0, SRC_GUIDE + "「不能有斷環」")

    # ---- ID rules
    _id_seq(rep, S, "source_id", "S"); _id_seq(rep, O, "obs_id", "O")
    _id_seq(rep, I, "inf_id", "I"); _id_seq(rep, Dd, "decision_id", "D")

    # ---- header checks
    td = doc.get("trade_date")
    if ctx and ctx.expected_team_id:
        st = Status.PASS if doc.get("team_id") == ctx.expected_team_id else Status.FAIL
        rep.add("TEAM_ID", st, f"team_id={doc.get('team_id')} 期望 {ctx.expected_team_id}", doc.get("team_id"),
                ctx.expected_team_id, SRC_SCHEMA)
    if ctx and ctx.filename:
        exp = f"D-Plan_{doc.get('team_id')}_{td}.json"
        st = Status.PASS if Path(ctx.filename).name == exp else Status.FAIL
        rep.add("FILENAME", st, f"檔名 {Path(ctx.filename).name}，期望 {exp}", Path(ctx.filename).name, exp, SRC_GUIDE)
    try:
        tdd = _date.fromisoformat(td)
        if tdd.weekday() >= 5:
            rep.add("TRADE_DATE", Status.FAIL, f"trade_date {td} 為週末", td, "weekday", SRC_GUIDE)
        elif ctx and ctx.trading_days is not None and td not in ctx.trading_days:
            rep.add("TRADE_DATE", Status.FAIL, f"trade_date {td} 不在交易日曆", td, "calendar", SRC_GUIDE)
        else:
            rep.add("TRADE_DATE", Status.PASS, f"trade_date {td}", td, None, SRC_GUIDE)
    except (TypeError, ValueError):
        rep.add("TRADE_DATE", Status.FAIL, f"trade_date 無效 {td}", td, None, SRC_GUIDE)
        tdd = None

    # ---- universe
    tick = [d.get("ticker") for d in Dd] + [o.get("ticker") for o in ORD] + [n.get("ticker") for n in NT]
    C.check_universe([t for t in tick if t], rb, rep, "D-Plan ")

    # ---- C6 time
    md = doc.get("agent_metadata", {}) or {}
    _check_time(doc, md, ctx, tdd, rb, rep)

    if ctx is None:
        for code in ("C2", "C9", "C11", "C12", "C13", "C14", "COVERAGE", "R_ACTIVE_SHARE"):
            rep.add(code, Status.UNKNOWN, "缺少前日結算 context，無法檢查", None, None, SRC_SCHEMA)
        _unknown_codes(rep)
        return rep

    # ---- coverage / action consistency
    prev = {t: s for t, s in ctx.prev_holdings.items() if int(s) != 0}
    dec_t = [d.get("ticker") for d in Dd]; nt_t = [n.get("ticker") for n in NT]
    dups = sorted({t for t in dec_t + nt_t if (dec_t + nt_t).count(t) > 1})
    missing = sorted(set(prev) - set(dec_t) - set(nt_t))
    nt_not_held = sorted(set(nt_t) - set(prev))
    cov_bad = []
    if dups: cov_bad.append(f"重複 {dups}")
    if missing: cov_bad.append(f"前日持股未交代 {missing}")
    if nt_not_held: cov_bad.append(f"no_trade 非前日持股 {nt_not_held}")
    rep.add("COVERAGE", Status.FAIL if cov_bad else Status.PASS,
            "；".join(cov_bad) if cov_bad else f"前日 {len(prev)} 檔持股皆恰出現一次", cov_bad or len(prev),
            "each prev holding exactly once", SRC_GUIDE + " ⑤")
    act_bad = []
    for d in Dd:
        t, a, held = d.get("ticker"), d.get("action"), prev.get(d.get("ticker"), 0)
        if a == "BUY" and held:
            act_bad.append(f"{d.get('decision_id')} BUY 但已持有 {t}")
        if a in ("ADD", "TRIM", "SELL_ALL") and not held:
            act_bad.append(f"{d.get('decision_id')} {a} 但未持有 {t}")
        if a == "SELL_ALL" and D(d.get("target_weight", 0)) != 0:
            act_bad.append(f"{d.get('decision_id')} SELL_ALL target_weight≠0")
    rep.add("ACTION", Status.FAIL if act_bad else Status.PASS,
            "；".join(act_bad) if act_bad else "action 與前日持股一致", act_bad or 0, None, SRC_GUIDE + " ⑤")

    # ---- C2 derive-orders.v2
    nav = ctx.nav
    lot = rb.rules.lot_size
    expected = {}
    c2_err = []
    for d in Dd:
        t = d.get("ticker")
        if t not in ctx.closes_prev:
            c2_err.append(f"{t} 缺前日收盤價")
            continue
        o = derive_order(d, prev.get(t, 0), nav, ctx.closes_prev[t], lot)
        if o:
            expected[(o.ticker, o.decision_ref)] = (o.side, o.shares)
        else:
            rep.add("C2_NOOP", Status.WARNING, f"{d.get('decision_id')} {t} 推導股數不變（無委託）；建議改列 no_trade",
                    0, None, SRC_SCHEMA)
    actual = {(o.get("ticker"), o.get("decision_ref")): (o.get("side"), int(o.get("shares", 0))) for o in ORD}
    for k, v in expected.items():
        if actual.get(k) != v:
            c2_err.append(f"{k[0]}({k[1]}) 期望 {v[0]} {v[1]:,}，實際 {actual.get(k)}")
    for k in set(actual) - set(expected):
        c2_err.append(f"{k[0]}({k[1]}) 多出委託 {actual[k]}")
    if c2_err:
        rep.add("C2", Status.FAIL, f"orders ≠ derive-orders.v2：{c2_err}{DISPOSITION_NOTE}", c2_err, "bitwise equal", SRC_SCHEMA)
    else:
        rep.add("C2", Status.PASS, f"{len(ORD)} 筆委託與 derive-orders.v2 完全一致", len(ORD), None, SRC_SCHEMA)

    # ---- C13 oversell
    C.check_orders(ORD, prev, rb, rep)
    for c in rep.by_rule("R_OVERSELL"):
        c.rule_id = "C13"

    # ---- C9 / C11 post-trade estimate at T-1 close
    est = estimate_post_trade(ORD, ctx, rb)
    port = Report("post_trade_estimate")
    if ctx.partial_portfolio:
        port.add("R_COUNT", Status.NOT_APPLICABLE, "範例為節錄持股（partial_portfolio），不檢查檔數", len(est.holdings),
                 [rb.rules.holdings_min, rb.rules.holdings_max], C.SRC["R_COUNT"])
    else:
        C.check_count(len(est.holdings), rb, port, "委託後(預估)")
    C.check_weights(est.weights, rb, port, "委託後(預估)")
    C.check_cash(est.cash_ratio, est.cash, rb, port, "委託後(預估)")
    for c in port.checks:
        c.rule_id = ("C11:" if c.rule_id == "R_COUNT" else "C9:") + c.rule_id
        c.detail["basis"] = "T-1 收盤價估算；實際以 T 日均價結算"
    rep.extend(port)

    # ---- C12 posture
    post = mv.get("posture", {}) or {}
    intent = post.get("net_exposure_intent")
    rng = post.get("target_cash_pct_range") or [None, None]
    tol = rb.rules.c12_hold_tolerance_nav * nav
    nf = est.net_flow
    ok_dir = {"increase": nf > 0, "reduce": nf < 0, "hold": abs(nf) <= tol}.get(intent)
    rep.add("C12_FLOW", Status.PASS if ok_dir else Status.FAIL,
            f"net_exposure_intent={intent}，委託淨流向 {nf:+,.0f}（{float(nf / nav):+.3%} NAV；hold 容差 ±2%）"
            + ("" if ok_dir else DISPOSITION_NOTE), nf, intent, SRC_SCHEMA)
    lo, hi = (D(rng[0]), D(rng[1])) if None not in rng else (None, None)
    if lo is None or lo > hi:
        rep.add("C12_RANGE", Status.FAIL, f"target_cash_pct_range 無效 {rng}", rng, "lo<=hi", SRC_SCHEMA)
    else:
        inside = lo <= est.cash_ratio <= hi
        rep.add("C12_CASH", Status.PASS if inside else Status.FAIL,
                f"預估委託後現金比 {float(est.cash_ratio):.3%}，宣告區間 [{float(lo):.1%}, {float(hi):.1%}]"
                + ("" if inside else DISPOSITION_NOTE), est.cash_ratio, rng, SRC_SCHEMA,
                includes_fees=rb.assumptions.c12_estimate_includes_fees)

    # ---- C14 funding_for
    _check_funding(Dd, ORD, ctx, rb, lo, rep)

    # ---- Active Share (post-trade estimate)
    if ctx.etf_holdings:
        asc = (rb.rules.raw.get("official_rules") or {}).get("active_share") or {}
        res = compute_official_active_share(est.weights, ctx.etf_holdings, rb.active_etfs,
                                            int(asc.get("top_n", 15)), est.cash_ratio, None,
                                            bool(asc.get("include_cash", True)), ctx.etf_data_date, ctx.etf_synthetic)
        C.check_active_share(res, rb, ctx.active_share_target, rep)     # official gate + internal target (WARN)
    else:
        rep.add("R_ACTIVE_SHARE", Status.UNKNOWN, "未提供主動 ETF 持股，無法計算", None, rb.rules.active_share_min,
                C.SRC["R_ACTIVE_SHARE"])

    _unknown_codes(rep)
    return rep


def _check_time(doc, md, ctx, tdd, rb: RuleBook, rep: Report) -> None:
    try:
        rs, rc = _iso(md["run_started_at"]), _iso(md["run_completed_at"])
    except Exception:  # noqa: BLE001
        rep.add("C6", Status.FAIL, "agent_metadata 時間缺漏或格式錯誤", None, None, SRC_SCHEMA)
        return
    if rs > rc:
        rep.add("C6_ORDER", Status.FAIL, "run_started_at 晚於 run_completed_at", md["run_started_at"], md["run_completed_at"], SRC_SCHEMA)
    times = [("run_completed_at", rc)]
    for s in doc.get("sources", []):
        if s.get("fetched_at"):
            times.append((f"{s.get('source_id')}.fetched_at", _iso(s["fetched_at"])))
    # stricter own rule: no content describing the future relative to completion
    future = [f"{s.get('source_id')}.{k}" for s in doc.get("sources", []) for k in ("content_as_of", "published_at")
              if s.get(k) and _iso(s[k]) > rc]
    rep.add("PIT_CONTENT", Status.FAIL if future else Status.PASS,
            f"來源時點晚於 run_completed_at：{future}" if future else "所有來源時點 ≤ run_completed_at",
            future or 0, "<= run_completed_at", "本隊 PIT 規則（非官方）")
    if tdd is not None:
        close_h, close_m = map(int, rb.rules.submission_close.split(":"))
        open_h, open_m = map(int, rb.rules.submission_open.split(":"))
        tz = rc.tzinfo
        cutoff = datetime(tdd.year, tdd.month, tdd.day, close_h, close_m, tzinfo=tz)
        prevd = tdd - timedelta(days=1)
        opening = datetime(prevd.year, prevd.month, prevd.day, open_h, open_m, tzinfo=tz)
        late = [k for k, t in times if t > cutoff]
        rep.add("C6_CUTOFF", Status.FAIL if late else Status.PASS,
                f"晚於 {cutoff.isoformat()}：{late}" if late else f"時間戳皆 ≤ {cutoff.isoformat()}",
                late or 0, cutoff.isoformat(), "比賽辦法 §六(三)；schema C6")
        if ctx and ctx.submission_time:
            sub = _iso(ctx.submission_time)
            late2 = [k for k, t in times if t > sub]
            in_win = opening <= sub <= cutoff
            st = Status.PASS if (not late2 and in_win) else Status.FAIL
            rep.add("C6", st, f"提交時間 {sub.isoformat()}（窗口 {opening.isoformat()}～{cutoff.isoformat()}）"
                    + (f"；晚於提交 {late2}" if late2 else ""), sub.isoformat(), [opening.isoformat(), cutoff.isoformat()],
                    SRC_SCHEMA)
        else:
            rep.add("C6", Status.UNKNOWN, "未提供 server 收件時間；僅以截止時間檢查", None, cutoff.isoformat(), SRC_SCHEMA)


def _check_funding(Dd, ORD, ctx, rb, lo, rep: Report) -> None:
    flagged = [d for d in Dd if d.get("funding_for")]
    if not flagged:
        rep.add("C14", Status.NOT_APPLICABLE, "無 funding_for 宣告", 0, None, SRC_SCHEMA)
        return
    did = {d.get("decision_id"): d for d in Dd}
    errs = []
    for d in flagged:
        if d.get("action") not in ("TRIM", "SELL_ALL"):
            errs.append(f"{d.get('decision_id')} action={d.get('action')} 不可宣告 funding_for")
        for r in d.get("funding_for", []):
            tgt = did.get(r)
            if not tgt or tgt.get("action") not in ("BUY", "ADD"):
                errs.append(f"{d.get('decision_id')}.funding_for→{r} 非同日 BUY/ADD")
    if lo is not None:
        ex = {d.get("decision_id") for d in flagged}
        est2 = estimate_post_trade(ORD, ctx, rb, exclude_decisions=ex)
        if not est2.cash_ratio < lo:
            errs.append(f"拿掉調度賣出後現金比 {float(est2.cash_ratio):.3%} 未低於宣告下限 {float(lo):.1%}（缺口不存在）")
        gap = est2.cash_ratio
    else:
        gap = None
    rep.add("C14", Status.FAIL if errs else Status.PASS,
            "；".join(errs) + DISPOSITION_NOTE if errs else f"funding_for 有效（拿掉調度賣出後現金比 {float(gap):.3%} < 下限）",
            gap, lo, SRC_SCHEMA)


def _unknown_codes(rep: Report) -> None:
    for code in UNKNOWN_CODES:
        rep.add(code, Status.NOT_IMPLEMENTED, f"官方 {code} 定義未公開（verify_dplan.py 未釋出），未實作", None, None, SRC_SCHEMA)


def main(argv=None):
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--context", help="JSON with prev_holdings, prev_cash, closes_prev, ...")
    args = ap.parse_args(argv)
    doc = json.loads(Path(args.file).read_text(encoding="utf-8"))
    ctx = ValidationContext.from_json(args.context) if args.context else None
    if ctx and not ctx.filename:
        ctx.filename = args.file
    rep = validate_dplan(doc, ctx)
    for c in rep.checks:
        print(f"[{c.status.value:15s}] {c.rule_id:22s} {c.message}")
    print("SUMMARY", rep.summary(), "OK" if rep.ok else "NOT OK")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
