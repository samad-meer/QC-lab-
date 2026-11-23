# QC Lab audit, 31 October 2026

## Status after the fixes, same day

The code is ready for validation. It is **not yet approved for GMP use**: that takes
your QA lead, your validation team and a real server. The findings below are kept as
they were found, as the record of what was wrong.

**Evidence for the fixes**

- 712 automated tests pass on SQLite and on real PostgreSQL 18, with all 98 triggers
  active. 10 skip on SQLite because they need those triggers.
- Added later the same day: this installation moved from SQLite to PostgreSQL 18 with
  its records, and SQLite support was removed. All 1,120 rows in 66 tables matched field
  by field, all 98 triggers are on, and 13 of 13 direct tampering attempts were refused
  on the real database. All 712 tests pass there and none skip, as a login without
  superuser rights.
- Added 1 November: Settings has a "Who can sign in" list, using the same switch as
  Deactivate. Three gaps were found and closed while building it: an account with no
  active role could sign in and read 18 endpoints; a blocked person's session came back
  with no password when they were allowed again; and the audit trail wrote "—" instead
  of False as the earlier state. 730 tests pass on PostgreSQL, and 22 of 22 checks passed
  in a real browser on a private copy. Deactivating through the admin site still keeps
  someone out but does not delete their session, so use Settings or Users.
- Added 1 November, later: closed B28 and B29, and built the release, calibration and
  qualification alerts, email, role rename and delete, and the Sections screen. A print
  window now opens before anything is recorded, so a blocked one costs no copy; a copy
  whose window closed can be opened by whoever printed it, for a day. That day also
  closes a hole: the 22 prints from before copies were tracked showed no opening, so
  each could have been opened once more by its URL. All 777 tests pass on PostgreSQL.
  28 checks passed in a real browser on a private copy. After the router change, 51
  screens were walked again as the administrator and the main screens as five other
  logins; review, investigation and lab record detail pages were not, because the data
  has none to open. Email has only run against Django's test mail backend: no real mail
  server has been used.
- A clean install, the production web server, a restricted database login and sign-in
  were run for real. `check --deploy` reports no issues.
- Backup and restore were run, and the integrity check passed on the restored copy.
- The whole failed-result journey was walked by five people in real browsers (30 of 30
  checks), and the lab record screens too (26 of 27, the other being the app rightly
  refusing a test script's future date). 32 pages have no sideways scroll at 1280 and
  390 wide.
- `pip-audit` and `npm audit` find no known vulnerabilities.

**Not tested:** nginx itself (`deploy/nginx-qclab.conf` was written but nginx is not
installed here, so forwarded headers were simulated), a real TLS certificate, the
application under realistic data volumes, and a real printer.

**Fixed:** B1 to B12, B14 to B22, B24, B25, B30 to B32, B34, B37, W1 to W7, W9, W11 to
W18, W22, W25, W26, W30, M1 to M16, and S1 to S8.

A re-check against the code moved B13, B23, B26, B27, B28 and W10 from fixed to partly
fixed, and found the smaller items listed under "Not done".

**Partly fixed**

| # | What is done | What is left |
| --- | ------------ | ------------- |
| B13 | Batch reports follow the sample's batch, whatever the number says now | The deviation form still cannot link a sample, so a deviation shows only through its typed batch number |
| B23 | My tasks skips finished samples | Due-date alerts still run inside a person's notification request, and grow with open samples |
| B26 | The sample and review pages say when step data fails to load | Role history and Workflows history still show a failed load as empty; the top bar shows 0 tasks |
| B27 | The worklist shows only the person's own samples | Someone who is both analyst and reviewer gets the review count on the worklist badge |
| B33 | OOT Trends defaults to 90 days and filters by product in the database | It still loads every result in the period, and has not been measured on large data |
| B35 | Result entry refuses bad input properly | A few other endpoints can still return 500 on malformed input |
| B36 | A retest cannot be decided during a hold | A stage can still be claimed before it is reached |
| W8 | A failure holds the whole batch, so a resample cannot escape it | Repeat, retest and resample are still labels, and a resample sits on the original sample number |
| W10 | An expired batch needs a reason, printed on the certificate | `shelf_life_months` is still unused; a finished product can have no expiry; expiry and retest date share one field |
| W20 | Laboratory finding, conclusion and failure history | No formal Phase II record, or extension to other batches |
| W21 | On Time shows overdue samples; pooled rates are labelled; trends say what they leave out | Superseded failures are still not plotted on trends |
| W24 | Receipt date, issue date and specification version print | No manufacturer address; method and dates can still be hidden |
| W27 | Excel carries the note | CSV stays a plain table with no stamp, on purpose |
| W28 | Greek, subscripts and lab symbols print | Urdu does not |
| W29 | Dialogs are named, trap focus and close on Escape; skip link; page titles; button contrast | Other contrast items and form error wiring |
| M17 | URS, traceability, IQ, OQ and PQ drafted | None executed. Validation plan, risk assessment and SOPs are yours |
| S9 | Login CSRF, stored typed passwords, pinned packages, `.gitignore` | No CSP; any ZIP still passes as xlsx or docx |

**Not done**

- B38: `/tasks#...` links do not scroll, and overdue tasks stop at 50.
- W19: `admin.override` is still there, by your decision. Remove it before go-live.
- W23: a specification cannot take effect on a future date, and an overdue review blocks nothing.
- M18 to M23: stability, environmental monitoring, sampling plans, OOT statistics,
  system suitability, measurement uncertainty.
- M24 and M25: investigations and lab records in My tasks. Alerts for calibration and
  qualification coming due, and email, are built; email needs a mail server named.
- M26: frontend tests, CI and version control.
- Refusals: execution refusals are returned to the person but not written to the audit
  trail. Only permission refusals and some named ones are.
- Reports: Analyst Workload and Bottlenecks figures have no drill-down; turnaround does
  not separate hold or rework time; exports drop "so far" on running samples; recurring
  investigations ignore the document's period.
- Records: the move from Received to In Testing writes no sample history row; analysis
  dates come from current results only; changing `restart_yearly` is not audited.
- Accessibility: no form exposes required or error state to screen readers.
- Tidying: a stale comment in `certificates/services.py` and an unused `require` in
  `accounts/authz.py`.

**Decisions made without your QA lead, to confirm**

- The Quality rules ship strict: investigation before retest, 2 retests, second analyst,
  batch-wide hold. Change them on Admin → Quality rules.
- Authorizing a retest does not disqualify someone from closing the investigation,
  otherwise a one-approver lab could never close one.
- Each printed copy opens once. A blocked popup or a refresh means printing a new
  numbered copy.
- An open deviation on a batch blocks its certificates.
- Signing needs the password alone, relying on the 15-minute idle timeout for 21 CFR
  11.200(a)(1).

---

## The audit as found

**Verdict: not ready for GMP use.** The signing and record-keeping core is solid, but
the app cannot be installed on PostgreSQL today, it can pass a result it should not,
and its out-of-specification path does not meet FDA expectations.

This is an engineering audit against published standards, not a regulatory opinion.
It uses FDA, EU and WHO references. Your own regulator decides which ones apply, and
your QA lead should confirm the GMP items.

## How it was checked

- Six independent reviews, one each for data integrity, QC lab practice, security,
  core workflow, Reports and Investigations, and the frontend.
- The full test suite on SQLite: **405 of 405 pass**.
- The full test suite on a real PostgreSQL 18, for the first time: **`migrate` crashes**.
  With that one line fixed in a scratch copy, **52 of 405 tests error**. 34 are real
  bugs, and 18 are tests editing locked rows, which the triggers rightly refuse.
- With the two lock bugs fixed in the copy and the sample trigger relaxed so those
  tests could run, 402 pass. The other 3 are tests editing locked rows.
- End-to-end scenarios through the real API on PostgreSQL with all triggers active.
- Dependency scans (`pip-audit`, `npm audit`) and `manage.py check --deploy`.

Nothing in the project was changed except this new file.

**Evidence** says how far each finding was checked:

| Tag | Meaning |
| --- | --- |
| **Ran** | Reproduced by running the real code, on PostgreSQL unless it says otherwise |
| **Read** | I read the code myself and confirmed it |
| **Reviewer** | Reported by a reviewer, and not separately checked by me |

**Severity:** Critical can cause a wrong quality decision or stops the system running.
High blocks real work or misleads about quality data. Medium and Low are smaller.

**Corrections to my earlier report on Reports:**

- I said every dashboard number opens exactly that many records. That is not true of the
  failed samples and failed batches figures (B22).
- I said an analyst sees only their own samples. That holds for sample rows, but
  Document Control counts are lab-wide (B34).
- I said PostgreSQL was untested. The real position is worse: it cannot be installed (B1).

---

## 1. Broken: does not work, or gives a wrong answer

| # | Sev | Problem | Where | Evidence |
| --- | --- | --- | --- | --- |
| B1 | Critical | **Production cannot be installed.** `migrate` crashes on PostgreSQL with both drivers, because SQL with a bare `%` goes through a call that treats `%` as a placeholder. `requirements.txt` has no PostgreSQL driver either, and `settings.py` falls back to SQLite without warning. So no database lock has ever been active. The fix is one line: `params=None`. | `certificates/migrations/0002_pg_lockdown.py:101` | Ran |
| B2 | Critical | **Retests crash on PostgreSQL.** Anything entered over a failed result gives a 500, so a failure can never be retested. Fix: `select_for_update(of=("self",))`. | `execution/services.py:778` | Ran |
| B3 | Critical | **Checklist answers crash on PostgreSQL**, including receipt checks and required documents, so any workflow with checklists stops. Same fix. | `execution/services.py:147` | Ran |
| B4 | Critical | **A certificate can contradict its own limit.** Enter 5.0049999 against NMT 5.00 with 2 decimals: it rounds to 5.00 and passes, is stored as 5.005, and the certificate prints **5.01, PASS**. | `lims/evaluation.py:57`, `certificates/services.py:72` | Ran |
| B5 | Critical | **Rounding is not tied to the limit.** Nothing checks `decimals` against the limit. 0.40 passes NMT 0.10 with decimals 0. 0.149 passes NMT 0.14 with decimals 1. 97.5 passes NLT 97.6 with decimals 0. 98.46 fails NLT 98.5 with decimals 2, where USP rounding passes it. USP General Notices 7.20. | `lims/evaluation.py:57`, `standards/api.py:97` | Ran |
| B6 | High | **Correcting a batch number crashes on PostgreSQL** if the batch has open samples. The trigger forbids what the feature does. Other details correct normally. | `batches/services.py:124`, `lims/migrations/0006:21` | Ran |
| B7 | High | A batch correction skips a certificate already in review, so it can release with the old expiry date. | `batches/services.py:124` | Read; reviewer ran it |
| B8 | High | **One long text field crashes the PDF.** A 4,000-character root cause saves, then the OOS report and Sample History PDFs return 500 (`LayoutError`). The screen accepts what the export cannot print. | `reports/export.py:217` | Ran |
| B9 | High | The OOS report ignores dates when matching investigations. A new failure after a closed case shows "Closed" with the old root cause and no "None opened" link, while the dashboard says it needs investigation. | `reports/results.py:160`, `reports/records.py:174` | Read |
| B10 | High | The OOS report shows the wrong retest. Retests sort newest first and the code takes the last, so declined-then-passed reads "Retest, Declined". | `reports/records.py:188`, `reports/results.py:200` | Ran |
| B11 | High | Sample Register shows a green **"All tests within limits"** on a sample that failed three times and then passed, even on the "requires investigation" list. | `reports/samples.py:54` | Ran |
| B12 | High | Test Results Register says "every recorded result" but hides superseded failures by default, and exports do not say so. | `reports/results.py:42,80` | Read |
| B13 | High | Batch reports match investigations on typed text. After a batch number correction, an open OOS shows "Open investigations 0". A deviation cannot link to a sample at all. | `reports/batches.py:79` | Read |
| B14 | High | The closer's independence check is too narrow. It misses whoever wrote the root cause, completed the actions, was previously responsible or authorized the retest. | `quality/services.py:139` | Read |
| B15 | High | Specification approval is not tied to what was reviewed. Edits made after review go effective unseen, and someone who edited another person's draft can approve it with no flag, because only the creator is checked. | `standards/api.py:300` | Read; reviewer ran it |
| B16 | High | **"Every print is recorded" is false.** An analyst without `cert.print` reopened copy 1 three times. Each read ORIGINAL, and print events stayed at 1. | `certificates/views.py:129` | Ran |
| B17 | High | The same result reads differently per screen: 98.450000 on the sample page, 98.45 on the batch page, 98.5 on the certificate. | `frontend/src/pages/SampleDetailPage.tsx:86,423` | Read |
| B18 | High | Screens use the browser's time zone and format; certificates and reports use lab time. One signature can read differently on screen and on paper. | `frontend/src/util.ts:2` | Read |
| B19 | High | Front desk "received" time is set when the page opens. Leave it open and the next sample silently gets the old time. | `frontend/src/pages/FrontDesk.tsx:104` | Read |
| B20 | High | The Users screen says "The user can change this themselves from My account". That feature does not exist. | `frontend/src/pages/admin/Users.tsx:137` | Read |
| B21 | High | A role with `user.manage` but not `role.manage` cannot use the Users screen, because it loads roles it may not read. | `frontend/src/pages/admin/Users.tsx:290` | Read |
| B22 | High | Failed samples and failed batches on the dashboard share one link, which opens failed tests, so the counts do not match. | `reports/dashboard.py:116` | Read |
| B23 | High | `/api/tasks/` slows as history grows: 29 queries became 1,829 at 300 rows, and every open tab polls it every 30 seconds. | `execution/tasks.py:116` | Reviewer ran it |
| B24 | Medium | "Change" on a review date opens blank, and saving with only a reason erases the date. | `frontend/src/pages/ProductDetail.tsx:284` | Reviewer |
| B25 | Medium | On hold or awaiting acceptance, the sample page still shows "Your turn" and Save, then refuses. | `frontend/src/pages/SampleDetailPage.tsx:214` | Reviewer |
| B26 | Medium | Failed requests read as empty or "Everything is in", against the README. | `frontend/src/pages/SampleDetailPage.tsx:182`, `Review.tsx:36` | Reviewer |
| B27 | Medium | With `sample.view.all` and `result.enter`, everyone's samples show as "Your turn to test". | `frontend/src/pages/Worklist.tsx:10` | Reviewer |
| B28 | Medium | Print shows for roles that are then refused. | `frontend/src/pages/CertificatePage.tsx:283` | Reviewer |
| B29 | Medium | Typed work is lost: clicking outside closes a dialog, and spec and workflow editors have no unsaved-change guard. | `frontend/src/components/ModalBackdrop.tsx:13` | Reviewer |
| B30 | Medium | No error boundary, so any screen error blanks the whole app. | `frontend/src/main.tsx` | Read |
| B31 | Medium | Deleting a role deletes its grant history, so "who could approve on 3 March?" can no longer be answered. | `accounts/models.py:66` | Read; reviewer ran it |
| B32 | Medium | Django admin sign-ins and failed attempts leave no audit row. | `qclab/urls.py:5` | Reviewer |
| B33 | Medium | OOT Trends loads every numeric result on each page, sort and export. | `reports/results.py:284` | Reviewer |
| B34 | Medium | Document Control "Samples using it" shows lab-wide counts to an analyst. | `reports/compliance.py:138` | Read |
| B35 | Medium | Bad input returns 500, not 400. An oversized value does so on PostgreSQL; the README says never. Also `test_definition_id="abc"` and several others. | `lims/views.py:243`, `lims/evaluation.py:44` | Ran (oversized value); rest Reviewer |
| B36 | Low | A retest can be authorized during a hold, and a stage can be claimed before it is reached. | `execution/services.py:742,557` | Reviewer |
| B37 | Low | A zero-test specification made in Django admin gives an empty "COMPLIES" certificate. | `certificates/services.py:156` | Reviewer |
| B38 | Low | `/tasks#...` links do not scroll, and overdue tasks silently stop at 50. | `execution/tasks.py:169` | Reviewer |

---

## 2. Wrong: works as built, but conflicts with the standard

| # | Sev | Problem | Standard | Where | Evidence |
| --- | --- | --- | --- | --- | --- |
| W1 | Critical | **A failure can be retested with no investigation.** `execution`, `lims` and `certificates` never refer to `quality`. | FDA OOS guidance | `execution/services.py:698` | Ran |
| W2 | Critical | **A certificate can release with an investigation missing or open.** Tested: 0 investigations, released. | 21 CFR 211.192 | `certificates/services.py:252` | Ran |
| W3 | Critical | **Testing into compliance.** Fail, fail, fail, pass was APPROVED, and the last value wins. There is no retest limit or averaging rule, and the same analyst retests. | FDA OOS guidance | `execution/services.py:716`, `lims/views.py:238` | Ran |
| W4 | Critical | **A new sample number escapes a failure.** Sample A fails and stays open. Sample B on the same batch passes and gets a COMPLIES certificate. | FDA OOS guidance | `certificates/services.py:216` | Ran |
| W5 | Critical | **Administrators know every signing password.** Only they set passwords, there is no forced change, and an admin can sign as an analyst with no override flag. | 21 CFR 11.100(a), 11.300 | `accounts/admin_api.py:310`, `accounts/profile_api.py:104` | Read |
| W6 | High | Reviewers and readers do not see the failure. After a passing retest the certificate shows PASS with no history, and review shows 0 out of specification. | 21 CFR 211.194(a)(8) | `frontend/src/pages/Review.tsx:90` | Ran |
| W7 | High | A certificate reads like batch release: "Approved, releasable" and "Approve and release". | ICH Q7, EU GMP | `certificates/models.py:11`, `frontend/src/pages/Review.tsx:241` | Read |
| W8 | High | Repeat, retest and resample are only labels. A resample lands on the original sample number, and a result cannot be invalidated for a proven lab error. | FDA OOS guidance | `execution/models.py:367` | Read |
| W9 | High | `<0.05` and `ND` are refused, so an analyst must invent a number. | 21 CFR 211.194(a) | `lims/evaluation.py:53` | Ran |
| W10 | High | An expired batch registers and gets a certificate. Tested with expiry 2020-01-01. `shelf_life_months` is unused. | ICH Q7 | `batches/services.py:32` | Ran |
| W11 | High | The printed limit is separate from the judged limit, so a certificate can read 95-105 % while the system judges 90-110. | 21 CFR 211.194 | `standards/api.py:103` | Read |
| W12 | High | The integrity hash is computed once and never checked again. It leaves out signer, time and letterhead, and the QR page shows no results, so altered paper still verifies. | 21 CFR 11.70, 11.10(c) | `certificates/services.py:272`, `certificates/views.py:170` | Read |
| W13 | High | Reprints are not true copies: letterhead, licence number and logo are read live, outside the hash. | 21 CFR 11.10(b), Annex 11 §8 | `templates/certificates/coa.html:120` | Read |
| W14 | High | Signing takes a password alone while sessions last 14 days, so it cannot count as one continuous session. | 21 CFR 11.200(a)(1) | `certificates/services.py:176` | Read |
| W15 | High | Database locks are incomplete even once they install: none on specifications, test definitions, grants or templates, and **`TRUNCATE` is not blocked, so the audit table can be emptied**. The README's "even direct SQL is refused" overclaims. | PIC/S PI 041, 21 CFR 11.10(e) | migrations | Ran |
| W16 | High | Django admin can change a specification's status and approver, and add tests to an approved one. | Annex 11 §14 | `lims/admin.py:21` | Read |
| W17 | High | By default only the administrator can read the audit trail, so the override holder alone reviews their own overrides. | Annex 11 §9 | `accounts/permissions_registry.py` | Read |
| W18 | High | Audit gaps: `SPEC_EDITED` stores only a count, several events keep new values only, and reasons are optional in places. | 21 CFR 11.10(e) | `standards/api.py:286`, `accounts/admin_api.py:143`, `lims/workflow_api.py:314` | Reviewer |
| W19 | High | **Administrator override.** This was your deliberate decision and it stands, but one person can fail, authorize, retest and sign, and the certificate then prints that someone other than the analyst authorized it. An inspector would cite it. Remove `admin.override` in production. | 21 CFR 211.194(a)(8) | `templates/certificates/coa.html:209` | Read |
| W20 | High | The investigation record is thin: no Phase I and Phase II, free-text outcome, no failed value on the closure screen, and closure with no actions allowed even when Critical. | FDA OOS guidance, 21 CFR 211.192 | `quality/models.py:70` | Reviewer |
| W21 | High | Report figures mislead. Product failure rate pools all tests and versions, trends silently drop superseded failures, and On Time counts released samples only: 10 on time plus 40 overdue reads 100 %. | GMP data practice | `reports/batches.py:138`, `reports/results.py:287`, `reports/samples.py:188` | Read (On Time); rest Reviewer |
| W22 | Medium | Specification approval and investigation closure store no signature meaning or hash. | 21 CFR 11.50, 11.70 | `standards/api.py:315`, `quality/services.py:372` | Reviewer |
| W23 | Medium | A specification cannot take effect on a future date, so there is no training window, and an overdue review blocks nothing. | EU GMP Chapter 4 | `standards/api.py:314` | Reviewer |
| W24 | Medium | Certificate content gaps: no receipt date, issue date, manufacturer address or specification identifier. Analysis dates are data-entry times. | ICH Q7 11.4, ISO/IEC 17025 7.8.2 | `templates/certificates/coa.html:138` | Reviewer |
| W25 | Medium | Usernames can be reused through Django admin, merging two people in the trail. | 21 CFR 11.100(a) | `accounts/admin.py:15` | Reviewer |
| W26 | Medium | Batch and product views are silently partial for a restricted user, with no note saying so. | ALCOA+ (complete) | `reports/documents.py:350` | Reviewer |
| W27 | Medium | A filtered CSV looks complete, with no stamp or filters, and Excel omits the report's note. | GMP data practice | `reports/export.py:66` | Reviewer |
| W28 | Medium | PDF font lacks Greek, subscripts and Urdu, so α, β and B₁₂ print wrongly with no warning. | ALCOA+ (accurate) | `reports/export.py:131` | Reviewer ran it |
| W29 | Medium | Accessibility: most dialogs have no name, none trap focus, some contrast is as low as 1.28:1, and every page has the same title. | WCAG 2.1 AA | `frontend/src/index.css:315` | Reviewer |
| W30 | Medium | Some reasons are optional where the README says required, and an OOS retest is authorized in one click with no confirmation. | Annex 11 §9 | `frontend/src/components/execution/ChecklistRowView.tsx:96`, `frontend/src/pages/Tasks.tsx:169` | Reviewer |

---

## 3. Remaining: not built yet

**Needed before go-live**

| # | What is missing | Standard |
| --- | --- | --- |
| M1 | **An end for a failed, rejected or cancelled sample**, and a failing report. Today it stays In Testing and overdue forever (Ran). "DOES NOT COMPLY" can never appear. | 21 CFR 211.165(f) |
| M2 | Batch disposition: quarantine, release and reject by the quality unit | ICH Q7, EU GMP |
| M3 | Withdraw or amend a released certificate. The QR says "current" forever | ISO/IEC 17025 7.8.8 |
| M4 | Raw data: replicates, weights, calculations, dissolution stages. A result holds one value | 21 CFR 211.194(a) |
| M5 | Instruments, calibration, maintenance and logbooks | 21 CFR 211.160(b)(4), 211.194(d) |
| M6 | Reference standards, reagents and columns, with lots, potency, expiry and link to results | 21 CFR 211.194(c) |
| M7 | Method master with versions and validation status. A method is free text | 21 CFR 211.165(e), ICH Q2 |
| M8 | Analyst qualification per method, with expiry | 21 CFR 211.25 |
| M9 | Chain of custody, sampling record, storage location, retained samples, destruction | 21 CFR 211.170 |
| M10 | Change control | EU GMP, ICH Q10 |
| M11 | CAPA effectiveness check and a verifier. Owners complete their own actions | ICH Q10 |
| M12 | Login lockout, password expiry and history, and users choosing their own password | 21 CFR 11.300 |
| M13 | Idle timeout. Sessions last 14 days and bench PCs stay signed in | 21 CFR 11.10(d), Annex 11 §12 |
| M14 | Audit-trail review record | Annex 11 §9 |
| M15 | Backup, restore test, retention and archive. Uploaded files sit outside the database | Annex 11 §7.2, §17 |
| M16 | Production package: app server, nginx config, screen-refresh fallback, HTTPS, error logging. Nothing exists in the project. `/admin/*` screens collide with Django admin on one address | |
| M17 | Computer system validation: requirements, IQ/OQ/PQ, traceability. No such documents exist | Annex 11 §4, GAMP 5 |

**Later phases**

| # | What is missing |
| --- | --- |
| M18 | Stability programme (21 CFR 211.166); `STABILITY` is only a label |
| M19 | Environmental monitoring |
| M20 | Sampling plans |
| M21 | OOT statistics and outlier rules (USP <1010>) |
| M22 | System suitability |
| M23 | Measurement uncertainty and decision rules |
| M24 | Investigations in My tasks, plus due and overdue alerts for investigations and CAPA |
| M25 | Email alerts |
| M26 | Frontend tests, CI, version control, and running the backend tests on PostgreSQL |
| M27 | Screens for renaming or deleting a role, and for sections |

---

## 4. Security

| # | Sev | Problem | Where | Evidence |
| --- | --- | --- | --- | --- |
| S1 | Critical | **Unsafe defaults.** If `DJANGO_DEBUG` is unset, debug is on, and the login-page API gives anyone the demo usernames and password. `seed_demo` has no production guard and creates a superuser with `qclab1234`, which still works with debug off. `SECRET_KEY` also has a known default. | `qclab/settings.py:14-19`, `accounts/views.py:58`, `lims/management/commands/seed_demo.py:26,72` | Read |
| S2 | High | No login throttling or lockout at `/api/auth/login/`, `/admin/login/` or the signing prompt, and no MFA, even for `admin.override`. | `accounts/views.py:23` | Read |
| S3 | High | HTTPS is not configured: 4 `check --deploy` warnings remain even when configured as the README says. `CSRF_TRUSTED_ORIGINS` is localhost only, so behind HTTPS every POST should get 403, and QR links print as `http://`. | `qclab/settings.py:136-140` | Ran (`check --deploy`); rest Read |
| S4 | High | A limited administrator can escalate. `user.manage` alone can assign the Administrator role or reset `sysadmin`, so the README's "needs a different administrator" does not hold. | `accounts/admin_api.py:155,204,310` | Reviewer; reset path Read |
| S5 | High | Known vulnerabilities: Pillow 12.3.0 (39, fixed in 13.0.0; it decodes uploaded photos), DRF 3.18.0 (3, fixed in 3.18.2), sqlparse 0.5.5 (5, fixed in 0.6.0), and 2 high in npm (Vite 6.4.3 and source-map-js, dev server only). Django has none. | `requirements.txt`, `frontend/package.json` | Ran |
| S6 | Medium | The audit IP address can be forged with `X-Forwarded-For`. | `audit/middleware.py:26` | Read |
| S7 | Medium | No request size cap: the settings comment is wrong, and a huge JSON body or upload is buffered before any check. | `qclab/settings.py:129` | Reviewer |
| S8 | Medium | With debug off, production errors are logged nowhere. There is no `LOGGING` or `ADMINS`. | `qclab/settings.py` | Read |
| S9 | Low | No CSP. Login CSRF. A password typed as a username stays in the audit trail. Any ZIP is accepted as xlsx or docx. Requirements are unpinned. No `.gitignore`. | `accounts/views.py:30`, `execution/files.py:29` | Reviewer |

---

## 5. What is right

These come mostly from the reviewers' checks, backed by the test runs above.

- A signed certificate is frozen. Signatures are ordered, by different people, with name,
  time and meaning printed, and a send-back voids them.
- Results are never edited. Superseding keeps who, when and why, and a failed result
  cannot be replaced without an independent retest decision.
- A FAIL blocks signing under a row lock, on the exact data that gets frozen.
- Sample and batch numbers, locks, double-sign and stale-screen races all held up.
- Specifications and workflows are versioned and bound at registration. Holds stop work.
- All 97 API URL patterns were walked, with no case of reaching another user's record
  by changing an id. No SQL injection, no stored XSS route, and file handling is careful.
- All 125 frontend API call sites match the backend.
- On PostgreSQL the triggers do block `UPDATE` and `DELETE` on the tables they cover.
  Apart from the problems listed here, the code behaved correctly there.
- Reports state honestly what the system does not record.

---

## 6. Suggested order

1. **Make it run on PostgreSQL:** B1, B2, B3, B6, add the driver, and run the tests there.
   These are small changes.
2. **Stop wrong results:** B4, B5, B11, W9, W10, W11.
3. **Close the failure path:** W1 to W4, W6, W8, W20, M1, M3. This is the largest piece.
   Your QA lead must first set the rules: retest limits, who retests, what releases.
4. **Secure sign-in:** S1 to S5, W5, W14, M12, M13.
5. **Strengthen records:** W12, W13, W15, W16, W17, W18, M14.
6. **Fix reports and screens:** B7 to B23, then the Medium items.
7. **Build the missing lab records:** M2, M4 to M11.
8. **Prepare go-live:** M15, M16, M17, and remove `admin.override`.
