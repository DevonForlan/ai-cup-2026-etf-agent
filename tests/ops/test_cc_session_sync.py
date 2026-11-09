"""Issue #55: Claude Code session -> Shared State sync (parsing, redaction, status, retry, never blocking)."""
import json
from pathlib import Path

from agent.ops import cc_session_sync as C

SID = "11111111-2222-3333-4444-555555555555"


def _line(**kw):
    return json.dumps(kw, ensure_ascii=False) + "\n"


def _transcript(tmp_path: Path, extra: str = "") -> Path:
    t = "2026-11-09T07:00:%02d.000Z"
    rows = [
        _line(type="user", timestamp=t % 1, cwd="C:\\Users\\devon.tseng\\Desktop\\proj", origin={"kind": "human"},
              promptSource="typed", message={"role": "user", "content": "Verify the run, token=ghp_" + "a" * 30 + " ok #49"}),
        _line(type="assistant", timestamp=t % 2, message={"model": "m", "role": "assistant", "content": [
            {"type": "thinking", "thinking": "SECRET THOUGHT"},
            {"type": "text", "text": "Reading Issue #49 and PR #53. 下一步：等 17:00 評估。"},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "gh issue view 49 --token abc123456789"}}]}),
        _line(type="user", timestamp=t % 3, message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "x" * 5000}]}),
        _line(type="assistant", timestamp=t % 4, message={"model": "m", "role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "ScheduleWakeup", "input": {"delaySeconds": 3600, "reason": "wait"}}]}),
        _line(type="user", timestamp=t % 5, message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "Next wakeup scheduled for 16:30:00 (in 3507s)."}]}),
        _line(type="system", subtype="stop_hook_summary", timestamp=t % 6),
        _line(type="assistant", timestamp=t % 7, message={"model": "<synthetic>", "role": "assistant", "content": [
            {"type": "text", "text": "API Error: Can't reach the API server (ENOTFOUND)"}]}),
        _line(type="api-request", sessionId=SID, params={"big": "x" * 100}),
    ]
    p = tmp_path / f"{SID}.jsonl"
    p.write_text("".join(rows) + extra, encoding="utf-8")
    return p


def test_parse_events_turns_and_redaction(tmp_path):
    p = _transcript(tmp_path)
    st = C.new_state(SID)
    ev = C.read_new(p, st)
    kinds = [e["kind"] for e in ev]
    assert kinds == ["USER_PROMPT", "CLAUDE_RESPONSE", "TOOL_ACTION", "TOOL_RESULT", "TOOL_ACTION", "TOOL_RESULT",
                     "TURN_END", "API_ERROR"]
    blob = json.dumps(ev)
    assert "ghp_" + "a" * 30 not in blob and "abc123456789" not in blob and "SECRET THOUGHT" not in blob
    assert "devon.tseng" not in blob and "ENOTFOUND" in blob              # operationally useful error text is kept
    assert ev[0]["turn"] == 1 and ev[-1]["turn"] == 2                       # a Stop closes turn 1 (matches the "turn N" count)
    big = next(e for e in ev if e["kind"] == "TOOL_RESULT")
    assert len(big["text"]) < 700 and big["len"] == 5000 and big["sha256"]  # large outputs: clipped + hash kept
    assert st["next_check"] == "16:30:00"


def test_latest_doc_status_and_fields(tmp_path):
    st = C.new_state(SID)
    C.read_new(_transcript(tmp_path), st)
    doc = C.latest_doc(st)
    assert doc["status"] == "ERROR" and doc["latest_user_prompt"].startswith("Verify the run")
    assert doc["related_issues"] == [49] and doc["related_prs"] == [53]
    assert doc["latest_claude_response"].startswith("Reading Issue #49") and "下一步" in doc["pending_next_action"]
    assert "<user>" in doc["project"] and "devon" not in doc["project"]
    st["last_event_kind"] = "TURN_END"
    assert C.latest_doc(st)["status"] == "WAITING_SCHEDULE"                 # a wakeup is pending after the last response
    st["pending_wakeup"] = None
    assert C.latest_doc(st)["status"] == "COMPLETED"


def test_incremental_and_partial_line(tmp_path):
    p = _transcript(tmp_path)
    st = C.new_state(SID)
    first = len(C.read_new(p, st))
    assert C.read_new(p, st) == []                                          # nothing new
    with p.open("a", encoding="utf-8") as f:
        f.write(_line(type="user", timestamp="2026-11-09T07:01:00.000Z", origin={"kind": "human"},
                      message={"role": "user", "content": "next"})[:-10])  # an incomplete trailing line is not consumed
    assert C.read_new(p, st) == []
    with p.open("a", encoding="utf-8") as f:
        f.write(_line(type="user", timestamp="2026-11-09T07:01:00.000Z", origin={"kind": "human"},
                      message={"role": "user", "content": "next"})[-10:])
    n = C.read_new(p, st)
    assert len(n) == 1 and n[0]["kind"] == "USER_PROMPT" and first == 8


def test_local_sync_and_publish_failure_is_queued_not_raised(tmp_path):
    p = _transcript(tmp_path)
    root = tmp_path / "root"
    r = C.sync(SID, str(p), root, push=False, force=True)           # root is not a git repo -> publish fails
    assert r["status"] == "PUBLISH_PENDING"
    d = root / "logs" / "cc_sessions" / SID
    assert (d / "events.jsonl").exists() and (d / "transcript.md").exists() and (d / "latest.json").exists()
    assert json.loads((d / "state.json").read_text(encoding="utf-8"))["pending_publish"] is True   # catch-up on the next sync
    txt = (d / "transcript.md").read_text(encoding="utf-8")
    assert "## Turn 1" in txt and "### User" in txt and "### Claude" in txt and "### Tool actions" in txt
    r2 = C.sync(SID, str(p), root, push=False)                              # second run: no duplicate events
    assert r2["new_events"] == 0
    assert len((d / "events.jsonl").read_text(encoding="utf-8").splitlines()) == 8


def test_hook_never_blocks_or_raises(tmp_path):
    assert C.hook("not json", tmp_path) == 0
    assert C.hook("", tmp_path) == 0
    assert C.hook(json.dumps({"session_id": SID}), tmp_path) == 0           # no transcript path: nothing spawned


def test_redaction_cases():
    for raw, secret in [("Authorization: Bearer abcdef0123456789abcdef", "abcdef0123456789abcdef"),
                        ("password: hunter2hunter2", "hunter2hunter2"), ("https://u:pw12345@h.example/x", "pw12345"),
                        ("mail someone@example.com", "someone@example.com"),
                        ("-----BEGIN PRIV" + "ATE KEY-----\nABC\n-----END PRIV" + "ATE KEY-----", "ABC"),
                        ("C--Users-devon-tseng-Desktop", "devon-tseng")]:
        assert secret not in C.redact(raw)
    assert "ENOTFOUND" in C.redact("getaddrinfo ENOTFOUND api.example.com")


def test_module_never_touches_submission_or_scheduler_code():
    import ast
    tree = ast.parse(Path(C.__file__).read_text(encoding="utf-8"))
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            mods.add(n.module or "")
        elif isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
    assert not [m for m in mods if "submission" in m or "scheduled_run" in m or "competition_day" in m or "morning" in m]


def test_cli_flag_redaction_keeps_the_flag_name():
    out = C.redact("gh x --token abc123456789 --password=hunter22 --verbose non-secret value")
    assert "abc123456789" not in out and "hunter22" not in out
    assert "--token " + C.R in out and "--password=" + C.R in out and chr(1) not in out
    assert "non-secret value" in out and "--verbose" in out                    # prose / other flags untouched
