"""Secret / sensitive-data scan (Round 06). Pattern-based; findings are REDACTED (never printed in full).

  python agent\\ops\\security_scan.py            -> reports/round06_security_scan.md / .json

Scans: every git-tracked file, plus untracked operational logs (logs/llm, logs/ops) and rehearsal outputs.
Checks: API keys (Google / OpenAI / Anthropic / AWS / GitHub / Slack), bearer tokens, private keys, passwords /
secrets assignments, connection strings with credentials, .env tracked by git, .env missing from .gitignore,
and environment-variable key VALUES appearing in any scanned file (exact match, if a key is set).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import write_json  # noqa: E402

PATTERNS = [
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"(?i)\bauthorization\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("connection_string", re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|mssql)://[^\s:/@]+:[^\s@/]+@")),
    ("odbc_password", re.compile(r"(?i)\b(?:password|pwd)\s*=\s*[^;'\"\s]{4,}\s*;")),
    ("password_assignment", re.compile(r"(?i)\b(?:password|passwd|secret|api_key|apikey|access_token)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]")),
]
KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
SKIP_EXT = {".parquet", ".npy", ".png", ".jpg", ".pdf", ".docx", ".xlsx", ".zip", ".pyc", ".gz"}
ALLOW = [re.compile(r"(?i)password\s*[:=]\s*['\"](?:\*+|x+|<[^>]+>|redacted|dummy[^'\"]*)['\"]")]


def redact(s: str) -> str:
    s = s.strip()
    return (s[:4] + "…" + f"[{len(s)} chars]") if len(s) > 8 else "[redacted]"


def tracked_files() -> list[Path]:
    r = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, timeout=60)
    return [ROOT / x for x in r.stdout.decode("utf-8", "replace").split("\0") if x]


def extra_files() -> list[Path]:
    out = []
    for d in ("logs/llm", "logs/ops", "rehearsal", "submissions", "data/settlement"):
        p = ROOT / d
        if p.exists():
            out += [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in {".json", ".jsonl", ".log", ".txt",
                                                                                   ".md", ".csv"}]
    return out


def scan_text(text: str, rel: str, env_values: dict[str, str]) -> list[dict]:
    found = []
    for i, line in enumerate(text.splitlines(), 1):
        for name, rx in PATTERNS:
            for m in rx.finditer(line):
                if any(a.search(line) for a in ALLOW):
                    continue
                found.append({"file": rel, "line": i, "type": name, "match": redact(m.group(0))})
        for k, v in env_values.items():
            if v and len(v) >= 8 and v in line:
                found.append({"file": rel, "line": i, "type": f"env_value:{k}", "match": redact(v)})
    return found


def scan(files: list[Path] | None = None, *, include_untracked_logs: bool = True) -> dict:
    files = files if files is not None else tracked_files() + (extra_files() if include_untracked_logs else [])
    env_values = {k: os.environ.get(k, "") for k in KEY_ENVS}
    findings, scanned, skipped = [], 0, 0
    for f in files:
        if not f.is_file() or f.suffix.lower() in SKIP_EXT or f.stat().st_size > 20 * 2**20:
            skipped += 1
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            skipped += 1
            continue
        scanned += 1
        rel = str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else str(f)
        findings += scan_text(text, rel.replace("\\", "/"), env_values)
    checks = []
    tracked = {str(p.relative_to(ROOT)).replace("\\", "/") for p in tracked_files()} if files else set()
    env_tracked = sorted(t for t in tracked if t == ".env" or t.endswith("/.env") or t.startswith(".env."))
    env_tracked = [t for t in env_tracked if not t.endswith(".example")]
    checks.append({"check": ".env not tracked by git", "ok": not env_tracked, "detail": env_tracked})
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    checks.append({"check": ".env in .gitignore", "ok": any(l.strip() == ".env" for l in gi.splitlines()), "detail": ""})
    checks.append({"check": "logs/llm ignored", "ok": "logs/llm/" in gi, "detail": ""})
    res = {"scanned_files": scanned, "skipped_files": skipped, "findings": findings, "checks": checks,
           "env_keys_present": {k: "PRESENT" if v else "ABSENT" for k, v in env_values.items()},
           "passed": not findings and all(c["ok"] for c in checks)}
    return res


def write_report(res: dict, out: Path | None = None) -> Path:
    out = out or ROOT / "reports" / "round06_security_scan.md"
    write_json(out.with_suffix(".json"), res)
    lines = ["# Security scan (Round 06)", "", f"**{'PASS' if res['passed'] else 'FINDINGS'}** — scanned "
             f"{res['scanned_files']} files (tracked + operational logs), skipped {res['skipped_files']} binary/large.", "",
             "| check | ok |", "|---|---|"] + [f"| {c['check']} | {'yes' if c['ok'] else 'NO ' + str(c['detail'])} |"
                                             for c in res["checks"]]
    lines += ["", f"API key env vars: {res['env_keys_present']} (presence only; values never printed)", "",
              "## Findings (redacted)", ""]
    lines += ["| file | line | type | redacted |", "|---|---|---|---|"] + \
        [f"| {f['file']} | {f['line']} | {f['type']} | {f['match']} |" for f in res["findings"]] if res["findings"] else ["none"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    res = scan()
    p = write_report(res)
    print(f"SECURITY SCAN: {'PASS' if res['passed'] else 'FINDINGS'} ({res['scanned_files']} files) -> {p}")
    for f in res["findings"][:50]:
        print(f"  {f['file']}:{f['line']}  {f['type']}  {f['match']}")
    return 0 if res["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
