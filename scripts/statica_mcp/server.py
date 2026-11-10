"""stdio MCP 서버 - `run.py` 서브커맨드를 도구로 노출한다.

호출 하나가 `python run.py <subcommand> ...` 하위 프로세스 하나다. 같은 프로세스
안에서 핸들러를 부르지 않는 이유:

- 분석기나 그 하위 도구가 stdout 에 한 줄이라도 쓰면 MCP 스트림이 깨진다.
  하위 프로세스의 stdout 은 우리가 읽고 버리는 파이프라 그 위험이 없다.
- ``state.set_state_dir`` 같은 모듈 전역이 호출 사이에 새지 않는다.
- 훅 · 스킬과 **완전히 같은 경로**를 지난다. CLI 의 "stdout 에 JSON 하나"
  계약을 그대로 쓰므로 세 경로의 결과가 어긋날 수 없다.

Python 3.8 문법만 쓴다 (패키지 docstring 참조).
"""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import guides
from . import tools as catalog

SERVER_INFO = {"name": "statica-mcp", "title": "STATICA", "version": "0.1.0"}
# 최신이 앞. 클라이언트가 모르는 버전을 부르면 최신으로 답한다.
SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MIN_PYTHON = (3, 10)

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
RUN_PY = SCRIPTS_DIR / "run.py"

INSTRUCTIONS = """\
STATICA runs Suresoft STATIC static analysis on the local machine. STATIC \
produces the findings; these tools prepare, run and report that analysis and \
never fix defects in source code.
- Connecting a new project: read statica_get_guide topic=bootstrap first and \
follow it step by step. Explain what the connection does and get the user's \
approval before statica_bootstrap_begin. Resume an unfinished connection \
instead of starting over.
- statica_upload creates a team-visible server revision: call it only when \
the user explicitly asks to upload. statica_bootstrap_finish uploads the first \
analysis as part of an approved connection.
- Defect counts describe the analyzed scope, not the project total; say so, \
and do not list defects file by file.
- Ruleset, metric and report-generator changes apply to everyone using the \
server project. Read the current state first and confirm with the user.
- Never ask for, print or store the AccessKey.
- On setup errors run statica_doctor.
"""

# 오래 걸리는 호출에서 진행 알림을 보내는 간격(초). 클라이언트가 progressToken 을
# 줬을 때만 보낸다.
PROGRESS_INTERVAL = 15


def python_ok():
    return sys.version_info[:2] >= MIN_PYTHON


def _python_info():
    return {"executable": sys.executable,
            "version": "%d.%d.%d" % sys.version_info[:3],
            "supported": python_ok(),
            "required": "%d.%d+" % MIN_PYTHON}


def python_too_old():
    """3.10 미만으로 떴을 때의 응답. CLI 는 이 인터프리터로 돌 수 없다."""
    return {
        "ok": False, "code": "PYTHON_TOO_OLD",
        "message": ("STATICA needs Python %d.%d or later; this MCP server runs "
                    "on %s (%s)." % (MIN_PYTHON[0], MIN_PYTHON[1],
                                     _python_info()["version"],
                                     sys.executable)),
        "hint": ("Install Python %d.%d+ or point STATICA_PYTHON at one, then "
                 "restart the MCP client.") % MIN_PYTHON,
        "mcpServer": dict(SERVER_INFO, python=_python_info()),
    }


# --------------------------------------------------------------------------
# 하위 프로세스
# --------------------------------------------------------------------------

def _extract_json(text):
    """stdout 의 마지막 최상위 JSON 객체. CLI 는 하나만 내지만 방어한다."""
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    found = None
    idx = text.find("{")
    while idx >= 0:
        try:
            obj, end = decoder.raw_decode(text[idx:])
        except ValueError:
            idx = text.find("{", idx + 1)
            continue
        if isinstance(obj, dict):
            found = obj
        idx = text.find("{", idx + end)
    return found


def _popen_kwargs():
    if sys.platform == "win32":
        # 콘솔 없는 부모(MCP 클라이언트) 밑에서 콘솔 창이 뜨지 않게, 그리고
        # 시간 초과 때 트리째 끊을 수 있게 새 그룹으로 띄운다.
        flags = 0x08000000 | subprocess.CREATE_NEW_PROCESS_GROUP  # CREATE_NO_WINDOW
        return {"creationflags": flags}
    return {"start_new_session": True}


def _kill_tree(proc):
    """시간 초과한 호출을 분석기 손자까지 끊는다. 실패해도 조용히 넘어간다."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30,
                           creationflags=0x08000000)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


# MCPB 번들은 설치 경로를 자기 user_config 로 받아 이 변수로 넘긴다. CLI 가 읽는
# 변수와 이름이 다른 이유가 있다: MCPB 호스트는 사용자가 비워 둔 user_config 를
# 빈 문자열로 넘기는데, 그 빈 값을 ARACHNE_INSTALL_PATH 에 그대로 실으면 머신에
# 이미 있던 설치 경로를 덮어 STATIC 을 못 찾게 된다. 그래서 별도 변수로 받아,
# 값이 있을 때만 CLI 변수로 옮긴다.
INSTALL_PATH_ENV = "STATICA_INSTALL_PATH"
CLI_INSTALL_ENV = "ARACHNE_INSTALL_PATH"


def install_env(env):
    """STATICA_INSTALL_PATH 가 채워져 있으면 CLI 가 읽는 변수로 옮긴다.

    비어 있으면 아무것도 하지 않는다 - 머신에 이미 설정된 ARACHNE_INSTALL_PATH
    를 그대로 쓴다. 원본 매핑은 건드리지 않고 사본을 돌려준다.
    """
    override = (env.get(INSTALL_PATH_ENV) or "").strip()
    if override:
        env = dict(env)
        env[CLI_INSTALL_ENV] = override
    return env


def run_cli(argv, cwd=None, timeout=catalog.DEFAULT_TIMEOUT, on_tick=None):
    """``run.py argv...`` 를 돌려 (payload | None, 오류 문자열 | None).

    ``on_tick(경과초)`` 를 주면 기다리는 동안 PROGRESS_INTERVAL 마다 부른다.
    """
    env = install_env(dict(os.environ, PYTHONUTF8="1",
                           PYTHONIOENCODING="utf-8"))
    cmd = [sys.executable, str(RUN_PY)] + list(argv)
    try:
        # stdin 은 반드시 닫아 둔다. 물려주면 하위 프로세스가 MCP 메시지를
        # 가로채 읽을 수 있다.
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **_popen_kwargs())
    except OSError as exc:
        return None, "could not start run.py (%s)" % exc
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        remaining = timeout - elapsed
        if remaining <= 0:
            _kill_tree(proc)
            try:
                proc.communicate(timeout=30)
            except (subprocess.SubprocessError, OSError):
                pass
            return None, ("'%s' did not finish within %d seconds and was "
                          "stopped." % (argv[0], timeout))
        wait = min(remaining, PROGRESS_INTERVAL) if on_tick else remaining
        try:
            # TimeoutExpired 뒤에도 communicate 를 다시 부를 수 있다 (프로세스는
            # 살아 있고 읽은 출력은 보존된다).
            out, err = proc.communicate(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            if on_tick and time.monotonic() - started < timeout:
                on_tick(int(time.monotonic() - started))
    stdout = out.decode("utf-8", errors="replace")
    payload = _extract_json(stdout)
    if payload is None:
        detail = (err.decode("utf-8", errors="replace") or stdout).strip()[-2000:]
        return None, ("'%s' returned no JSON (exit %d).\n%s"
                      % (argv[0], proc.returncode, detail))
    return payload, None


def guide_result(arguments):
    """statica_get_guide. 하위 프로세스 없이 이 서버가 답한다."""
    text, failure = guides.read_guide(arguments.get("topic"))
    if text is None:
        return {"content": [{"type": "text", "text": failure}], "isError": True}
    return {"content": [{"type": "text", "text": text}], "isError": False}


def call_tool(spec, arguments, runner=run_cli, on_tick=None):
    """도구 하나를 실행해 MCP tools/call 결과를 만든다."""
    if spec.get("builtin") == "guide":
        # 문서 읽기라 CLI 도, 3.10 도 필요 없다.
        return guide_result(arguments)
    if not python_ok():
        payload = python_too_old()
        if spec["command"] != "doctor":
            payload["message"] = ("%s is unavailable: %s"
                                  % (spec["name"], payload["message"]))
        return _result(payload, is_error=True)

    project_dir = arguments.get("projectDir")
    kwargs = {"cwd": project_dir, "timeout": catalog.timeout_for(spec, arguments)}
    if on_tick is not None:
        kwargs["on_tick"] = on_tick
    payload, failure = runner(catalog.to_argv(spec, arguments), **kwargs)
    if payload is None:
        return {"content": [{"type": "text", "text": failure}], "isError": True}
    if spec["command"] == "doctor":
        # 이 서버가 어느 인터프리터로 떴는가. 훅 · 스킬과 다른 파이썬을 쓰고 있을
        # 수 있고, 그것이 "MCP 에서는 되는데 훅은 조용하다" 류의 답이다.
        payload["mcpServer"] = dict(SERVER_INFO, python=_python_info(),
                                    runPy=str(RUN_PY))
    return _result(payload, is_error=payload.get("ok") is False)


def _result(payload, is_error):
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


# --------------------------------------------------------------------------
# JSON-RPC
# --------------------------------------------------------------------------

def negotiate_protocol(requested):
    return requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]


class Server:
    """메시지 하나씩 받아 답을 ``send`` 로 보낸다.

    오래 걸리는 tools/call 은 작업자 스레드 하나가 순서대로 처리한다. 읽기 루프는
    그동안에도 ping · tools/list · 취소를 받는다. 작업자가 하나뿐인 이유: 같은
    워크스페이스에 분석을 겹쳐 돌리면 STATIC 의 상태 파일이 서로를 덮는다.

    취소: 대기 중인 호출은 시작하지 않는다. **이미 도는 호출은 끝까지 둔다** -
    분석 중간에 끊으면 워크스페이스가 반쯤 쓰인 상태로 남는다. 답만 보내지 않는다.
    """

    def __init__(self, send, runner=run_cli):
        self._send = send
        self._runner = runner
        self._tools = [catalog.tool_listing(t) for t in catalog.TOOLS]
        self._pending = queue.Queue()
        self._lock = threading.Lock()
        self._outstanding = set()
        self._abandoned = set()
        self._worker = threading.Thread(target=self._work, name="statica-mcp")
        # 데몬이 아니다: 클라이언트가 떠나도 도는 분석은 마저 끝낸다.
        self._worker.start()

    # -- 응답 ------------------------------------------------------------
    def _result(self, rid, value):
        self._send({"jsonrpc": "2.0", "id": rid, "result": value})

    def _error(self, rid, code, message):
        self._send({"jsonrpc": "2.0", "id": rid,
                    "error": {"code": code, "message": message}})

    # -- 작업자 ----------------------------------------------------------
    def _work(self):
        while True:
            item = self._pending.get()
            if item is None:
                return
            rid, spec, arguments, token = item
            with self._lock:
                skip = rid in self._abandoned
            if not skip:
                on_tick = None
                if token is not None:
                    def on_tick(elapsed, token=token, name=spec["name"]):
                        self._send({"jsonrpc": "2.0",
                                    "method": "notifications/progress",
                                    "params": {"progressToken": token,
                                               "progress": elapsed,
                                               "message": "%s still running "
                                                          "(%ds)" % (name,
                                                                     elapsed)}})
                try:
                    value = call_tool(spec, arguments, self._runner, on_tick)
                except Exception as exc:  # noqa: BLE001 - 작업자는 죽으면 안 된다
                    value = {"content": [{"type": "text", "text": (
                        "%s failed unexpectedly (%s)."
                        % (spec["name"], type(exc).__name__))}], "isError": True}
                with self._lock:
                    skip = rid in self._abandoned
                if not skip:
                    self._result(rid, value)
            with self._lock:
                self._outstanding.discard(rid)
                self._abandoned.discard(rid)

    def _cancel(self, rid):
        with self._lock:
            # 이미 답했거나 받은 적 없는 id 는 기억하지 않는다. 클라이언트가 그
            # id 를 다시 쓰면 그 답을 잃게 된다.
            if rid in self._outstanding:
                self._abandoned.add(rid)

    def close(self):
        """입력이 끝났다. 이미 받은 호출은 마저 처리하고 작업자를 끝낸다.

        stdin 을 닫고도 stdout 은 계속 읽는 클라이언트가 있다. 받아 둔 호출을
        버리면 그 답이 사라진다. 클라이언트가 정말 떠났다면 send 가 조용히 실패할
        뿐이다. 클라이언트가 프로세스를 끝내면 이 일 자체가 없다.
        """
        self._pending.put(None)

    def join(self, timeout=None):
        self._worker.join(timeout)

    # -- 요청 ------------------------------------------------------------
    def handle_line(self, line):
        line = line.strip()
        if not line:
            return
        try:
            req = json.loads(line)
        except ValueError:
            self._error(None, -32700, "Parse error: line is not valid JSON")
            return
        if not isinstance(req, dict):
            self._error(None, -32600, "Invalid Request: expected a JSON object")
            return
        method = req.get("method")
        params = req.get("params")
        if not isinstance(params, dict):
            params = {}
        if "id" not in req:  # 알림 - 답하지 않는다
            if method == "notifications/cancelled":
                self._cancel(params.get("requestId"))
            return
        rid = req["id"]
        if not isinstance(method, str):
            self._error(rid, -32600, "Invalid Request: 'method' must be a string")
            return

        if method == "initialize":
            self._result(rid, {
                "protocolVersion": negotiate_protocol(params.get("protocolVersion")),
                "capabilities": {"tools": {"listChanged": False},
                                 "prompts": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            })
        elif method == "ping":
            self._result(rid, {})
        elif method == "tools/list":
            self._result(rid, {"tools": self._tools})
        elif method == "tools/call":
            self._tools_call(rid, params)
        elif method == "prompts/list":
            self._result(rid, {"prompts": guides.prompt_listing()})
        elif method == "prompts/get":
            arguments = params.get("arguments")
            value, failure = guides.get_prompt(
                params.get("name"), arguments if isinstance(arguments, dict) else {})
            if value is None:
                self._error(rid, -32602, failure)
            else:
                self._result(rid, value)
        else:
            self._error(rid, -32601, "Method not found: %s" % method)

    def _tools_call(self, rid, params):
        name = params.get("name")
        spec = catalog.by_name(name) if isinstance(name, str) else None
        if spec is None:
            self._error(rid, -32602, "Unknown tool: %s" % name)
            return
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        bad = catalog.validate(spec, arguments, os.path.isabs, os.path.isdir)
        if bad is not None:
            # 입력 오류는 도구 결과로 돌려준다 - 모델이 읽고 고쳐 다시 부를 수
            # 있어야 한다 (JSON-RPC 오류는 클라이언트가 삼키는 경우가 있다).
            self._result(rid, {"content": [{"type": "text", "text": (
                "%s: %s" % (name, bad))}], "isError": True})
            return
        if spec.get("builtin"):
            # 문서 읽기는 줄을 세우지 않는다. 긴 분석이 작업자를 잡고 있는 동안에도
            # 절차를 읽을 수 있어야 한다.
            self._result(rid, call_tool(spec, arguments))
            return
        meta = params.get("_meta")
        token = meta.get("progressToken") if isinstance(meta, dict) else None
        with self._lock:
            self._outstanding.add(rid)
        self._pending.put((rid, spec, arguments, token))


def ensure_utf8_stdio():
    """한국어 Windows 에서 파이프가 cp949 로 열리는 것을 막는다 (run.py 와 같다)."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main():
    ensure_utf8_stdio()
    lock = threading.Lock()

    def send(message):
        # ensure_ascii: 선로 위는 ASCII 만. 콘솔 인코딩이 무엇이든 깨지지 않는다.
        line = json.dumps(message, ensure_ascii=True) + "\n"
        with lock:
            try:
                sys.stdout.write(line)
                sys.stdout.flush()
            except (OSError, ValueError):
                pass  # 클라이언트가 이미 떠났다

    if not python_ok():
        sys.stderr.write("statica-mcp: Python %s is too old; serving the "
                         "environment report only.\n" % _python_info()["version"])
    server = Server(send)
    try:
        for line in sys.stdin:
            server.handle_line(line)
    finally:
        server.close()
    return 0
