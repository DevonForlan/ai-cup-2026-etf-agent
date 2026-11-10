"""Issue #65: persistent 85% technology floor from 2026-11-12 (no auto-expiry); 2026-11-11 keeps its own 75% history segment."""
import hashlib

import yaml

from agent.config import ROOT
from agent.tactical import override as TO
from agent.tactical import tech_overweight as TW


def test_floor_schedule_persistent_from_1112_and_history_kept():
    cfg = TW.load_config()
    assert cfg["owner_tech_floor"] == 0.85
    assert TW.floor_for(cfg, "2026-11-10") is None                    # before the first segment: inactive
    assert TW.floor_for(cfg, "2026-11-11") == 0.75                    # Issue #63 history segment (already submitted)
    for d in ("2026-11-12", "2026-11-13", "2026-11-27", "2027-01-04"):
        assert TW.floor_for(cfg, d) == 0.85                           # persistent: never expires on its own
        assert TW.resolve(d)["target_tech_weight_min"] == 0.85
        assert TO.is_active(d, "competition") is True
    assert TO.is_active("2026-11-10", "competition") is False
    assert TO.is_active("2026-11-12", "dry-run") is False             # competition mode only


def test_owner_can_end_or_change_the_floor(tmp_path):
    cfg = yaml.safe_load((ROOT / "config/tactical_tech_overweight_v1.yaml").read_text(encoding="utf-8"))
    cfg["floor_schedule"][1]["to"] = "2026-11-20"                     # explicit Owner end date
    p = tmp_path / "ended.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert TW.resolve("2026-11-20", p)["target_tech_weight_min"] == 0.85
    assert TW.resolve("2026-11-21", p) is None
    cfg["enabled"] = False
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert TW.resolve("2026-11-12", p) is None


def test_activate_patches_on_floor_dates_only(tmp_path):
    import agent.pipeline as P
    before = P.construct
    for d in ("2026-11-12", "2026-11-30"):
        with TO.activate(d, "competition", state_dir=tmp_path):
            assert P.construct is not before
        assert P.construct is before
    with TO.activate("2026-11-12", "dry-run", state_dir=tmp_path):
        assert P.construct is before


def test_frozen_quant_untouched_and_no_hand_picked_tickers():
    assert hashlib.sha256((ROOT / "config/strategy_quant_v1.yaml").read_bytes()).hexdigest() == \
        "f34fa02e924011b20c52a4bd42e961169f97e1950e76e04b7e78dc43ac23d2e0"
    cfg = yaml.safe_load((ROOT / "config/tactical_tech_overweight_v1.yaml").read_text(encoding="utf-8"))
    assert not any(k in cfg for k in ("sleeve", "tickers", "add_tickers", "buy_tickers"))
