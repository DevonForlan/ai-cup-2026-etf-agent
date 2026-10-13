"""Daily compliance summary (rule sync 2026-10-07/12). Read-only view over the D-Plan validation report:
it never decides anything and never changes the D-Plan."""
from __future__ import annotations

OK_RUN = ("READY_TO_SUBMIT", "DRY_RUN_OK", "HISTORICAL_OK")


def _status(checks: list[dict], *ids: str) -> str:
    sel = [c for c in checks if c["rule_id"] in ids or any(c["rule_id"].endswith(":" + i) for i in ids)]
    if not sel:
        return "N/A"
    if any(c["status"] == "FAIL" for c in sel):
        return "FAIL"
    if any(c["status"] in ("UNKNOWN", "ERROR") for c in sel):
        return "UNKNOWN"
    return "PASS"


def build(validation: dict, internal_target: float | None, llm: dict | None, llm_configured: bool) -> dict:
    checks = validation.get("checks") or []
    tsmc_fail = any(c["rule_id"].endswith("R_TSMC_CAP") and c["status"] == "FAIL" for c in checks)
    other = _status(checks, "R_OTHER_CAP")
    as_chk = next((c for c in checks if c["rule_id"] == "R_ACTIVE_SHARE"), None)
    as_val = None if as_chk is None else as_chk.get("actual")
    if as_chk is None or as_val is None:
        as_off, as_int = "UNKNOWN", "UNKNOWN"
    else:
        as_off = "FAIL" if as_chk["status"] == "FAIL" else "PASS"
        as_int = "PASS" if internal_target is None or float(as_val) >= internal_target else "WARN"
    llm = llm or {}
    claude = ("PASS" if llm.get("used") else "FALLBACK") if llm_configured else "TEMPLATE"
    out = {
        "Universe 150": _status(checks, "R_UNIVERSE"),
        "Holdings 20-30": _status(checks, "R_COUNT"),
        "2330 <= 25%": "FAIL" if tsmc_fail else ("PASS" if other != "N/A" else "N/A"),
        "Other stocks <= 10%": other,
        "Cash < 25%": _status(checks, "R_CASH_MAX", "R_CASH_NEG"),
        "Active Share official >= 15%": as_off + ("" if as_val is None else f" ({float(as_val):.2%})"),
        "Active Share internal safety target": as_int + ("" if internal_target is None else f" (target {internal_target:.0%})"),
        "Strategy consistency": _status(checks, "C12_FLOW", "C12_CASH", "C14"),
        "D-Plan validation": "PASS" if validation.get("ok") else "FAIL",
        "Manual override": "NO",          # no manual edit step exists; FINAL is the validated package file (sha256)
        "Claude runtime": claude,
    }
    return out


def overall(items: dict, run_status: str) -> str:
    bad = any(str(v).startswith("FAIL") for k, v in items.items() if k != "Claude runtime")
    return "READY" if run_status in OK_RUN and not bad else "BLOCKED"
