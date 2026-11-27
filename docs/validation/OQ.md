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
| 47 | C8 | On a recorded stage, write a value outside its limit without a reason, then with one; change a written value without a reason, then with one | The first of each refused; the out-of-limit value is saved and flagged; the changed value keeps the old one in its history | | | |
| 48 | C8 | Try to sign "Checked by" before "Done by"; sign "Done by" with a wrong password, then correctly; then try to change a value | Each refused with its reason; once "Done by" is signed the values are final | | | |
| 49 | C8 | Have whoever signed "Done by" try to sign "Checked by" as well; sign it as the right role; sign the last column over a flagged value | The same person refused; the last column asks you to review and comment on the flagged value; the stage passes when the last column is signed, and every signature is in the activity log | | | |
| 50 | C9 | As the supervisor, assign a stage to operator A; as operator B try to write it; then reassign it to B | B refused while A holds it; after reassigning, A's name stays in the history with the time, and B can write it | | | |
| 51 | C10 | Add a required Photo or file check point to a stage, fill every other value and try to sign "Done by" | Refused, naming the photo | | | |
| 52 | C10 | Attach a program file (.exe), then a text file named .jpg, then a real photograph | The first two refused with the reason; the photograph saved with your name and the time | | | |
| 53 | C10 | Replace the photograph without a reason, then with one; sign "Done by" and try to replace it again | The first refused; the second saved and the first still listed; after signing, refused: the values are final | | | |
| 54 | C10 | As someone who cannot see the batch, open the photograph's address; then do the same signed out | Not found; refused | | | |
| 55 | C10 | Change the stored photograph on the server's disk, then run `verify_integrity` (put the file back afterwards) | Fails, naming the batch record file | | | |
| 56 | Q5 | As an analyst with no export permission, open Reports, Person Activity and choose Last week; then, as the administrator, tick "Print their own activity" for their role, and print again with PDF | First: the report shows on screen with no print buttons, and asking for the file is refused. Then: only their own work; the PDF names them, the dates and the totals; the export is in the activity log | | | |
| 57 | Q5 | As the same analyst, ask for another person's activity (change `person=` in the address); then do it as the lab head | The analyst is refused; the lab head sees it, with that person's name at the top | | | |
| 58 | Q6 | Register a sample for an analyst and assign a batch stage to an operator; open Tasks by Person, then Team Tasks | Each person's count equals their My tasks; each task shows who gave it, when and when it is due; a name opens that person's tasks | | | |
| 59 | Q7 | On All samples, and on a report, choose Last week, then Last month | The Monday-to-Sunday week and the calendar month that have ended; today's work is not in them | | | |
| 60 | U1 | Open the main screens, the sign-in page, a certificate's QR page and a printed certificate copy in a window 390 px wide, then 1280 and 2560 | Nothing scrolls sideways; on a phone the menu opens from a button and shows every link; the QR page and the printed copy can be read | | | |
| 61 | U2 | With a mail server named, raise an alert (a calibration coming due) and open no page for a minute; then make the mail server unreachable and load three pages | The email is sent by the system; the pages load as usual while the mail server is down | | | |
| 62 | Q8 | As the lab head open the dashboard and open each headline figure, each day of the two-week outlook, each stage and age of the waiting samples, each failing test and product, each dial, each cell of the product table, each section column, each limit with something outside it, and each part of the donuts and pies; then do the same as an analyst, and open Reports with a date range of your own | Every part opens a list with the same count as the part; this month is compared with the same days of last month; the analyst's figures count only their samples and show no batch, analyst or equipment view | | | |
