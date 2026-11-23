#!/usr/bin/env bash
# Development only: the API (Django) and the screens (Vite) together in one
# window. Ctrl+C stops both. Production is deploy/run.py behind nginx instead.
#
#     ./dev.sh                                  then open http://localhost:5173
#     BACKEND_PORT=8010 FRONTEND_PORT=5180 ./dev.sh    other ports, kept in step

set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
# manage.py and vite.config.ts both read BACKEND_PORT, so the screens find this API.
export BACKEND_PORT="${BACKEND_PORT:-8007}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
# Sign-in trusts only the screens' own address; 5173 is trusted by default.
if [ "$FRONTEND_PORT" != 5173 ] && [ -z "${DJANGO_CSRF_TRUSTED_ORIGINS:-}" ]; then
  export DJANGO_CSRF_TRUSTED_ORIGINS="http://localhost:$FRONTEND_PORT"
fi

PY="$ROOT/backend/.venv/Scripts/python.exe"           # Windows
[ -x "$PY" ] || PY="$ROOT/backend/.venv/bin/python"   # Linux, macOS
if [ ! -x "$PY" ]; then
  echo "backend/.venv is missing. Create it and install backend/requirements.txt first." >&2
  exit 1
fi
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "frontend/node_modules is missing. Run: cd frontend && npm install" >&2
  exit 1
fi
on_windows() { case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) return 0 ;; esac; return 1; }

port_busy() {
  if on_windows; then
    netstat -ano | grep LISTENING | grep -qE ":$1 "
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
  fi
}

# Windows: whoever listens on the port, and the processes above it. Only a QC Lab
# runserver or Vite from this folder is stopped; anything else is left alone.
FREE_PORT_PS=$(cat <<'PS'
$ProgressPreference = 'SilentlyContinue'
$port = [int]$env:QCLAB_PORT_TO_FREE
$root = $env:QCLAB_ROOT.ToLower()
$conn = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $conn) { exit 0 }
$procs = @{}
Get-CimInstance Win32_Process | ForEach-Object { $procs[[int]$_.ProcessId] = $_ }
$chain = @()
$p = $procs[[int]$conn.OwningProcess]
while ($p -and $chain.Count -lt 6) { $chain += $p; $p = $procs[[int]$p.ParentProcessId] }
$server = @($chain | Where-Object { $_.Name -match '^(python|node|cmd)' -and $_.CommandLine -match 'runserver|vite' })
$ours = @($server | Where-Object { ('' + $_.CommandLine + ' ' + $_.ExecutablePath).ToLower().Contains($root) })
if ($ours.Count -eq 0) {
  $who = if ($chain.Count) { $chain[0].Name + ' (process ' + $chain[0].ProcessId + ')' } else { 'process ' + $conn.OwningProcess }
  Write-Output ('Port ' + $port + ' is used by ' + $who + ', which is not a QC Lab server, so it was left alone.')
  exit 2
}
$top = $ours[-1]
Write-Output ('Stopping the QC Lab server already running on port ' + $port + ' (process ' + $top.ProcessId + ')...')
taskkill /T /F /PID $top.ProcessId | Out-Null
for ($i = 0; $i -lt 40; $i++) {
  if (-not (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)) { exit 0 }
  Start-Sleep -Milliseconds 250
}
Write-Output ('Port ' + $port + ' is still in use after stopping it.')
exit 1
PS
)

# A QC Lab server left running from before would answer instead of the new one,
# so it is stopped first.
free_port() {
  port_busy "$1" || return 0
  if on_windows; then
    QCLAB_PORT_TO_FREE="$1" QCLAB_ROOT="$(cygpath -w "$ROOT")" powershell.exe -NoProfile -NonInteractive \
      -EncodedCommand "$(printf '%s' "$FREE_PORT_PS" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)" && return 0
  else
    echo "Port $1 is already in use." >&2
  fi
  echo "Stop it yourself, or choose other ports: BACKEND_PORT=8010 FRONTEND_PORT=5180 ./dev.sh" >&2
  return 1
}
free_port "$BACKEND_PORT" || exit 1
free_port "$FRONTEND_PORT" || exit 1

# Each one starts children of its own (Django's reloader, Vite's node), so the
# whole tree is stopped, or a leftover keeps holding the port.
stop_tree() {
  if [ -r "/proc/$1/winpid" ]; then   # Git Bash on Windows
    taskkill //T //F //PID "$(cat "/proc/$1/winpid")" >/dev/null 2>&1
  else
    local child
    for child in $(pgrep -P "$1" 2>/dev/null); do stop_tree "$child"; done
    kill -TERM "$1" 2>/dev/null
  fi
}

(cd "$ROOT/backend" && exec "$PY" manage.py runserver "$BACKEND_PORT") &
API=$!
# --strictPort: if the port is taken, stop rather than quietly move to another.
(cd "$ROOT/frontend" && exec npm run dev -- --port "$FRONTEND_PORT" --strictPort) &
WEB=$!

stop() {
  trap - INT TERM EXIT
  echo
  echo "Stopping the API and the screens..."
  stop_tree "$API"
  stop_tree "$WEB"
  wait 2>/dev/null
}
trap 'stop; exit 130' INT
trap 'stop; exit 143' TERM
trap stop EXIT

echo "QC Lab: open http://localhost:$FRONTEND_PORT  (API on port $BACKEND_PORT). Ctrl+C stops both."

# If either stops on its own, stop the other too: half a system only misleads.
while kill -0 "$API" 2>/dev/null && kill -0 "$WEB" 2>/dev/null; do
  sleep 1
done
kill -0 "$API" 2>/dev/null || echo "The API stopped. Its message is above." >&2
kill -0 "$WEB" 2>/dev/null || echo "The screens stopped. Its message is above." >&2
exit 1
