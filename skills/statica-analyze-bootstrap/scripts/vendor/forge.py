"""워크스페이스 생성과 wrapper-forge 실행. 기존 스킬 forge_wrapper.py 에서 떼어낸 부분."""
import shutil
import subprocess
from pathlib import Path


def create_workspace(works_root, name):
    ws = Path(works_root) / name
    ws.mkdir(parents=True, exist_ok=False)
    return ws


def seed_workspace(ws, template_dir):
    """templates/app.data.json 을 .staticdata/.app/ 로 복사해 완전한 워크스페이스로 만든다."""
    dest = Path(ws) / ".staticdata" / ".app" / "app.data.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(template_dir) / "app.data.json", dest)
    return [str(dest)]


def run_wrapper_forge(exe, name, ide, compiler, compiler_dir, ws, decode=None):
    """`decode` 는 출력 바이트를 문자열로 푸는 함수. 생략하면 원본 그대로 CP949 다.

    파라미터로 뺀 이유: 리눅스 Arachne 는 UTF-8 로 출력하는데 여기서 CP949 로
    풀면 한글이 든 실패 메시지가 통째로 깨진다. 이 파일은 검증된 원본 자산이라
    로직을 고치지 않는 것이 규율이므로, 기본값은 손대지 않고 호출하는 쪽
    (`bootstrap.begin`)이 플랫폼에 맞는 함수를 넘기게 했다.
    """
    args = [str(exe), "add", "-n", name, "-i", ide, "-c", compiler,
            "-p", str(compiler_dir), "-w", str(ws)]
    proc = subprocess.run(args, capture_output=True, timeout=600)
    if decode is None:
        decode = lambda b: (b or b"").decode("cp949", errors="replace")
    return {
        "ok": proc.returncode == 0,
        "command": args,
        "returncode": proc.returncode,
        "stdout": decode(proc.stdout).strip(),
        "stderr": decode(proc.stderr).strip(),
    }
