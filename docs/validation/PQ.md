# Performance qualification protocol (draft)

Proves the system supports real work, with trained people following approved SOPs, on
the live installation. Executed by: ________ Date: ________ Reviewed by: ________ Date: ________

## Before starting

- IQ and OQ approved, with no open critical deviations.
- SOPs approved, and users trained on them, with records.
- Real products, specifications, methods, instruments and materials entered and reviewed.
- Quality rules confirmed by QA, and `admin.override` removed.

## Scenarios

Run each on real or representative samples, in parallel with the current system if there
is one, and compare the outputs.

| # | Scenario | Acceptance | Result | Pass? | Initials |
| - | -------- | ---------- | ------ | ----- | -------- |
| 1 | At least three batches of each product type, receipt to certificate | Certificates match the parallel record | | | |
| 2 | An OOS, from failure to closure, with a real investigation | Follows the OOS SOP; complete record | | | |
| 3 | A confirmed failure to rejection and batch disposition | Follows the SOP | | | |
| 4 | A deviation with CAPA, through effectiveness check | Follows the SOP | | | |
| 5 | A specification change through change control | New version applies only to later samples | | | |
| 6 | A monthly audit-trail review by QA | Recorded, findings acted on | | | |
| 7 | Normal peak load: all users on a busy day | Acceptable response times; no errors in the log | | | |
| 8 | Restore from last night's backup to a test server | Complete; `verify_integrity` passes | | | |
| 9 | A power cut or server restart mid-shift | Nothing saved is lost; users can continue | | | |

## After PQ

Agree the routine: audit-trail review frequency, access review, backup and restore
testing, periodic review. Then the validation report releases the system for use.
