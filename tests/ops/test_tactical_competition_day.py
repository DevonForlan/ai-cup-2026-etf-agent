"""Issue #43: TACTICAL_OVERRIDE_V1 through the real competition_day flow (fixture store, mode=competition): the rotated D-Plan is
generated, validated, archived and carries the tactical version/fingerprint; with the override disabled the same day is Quant-only."""
import json
from pathlib import Path

import pytest
import yaml

from agent.tactical import override as O
from tests.ops.test_competition_day import CLK1, CLK2, T1, T2, day1_settled, official_from, run, save_official


def _cfg_from(st, tmp_path, enabled=True):
    held = {t: int(s) for t, s in st.holdings.items() if int(s) > 0}
    order = sorted(held, key=lambda t: -held[t])
    tech = order[: max(len(order) * 2 // 3, 4)]
    p = tmp_path / "tact.yaml"
    p.write_text(yaml.safe_dump({"version": "TACTICAL_OVERRIDE_V1", "enabled": enabled, "entry_trade_date": T2, "exit_trade_date": "2026-10-28",
                                 "hold_trading_days": 1, "rotation_nav_pct_ladder": [0.20, 0.10, 0.05], "sleeve": {}, "sleeve_industry": {},
                                 "reduce_tickers": tech, "baseline_holdings": held}), encoding="utf-8")
    return p, tech, held


def test_rotated_day_through_the_real_flow(fixture_store, ops_cfg, rb, monkeypatch, tmp_path):
    s1, st = day1_settled(fixture_store, ops_cfg, rb)
    save_official(official_from(st), ops_cfg)
    p, tech, held = _cfg_from(st, tmp_path)
    # sleeve: eligible names that are not held (the fixture universe has plenty)
    free = [t for t in sorted(rb.universe) if t not in held][:4]
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["sleeve"] = {t: 0.25 for t in free}
    doc["sleeve_industry"] = {t: "x" for t in free}
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    monkeypatch.setattr(O, "CONFIG_PATH", p)
    monkeypatch.setattr(O, "STATE_DIR", tmp_path / "state", raising=False)
    s2 = run(fixture_store, ops_cfg, T2, CLK2)
    assert s2["status"] == "READY_TO_SUBMIT", s2.get("reason")
    t = s2["tactical_override"]
    assert t["status"] == "APPLIED" and t["version"] == "TACTICAL_OVERRIDE_V1" and len(t["fingerprint"]) == 64
    assert s2["validation"] == "PASS" and t["tech_weight_after"] < t["tech_weight_before"]
    fin = json.loads(Path(s2["final_file"]).read_text(encoding="utf-8"))
    sides = {(o["ticker"], o["side"]) for o in fin["orders"]}
    assert any(side == "BUY" and tk in free for tk, side in sides) and any(side == "SELL" and tk in tech for tk, side in sides)
    meta = json.loads(Path(s2["package"], "run_metadata.json").read_text(encoding="utf-8"))
    assert meta["tactical_override"]["status"] == "APPLIED" and meta["tactical_override"]["fingerprint"] == t["fingerprint"]


def test_disabled_override_leaves_the_day_quant_only(fixture_store, ops_cfg, rb, monkeypatch, tmp_path):
    s1, st = day1_settled(fixture_store, ops_cfg, rb)
    save_official(official_from(st), ops_cfg)
    p, _, _ = _cfg_from(st, tmp_path, enabled=False)
    monkeypatch.setattr(O, "CONFIG_PATH", p)
    s2 = run(fixture_store, ops_cfg, T2, CLK2)
    assert s2["status"] == "READY_TO_SUBMIT" and "tactical_override" not in s2
