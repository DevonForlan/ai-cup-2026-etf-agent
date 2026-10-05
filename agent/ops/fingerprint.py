"""Deterministic decision fingerprint (Round 06).

decision_core  = hash of WHAT the agent decided: decisions (ticker, action, target_weight), no-trade names,
                 orders (ticker, side, shares), market_view regime / stance / posture.
decision_fingerprint = hash of decision_core + the inputs that produced it: strategy config hash, data
                 snapshot hash, settlement hash, code version.
Never included: generated_at / run timestamps, run_id, LLM or template prose, agent_metadata.
Same inputs -> same fingerprint; a different fingerprint with identical inputs means non-determinism.
"""
from __future__ import annotations

from pathlib import Path

from agent.ops.common import sha256_file, sha256_json

NARRATIVE_KEYS = ("logic", "counter_evidence", "risk_check", "statement", "conclusion")


def decision_core(doc: dict) -> dict:
    mv = doc.get("market_view") or {}
    return {
        "trade_date": doc.get("trade_date"), "team_id": doc.get("team_id"),
        "market_view": {k: mv.get(k) for k in ("regime", "stance", "posture")},
        "decisions": sorted(([d["ticker"], d["action"], d.get("target_weight")] for d in doc.get("decisions", [])),
                            key=lambda x: x[0]),
        "no_trade": sorted(([d["ticker"], d.get("target_weight")] for d in doc.get("no_trade_decisions", [])),
                           key=lambda x: x[0]),
        "orders": sorted(([o["ticker"], o["side"], int(o["shares"])] for o in doc.get("orders", [])),
                         key=lambda x: (x[0], x[1])),
    }


def decision_core_hash(doc: dict) -> str:
    return sha256_json(decision_core(doc))


def decision_fingerprint(doc: dict, *, strategy_hash: str | None, data_snapshot_hash: str | None,
                         settlement_hash: str | None, code_version: str | None) -> str:
    return sha256_json({"core": decision_core(doc), "strategy": strategy_hash, "data": data_snapshot_hash,
                        "settlement": settlement_hash, "code": code_version})


def narrative_text(doc: dict) -> dict:
    """All prose fields (excluded from the fingerprint) — used to classify NARRATIVE_ONLY differences."""
    mv = doc.get("market_view") or {}
    return {"market_view": [mv.get("logic"), mv.get("counter_evidence")],
            "inferences": [[i.get("inf_id"), i.get("logic"), i.get("counter_evidence"), i.get("conclusion")]
                           for i in doc.get("inferences", [])],
            "observations": [[o.get("obs_id"), o.get("statement")] for o in doc.get("observations", [])],
            "decisions": [[d.get("decision_id"), d.get("risk_check")] for d in doc.get("decisions", [])]}


def store_snapshot_hash(store_root: Path) -> str:
    """Hash of every parquet table in the history store (same as refresh_daily's store_manifest_hash)."""
    return sha256_json({p.name: sha256_file(p) for p in sorted(Path(store_root).glob("*.parquet"))})
