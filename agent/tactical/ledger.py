"""Local sleeve ledger (data/tactical/<id>/ledger.json). Written atomically; git keeps only metadata via Shared State."""
from __future__ import annotations

import json
import os
from pathlib import Path

from agent.config import ROOT

OPEN_STATES = ("PLANNED", "UNWIND_PLANNED", "OVERDUE")
CLOSED_STATES = ("CLOSED_UNWOUND", "CLOSED_NOT_ENTERED")


def path_for(state_dir, spec_id: str) -> Path:
    d = Path(state_dir) if state_dir else ROOT / "data" / "tactical"
    d = d if d.is_absolute() else ROOT / d
    return d / spec_id / "ledger.json"


def load(state_dir, spec_id: str) -> dict | None:
    p = path_for(state_dir, spec_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save(state_dir, spec_id: str, sleeve: dict) -> Path:
    p = path_for(state_dir, spec_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(sleeve, ensure_ascii=False, indent=1, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, p)
    return p
