import copy

import pytest

from agent.ops.common import load_ops_config

CLEAN_GIT = {"sha": "test000", "branch": "master", "dirty_paths": []}
DIRTY_GIT = {"sha": "test000", "branch": "master", "dirty_paths": ["agent/pipeline.py"]}


@pytest.fixture
def ops_cfg(tmp_path):
    """config/ops.yaml with every output path redirected into a (short) tmp dir."""
    c = copy.deepcopy(load_ops_config())
    for k in c["paths"]:
        c["paths"][k] = str(tmp_path / k[:4])
    c["paths"]["first_seen_ledger"] = str(tmp_path / "obs" / "fs.parquet")
    return c
