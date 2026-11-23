# QC Lab validation package

For the QA lead and validation team. These are drafts to review, adapt to your quality
system and execute. Nothing here has been executed or approved, and writing them does
not validate the system: that is your organisation's decision, on evidence from your
own installation.

## Scope and category

QC Lab is custom software that creates and signs GMP records, so treat it as GAMP 5
Category 5. It falls under 21 CFR Part 11 and EU GMP Annex 11 wherever those apply to
you. Your regulator decides which standards bind you.

## What is here

| Document | Purpose | Status |
| -------- | ------- | ------ |
| [URS.md](URS.md) | What the system must do | Draft: confirm against your SOPs |
| [TRACEABILITY.md](TRACEABILITY.md) | Each requirement to its tests | Draft |
| [IQ.md](IQ.md) | Installed correctly | Protocol, not executed |
| [OQ.md](OQ.md) | Works as specified on your installation | Protocol, not executed |
| [PQ.md](PQ.md) | Works in your lab, with your people and SOPs | Protocol, not executed |

Still yours to write: the validation plan and report, the risk assessment, supplier
assessment, SOPs for use and administration, training records, and the periodic review
plan.

## Automated evidence

The repository's test suite runs on every change and is evidence towards OQ, not a
replacement for it. It runs on PostgreSQL, with the database locks active:

```powershell
cd backend
$env:POSTGRES_DB="qclab_test_run"; $env:POSTGRES_USER="postgres"; $env:POSTGRES_PASSWORD="..."
.venv\Scripts\python.exe manage.py test --noinput
```

None may skip for a validation run: ten of them exercise the PostgreSQL triggers
directly. File the output with the protocol.

## Changing a validated system

Every code, configuration or Quality rules change after release goes through change
control: Lab records → Change control records the change and its approval, and the
impact assessment decides how much of OQ to repeat.
