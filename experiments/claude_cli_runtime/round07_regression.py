"""Round 07 minimal real-CLI regression (quota-aware): 1 auth healthcheck + 1 structured smoke.

The smoke uses the new `mops_research` schema on real, PIT-visible MOPS announcements of the current
holdings, through the production path (sectioned config -> ClaudeCodeCLIProvider -> LLMClient ->
MOPSResearcher grounding). Output: whitelisted auth fields only; no credential is read or stored.
Usage: .venv\\Scripts\\python.exe experiments\\claude_cli_runtime\\round07_regression.py --date 2026-10-06
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"

from agent.competition_day import llm_runtime_status  # noqa: E402
from agent.data.loaders import HistoryStore  # noqa: E402
from agent.data.pit import PITView  # noqa: E402
from agent.engine.rules import load_rulebook  # noqa: E402
from agent.llm.client import LLMClient, load_llm_config  # noqa: E402
from agent.llm.logging import LLMCallLogger  # noqa: E402
from agent.llm.providers.claude_cli import ClaudeCodeCLIProvider  # noqa: E402
from agent.ops.common import TPE  # noqa: E402
from agent.research.mops_research import MOPSResearcher, select_documents  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--tickers", default=None, help="comma list (default: latest internal holdings)")
    a = ap.parse_args()
    cfg = dict(load_llm_config("config/llm_claude_cli.yaml"), enabled=True)
    prov = ClaudeCodeCLIProvider(None, cfg)
    st = llm_runtime_status(prov)                                  # 1) auth healthcheck (whitelisted fields)
    out = {"run_at": datetime.now(TPE).isoformat(timespec="seconds"), "healthcheck": st}
    print(st["line"], "| version", st.get("version"), st.get("version_check"), "| auth", st.get("authMethod"),
          st.get("subscriptionType"), st.get("apiProvider"))
    if st["status"] != "READY":
        out["smoke"] = {"skipped": "LLM DEGRADED -> template"}
    else:                                                          # 2) one structured call (mops_research)
        rb = load_rulebook()
        if a.tickers:
            ticks = set(a.tickers.split(","))
        else:
            fin = sorted((ROOT / "submissions" / a.date.replace("-", "") / "FINAL").glob("*.json"))
            ticks = {d["ticker"] for d in json.loads(fin[-1].read_text(encoding="utf-8"))["decisions"]} if fin else set()
            ticks = ticks or set(list(rb.universe)[:30])          # decision tickers of the current FINAL
        view = PITView(HistoryStore(ROOT / "data" / "history"), datetime.now(TPE).isoformat(timespec="seconds"))
        docs = select_documents(view, a.date, ticks, 5, 8)
        acts = {t: "NO_TRADE" for t in ticks}
        log_root = ROOT / "logs" / "llm" / "round07_regression"
        client = LLMClient(cfg, provider=prov, logger=LLMCallLogger(log_root, a.date, True))
        rs = MOPSResearcher(client)
        t0 = time.perf_counter()
        found = rs.run(docs, acts, {t: rb.universe[t]["name"] for t in ticks if t in rb.universe}, a.date)
        out["smoke"] = {"task": "mops_research", "docs": len(docs), "latency_sec": round(time.perf_counter() - t0, 1),
                        "stats": rs.stats.__dict__, "accepted": len(found),
                        "items": [f.item.model_dump() for f in found], "llm": client.logger.summary()}
        print("smoke:", json.dumps({k: out["smoke"][k] for k in ("docs", "latency_sec", "accepted")}),
              "rejected:", rs.stats.rejected, "calls:", client.logger.summary().get("calls"))
    OUT.mkdir(exist_ok=True)
    (OUT / "round07_regression.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str),
                                                 encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
