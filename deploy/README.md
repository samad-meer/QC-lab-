# Installing QC Lab

For whoever installs and runs the system. Commands are written for Windows; on Linux
use `python` and forward slashes. `python deploy/run.py` loads `deploy/qclab.env`, so
use it instead of `manage.py` for everything in production.

## What you need

- PostgreSQL 16 or later. It is the only database supported: it holds the locks that
  protect the records.
- Python 3.13 and Node 20 or later on the build machine.
- nginx, or another proxy that can do the same, with a TLS certificate.
- Somewhere off this machine for backups.

## Install

1. **Packages.** Use the pinned versions, so a validated install can be reproduced.

   ```powershell
   cd backend
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.lock
   ```

2. **Database.** Run `deploy/create_roles.sql` as the PostgreSQL superuser, after
   replacing both passwords. This makes two logins on purpose: `qclab_owner` owns the
   tables and runs migrations, and `qclab_app` is what the application uses. The
   application's login cannot switch off a trigger, drop a table or TRUNCATE. If the
   application used the owner login, anyone with its password could remove the locks.

3. **Settings.** Copy `deploy/qclab.env.example` to `deploy/qclab.env` and fill it in.
   Restrict who can read that file.

4. **Tables.** Migrations run as the owner, for this one command:

   ```powershell
   $env:POSTGRES_USER = "qclab_owner"; $env:POSTGRES_PASSWORD = "..."
   backend\.venv\Scripts\python.exe deploy\run.py migrate
   Remove-Item Env:POSTGRES_USER, Env:POSTGRES_PASSWORD
   ```

5. **First administrator.** They choose their own password when they first sign in.
   Never run `seed_demo` here: it refuses to, because its password is published.

   ```powershell
   backend\.venv\Scripts\python.exe deploy\run.py create_administrator your.name
   ```

6. **Admin site files and the screens.**

   ```powershell
   backend\.venv\Scripts\python.exe deploy\run.py collectstatic --noinput
   cd frontend; npm ci; npm run build
   ```

7. **Check it.** This must say `no issues`.

   ```powershell
   backend\.venv\Scripts\python.exe deploy\run.py check --deploy
   ```

8. **nginx.** Install `deploy/nginx-qclab.conf`, replacing the name and paths.

9. **The web server.** Run this as a service, restarting if it stops:

   ```powershell
   backend\.venv\Scripts\python.exe deploy\run.py serve
   ```

   It listens on 127.0.0.1 only, and it believes forwarded headers only from there.
   Do not expose port 8007 directly.

## Scheduled tasks

| Task | How often | Command |
| ---- | --------- | ------- |
| Backup | Nightly | `deploy/backup.ps1` |
| Alerts and email | Not needed: the web server's background worker sends email every 30 seconds and sweeps due dates hourly. Schedule hourly only if you set `QCLAB_BACKGROUND=0` | `deploy/run.py send_due_alerts` |
| Integrity check | Nightly | `deploy/run.py verify_integrity` |
| Restore test | Quarterly | `deploy/restore_test.ps1` |

`verify_integrity` recomputes the hash of every certificate, signature and stored file,
and fails if anything changed behind the application. Treat a failure as a quality
incident and tell QA. Do not just rerun it.

## Backups

`backup.ps1` takes the database and the uploaded files, which are not in the database,
and checks that the dump can be read back. Copy the backups off this machine. Keep
them for as long as your retention rule requires: GMP records usually outlive the
system, so agree the period with QA, and plan to read old exports with the system gone.

To restore: create the roles, restore the dump into an empty database with `pg_restore`,
put the files back in `QCLAB_MEDIA_ROOT`, then run `verify_integrity`.

## Keep the clock right

Every timestamp comes from the server, so its clock is part of the record. Keep it
synchronised (NTP on Linux, the Windows Time service on Windows) and include that in
your installation record.

## Before real work starts

1. **Execute validation.** See `docs/validation/`.
2. **Confirm the Quality rules** with your QA lead (Admin → Quality rules).
3. **Remove `admin.override`** from the Administrator role (Roles screen). It lets one
   person do every step, which is for demonstrations and emergencies. Putting it back
   needs a different administrator.
4. **Separate the administrator from the lab.** The person who manages accounts should
   not also test, review or release.
5. **Review roles** against your organisation, and give the lab head or QA `audit.view`
   so someone other than the administrator reads the activity log.
6. **Check the letterhead and certificate template** on a printed copy.
