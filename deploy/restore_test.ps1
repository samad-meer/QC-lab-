# Proves a backup restores: into a throwaway database, then the integrity check.
# Run at least quarterly and file the output. A backup never restored is a hope.
#
#   restore_test.ps1 -PgBin "F:\posgreeSql\bin" -Backup "G:\qclab-backups\2026-10-31_0200"
#
# Needs a login that may create databases. Touches nothing in the live database.

param(
    [Parameter(Mandatory)] [string] $PgBin,
    [Parameter(Mandatory)] [string] $Backup,
    [string] $User = "postgres",
    [string] $PgHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$target = "qclab_restore_test"
$psql = Join-Path $PgBin "psql.exe"

& $psql --host=$PgHost --username=$User --command="DROP DATABASE IF EXISTS $target"
& $psql --host=$PgHost --username=$User --command="CREATE DATABASE $target"
& (Join-Path $PgBin "pg_restore.exe") --host=$PgHost --username=$User --dbname=$target --no-owner `
    (Join-Path $Backup "qclab.dump")
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }

Write-Output "Audit rows restored:"
& $psql --host=$PgHost --username=$User --dbname=$target --tuples-only --command="SELECT count(*) FROM audit_auditevent"
Write-Output "Certificates restored:"
& $psql --host=$PgHost --username=$User --dbname=$target --tuples-only --command="SELECT count(*) FROM certificates_certificate"

Write-Output "Now run manage.py verify_integrity with POSTGRES_DB=$target to check every hash, then drop the database."
