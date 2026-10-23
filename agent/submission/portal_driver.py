"""Official portal browser driver (Issue #4) — normal browser automation of the human UI.

The driver operates the real page in a PERSISTENT browser profile (system Microsoft Edge via Playwright) that the
Owner logs into interactively. It never types credentials, never reads cookies / storage / tokens, never calls the
portal's private /api, never bypasses SSO / MFA / CAPTCHA. Selectors and official wording come only from
config/portal_adapter.yaml; anything not confirmed there is unusable (UIUnexpected -> the runner fails closed).

    .venv\\Scripts\\python.exe -m agent.submission.portal_driver discover [--wait-login 300] [--headless]
        read-only: open the portal, wait for the Owner's manual login (optional), capture the page state
        (url, title, visible elements by role with accessible name / id / data-* attributes, tables, alerts,
        file inputs, which adapter selectors resolve, screenshot, page text) into data/portal_discovery/<timestamp>/
        (local only, gitignored). Never uploads, never clicks.
    .venv\\Scripts\\python.exe -m agent.submission.portal_driver readonly-test [--headless]
        read-only real-portal test: open -> login -> Team ID -> trade date -> window -> attempts -> history ->
        strategy document -> evidence. Prints PORTAL_READONLY_REAL_TEST = PASS | FAIL. Never uploads / submits.
    .venv\\Scripts\\python.exe -m agent.submission.portal_driver inventory
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
PENDING = ("PENDING_WINDOW_ONLY", "PENDING_REAL_E2E_SELECTOR", "PENDING_REAL_E2E_WORDING")
ALL_STATUSES = READ_OK | set(PENDING) | {"CONFIRMED_PUBLIC_BUNDLE"}


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


def classify_login(url: str, portal_host: str, *, nav_visible: bool, login_marker_visible: bool,
                   adapter: dict) -> str:
    """LOGGED_IN: on the portal host with the portal navigation and no login marker. LOGIN_REQUIRED: the login FORM
    (login_url_markers, e.g. /login) or the portal's login marker. IN_TRANSIT: an SSO hop (sso_hop_markers, e.g.
    /sso) or another page while redirects settle -- a logged-in session also passes through the SSO hop, so the hop
    alone never means logged out (observed 2026-10-23)."""
    from urllib.parse import urlparse
    u = urlparse(url or "")
    forms = adapter.get("login_url_markers") or [adapter.get("login_path_fragment") or "/login"]
    hops = adapter.get("sso_hop_markers") or []
    if any(u.path.rstrip("/").endswith(f.rstrip("/")) for f in forms):
        return "LOGIN_REQUIRED"
    if u.netloc == portal_host:
        if login_marker_visible:
            return "LOGIN_REQUIRED"
        if nav_visible:
            return "LOGGED_IN"
        return "IN_TRANSIT"
    if any(h in u.path for h in hops):
        return "IN_TRANSIT"
    return "IN_TRANSIT"


def parse_attempts(text: str | None) -> tuple[int | None, int | None]:
    """'今日已繳交 0 / 25 次' (observed 2026-10-23) -> (used 0, remaining 25). Anything else -> (None, None)."""
    import re
    m = re.search(r"已繳交\s*(\d+)\s*/\s*(\d+)\s*次", text or "")
    if not m:
        return None, None
    used, limit = int(m.group(1)), int(m.group(2))
    return used, max(limit - used, 0)


def parse_trade_date(text: str | None) -> str | None:
    """'本次繳交對應交易日 2026-10-27 · ...' -> '2026-10-27'; '本次繳交對應交易日 — · 目前沒有開放中的繳交窗口' -> None."""
    import re
    m = re.search(r"對應交易日\s*(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", text or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def parse_doc_status(text: str | None, adapter: dict) -> str | None:
    """Strategy-document section text -> the verbatim status marker found (e.g. 未繳交), else None."""
    for m in wording_markers(adapter, "strategy_doc_status_values"):
        if m in (text or ""):
            return m
    return None


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

    # names used by the operations brief (aliases of the methods above; same behaviour)
    def read_window_state(self) -> str:
        return self.read_window_status()

    def read_strategy_doc_status(self) -> str | None:
        return self.read_strategy_document_status()

    def detect_unexpected_modal(self) -> list[str]:
        return list(self.read_page_state().get("unexpected_dialogs") or [])

    def detect_error_banner(self) -> list[str]:
        return []

    def wait_upload_complete(self, timeout_s: float):
        return None

    def wait_server_validation(self, timeout_s: float):
        return self.wait_for_server_validation(timeout_s)

    def capture_screenshot(self, tag: str) -> str | None:
        return next((x for x in self.capture_evidence(tag) if str(x).endswith(".png")), None)

    def capture_page_text(self, tag: str) -> str | None:
        return next((x for x in self.capture_evidence(tag) if str(x).endswith(".txt")), None)


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
                loc = self.page.get_by_text(st["text"], exact=bool(st.get("exact")))
            elif by == "text_regex":
                import re
                loc = self.page.get_by_text(re.compile(st["pattern"]))
            elif by == "anchor_ancestor":                 # section around a stable visible heading text
                loc = self.page.get_by_text(st["text"], exact=True)
                for _ in range(int(st.get("levels", 1))):
                    loc = loc.locator("..")
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

    def check_login(self, settle_s: float = 30.0) -> str:
        """Waits for redirects to settle (SSO hop -> portal), then classify_login(). The login form is never filled
        (the Owner logs in manually). Still in transit after `settle_s` -> UNKNOWN (fail closed)."""
        from urllib.parse import urlparse
        portal_host = urlparse(self.url).netloc
        end = time.monotonic() + settle_s
        while True:
            st = classify_login(self.page.url, portal_host, nav_visible=self._visible("nav_docs_link"),
                                login_marker_visible=self._visible("login_required_marker"), adapter=self.adapter)
            if st != "IN_TRANSIT":
                return st
            if time.monotonic() >= end:
                return "UNKNOWN"
            time.sleep(1.0)

    def _visible(self, name: str) -> bool:
        try:
            loc = self._locate(name)
            return loc is not None and loc.is_visible()
        except Exception:  # noqa: BLE001
            return False

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
        closed = wording_markers(self.adapter, "no_open_window") + wording_markers(self.adapter, "window_closed")
        if any(m in body for m in closed):
            return "CLOSED"
        return "UNKNOWN"          # an explicit OPEN marker is PENDING_WINDOW_ONLY (never inferred)

    def read_rehearsal_status(self) -> str:
        body = self.page.inner_text("body", timeout=10000)
        return "REHEARSAL_OPEN" if any(m in body for m in wording_markers(self.adapter, "rehearsal_open")) else "NO"

    def read_page_state(self) -> dict:
        known = wording_markers(self.adapter, "known_modals")
        dialogs = self._dialogs()
        unexpected = [d for d in dialogs if not any(k in d for k in known)]
        return {"url": self.safe_url(), "title": self.page.title(), "login": self.check_login(),
                "window_status": self.read_window_status(), "dialogs": dialogs, "unexpected_dialogs": unexpected,
                "error_banners": self.detect_error_banner()}

    def detect_error_banner(self) -> list[str]:
        """Visible alert / status texts that carry a CONFIRMED official error wording (verbatim)."""
        try:
            body = self.page.inner_text("body", timeout=10000)
        except Exception:  # noqa: BLE001
            return []
        keys = ("window_closed", "rehearsal_closed", "attempt_limit", "auth_loop", "file_too_large")
        return [m for k in keys for m in wording_markers(self.adapter, k) if m in body]

    def wait_upload_complete(self, timeout_s: float):
        """The upload is complete when the validation panel appears (the portal validates on upload)."""
        return self.wait_for_server_validation(timeout_s)

    def capture_screenshot(self, tag: str) -> str | None:
        d = self._evidence_day()
        shot = d / f"{datetime.now(TPE):%H%M%S}_{tag}.png"
        self.page.screenshot(path=str(shot), full_page=True)
        return str(shot)

    def capture_page_text(self, tag: str) -> str | None:
        d = self._evidence_day()
        txt = d / f"{datetime.now(TPE):%H%M%S}_{tag}.txt"
        txt.write_text(self.page.inner_text("body", timeout=10000), encoding="utf-8")
        return str(txt)

    def _evidence_day(self) -> Path:
        d = self.evidence_dir / datetime.now(TPE).strftime("%Y%m%d")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def read_team_id(self) -> str | None:
        return self._text("team_id")

    def read_trade_date(self) -> str | None:
        return parse_trade_date(self._text("trade_date"))

    def read_attempts(self) -> tuple[int | None, int | None]:
        return parse_attempts(self._text("attempt_count"))

    def read_history(self) -> list[dict]:
        try:
            rows = self._locate("history_rows")
        except UIUnexpected:
            return []
        if rows is None:
            return []
        loc = self.page.locator(self._sel("history_rows")["strategies"][0].get("css", "tr"))
        acc, rej = wording_markers(self.adapter, "history_accepted"), wording_markers(self.adapter, "history_rejected")
        empty = wording_markers(self.adapter, "history_empty")
        out = []
        for i in range(loc.count()):
            text = (loc.nth(i).inner_text(timeout=3000) or "").strip()
            if not text or any(m in text for m in empty):        # the empty-state row is not a submission
                continue
            out.append({"text": text[:500], "accepted": any(m in text for m in acc), "rejected": any(m in text for m in rej)})
        return out

    def read_strategy_document_status(self) -> str | None:
        return parse_doc_status(self._text("strategy_document_status"), self.adapter)

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
        """The 檢核結果 panel is always on the page (「待上傳」 before any upload; observed 2026-10-23), so visibility
        proves nothing: wait until its text carries a CONFIRMED pass or fail marker. Pass wording still pending ->
        a passing file times out -> MANUAL_CHECK_REQUIRED (fail closed, never a guessed PASS)."""
        if self._locate("validation_result_panel") is None:
            raise UIUnexpected("VALIDATION_PANEL_NOT_FOUND")
        end = time.monotonic() + timeout_s
        while True:
            if self.read_validation_result()[0] in ("PASS", "FAIL"):
                return
            if time.monotonic() >= end:
                raise TimeoutError(f"no confirmed validation result within {timeout_s:.0f}s")
            time.sleep(1.0)

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
        out = []
        for f in (self.capture_screenshot, self.capture_page_text):
            try:
                out.append(f(tag))
            except Exception:  # noqa: BLE001 - evidence capture never changes the outcome
                pass
        return [x for x in out if x]

    def close(self):
        try:
            self.ctx.close()
        finally:
            self._pw.stop()


# ----------------------------------------------------------------------------- read-only discovery
_ATTRS_JS = """e => ({tag: e.tagName.toLowerCase(), id: e.id || null, name: e.getAttribute('name'),
  type: e.getAttribute('type'), accept: e.getAttribute('accept'), role: e.getAttribute('role'),
  aria_label: e.getAttribute('aria-label'), disabled: !!e.disabled,
  data: Object.fromEntries([...e.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])),
  text: (e.innerText || '').trim().slice(0, 120)})"""   # never e.value: no form values are read


_ANCESTORS_JS = """e => { const out = []; let n = e;
  for (let i = 0; n && i < 4; i++, n = n.parentElement) {
    out.push({level: i, tag: n.tagName.toLowerCase(), id: n.id || null, role: n.getAttribute('role'),
      data: Object.fromEntries([...n.attributes].filter(a => a.name.startsWith('data-')).map(a => [a.name, a.value])),
      text: (n.innerText || '').trim().slice(0, 300)}); }
  return out; }"""


def _attrs(loc) -> dict:
    """Structural attributes of one element (tag / id / name / aria / data-* / visible text). Read-only DOM
    inspection: never reads cookies, storage, tokens or form values of credential fields."""
    try:
        return loc.evaluate(_ATTRS_JS, timeout=2000)
    except Exception:  # noqa: BLE001
        return {}


def readonly_test(*, headless: bool = False, ops_cfg: dict | None = None, team_id: str | None = None) -> dict:
    """§6 read-only real-portal test. PASS = logged in, Team ID read and equal to the configured one, every read step
    ran without an exception and evidence was captured. Never uploads, never clicks submit."""
    ops_cfg = ops_cfg or load_ops_config()
    team_id = team_id or (ops_cfg.get("team") or {}).get("competition_team_id")
    out_dir = ROOT / "data" / "portal_discovery" / (datetime.now(TPE).strftime("%Y%m%d_%H%M%S") + "_readonly")
    out_dir.mkdir(parents=True, exist_ok=True)
    drv = PlaywrightPortalDriver(ops_cfg, headless=headless, evidence_dir=out_dir)
    steps: dict = {}
    try:
        for name, fn in (("open", drv.open_portal), ("login", drv.check_login), ("team_id", drv.read_team_id),
                         ("trade_date", drv.read_trade_date), ("window", drv.read_window_state),
                         ("attempts", drv.read_attempts), ("history", lambda: len(drv.read_history())),
                         ("strategy_document", drv.read_strategy_doc_status),
                         ("modals", drv.detect_unexpected_modal), ("error_banners", drv.detect_error_banner),
                         ("evidence", lambda: drv.capture_evidence("readonly_test"))):
            try:
                steps[name] = {"ok": True, "value": fn()}
            except Exception as e:  # noqa: BLE001
                steps[name] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            if name == "login" and steps[name].get("value") != "LOGGED_IN":
                break
    finally:
        drv.close()
    logged_in = (steps.get("login") or {}).get("value") == "LOGGED_IN"
    ok = logged_in and all(v["ok"] for v in steps.values()) and (steps.get("team_id") or {}).get("value") == team_id \
        and bool((steps.get("evidence") or {}).get("value"))
    res = {"PORTAL_READONLY_REAL_TEST": "PASS" if ok else "FAIL", "login": (steps.get("login") or {}).get("value"),
           "expected_team_id": team_id, "steps": steps, "out_dir": str(out_dir),
           "note": "READ-ONLY: nothing uploaded or submitted; evidence local only (gitignored)"}
    (out_dir / "readonly_test.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str),
                                                encoding="utf-8")
    return res


def discover(*, wait_login_s: int = 0, headless: bool = False, ops_cfg: dict | None = None) -> dict:
    out_dir = ROOT / "data" / "portal_discovery" / datetime.now(TPE).strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    drv = PlaywrightPortalDriver(ops_cfg, headless=headless, evidence_dir=out_dir)
    try:
        drv.open_portal()
        login = drv.check_login()
        end = time.monotonic() + wait_login_s
        from urllib.parse import urlparse
        while login != "LOGGED_IN" and time.monotonic() < end:
            time.sleep(5)                                  # the Owner logs in manually in the opened window
            u = urlparse(drv.page.url)
            on_form = classify_login(drv.page.url, urlparse(drv.url).netloc, nav_visible=False,
                                     login_marker_visible=False, adapter=drv.adapter) == "LOGIN_REQUIRED"
            if not on_form and u.netloc != urlparse(drv.url).netloc:
                drv.open_portal()                          # logged in but landed on the main site: go back
            login = drv.check_login(settle_s=5)
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
            inputs = [_attrs(file_inputs.nth(i)) for i in range(file_inputs.count())]
        except Exception:  # noqa: BLE001
            inputs = []
        elements = {}
        for role in ("button", "link", "tab", "heading", "alert", "status", "dialog", "table", "row", "textbox",
                     "combobox", "checkbox"):
            try:
                loc = page.get_by_role(role)
                elements[role] = [_attrs(loc.nth(i)) for i in range(min(loc.count(), 80))]
            except Exception:  # noqa: BLE001
                elements[role] = []
        try:
            tables = page.locator("table")
            table_info = [{"headers": [(h or "").strip() for h in tables.nth(i).locator("th").all_inner_texts()][:20],
                           "rows": tables.nth(i).locator("tbody tr").count(),
                           "first_rows": [(r or "").strip()[:300] for r in
                                          tables.nth(i).locator("tbody tr").all_inner_texts()[:5]]}
                          for i in range(tables.count())]
        except Exception:  # noqa: BLE001
            table_info = []
        try:
            stable = page.locator("[data-testid], [data-test], [data-cy], [id]")
            stable_attrs = [_attrs(stable.nth(i)) for i in range(min(stable.count(), 150))]
        except Exception:  # noqa: BLE001
            stable_attrs = []
        anchors = {}
        for text in drv.adapter.get("discovery_anchors") or []:
            try:
                loc = page.get_by_text(text)
                anchors[text] = loc.first.evaluate(_ANCESTORS_JS, timeout=3000) if loc.count() else None
            except Exception:  # noqa: BLE001
                anchors[text] = None
        resolves = {}
        for name in (drv.adapter.get("selectors") or {}):
            try:
                resolves[name] = "RESOLVES" if drv._locate(name) is not None else "NOT_FOUND"
            except UIUnexpected as e:
                resolves[name] = str(e).split(":")[0]
        res = {"captured_at": datetime.now(TPE).isoformat(), "login": login, "page_state": state,
               "visible_by_role": visible, "elements": elements, "tables": table_info, "anchors": anchors,
               "stable_attributes": stable_attrs, "file_inputs": inputs, "adapter_resolution": resolves,
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
    r_ = sp.add_parser("readonly-test")
    r_.add_argument("--headless", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "inventory":
        print(json.dumps(selector_inventory(load_adapter()), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "readonly-test":
        try:
            r = readonly_test(headless=a.headless)
        except UIUnexpected as e:
            r = {"PORTAL_READONLY_REAL_TEST": "FAIL", "reason": str(e)}
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return 0 if r["PORTAL_READONLY_REAL_TEST"] == "PASS" else 2
    try:
        r = discover(wait_login_s=a.wait_login, headless=a.headless)
        if r.get("login") != "LOGGED_IN":
            print("LOGIN_REQUIRED: log in in the opened automation-profile window (use --wait-login 600)")
    except UIUnexpected as e:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(e)}, ensure_ascii=False))
        return 2
    print(json.dumps({k: r[k] for k in ("login", "adapter_resolution", "read", "out_dir")}, ensure_ascii=False, indent=1,
                     default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
