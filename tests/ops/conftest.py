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
    return c


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
    return import_settlement(off["date"], a, verify_file=b, operator="test operator", source="test back office",
                             confirm=confirm, ops_cfg=ops_cfg, closes=closes or {},
                             supersede_reason="test re-entry")
