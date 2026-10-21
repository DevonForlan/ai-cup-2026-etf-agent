"""CI secret scan over git-TRACKED files (no network, no third-party service).

    python scripts/ci/secret_scan.py            -> exit 1 on any finding

Patterns: provider API keys, GitHub tokens, AWS keys, Slack tokens, private keys, JWTs, credential assignments.
ALLOWLIST holds only documented FAKE test values (e.g. the fake token in the stderr-redaction test,
tests/ops/test_round07.py). The literal is assembled below so this file never matches its own patterns.
Never weaken a pattern to get green: add a precise allowlist entry with a reason instead (reviewed in the PR).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATTERNS = {
    "anthropic_key": r"sk-ant-[A-Za-z0-9_-]{10,}",
    "openai_key": r"\bsk-[A-Za-z0-9]{20,}",
    "google_api_key": r"AIza[0-9A-Za-z_-]{30,}",
    "github_token": r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    "aws_access_key": r"\bAKIA[0-9A-Z]{16}\b",
    "slack_token": r"\bxox[baprs]-[A-Za-z0-9-]{10,}",
    "private_key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "jwt": r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}",
    "credential_assignment": r"(?i)\b(password|passwd|api[_-]?key|secret[_-]?key|access[_-]?token|session[_-]?id)\s*[:=]\s*['\"][^'\"\s*<>{}$]{8,}['\"]",
}
# (path, exact matched text) -> reason. Keep this list tiny and specific.
ALLOWLIST = {
    ("tests/ops/test_round07.py", "sk-ant-" + "oat01-SECRET"): "fake token in the stderr-redaction test",
}
SKIP_SUFFIX = {".pdf", ".docx", ".xlsx", ".png", ".jpg", ".jpeg", ".parquet", ".zip", ".pkl"}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def scan() -> list[dict]:
    rx = {k: re.compile(v) for k, v in PATTERNS.items()}
    findings = []
    for rel in tracked_files():
        p = ROOT / rel
        if p.suffix.lower() in SKIP_SUFFIX or not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for name, r in rx.items():
                for m in r.finditer(line):
                    if (rel.replace("\\", "/"), m.group(0)) in ALLOWLIST:
                        continue
                    findings.append({"file": rel, "line": i, "rule": name, "match": m.group(0)[:12] + "…"})
    return findings


def main() -> int:
    f = scan()
    for x in f:
        print(f"SECRET? {x['file']}:{x['line']} [{x['rule']}] {x['match']}")
    print(f"secret scan: {len(f)} finding(s); allowlisted fakes: {len(ALLOWLIST)}")
    return 1 if f else 0


if __name__ == "__main__":
    raise SystemExit(main())
