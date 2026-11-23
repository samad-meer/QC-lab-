# Development only: runs dev.sh from PowerShell, so the API and the screens start
# together in this window. Ctrl+C stops both.
#
#     .\dev.ps1                                         then open http://localhost:5173
#     $env:BACKEND_PORT = 8010; $env:FRONTEND_PORT = 5180; .\dev.ps1    other ports

# The full path: a plain "bash" can start the Linux (WSL) one, where this cannot run.
$bash = Join-Path $env:ProgramFiles 'Git\bin\bash.exe'
if (-not (Test-Path $bash)) {
    Write-Error 'Git Bash was not found. Install Git for Windows, or run dev.sh from Git Bash.'
    exit 1
}
& $bash (Join-Path $PSScriptRoot 'dev.sh') @args
exit $LASTEXITCODE
