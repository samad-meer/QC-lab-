# Installation qualification protocol (draft)

Proves the system is installed as specified. Record evidence for each step. Executed by:
________ Date: ________ Reviewed by: ________ Date: ________

| # | Check | Expected | Actual | Pass? | Initials |
| - | ----- | -------- | ------ | ----- | -------- |
| 1 | Server name, OS and version recorded | As in the installation plan | | | |
| 2 | PostgreSQL version | 16 or later | | | |
| 3 | Python version | 3.13 | | | |
| 4 | Package versions, `pip freeze` | Identical to `requirements.lock` | | | |
| 5 | Application files | Hash of the release matches the release record | | | |
| 6 | Database logins | `qclab_owner` and `qclab_app` both exist; the application uses `qclab_app` | | | |
| 7 | `deploy/run.py showmigrations` | Every migration applied | | | |
| 8 | Triggers | `select count(*) from pg_trigger where not tgisinternal` matches the release record | | | |
| 9 | As `qclab_app`: `TRUNCATE audit_auditevent` | Refused | | | |
| 10 | As `qclab_app`: `ALTER TABLE audit_auditevent DISABLE TRIGGER ALL` | Refused | | | |
| 11 | `deploy/run.py check --deploy` | No issues | | | |
| 12 | `DJANGO_DEBUG` in the environment file | 0 | | | |
| 13 | Environment file permissions | Readable only by the service account and administrators | | | |
| 14 | Plain http request | Redirected to https | | | |
| 15 | TLS certificate | Valid, TLS 1.2 or later | | | |
| 16 | Port 8007 from another machine | Not reachable | | | |
| 17 | Server clock | Synchronised to the named time source | | | |
| 18 | Time zone in `settings.py` | The lab's | | | |
| 19 | Scheduled tasks | Backup, alerts and integrity check scheduled and have run | | | |
| 20 | Backup | A backup exists off this machine | | | |
| 21 | Restore test | `deploy/restore_test.ps1` succeeded and `verify_integrity` passed on the restored copy | | | |
