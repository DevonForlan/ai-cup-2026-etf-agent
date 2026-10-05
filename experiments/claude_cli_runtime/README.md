# Claude Code CLI runtime PoC (Round 06B)

Python → `subprocess` → the user's own, unmodified, already-logged-in `claude.exe` (`claude -p`). No Agent SDK,
no API key, no setup-token, no credential is read / copied / stored by Python. Calls are sequential.

| script | what it does |
|---|---|
| `auth_probe.py` | `claude auth status` → whitelisted fields only → `reports/claude_cli_auth_probe.json` |
| `smoke_test.py` | first real call: F1 / F2 → {market_view, counter_evidence, fact_refs} |
| `structured_20.py` | 20 sequential calls, same input: schema / grounding / hallucination / latency / variability |
| `attack_tests.py` | permission attacks (dir, git status, .env, edit strategy, create file), injection in fact + system, session leakage, 3 s timeout + cleanup |
| `intelligence_test.py` | conflicting-evidence synthesis + MOPS-like announcements (SYNTHETIC) vs template baseline |
| `research_readonly_test.py` | optional RESEARCH_READONLY profile (Read inside the sandbox only) |
| `narrative_replay.py --days 3/15` | W5 Template vs CLI through the real pipeline + ReplayProvider identity check |

Results in `results/`; replay outputs in `reports/round06b_cli_replay/`, human review in `reports/human_review_cli/`.
Per-call sandboxes: `runtime/claude_cli/<run>/` (gitignored, removed after each call).
Provider: `agent/llm/providers/claude_cli.py`; config `config/llm_claude_cli.yaml` (`enabled: false`);
opt-in: `python agent\competition_day.py ... --llm-provider claude-cli` (default stays template).
