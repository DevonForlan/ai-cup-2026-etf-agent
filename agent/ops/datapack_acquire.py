"""Automatic official DataPack acquisition through the confirmed portal UI (Issue #23, Owner priority update
2026-10-27). Used by the 19:30 / 07:30 COMPETITION runs before the DataPack gate.

    .venv\\Scripts\\python.exe -m agent.ops.datapack_acquire --date 2026-10-28 [--team-id TEAM_11442]

Flow (fail closed at every step; nothing is guessed):
  1. a DataPack for T that already passes the gate is in data/official_datapack/  -> ALREADY_PRESENT (no browser)
  2. Owner-logged-in automation profile: login LOGGED_IN, page Team ID == team, page trade date == T
     (otherwise LOGIN_REQUIRED / PAGE_MISMATCH: no download)
  3. press the CONFIRMED 下載資料包 button (portal_driver.download_datapack: browser download event only; no URL,
     API, cookie or token handling) into a quarantine folder data/official_datapack/.incoming/<ts>/
  4. validate the downloaded file with the SAME gate the run uses (agent.ops.datapack.datapack_gate):
     doc_type, team_id, trade_date, as_of_date == previous trading day, `missing`, schema, numbers
  5. PASS -> atomic move (os.replace) into data/official_datapack/ + provenance record (sha256, size, time,
     suggested filename, page identity, gate result) in data/official_datapack/provenance/
     STALE / not yet published -> bounded retry (the portal refreshes after 19:00); INVALID -> kept in quarantine
The official file content is never modified. Downloads stay local (gitignored).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.ops.common import TPE, load_ops_config, ops_path, write_json  # noqa: E402

RETRYABLE = ("DATAPACK_STALE", "DATAPACK_MISSING", "DOWNLOAD_FAILED")


def cfg_acquire(ops_cfg: dict) -> dict:
    a = dict(((ops_cfg.get("datapack") or {}).get("auto_download")) or {})
    a.setdefault("enabled", False)
    a.setdefault("max_attempts", 3)
    a.setdefault("retry_wait_s", 300)
    a.setdefault("download_timeout_s", 60)
    return a


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _gate(trade_date: str, team: str, directory: Path, ops_cfg: dict) -> dict:
    from agent.ops.datapack import datapack_gate
    from agent.ops.datapack_downloader import ManualFileProvider
    return datapack_gate(trade_date, team, provider=ManualFileProvider(directory=directory), ops_cfg=ops_cfg)


def _audit(ops_cfg: dict, row: dict) -> None:
    d = ops_path(ops_cfg, "official_datapack_dir") / "provenance"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "acquisition_log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def install(downloaded: Path, trade_date: str, team: str, ops_cfg: dict, meta: dict) -> dict:
    """Validate a downloaded file in quarantine, then move it atomically into the official folder."""
    official = ops_path(ops_cfg, "official_datapack_dir")
    g = _gate(trade_date, team, downloaded.parent, ops_cfg)
    sha = _sha(downloaded)
    res = {"status": None, "gate": {k: g.get(k) for k in ("status", "reason", "freshness", "validation",
                                                          "settlement_date", "problems", "warnings")},
           "sha256": sha, "bytes": downloaded.stat().st_size, "quarantine": str(downloaded)}
    if g["status"] != "PASS":
        res["status"] = g.get("reason") or "DATAPACK_INVALID"
        return res
    for p in official.glob("*.json"):                     # identical official file already installed
        if _sha(p) == sha:
            res.update(status="ALREADY_PRESENT", file=str(p))
            return res
    target = official / downloaded.name
    if target.exists():                                   # same name, different content: keep both, never overwrite
        target = official / f"{downloaded.stem}_{datetime.now(TPE):%Y%m%d_%H%M%S}{downloaded.suffix}"
    os.replace(downloaded, target)
    prov = {"file": target.name, "sha256": sha, "bytes": res["bytes"], "trade_date": trade_date, "team_id": team,
            "installed_at": datetime.now(TPE).isoformat(), "method": "portal UI 下載資料包 (Owner-logged-in profile)",
            "gate": res["gate"], **meta}
    write_json(official / "provenance" / f"{target.stem}.json", prov)
    res.update(status="INSTALLED", file=str(target), provenance=prov)
    return res


def acquire(trade_date: str, team: str, *, ops_cfg: dict | None = None, driver_factory=None, sleep=time.sleep,
            force: bool = False) -> dict:
    ops_cfg = ops_cfg or load_ops_config()
    a = cfg_acquire(ops_cfg)
    official = ops_path(ops_cfg, "official_datapack_dir")
    official.mkdir(parents=True, exist_ok=True)
    out = {"trade_date": trade_date, "team_id": team, "started_at": datetime.now(TPE).isoformat(), "attempts": []}
    if not force:
        g = _gate(trade_date, team, official, ops_cfg)
        if g["status"] == "PASS":
            out.update(status="ALREADY_PRESENT", file=g["file"])
            _audit(ops_cfg, out)
            return out
    if not (a["enabled"] or force):
        out.update(status="AUTO_DOWNLOAD_DISABLED")
        _audit(ops_cfg, out)
        return out
    status = None
    for n in range(1, int(a["max_attempts"]) + 1):
        r = _attempt(trade_date, team, ops_cfg, a, driver_factory)
        out["attempts"].append(r)
        status = r["status"]
        if status not in RETRYABLE or n == int(a["max_attempts"]):
            break
        sleep(float(a["retry_wait_s"]))
    out.update(status=status, file=out["attempts"][-1].get("file"), finished_at=datetime.now(TPE).isoformat())
    _audit(ops_cfg, out)
    return out


def _attempt(trade_date: str, team: str, ops_cfg: dict, a: dict, driver_factory) -> dict:
    from agent.submission.portal_driver import UIUnexpected
    ts = datetime.now(TPE).strftime("%Y%m%d_%H%M%S")
    quarantine = ops_path(ops_cfg, "official_datapack_dir") / ".incoming" / ts
    r = {"at": datetime.now(TPE).isoformat()}
    drv = None
    try:
        if driver_factory is None:
            from agent.submission.auto_upload import _default_driver
            driver_factory = _default_driver
        drv = driver_factory(ops_cfg, False)
        drv.open_portal()
        login = drv.check_login()
        if login != "LOGGED_IN":
            r.update(status="LOGIN_REQUIRED", detail=f"LOGIN_STATE_{login}")
            return r
        page_team, page_date = drv.read_team_id(), drv.read_trade_date()
        r.update(page_team_id=page_team, page_trade_date=page_date)
        if page_team != team or page_date != trade_date:
            r.update(status="PAGE_MISMATCH", detail=f"page {page_team} / {page_date} != {team} / {trade_date}")
            return r
        dl = drv.download_datapack(quarantine, timeout_s=float(a["download_timeout_s"]))
        meta = {"suggested_filename": dl.get("suggested_filename"), "page_team_id": page_team,
                "page_trade_date": page_date, "portal_url": getattr(drv, "safe_url", lambda: None)(),
                "downloaded_at": datetime.now(TPE).isoformat()}
        res = install(Path(dl["path"]), trade_date, team, ops_cfg, meta)
        r.update(res)
        if res["status"] not in ("INSTALLED", "ALREADY_PRESENT"):
            write_json(quarantine / "QUARANTINED.json", {"reason": res["status"], **res})
        return r
    except UIUnexpected as e:
        r.update(status="DOWNLOAD_FAILED", detail=str(e)[:300])
        return r
    except Exception as e:  # noqa: BLE001 - any browser problem fails closed (the run then stays BLOCKED)
        r.update(status="DOWNLOAD_FAILED", detail=f"{type(e).__name__}: {str(e)[:250]}")
        return r
    finally:
        if drv is not None:
            try:
                drv.close()
            except Exception:  # noqa: BLE001
                pass


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--team-id", default=None)
    ap.add_argument("--force", action="store_true", help="download even if a valid DataPack is already present / "
                                                         "auto_download is disabled (manual operator run)")
    a = ap.parse_args(argv)
    ops = load_ops_config()
    team = a.team_id or (ops.get("team") or {}).get("competition_team_id")
    r = acquire(a.date, team, ops_cfg=ops, force=a.force)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return 0 if r["status"] in ("INSTALLED", "ALREADY_PRESENT") else 2


if __name__ == "__main__":
    raise SystemExit(main())
