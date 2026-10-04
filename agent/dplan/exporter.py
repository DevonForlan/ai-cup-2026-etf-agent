"""Evidence Graph -> D-Plan v4.2 JSON. Only nodes reachable from market_view / decisions /
no_trade_decisions / orders are exported; IDs are renumbered S1.., O1.., I1.., D1.. in first-use order."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from agent.dplan.graph import EvidenceGraph


def _clean_values(v: dict) -> dict:
    out = {}
    for k, x in v.items():
        if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
            continue
        out[k] = int(x) if isinstance(x, bool) else x
    return out or {"value_missing": 0}


def export_dplan(g: EvidenceGraph, team_id: str, metadata: dict) -> tuple[dict, dict]:
    """Returns (dplan dict, id_map internal_key -> exported id)."""
    idmap: dict[str, str] = {}
    cnt = {"S": 0, "O": 0, "I": 0, "D": 0}

    def assign(key: str, prefix: str) -> str:
        if key not in idmap:
            cnt[prefix] += 1
            idmap[key] = f"{prefix}{cnt[prefix]}"
        return idmap[key]

    mv = g.get("mv")
    decisions = g.of_kind("Decision")
    nts = g.of_kind("NoTrade")
    orders = g.of_kind("Order")

    # traversal order: market view -> decisions -> no-trades (first-use numbering)
    def visit_fact(fk: str) -> str:
        for sk in g.get(fk).refs:
            assign(sk, "S")
        return assign(fk, "O")

    for fk in mv.refs:
        visit_fact(fk)
    for d in decisions:
        for ik in d.refs:
            for fk in g.get(ik).refs:
                visit_fact(fk)
            assign(ik, "I")
        assign(d.key, "D")
    for n in nts:
        for ik in n.refs:
            for fk in g.get(ik).refs:
                visit_fact(fk)
            assign(ik, "I")
    # inferences that nothing references (only in fallback with no holdings) still need >=1
    if cnt["I"] == 0:
        infs = g.of_kind("Inference")
        if infs:
            for fk in infs[0].refs:
                visit_fact(fk)
            assign(infs[0].key, "I")

    def ordered(prefix: str):
        return sorted((k for k, v in idmap.items() if v.startswith(prefix)), key=lambda k: int(idmap[k][1:]))

    sources = []
    for k in ordered("S"):
        d = g.get(k).data
        s = {"source_id": idmap[k], "authority": d["authority"], "url": d["url"], "name": d["name"][:300]}
        for opt in ("archive_url", "published_at"):
            if d.get(opt):
                s[opt] = d[opt]
        s["content_as_of"] = d["content_as_of"]
        if d.get("fetched_at"):
            s["fetched_at"] = d["fetched_at"]
        sources.append(s)
    observations = []
    for k in ordered("O"):
        n = g.get(k)
        o = {"obs_id": idmap[k], "source_ref": [idmap[r] for r in n.refs][:5]}
        if n.data.get("topic"):
            o["topic"] = n.data["topic"]
        o["statement"] = n.data["statement"][:500]
        o["values"] = _clean_values(n.data["values"])
        observations.append(o)
    inferences = []
    for k in ordered("I"):
        n = g.get(k)
        i = {"inf_id": idmap[k], "premise_refs": [idmap[r] for r in n.refs][:10], "logic": n.data["logic"][:1000]}
        if n.data.get("conclusion"):
            i["conclusion"] = n.data["conclusion"][:300]
        i["counter_evidence"] = (n.data.get("counter_evidence") or None)
        if i["counter_evidence"]:
            i["counter_evidence"] = i["counter_evidence"][:500]
        inferences.append(i)
    dec_out = []
    for d in decisions:
        x = {"decision_id": idmap[d.key], "ticker": d.data["ticker"], "action": d.data["action"],
             "target_weight": d.data["target_weight"], "inference_refs": [idmap[r] for r in d.refs][:5]}
        if d.data.get("risk_check"):
            x["risk_check"] = d.data["risk_check"][:300]
        if d.data.get("funding_for"):
            x["funding_for"] = [idmap[r] for r in d.data["funding_for"]][:5]
        dec_out.append(x)
    nt_out = []
    for n in nts:
        x = {"ticker": n.data["ticker"], "reason_refs": [idmap[r] for r in n.refs][:5]}
        if n.data.get("reason"):
            x["reason"] = n.data["reason"][:300]
        nt_out.append(x)
    ord_out = []
    for o in orders:
        x = {"ticker": o.data["ticker"], "side": o.data["side"], "shares": int(o.data["shares"]),
             "decision_ref": idmap[o.data["decision_ref"]]}
        if o.data.get("derivation_detail"):
            x["derivation_detail"] = o.data["derivation_detail"][:300]
        ord_out.append(x)
    md = mv.data

    def sub(text):
        # replace {{internal_key}} placeholders with exported IDs (e.g. {{fact:2330}} -> O5)
        if not isinstance(text, str):
            return text
        return re.sub(r"\{\{([^}]+)\}\}", lambda m: idmap.get(m.group(1), "?"), text)

    for i in inferences:
        i["logic"] = sub(i["logic"])
        if i.get("counter_evidence"):
            i["counter_evidence"] = sub(i["counter_evidence"])
    doc = {
        "schema_version": "4.2",
        "doc_type": "D-Plan",
        "team_id": team_id,
        "trade_date": g.trade_date,
        "sources": sources,
        "observations": observations,
        "market_view": {"basis_refs": [idmap[r] for r in mv.refs][:10], "logic": sub(md["logic"])[:1000],
                        "regime": md["regime"], "stance": md["stance"], "posture": md["posture"],
                        "counter_evidence": md.get("counter_evidence")},
        "inferences": inferences,
        "decisions": dec_out,
        "no_trade_decisions": nt_out,
        "orders": ord_out,
        "agent_metadata": metadata,
    }
    return doc, idmap


def write_dplan(doc: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"D-Plan_{doc['team_id']}_{doc['trade_date']}.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
