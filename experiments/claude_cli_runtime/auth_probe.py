"""Claude Code CLI auth probe (Round 06B). Runs the official `claude auth status` (JSON) and keeps ONLY:
loggedIn, authMethod, subscription / API-key type, whether the login belongs to an organization (boolean),
CLI version. Never prints or stores tokens, emails, organization names/ids, credential paths or raw output.

  .venv\\Scripts\\python.exe experiments\\claude_cli_runtime\\auth_probe.py   -> reports\\claude_cli_auth_probe.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from agent.llm.providers.claude_cli import clean_env, resolve_claude_cli  # noqa: E402

ALLOWED_KEYS = {"loggedIn", "authMethod", "subscriptionType", "apiProvider", "apiKeySource"}


def parse_status(stdout: str, exit_code: int) -> dict:
    """Pure parser (unit-tested): whitelist fields, reduce org info to a boolean, drop everything else."""
    try:
        j = json.loads(stdout or "{}")
    except ValueError:
        return {"loggedIn": exit_code == 0, "authMethod": "unparseable", "parse_error": True}
    out = {k: j.get(k) for k in ALLOWED_KEYS if k in j}
    out.setdefault("loggedIn", exit_code == 0)
    org_keys = [k for k in j if "org" in k.lower()]
    out["ORG_MANAGED_ACCOUNT"] = any(bool(j.get(k)) for k in org_keys)
    out["fields_seen"] = sorted(j.keys())            # names only, never values
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cli = resolve_claude_cli()
    res = {"probed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cli_found": bool(cli["path"]),
           "cli_kind": cli["kind"], "claude_code_version": cli["version"]}
    if cli["path"]:
        r = subprocess.run([cli["path"], "auth", "status"], capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace", env=clean_env())
        res.update(parse_status(r.stdout, r.returncode))
        res["exit_code"] = r.returncode
    out = ROOT / "reports" / "claude_cli_auth_probe.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in ("claude_code_version", "cli_kind", "loggedIn", "authMethod", "subscriptionType", "apiProvider",
              "ORG_MANAGED_ACCOUNT"):
        print(f"{k}: {res.get(k)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
