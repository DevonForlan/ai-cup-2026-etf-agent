"""Issue #23: the two intermittent local failures reproduced deterministically and fixed.

1. manifest.json rename: a Windows scanner / indexer briefly holding the target makes os.replace raise
   PermissionError [WinError 5] -> retried, still raised when it never clears.
2. Claude CLI hard timeout: taskkill itself stalling past its 30 s timeout (machine under load) used to escape as
   TimeoutExpired -> the child is killed directly and the runner returns a timed-out record instead of raising.
"""
import os
import subprocess
import sys

import pytest

from agent.data import manifest as M
from agent.llm.providers import claude_cli as C


def test_manifest_replace_retries_transient_permission_error(tmp_path, monkeypatch):
    src, dst = tmp_path / "m.tmp1", tmp_path / "manifest.json"
    src.write_text("[1]", encoding="utf-8")
    dst.write_text("[]", encoding="utf-8")
    real, calls = os.replace, []

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError(13, "Access is denied")       # WinError 5 while another process holds dst
        real(a, b)
    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    M.replace_with_retry(src, dst)
    assert len(calls) == 3 and dst.read_text(encoding="utf-8") == "[1]" and not src.exists()


def test_manifest_replace_gives_up_and_raises(tmp_path, monkeypatch):
    calls = []

    def locked(a, b):
        calls.append(1)
        raise PermissionError(13, "Access is denied")
    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(PermissionError):
        M.replace_with_retry(tmp_path / "a", tmp_path / "b", attempts=4)
    assert len(calls) == 4                                       # bounded, never silent


def test_manifest_replace_does_not_retry_other_errors(tmp_path, monkeypatch):
    calls = []

    def missing(a, b):
        calls.append(1)
        raise FileNotFoundError(a)
    monkeypatch.setattr(os, "replace", missing)
    with pytest.raises(FileNotFoundError):
        M.replace_with_retry(tmp_path / "a", tmp_path / "b")
    assert len(calls) == 1


@pytest.mark.skipif(os.name != "nt", reason="taskkill path is Windows-only")
def test_cli_timeout_survives_a_stalled_taskkill(tmp_path, monkeypatch):
    real_run = subprocess.run

    def stalled(cmd, *a, **k):
        if cmd and cmd[0] == "taskkill":
            raise subprocess.TimeoutExpired(cmd, 30)             # taskkill itself hung (observed 2026-10-27 17:00)
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(C.subprocess, "run", stalled)
    # a child that ignores CTRL_BREAK for the grace period forces the kill path
    code = "import signal,time; signal.signal(signal.SIGBREAK, signal.SIG_IGN); time.sleep(60)"
    rec = C.default_runner([sys.executable, "-c", code], "", str(tmp_path), C.clean_env(), timeout=1.0, grace=1.0)
    assert rec["timed_out"] and rec["cleanup"] == "killed_tree" and rec.get("taskkill_failed") is True
    assert rec["elapsed"] < 30
    out = real_run(["tasklist", "/FI", f"PID eq {rec['pid']}", "/NH"], capture_output=True, text=True).stdout
    assert str(rec["pid"]) not in out                            # no orphan left behind
