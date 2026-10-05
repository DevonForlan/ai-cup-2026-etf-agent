"""First real smoke test through the user's own logged-in claude CLI (`claude -p`, NARRATIVE_LOCKED).
F1 TAIEX 20-day trend positive / F2 SOX overnight -0.4% -> {market_view, counter_evidence, fact_refs}."""
import json
import sys

from _common import SMOKE_FACTS, call, count_procs, grounded, grounding, provider, repo_state, write


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = provider()
    hc = p.healthcheck()
    before = {"claude": count_procs("claude.exe"), "repo": repo_state()}
    r = call(p, SMOKE_FACTS)
    after = {"claude": count_procs("claude.exe"), "repo": repo_state()}
    out = {"healthcheck": {k: hc[k] for k in ("claude_code_version", "authMethod", "profile", "status")}, "call": r,
           "claude_procs_before": before["claude"], "claude_procs_after": after["claude"],
           "repo_unchanged": before["repo"] == after["repo"]}
    if r["ok"]:
        obj = json.loads(r["text"])
        g = grounding(SMOKE_FACTS, obj)
        out.update(schema_ok=set(obj) == {"market_view", "counter_evidence", "fact_refs"}, grounding=g,
                   grounded=grounded(g), output=obj)
    write("smoke_test", out)
    print(json.dumps({k: out.get(k) for k in ("healthcheck", "schema_ok", "grounded", "repo_unchanged",
                                              "claude_procs_before", "claude_procs_after")}, ensure_ascii=False))
    print("call:", json.dumps({k: r.get(k) for k in ("ok", "error", "category", "detail", "model", "latency")},
                              ensure_ascii=False))
    print("meta:", json.dumps({k: (r.get("meta") or {}).get(k) for k in
                               ("exit_code", "init_tools", "init_mcp_servers", "tool_violations", "permission_denials",
                                "sandbox_created_files", "session_id", "usage", "total_cost_usd", "stderr_summary")},
                              ensure_ascii=False, default=str)[:1500])
    if r["ok"]:
        print("output:", r["text"][:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
