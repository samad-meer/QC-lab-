# Operational qualification protocol (draft)

Proves the system does what the requirements say on your installation. Use test accounts
in each role and a test product. Record the sample or record number and attach evidence
for each step. Executed by: ________ Date: ________ Reviewed by: ________ Date: ________

Run the automated suite on PostgreSQL first and attach the output (see README.md).

| # | Req | Do this | Expected | Actual | Pass? | Initials |
| - | --- | ------- | -------- | ------ | ----- | -------- |
| 1 | D2 | Administrator creates a user; the user signs in | Must choose a new password before anything else | | | |
| 2 | D2 | Choose a password used recently | Refused | | | |
| 3 | D3 | Enter a wrong password 5 times, then the right one | Account locked for 15 minutes; "locked" in the activity log | | | |
| 4 | D4 | Leave a session idle for 16 minutes | Signed out with a message | | | |
| 5 | D8 | With only `user.manage`, try to give someone the Administrator role | Refused | | | |
| 6 | S1 | Register two samples | Distinct numbers, in sequence | | | |
| 7 | S4 | Register a batch that expired last year, without a reason | Refused | | | |
| 8 | S4 | Repeat with a reason, then complete to a certificate | The reason prints on the certificate | | | |
| 9 | R1 | Limit NMT 0.10 with 2 decimals; enter 0.104, then correct to 0.105 | 0.104 passes; 0.105 rounds to 0.11 and fails | | | |
| 10 | R2 | Enter 5.0049999 | Refused: too many decimal places | | | |
| 11 | R3 | On an NMT test, enter `<0.05`, then on another `ND` | Both accepted and printed as written | | | |
| 12 | R3 | On NMT 0.10, enter `<0.50` | Refused | | | |
| 13 | R4 | Correct a passing result with a reason | Old value kept, with who, when and why | | | |
| 14 | F1 | Fail a test, then request a retest straight away | Refused: open an investigation | | | |
| 15 | F1 | Open the investigation, request a retest | Refused: record the laboratory finding | | | |
| 16 | F3 | Record the finding, authorize, try the retest as the first analyst | Refused: a second analyst | | | |
| 17 | F2 | Retest until the limit is reached, then request another | Refused | | | |
| 18 | F5 | With a passing retest and the investigation open, sign as analyst | Refused, naming the investigation | | | |
| 19 | F5 | On a second sample of the same batch, sign as analyst | Refused, naming the failed sample | | | |
| 20 | F6 | Find no laboratory error, conclude "Invalidated" | Refused at submission | | | |
| 21 | F9 | Whoever worked on it tries to close it | Refused | | | |
| 22 | F9 | Someone independent closes it with their password; then try to edit it | Closed; refused | | | |
| 23 | F7 | Confirm a failure and reject the sample | Sample rejected, no longer overdue, batch certificates blocked | | | |
| 24 | F8 | Reach review for a sample with a retest | Failed value and retest shown before signing | | | |
| 25 | C1 | Sign one certificate twice as the same person | Refused and recorded | | | |
| 26 | C3 | Print twice; try to reopen copy 1 | Numbered copies recorded; reopening refused | | | |
| 27 | C4 | Change the licence number, then print a duplicate of an older certificate | Old licence number printed | | | |
| 28 | C2 | Scan the QR code | Shows the certificate, its results and hash | | | |
| 29 | C5 | Withdraw a certificate, scan its QR code, try to print | Says withdrawn with the reason; printing refused | | | |
| 30 | C6 | Try to release a batch with an open investigation | Refused | | | |
| 31 | D5 | Change a user's role | Activity log shows old and new values | | | |
| 32 | D6 | As `qclab_app` in `psql`: `UPDATE audit_auditevent SET action='x'` on a real row | Refused | | | |
| 33 | D7 | Record an audit review; hold an override in the period and review as that person | First recorded; second refused | | | |
| 34 | R6 | Use an instrument past its calibration date | Refused | | | |
| 35 | R6 | Use an expired reference standard | Refused | | | |
| 36 | R7 | Enter a result without a qualification for the test's method | Refused | | | |
| 37 | Q1 | Open reports as an analyst | Only their samples, with a note saying so | | | |
| 38 | Q2 | Export to Excel and PDF | Who, when and filters on the file; export in the activity log | | | |
| 39 | Q3 | Compare dashboard failure figures with the OOS report | Same numbers | | | |
| 40 | C2 | Run `verify_integrity` | Passes | | | |
| 41 | D11 | With a test user signed in, an administrator unticks them in Settings, Who can sign in | Their screen returns to sign-in; signing in is refused; the activity log shows who changed it | | | |
| 42 | D11 | Tick them again, then reopen the same browser | Sign-in page, not their old session | | | |
| 43 | D11 | Create an account with no role in the admin site, then try to sign in with it | Refused | | | |
| 44 | C7 | Set up QC stages on a product, register a sample of a new batch for a stage, then change the stages | The batch keeps the first version; a new batch takes the second | | | |
| 45 | C7 | With every sample approved, try to release a batch whose required QA stage is not recorded | Refused, naming the stage; an optional stage is not named | | | |
| 46 | C7 | Record a QA stage as failed without remarks, then with remarks, then record it again as passed | First refused; both records kept, the latest counts | | | |
