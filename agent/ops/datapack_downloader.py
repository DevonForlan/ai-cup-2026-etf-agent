"""Official DataPack providers (docs/OFFICIAL_DATAPACK_INTEGRATION.md).

  ManualFileProvider      ENABLED  — scans data/official_datapack/*.json (files the operator downloaded by hand
                                     from the back office 「文件繳交」→「下載資料包」) and returns the latest one for
                                     the requested trade date. It never asks a human to type holdings / cash / NAV.
  OfficialPortalProvider  DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION — does nothing: no browser login, no guessed
                                     URL / API, no cookies / tokens / CSRF. Returns DOWNLOAD_NOT_CONFIGURED.

Official portal auto-download: PENDING_REAL_DATAPACK_AVAILABILITY (phases D1–D5 in the doc).
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTAL_STATUS = "DISABLED_PENDING_OFFICIAL_PORTAL_VALIDATION"


class DataPackProvider(ABC):
    name = "base"
    status = "ENABLED"

    @abstractmethod
    def locate(self, team_id: str, trade_date: str) -> Path | None:
        """Path of the latest candidate DataPack for (team_id, trade_date), or None. Never validates content."""


class ManualFileProvider(DataPackProvider):
    name = "manual_file"
    status = "ENABLED"

    def __init__(self, directory: Path | None = None, ops_cfg: dict | None = None):
        if directory is None:
            from agent.ops.common import load_ops_config, ops_path
            directory = ops_path(ops_cfg or load_ops_config(), "official_datapack_dir")
        self.directory = Path(directory)

    def candidates(self, team_id: str) -> list[tuple[str, str, Path]]:
        """(trade_date, generated_at, path) of every file in the official directory that declares itself a
        DataPack of this team. Unreadable / foreign files are skipped here and reported by the validator only
        if they are the selected file."""
        out = []
        if not self.directory.exists():
            return out
        for p in sorted(self.directory.glob("*.json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                out.append(("", "", p))                     # kept so a damaged latest file is not silently ignored
                continue
            if isinstance(d, dict) and d.get("doc_type") == "DataPack" and d.get("team_id") == team_id:
                out.append((str(d.get("trade_date") or ""), str(d.get("generated_at") or ""), p))
        return out

    def locate(self, team_id: str, trade_date: str) -> Path | None:
        c = self.candidates(team_id)
        exact = sorted((x for x in c if x[0] == trade_date), key=lambda x: (x[1], x[2].stat().st_mtime))
        if exact:
            return exact[-1][2]                              # latest generated DataPack for this trade date
        # nothing for this trade date: return the newest readable or unreadable file so the validator can say
        # exactly why (stale / invalid) instead of a bare "missing"
        rest = sorted(c, key=lambda x: (x[0], x[1], x[2].stat().st_mtime))
        return rest[-1][2] if rest else None


class OfficialPortalProvider(DataPackProvider):
    name = "official_portal"
    status = PORTAL_STATUS

    def locate(self, team_id: str, trade_date: str) -> Path | None:
        return None

    def fetch(self, team_id: str, trade_date: str) -> dict:
        return {"status": "DOWNLOAD_NOT_CONFIGURED", "provider_status": PORTAL_STATUS,
                "detail": "official portal download not implemented: no login, no guessed endpoint, no cookies"}


def fetch_latest_datapack(team_id: str, trade_date: str, provider: DataPackProvider | None = None) -> dict:
    """Entry point used by the scheduler / status command. Only the manual-file provider is active."""
    portal = OfficialPortalProvider()
    provider = provider or ManualFileProvider()
    path = provider.locate(team_id, trade_date)
    return {"provider": provider.name, "provider_status": provider.status, "file": str(path) if path else None,
            "portal": portal.fetch(team_id, trade_date)}
