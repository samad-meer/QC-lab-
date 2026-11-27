# User requirements (draft)

Confirm each line against your SOPs. The references show where a requirement comes from;
confirm which apply to you. Priority: **M** mandatory, **D** desired.

## Sample handling

| ID | Requirement | Priority | Reference |
| -- | ----------- | -------- | --------- |
| S1 | Each sample gets a unique number that is never reused | M | 21 CFR 211.194 |
| S2 | A sample is bound at registration to the specification and review workflow in force | M | 21 CFR 211.160 |
| S3 | Receipt checks are completed before testing starts | D | EU GMP Ch. 6 |
| S4 | A batch past expiry cannot be registered without a recorded reason, which prints on the certificate | M | ICH Q7 |
| S5 | Who held a sample, where it was stored and its destruction are recorded | M | 21 CFR 211.170 |
| S6 | A sample ends as approved, rejected or cancelled, and an ended sample never reopens | M | 21 CFR 211.165(f) |

## Results

| ID | Requirement | Priority | Reference |
| -- | ----------- | -------- | --------- |
| R1 | The system decides pass or fail, rounding to the precision of the limit | M | USP General Notices 7.20 |
| R2 | The value judged, stored and printed is the same value | M | ALCOA+ |
| R3 | A result below the method's limit is recorded as such | M | 21 CFR 211.194(a) |
| R4 | A result is never edited: correction supersedes it, with who, when and why | M | 21 CFR 11.10(e) |
| R5 | Replicates, worksheet reference, instrument and materials can be recorded with a result | M | 21 CFR 211.194(a) |
| R6 | An instrument out of calibration, or an expired material, cannot be used | M | 21 CFR 211.160(b)(4) |
| R7 | An analyst must hold a current qualification for a method linked to the test | M | 21 CFR 211.25 |

## Failures

| ID | Requirement | Priority | Reference |
| -- | ----------- | -------- | --------- |
| F1 | A failure needs a recorded laboratory finding before any retest | M | FDA OOS guidance |
| F2 | The number of retests is limited by a rule the quality unit sets | M | FDA OOS guidance |
| F3 | A second analyst retests | M | FDA OOS guidance |
| F4 | A retest is authorized by someone independent | M | FDA OOS guidance |
| F5 | No certificate is signed while a failure is unsettled, on the sample or its batch | M | 21 CFR 211.192 |
| F6 | Only a found laboratory error invalidates a failure | M | FDA OOS guidance |
| F7 | A confirmed failure ends in rejection | M | 21 CFR 211.165(f) |
| F8 | Original failures stay on record and are visible to reviewers | M | 21 CFR 211.194(a)(8) |
| F9 | Investigations close independently, with a password, and never change afterwards | M | 21 CFR 211.192 |
| F10 | Corrective actions are verified by someone other than whoever did them | M | ICH Q10 |

## Review, certificates and release

| ID | Requirement | Priority | Reference |
| -- | ----------- | -------- | --------- |
| C1 | Every signature on a certificate comes from a different person, in workflow order | M | 21 CFR 211.194(a)(8) |
| C2 | Signing freezes and hashes the content, and later changes are detected | M | 21 CFR 11.70 |
| C3 | Only an approved certificate prints; each copy is numbered and recorded | M | Annex 11 §8 |
| C4 | A reprint matches the original, letterhead included | M | 21 CFR 11.10(b) |
| C5 | A released certificate can be withdrawn, and its QR page then says so | M | ISO/IEC 17025 7.8.8 |
| C6 | Batch disposition is a separate decision by the quality unit | M | ICH Q7 |
| C7 | Each product's QC stages are versioned and fixed on a batch when it is created; a batch is released only when every required stage has passed | M | 21 CFR 211.110, 211.165 |
| C8 | A batch's recorded stage is written on its batch record: a value outside its limits is saved flagged with a reason, a change keeps the old value and needs a reason, the sign-off columns are signed in order by their roles with a password and each by a different person, and the first signature makes the values final | M | 21 CFR 211.188(b), 11.70 |
| C9 | A supervisor can name who fills a stage and signs its first column; only that person can then write it, and reassigning keeps who had it and when | D | 21 CFR 211.188(b)(11) |
| C10 | A batch record can hold a photograph or file as evidence, required or optional as the lab sets it. It is checked for what it really is, kept with who added it and its hash, changed only by a recorded correction that keeps the first, final once the stage is signed, covered by the integrity check, and shown only to people who can see the batch | M | 21 CFR 211.188, ALCOA+ |

## Security and data integrity

| ID | Requirement | Priority | Reference |
| -- | ----------- | -------- | --------- |
| D1 | Each account belongs to one person, and a username is never reissued | M | 21 CFR 11.100(a) |
| D2 | Only the person knows their password: an administrator's is temporary | M | 21 CFR 11.300 |
| D3 | Repeated wrong passwords lock the account, including at signature prompts | M | 21 CFR 11.300(d) |
| D4 | Idle sessions end, and passwords expire | M | Annex 11 §12 |
| D5 | Every create, change and refusal is in an audit trail with old and new values | M | 21 CFR 11.10(e) |
| D6 | Audit records cannot be altered, even with database access by the application's login | M | PIC/S PI 041 |
| D7 | The audit trail is reviewed by someone independent, and the review is recorded | M | Annex 11 §9 |
| D8 | Access is by role, and nobody can give out more access than they hold | M | 21 CFR 11.10(d) |
| D9 | Backups are taken and a restore is proven | M | Annex 11 §7.2 |
| D10 | Traffic is encrypted | M | Annex 11 §12 |
| D11 | Only people an administrator has allowed can sign in. Blocking someone ends their session at once, and allowing them back does not revive it | M | 21 CFR 11.10(d) |

## Reporting

| ID | Requirement | Priority | Reference |
| -- | ----------- | -------- | --------- |
| Q1 | Reports show only what the reader may see, and say when that is partial | M | 21 CFR 11.10(d) |
| Q2 | An export says who generated it, when and with what filters, and is itself audited | M | ALCOA+ |
| Q3 | A failed test, a failed sample and a batch disposition are kept apart | M | Brief |
| Q4 | Change control records every change to specifications, methods and the system | M | EU GMP |
| Q5 | Anyone can open their own activity for a week, a month or any dates, and print it when the administrator has given their role that permission; seeing someone else's needs its own permission; the print names the person, the period and the totals, and is itself audited | D | Brief, ALCOA+ |
| Q6 | Whoever plans the work can see what each person holds, and for each task who gave it, when, and when it falls due, across samples, batch records, investigations and actions | D | Brief |
| Q7 | A date filter offers the week and the month that have just ended, as well as the current ones | D | Brief |
| Q8 | The dashboard shows the lab in figures and charts (what is late, how the period compares with the one before, what is coming due, how long work has waited, how long release takes, where failures come from, whether the equipment is in date, what stays inside its limit); each part opens exactly the records it counts, and a chart shows only what its reader may see | D | Brief |

## Usability and operation

| ID | Requirement | Priority | Reference |
| -- | ----------- | -------- | --------- |
| U1 | The screens work on a phone, a tablet and a large monitor: nothing runs off the screen, the menu stays reachable, and the certificate's QR page and a printed copy can be read on a phone | D | Brief |
| U2 | Alert email and due-date alerts are sent by the system itself, within about a minute, and never make a page wait | D | Brief |
