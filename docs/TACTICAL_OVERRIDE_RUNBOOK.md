# Tactical override runbook (Issue #43)

Owner directive 2026-11-08: temporary 1-trading-day non-tech rotation, entry trade date 2026-11-09, exit in the 2026-11-10 D-Plan.
Frozen Quant v1 (`config/strategy_quant_v1.yaml` sha256 `f34fa02e…23d2e0`) and all frozen paths are untouched.

## How it works
- `agent/tactical/hook.py` wraps `agent.pipeline.construct` inside `competition_day` only. The frozen constructor runs first; its result is replaced only on the entry date or when an open sleeve is due for unwinding.
- Spec: `config/tactical/tactical_override_20261109.yaml`, pinned by sha256 in `config/ops.yaml` (`tactical.spec_sha256`). A mismatch disables new entries. `.gitattributes` keeps the file LF so the pin is stable on Windows.
- Entry: sell tech pro rata to ~20 % NAV (lots, min order 0.15 % NAV), buy 6 non-tech names at equal TWD weight; built through the frozen `_finalize` compliance path (names, caps, cash, Active Share, stress), D-Plan validator, Active Share gate.
- Ledger `data/tactical/<id>/ledger.json` stores the pre-entry share count of every touched ticker plus signed unwind orders.
- Exit (expiry first): on any trade date >= exit date with a non-restored sleeve, targets are the pre-entry share counts (idempotent). Scales 1/.75/.5/.25 if a full unwind is not legal. `TACTICAL_UNWIND_OVERDUE` is flagged when the exit date has passed or the unwind is partial; it is never silently extended.
- Fail closed: any entry problem (Quant fallback, plan error, compliance failure, exception) keeps the pure Frozen Quant result.

## Rollback (one flag)
Set `tactical.enabled: false` in `config/ops.yaml` (or `enabled: false` in the spec and re-pin). Open sleeves are still unwound unless `unwind_even_if_disabled: false`.

## 2-day option
Set `hold_trading_days: 2` in the spec (exit 2026-11-11), re-pin the sha256 in `config/ops.yaml`, before the entry D-Plan is generated.

## Evidence
Research verdict was DO_NOT_ROTATE (OOS negative at every size); retained in the audit trail (Issue #43, branch `research/43-short-rotation`).
