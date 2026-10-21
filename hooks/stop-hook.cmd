: << 'CMDBLOCK'
@echo off
REM Stop hook shim, cross-platform polyglot. Two jobs only: call run.py, then
REM normalize the exit code. Keep this file pure ASCII -- see hooks/README.md
REM for why, for the polyglot mechanics, and for the exit-code rationale.
setlocal
set "RUNPY=%CLAUDE_PLUGIN_ROOT%\scripts\run.py"
if not exist "%RUNPY%" exit /b 0
where python >nul 2>nul
if errorlevel 1 exit /b 0
python "%RUNPY%" hook-stop
if "%ERRORLEVEL%"=="2" exit /b 2
exit /b 0
CMDBLOCK

# Unix branch. cmd.exe never reaches this: the batch block above always
# "exit /b" first, and the ": << 'CMDBLOCK'" line is read as a label.
RUNPY="${CLAUDE_PLUGIN_ROOT}/scripts/run.py"
[ -f "$RUNPY" ] || exit 0

# python3 first: on most Linux distributions bare "python" is absent, and where
# it does exist it can still be Python 2.
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done
[ -n "${PY:-}" ] || exit 0

"$PY" "$RUNPY" hook-stop
status=$?
[ "$status" = "2" ] && exit 2
exit 0
