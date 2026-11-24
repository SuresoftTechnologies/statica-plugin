: << 'CMDBLOCK'
@echo off
REM Stop hook shim, cross-platform polyglot. Two jobs only: call run.py, then
REM normalize the exit code (2 = ask the agent to continue, anything else = 0).
REM Keep this file pure ASCII with LF line endings, and do not use labels or
REM goto: cmd.exe mis-handles them in LF files.
REM
REM run.py is found next to this file (..\scripts\run.py), so the same shim
REM works in the plugin and in the STATIC Agent Kit (agent_kit\plugins\hooks).
REM In the Agent Kit layout its bundled Python (agent_kit\python) is used;
REM otherwise the python on PATH.
setlocal
set "HOOKDIR=%~dp0"
set "RUNPY=%HOOKDIR%..\scripts\run.py"
if not exist "%RUNPY%" exit /b 0
set "KIT=%HOOKDIR%..\.."
set "PY="
if exist "%KIT%\python\python.exe" if exist "%KIT%\plugins\scripts\run.py" set "PY=%KIT%\python\python.exe"
if not defined PY (
    where python >nul 2>nul
    if errorlevel 1 exit /b 0
    set "PY=python"
)
"%PY%" "%RUNPY%" hook-stop
if "%ERRORLEVEL%"=="2" exit /b 2
exit /b 0
CMDBLOCK

# Unix branch. cmd.exe never reaches this: the batch block above always
# "exit /b" first, and the ": << 'CMDBLOCK'" line is read as a label.
HOOKDIR="$(cd "$(dirname "$0")" && pwd)"
RUNPY="$HOOKDIR/../scripts/run.py"
[ -f "$RUNPY" ] || exit 0

# Agent Kit layout (agent_kit/plugins/hooks): use the bundled Python.
KIT="$HOOKDIR/../.."
PY=""
if [ -f "$KIT/plugins/scripts/run.py" ]; then
    for candidate in "$KIT/python/bin/python3" "$KIT/python/python3" "$KIT/python/python.exe"; do
        if [ -x "$candidate" ]; then
            PY="$candidate"
            break
        fi
    done
fi

# Otherwise python3 first: on most Linux distributions bare "python" is absent,
# and where it does exist it can still be Python 2.
if [ -z "$PY" ]; then
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PY="$candidate"
            break
        fi
    done
fi
[ -n "$PY" ] || exit 0

"$PY" "$RUNPY" hook-stop
status=$?
[ "$status" = "2" ] && exit 2
exit 0
