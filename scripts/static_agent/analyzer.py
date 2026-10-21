import subprocess

from .budget import UNBOUNDED_CHILD_TIMEOUT_SECONDS
from .changes import module_dirs
from .errors import PluginError
from .paths import bin_path, is_windows
from .workspace import read_json

# 확장자를 붙이지 않는다 — `paths.bin_path` 가 OS 를 보고 `.exe` 를 붙인다.
ANALYZER_EXE = "analyzer-csa"

# java · kotlin · python · csharp 을 맡는 다른 실행 파일. 옵션도 종료 코드 체계도
# analyzer-csa 와 다르므로 아래 표를 이쪽에 적용하지 않는다 (`plugin_exit_hint` 참조).
PLUGIN_EXE = "analyzer-plugin"

# analyzer-csa 의 종료 코드는 평평한 값이 아니라 **합성된** 값이다.
#
#     AnalyzerExceptionFactory.createException():
#         int exitCode = analyzerStep.getStepCode() + this.exitCode;
#
# 즉 "어느 단계에서 터졌는가"(AnalyzerStep.stepCode, 1000 단위)와 "무엇이
# 터졌는가"(AnalyzerExceptionFactory 의 base code)를 더한 값이다. 같은 원인이라도
# 단계가 다르면 코드가 다르다 — 워크스페이스 잠금(120)은 공통 단계에서는 120 이지만
# TU 분석 중에 걸리면 1120 이다. 그래서 표를 코드 전체로 만들면 안 되고,
# 단계와 원인을 따로 두고 조회 시점에 분해해야 한다.

# AnalyzerStep.java 의 stepCode / stepName.
ANALYZER_STEPS = {
    0: "공통",
    1: "TU 분석",
    2: "link 분석",
    3: "RTE(런타임 오류) 분석",
    4: "DB 처리",
    5: "프로젝트 처리",
}

# AnalyzerExceptionFactory.java 의 base code -> 한국어 원인 설명.
# 단계 코드가 더해지기 전의 값이라 1000 미만이다.
ANALYZE_EXIT_CODES = {
    1: "알 수 없는 예외가 발생했습니다.",
    2: "분석 대상 파일을 찾지 못했습니다.",
    3: "분석 대상이 모두 제외되었습니다. 스코프 설정을 확인하세요.",
    10: "module.capture.json 을 처리하지 못했습니다.",
    11: "rule.config.json 을 처리하지 못했습니다.",
    12: "analysis.scope.json 을 처리하지 못했습니다.",
    13: "compile.capture.json 을 처리하지 못했습니다.",
    14: "wrapper.config.json 을 처리하지 못했습니다.",
    15: "wrapper.toolchain.json 을 처리하지 못했습니다.",
    16: "ci.ini 를 처리하지 못했습니다.",
    17: "컴파일러 conf 파일을 처리하지 못했습니다.",
    18: "parser.conf 를 처리하지 못했습니다.",
    19: ".csencodings 를 처리하지 못했습니다.",
    20: "listing.files 를 처리하지 못했습니다.",
    21: "cal 파일을 처리하지 못했습니다.",
    22: "lib.cal 을 처리하지 못했습니다.",
    23: "psionic.ini 를 처리하지 못했습니다.",
    24: "ignore.ini 를 처리하지 못했습니다.",
    25: "rule.ini 를 처리하지 못했습니다.",
    26: "psionic.xml 을 처리하지 못했습니다.",
    27: "전처리 파일을 처리하지 못했습니다.",
    28: "로그 파일을 처리하지 못했습니다.",
    29: "소스 파일을 읽지 못했습니다.",
    30: "link.result.ci 를 처리하지 못했습니다.",
    31: "rule.db 를 처리하지 못했습니다.",
    32: "module.view.db 를 처리하지 못했습니다.",
    33: ".inf 파일을 처리하지 못했습니다.",
    34: "문서 규칙 파일(__MISRA__DIR__RULES__)을 처리하지 못했습니다.",
    35: "project.metric.json 을 처리하지 못했습니다.",
    36: "analyze.failed.json 을 처리하지 못했습니다.",
    40: "디렉터리 생성에 실패했습니다.",
    41: "디렉터리 복사에 실패했습니다.",
    42: "TU 디렉터리를 처리하지 못했습니다.",
    50: "데이터베이스에 접근하지 못했습니다.",
    51: "DB 스키마가 분석기와 맞지 않아 갱신하지 못했습니다.",
    52: "link 분석 데이터를 해석하지 못했습니다. link.result.ci 를 확인하세요.",
    53: "RTE 분석 데이터를 해석하지 못했습니다. psionic.xml 을 확인하세요.",
    54: "sourcefiles.db 를 처리하지 못했습니다.",
    100: "서버 API 호출에 실패했습니다.",
    110: "라이선스 확인에 실패했습니다.",
    111: "라이선스가 만료되었거나 유효하지 않습니다.",
    112: "서버에 프로젝트가 없습니다.",
    113: "같은 프로젝트를 다른 클라이언트가 이미 분석 중입니다.",
    114: "라이선스 동시 실행 한도를 초과했습니다.",
    115: "서버가 X-Revision-Id 헤더를 주지 않았습니다.",
    116: "라이선스 획득에 실패했습니다.",
    117: "분석 세션이 만료되었습니다(하트비트 타임아웃).",
    120: "워크스페이스가 다른 프로세스에 잠겨 있습니다.",
    130: ".zip 업로드에 실패했습니다.",
    200: "명령을 객체로 변환하지 못했습니다.",
    201: "입력 명령을 해석하지 못했습니다.",
    300: "오류 .zip 내보내기에 실패했습니다.",
    301: "분석 전에 검증이 실행되었습니다. 분석 후에 검증하세요.",
    302: "입력 데이터 검증에 실패했습니다.",
}

# analyzer.run 이 제한 시간 초과 때 스스로 붙이는 센티널. 분석기가 낸 코드가 아니라서
# 단계/원인으로 분해되지 않으므로 분해보다 먼저 걸러야 한다 (파이썬에서 -1 // 1000 은
# -1, -1 % 1000 은 999 라 그냥 분해하면 엉뚱한 결과가 나온다).
TIMEOUT_RETURNCODE = -1

_SENTINEL_HINTS = {
    TIMEOUT_RETURNCODE: "분석기가 제한 시간을 초과하여 강제 종료되었습니다.",
}


def exit_code_hint(code):
    """종료 코드를 단계 + 원인으로 분해해 한국어 한 문장으로 만든다.

    step = code // 1000 (AnalyzerStep.stepCode), base = code % 1000
    (AnalyzerExceptionFactory 의 base code). 단계가 COMMON(0)이면 코드가 곧 base 라
    평평한 120 같은 값도 그대로 해석된다.
    """
    if code in _SENTINEL_HINTS:
        return _SENTINEL_HINTS[code]
    if code < 0:
        return f"분석기가 종료 코드 {code} 로 실패했습니다."

    step, base = divmod(code, 1000)
    stage = ANALYZER_STEPS.get(step)
    if stage is None:
        # PROJECT(5000)를 넘는 단계는 분석기에 없다 — 우리가 모르는 코드다.
        return f"분석기가 종료 코드 {code} 로 실패했습니다."

    cause = ANALYZE_EXIT_CODES.get(base, "알 수 없는 원인입니다.")
    # 구분자는 CP949 로 인코딩되는 문자만 쓴다 (em dash 는 CP949 에 없다).
    return f"{stage} 단계에서 실패했습니다: {cause} (종료 코드 {code})"


# 분석기 출력의 인코딩. Windows 에서는 활성 코드페이지(한국어 환경이면 CP949)로
# 나오고, 리눅스에서는 UTF-8 이다. 리눅스에서 CP949 로 풀면 한글 경로가 든 줄이
# 통째로 깨진다 — 사용자에게 보이는 실패 메시지가 거기서 나온다.
OUTPUT_ENCODING = "cp949" if is_windows() else "utf-8"


def decode(raw):
    """분석기·wrapper-forge 의 바이트 출력을 문자열로 푼다.

    `text=True` 를 쓰지 않고 언제나 바이트를 받아 여기서 푸는 이유는
    docs/architecture.md 함정 2 에 있다.
    """
    return (raw or b"").decode(OUTPUT_ENCODING, errors="replace")


def run(args, cwd, timeout=UNBOUNDED_CHILD_TIMEOUT_SECONDS):
    """분석기를 돌린다.

    기본값은 훅 예산에 묶이지 않는 넉넉한 제한 시간이다. 훅 아래에서 도는
    호출자는 남은 예산으로 깎은 값을 반드시 명시해서 넘겨야 한다 — 남은
    예산을 아는 것은 호출한 쪽뿐이므로, 여기서 훅 상수를 직접 읽지 않는다.
    """
    exe = bin_path(ANALYZER_EXE)
    if not exe.is_file():
        raise PluginError("ANALYZER_NOT_FOUND", f"분석기를 찾을 수 없습니다: {exe}")
    try:
        proc = subprocess.run([str(exe)] + list(args), cwd=str(cwd),
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return {
            "command": list(args),
            "returncode": -1,
            "stdout": decode(e.stdout or b"").strip(),
            "stderr": decode(e.stderr or b"").strip(),
        }
    return {
        "command": list(args),
        "returncode": proc.returncode,
        "stdout": decode(proc.stdout).strip(),
        "stderr": decode(proc.stderr).strip(),
    }


def _finish(raw):
    ok = raw["returncode"] == 0
    out = dict(raw, ok=ok)
    if not ok:
        out["hint"] = exit_code_hint(raw["returncode"])
    return out


def _options(parallel, force):
    args = []
    if parallel is not None:
        args += ["-p", str(parallel)]
    if force:
        args.append("-f")
    return args


def analyze_tu(ws, tu_dir, project_key, parallel=None, force=False, timeout=None):
    """TU 하나를 분석한다.

    ``timeout`` 은 호출자가 정한다. None 이면 훅 예산에 묶이지 않는 기본값을
    쓴다 — 훅 아래에서 도는 pipeline.run_analyze 는 남은 예산으로 깎은 값을
    매 호출마다 계산해서 넘긴다.
    """
    args = ["analyze", "-t", str(tu_dir), "-k", project_key] + _options(parallel, force)
    if timeout is None:
        timeout = UNBOUNDED_CHILD_TIMEOUT_SECONDS
    return _finish(run(args, cwd=ws, timeout=timeout))


def analyze_module(ws, module_dir, project_key, parallel=None, force=False,
                   timeout=None):
    """모듈 하나를 분석한다.

    `-t` 와 결정적으로 다른 점은 **없는 TU 디렉터리를 만든다**는 것이다. 새로
    캡처된 소스는 TU 가 없어 `-t` 로는 손댈 수 없으므로, 그 소스를 처음 분석에
    태우는 길은 이것뿐이다 - `-w` 도 만들어 주지만 서버 업로드까지 하므로 훅
    아래에서 쓸 수 없다 (업로드는 /statica:upload 의 몫이다).

    대가는 범위다. 모듈의 TU 를 전부 훑으므로 캐시가 다 맞아도 TU 하나보다 비싸다.
    그래서 부르는 쪽(pipeline)이 modules_missing_tus 로 대상을 좁히고 예산을 잰다.
    """
    args = (["analyze", "-m", str(module_dir), "-k", project_key]
            + _options(parallel, force))
    if timeout is None:
        timeout = UNBOUNDED_CHILD_TIMEOUT_SECONDS
    return _finish(run(args, cwd=ws, timeout=timeout))


def analyze_workspace(ws, project_key, parallel=None):
    # 전체 분석은 /statica:upload 로만 들어온다 — Stop 훅이 아니라 슬래시 커맨드라서
    # 훅 예산(budget.py)에 묶이지 않는다. 그래서 일부러 더 넉넉하게 준다.
    args = ["analyze", "-w", str(ws), "-k", project_key] + _options(parallel, False)
    return _finish(run(args, cwd=ws, timeout=3600))


# analyzer-plugin 은 몇 초에 끝난다 (실측: java 3파일 4.6초, python 1파일 6초).
# 그래도 넉넉히 준다 - csharp 은 솔루션을 실제로 빌드하므로 분 단위로 갈 수 있다.
PLUGIN_TIMEOUT_SECONDS = 1800


def plugin_exit_hint(code, output):
    """analyzer-plugin 실패를 사람이 읽을 한 문장으로.

    analyzer-csa 의 `단계*1000 + 원인` 표를 여기 쓰지 않는다. 다른 실행 파일이고
    코드 체계가 같다는 근거가 없다 - 남의 표로 번역하면 그럴듯한 거짓 원인이
    나오고, 그건 원인을 모른다고 말하는 것보다 나쁘다. 대신 분석기가 실제로 찍은
    마지막 줄을 그대로 보여준다.
    """
    if code == TIMEOUT_RETURNCODE:
        return "분석기가 제한 시간을 초과하여 강제 종료되었습니다."
    tail = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if tail:
        return f"분석기가 종료 코드 {code} 로 실패했습니다: {tail[-1][:300]}"
    return f"분석기가 종료 코드 {code} 로 실패했습니다."


def run_plugin(args, cwd, timeout=PLUGIN_TIMEOUT_SECONDS):
    """`analyzer-plugin` 을 돌린다. `run()` 과 같은 모양을 돌려준다."""
    exe = bin_path(PLUGIN_EXE)
    if not exe.is_file():
        raise PluginError("ANALYZER_NOT_FOUND", f"분석기를 찾을 수 없습니다: {exe}")
    try:
        proc = subprocess.run([str(exe)] + list(args), cwd=str(cwd),
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return {
            "command": list(args),
            "returncode": TIMEOUT_RETURNCODE,
            "stdout": decode(e.stdout or b"").strip(),
            "stderr": decode(e.stderr or b"").strip(),
        }
    return {
        "command": list(args),
        "returncode": proc.returncode,
        "stdout": decode(proc.stdout).strip(),
        "stderr": decode(proc.stderr).strip(),
    }


def analyze_plugin(ws, language, project_key, agent_json, project_dir, timeout=None,
                   *, upload=False):
    """전량 분석한다. 기본은 로컬 저장, 명시적 upload=True 일 때만 업로드한다."""
    from . import languages as langs
    args = langs.analyze_args(ws, language, project_key, agent_json, project_dir,
                             upload=upload)
    if timeout is None:
        timeout = PLUGIN_TIMEOUT_SECONDS
    raw = run_plugin(args, cwd=ws, timeout=timeout)
    ok = raw["returncode"] == 0
    out = dict(raw, ok=ok)
    if not ok:
        # 실패 사유는 stdout 에 찍히는 일이 많다 (예: 옵션 오류). 둘 다 본다.
        out["hint"] = plugin_exit_hint(
            raw["returncode"], (raw.get("stderr") or "") + "\n" + (raw.get("stdout") or ""))
    return out


def read_failures(ws):
    """모듈별 analyze.failed.json 을 모아 {모듈명: 내용} 으로 돌려준다."""
    out = {}
    for module in module_dirs(ws):
        data = read_json(module / "analyze.failed.json")
        if not data:
            continue
        if (data.get("moduleFailure") or data.get("fileFailures")):
            out[module.name] = data
    return out
