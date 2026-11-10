"""Issue #63: one-day technology overweight overlay - date scoping, pure weight logic, activation wiring."""
from decimal import Decimal

import yaml

from agent.config import D, ROOT
from agent.tactical import override as TO
from agent.tactical import tech_overweight as TW


def test_issue63_history_segment_and_issue65_persistence():
    cfg = TW.load_config()
    assert cfg is not None
    assert TW.resolve("2026-11-11")["target_tech_weight_min"] == 0.75      # Issue #63 history segment (one day)
    assert TW.resolve("2026-11-10") is None
    assert TW.resolve("2026-11-12")["target_tech_weight_min"] == 0.85      # Issue #65: persistent floor, replaces the one-day rule
    assert TO.is_active("2026-11-11", "competition") is True
    assert TO.is_active("2026-11-12", "competition") is True
    assert TO.is_active("2026-11-11", "precompetition") is False           # operational (competition) mode only

def test_frozen_quant_untouched():
    import hashlib
    assert hashlib.sha256((ROOT / "config/strategy_quant_v1.yaml").read_bytes()).hexdigest() == \
        "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"
    assert len(TW.tech_tickers(TW.load_config())) > 50


def _fixture():
    tech = {"T1", "T2", "T3"}
    tw = {"T1": D("0.20"), "T2": D("0.10"), "N1": D("0.20"), "N2": D("0.20"), "N3": D("0.15")}     # cash 15 %, tech 30 %
    rank = {"T1": 1, "T2": 5, "N1": 2, "N2": 9, "N3": 20, "T3": 3}
    elig = {t: True for t in rank}
    return tech, tw, rank, elig


def test_funding_from_lowest_ranked_non_tech_first_and_cash_unchanged():
    tech, tw, rank, elig = _fixture()
    w, nt, info = TW.overlay_weights(tw, {"N1"}, rank, elig, tech, D("0.50"), D("0.30"))
    assert info["funded_from"][0] == "N3"                     # worst rank first
    assert sum(w[t] for t in w if t in tech) >= D("0.4999")
    assert abs((1 - sum(w.values())) - D("0.15")) < D("0.0001")      # cash unchanged
    assert "N1" in nt                                         # untouched name keeps its no-trade status


def test_no_ceiling_other_than_name_cap_and_new_names_come_from_quant_ranking():
    tech, tw, rank, elig = _fixture()
    w, _, info = TW.overlay_weights(tw, set(), rank, elig, tech, D("0.60"), D("0.20"))
    assert max(w[t] for t in tech if t in w) <= D("0.20")
    assert set(info["added"]) <= {"T3"}                       # only an eligible, ranked technology name can be added
    assert "T3" in w and w["T3"] > 0


def test_ineligible_or_unranked_tech_name_is_never_added():
    tech, tw, rank, elig = _fixture()
    elig["T3"] = False
    w, _, info = TW.overlay_weights(tw, set(), rank, elig, tech, D("0.60"), D("0.20"))
    assert "T3" not in w and info["added"] == []


def test_noop_when_target_already_met():
    tech, tw, rank, elig = _fixture()
    w, nt, info = TW.overlay_weights(tw, {"N1"}, rank, elig, tech, D("0.25"), D("0.30"))
    assert w == tw and nt == {"N1"} and info["funded_from"] == []


def test_activate_is_inert_before_the_first_segment(tmp_path):
    import agent.pipeline as P
    before = P.construct
    with TO.activate("2026-11-12", "dry-run", state_dir=tmp_path) as act:      # non-operational mode: never patched
        assert P.construct is before and act.calls == 0
    with TO.activate("2026-11-11", "competition", state_dir=tmp_path):
        assert P.construct is not before
    assert P.construct is before

def test_disabled_config_is_inactive(tmp_path):
    src = yaml.safe_load((ROOT / "config/tactical_tech_overweight_v1.yaml").read_text(encoding="utf-8"))
    src["enabled"] = False
    p = tmp_path / "off.yaml"
    p.write_text(yaml.safe_dump(src), encoding="utf-8")
    assert TW.resolve("2026-11-11", p) is None
