"""Issue #55 - publish the Claude Code terminal/session record to GitHub Shared State (branch `shared-state`).

    shared_state/cc_sessions/latest.json            newest session pointer (small, queryable)
    shared_state/cc_sessions/index.jsonl            one line per publish
    shared_state/cc_sessions/<session-id>/{transcript.md, events.jsonl, latest.json}

Source: the Claude Code session transcript (<~/.claude/projects/<project>/<session-id>.jsonl, read-only, parsed incrementally by
byte offset). Downstream only: nothing here can touch a decision, a D-Plan, a submission or the scheduler. Every error is
swallowed; the local copy under logs/cc_sessions/<session-id>/ is the durable queue - a failed publish leaves `pending` and the next
sync (any hook, or `sweep`) publishes it, so a DNS/GitHub outage only delays visibility.

    python -m agent.ops.cc_session_sync hook          # Claude Code hook entry (stdin JSON); returns at once, work is detached
    python -m agent.ops.cc_session_sync sync [--session ID | --transcript PATH] [--no-push] [--force]
    python -m agent.ops.cc_session_sync sweep         # every known session, retry pending publishes
    python -m agent.ops.cc_session_sync redact-test

How a reader finds "CC latest response": shared_state/cc_sessions/latest.json -> <session>/latest.json -> transcript.md / events.jsonl
-> related Issue/PR comments -> commits / submission / evaluation Shared State (docs/CC_SESSION_SYNC.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):          # `python <path>/cc_session_sync.py hook` works from any cwd / any shell
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402

REL = "shared_state/cc_sessions"
LOCAL = Path("logs") / "cc_sessions"
PUBLISH_MIN_INTERVAL_S = 90          # throttle of the git publish (local parsing is always incremental and cheap)
HOOK_MIN_INTERVAL_S = 45             # PostToolUse-style hooks: do not even spawn more often than this
LOCK_STALE_S = 600
CLIP_PROMPT, CLIP_RESPONSE, CLIP_TOOL_IN, CLIP_RESULT_T, CLIP_RESULT_E = 8000, 20000, 300, 300, 600
TPE = timezone(timedelta(hours=8))
R = "[REDACTED_SECRET]"

# ----------------------------------------------------------------------------- redaction
_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.S), R),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"), R),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"), R),
    (re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}"), R),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), R),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), R),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), R),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), R),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), R),          # JWT
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/]{12,}=*"), r"\1 " + R),
    (re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1" + R + "@"),                            # user:pass@host
    # key = value / key: value / "key": "value" for secret-like keys (value redacted, key kept)
    (re.compile(r"(?i)(\"?\b(?:password|passwd|pwd|passphrase|secret|client[_-]?secret|api[_-]?key|apikey|"
                r"access[_-]?key|secret[_-]?key|private[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
                r"auth[_-]?token|token|csrf[_-]?token|xsrf[_-]?token|csrf|xsrf|session[_-]?(?:secret|token|key|"
                r"cookie)|sessionid|cookie|set-cookie|authorization)\b\"?\s*[:=]\s*)(\"[^\"\n]{4,}\"|'[^'\n]{4,}'|"
                r"[^\s,;'\"<>]{4,}[^\n]*?)(?=$|[\s,;}])", re.M), r"\1" + R),
    # command-line flags: --token VALUE / --password=VALUE / -p VALUE style secrets
    (re.compile(r"(?i)(?<![\w-])(--?(?:token|password|passwd|secret|api-key|apikey|access-key|auth|cookie|bearer)(?:\s+|=))(?!--)[^\s\"']{4,}"), r"\1" + R),
    (re.compile(r"(?i)([?&](?:token|access_token|api_key|apikey|key|sig|signature|csrf|session)=)[^&\s\"'<>]+"), r"\1" + R),
    # personal data (organisation policy): e-mail addresses, except the commit-trailer noreply address
    (re.compile(r"\b(?!noreply@anthropic\.com\b)[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
]
_USER_PATH = re.compile(r"(?i)([A-Z]:[\\/]+Users[\\/]+)[^\\/\s\"']+")
_USER_NAME = re.compile(r"(?i)devon[.\-]tseng|DEVON~1\.TSE")


def redact(s: str) -> str:
    if not s:
        return s
    for rx, rep in _PATTERNS:
        s = rx.sub(rep, s)
    s = _USER_PATH.sub(r"\1<user>", s)
    return _USER_NAME.sub("<user>", s)


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + f"…[+{len(s) - n} chars; sha256:{hashlib.sha256(s.encode('utf-8', 'replace')).hexdigest()[:16]}]"


def _clean(s: str, n: int) -> str:
    return redact(_clip(s, n))


# ----------------------------------------------------------------------------- transcript -> events
_SYSREM = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_TN = re.compile(r"<task-notification>.*?</task-notification>", re.S)
_TAG = lambda t, s: (re.search(rf"<{t}>(.*?)</{t}>", s, re.S) or [None, ""])[1].strip()  # noqa: E731
_WAKE = re.compile(r"Next wakeup scheduled for ([^\n(]+)")
_SKIP_PREFIX = ('{"type":"api-request', '{"type":"file-history', '{"type":"mode"', '{"type":"permission-mode"',
                '{"type":"atis-latch"', '{"type":"last-prompt"', '{"type":"ai-title"', '{"type":"session-owner"',
                '{"type":"cost-state"', '{"type":"tools-used"')


def _ts(d: dict) -> str:
    return d.get("timestamp") or ""


def new_state(session_id: str) -> dict:
    return {"session_id": session_id, "offset": 0, "seq": 0, "turn": 1, "stops": 0, "rendered_turn": 0, "group": None,
            "last_prompt": None, "last_response": None, "last_response_ts": None, "last_tool_actions": [], "last_event_kind": None,
            "last_ts": None, "cwd": None, "pending_wakeup": None, "next_check": None, "recent_text": [], "prs": [],
            "pending_publish": False, "last_publish": 0.0}


def _tool_summary(name: str, inp: dict) -> str:
    keys = ("command", "file_path", "path", "pattern", "url", "query", "prompt", "description", "skill", "to", "delaySeconds")
    bits = [f"{k}={inp[k]}" for k in keys if k in inp and inp[k] not in (None, "")]
    return _clean(f"{name}: " + " | ".join(str(b).replace("\n", " ") for b in bits) if bits else name, CLIP_TOOL_IN)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def parse_line(d: dict, st: dict) -> list[dict]:
    """One transcript record -> 0..n sanitized events (mutates the running state `st`)."""
    out: list[dict] = []
    t = d.get("type")
    ts = _ts(d)
    if d.get("cwd"):
        st["cwd"] = d["cwd"]

    def emit(kind: str, **kw):
        st["seq"] += 1
        ev = {"seq": st["seq"], "ts": ts, "turn": st["turn"], "kind": kind, **kw}
        out.append(ev)
        st["last_event_kind"], st["last_ts"] = kind, ts or st["last_ts"]
        st["recent_text"] = (st["recent_text"] + [ev.get("text") or ev.get("summary") or ""])[-40:]

    if t == "system":
        sub = d.get("subtype")
        if sub == "stop_hook_summary":
            emit("TURN_END", text=f"turn {st['turn']} completed")
            st["stops"] += 1
            st["turn"] = st["stops"] + 1
        elif sub == "scheduled_task_fire":
            st["pending_wakeup"] = None
            emit("SCHEDULED_WAKEUP", text=_clean(d.get("content", ""), 300), prompt=_clean(d.get("prompt", ""), 600))
        elif sub in ("informational", "local_command", "compact_boundary", "model_refusal_no_fallback", "away_summary"):
            txt = d.get("content") or d.get("subtype")
            emit("SYSTEM_INFO" if sub != "model_refusal_no_fallback" else "API_ERROR", subtype=sub, text=_clean(str(txt), 600))
        return out
    if t == "pr-link":
        n = d.get("prNumber")
        if n and (not st["prs"] or st["prs"][-1] != n):          # the transcript repeats this record every turn
            st["prs"] = (st["prs"] + [n])[-10:]
            emit("PR_LINK", pr=n, text=f"PR #{n} {d.get('prUrl', '')}")
        return out
    if t == "attachment":
        a = d.get("attachment") or {}
        if a.get("type") == "queued_command":
            txt = _text_of(a.get("prompt") or "")
            if "<task-notification>" in txt:
                for m in _TN.findall(txt):
                    emit("TASK_NOTIFICATION", task_id=_TAG("task-id", m), status=_TAG("status", m), text=_clean(_TAG("summary", m), 400))
        elif a.get("type") == "task_status":
            emit("BACKGROUND_TASK_STATUS", task_id=a.get("taskId"), status=a.get("status"), text=_clean(str(a.get("description", "")), 300))
        return out
    if t == "assistant":
        m = d.get("message") or {}
        synthetic = m.get("model") == "<synthetic>" or d.get("isApiErrorMessage")
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                txt = _clean(b["text"], CLIP_RESPONSE)
                if synthetic:
                    emit("API_ERROR", text=_clean(b["text"], 1500))
                else:
                    st["last_response"], st["last_response_ts"] = txt, ts
                    emit("CLAUDE_RESPONSE", text=txt)
            elif b.get("type") == "tool_use":
                inp = b.get("input") or {}
                summ = _tool_summary(b.get("name", "?"), inp)
                st["last_tool_actions"] = (st["last_tool_actions"] + [summ])[-8:]
                if b.get("name") == "ScheduleWakeup" and not inp.get("stop"):
                    st["pending_wakeup"] = {"at": ts, "delaySeconds": inp.get("delaySeconds"), "reason": _clean(str(inp.get("reason", "")), 200)}
                emit("TOOL_ACTION", tool=b.get("name"), tool_use_id=b.get("id"), summary=summ)
        return out
    if t == "user":
        m = d.get("message") or {}
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    txt = _text_of(c) if not isinstance(c, str) else c
                    w = _WAKE.search(txt or "")
                    if w:
                        st["next_check"] = w.group(1).strip()
                    emit("TOOL_RESULT", tool_use_id=b.get("tool_use_id"), is_error=bool(b.get("is_error")), len=len(txt or ""),
                         sha256=hashlib.sha256((txt or "").encode("utf-8", "replace")).hexdigest()[:16],
                         text=_clean(txt or "", CLIP_RESULT_E if b.get("is_error") or "ENOTFOUND" in (txt or "") else CLIP_RESULT_T))
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                return out
        raw = _text_of(content or "")
        origin = d.get("origin")
        kind = origin.get("kind") if isinstance(origin, dict) else None
        if "<task-notification>" in raw and (kind in ("task-notification", None)):
            for tn in _TN.findall(raw):
                emit("TASK_NOTIFICATION", task_id=_TAG("task-id", tn), status=_TAG("status", tn), text=_clean(_TAG("summary", tn), 400))
            return out
        body = _SYSREM.sub("", raw).strip()
        if not body:
            return out
        if kind == "peer":
            emit("SUBAGENT_HANDBACK", text=_clean(body, 1500))
        elif d.get("turnOrigin") == "scheduled" or kind == "auto-continuation":
            emit("SCHEDULED_PROMPT", text=_clean(body, 1500))
            st["pending_wakeup"] = None
        else:
            st["last_prompt"] = _clean(body, CLIP_PROMPT)
            st["pending_wakeup"] = None
            emit("USER_PROMPT", text=st["last_prompt"], source=d.get("promptSource") or kind)
    return out


def read_new(path: Path, st: dict, max_bytes: int = 400_000_000) -> list[dict]:
    """Parse the transcript from st['offset'] (complete lines only) and advance the offset."""
    events: list[dict] = []
    size = path.stat().st_size
    if size < st["offset"]:                       # transcript rewritten/truncated: restart
        sid = st["session_id"]
        st.clear()
        st.update(new_state(sid))
    with path.open("rb") as f:
        f.seek(st["offset"])
        pos = st["offset"]
        while pos < min(size, st["offset"] + max_bytes):
            line = f.readline()
            if not line or not line.endswith(b"\n"):
                break
            pos += len(line)
            s = line.decode("utf-8", "replace")
            if s.startswith(_SKIP_PREFIX):
                continue
            try:
                events.extend(parse_line(json.loads(s), st))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        st["offset"] = pos
    return events


# ----------------------------------------------------------------------------- rendering
def _local_ts(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TPE).strftime("%Y-%m-%d %H:%M:%S%z")
    except ValueError:
        return ts


_GROUP = {"USER_PROMPT": "User", "SCHEDULED_PROMPT": "User", "CLAUDE_RESPONSE": "Claude", "TOOL_ACTION": "Tool actions",
          "TOOL_RESULT": "Tool actions"}


def render(events: list[dict], st: dict) -> str:
    out: list[str] = []
    for e in events:
        if e["turn"] != st["rendered_turn"]:
            out.append(f"\n## Turn {e['turn']} — {_local_ts(e['ts'])}\n")
            st["rendered_turn"], st["group"] = e["turn"], None
        g = _GROUP.get(e["kind"], "Events")
        if g != st["group"]:
            out.append(f"\n### {g}\n")
            st["group"] = g
        k = e["kind"]
        if k in ("USER_PROMPT", "SCHEDULED_PROMPT", "CLAUDE_RESPONSE"):
            out.append(f"_{_local_ts(e['ts'])}_\n\n{e['text']}\n")
        elif k == "TOOL_ACTION":
            out.append(f"- `{e['summary']}`")
        elif k == "TOOL_RESULT":
            out.append(f"  - result{' (ERROR)' if e.get('is_error') else ''}: {e['text'].replace(chr(10), ' ')[:300]}")
        else:
            out.append(f"- **{k}** {_local_ts(e['ts'])} {(e.get('text') or e.get('summary') or '').replace(chr(10), ' ')[:400]}")
    return "\n".join(out) + ("\n" if out else "")


# ----------------------------------------------------------------------------- latest.json
_PR_RE = re.compile(r"\bPRs?\s*#(\d{1,4})")
_ISSUE_RE = re.compile(r"(?<!PR )(?<!PRs )#(\d{2,3})\b")


def _status(st: dict) -> str:
    last = st.get("last_event_kind")
    text = (st.get("last_response") or "")
    if last == "API_ERROR":
        return "ERROR"
    if "BLOCKED_HARD_CONSTRAINT" in text:
        return "BLOCKED"
    if st.get("pending_wakeup") and last in ("TURN_END", "CLAUDE_RESPONSE"):
        return "WAITING_SCHEDULE"
    if last == "TURN_END":
        return "COMPLETED"
    return "RUNNING"


def _next_action(text: str) -> str:
    for ln in (text or "").splitlines():
        if re.match(r"\s*[*\-]?\s*\**(下一步|NEXT_ACTION|Next action|接下來)", ln):
            return ln.strip()[:400]
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    return (lines[-1] if lines else "")[:400]


def _production_head() -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT), capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def latest_doc(st: dict) -> dict:
    blob = "\n".join(st.get("recent_text") or [])
    issues = []
    for n in _ISSUE_RE.findall(blob):
        if int(n) not in issues:
            issues.append(int(n))
    prs = list(dict.fromkeys(int(n) for n in _PR_RE.findall(blob))) or [int(p) for p in st.get("prs", [])[-1:]]
    return {"session_id": st["session_id"], "turn": st["turn"] - (1 if st.get("last_event_kind") == "TURN_END" else 0),
            "timestamp": _local_ts(st.get("last_ts") or ""), "project": redact(st.get("cwd") or ""),
            "status": _status(st), "latest_user_prompt": st.get("last_prompt"), "latest_claude_response": st.get("last_response"),
            "latest_claude_response_at": _local_ts(st.get("last_response_ts") or ""),
            "latest_tool_summary": "; ".join((st.get("last_tool_actions") or [])[-5:]),
            "pending_next_action": _next_action(st.get("last_response") or ""),
            "next_scheduled_check": st.get("next_check") if st.get("pending_wakeup") else None,
            "related_issues": issues[-8:], "related_prs": prs[-6:], "production_head": _production_head(),
            "events": st["seq"], "synced_at": datetime.now(TPE).replace(microsecond=0).isoformat()}


# ----------------------------------------------------------------------------- local store + publish
def _local_dir(root: Path, sid: str) -> Path:
    return root / LOCAL / sid


def _locate(sid: str | None = None, transcript: str | None = None) -> tuple[str, Path] | None:
    if transcript:
        p = Path(transcript)
        return (sid or p.stem, p) if p.exists() else None
    base = Path.home() / ".claude" / "projects"
    cands = sorted(base.glob(f"*/{sid}.jsonl")) if sid else []
    if cands:
        return sid, cands[0]
    return None


def _with_lock(d: Path, fn):
    d.mkdir(parents=True, exist_ok=True)
    lock = d / "sync.lock"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime < LOCK_STALE_S:
            return {"status": "BUSY"}
        lock.write_text(str(os.getpid()), encoding="utf-8")
        return fn()
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def sync_local(sid: str, transcript: Path, root: Path) -> dict:
    """Incrementally parse the transcript into logs/cc_sessions/<sid>/ (always safe, no network)."""
    d = _local_dir(root, sid)

    def work():
        sp = d / "state.json"
        st = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else new_state(sid)
        events = read_new(transcript, st)
        if events:
            with (d / "events.jsonl").open("a", encoding="utf-8", newline="\n") as f:
                for e in events:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            with (d / "transcript.md").open("a", encoding="utf-8", newline="\n") as f:
                if not (d / "transcript.md").stat().st_size:
                    f.write(f"# Claude Code session {sid}\n\nSanitized, redacted, append-only. Source: local session transcript (read-only).\n")
                f.write(render(events, st))
            st["pending_publish"] = True
        doc = latest_doc(st)
        (d / "latest.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        sp.write_text(json.dumps(st, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return {"status": "OK", "new_events": len(events), "doc": doc, "state": st}

    return _with_lock(d, work)


def publish(sid: str, root: Path, *, push: bool = True, force: bool = False) -> dict:
    """Copy the local session files to the shared-state worktree, commit and push. Never raises."""
    from agent.ops import shared_state_sync as S
    d = _local_dir(root, sid)
    try:
        sp = d / "state.json"
        st = json.loads(sp.read_text(encoding="utf-8"))
        if not force and not st.get("pending_publish"):
            return {"status": "NOTHING_TO_PUBLISH"}
        if not force and time.time() - st.get("last_publish", 0) < PUBLISH_MIN_INTERVAL_S:
            return {"status": "THROTTLED"}
        wt = S.ensure_worktree(root)
        dst = wt / REL / sid
        dst.mkdir(parents=True, exist_ok=True)
        for n in ("transcript.md", "events.jsonl", "latest.json"):
            if (d / n).exists():
                (dst / n).write_bytes((d / n).read_bytes())
        doc = json.loads((d / "latest.json").read_text(encoding="utf-8"))
        top = wt / REL / "latest.json"
        cur = None
        try:
            cur = json.loads(top.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if cur is None or (cur.get("session_id") == sid) or (cur.get("synced_at", "") <= doc["synced_at"]):
            top.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        with (wt / REL / "index.jsonl").open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({k: doc[k] for k in ("session_id", "turn", "timestamp", "status", "events", "synced_at")}) + "\n")
        ga = wt / ".gitattributes"
        if not ga.exists() or "shared_state/** -text" not in ga.read_text(encoding="utf-8"):
            ga.write_text((ga.read_text(encoding="utf-8") if ga.exists() else "") + "shared_state/** -text\n", encoding="utf-8", newline="\n")
        S._git(wt, "add", "-A", REL, ".gitattributes")
        if S._git(wt, "diff", "--cached", "--quiet", check=False).returncode != 0:
            S._git(wt, "commit", "-q", "-m", f"shared-state: cc session {sid[:8]} turn {doc['turn']} {doc['status']}\n\n"
                   "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        pushed = None
        if push:
            for _ in range(S.PUSH_ATTEMPTS):
                r = S._git(wt, "push", "-u", "origin", S.BRANCH, check=False)
                if r.returncode == 0:
                    pushed = True
                    break
                S._git(wt, "pull", "--rebase", "origin", S.BRANCH, check=False)
            else:
                raise RuntimeError("push failed: " + (r.stderr or r.stdout).strip()[:200])
        st["pending_publish"], st["last_publish"] = False, time.time()
        sp.write_text(json.dumps(st, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        return {"status": "PUBLISHED", "pushed": bool(pushed), "turn": doc["turn"]}
    except Exception as e:  # noqa: BLE001  downstream only: the local queue keeps the data, the next sync retries
        return {"status": "PUBLISH_PENDING", "detail": f"{type(e).__name__}: {e}"[:300]}


def sync(sid: str | None = None, transcript: str | None = None, root=None, *, push: bool = True, force: bool = False) -> dict:
    root = Path(root or ROOT)
    loc = _locate(sid, transcript)
    if loc is None:
        return {"status": "TRANSCRIPT_NOT_FOUND"}
    sid, path = loc
    try:
        r = sync_local(sid, path, root)
    except Exception as e:  # noqa: BLE001
        return {"status": "PARSE_ERROR", "detail": f"{type(e).__name__}: {e}"[:300]}
    if r.get("status") != "OK":
        return r
    p = publish(sid, root, push=push, force=force)
    return {"status": p["status"], "new_events": r["new_events"], "turn": r["doc"]["turn"], "session_status": r["doc"]["status"], **p}


def sweep(root=None, *, push: bool = True) -> list[dict]:
    root = Path(root or ROOT)
    out = []
    base = root / LOCAL
    for sp in sorted(base.glob("*/state.json")) if base.is_dir() else []:
        out.append({"session_id": sp.parent.name, **publish(sp.parent.name, root, push=push)})
    return out


# ----------------------------------------------------------------------------- hook entry (never blocks, always exit 0)
def hook(stdin_text: str, root=None) -> int:
    try:
        root = Path(root or ROOT)
        info = json.loads(stdin_text or "{}")
        sid, tp = info.get("session_id"), info.get("transcript_path")
        ev = info.get("hook_event_name", "")
        if not sid or not tp:
            return 0
        d = _local_dir(root, sid)
        d.mkdir(parents=True, exist_ok=True)
        mark = d / "hook.stamp"
        fast = ev in ("Stop", "UserPromptSubmit", "SubagentStop", "SessionEnd", "Notification", "SessionStart", "PreCompact")
        if not fast and mark.exists() and time.time() - mark.stat().st_mtime < HOOK_MIN_INTERVAL_S:
            return 0
        mark.write_text(str(time.time()), encoding="utf-8")
        cmd = [sys.executable, str(Path(__file__).resolve()), "sync", "--session", sid, "--transcript", tp]
        if ev in ("Stop", "SessionEnd"):
            cmd.append("--force")
        flags = 0x08000000 | 0x00000008 if os.name == "nt" else 0       # CREATE_NO_WINDOW | DETACHED_PROCESS
        subprocess.Popen(cmd, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)
    except Exception:  # noqa: BLE001
        pass
    return 0


def redact_test() -> int:
    samples = {"Authorization: Bearer abcdef0123456789abcdef": "abcdef0123456789abcdef",
               "token=ghp_" + "a" * 30: "ghp_" + "a" * 30, "password: hunter2hunter2": "hunter2hunter2",
               "https://user:pw12345@example.com/x": "pw12345", "x api_key = sk-" + "b" * 24: "b" * 24,
               "mail me at someone@example.com": "someone@example.com", "-----BEGIN PRIV" + "ATE KEY-----\nABC\n-----END PRIV" + "ATE KEY-----": "ABC",
               "C:\\Users\\devon.tseng\\Desktop\\x": "devon.tseng", "Cookie: sessionid=zzzzzzzzzz": "zzzzzzzzzz"}
    bad = [k for k, v in samples.items() if v in redact(k)]
    print("redact-test", "FAIL " + str(bad) if bad else "PASS")
    return 1 if bad else 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=("hook", "sync", "sweep", "redact-test"))
    ap.add_argument("--session")
    ap.add_argument("--transcript")
    ap.add_argument("--root")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "hook":
        return hook(sys.stdin.read(), a.root)
    if a.cmd == "redact-test":
        return redact_test()
    if a.cmd == "sweep":
        for r in sweep(a.root, push=not a.no_push):
            print(json.dumps(r, ensure_ascii=False))
        return 0
    r = sync(a.session, a.transcript, a.root, push=not a.no_push, force=a.force)
    print(json.dumps({k: v for k, v in r.items() if k != "doc"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
