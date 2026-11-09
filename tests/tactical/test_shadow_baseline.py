"""Issue #48: the shadow baseline can never be mistaken for a submission artefact."""
from pathlib import Path

from agent.ops import shadow_baseline as SB


def test_shadow_artifacts_live_outside_submissions(tmp_path):
    out, subs = SB._paths(tmp_path, "2026-11-09")
    assert out == tmp_path / "logs" / "shadow" / "20261109"
    assert subs == tmp_path / "submissions" / "20261109" and subs not in out.parents


def test_module_imports_no_submission_or_portal_code():
    import ast
    tree = ast.parse(Path(SB.__file__).read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
            mods |= {f"{n.module}.{a.name}" for a in n.names}
        elif isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
    assert not [m for m in mods if "submission" in m or "portal" in m or "auto_upload" in m or m.endswith("final")]


def test_orders_after_applies_buys_and_sells():
    h = SB._orders_after({"A": 5000, "B": 1000}, [{"ticker": "A", "side": "SELL", "shares": 2000},
                                                 {"ticker": "B", "side": "SELL", "shares": 1000},
                                                 {"ticker": "C", "side": "BUY", "shares": 3000}])
    assert h == {"A": 3000, "C": 3000}


def test_frozen_fingerprint_constant_matches_repo():
    import hashlib
    from agent.config import ROOT
    assert hashlib.sha256((ROOT / "config" / "strategy_quant_v1.yaml").read_bytes()).hexdigest() == SB.FROZEN_FP
