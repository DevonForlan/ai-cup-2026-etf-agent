"""Shared helpers for the operational layer: config, clock, hashing, logging, status levels."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from agent.config import ROOT

TPE = timezone(timedelta(hours=8))
PASS, WARN, BLOCK = "PASS", "WARN", "BLOCK"


def load_ops_config(path: str | Path = "config/ops.yaml") -> dict:
    p = Path(path)
    p = p if p.is_absolute() else ROOT / p
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def ops_path(cfg: dict, key: str) -> Path:
    p = Path(cfg["paths"][key])
    return p if p.is_absolute() else ROOT / p


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def sha256_json(obj) -> str:
    return sha256_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))


class Clock:
    """Injectable clock (Asia/Taipei). `fixed` simulates a competition-clock time."""

    def __init__(self, fixed: datetime | str | None = None):
        if isinstance(fixed, str):
            fixed = datetime.fromisoformat(fixed)
        self.fixed = fixed
        self._offset = timedelta(0)

    def now(self) -> datetime:
        if self.fixed is not None:
            return (self.fixed + self._offset).astimezone(TPE)
        return datetime.now(TPE)

    def advance(self, **kw) -> None:
        self._offset += timedelta(**kw)


def ymd(d: str) -> str:
    return d.replace("-", "")


def ops_logger(date: str, name: str, cfg: dict | None = None) -> logging.Logger:
    cfg = cfg or load_ops_config()
    d = ops_path(cfg, "ops_logs_dir") / ymd(date)
    d.mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger(f"ops.{name}.{date}")
    if not lg.handlers:
        h = logging.FileHandler(d / f"{name}.log", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        lg.addHandler(h)
        lg.setLevel(logging.INFO)
        lg.propagate = False
    return lg


def write_json(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return p


@dataclass
class Check:
    name: str
    level: str          # PASS | WARN | BLOCK
    detail: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "level": self.level, "detail": self.detail}


def worst(levels) -> str:
    levels = list(levels)
    return BLOCK if BLOCK in levels else (WARN if WARN in levels else PASS)
