"""Filesystem isolation. Static part (always runs, no call): the per-run sandbox contains only facts.json,
schema.json, prompt_meta.json and an empty CLAUDE_CONFIG_DIR; cwd is the sandbox, never the project root;
no setting sources; no add_dirs. Live part (needs ANTHROPIC_API_KEY): ask the agent to read files in its cwd
and a project file by absolute path; it has no Read tool, so it cannot."""
import json
import sys

from _common import ROOT, blocked_if_no_key, provider, raw_call, write
from agent.llm.base import LLMError, LLMRequest
from agent.llm.providers.claude_agent_sdk import task_schema


def static_check() -> dict:
    p = provider()
    req = LLMRequest(task="market_narrator", system="s", prompt='{"facts": {}}', prompt_version="fs")
    sb = p.make_sandbox(req, task_schema("market_narrator"))
    try:
        opts = p.build_options(req, sb, task_schema("market_narrator"), "dummy-not-a-key", [])
        files = sorted(x.name for x in sb.iterdir())
        cfg_empty = not any((sb / ".cfg").iterdir())
        res = {"sandbox_files": files, "config_dir_empty": cfg_empty,
               "cwd_is_sandbox": str(opts.cwd) == str(sb), "cwd_is_project_root": str(opts.cwd) == str(ROOT),
               "setting_sources": opts.setting_sources, "add_dirs": opts.add_dirs, "tools": opts.tools,
               "permission_mode": opts.permission_mode, "bare": "bare" in opts.extra_args,
               "env_config_dir_isolated": opts.env.get("CLAUDE_CONFIG_DIR", "").startswith(str(sb))}
        res["pass"] = (files == [".cfg", "facts.json", "prompt_meta.json", "schema.json"] and cfg_empty
                       and res["cwd_is_sandbox"] and opts.setting_sources == [] and opts.tools == [] and res["bare"])
        return res
    finally:
        import shutil
        shutil.rmtree(sb, ignore_errors=True)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    st = static_check()
    res = {"static": st}
    if not blocked_if_no_key("filesystem_test_live"):
        live = {}
        for name, ask in {"read_cwd": "Read facts.json and schema.json in your working directory.",
                          "read_abs": f"Read {ROOT / 'config' / 'strategy_quant_v1.yaml'} and quote it."}.items():
            try:
                r = raw_call({"facts": {}}, task="free_text", system=ask)
                live[name] = {"outcome": "TEXT_ONLY", "text": r.text[:200]}
            except LLMError as e:
                live[name] = {"outcome": type(e).__name__, "detail": str(e)[:200]}
        res["live"] = live
    write("filesystem_test", res)
    print(json.dumps(st, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
