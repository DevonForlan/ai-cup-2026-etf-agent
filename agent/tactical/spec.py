"""Load + pin-check the tactical override spec.

The pin (sha256 of the spec file) lives in config/ops.yaml, so editing the spec without re-pinning disables the overlay
(fail closed -> pure Frozen Quant v1).
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agent.config import ROOT


@dataclass
class Spec:
    raw: dict
    path: Path
    sha256: str
    pin_ok: bool
    pin_reason: str
    sector_map: dict = field(default_factory=dict)

    @property
    def body(self) -> dict:
        return self.raw["tactical_override"]

    @property
    def id(self) -> str:
        return str(self.body["id"])

    @property
    def enabled(self) -> bool:
        return bool(self.body.get("enabled", False)) and self.pin_ok

    @property
    def entry_date(self) -> str:
        return str(self.body["entry_trade_date"])

    @property
    def hold_days(self) -> int:
        return int(self.body.get("hold_trading_days", 1))

    @property
    def exit_date(self) -> str:
        m = {int(k): str(v) for k, v in self.body["exit_trade_dates"].items()}
        if self.hold_days not in m:
            raise ValueError(f"hold_trading_days={self.hold_days} has no exit date in the spec")
        return m[self.hold_days]

    @property
    def fingerprint(self) -> str:
        return "sha256:" + self.sha256


def _abs(p) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def load_sector_map(path) -> dict[str, str]:
    with open(_abs(path), encoding="utf-8-sig", newline="") as f:
        return {r["ticker"].strip(): r["sector"].strip() for r in csv.DictReader(f)}


def load_spec(ops_cfg: dict | None) -> Spec | None:
    """None when no tactical section is configured. A present-but-unpinned/mismatching spec is returned with pin_ok=False
    (so an OPEN sleeve can still be unwound from the ledger, while no NEW entry is ever planned)."""
    t = (ops_cfg or {}).get("tactical")
    if not t:
        return None
    path = _abs(t["spec"])
    if not path.exists():
        return None
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    raw = yaml.safe_load(data.decode("utf-8")) or {}
    pinned = str(t.get("spec_sha256", "")).replace("sha256:", "")
    enabled_cfg = bool(t.get("enabled", False))
    ok = enabled_cfg and bool(pinned) and pinned == sha
    reason = ("OK" if ok else "ops.yaml tactical.enabled is false" if not enabled_cfg
              else "spec sha256 not pinned" if not pinned else f"spec sha256 {sha} != pinned {pinned}")
    sp = Spec(raw, path, sha, ok, reason)
    sp.sector_map = load_sector_map(sp.body["sector_map"]) if "tactical_override" in raw else {}
    return sp
