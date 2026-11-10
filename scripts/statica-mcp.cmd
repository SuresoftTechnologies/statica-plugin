: << 'CMDBLOCK'
@echo off
REM STATICA MCP server launcher, cross-platform polyglot (same mechanics as
REM hooks/stop-hook.cmd). Keep this file pure ASCII. stdout belongs to the MCP
REM stream, so nothing here may print to it.
REM
REM Picks the interpreter by running it, not by finding it on PATH: on Windows
REM "python" is often the Microsoft Store alias stub, which exists on PATH but
REM exits 49 without running anything.
REM Order: STATICA_PYTHON, py -3, python, python3. Python 3.10+ is preferred;
REM an older one is still started so the server can say what is wrong.
setlocal
set "SERVER=%~dp0mcp_server.py"
if defined STATICA_PYTHON (
    "%STATICA_PYTHON%" "%SERVER%"
    exit /b
)
for %%P in ("py -3" python python3) do (
    %%~P -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        %%~P "%SERVER%"
        exit /b
    )
)
for %%P in ("py -3" python python3) do (
    %%~P -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        %%~P "%SERVER%"
        exit /b
    )
)
echo statica-mcp: no working Python found. Install Python 3.10+ or set STATICA_PYTHON. 1>&2
exit /b 1
CMDBLOCK

# Unix branch. cmd.exe never reaches this: the batch block above always
# "exit /b" first, and the ": << 'CMDBLOCK'" line is read as a label.
DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SERVER="$DIR/mcp_server.py"

if [ -n "${STATICA_PYTHON:-}" ]; then
    exec "$STATICA_PYTHON" "$SERVER"
fi
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        exec "$candidate" "$SERVER"
    fi
done
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        exec "$candidate" "$SERVER"
    fi
done
echo "statica-mcp: no working Python found. Install Python 3.10+ or set STATICA_PYTHON." >&2
exit 1
