import copy
from pathlib import Path

import pytest

from agent.ops.common import load_ops_config

CLEAN_GIT = {"sha": "test000", "branch": "master", "dirty_paths": []}
DIRTY_GIT = {"sha": "test000", "branch": "master", "dirty_paths": ["agent/pipeline.py"]}


@pytest.fixture
def ops_cfg(tmp_path):
    """config/ops.yaml with every output path redirected into a (short) tmp dir."""
    c = copy.deepcopy(load_ops_config())
    for i, k in enumerate(c["paths"]):
        c["paths"][k] = str(tmp_path / f"{k[:3]}{i}")
    c["paths"]["first_seen_ledger"] = str(tmp_path / "obs" / "fs.parquet")
    # synthetic fixture world: 2026-10-26 is its first trading day and it has no market holidays (TESTS ONLY;
    # the real config/ops.yaml never contains this key — asserted in tests/ops/test_datapack_integration.py)
    c["datapack_calendar_override"] = {"first_trade_date": "2026-10-26", "hol": set()}
    # the synthetic fixture market TRADES on 2026-10-23 (its prices exist); the real 2026-10-23 typhoon closure
    # (config/ops.yaml, Issue #11) belongs to the real calendar only, so the fixture world keeps 10-23 as a trading day
    c["market_holidays"] = [d for d in c.get("market_holidays") or [] if str(d) != "2026-10-23"]
    return c


def write_official_datapack(off: dict, ops_cfg, team_id: str = "TEAM_TEST") -> Path:
    """What the organiser will provide: the official DataPack for the NEXT trading day, put in the (tmp)
    official_datapack_dir. Closes come from the synthetic fixture so the file is internally consistent."""
    import csv
    import json
    from datetime import date, timedelta
    from agent.ops.datapack import simulated_datapack
    closes = {}
    with open(Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / "daily_prices.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["date"] == off["date"] and r.get("close"):
                closes[r["ticker"]] = float(r["close"])
    nxt = date.fromisoformat(off["date"]) + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    d = Path(ops_cfg["paths"]["official_datapack_dir"])
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"DataPack_{team_id}_{nxt.isoformat()}.json"
    p.write_text(json.dumps(simulated_datapack(off, closes, team_id, nxt.isoformat()), ensure_ascii=False),
                 encoding="utf-8")
    return p


def store_without_date(src_store, dst: Path, date: str, tables=("daily_prices", "institutional")):
    """Copy of a store truncated BEFORE `date` in `tables` (live-like: T-1 not yet in the store)."""
    import shutil
    from agent.data.loaders import HistoryStore
    dst.mkdir(parents=True, exist_ok=True)
    for p in src_store.root.glob("*.parquet"):
        shutil.copy2(p, dst / p.name)
    st = HistoryStore(dst)
    for t in tables:
        df = st.load(t)
        df[df["date"] < date].to_parquet(st.path(t), index=False)
    return HistoryStore(dst)


def enter_official(off: dict, ops_cfg, tmp_dir: Path, closes: dict | None = None, confirm: bool = True):
    """Simulate the operator: write the official settlement twice (A/B CSV) and import with double entry."""
    from agent.ops.settlement_entry import import_settlement
    tmp_dir.mkdir(parents=True, exist_ok=True)
    rows = ["ticker,shares"] + [f"{t},{s}" for t, s in sorted(off["holdings"].items())]
    rows += [f"__DATE__,{off['date']}", f"__CASH__,{off['cash']}", f"__NAV__,{off['nav']}",
             f"__ACCRUED__,{off.get('accrued_dividends', 0)}", f"__WARNINGS__,{';'.join(off.get('warnings') or [])}"]
    a, b = tmp_dir / f"off_{off['date']}_A.csv", tmp_dir / f"off_{off['date']}_B.csv"
    for f in (a, b):
        f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    r = import_settlement(off["date"], a, verify_file=b, operator="test operator", source="test back office",
                          confirm=confirm, ops_cfg=ops_cfg, closes=closes or {}, supersede_reason="test re-entry")
    if confirm:                      # the organiser's machine-produced settlement is the official DataPack
        write_official_datapack(off, ops_cfg)
    return r
