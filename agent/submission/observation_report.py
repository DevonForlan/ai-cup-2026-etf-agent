"""Issue #20: turn a read-only `portal_driver observe` capture into an adapter PROPOSAL for the window-only items.

    .venv\\Scripts\\python.exe -m agent.submission.observation_report data\\portal_discovery\\<ts>_observe

Reads observe.jsonl (local evidence) and writes adapter_proposal.md + adapter_proposal.json next to it: for each
window-only item (validation_pass, submit_confirmation_modal, submit_confirm_button, submit_success) the VERBATIM
texts the page showed, when they first appeared and the evidence files of that snapshot. It never edits
config/portal_adapter.yaml: a human picks the values from this evidence in a reviewed adapter PR
(docs/LIVE_OBSERVATION_1930.md). Texts already known in the adapter (pending / fail / window wording, the review
dialog) are left out, so only NEW wording is proposed; nothing is inferred.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ITEMS = ("validation_pass", "submit_confirmation_modal", "submit_confirm_button", "submit_success")
KNOWN_WORDING = ("validation_pending", "validation_not_uploaded", "validation_fail", "instant_check_note",
                 "window_closed", "window_closed_inline", "no_open_window", "rehearsal_not_collected",
                 "history_submitted", "dplan_status_values")
REVIEW_DIALOG = "繳交內容回看"


def load(out_dir: Path) -> list[dict]:
    p = Path(out_dir) / "observe.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def _known(adapter: dict) -> list[str]:
    from agent.submission.portal_driver import wording_markers
    return [m for k in KNOWN_WORDING for m in wording_markers(adapter, k)]


def _is_known(text: str, known: list[str]) -> bool:
    t = (text or "").strip()
    return not t or any(m and (t == m or m in t) for m in known)


def _first(found: dict, text: str, snap: dict, **extra) -> None:
    if text and text not in found:
        found[text] = {"text": text, "first_seen": snap.get("at"), "evidence": snap.get("evidence") or [], **extra}


def _buttons(snap: dict) -> set[str]:
    return {(b.get("text") or "").strip() for b in snap.get("buttons") or [] if (b.get("text") or "").strip()}


def candidates(snaps: list[dict], adapter: dict) -> dict:
    """Pure: observe snapshots -> {item: [verbatim candidates]} + a timeline of the submit-relevant changes."""
    known = _known(adapter)
    out = {k: {} for k in ITEMS}
    timeline = []
    baseline = _buttons(snaps[0]) if snaps else set()
    prev = {}
    for s in snaps:
        if "native_dialog" in s:                                         # window.confirm / alert: recorded verbatim
            nd = s["native_dialog"]
            _first(out["submit_confirmation_modal"], nd.get("message") or "", s, kind=f"native {nd.get('type')}",
                   note="native browser dialog: CANCELLED by the observer (nothing submitted)")
            timeline.append({"at": s.get("at"), "event": "native_dialog", "detail": nd})
            continue
        panel = (s.get("validation_panel") or "").strip()
        if panel and not _is_known(panel, known):
            _first(out["validation_pass"], panel, s, kind="validation panel text (new wording)")
        dialogs = [d for d in s.get("dialogs") or [] if REVIEW_DIALOG not in d]
        for d in dialogs:
            _first(out["submit_confirmation_modal"], d, s, kind="role dialog / alertdialog")
            for b in sorted(_buttons(s) - baseline):                     # buttons present only with the dialog
                _first(out["submit_confirm_button"], b, s, kind="button that appeared with the dialog", dialog=d[:120])
        for a in s.get("alerts") or []:
            if not _is_known(a, known):
                _first(out["submit_success"], a.strip(), s, kind="alert / status region")
        for m in s.get("mutations") or []:
            t = (m.get("text") or "").strip()
            if t and not _is_known(t, known) and REVIEW_DIALOG not in t and len(t) <= 200 and \
                    m.get("kind") == "added" and m.get("role") in ("alert", "status", "dialog", "alertdialog", None):
                _first(out["submit_success"], t, s, kind=f"DOM text added ({m.get('tag')}, role {m.get('role')})")
        for key in ("submit_button", "dplan_status", "attempts", "window_status"):
            if key in s and s.get(key) != prev.get(key):
                timeline.append({"at": s.get("at"), "event": key, "value": s.get(key)})
        rows = [r.get("text") for r in s.get("history") or []]
        if "history" in s and rows != prev.get("_rows"):
            timeline.append({"at": s.get("at"), "event": "history", "value": rows})
            prev["_rows"] = rows
        prev.update({k: s.get(k) for k in ("submit_button", "dplan_status", "attempts", "window_status") if k in s})
    return {"items": {k: list(v.values()) for k, v in out.items()}, "timeline": timeline,
            "snapshots": len(snaps)}


def render(out_dir: Path, res: dict) -> str:
    lines = [f"# Adapter proposal from `{Path(out_dir).name}` (Issue #20)", "",
             "PROPOSAL ONLY: verbatim texts the real page showed during the Owner's manual upload / submit. Copy a value",
             "into `config/portal_adapter.yaml` only if it is clearly the item named here; cite this folder as `source`.",
             "If no dialog appeared between 送出繳交 and the success text, the dialog and its confirm button become",
             "`CONFIRMED_NOT_PRESENT` (both). Anything unclear stays PENDING (the runner then stays manual).", ""]
    for k in ITEMS:
        lines.append(f"## {k}")
        cs = res["items"][k]
        if not cs:
            lines += ["(nothing observed)", ""]
            continue
        for c in cs:
            extra = ", ".join(f"{x}: {c[x]}" for x in ("kind", "dialog", "note") if c.get(x))
            lines.append(f"- `{c['text'][:300]}`  — first seen {c['first_seen']} ({extra}); evidence: "
                         f"{', '.join(Path(e).name for e in c['evidence'][:2]) or 'n/a'}")
        lines.append("")
    lines.append("## Timeline")
    for t in res["timeline"]:
        lines.append(f"- {t['at']} {t['event']}: {json.dumps(t.get('value', t.get('detail')), ensure_ascii=False)[:300]}")
    return "\n".join(lines) + "\n"


def report(out_dir: str | Path, adapter: dict | None = None) -> dict:
    from agent.submission.portal_driver import load_adapter
    out_dir = Path(out_dir)
    res = candidates(load(out_dir), adapter or load_adapter())
    (out_dir / "adapter_proposal.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "adapter_proposal.md").write_text(render(out_dir, res), encoding="utf-8")
    return res


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("observe_dir")
    a = ap.parse_args(argv)
    res = report(a.observe_dir)
    print(json.dumps({k: len(v) for k, v in res["items"].items()} | {"snapshots": res["snapshots"],
                                                                     "proposal": str(Path(a.observe_dir) /
                                                                                     "adapter_proposal.md")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
