"""Official portal browser driver (Issue #4) — normal browser automation of the human UI.

The driver operates the real page in a PERSISTENT browser profile (system Microsoft Edge via Playwright) that the
Owner logs into interactively. It never types credentials, never reads cookies / storage / tokens, never calls the
portal's private /api, never bypasses SSO / MFA / CAPTCHA. Selectors and official wording come only from
config/portal_adapter.yaml; anything not confirmed there is unusable (UIUnexpected -> the runner fails closed).

    .venv\\Scripts\\python.exe -m agent.submission.portal_driver discover [--wait-login 300] [--headless]
        read-only: open the portal, wait for the Owner's manual login (optional), capture the page state
        (url, title, visible buttons / headings / dialogs, which adapter selectors resolve, screenshot) into
        data/portal_discovery/<timestamp>/ (local only, gitignored). Never uploads or clicks submit.
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
from agent.ops.common import TPE, load_ops_config  # noqa: E402

ACTION_OK_COMPETITION = {"CONFIRMED_REAL_E2E"}
ACTION_OK_OFFICIAL_TEST = {"CONFIRMED_REAL_E2E", "OWNER_OBSERVED_LABEL", "GENERIC_CANDIDATE"}
READ_OK = {"CONFIRMED_REAL_E2E", "CONFIRMED_PUBLIC_BUNDLE", "OWNER_OBSERVED_LABEL", "GENERIC_CANDIDATE"}
PENDING = ("PENDING_REAL_E2E_SELECTOR", "PENDING_REAL_E2E_WORDING")


class UIUnexpected(RuntimeError):
    """The portal did not look / behave as confirmed in the adapter -> fail closed."""


# ----------------------------------------------------------------------------- adapter
def load_adapter(path: str | Path | None = None) -> dict:
    import yaml
    p = Path(path) if path else ROOT / "config" / "portal_adapter.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def wording_markers(adapter: dict, key: str) -> list[str]:
    """Verbatim official markers; PENDING wording -> [] (never matched)."""
    w = (adapter.get("wording") or {}).get(key) or {}
    return [] if w.get("status") in PENDING else [m for m in (w.get("markers") or []) if m]


def classify(text: str, adapter: dict, pass_key: str, fail_key: str) -> str:
    """PASS / FAIL / UNKNOWN from verbatim markers only; never guessed from fuzzy text. Both or neither -> UNKNOWN."""
    t = text or ""
    p = any(m in t for m in wording_markers(adapter, pass_key))
    f = any(m in t for m in wording_markers(adapter, fail_key))
    return "PASS" if (p and not f) else ("FAIL" if (f and not p) else "UNKNOWN")


def selector_inventory(adapter: dict) -> list[dict]:
    out = []
    for name, s in (adapter.get("selectors") or {}).items():
        out.append({"element": name, "status": s.get("status"), "strategies": s.get("strategies") or [],
                    "usable_for_read": s.get("status") in READ_OK and bool(s.get("strategies")),
                    "usable_for_action_competition": s.get("status") in ACTION_OK_COMPETITION,
                    "usable_for_action_official_test": s.get("status") in ACTION_OK_OFFICIAL_TEST and bool(s.get("strategies"))})
    return out


# ----------------------------------------------------------------------------- driver interface
class PortalDriver:
    """Interface used by agent/submission/auto_upload.py (tests use a fake implementation)."""
    def open_portal(self): ...
    def check_login(self) -> str: ...                       # LOGGED_IN | LOGIN_REQUIRED | UNKNOWN
    def read_page_state(self) -> dict: ...                  # url, title, modals, window_status, markers
    def read_team_id(self) -> str | None: ...
    def read_trade_date(self) -> str | None: ...
    def read_window_status(self) -> str: ...                # OPEN | CLOSED | UNKNOWN
    def read_attempts(self) -> tuple[int | None, int | None]: ...   # (used, remaining)
    def read_history(self) -> list[dict]: ...
    def read_strategy_document_status(self) -> str | None: ...
    def upload_file(self, path: Path): ...
    def wait_for_server_validation(self, timeout_s: float): ...
    def read_validation_result(self) -> tuple[str, str]: ...  # (PASS | FAIL | UNKNOWN, verbatim text)
    def submit(self): ...
    def read_submit_result(self) -> tuple[str, str]: ...    # (OK | FAIL | UNKNOWN, verbatim text)
    def verify_acceptance(self, file_name: str, sha256: str, trade_date: str, timeout_s: float, poll_s: float) -> list[dict]: ...
    def capture_evidence(self, tag: str) -> list[str]: ...
    def close(self): ...


class PlaywrightPortalDriver(PortalDriver):
    def __init__(self, ops_cfg: dict | None = None, *, official_test: bool = False, headless: bool = False,
                 adapter: dict | None = None, evidence_dir: Path | None = None):
        ops_cfg = ops_cfg or load_ops_config()
        a = ops_cfg.get("auto_upload") or {}
        self.adapter = adapter or load_adapter(a.get("adapter"))
        self.url = (ops_cfg.get("submission") or {}).get("portal_url") or self.adapter.get("portal_url")
        self.official_test = official_test
        self.profile = ROOT / a.get("browser_profile_dir", "data/browser_profiles/fundaiagent")
        self.channel = a.get("browser_channel", "msedge")
        self.evidence_dir = evidence_dir or ROOT / "data" / "submission_evidence"
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise UIUnexpected("PLAYWRIGHT_NOT_INSTALLED (pip install -r requirements-portal.txt)") from e
        self.profile.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.ctx = self._pw.chromium.launch_persistent_context(str(self.profile), channel=self.channel,
                                                               headless=headless, accept_downloads=True)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    # --- selector resolution -------------------------------------------------------------------------------
    def _sel(self, name: str) -> dict:
        s = (self.adapter.get("selectors") or {}).get(name)
        if not s:
            raise UIUnexpected(f"UNKNOWN_SELECTOR {name}")
        return s

    def _locate(self, name: str, *, action: bool = False):
        s = self._sel(name)
        allowed = (ACTION_OK_OFFICIAL_TEST if self.official_test else ACTION_OK_COMPETITION) if action else READ_OK
        if s.get("status") not in allowed or not s.get("strategies"):
            raise UIUnexpected(f"{s.get('status')}: {name} not usable for {'action' if action else 'read'}")
        for st in s["strategies"]:
            by = st.get("by")
            if by == "role":
                loc = self.page.get_by_role(st["role"], name=st.get("name"))
            elif by == "label":
                loc = self.page.get_by_label(st["label"])
            elif by == "text":
                loc = self.page.get_by_text(st["text"])
            elif by in ("attr", "css"):
                loc = self.page.locator(st.get("css") or f"[{st['attr']}]")
            else:
                continue
            try:
                if loc.count() > 0:
                    return loc.first
            except Exception:  # noqa: BLE001
                continue
        return None

    def _text(self, name: str) -> str | None:
        try:
            loc = self._locate(name)
        except UIUnexpected:
            return None
        return None if loc is None else (loc.inner_text(timeout=5000) or "").strip()

    # --- read-only ---------------------------------------------------------------------------------------------
    def open_portal(self):
        self.page.goto(self.url, wait_until="networkidle", timeout=60000)

    def check_login(self, settle_s: float = 20.0) -> str:
        """LOGGED_IN: on the portal host with the 文件繳交 navigation visible. LOGIN_REQUIRED: redirected off the portal
        host (SSO hand-off / main-site login form) or a login path / marker. Waits for the SPA to settle; the login
        form is never filled (the Owner logs in manually)."""
        from urllib.parse import urlparse
        portal_host = urlparse(self.url).netloc
        frags = self.adapter.get("login_url_markers") or [self.adapter.get("login_path_fragment") or "/login"]
        end = time.monotonic() + settle_s
        while True:
            u = urlparse(self.page.url)
            if u.netloc and u.netloc != portal_host:
                return "LOGIN_REQUIRED"
            if any(f in u.path for f in frags) or self._locate("login_required_marker") is not None:
                return "LOGIN_REQUIRED"
            if self._locate("nav_docs_link") is not None:
                return "LOGGED_IN"
            if time.monotonic() >= end:
                return "UNKNOWN"
            time.sleep(1.0)

    def safe_url(self) -> str:
        """URL without query / fragment (SSO state parameters are never written to evidence)."""
        from urllib.parse import urlparse
        u = urlparse(self.page.url)
        return f"{u.scheme}://{u.netloc}{u.path}"

    def _dialogs(self) -> list[str]:
        try:
            d = self.page.get_by_role("dialog")
            return [(d.nth(i).inner_text(timeout=3000) or "").strip()[:300] for i in range(d.count())]
        except Exception:  # noqa: BLE001
            return []

    def read_window_status(self) -> str:
        body = self.page.inner_text("body", timeout=10000)
        if any(m in body for m in wording_markers(self.adapter, "window_closed") + wording_markers(self.adapter, "rehearsal_closed")):
            return "CLOSED"
        return "UNKNOWN"          # an explicit OPEN marker is PENDING_REAL_E2E_WORDING

    def read_page_state(self) -> dict:
        known = wording_markers(self.adapter, "known_modals")
        dialogs = self._dialogs()
        unexpected = [d for d in dialogs if not any(k in d for k in known)]
        return {"url": self.safe_url(), "title": self.page.title(), "login": self.check_login(),
                "window_status": self.read_window_status(), "dialogs": dialogs, "unexpected_dialogs": unexpected}

    def read_team_id(self) -> str | None:
        return self._text("team_id")

    def read_trade_date(self) -> str | None:
        t = self._text("trade_date")
        if not t:
            return None
        import re
        m = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", t)
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None

    def read_attempts(self) -> tuple[int | None, int | None]:
        t = self._text("attempt_count")
        if not t:
            return None, None
        import re
        nums = [int(x) for x in re.findall(r"\d+", t)]
        return (nums[0], nums[1]) if len(nums) >= 2 else (None, None)   # exact layout: PENDING_REAL_E2E_SELECTOR

    def read_history(self) -> list[dict]:
        try:
            rows = self._locate("history_rows")
        except UIUnexpected:
            return []
        if rows is None:
            return []
        loc = self.page.locator(self._sel("history_rows")["strategies"][0].get("css", "tr"))
        acc, rej = wording_markers(self.adapter, "history_accepted"), wording_markers(self.adapter, "history_rejected")
        out = []
        for i in range(loc.count()):
            text = (loc.nth(i).inner_text(timeout=3000) or "").strip()
            out.append({"text": text[:500], "accepted": any(m in text for m in acc), "rejected": any(m in text for m in rej)})
        return out

    def read_strategy_document_status(self) -> str | None:
        return self._text("strategy_document_status")

    # --- actions (guarded) -------------------------------------------------------------------------------------
    def upload_file(self, path: Path):
        inp = self._locate("dplan_file_input", action=True)
        if inp is None:
            raise UIUnexpected("DPLAN_FILE_INPUT_NOT_FOUND")
        inp.set_input_files(str(path))
        if self._sel("upload_button").get("status") not in PENDING:
            btn = self._locate("upload_button", action=True)
            if btn is None:
                raise UIUnexpected("UPLOAD_BUTTON_NOT_FOUND")
            btn.click()

    def wait_for_server_validation(self, timeout_s: float):
        panel = self._locate("validation_result_panel")
        if panel is None:
            raise UIUnexpected("VALIDATION_PANEL_NOT_FOUND")
        panel.wait_for(state="visible", timeout=int(timeout_s * 1000))

    def read_validation_result(self) -> tuple[str, str]:
        text = self._text("validation_result_panel") or ""
        return classify(text, self.adapter, "validation_pass", "validation_fail"), text

    def submit(self):
        st = self.read_page_state()
        if st["unexpected_dialogs"]:
            raise UIUnexpected(f"UNEXPECTED_MODAL {st['unexpected_dialogs'][:1]}")
        btn = self._locate("submit_button", action=True)
        if btn is None or not btn.is_enabled():
            raise UIUnexpected("SUBMIT_BUTTON_NOT_AVAILABLE")
        btn.click()
        if self._sel("submit_confirmation_modal").get("status") not in PENDING:
            if self._locate("submit_confirmation_modal") is not None:
                c = self._locate("submit_confirm_button", action=True)
                if c is None:
                    raise UIUnexpected("SUBMIT_CONFIRM_BUTTON_NOT_FOUND")
                c.click()

    def read_submit_result(self) -> tuple[str, str]:
        body = self.page.inner_text("body", timeout=10000)
        if any(m in body for m in wording_markers(self.adapter, "submit_success")):
            return "OK", next(m for m in wording_markers(self.adapter, "submit_success") if m in body)
        for k in ("window_closed", "attempt_limit", "auth_loop"):
            for m in wording_markers(self.adapter, k):
                if m in body:
                    return "FAIL", m
        return "UNKNOWN", ""

    def verify_acceptance(self, file_name: str, sha256: str, trade_date: str, timeout_s: float, poll_s: float) -> list[dict]:
        end = time.monotonic() + timeout_s
        while True:
            rows = [r for r in self.read_history() if r.get("accepted") and (file_name in r["text"] or trade_date in r["text"])]
            if rows or time.monotonic() >= end:
                return rows
            time.sleep(poll_s)
            self.page.reload(wait_until="networkidle")

    def capture_evidence(self, tag: str) -> list[str]:
        d = self.evidence_dir / datetime.now(TPE).strftime("%Y%m%d")
        d.mkdir(parents=True, exist_ok=True)
        stem = f"{datetime.now(TPE):%H%M%S}_{tag}"
        shot, txt = d / f"{stem}.png", d / f"{stem}.txt"
        try:
            self.page.screenshot(path=str(shot), full_page=True)
            txt.write_text(self.page.inner_text("body", timeout=10000), encoding="utf-8")
        except Exception:  # noqa: BLE001
            return []
        return [str(shot), str(txt)]

    def close(self):
        try:
            self.ctx.close()
        finally:
            self._pw.stop()


# ----------------------------------------------------------------------------- read-only discovery
def discover(*, wait_login_s: int = 0, headless: bool = False, ops_cfg: dict | None = None) -> dict:
    out_dir = ROOT / "data" / "portal_discovery" / datetime.now(TPE).strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    drv = PlaywrightPortalDriver(ops_cfg, headless=headless, evidence_dir=out_dir)
    try:
        drv.open_portal()
        login = drv.check_login()
        end = time.monotonic() + wait_login_s
        while login != "LOGGED_IN" and time.monotonic() < end:
            time.sleep(5)                                  # the Owner logs in manually in the opened window
            login = drv.check_login()
        if login == "LOGGED_IN":
            drv.open_portal()
        state = drv.read_page_state()
        page = drv.page
        visible = {}
        for role in ("button", "link", "heading", "tab", "table", "dialog"):
            try:
                loc = page.get_by_role(role)
                visible[role] = sorted({(loc.nth(i).inner_text(timeout=2000) or "").strip()[:80]
                                        for i in range(min(loc.count(), 60))} - {""})
            except Exception:  # noqa: BLE001
                visible[role] = []
        try:
            file_inputs = page.locator("input[type=\"file\"]")
            inputs = [{"accept": file_inputs.nth(i).get_attribute("accept"), "name": file_inputs.nth(i).get_attribute("name")}
                      for i in range(file_inputs.count())]
        except Exception:  # noqa: BLE001
            inputs = []
        resolves = {}
        for name in (drv.adapter.get("selectors") or {}):
            try:
                resolves[name] = "RESOLVES" if drv._locate(name) is not None else "NOT_FOUND"
            except UIUnexpected as e:
                resolves[name] = str(e).split(":")[0]
        res = {"captured_at": datetime.now(TPE).isoformat(), "login": login, "page_state": state,
               "visible_by_role": visible, "file_inputs": inputs, "adapter_resolution": resolves,
               "read": {"team_id": drv.read_team_id(), "trade_date": drv.read_trade_date(),
                        "attempts": drv.read_attempts(), "history_rows": len(drv.read_history()),
                        "strategy_document_status": drv.read_strategy_document_status()},
               "evidence": drv.capture_evidence("discovery"), "out_dir": str(out_dir),
               "note": "READ-ONLY discovery: nothing uploaded or submitted; local only (gitignored)"}
    finally:
        drv.close()
    (out_dir / "page_state.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    d = sp.add_parser("discover")
    d.add_argument("--wait-login", type=int, default=0, help="seconds to wait for the Owner's manual login")
    d.add_argument("--headless", action="store_true")
    sp.add_parser("inventory")
    a = ap.parse_args(argv)
    if a.cmd == "inventory":
        print(json.dumps(selector_inventory(load_adapter()), ensure_ascii=False, indent=1))
        return 0
    try:
        r = discover(wait_login_s=a.wait_login, headless=a.headless)
    except UIUnexpected as e:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps({k: r[k] for k in ("login", "adapter_resolution", "read", "out_dir")}, ensure_ascii=False, indent=1,
                     default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
