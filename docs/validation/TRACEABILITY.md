# Requirements traceability (draft)

Each requirement in [URS.md](URS.md) against the automated tests that exercise it
(modules under `backend/`) and the OQ step that proves it on your installation.
Automated tests are supporting evidence. The OQ step is the validation evidence.

| Req | Automated tests | OQ step |
| --- | --------------- | ------- |
| S1 | `lims/tests.py` (numbering) | 6 |
| S2 | `certificates/tests.py`, `standards/tests.py` | 8 |
| S3 | `execution/tests.py` (receipt checks) | PQ 1 |
| S4 | `lims/test_values.py` (past expiry) | 7, 8 |
| S5 | `labrecords/test_custody.py` | PQ 1 |
| S6 | `quality/test_failure_path.py` (sample ends) | 23 |
| R1 | `lims/test_values.py` (rounding) | 9 |
| R2 | `lims/test_values.py` (one number everywhere) | 10 |
| R3 | `lims/test_values.py` (below the limit) | 11, 12 |
| R4 | `certificates/tests.py` | 13 |
| R5 | `labrecords/test_raw_data.py` | PQ 1 |
| R6 | `labrecords/test_instruments.py`, `labrecords/test_raw_data.py` | 34, 35 |
| R7 | `labrecords/test_methods.py` | 36 |
| F1 | `quality/test_failure_path.py` | 14, 15 |
| F2 | `quality/test_failure_path.py` | 17 |
| F3 | `quality/test_failure_path.py` | 16 |
| F4 | `execution/tests.py` (retests) | 16 |
| F5 | `quality/test_failure_path.py` | 18, 19 |
| F6 | `quality/test_failure_path.py` | 20 |
| F7 | `quality/test_failure_path.py` | 23 |
| F8 | `quality/test_failure_path.py`, `reports/test_fixes.py` | 24 |
| F9 | `quality/tests.py`, `quality/test_failure_path.py` | 21, 22 |
| F10 | `quality/test_capa_verification.py` | PQ 4 |
| C1 | `certificates/tests.py` | 25 |
| C2 | `certificates/test_integrity.py` | 28, 40 |
| C3 | `certificates/test_integrity.py` | 26 |
| C4 | `certificates/test_integrity.py` | 27 |
| C5 | `quality/test_failure_path.py` (withdrawal) | 29 |
| C6 | `batches/test_disposition.py` | 30 |
| C7 | `batches/test_qc_stages.py` | 44, 45, 46 |
| C8 | `batches/test_batch_records.py` | 47, 48, 49 |
| C9 | `batches/test_stage_assignment.py` | 50 |
| C10 | `batches/test_record_files.py` | 51, 52, 53, 54, 55 |
| D1 | `accounts/tests.py` | 1 |
| D2 | `accounts/test_sign_in.py` | 1, 2 |
| D3 | `accounts/test_sign_in.py` | 3 |
| D4 | `accounts/test_sign_in.py` | 4 |
| D5 | `audit/tests.py`, `execution/test_admin_override.py` | 31 |
| D6 | `certificates/test_integrity.py`, `labrecords/test_locks_on_postgres.py` (PostgreSQL only) | 32, IQ 9, IQ 10 |
| D7 | `audit/test_reviews.py` | 33 |
| D8 | `accounts/test_sign_in.py`, `reports/tests.py` | 5 |
| D9 | None | IQ 21, PQ 8 |
| D10 | `accounts/test_sign_in.py` (proxy) | IQ 14, IQ 15 |
| D11 | `accounts/test_sign_in_access.py` | 41, 42, 43 |
| Q1 | `reports/tests.py`, `reports/test_fixes.py` | 37 |
| Q2 | `reports/tests.py` | 38 |
| Q3 | `reports/tests.py`, `reports/test_fixes.py` | 39 |
| Q4 | `labrecords/test_changes.py` | PQ 5 |
| Q5 | `reports/test_team_reports.py` (Person Activity), `reports/test_report_permissions.py` | 56, 57 |
| Q6 | `reports/test_team_reports.py` (open work, batch stages) | 58 |
| Q7 | `qclab/tests.py` (last week and last month) | 59 |
| Q8 | `reports/test_dashboard_charts.py`, `reports/tests.py` (DashboardTests) | 62 |
| U1 | None: checked in a browser at several widths | 60 |
| U2 | `notifications/test_worker.py`, `notifications/tests.py`, `notifications/test_lab_alerts.py` | 61 |
