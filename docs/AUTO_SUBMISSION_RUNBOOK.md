# Production auto-submission runbook (Issue #20)

Owner Decision 2026-10-27 (Issue #20). Quant v1 is frozen and untouched. Submission is a **downstream, fail-closed**
layer: it only handles an existing, validated COMPETITION FINAL.

## Schedule

| Time | Task | What it does |
|---|---|---|
| 17:00 | `AI_CUP_Precompetition_Evaluation_1700` | Unchanged: paper evaluation only. Never touches FINAL or submission state. |
| 19:30 | `AI_CUP_Precompetition_DryRun_1930` | Unchanged prediction → FINAL → validation / compliance, then the downstream submission runner. Now runs under the production lock. |
| 07:30 | `AI_CUP_Competition_MorningFinal_0730` (new) | Lock → morning refresh → latest COMPETITION FINAL → supersede only if every gate passes before 08:30 → downstream submission runner. |

`automation/register_morning_final_task.ps1` registers the 07:30 task: daily, StartWhenAvailable, no wake, at most
85 minutes, so it ends by 08:55.

**Hard stops**
- **08:30:** no new investment decision; the existing FINAL may still be validated, uploaded, submitted and verified.
- **08:55:** no new upload or submit.

## Success = SUBMISSION_CONFIRMED (never "ACCEPTED")

The portal shows no "accepted" wording. `agent/submission/confirmation.py` confirms a submission read-only when **all**
of these hold:

1. **Submitted marker:** the history row's 每日上傳 JSON cell reads 已繳交.
2. **Unique row:** exactly one history row exists for T. Several rows → `AMBIGUOUS`, and the run fails closed.
3. **Trade date:** the review header and the JSON `trade_date` both equal T.
4. **Team:** the page Team ID and the JSON `team_id` both equal `TEAM_11442`.
5. **Review content:** 「回看」 (the review dialog `繳交內容回看`) returns JSON that equals the active FINAL. The portal
   re-orders keys, so the parsed content is compared, not the file bytes.
6. **No failure markers:** no rejection wording and no 檢核 failure wording (`文件檢查未通過`).

Selectors and wording come only from `config/portal_adapter.yaml`. The Issue #20 entries are `CONFIRMED_REAL_E2E` from
read-only discovery on 2026-10-27 (local evidence under `data/portal_discovery/`).

## Runner rules (`agent/submission/auto_upload.py`)

| Rule | Behaviour |
|---|---|
| Gate | Requires all of: COMPETITION, Team ID, trade date, one active FINAL with a verified SHA, local validation and compliance PASS, Quant fingerprint, window open and before 08:55, the manual-E2E prerequisite, and `auto_upload.enabled` with `method: browser`. |
| Idempotency | Key = trade_date + TEAM_ID + FINAL_SHA. A confirmed local receipt stops the run before the browser starts. A portal history row whose 回看 content equals the FINAL also stops it (`ALREADY_SUBMITTED`). |
| Unknown submit result | Read-only verification only; the runner never clicks submit a second time. An exception after the 送出繳交 click is recorded as `submitted` / `SUBMIT_RESULT_UNKNOWN` and verified read-only. A later run in the `SUBMITTED` state only verifies, and the 07:30 run makes no new decision for it. |
| Existing portal row | A history row for T that is not this FINAL, or whose 回看 cannot be read, fails closed (`HISTORY_ROW_EXISTS_UNCONFIRMED`): nothing is uploaded or submitted over it. |
| Submit flow | 送出繳交 is pressed only when `portal_driver.submit_flow_pending()` is empty: `validation_pass`, `submit_confirmation_modal`, `submit_confirm_button` and `submit_success` are all confirmed from a live observation. Otherwise the run stops after `SERVER_VALIDATED` with `SUBMIT_FLOW_UNCONFIRMED` and the Owner submits by hand. |
| Retry | At most `max_automated_attempts` (3) per date, and only for the same SHA. Each run re-checks receipts, portal history, the FINAL SHA and the clock. |
| Lock | `logs/locks/submission_<ymd>.lock` covers the runner. `logs/locks/competition_production.lock` is shared by 19:30 and 07:30. A held lock gives `LOCK_UNAVAILABLE`, and the run stops. |
| Status | `PREDICTION_STATUS` and `SUBMISSION_STATUS` are separate. A blocked submission never fails the prediction. |
| Fail closed | Anything unknown, mismatched or missing → `SUBMISSION_STATUS = BLOCKED` and `MANUAL_ACTION_REQUIRED` (`data/submission_evidence/<ymd>/MANUAL_UPLOAD_REQUIRED.json`). |

**Still unconfirmed (stays fail-closed):**
- The official 檢核 *pass* wording (`validation_pass`).
- The submit confirmation modal and its confirm button.
- The submit success text.

These appear only during an upload / submit in an open window. Until they are captured, an automated run uploads the
file, saves the 檢核 panel evidence, and stops before 送出繳交 with `MANUAL_UPLOAD_REQUIRED`. Never guess them: add them
to the adapter only from real evidence, in a reviewed PR. See `docs/LIVE_OBSERVATION_1930.md` for the live capture
(`portal_driver observe`) and the adapter-update path (`agent.submission.observation_report`).

## The 07:30 supersede rule (`agent/ops/morning_final.py`)

The morning candidate replaces the evening FINAL only when **all** of these hold:
- the run is for the same T and in competition mode;
- the run status is `READY_TO_SUBMIT`;
- `final_action` is `KEPT_DIFFERENT`;
- data health, validation and every compliance item are PASS;
- the time is before 08:30.

The replacement uses `final.replace_final` with operator `morning_final_0730`. It records the prior and new SHA, the
reason and the evidence (`logs/morning/supersede.jsonl`, `final_history.jsonl`), so there is exactly one active FINAL.

Before replacing, a read-only portal check (`morning_final.portal_clear`) must show no submission row for T. A row, or
an unknown portal state, keeps the evening FINAL.

When T is already SUBMISSION_CONFIRMED, the 07:30 run makes no new decision; `competition_day` refuses one anyway.
When T is `SUBMITTED` (result unknown), it makes no new decision either and only verifies.

## Commands

```
# read-only check of a trade date (optionally record the MANUAL receipt with the confirmation)
.venv\Scripts\python.exe -m agent.submission.confirmation verify --date 2026-10-27 [--record-manual --confirmed-by "Owner"]
# submission gate only (no browser)
.venv\Scripts\python.exe -m agent.submission.auto_upload --date T --check
# manual morning run
.\automation\run_morning_final.ps1
```

## Post-merge sequence (Owner merges; Claude Code never merges)

After **#21** is merged:

1. In the project folder: `git checkout master` and `git pull --ff-only`.
2. Check `git rev-parse HEAD` == `git rev-parse origin/master`, and that `git status --short` is empty.
3. Record the Day-1 manual submission (read-only portal check plus a local receipt):

   ```
   .venv\Scripts\python.exe -m agent.submission.confirmation verify --date 2026-10-27 --record-manual --confirmed-by "Owner (manual upload 2026-10-27 01:16)"
   ```

   Expected: `"status": "SUBMISSION_CONFIRMED"`, all 8 checks `true`, `"receipt_state": "SUBMISSION_CONFIRMED"`.
4. Check the gate prerequisite:

   ```
   .venv\Scripts\python.exe -c "from agent.ops.common import load_ops_config as L; from agent.submission.auto_upload import manual_e2e_evidence as E; print(E(L()))"
   ```

   Expected: `completed: True`, evidence 2026-10-27 `sha256:19ee7df7…cb921`.
5. Scheduler check: `Get-ScheduledTask -TaskName AI_CUP_* | Get-ScheduledTaskInfo`. Expect 17:00 / 19:30 unchanged, and
   07:30 `AI_CUP_Competition_MorningFinal_0730` with its next run at 07:30. `automationun_morning_final.ps1` now exists
   in the project folder.

After **#22** is merged:

6. `git pull --ff-only`, then check `local master == origin/master` and a clean tree.
7. `config/ops.yaml`: `auto_upload.enabled: true`, `method: browser`.
8. Once the 19:30 FINAL for T exists: `.venv\Scripts\python.exe -m agent.submission.auto_upload --date T --check`.
   Expected failures are only time-related (`WINDOW_NOT_OPEN` before 19:30). `MANUAL_E2E_NOT_COMPLETED`,
   `AUTO_UPLOAD_DISABLED`, `TEAM_ID_MISMATCH`, `QUANT_FREEZE_FAIL`, `LOCAL_VALIDATION_*` or `SHA_MISMATCH` are blockers;
   report them.
