"""Official 開賽前試繳 (rehearsal) behaviour verification (Issue #4) — Owner-requested, real UI, step by step.

The portal's rehearsal (observed 2026-10-23: 「開賽前試繳 · 2026-10-23 20:30 至 2026-10-26 00:00 ... 檢核以第 1 交易日
2026-10-27 為準 ... 開賽首日持股為 0（全現金）」) validates an uploaded D-Plan without collecting it. This module:

    .venv\\Scripts\\python.exe -m agent.submission.rehearsal scan
        read-only full DOM state of the 文件繳交 page (buttons enabled / disabled / aria-disabled, hidden controls,
        file inputs, dialogs, forms, tables, alerts). No file selected, no click.
    .venv\\Scripts\\python.exe -m agent.submission.rehearsal probe --file <D-Plan.json> [--control-timeout 900]
        opens the portal in the logged-in automation profile, scans the full DOM state (buttons enabled / disabled /
        aria-disabled, hidden controls, inputs, dialogs, tables, alerts), selects the JSON, then STOPS and waits for an
        explicit instruction in <evidence>/CONTROL.json before every click:
            {"action": "click", "name": "<button accessible name>"}   only names in CLICK_ALLOWLIST
            {"action": "rescan"} | {"action": "reload"} | {"action": "stop"}
        Every step: screenshot + page text + DOM summary + timestamp (local, gitignored).
Never types credentials, never reads cookies / storage / tokens / form values, never calls the portal's /api.
No trial-D-Plan generator: a D-Plan generated before the official window fails C6 inside the FROZEN pipeline
(agent/pipeline.py) and is replaced by the all-cash fallback, so a locally valid file cannot exist during the rehearsal.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.config import ROOT  # noqa: E402
from agent.ops.common import TPE, load_ops_config, sha256_file, write_json, ymd  # noqa: E402

CLICK_ALLOWLIST = ("上傳試繳檔案", "送出繳交", "確認送出", "確認", "確定", "送出", "關閉", "取消")

_SCAN_JS = """() => {
  const sel = 'button, [role=button], input, select, textarea, form, dialog, [role=dialog], [role=alertdialog], ' +
              '[aria-disabled], [role=alert], [role=status], table, [aria-live]';
  const vis = e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  return [...document.querySelectorAll(sel)].map(e => ({
    tag: e.tagName.toLowerCase(), type: e.getAttribute('type'), role: e.getAttribute('role'),
    accept: e.getAttribute('accept'), id: e.id || null, name: e.getAttribute('name'),
    aria_label: e.getAttribute('aria-label'), aria_disabled: e.getAttribute('aria-disabled'),
    disabled: e.disabled === true, hidden_attr: e.hidden === true, visible: vis(e),
    files_selected: (e.tagName === 'INPUT' && e.type === 'file') ? e.files.length : null,
    data: Object.fromEntries([...e.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])),
    text: (e.tagName === 'INPUT' ? '' : (e.innerText || e.textContent || '')).trim().slice(0, 300)}));
}"""


def rehearsal_window(ops_cfg: dict) -> dict | None:
    w = (ops_cfg.get("submission") or {}).get("rehearsal_window")
    return dict(w) if w else None


def rehearsal_root(trade_date: str) -> Path:
    return ROOT / "data" / "official_test_runs" / f"{ymd(trade_date)}_rehearsal"


def in_window(now: datetime, ops_cfg: dict) -> tuple[bool, dict | None]:
    w = rehearsal_window(ops_cfg)
    if not w:
        return False, None
    return datetime.fromisoformat(w["opens"]) <= now < datetime.fromisoformat(w["closes"]), w


# ----------------------------------------------------------------------------- real-UI probe (step by step)
def scan(page) -> dict:
    els = page.evaluate(_SCAN_JS)
    buttons = [e for e in els if e["tag"] == "button" or e["role"] == "button"]
    return {"at": datetime.now(TPE).isoformat(timespec="seconds"), "url": _safe(page.url),
            "buttons": [{k: b[k] for k in ("text", "visible", "disabled", "aria_disabled", "hidden_attr", "type",
                                            "aria_label", "data")} for b in buttons],
            "file_inputs": [e for e in els if e["tag"] == "input" and e["type"] == "file"],
            "dialogs": [e for e in els if e["tag"] == "dialog" or e["role"] in ("dialog", "alertdialog")],
            "alerts": [e for e in els if e["role"] in ("alert", "status") or e.get("aria_live")],
            "forms": [e for e in els if e["tag"] == "form"], "tables": [e for e in els if e["tag"] == "table"],
            "elements_total": len(els)}


def _safe(url: str) -> str:
    from urllib.parse import urlparse
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}{u.path}"


def probe(file: Path, *, control_timeout_s: int = 900, ops_cfg: dict | None = None) -> dict:
    from agent.submission.portal_driver import PlaywrightPortalDriver
    ops_cfg = ops_cfg or load_ops_config()
    ok, w = in_window(datetime.now(TPE), ops_cfg)
    if not ok:
        return {"status": "BLOCKED", "reason": f"OUTSIDE_REHEARSAL_WINDOW ({w})"}
    out_dir = rehearsal_root(w["trade_date"]) / "probe" / datetime.now(TPE).strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    log = {"file": str(file), "filename": file.name, "sha256": sha256_file(file), "file_bytes": file.stat().st_size,
           "steps": [], "out_dir": str(out_dir)}
    drv = PlaywrightPortalDriver(ops_cfg, official_test=True, evidence_dir=out_dir)

    def step(tag: str, **extra):
        page = drv.page
        rec = {"step": tag, "scan": scan(page), "evidence": drv.capture_evidence(tag), **extra}
        try:
            rec["body_text"] = page.inner_text("body", timeout=10000)
        except Exception:  # noqa: BLE001
            rec["body_text"] = None
        log["steps"].append(rec)
        write_json(out_dir / "probe_log.json", log)
        write_json(out_dir / "STATE.json", {"last_step": tag, "buttons": rec["scan"]["buttons"],
                                            "dialogs": rec["scan"]["dialogs"], "waiting_for": "CONTROL.json"})
        return rec

    def wait_control() -> dict:
        ctl = out_dir / "CONTROL.json"
        end = time.monotonic() + control_timeout_s
        while time.monotonic() < end:
            if ctl.exists():
                try:
                    c = json.loads(ctl.read_text(encoding="utf-8"))
                except ValueError:
                    c = None
                ctl.unlink(missing_ok=True)
                if c:
                    return c
            time.sleep(2)
        return {"action": "stop", "reason": "control timeout"}

    try:
        drv.open_portal()
        login = drv.check_login()
        log["login"] = login
        if login != "LOGGED_IN":
            step("login_required")
            log["status"] = "LOGIN_REQUIRED"
            return log
        step("before_upload")
        inp = drv._locate("dplan_file_input", action=True)
        if inp is None:
            step("no_json_input")
            log["status"] = "FAIL_CLOSED"
            return log
        inp.set_input_files(str(file))
        time.sleep(3)
        step("after_select_json")
        while True:
            c = wait_control()
            a = c.get("action")
            if a == "stop":
                step("stopped", reason=c.get("reason"))
                break
            if a == "rescan":
                time.sleep(float(c.get("wait_s", 0)))
                step(c.get("tag") or "rescan")
                continue
            if a == "reload":
                drv.page.reload(wait_until="networkidle")
                time.sleep(3)
                step(c.get("tag") or "after_reload")
                continue
            if a == "click":
                name = c.get("name")
                if name not in CLICK_ALLOWLIST:
                    step("refused_click", refused=name)
                    continue
                btn = drv.page.get_by_role("button", name=name, exact=True)
                if btn.count() != 1:
                    step("click_target_ambiguous", name=name, count=btn.count())
                    continue
                state = {"enabled": btn.is_enabled(), "visible": btn.is_visible()}
                if not state["enabled"]:
                    step("click_target_disabled", name=name, state=state)
                    continue
                btn.click(timeout=10000)
                time.sleep(float(c.get("wait_s", 5)))
                step(c.get("tag") or f"after_click_{name}", clicked=name, state_before=state)
                continue
            step("unknown_control", control=c)
        log["status"] = "DONE"
        return log
    finally:
        write_json(out_dir / "probe_log.json", log)
        drv.close()


def scan_only(*, ops_cfg: dict | None = None) -> dict:
    """Read-only full DOM state of the 文件繳交 page (no file selected, no click)."""
    from agent.submission.portal_driver import PlaywrightPortalDriver
    ops_cfg = ops_cfg or load_ops_config()
    out_dir = ROOT / "data" / "portal_discovery" / (datetime.now(TPE).strftime("%Y%m%d_%H%M%S") + "_domscan")
    out_dir.mkdir(parents=True, exist_ok=True)
    drv = PlaywrightPortalDriver(ops_cfg, evidence_dir=out_dir)
    try:
        drv.open_portal()
        res = {"login": drv.check_login()}
        if res["login"] == "LOGGED_IN":
            res.update(scan=scan(drv.page), evidence=drv.capture_evidence("domscan"))
    finally:
        drv.close()
    write_json(out_dir / "domscan.json", res)
    res["out_dir"] = str(out_dir)
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("probe")
    p.add_argument("--file", required=True)
    p.add_argument("--control-timeout", type=int, default=900)
    sp.add_parser("scan")
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        r = scan_only()
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return 0 if r.get("login") == "LOGGED_IN" else 2
    r = probe(Path(a.file), control_timeout_s=a.control_timeout)
    print(json.dumps({k: r.get(k) for k in ("status", "login", "filename", "sha256", "out_dir")}, ensure_ascii=False,
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
