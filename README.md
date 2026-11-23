# QC Lab — sample to signed certificate

A system that takes a sample from the front desk to a signed, printed
Certificate of Analysis. Stage One of the brief: receipt and numbering,
sections, analyst assignment, personal worklists, result entry with
automatic pass/fail, the certificate, every signature its review workflow
requires, controlled printing, QR verification, and a full audit trail.

## Stack

| Layer    | Tech                                              |
| -------- | ------------------------------------------------- |
| Backend  | Django 5.2 LTS + Django REST Framework (Python)   |
| Database | PostgreSQL 16 or later, everywhere               |
| Frontend | React 19 + TypeScript + Vite (dev proxy → Django) |
| COA      | Server-rendered print page with QR code           |

## Interface

- **Login** — split screen: the journey and the three rules on the left, sign-in
  on the right. In `DEBUG`, one-click demo accounts appear (never in production —
  the backend only sends them when `DEBUG` is on).
- **Journey stepper** on every sample and certificate: Received → Tested →
  *the review stages of its product's workflow* → Printed, with every
  signature step marked.
- **Role-aware navigation** with a live count of what is waiting for *you*,
  from `/api/summary/`.
- **Light and dark themes**, remembered per browser, defaulting to the system
  setting.
- Toasts confirm each action, skeletons cover loading, and a failed request
  always shows as an error — never as an empty list, which in a queue would
  wrongly read as "no work waiting".

## Run it (development)

PostgreSQL is the only database, on a developer's machine too. Without its settings
the application refuses to start.

Database, once: run `deploy/create_roles.sql` as the PostgreSQL superuser, after
replacing both passwords. Then create `backend/.env`, which `manage.py` reads:

```ini
POSTGRES_DB=qclab
POSTGRES_USER=qclab_app
POSTGRES_PASSWORD=...
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
```

The application's login cannot change tables, so migrations run as the owner, for
that one command. Keep the owner's password in `deploy/qclab_owner.env`, never in `.env`.

```powershell
cd backend
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:POSTGRES_USER = "qclab_owner"; $env:POSTGRES_PASSWORD = "..."
.venv\Scripts\python.exe manage.py migrate
Remove-Item Env:POSTGRES_USER, Env:POSTGRES_PASSWORD
```

Backend — **port 8007**:

```powershell
.venv\Scripts\python.exe manage.py seed_demo      # demo users + products
.venv\Scripts\python.exe manage.py runserver      # defaults to 8007
```

Frontend (port 5173, proxies /api and /verify to the backend):

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

To use a different backend port, set `BACKEND_PORT` for **both** processes —
`manage.py` and `vite.config.ts` read the same variable, so they stay in step.

**Both in one window.** After the steps above, `.\dev.ps1` (PowerShell) or
`./dev.sh` (Git Bash) starts the backend and the frontend together, and Ctrl+C
stops both. A QC Lab runserver or Vite already running on port 8007 or 5173 is
stopped first; anything else on those ports is left alone, and the start refused.
If either half stops, the other is stopped too. `BACKEND_PORT=8010
FRONTEND_PORT=5180 ./dev.sh` runs them on other ports. It is for development only:
production is `deploy/run.py` behind nginx.

## Demo logins (password: `qclab1234`)

| Username      | Role                            |
| ------------- | ------------------------------- |
| `frontdesk`   | Sample custodian (front desk)   |
| `analyst.gf`  | Analyst — GF + Nutra sections   |
| `analyst.gf2` | Second analyst — GF + Nutra (does retests) |
| `analyst.api` | Analyst — API section           |
| `checker`     | Checker (AM / DM)               |
| `qa.officer`  | QA officer (demo role)          |
| `labhead`     | Approver (QCM / HOD)            |
| `prod.operator` | Production operator (Kamran Ali): fills batch records, signs “Done by” |
| `prod.officer`  | Production supervisor (Asif Mehmood): fills batch records, signs “Checked by (Production)” |
| `sysadmin`    | Administrator: every step of the lab's work (flagged in the log), plus Django admin (`/site-admin/`) |

The demo products use three workflows, so they need different numbers of
signatures: Paracetamol — *Standard review* (Checked → Approved, 3);
Vitamin C — *Short release* (Approved, 2); Ibuprofen — *Extended review*
(Checked → QA review → Approved, 4).

## The journey

Front desk registers → system issues sample number (never reused) and binds
the product's specification and review workflow → analyst's worklist →
results entered, pass/fail decided by the system → analyst signs (password
re-entry) → content frozen + SHA-256 hashed → each review stage of the
workflow, in order: its role signs, or sends the work back with a comment →
the last signature releases the certificate → print (copy 1 = original, then
numbered duplicates, every print recorded) → QR on the COA opens a public
read-only verification page.

## Review workflows

Not every product needs the same checks. `/admin/workflows` (permission
`workflow.manage`) defines **review workflows**: the signatures a
certificate needs after the analyst's, in order — one stage, or several.
Each stage has a name (the stepper label), a signature title and holder
("Checked by" · "AM / DM", printed under the signature line), and **the one
role that signs it**. Each product chooses a workflow; a product without one
uses the default.

- **Review signatures are workflow stages, not permissions.** The old
  `cert.sign.checked` / `cert.sign.approved` / `cert.sendback` /
  `cert.reject` permissions were retired (revoked, kept in the history) by
  `accounts/0008`. Whoever may sign a stage may also send the work back from
  it.
- **Versioned like specifications.** Saving changed stages creates a new
  version; every sample is bound to the version in force when it was
  registered, so an edit never re-routes work already in review. On
  PostgreSQL the binding and the stages are locked by triggers
  (`lims/migrations/0006`).
- **Guardrails:** an administrator cannot make their own role a signer;
  a workflow samples have been through cannot be deleted; a role that signs
  a stage cannot be deleted. Combinations normally kept apart (an analyst
  role that also signs a stage, an administrator role that signs, one role
  on two stages) are flagged on the role and workflow screens, not blocked.
- The original chain became the default *Standard review* workflow
  (`lims/0005`), with the lab's existing signature titles. Existing samples
  and certificates were bound to it unchanged.

## Inside each step: checklists, files, handovers (`backend/execution/`)

Every step of a workflow — the front desk's receipt checks, the analyst's
testing and each review stage — can carry its own requirements, set on the Workflows screen and versioned
with the stages (a change is a new version; samples keep the requirements
they were registered under).

- **Receipt checks.** What the front desk checks when a sample arrives (seal,
  label, temperature, a delivery note). With checks configured, they open
  right under the form as soon as the sample is registered, and also on the
  sample page and in the task center. Testing is refused until someone
  holding `sample.register` completes them, and the analyst is notified then.
  A workflow with no receipt checks sends samples straight to the analyst.
  They are made once: a later send-back does not reopen them.
- **Checklists and required documents.** Each item is a tick box, yes/no,
  pass/fail, number (unit, min/max, decimal places), text, date, a choice
  from a list, or a document. The server decides whether each answer
  conforms; a missing required answer or a non-conforming one blocks the
  step's signature, with the reason shown on screen and returned by the API.
  Answers belong to an *attempt* (the certificate version being built): after
  a send-back, nothing carries over. A changed answer is a new row — the old
  one is kept with who replaced it, when and why.
- **Files** are checked by extension *and* content (a renamed HTML file is
  not a PDF), size-capped (20 MB outer limit, per-item limits below that),
  hashed (SHA-256), stored under `MEDIA_ROOT` with a random name and **no
  public URL** — `/api/attachments/<id>/` serves them only to people who can
  see the sample. Never deleted: a new version replaces one, a withdrawal
  needs a reason and stays listed.
- **Holding a step.** A step can require acceptance: the analyst confirms
  receipt of the sample, or a reviewer *takes* the stage (or accepts it when
  it is assigned to them). Handovers between people wait for the receiver to
  accept; a decline needs a reason and goes back to whoever assigns work.
  A stage assigned to a named reviewer can only be signed by them. The
  sample's analyst can never be assigned to review it.
- **Holds** stop all entry and signing on a sample until released; both
  directions need a reason.
- **Retests.** A failed result is never replaced directly. It needs an OOS
  investigation with its laboratory finding recorded first (see *Investigations*).
  The analyst then asks for a retest with a reason; someone else holding
  `result.retest.authorize` (never the requester, the analyst, or whoever entered
  the failure) authorizes or declines it; only then can one retest result be
  entered, by a second analyst. Retests per test stop at the lab's limit. The failed
  result stays on record, linked to the retest. *Quality rules* below sets these.
- **Waivers.** An item marked *waivable* can be set aside by someone holding
  `stage.waive`, with a reason. Whoever waives a stage's requirement cannot
  sign that stage, and an analyst cannot waive their own testing's.
- **Notes and feedback**, threaded, per step. Never edited or deleted — an
  amendment is a new wording, with the earlier ones shown beneath it.
- **My tasks** (`/tasks`) lists everything waiting on the signed-in person —
  handovers to accept, returned work with the reviewer's reason, testing and
  what each sample still needs, reviews, retests to decide, declined work to
  reassign, holds and overdue samples — computed by the server from the same
  rules it enforces.

- **Notifications** (`backend/notifications/`). Whoever is given work hears
  about it: a sample assigned at registration, a step assigned or handed
  over, a named reviewer's stage being reached, work sent back, a retest
  requested (to those who may decide it) or decided, a hold placed or
  released, and the answer to a handover you sent. The bell in the top bar
  shows the unread count and the latest messages; anything new pops up as a
  toast (checked every 30 seconds, on every page change and on returning to
  the window; the task count follows the same rhythm). Nobody is notified of
  their own action, and nobody can read anyone else's. Beyond these: a failing
  result goes straight to those who may authorize a retest, a review with nobody
  named goes to everyone who could take it, samples due soon or overdue reach
  whoever they are waiting for, a released certificate reaches the analyst, whoever
  registered the sample and the people who print, and calibrations and analyst
  qualifications warn before they run out. Admin → Notification rules turns each
  alert on or off, adds roles, sets how early the warning goes and whether overdue
  reminders repeat, and chooses which alerts also go by email.
- **Email** is off until a mail server is named (`QCLAB_EMAIL_HOST` and friends in
  `deploy/qclab.env.example`). An email is queued in the same transaction as the
  action that caused it, so a signature never waits on a mail server and an action
  that rolls back sends nothing. The queue goes out on the next look at any
  person's bell, or on `send_due_alerts`, with retries; one that fails for good is
  on the audit trail. Notification rules has a button to send yourself a test.
- **Dashboard** (`/dashboard`, opened by clicking the system name): what is
  waiting on you, your notifications, where the samples you can see stand,
  and shortcuts for your role.

Every record carries the person and a server-side timestamp, shown to the
second. New permissions: `sample.assign`, `sample.hold`,
`result.retest.authorize`, `stage.waive` — granted by default to the front
desk (assign) and lab head (all four), the checker (hold); any of them can be
moved on the Roles screen (`accounts/0010`). `sample.comment` allows writing
notes and feedback; anyone who can see a sample can read them. Every role
holds it by default (`accounts/0011`) — take it from a read-only role such as
an auditor. On PostgreSQL the answer, file, comment, waiver and completed
receipt tables are locked by triggers (`execution/0002`, `execution/0003`).

## Products and batches: the trace (`backend/batches/`, `lims/products_api.py`)

- **Product master** (Admin → Products). Code, name, generic name, kind of
  material, dosage form, strength, pack size, storage condition and shelf life.
  Changes need a reason. Products are never deleted; one no longer made is set
  inactive and stops being offered at the front desk.
- **Batches.** A batch has many samples. Two identifiers are kept apart: the
  **official batch number**, stored exactly as the manufacturer assigned it and
  never generated here, and the **internal ID**, issued by the system. The same
  number on one product is one batch, whatever its capitals. A batch is recorded
  the first time one of its samples is registered, or by hand beforehand.
- **What a batch records stands.** A different expiry date at the front desk is
  refused rather than guessed at; a detail the batch lacks is filled in.
  Corrections need a reason and keep the old values. The official number cannot
  change once a certificate has been signed for the batch. Open samples pick up
  a correction; released ones keep what they were released with.
- **Samples with no batch.** Water, swabs, complaints: the sample says what it is
  in a reference instead, and runs the same journey.
- **The batch page** shows the trace: product, samples, current results,
  certificates, documents and history, limited to what the person may see.
- **Internal ID rule** (Settings): prefix, separator, digits, and whether to
  include the year, section or product and restart yearly. A number is never
  issued twice, even after the rule changes.
- **Batch documents.** Batch records, specifications, supplier certificates and
  the like are stored privately, checked like any upload, replaced by new
  versions, and withdrawn with a reason. Never deleted.

Numbers on samples registered before batches existed were turned into batch
records by migration (`batches/0002`); same product and same number is one batch.

## Specifications, templates and prints (`backend/standards/`)

- **Specifications** (Products → a product). A new version starts as a draft,
  copied from the current one, and changes nothing. Someone other than its
  author makes it effective by signing with their password. Only samples
  registered afterwards use it. An approved version is never edited or deleted;
  only its next review date can move, with a reason.
- **Test templates** (Admin → Test templates). A library of tests. A template is
  copied into a specification, which records where it came from. A change is a
  new version and never reaches a specification already using it.
- **Certificate templates** (Admin → Certificate templates). Title, a line under
  it, footer, and whether the method column, internal batch ID, manufacturing
  site, dosage form, analysis dates and storage condition print. Each product
  uses the default unless it names another. No option can remove a test, limit,
  result, outcome or signature. The layout is frozen when the analyst signs.
- **Labels and printable records.** A sample or batch label with a QR code, and
  a full sample record or batch record, from one label layout and one record
  layout. Each print is logged. A record states that it is not a certificate.

## The certificate

`/admin/settings` sets the **letterhead** — company name, address, licence number,
logo, contact details and a footer note. It appears on every certificate
signed from then on, and is frozen with it, so a reprint reads as the original did. What each signature is called belongs to its workflow
stage (see *Review workflows*).

The logo set there also shows beside the system name in the top bar and on the
sign-in page.

**Time zone.** Pakistan (`Asia/Karachi`) unless changed under *Date and time* on
the same screen, which offers every time zone. Times are stored in UTC, so a
change moves no recorded time. It changes how times are shown and printed from
then on, how a time typed at the front desk is read, and where "today" begins
for due dates, overdue alerts and report periods. The *Clock* beside it writes
every time of day as 12-hour (`02:05:12 PM`, the default) or 24-hour (`14:05:12`):
on screens, in reports and exports (Excel cells stay real times), and on the
certificate's signature lines (`LabConfig.time_format`, `accounts/0023`).

The letterhead and certificate templates are presentation. Which tests, limits,
results and signatures a certificate carries is fixed in code: a document an
administrator can reshape is a document that can be made to omit a failing test.
Certificates already signed keep the details they were issued with, because
their content is frozen.

The printed COA carries: letterhead and logo, batch details (manufacture date,
expiry/retest date, storage condition), the analysis window taken from the first
and last result entered, every test with its method and limit, every
signature its workflow requires, "Page X of Y", an "END OF CERTIFICATE" marker, the integrity hash,
and the verification QR code. Long certificates repeat the table header on each
page and never split a row.

**Retests on the certificate** are a choice of the product's workflow ("Show
retests on the printed certificate" on the Workflows screen). Off, the
certificate reports the final result only. On, it also lists each retest: the
failed result, the reason, who authorized it and the retest result, and marks
the reported value **R**. The choice is versioned with the workflow and bound at
registration, and the retest history is frozen into the signed content, so
every copy of a certificate prints the same. The sample page always keeps the
full history.

Batch details are optional at receipt — a raw-material drum may carry no
manufacturing date, and an in-process sample has no expiry.

## Lists: date filters and pages

Every list works the same way, from one place. On the server,
`qclab/listing.py` reads the date range and page and answers in one shape
(`results`, `count`, `page`, `page_size`, `pages`), so an endpoint states only
which records it lists and which of their dates can be filtered on. On the
screen, `useList` (`frontend/src/useList.ts`) loads a page and `ListCard`,
`DateRangeFilter` and `Pagination` (`frontend/src/components/list/`) draw it, so
a page supplies only its words, its own filters and how a row looks. A new list
needs none of this written again.

- **Dates.** A named period (today, this week, this month, last 90 days, all
  time), or any from and to, to the minute. The end includes its whole last
  minute, and a date with no time covers the whole day. Sample lists can filter
  on the received date or the due date. Dates that make no sense are refused
  with a message, never ignored.
- **Pages.** 25 rows by default, up to 200 through the API; the screens offer
  10, 25, 50 or 100. A page past the end gives the last page.
- **The address bar** holds every filter and page number, so a refresh, the Back
  button and a shared link all keep them.

Sample lists, the Activity log and Analytics have the date filter. Users has
pages only, as nothing about it is a matter of date. My tasks is neither: it is
a to-do list, and a filter there could hide work that is waiting. For the same
reason Pending Work and Overdue Work have no date filter; every other report does.

## Analytics and the activity log

Two admin screens, both driven by the same time ranges — **Today / This week /
This month / Last 90 days / All time**. Weeks start Monday and months on the 1st:
"this week" means the week you are in, not a rolling seven days.

**Analytics** (`/admin/analytics`) — samples received and released, median and
slowest turnaround, out-of-specification rate, corrections and returned work,
activity per day, workload per analyst, and samples per section. Every figure is
derived at read time; nothing is stored, so no statistic can drift out of step
with the records it describes. It counts a failure only while it is the current
result, and measures turnaround to the analyst's signature, so its figures can
differ from the Reports dashboard, which keeps every failure and runs to release.

**Activity log** (`/admin/audit`) — every action as a sentence a person can read
("*Bilal Ahmed signed the certificate for GF-2026-0004 as “Checked by”*"),
with the raw action code, the record it touched, and the address it came from.
Filter by period, person, record or action; or show only refusals and
corrections — the rows an inspector goes looking for.

Charts are deliberately **single-hue**: bar length carries the magnitude, so
colour never has to be told apart, and pass/fail is always a labelled badge
rather than a colour. The blue was checked for ≥3:1 contrast on both the light
and dark card surfaces. The two line charts on the Reports dashboard need a second
colour: `--chart-1` and `--chart-2` were validated together for colour blindness
and contrast in both themes, and each line also has a legend entry and an end label.

## Reports (`backend/reports/`)

`/reports` is the reporting module, for analysts, supervisors, QA reviewers and
management. It opens on the QC dashboard: what is in the lab right now, what
happened in the period, and every report you may open.

| Category | Reports |
| -------- | ------- |
| Sample reports | Sample Register, Sample History, Turnaround Time |
| Test results and failures | Test Results Register, OOS Investigations, OOT Trends, Retest History |
| Batch and product | Batch QC Summary, Product Quality History, Certificates of Analysis |
| Workflow and performance | Pending Work, Overdue Work, Analyst Workload, Workflow Bottlenecks |
| Quality and compliance | Audit Trail, Document Control, Deviations & CAPA |

**One way to report anything.** A report states which records it reads, its
columns, filters and dates, and how a record becomes a row (`reports/engine.py`
and one module per category). Filtering, sorting, paging, the generation stamp
and the exports are written once, and the screens draw whatever the server
defines, so a new report needs no new screen. Sample History, the Batch QC
Summary and Product Quality History are about one thing, so they are documents
(`reports/documents.py`): the screen and the PDF draw the same sections.

- **You see what you may see.** Every sample-based report, tile and export
  reads through `samples_visible_to`, and a filter can only narrow it. An analyst
  without `sample.view.all` gets their own samples throughout.
- **A number opens its records.** Every tile on the dashboard is a link to the
  list behind it, and that list has the same count.
- **Three failures, counted apart.** A failed test is one result. A sample with
  a failed test is not a failed sample decision. A batch disposition is a
  release decision, which this system does not record, and a released
  certificate is not one.
- **A failure stays listed.** The OOS report lists every failed result,
  superseded or not, with what followed it. A sample requires investigation until
  an OOS investigation of that test closes after the failure: a passing retest
  does not settle it.
- **Like is compared with like.** Trends and pass rates group results only where
  the test, method, unit and limits are all the same. A signal on OOT Trends is a
  prompt to look: there is no statistical out-of-trend rule until the lab has an
  approved procedure and enough data.
- **Workload is not a league table.** Analyst Workload is listed by name, because
  test complexity and investigation work vary too much for volume to rank anyone.
- **One way to write a date.** Every report writes dates as `30-Oct-2026 14:05:12`
  in the lab's time zone, whoever opens it and wherever they are.

**Exports.** CSV, Excel and PDF, built from the same rows as the screen, covering
every page of the selection. Excel and PDF carry the filters, who generated them
and when; a CSV is a plain table with the time in its file name. Every export is
in the activity log. A selection over the limit (50,000 rows, or 2,000 for a PDF)
is refused rather than cut short, because a cut-off report looks complete. Text
that a spreadsheet would run as a formula is written as text.

**Lists export too.** All samples, Batches, every Lab records register, Products,
Users and the Activity log have **Excel** and **PDF** buttons at the top right of
the list. The file holds every page of the list under the filters on screen, in
the same order, with the same header, limits and activity-log entry as a report
export. The buttons need the *Export reports* permission and are greyed out when
the list is empty. A list joins in by passing `export=` to `paginated()`
(`qclab/listing.py`); the columns are declared beside the list's endpoint, and
the writing is done by `reports/list_export.py`.

**Permissions.** `report.view` opens the module, and **each report is a permission
of its own** (`report.open.<report>`), so a role can be given Batch QC Summary and
nothing else. A report's history page of one record goes with it: a sample's with the
Sample Register, a batch's with Batch QC Summary, a product's with Product Quality
History. The Reports overview's figures are the Sample Register's. A link into a report
someone cannot open is shown as plain text, and the catalogue leaves that report out.
`report.export` downloads, and `report.performance` shows workload on the overview.
`accounts/0025` kept everyone as they were: a role holding `report.view` got every
report it could open, the two workload reports only with `report.performance` and the
Audit Trail only with `audit.view`. Untick what a role should not open on the Roles screen.

**Not recorded, so not reported:** SOPs. Reports say so where it matters rather
than leaving a blank that reads as nothing.

## Investigations, deviations and CAPA (`backend/quality/`)

A failed result stays exactly as it was entered, and an investigation only ever
points at it. Nothing here changes a result, a retest or a certificate. The
register is the Deviations & CAPA report; `/investigations/<id>` is one record.

- **Opening one.** An OOS investigation starts from a failed result (on the sample
  page, or the *None opened* link on the OOS report), an OOT one from a result, and
  a deviation from nothing but a description. One open OOS investigation per test
  per sample. References (`INV-2026-0001`) are never reused.
- **The laboratory investigation comes first.** An OOS records what the lab checked
  and whether it found an error, before any retest can be requested. Whoever entered
  the result does not record it. The record shows the failure and every result since.
- **What stops a certificate.** No certificate is signed, for this sample or any
  sample of its batch, while a failure has no investigation closed after it, a
  closed one confirmed it, or any investigation or deviation is open
  (`quality/gates.py`). A passing retest settles nothing by itself.
- **How it can end.** Invalidated, only if a laboratory error was found. Not confirmed,
  if none was found and retests are within limits. Confirmed, and the sample is then
  rejected: it never gets a certificate, and the batch's certificates stop too.
- **Working on it.** Filling in a blank needs no reason; changing what was written
  does. Every change is kept with its old and new values, on the record's own
  history and in the activity log. Corrective and preventive actions are added
  and completed once, never removed.
- **Closing it.** It goes for closure with a classification, root cause, final
  outcome and conclusion, every action complete and verified by someone else, and a
  major or critical one with at least one action. Someone holding
  `investigation.approve` then closes it with their password, or sends it back with
  a reason. That person is independent of the work: never anyone who wrote on it,
  was responsible for it, owned or verified an action, sent it for closure, entered
  the failed result or holds the sample. Deciding a retest does not count: that is
  a quality decision, and in most labs the same person approves closures. The
  administrator override passes this, and the audit row says so.
- **Closed is closed.** A closed investigation never changes again, and nothing
  is deleted. On PostgreSQL the tables are locked by triggers (`quality/0002`).

`investigation.manage` opens and works on them (checker and lab head by default);
`investigation.approve` closes them (lab head). Whoever is made responsible for
one, or owns an action, is notified; it does not appear under My tasks.

## Quality rules (Admin → Quality rules)

What must happen after a failed result. The quality unit's decision, so only someone
holding `investigation.approve` can change them, with a reason, and every change is
in the activity log. They ship strict:

| Rule | As shipped |
| ---- | ---------- |
| A failure needs an investigation before any retest, closed before any certificate | On |
| Retests allowed per test on a sample | 2 |
| A second analyst retests, not whoever produced the first failure | On |
| A failure holds the whole batch | On |

## How a sample ends

**Approved**, with a certificate. **Rejected**, for a failure a closed investigation
confirmed. **Cancelled**, for a sample registered by mistake, damaged or not testable,
and never one with a failed result. Rejecting and cancelling are signed by someone
other than the analyst, with a reason. An ended sample never reopens. A released
certificate can be **withdrawn** (`cert.withdraw`) with a password and a reason: its
content stays as signed, it can no longer be printed, and its QR page says so.

## Lab records (`backend/labrecords/`, `/lab`)

- **Instruments.** Register and logbook. An instrument is usable only while in service
  and in calibration; a failed calibration takes it out of service.
- **Standards and reagents.** One record per lot, quarantined until released. Usable
  only while available and in date.
- **Methods.** Versioned, with validation status, drafted by one person and made
  effective by another. A test can name one; a specification cannot be approved on a
  method that is not effective or not validated.
- **Analyst qualifications.** Where a test names a method, only someone currently
  qualified on it can enter the result.
- **Raw data.** A result can carry replicates (the server computes the mean), a
  worksheet reference, the instrument and the materials. An unusable one is refused.
- **Chain of custody.** On the sample page. Retained samples have a register, and
  destruction needs a witness and the retention date to have passed.
- **Change control.** `CC-2026-0001`, approved independently, implemented, closed.
- **Batch disposition.** On the batch page (`batch.disposition`): quarantine, release
  or reject. Release is refused until every sample is approved, nothing is open and
  every required QC stage that applies to the batch has passed. A certificate of analysis is not this decision,
  and says so.
- **Who sees what.** Each register has a see permission of its own (`instrument.view`,
  `material.view`, `method.view`, `qualification.view`, `retained.view`, `change.view`),
  and working on a register comes with seeing it: whoever holds `instrument.manage` sees
  the instruments (`INCLUDED_WITH` in the registry). A register someone cannot see is a
  403 and is not listed; a role that sees none has no Lab records in its menu. The
  instrument and lot pick-lists on a result, and the method list a specification draws
  on, stay open to whoever fills them. `accounts/0025` gave every role every register,
  so nothing changed until a role is narrowed.

## QC stages (`backend/batches/stages.py`)

The stages every batch of a product goes through, such as a line clearance, the final
grain test and the core tablet test. They are set on the product page (`product.manage`)
and every batch gets its own run of them.

- **Set per product, versioned.** Each stage has an order, a name, how it is done and
  whether it is required for release. Saving with a reason makes a new version, and a
  batch keeps the version in force when it was created, like a sample's specification.
- **Tested in the lab.** The front desk registers a sample for the stage. The stage
  passes when every sample registered for it is approved with a certificate in force,
  and fails when one is rejected.
- **Recorded by QA.** Someone with `batch.stage.record` (the lab head, the QA officer)
  records it passed or failed, with remarks and their password. A failure needs
  remarks. Doing it again (a re-line clearance) adds a record beside the first; the
  latest counts. Nothing changes once the batch is released or rejected.
- **Strict release.** A batch is released only when every required stage has passed.
  An optional stage is shown but never waited for. A batch created before its product
  had stages has none, and is released on its samples as before.
- **Locked.** On PostgreSQL a version of the stages and a recorded result can never be
  changed or deleted, a batch keeps its stages and a sample keeps its stage
  (`batches/0004`, `lims/0019`).
- **Tests per stage.** A lab-tested stage can have its own tests and limits, such as LOD
  and bulk density for the final grain, chosen with *Tests for* on the product page.
  They are a specification of their own: versioned, drafted by one person and made
  effective by another. A sample registered for the stage is tested on them once a
  version is effective, and on the product's specification until then, or when the
  stage has none. Front desk, sample page and certificate say which. A stage keeps its
  tests when it is renamed (`QcStage.tests_key`, `Specification.stage_key`,
  `lims/0020`, which also locks the stage of an approved version).
- **Stage order.** A stage can *wait for the stages before it*: no sample is registered
  for it and nothing is recorded until every earlier required stage has passed or does
  not apply. The front desk shows it greyed out with what it waits for.
- **One batch's exceptions.** QA (`batch.stage.record`) can mark a stage *not
  applicable* to one batch, only before anything has been done for it, so a failure is
  never hidden that way, and can say it applies after all. QA can also *add a stage* to
  one batch alone, choosing which tests its samples get. Both are signed with a
  password and a reason, append-only, and never change the product's stages
  (`batches/0005`). Release waits for every required stage that applies.
- **Batch records.** A recorded stage can be a whole page of the batch manufacturing
  record. On the product page it gets *steps* (Premixing, Preparation of binding
  solution, Drying), each with its instructions and *check points*: a number with its
  unit (kg, L, °C), a percentage, a start and end time, a time, a date, text, yes / no,
  or a *choice from a list* whose options the lab types, marking which are acceptable.
  A number or percentage can have limits, such as LOD 3.00 – 4.50 %; a choice answered
  with an option not marked acceptable is flagged like a number outside its limits.
  A kind the list lacks is added with *+ New kind…* at the end of the list (Temperature
  in °C, 50 – 80; Equipment ID; Visual check), kept under *Admin → Check point kinds*
  (`product.manage`, `batches/0007`) and offered in every stage after that; a stage
  keeps a copy, so changing or retiring a kind changes no stage already saved. The stage has
  *sign-off columns*, as many as needed, each with a title, who holds it and the role
  that signs it: Done by (Operator) → Checked by (Production) → Checked by (QA).
  Production (`batch.record.fill`, `batch.view.all`; the Production operator and
  supervisor roles, `accounts/0024`) fills the values on the batch page. A change needs
  a reason and the old value stays; a value outside its limits is saved, flagged red,
  with a reason. The columns are signed in order with a password, each by its role and
  each by a different person; the first signature makes the values final, and the last
  acknowledges every value out of limit, with a comment. The stage passes when the
  last column is signed. Release waits for that, and an optional stage with an
  unacknowledged value out of limit holds release too. Everything is append-only
  (`batches/0006`). A recorded stage with no sign-off columns is still recorded passed
  or failed by QA, as before.
- **Signed under every step, or once.** Each batch-record stage says where its columns
  are signed (`batches/0008`). *Under every step*, as the paper record has it, each step
  gets its own row: the date, then the columns (Done by, Checked by, …). A step's values
  are final once its first column is signed while later steps stay open, the last
  column of a step acknowledges that step's values out of limit, and the stage passes
  when every step is signed. *Once for the stage* is one row at the end, as above. New
  stages start under every step; stages saved before keep signing once until changed,
  and the change is a new version, so batches already made keep theirs.
- **Getting around.** Each lab-tested stage on the batch page has *Register a sample*,
  which opens the front desk with the section, product, batch and stage filled in. The
  Batches list, and its export, show how many required stages have passed.

## Sign-in and passwords

- **Only allowed people get in.** There is no self-registration: an administrator
  creates each account. To sign in, an account must be active and hold an active role.
  Admin → Sign-in and sessions → Who can sign in has a tick for each person. It is the same switch as
  Deactivate on the Users screen, so there is one list, not two. Unticking someone ends
  their session at once, and allowing them back does not revive it: they sign in again.
  Every change is in the audit trail.
- **A password is the person's own.** One set by an administrator is temporary: they
  must choose their own before doing anything else. The last five cannot be reused,
  and a password expires after 180 days.
- **Guessing stops.** Five wrong passwords lock an account for 15 minutes, wherever
  they were typed: sign-in, the admin site or a signature prompt.
- **A session ends.** After 15 idle minutes, and after 12 hours regardless. Polling for
  notifications does not count as being there.
- **Who is signed in (Admin → Sign-in and sessions, `user.manage`).** One row per
  computer: online (active in the last 5 minutes) or idle and when they will be signed
  out, when they signed in, and the browser, system and address it was from (kept in the
  session at sign-in, `accounts/signals.py`). An administrator can sign someone out on
  one computer, which leaves the account as it is, and lift a lockout early. The screen
  also lists who may sign in and the recent sign-ins, wrong passwords and lockouts, and
  reads again every 30 seconds without counting as activity. A session's key is never
  sent to the screen, only a fingerprint of it (`accounts/sessions_api.py`).
- **Nobody gives out more than they hold.** A role or a password reset cannot reach
  access the administrator does not have.

## User profiles

Every signed-in user has **My account** (`/profile`, reached from the top bar).

- **Identity** — photo, name, username, employee ID, designation, date of joining.
- **Access** — role, trained sections, and the plain-English list of what they
  may do. Previously nobody could see this about themselves.
- **Security** — last sign-in, changing their password, and a reminder that the
  password is a signature.

Who owns what: an **administrator** sets employee ID, designation, date of
joining, role, sections, a temporary password, and whether the account is active.
The **user** owns their photo, contact details and password.

Photos are validated by decoding (not by file extension), re-encoded to a
512×512 JPEG — which strips EXIF, including GPS — and served from an
**authenticated** endpoint rather than a public `/media/` path. A photo never
appears on a certificate: an electronic signature is not a picture.

Note `joining_date` (when the person joined the company) is deliberately
distinct from Django's `date_joined` (when the account was created).

## Roles and permissions

Roles are **data, not code**. An administrator creates roles, renames them,
and changes what each may do — from `/admin/roles` in the app, taking effect
immediately, no restart and no release.

- **The vocabulary of permissions is code** ([permissions_registry.py](backend/accounts/permissions_registry.py)).
  Each key corresponds to real enforcement that has been tested. Granting a
  key to a role is configuration; adding a new key is a release.
- **Grants are append-only and temporal.** Revoking sets `revoked_at` rather
  than deleting, so *"who could approve a certificate on 3 March?"* is a
  query. Every change carries who, when and why.
- **Guardrails:** an administrator cannot add permissions to a role they hold
  themselves, cannot change their own role or deactivate their own account,
  and system roles cannot be deleted while users hold them.
- **Segregation conflicts are surfaced, not blocked** — a role holding two
  signature capabilities is legitimate in a small lab, and is flagged on the
  role screen and in the audit trail.
- **Features shown (Settings).** The lab can switch off a whole module, or one part of
  it, for everyone, administrators too: any report, the Reports module, any Lab records
  register, or all of them. A hidden feature is taken out of everyone's permissions
  while it is hidden (`LabConfig.hidden_features`, `FEATURES` in the registry,
  `accounts/0026`), so menus, lists, links and the server all agree. No role, record or
  rule changes: a result still names an instrument from a hidden register, a hidden
  report can still be granted on the Roles screen (marked *hidden in Settings*), and
  showing it again brings everything back. Each change is in the activity log.
- **Some permissions come with others, or need another.** Seeing a register comes
  with working on it, so the role screen shows that box ticked and fixed. A report
  does nothing without "Open reports", and the screen says so. The reports are listed
  compactly, by what they are about, with *Tick all* and *Clear all*.

Three things are **not** permissions and cannot be granted away: immutability
after signature, no deletion, and printing only an approved certificate. Two
more hold for every role except one holding `admin.override` (below): a
different person for every signature on a certificate, and results only on
your own sample before signature. A role that signs every stage of a workflow
still cannot sign the same certificate twice — there is a test for exactly
that.

### The administrator override

The Administrator role holds every permission, including `admin.override`
("Act in anyone's place"), so one person can take a sample from registration to
print. That is a deliberate trade: **it removes the separation of duties for
whoever holds it**, and the audit trail is what stands in its place.

- **Passes the rules about who:** the assigned analyst, the role that signs a
  stage, acceptance of a step, a different person for every signature,
  independent retest decisions and waivers, withdrawing another person's file.
- **Never passes the rules about the record:** a hold (release it, with a
  reason), the order of the steps, an out-of-specification result (only through
  a retest), signed certificates, deletion, and the audit trail itself. Signing
  still needs the administrator's own password and carries their own name.
  Nobody amends another person's comment or accepts work for them.
- **Every use is flagged.** The audit row names the rule that was passed, reads
  as an administrator override, and appears under "needs attention";
  `/api/auth/audit/?override=1` lists them all. The screen warns before they act.
- **It is one switch.** Take `admin.override` away on the Roles screen and the
  separation of duties is back, even for a role holding every other permission.
  Putting it back needs a different administrator, because nobody can add to a
  role they hold (`accounts/0012` granted it in the first place).

Also recorded: refused attempts to change something, and every change made
through the Django admin site (`ADMIN_SITE_*`), so that site is not a way round
the trail.

The seeded roles (Sample custodian, Analyst, Checker, Lab head, Administrator)
are ordinary rows created by migration `accounts/0003`.

## The three rules, enforced

1. **A signature locks the document.** The snapshot and hash on a
   certificate can never change — guarded in `Certificate.save()` and, on
   PostgreSQL, by database triggers, so direct SQL through the application's login
   is refused too. Hashes are rechecked on every print and verification, and nightly
   by `manage.py verify_integrity`.
2. **Nothing is deleted.** Results are corrected by superseding (old value
   kept with who/why/when); audit events, signatures, prints, and workflow
   history are append-only at both the app and database layer.
3. **A different person for every signature.** Three people for the
   standard workflow, as many as a longer one requires. Enforced at signing
   time; refused attempts are recorded in the audit trail
   (`SIGN_REFUSED_SAME_PERSON`). The one exception is the administrator
   override, flagged on every row it is used for.

Also: an out-of-specification result **blocks** the analyst's signature —
no certificate can be built around a failure — and a failed result can only
be followed by an independently authorized retest (see *Inside each step*).
What is done about a failure is recorded as an investigation (see
*Investigations, deviations and CAPA*).

## Production notes

Installing, backups and scheduled tasks are in [deploy/README.md](deploy/README.md).
Validation drafts for QA are in [docs/validation/](docs/validation/README.md).

- Rounding policy (documented in `lims/evaluation.py`): entered values are
  rounded to the test's decimal places with ROUND_HALF_UP *before*
  comparison. Change it there and only there if your SOP differs.

## Tests

```powershell
cd backend
.venv\Scripts\python.exe manage.py test
```

Tests run on PostgreSQL, with the triggers active, so none skip. They read
`backend/test.env` instead of `.env`: a login that can create its own database and
cannot open the real one. Create it once as the superuser, with
`CREATE ROLE qclab_test LOGIN CREATEDB PASSWORD '...';`, then:

```ini
POSTGRES_DB=qclab_test_run
POSTGRES_USER=qclab_test
POSTGRES_PASSWORD=...
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
DJANGO_SETTINGS_MODULE=qclab.test_settings
```

A full run takes about 3 minutes. Do not start two at once: they share a test
database, and the second one replaces it.

The tests cover the full journey, the three rules, workflows with one and
with several review stages (order, roles, send-back from any stage, stale
screens, versioning), OOS blocking, send-back/versioning, print numbering,
access control, the concurrency/rounding regressions listed below, and the
step requirements: receipt checks, checklists and conformance, attempts, file checks and
private serving, acceptance and handovers, holds, retests, waivers and their
independence rules, comments and who may write them, retests on the certificate,
list date filters and pages, the product master, batches and their two
identifiers, samples with no batch, batch documents, specification approval, test
and certificate templates, labels and records, alerts and their rules, every
report (who may open it, what each person sees in it, tiles against their lists,
exports), investigations and their closure, the task center, and who is notified
of what.

## Concurrency and correctness notes

Signing and result entry both take a row lock on the sample, in a fixed
order (sample, then certificate), so:

- two sign requests cannot create two live certificate versions, and a
  signature from a screen showing an earlier stage is refused rather than
  landing on the next one;
- a result cannot land on a sample that has already been signed;
- the OOS gate is evaluated against the *same* snapshot that gets frozen,
  so a signed certificate can never contain a FAIL;
- a stale review screen cannot approve a certificate someone else already
  sent back (the action is refused with "someone else acted on it first").

Rounding is applied once, ROUND_HALF_UP, at the test's configured decimal
places — and the *printed* value uses the same rounding as the pass/fail
decision, so a certificate can never show a value that contradicts the
outcome beside it. Numbers are parsed via `str()` so a JSON float keeps its
decimal literal, and are bounded to what the column can store (a bad value
is a 400, never a 500).
