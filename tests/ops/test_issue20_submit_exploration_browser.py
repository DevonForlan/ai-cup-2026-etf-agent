"""Issue #20 (Owner Decision 2026-10-27, best-effort unattended submission): the REAL PlaywrightPortalDriver.submit()
bounded exploration against a LOCAL browser fixture that mirrors the portal structure seen on 2026-10-27
(檢核結果 panel, 送出繳交 button, verbatim wording). Never touches the real portal. Skipped when no local browser."""
import time
from pathlib import Path

import pytest

from agent.submission import portal_driver as PD

pw_api = pytest.importorskip("playwright.sync_api")

PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div id="notice"></div>
<section><div><span>檢核結果</span></div><div id="status">檢核通過，待送出</div>
<div>上傳即時檢查要項 · 送出後回報收件檢核</div><div>✓  收件層檢核全數通過</div>
<button id="submit" onclick="go()">送出繳交</button></section>
<script>
const MODE = "%MODE%";
function done(t){ document.getElementById('status').innerText = t || '已收件'; }
function go(){
  window.clicks = (window.clicks||0) + 1;
  if (MODE === 'none') return setTimeout(done, 300);
  if (MODE === 'native') { if (confirm('確定要送出本日 D-Plan 嗎？')) setTimeout(done, 300); return; }
  if (MODE === 'fail') return setTimeout(() => document.body.insertAdjacentHTML('beforeend',
       '<p>目前不在繳交窗口內，無法送出繳交。</p>'), 300);
  const labels = MODE === 'unknown' ? ['選項 A', '選項 B'] : ['取消', '確認送出'];
  const d = document.createElement('div'); d.setAttribute('role', 'dialog');
  d.innerHTML = '<p>確認送出本日 D-Plan？</p>' + labels.map(l => '<button>' + l + '</button>').join('');
  d.querySelectorAll('button').forEach(b => b.onclick = () => { window.dialogClick = b.innerText; d.remove();
       if (b.innerText === '確認送出') setTimeout(done, 300); });
  setTimeout(() => document.body.appendChild(d), 400);
}
if (MODE === 'notice') {
  const n = document.createElement('div'); n.setAttribute('role', 'dialog');
  n.innerHTML = '<p>系統公告：今晚 23:00 維護</p><button>我知道了</button>';
  n.querySelector('button').onclick = () => n.remove(); document.body.appendChild(n);
}
</script></body></html>"""


@pytest.fixture(scope="module")
def browser():
    with pw_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch(channel="msedge", headless=True)
        except Exception:  # noqa: BLE001
            try:
                b = pw.chromium.launch(headless=True)
            except Exception as e:  # noqa: BLE001
                pytest.skip(f"no local browser for the fixture ({type(e).__name__})")
        yield b
        b.close()


def _driver(browser, tmp_path, mode):
    html = tmp_path / f"portal_{mode}.html"
    html.write_text(PAGE.replace("%MODE%", "notice" if mode == "notice" else mode), encoding="utf-8")
    page = browser.new_page()
    page.goto(html.as_uri())
    d = PD.PlaywrightPortalDriver.__new__(PD.PlaywrightPortalDriver)
    d.adapter, d.page, d.official_test, d.evidence_dir, d.url = PD.load_adapter(), page, False, tmp_path / "ev", ""
    d.check_login = lambda *a, **k: "LOGGED_IN"
    return d


def _result(d, wait=3.0):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        r = d.read_submit_result()
        if r[0] != "UNKNOWN":
            return r
        time.sleep(0.2)
    return d.read_submit_result()


def test_dom_confirmation_dialog_is_explored_and_confirmed(browser, tmp_path):
    d = _driver(browser, tmp_path, "dialog")
    assert d.read_validation_result()[0] == "PASS"
    out = d.submit(explore_s=8)
    steps = [x["step"] for x in out["log"]]
    assert steps[0] == "clicked_submit" and "dialog" in steps and out["confirms"] == 1
    dlg = next(x for x in out["log"] if x["step"] == "dialog")
    assert dlg["clicked"] == "確認送出" and "取消" in dlg["buttons"] and "確認送出本日" in dlg["text"]
    assert _result(d) == ("OK", "已收件")
    assert d.page.evaluate("window.clicks") == 1                    # 送出繳交 pressed exactly once
    assert list((tmp_path / "ev").rglob("*submit_dialog_0*.png"))     # evidence of the explored dialog


def test_native_confirm_is_accepted_and_logged(browser, tmp_path):
    d = _driver(browser, tmp_path, "native")
    out = d.submit(explore_s=6)
    nat = [x for x in out["log"] if x["step"] == "native_dialog"]
    assert nat and nat[0]["accepted"] and "確定要送出" in nat[0]["message"]
    assert _result(d) == ("OK", "已收件")


def test_no_dialog_goes_straight_to_the_result(browser, tmp_path):
    d = _driver(browser, tmp_path, "none")
    out = d.submit(explore_s=6)
    assert out["confirms"] == 0 and _result(d) == ("OK", "已收件")


def test_unknown_dialog_is_captured_but_never_guessed(browser, tmp_path):
    d = _driver(browser, tmp_path, "unknown")
    out = d.submit(explore_s=5)
    dlg = next(x for x in out["log"] if x["step"] == "dialog")
    assert dlg["clicked"] is None and dlg["buttons"] == ["選項 A", "選項 B"] and out["confirms"] == 0
    assert d.page.evaluate("window.dialogClick || null") is None and d.read_submit_result()[0] == "UNKNOWN"


def test_failure_wording_ends_the_exploration(browser, tmp_path):
    d = _driver(browser, tmp_path, "fail")
    out = d.submit(explore_s=6)
    assert any(x.get("result") == "FAIL" for x in out["log"]) and d.read_submit_result()[0] == "FAIL"


def test_pre_submit_notice_dialog_is_dismissed_then_submitted(browser, tmp_path):
    d = _driver(browser, tmp_path, "notice")
    out = d.submit(explore_s=8)
    pre = [x for x in out["log"] if x["step"] == "pre_submit_dialog"]
    assert pre and pre[0]["clicked"] == "我知道了"
    assert out["confirms"] == 1 and _result(d) == ("OK", "已收件")


HISTORY = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<table><thead><tr><th>交易日</th><th>日期</th><th>每日上傳 JSON</th><th>繳交時間</th><th>回看</th></tr></thead><tbody>
<tr><td>第 2</td><td>2026-10-28</td><td>已繳交</td><td>2026-10-27 21:04</td><td><a onclick="rv('2026-10-28')">回看</a></td></tr>
<tr><td>第 1</td><td>2026-10-27</td><td>已繳交</td><td>2026-10-27 01:16</td><td><a onclick="rv('2026-10-27')">回看</a></td></tr>
</tbody></table>
<script>
function rv(d){
  const g = document.createElement('div'); g.setAttribute('role', 'dialog'); g.setAttribute('aria-label', '繳交內容回看');
  g.innerHTML = '<p>' + d + '</p><button>關閉</button><pre>{"trade_date": "' + d + '"}</pre>';
  g.querySelector('button').onclick = () => g.remove(); document.body.appendChild(g);
}
</script></body></html>"""


def test_review_picks_the_row_by_its_date_cell_not_the_submit_time(browser, tmp_path):
    """Real portal 2026-10-28: row 第 2 (trade date 10/28) was submitted 「2026-10-27 21:04」, so a text match on
    2026-10-27 hits two rows. 回看 must open the row whose 日期 cell is the trade date."""
    html = tmp_path / "history.html"
    html.write_text(HISTORY, encoding="utf-8")
    page = browser.new_page()
    page.goto(html.as_uri())
    d = PD.PlaywrightPortalDriver.__new__(PD.PlaywrightPortalDriver)
    d.adapter, d.page = PD.load_adapter(), page
    for t in ("2026-10-27", "2026-10-28"):
        r = d.open_review(t)
        assert r is not None and r["json_text"] == '{"trade_date": "' + t + '"}' and t in r["header"]
    assert d.open_review("2026-10-29") is None
