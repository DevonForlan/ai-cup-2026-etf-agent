"""Raw snapshot storage: data/raw/YYYYMMDD/<source>/<file> + manifest.json (append-only)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from agent.config import ROOT

RAW_DIR = ROOT / "data" / "raw"


@dataclass
class ManifestEntry:
    source: str            # e.g. twse_mi_index
    url: str
    fetched_at: str        # ISO +08:00
    content_as_of: str     # time the content describes
    published_at: str | None
    available_at: str      # earliest time we treat this content as visible (PIT)
    sha256: str
    parser_version: str
    authority: str         # twse|tpex|taifex|mops|fininst|media|vendor|other
    path: str              # relative to project root
    synthetic: bool = False


def sha256_bytes(b: bytes) -> str:
    return "sha256:" + hashlib.sha256(b).hexdigest()


def save_raw(snapshot_date: str, source: str, filename: str, content: bytes, *, url: str,
             fetched_at: str, content_as_of: str, available_at: str, authority: str,
             parser_version: str, published_at: str | None = None, synthetic: bool = False,
             raw_dir: Path = RAW_DIR) -> ManifestEntry:
    """snapshot_date = YYYYMMDD folder (the trade date whose data this is)."""
    d = raw_dir / snapshot_date / source
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_bytes(content)
    entry = ManifestEntry(
        source=source, url=url, fetched_at=fetched_at, content_as_of=content_as_of,
        published_at=published_at, available_at=available_at, sha256=sha256_bytes(content),
        parser_version=parser_version, authority=authority,
        path=str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p).replace("\\", "/"),
        synthetic=synthetic,
    )
    append_manifest(raw_dir / snapshot_date, entry)
    return entry


def append_manifest(day_dir: Path, entry: ManifestEntry) -> None:
    """Several fetchers may write the same day folder: serialise with a pid-aware lock file.
    A crashed writer's lock is recovered only when its owner process is gone (agent.data.locks)."""
    import os
    from agent.data.locks import FileLock
    mf = day_dir / "manifest.json"
    with FileLock(mf.with_suffix(".lock"), timeout=60.0, stale_after=120.0):
        entries = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else []
        entries.append(asdict(entry))
        tmp = mf.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, mf)


def read_manifest(day_dir: Path) -> list[dict]:
    mf = day_dir / "manifest.json"
    return json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else []
