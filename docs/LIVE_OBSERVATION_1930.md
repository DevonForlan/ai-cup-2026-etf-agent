# 19:30 live observation → adapter update (Issue #20)

Four portal elements exist only while a submission window is open, during an upload or submit:

| Adapter item | What it is | Needed for |
|---|---|---|
| `validation_pass` (wording) | the 檢核結果 text after a file that **passes** the instant check | recognising `SERVER_VALIDATED` |
| `submit_confirmation_modal` (selector) | the dialog after pressing 送出繳交, or `CONFIRMED_NOT_PRESENT` if none appears | the submit step |
| `submit_confirm_button` (selector) | the confirm button in that dialog, or `CONFIRMED_NOT_PRESENT` together with the dialog | the submit step |
| `submit_success` (wording) | the success text after a submit | the submit result |

They are `PENDING_WINDOW_ONLY`. While any one is pending, `portal_driver.submit_flow_pending()` blocks the submit
step:
- the runner never presses 送出繳交 → `SUBMISSION_STATUS = BLOCKED`, `MANUAL_ACTION_REQUIRED = YES`;
- `PREDICTION_STATUS` is unaffected.

Values come **only** from the evidence below. Never guess them.

## Tonight, step by step

1. **19:30, scheduled run** (unchanged): prediction → FINAL → validation / compliance → submission stage.
   - With #21 and #22 merged, the runner uploads the FINAL and waits 60 s for 檢核結果. It cannot recognise *pass*
     yet, so it stops with `FAIL_CLOSED · MANUAL_CHECK_REQUIRED: VALIDATION_TIMEOUT` and saves a screenshot and the
     page text (`data/submission_evidence/20261028/`). That page text is the first evidence of the 檢核 pass wording.
   - With #22 not merged, the stage is `DISABLED → MANUAL_UPLOAD_REQUIRED` (nothing uploaded).
   - Either way it never presses 送出繳交.
2. **Wait for the run to finish:** `logs\scheduled\latest_status.json` has `finished_at` and `submission_status`. On master
   before #21 is merged, the field is `auto_upload_status`. The observer refuses to start
   (`BUSY`) while the run holds the browser profile.
3. **Start the observer** (read-only: it never clicks, types or uploads):
   - after #21 is merged, from the project folder:
     `.venv\Scripts\python.exe -m agent.submission.portal_driver observe --minutes 30`
   - before #21 is merged, from `.worktrees\issue-20`:
     `..\..\.venv\Scripts\python.exe -m agent.submission.portal_driver observe --minutes 30 --root "C:\Users\devon.tseng\Desktop\個人\AI CUP 2026玉山人工智慧公開挑戰賽"`

   An Edge window opens with the automation profile (already logged in).
4. **In that window, by hand:**
   1. Check 本次繳交對應交易日 = 2026-10-28 and TEAM_11442.
   2. Upload **only** the FINAL named in `data\submission_evidence\20261028\MANUAL_UPLOAD_REQUIRED.json` (check its SHA
      there).
   3. Wait for 檢核結果. Press 送出繳交 only if it passed.
   4. If a dialog appears, read it and confirm.
   5. Wait for the success text and the new history row, then optionally open 「回看」 and 關閉.

   **Native browser dialog:** if the page uses a native `confirm()` box, the observer records its text and
   **cancels** it (Playwright cannot hand it to you), so nothing is submitted. Then submit in your normal browser as on
   Day 1. The recorded text is still the evidence.
5. **Stop:** let the timer run out, or press Ctrl+C (the summary is still written). Output:
   `data\portal_discovery\<ts>_observe\observe.jsonl`, `observe_summary.json`, screenshots and page text (local only).
6. **Record the submission** (after #21 is merged; read-only check plus a local receipt):
   `.venv\Scripts\python.exe -m agent.submission.confirmation verify --date 2026-10-28 --record-manual --confirmed-by "Owner (manual upload 2026-10-27 HH:MM)"`

   This makes 10/28 `SUBMISSION_CONFIRMED` locally, so the 07:30 run makes no new decision. If it is skipped, the 07:30
   run still checks the portal read-only and keeps the evening FINAL whenever a row for T exists or the portal state is
   unknown.

## Adapter update (next morning or right after, small PR)

1. **Proposal:** `.venv\Scripts\python.exe -m agent.submission.observation_report data\portal_discovery\<ts>_observe`
   writes `adapter_proposal.md` / `.json` next to the evidence. It lists, per item, the **new** verbatim texts with the
   time first seen and the snapshot files. Known wording is left out. It never edits the adapter.
2. **Branch:** `feat/20-adapter-window-evidence` (worktree `.worktrees\issue-20-adapter`), based on #21's branch, or on
   `master` once #21 is merged.
3. **Edit** `config/portal_adapter.yaml`, with values copied verbatim from the evidence:
   - `wording.validation_pass`: `status: CONFIRMED_REAL_E2E`, `markers: [<pass text>]`. The text must not also
     appear in `validation_pending` or `validation_fail`.
   - `selectors.submit_confirmation_modal` / `submit_confirm_button`:
     - if a dialog appeared, the role / name strategies seen in the snapshot (`dialogs`, `buttons`);
     - if none appeared, `status: CONFIRMED_NOT_PRESENT` for **both**.
   - `wording.submit_success`: `status: CONFIRMED_REAL_E2E`, `markers: [<success text>]`.
   - Every entry: `source: "Issue #20 live observation 2026-10-27 HH:MM (data/portal_discovery/<ts>_observe, local)"`.
4. **Tests:**
   - `test_window_only_items_need_live_observation_evidence` requires the `_observe` source for each confirmed item.
   - `test_submit_flow_pending_on_real_adapter_lists_only_window_only_items` must be updated to the new expected list:
     `[]` when all four are confirmed. This is a justified spec change; cite the evidence.
   - Add a classification test with the verbatim strings, e.g. `classify(<pass text>) == "PASS"` and
     `read_submit_result` on the success text gives `OK`.
5. **Run:**
   - targeted: `tests/ops/test_issue20_auto_submission.py`, `tests/ops/test_issue4_portal.py`;
   - full `python -m pytest -q`;
   - `scripts/ci/*` local checks;
   - `scripts\ci\local_freeze_regression.py`.
6. **Ship:** commit (trailer), push, small PR (`Refs #20`, evidence list, no Quant impact), Shared-State comment on #20,
   label `agent:review`, ChatGPT review. The Owner merges.

Until that PR is merged, every automated run stays at "upload + evidence, no submit". The Owner submits by hand.
