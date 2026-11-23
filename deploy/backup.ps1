# Nightly backup: the database and the uploaded files, which are not in it.
# Schedule with Task Scheduler. Stops with an error, so a failed backup is noticed.
#
#   backup.ps1 -PgBin "F:\posgreeSql\bin" -Media "F:\qclab\media" -Dest "G:\qclab-backups"
#
# Set PGPASSWORD in the task's environment for the owner login, or use a pgpass file.
# Copy -Dest off this machine: a backup on the same disk is not a backup.

param(
    [Parameter(Mandatory)] [string] $PgBin,
    [Parameter(Mandatory)] [string] $Media,
    [Parameter(Mandatory)] [string] $Dest,
    [string] $Database = "qclab",
    [string] $User = "qclab_owner",
    [string] $PgHost = "127.0.0.1",
    [int] $Keep = 30
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$folder = Join-Path $Dest $stamp
New-Item -ItemType Directory -Force -Path $folder | Out-Null

$dump = Join-Path $folder "qclab.dump"
& (Join-Path $PgBin "pg_dump.exe") --host=$PgHost --username=$User --format=custom --file=$dump $Database
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }

# A dump that cannot be listed cannot be restored either.
& (Join-Path $PgBin "pg_restore.exe") --list $dump | Out-Null
if ($LASTEXITCODE -ne 0) { throw "The dump could not be read back" }

Compress-Archive -Path (Join-Path $Media "*") -DestinationPath (Join-Path $folder "media.zip")

Get-FileHash $dump, (Join-Path $folder "media.zip") -Algorithm SHA256 |
    ForEach-Object { "$($_.Hash)  $(Split-Path $_.Path -Leaf)" } |
    Set-Content (Join-Path $folder "SHA256SUMS.txt")

Get-ChildItem $Dest -Directory | Sort-Object Name -Descending | Select-Object -Skip $Keep |
    Remove-Item -Recurse -Force

Write-Output "Backed up to $folder"
