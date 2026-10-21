"""부트스트랩 — 에이전트가 판단하고 CLI 가 단계를 집행한다.

한 번에 끝나는 함수가 아니다. 치환이 GUI 조작인 환경이 있어서 중간에 사람을
기다려야 하고, 그래서 단계마다 상태를 워크스페이스에 남겨 재개할 수 있어야 한다.

    begin   워크스페이스 생성 + wrapper 생성. 이후 되돌릴 것이 생긴다.
    guard   에이전트가 프로젝트 파일을 고치기 전에 원본을 보관.
    verify  빌드 후 캡처가 실제로 생겼는지 판정.
    finish  서버 프로젝트 생성 + ready 표시.
    abort   프로젝트 파일 원복 + 워크스페이스 제거.

각 단계는 서로 다른 프로세스에서 불릴 수 있다. 단계 사이의 상태는 전부
워크스페이스 안에 있다 — `agent.json`(projectPath·status·ide·compiler·wrapper)
과 스냅샷 색인이다. 파이썬 변수로 들고 가는 것은 없다. 어떤 단계든 프로젝트
경로 하나만으로 자기 워크스페이스를 다시 찾는다.

환경 식별·컴파일러 탐색·치환 방법 결정은 여기서 하지 않는다. 에이전트가
`skills/statica-analyze-bootstrap/` 의 가이드를 읽고 판단한다.
"""
import shutil
import subprocess
from pathlib import Path

from . import (capture, forge_vocab, languages, server_api, snapshot, toolchain,
               workspace)
from .analyzer import decode
from .errors import PluginError
from .paths import bin_path, works_root
from .vendor import forge
from .vendor import project_api as papi

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "assets"
TEMPLATE_DIR = PACKAGE_DIR / "templates"


def wrapper_dir_for(wrapper_name):
    """이 wrapper 의 디렉터리. 치환은 이 경로를 가리켜야 한다.

    설치본에서 `wrapper` 는 `works` 의 형제다 (`config/wrapper_forge.json` 의
    `substitution.wrapper_dir` 과 같은 값이고, 옛 `_config()` 도 이렇게 덮어썼다).
    그 아래 wrapper 이름으로 디렉터리가 하나 생긴다 — `vendor/substitution.py` 의
    `plan()` 이 쓰는 규칙과 같다.
    """
    return Path(works_root()).parent / "wrapper" / wrapper_name


def remove_wrapper(wrapper_name, timeout=120):
    """`wrapper-forge remove -n <name>` — begin 이 만든 wrapper 를 지운다.

    `vendor/forge.py` 는 원본과 바이트 동일하게 유지해야 하므로 여기 둔다.
    실패해도 예외를 내지 않는다: 호출하는 쪽(abort)은 이걸 부수 정리로 다루고,
    남은 wrapper 하나 때문에 워크스페이스 삭제를 포기해서는 안 된다.
    """
    result = {"ok": False, "name": wrapper_name, "returncode": None,
              "output": "", "message": ""}
    try:
        exe = bin_path("wrapper-forge")
    except PluginError as e:
        result["message"] = e.message
        return result
    args = [str(exe), "remove", "-n", str(wrapper_name)]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        result["message"] = (f"wrapper 삭제가 {timeout}초 안에 끝나지 않았습니다: "
                             f"{wrapper_name}")
        return result
    except OSError as e:
        result["message"] = (f"wrapper 삭제를 실행하지 못했습니다: {wrapper_name} "
                             f"({type(e).__name__})")
        return result
    result["returncode"] = proc.returncode
    result["output"] = (decode(proc.stdout) + "\n" + decode(proc.stderr)).strip()[:2000]
    result["ok"] = proc.returncode == 0
    result["message"] = (f"wrapper {wrapper_name} 를 지웠습니다." if result["ok"]
                         else f"wrapper {wrapper_name} 를 지우지 못했습니다 "
                              f"(종료 코드 {proc.returncode}).")
    return result


# 서버 응답에서 결과 JSON 으로 옮겨도 되는 필드. 이 경로가 이 플러그인에서 유일하게
# 인증 정보를 만지는 곳이므로, 새 필드가 늘어도 새지 않도록 화이트리스트로 받는다.
_PROJECT_CREATION_FIELDS = ("ran", "ok", "key", "status",
                            "created", "existed", "message", "code")


def _safe_project_creation(created):
    return {k: created[k] for k in _PROJECT_CREATION_FIELDS if k in (created or {})}


def _abs(path):
    """경로를 절대 경로로 편다 — **저장하기 전에** 쓴다.

    `agent.json` 의 `projectPath` 와 스냅샷 색인의 키가 이 값으로 만들어진다.
    `.` 이나 상대 경로가 그대로 저장되면 다른 디렉터리에서 부른 다음 단계가
    엉뚱한 것을 가리킨다 — 특히 `abort` 는 "되돌릴 것이 없다"며 성공을 보고하고,
    프로젝트는 치환된 채 남는다.

    조회 쪽에서는 쓰지 않는다. 조회는 `workspace.find_workspace_for` 가 양쪽
    철자를 스스로 편다 — 두 군데서 각자 펴면 한쪽만 바뀌었을 때 조용히 어긋난다.

    Git Bash 가 넘기는 `/c/...` 형태는 MSYS 가 파이썬에 닿기 전에 `C:\\...` 로
    바꿔 준다. 여기서 POSIX 경로를 따로 변환하면 안 된다 — `C:\\c\\...` 가 된다.
    """
    return workspace.resolve_path(path)


def _guarded_path(project_dir, raw):
    """`--file` 값을 프로젝트 기준 절대 경로로 편다.

    스냅샷 색인의 키는 경로 문자열의 md5 다. 같은 파일을 절대 경로로 한 번,
    상대 경로로 한 번 보관하면 항목이 둘이 되고, 두 번째 '원본' 은 이미 치환된
    내용이다. 복원은 그 나쁜 사본을 나중에 덮어쓰고도 성공을 보고한다.
    """
    path = Path(raw)
    if not path.is_absolute():
        path = Path(project_dir) / path
    return _abs(path)


def _find_ws(project_dir):
    """부트스트랩 중이든 끝났든, 이 프로젝트에 묶인 워크스페이스.

    경로를 여기서 펴지 않는다 — 조회가 스스로 편다 (`_abs` 주석 참조).
    """
    return workspace.find_workspace_for(project_dir)


_NAME_HINT = ("워크스페이스 이름은 서버 프로젝트 키(영문자로 시작하는 영숫자 3~20자)로 "
              "바뀌고, works 아래 디렉터리 이름과 wrapper 이름으로도 그대로 쓰입니다. "
              "영문자로 시작해 영숫자가 3자 이상 남도록, 경로 구분자 없이 지으세요 "
              "(예: myproj, cpp_demo).")


def validate_name(name):
    """워크스페이스 이름이 끝까지 쓸 수 있는 이름인지 본다.

    `begin` 이 이것을 부르지 않으면 어떻게 되는지가 이 함수의 존재 이유다:
    `--name "c++"` 도 `--name "3d"` 도 워크스페이스 생성 · wrapper 생성 · 치환 ·
    전체 빌드를 전부 통과한 뒤, 마지막 `finish` 에서 서버 프로젝트 키를 만들지
    못해 죽는다. 그 시점엔 사용자의 빌드 한 판이 이미 날아간 뒤다.

    경로 구분자도 여기서 막는다. 이름은 디렉터리 이름으로 그대로 쓰이는데,
    `iter_workspaces` 는 works 바로 아래 한 겹만 훑으므로 중첩된 디렉터리에
    만들어진 워크스페이스는 두 번 다시 조회되지 않는다.
    """
    raw = name if isinstance(name, str) else ""
    if not raw.strip():
        raise PluginError("BAD_WORKSPACE_NAME",
                          "워크스페이스 이름이 비어 있습니다.", _NAME_HINT)
    if any(sep in raw for sep in ("/", "\\")):
        raise PluginError(
            "BAD_WORKSPACE_NAME",
            f"워크스페이스 이름에 경로 구분자를 쓸 수 없습니다: {raw}", _NAME_HINT)
    key, error = papi.project_key_from_name(raw)
    if error:
        raise PluginError(
            "BAD_WORKSPACE_NAME",
            f"이 이름으로는 서버 프로젝트 키를 만들 수 없습니다: {raw}", _NAME_HINT)
    return key


def _require_ws(project_dir):
    ws = _find_ws(project_dir)
    if ws is None:
        raise PluginError(
            "NO_BOOTSTRAP_IN_PROGRESS",
            f"이 프로젝트에 진행 중인 부트스트랩이 없습니다: {project_dir}",
            "먼저 bootstrap-begin 을 실행하세요.")
    return ws


def _seed_plugin_workspace(ws, language, project_path, options=None):
    """analyzer-plugin 워크스페이스의 `app.data.json` 을 놓는다.

    C/C++ 은 템플릿 파일을 복사하지만(`forge.seed_workspace`) 여기서는 직접 쓴다.
    템플릿은 `language: CCPP` 로 고정돼 있고, 언어마다 `options` 의 모양도 다르다
    (csharp 만 targetConfiguration · netEnvironment 를 갖는다 — STATIC GUI 가
    만든 워크스페이스를 그대로 따랐다).

    `projectKey` 는 비워 둔다. 서버에 프로젝트를 만든 뒤 `finish` 가 채운다.
    """
    return workspace.write_json(Path(ws) / workspace.APP_DATA_REL, {
        "projectKey": "",
        "language": language.server,
        "projectPath": str(project_path),
        "options": options or {},
        "numOfParallel": 0,
        "useCache": True,
    })


def _create_server_project(ws, language):
    """서버에 프로젝트를 만들고 app.data.json 의 projectKey 를 채운다.

    이미 있으면(HTTP 409) 성공으로 친다 — 그래서 두 번 불러도 안전하고,
    java · kotlin 은 실제로 두 번 불린다 (`begin` 과 `finish`).

    **소유자를 넘기지 않는다.** `POST /v1/projects` 의 `email` 이 선택이라, 비우면
    서버가 accessKey 로 계정을 찾아 소유자로 삼는다 (`server_api` 모듈 docstring 참조).
    """
    return server_api.create_project(ws, Path(ws).name, language)


# 빌드 플러그인이 기술서를 만들려면 **그 전에** 서버에 프로젝트가 있어야 한다.
# 실측: 없는 키로 gradle `static` 태스크를 돌리면 기술서를 쓰기도 전에
# `response code: 500. internal server error` 로 죽는다. `-Dstatic.skipAnalysis=true`
# 로 분석을 건너뛰어도 마찬가지다 — 키 확인은 그보다 먼저 일어난다.
#
# 그래서 이 두 언어만 서버 등록이 `finish` 가 아니라 `begin` 으로 앞당겨진다.
# 나머지는 우리가 analyzer-plugin 을 직접 부르므로 `finish` 에서 만들어도 늦지 않다.
_NEEDS_PROJECT_AT_BEGIN = ("java", "kotlin")


def _plugin_input_hint(ws, language, key):
    """begin 이 마지막에 하는 말 — 이제 무엇을 준비해야 분석할 수 있는가.

    언어마다 준비물이 다르다. 이 문장이 없으면 에이전트는 워크스페이스만 만들어
    놓고 `bootstrap-finish` 로 직행했다가 "기술서가 없습니다" 로 막힌다.
    """
    descriptor = languages.descriptor_path(ws, language)
    if language.id in _NEEDS_PROJECT_AT_BEGIN:
        return (f"이제 빌드 플러그인으로 분석 기술서를 만드세요. 프로젝트의 원래 "
                f"빌드 명령 뒤에 세 옵션을 붙이면 됩니다: "
                f"--init-script=<설치경로>\\bin\\build-plugin\\gradle\\static.gradle "
                f"-Dstatic.key={key} \"-Dstatic.output={ws}\" "
                f"-Dstatic.skipAnalysis=true static. 기술서가 {descriptor} 에 "
                "생기면 bootstrap-verify 를 실행하세요. maven 과 자세한 절차는 "
                "statica-analyze-bootstrap 스킬의 other-languages.md 에 있습니다.")
    if language.id == "python":
        return (f"기술서 없이 바로 분석할 수 있습니다(프로젝트 루트를 분석기가 "
                f"직접 훑습니다). 가상환경 경로를 손으로 지정하고 싶을 때만 "
                f"{descriptor} 를 만드세요. 이어서 bootstrap-verify 를 실행하세요.")
    return ("준비물이 더 없습니다. 이어서 bootstrap-verify 를 실행하세요.")


def _begin_plugin(project_dir, name, language, build_command=None,
                  input_path=None, csharp_configuration=None, csharp_target=None):
    """java · kotlin · python · csharp 의 begin.

    C/C++ 판보다 훨씬 짧다. 여기에는 wrapper 도, 치환도, 컴파일러 검증도 없다 —
    analyzer-plugin 은 빌드를 가로채지 않고 소스와 기술서만 본다. 그래서 이
    단계가 **사용자 프로젝트 파일을 전혀 건드리지 않는다**는 점도 다르다
    (`guard` 가 필요 없고, `abort` 가 되돌릴 것도 없다).
    """
    project_dir = _abs(project_dir)
    result = {"ok": True, "command": "bootstrap-begin",
              "projectDir": str(project_dir), "language": language.id}

    # 여기서는 이름이 쓸 만한지 확인만 한다. 실제 키는 워크스페이스 디렉터리
    # 이름에서 나오고(`papi.create_and_fill` 이 그렇게 만든다), 그 이름은 충돌하면
    # `_2` 가 붙어 달라질 수 있다 — 아래에서 다시 구한다.
    validate_name(name)

    if language.id == "csharp":
        if not input_path:
            result.update(ok=False, stage="input", message=(
                "csharp 은 분석할 솔루션(.sln) 또는 프로젝트(.csproj) 경로가 "
                "필요합니다."), hint="--input <솔루션 경로> 를 주고 다시 실행하세요.")
            return result
        resolved_input = _guarded_path(project_dir, input_path)
        if not resolved_input.is_file():
            result.update(ok=False, stage="input",
                          message=f"분석 입력을 찾을 수 없습니다: {resolved_input}")
            return result
        result["inputPath"] = str(resolved_input)
    else:
        resolved_input = None

    existing = _find_ws(project_dir)
    if existing is not None:
        result["ok"] = False
        result["stage"] = "existing-workspace"
        result["workspace"] = str(existing)
        result["workspaceName"] = Path(existing).name
        result["status"] = workspace.status(workspace.read_agent_json(existing))
        result["message"] = (
            f"이 프로젝트에는 이미 워크스페이스가 있습니다: {Path(existing).name} "
            f"(상태: {result['status']}).")
        result["hint"] = ("진행 중이면 이어서 bootstrap-verify · bootstrap-finish 를, "
                          "처음부터 다시 하려면 bootstrap-abort 를 실행하세요.")
        return result

    ws_name = workspace.free_workspace_name(name)
    ws = forge.create_workspace(works_root(), ws_name)
    result["workspace"] = str(ws)
    result["workspaceName"] = ws_name
    # 실제 프로젝트 키는 디렉터리 이름에서 나온다 — 이름이 충돌해 `_2` 가 붙었으면
    # `--name` 에서 뽑은 값과 다르다. 빌드 플러그인에 넘길 키가 이것이므로,
    # 여기서 다시 구하지 않으면 에이전트가 존재하지 않는 키로 빌드를 돌린다.
    key, _ = papi.project_key_from_name(ws_name)
    result["projectKey"] = key

    try:
        options = {}
        if language.id == "csharp":
            options = {"targetConfiguration": csharp_configuration or "",
                       "netEnvironment": csharp_target or ""}
        # app.data.json 의 projectPath 는 STATIC GUI 를 따라 **분석 입력**을 적는다
        # (csharp 워크스페이스는 실제로 .sln 경로가 들어 있었다). 우리가 워크스페이스를
        # 역조회할 때 보는 것은 agent.json 의 projectPath 이므로 서로 달라도 된다.
        result["seeded"] = [str(_seed_plugin_workspace(
            ws, language, resolved_input or project_dir, options))]

        agent = {
            "projectPath": str(project_dir),
            languages.LANGUAGE_KEY: language.id,
            "buildCommand": build_command,
        }
        if resolved_input is not None:
            agent[languages.INPUT_PATH_KEY] = str(resolved_input)
        if csharp_configuration:
            agent[languages.CSHARP_CONFIGURATION_KEY] = csharp_configuration
        if csharp_target:
            agent[languages.CSHARP_TARGET_KEY] = csharp_target
        workspace.write_agent_json(ws, workspace.set_status(
            agent, workspace.STATUS_BOOTSTRAPPING))
    except PluginError:
        shutil.rmtree(ws, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(ws, ignore_errors=True)
        raise PluginError("BOOTSTRAP_FAILED",
                          f"부트스트랩 begin 단계에서 예상치 못한 오류가 났습니다 "
                          f"({type(e).__name__}).",
                          "환경을 확인한 뒤 다시 시도하세요.") from e

    result["descriptorPath"] = str(languages.descriptor_path(ws, language) or "")
    result["message"] = (f"{language.id} 워크스페이스 {ws_name} 를 만들었습니다. ")

    if language.id in _NEEDS_PROJECT_AT_BEGIN:
        # 빌드 플러그인이 서버에 프로젝트가 없으면 기술서도 못 만든다
        # (_NEEDS_PROJECT_AT_BEGIN 주석). 그래서 여기서 먼저 만든다.
        created = _create_server_project(ws, language)
        result["projectCreation"] = _safe_project_creation(created)
        if not (created or {}).get("ok"):
            # 워크스페이스는 남겨 둔다. 서버 문제(주소·소유자 이메일)는 고친 뒤
            # 같은 워크스페이스로 이어서 하면 되고, 지우면 사용자가 방금 고른
            # 이름과 설정을 다시 입력해야 한다.
            result["ok"] = False
            result["stage"] = "project"
            result["message"] += ("다만 서버에 프로젝트를 만들지 못했습니다: "
                                  + ((created or {}).get("message") or "")).strip()
            result["hint"] = ("Arachne 설정의 서버 주소와 AccessKey 를 확인한 뒤 "
                              "bootstrap-finish 를 실행하면 이어서 시도합니다. "
                              "그 전에는 빌드 플러그인이 기술서를 만들지 못합니다.")
            return result

    result["message"] += _plugin_input_hint(ws, language, key)
    return result


def begin(project_dir, name, ide, compiler, compiler_path, build_command=None,
          language=languages.CCPP, input_path=None,
          csharp_configuration=None, csharp_target=None):
    """워크스페이스와 wrapper 를 만든다. 이 단계까지는 프로젝트를 건드리지 않는다.

    소유자 이메일을 받지 않는다. 서버가 accessKey 로 계정을 찾아
    소유자로 삼는다 — 예전에는 이 값을 클라이언트가 정해야 했고, 대상 서버에 없는
    주소면 빌드까지 다 끝낸 마지막 단계에서 404 로 죽었다 (`server_api` 참조).

    워크스페이스를 만든 뒤 어떤 이유로든 실패하면 그 디렉터리를 지운다 — 남기면
    재시도할 때마다 `_2`, `_3` 이름이 쌓인다. 아직 프로젝트 파일은 손대지 않았고
    스냅샷도 없으므로, 이 단계의 정리는 잃을 것이 없다.

    `language` 가 C/C++ 이 아니면 완전히 다른 절차로 간다 (`_begin_plugin`).
    `ide` · `compiler` · `compiler_path` 는 그쪽에서 쓰이지 않는다.
    """
    language = languages.get(languages.normalize(language))
    if languages.is_plugin(language.id):
        return _begin_plugin(project_dir, name, language,
                             build_command=build_command,
                             input_path=input_path,
                             csharp_configuration=csharp_configuration,
                             csharp_target=csharp_target)

    # 여기서 한 번 펴 둔다. 이 값이 agent.json 에 들어가고, 이후 모든 단계가
    # 자기 워크스페이스를 이 문자열로 찾는다.
    project_dir = _abs(project_dir)
    result = {"ok": True, "command": "bootstrap-begin",
              "projectDir": str(project_dir), "ide": ide, "compiler": compiler,
              "compilerPath": str(compiler_path)}

    # 검증이 먼저다 — 잘못된 값으로 워크스페이스를 만들면 정리 비용만 든다.
    # 이름은 마지막 `finish` 에서야 서버 프로젝트 키가 되므로, 여기서 막지 않으면
    # 치환과 전체 빌드를 다 끝낸 뒤에 죽는다.
    validate_name(name)
    forge_vocab.validate(ide, compiler)

    # 이후 모든 단계는 프로젝트 경로로 자기 워크스페이스를 되찾는다. 같은 경로에
    # 워크스페이스가 둘이면 그 조회가 어느 쪽을 집을지 알 수 없게 되므로, 이미
    # 있으면 새로 만들지 않는다 — 이어서 하든 abort 하든 에이전트가 정한다.
    existing = _find_ws(project_dir)
    if existing is not None:
        result["ok"] = False
        result["stage"] = "existing-workspace"
        result["workspace"] = str(existing)
        result["workspaceName"] = Path(existing).name
        result["status"] = workspace.status(workspace.read_agent_json(existing))
        result["message"] = (
            f"이 프로젝트에는 이미 워크스페이스가 있습니다: {Path(existing).name} "
            f"(상태: {result['status']}).")
        result["hint"] = ("진행 중이면 이어서 bootstrap-verify · bootstrap-finish 를, "
                          "처음부터 다시 하려면 bootstrap-abort 를 실행하세요.")
        return result

    verification = toolchain.verify_compiler(compiler_path)
    result["compilerVerification"] = verification
    if not verification["ok"]:
        result["ok"] = False
        result["stage"] = "verify-compiler"
        result["message"] = verification["message"]
        return result

    ws_name = workspace.free_workspace_name(name)
    ws = forge.create_workspace(works_root(), ws_name)
    result["workspace"] = str(ws)
    result["workspaceName"] = ws_name

    def fail(stage, message):
        result["ok"] = False
        result["stage"] = stage
        result["message"] = message
        shutil.rmtree(ws, ignore_errors=True)
        return result

    try:
        result["seeded"] = forge.seed_workspace(ws, TEMPLATE_DIR)

        # wrapper 이름은 워크스페이스 이름과 같다. works 안에서 이름이 유일하므로
        # wrapper 도 유일해지고, `vendor/substitution.py` 가 워크스페이스 이름으로
        # wrapper 디렉터리를 계산하는 규칙과도 어긋나지 않는다.
        wrapper_name = ws_name
        forged = forge.run_wrapper_forge(
            bin_path("wrapper-forge"), wrapper_name, ide.casefold(),
            compiler.casefold(), str(Path(compiler_path).parent), ws,
            decode=decode)
        result["forge"] = forged
        if not forged["ok"]:
            return fail("forge",
                        f"wrapper 생성에 실패했습니다. {(forged.get('stderr') or '')[:500]}")

        result["wrapperName"] = wrapper_name
        result["wrapperDir"] = str(wrapper_dir_for(wrapper_name))

        agent = {
            "projectPath": str(project_dir),
            "buildCommand": build_command,
            "ide": ide.casefold(),
            "compiler": compiler.casefold(),
            "compilerPath": str(compiler_path),
            "wrapperName": wrapper_name,
            "wrapperDir": result["wrapperDir"],
        }
        workspace.write_agent_json(ws, workspace.set_status(
            agent, workspace.STATUS_BOOTSTRAPPING))
    except PluginError:
        shutil.rmtree(ws, ignore_errors=True)
        raise
    except Exception as e:
        # 원본 예외 텍스트는 담지 않는다 — 민감정보를 물고 있지 않다고 장담할 수
        # 없으므로 예외 타입만 남기고 PluginError 로 바꿔 올린다 (cli.main 이 이것을
        # JSON 객체 하나로 렌더링한다).
        shutil.rmtree(ws, ignore_errors=True)
        raise PluginError("BOOTSTRAP_FAILED",
                          f"부트스트랩 begin 단계에서 예상치 못한 오류가 났습니다 "
                          f"({type(e).__name__}).",
                          "환경을 확인한 뒤 다시 시도하세요.") from e

    result["message"] = (
        f"워크스페이스 {ws_name} 와 wrapper {wrapper_name} 를 만들었습니다. "
        "이제 치환을 적용하고 빌드한 뒤 bootstrap-verify 를 실행하세요.")
    return result


def guard(project_dir, files):
    """프로젝트 파일을 고치기 전에 원본을 보관한다.

    보관본은 워크스페이스 안에 들어간다. 그래서 이 뒤로는 워크스페이스를 함부로
    지울 수 없다 — 되돌릴 유일한 사본이 거기 있다 (`abort` 참조).
    """
    ws = _require_ws(project_dir)
    resolved = [_guarded_path(_abs(project_dir), f) for f in files]
    taken = snapshot.take(ws, resolved)
    return {"ok": True, "command": "bootstrap-guard", "workspace": str(ws),
            "snapshot": taken,
            "message": f"파일 {len(taken['entries'])}개의 원본을 보관했습니다. "
                       "되돌리려면 bootstrap-abort 를 실행하세요."}


def _plugin_readiness(ws, agent_json, language):
    """analyzer-plugin 워크스페이스가 분석을 시작할 수 있는 상태인가.

    `capture.summarize` 와 같은 자리다 — 이 갈래에는 캡처가 없으므로, 대신
    **분석 입력이 실제로 있는가**를 묻는다. 여기서 거르지 않으면 `finish` 가
    서버에 프로젝트를 만들어 놓고 첫 분석에서 "기술서가 없습니다"로 죽는다.

    `ok` 의 뜻은 양쪽이 같다: 분석할 것이 생겼는가.
    """
    summary = {"ok": False, "language": language.id, "kind": None, "path": None}

    if language.id == "csharp":
        source = languages.input_path(agent_json)
        summary["kind"] = "input"
        summary["path"] = str(source) if source else None
        if source is None:
            summary["message"] = ("분석 입력(.sln 또는 .csproj)이 기록되어 있지 "
                                  "않습니다. bootstrap-abort 후 --input 을 주고 "
                                  "다시 시작하세요.")
            return summary
        summary["ok"] = source.is_file()
        summary["message"] = (f"분석 입력을 확인했습니다: {source}" if summary["ok"]
                              else f"분석 입력을 찾을 수 없습니다: {source}")
        return summary

    descriptor = languages.descriptor_path(ws, language)
    summary["kind"] = "descriptor"
    summary["path"] = str(descriptor)
    if not descriptor.is_file():
        if not language.descriptor_required:
            # python 루트 모드. 기술서가 없는 것이 정상이다.
            summary["ok"] = True
            summary["kind"] = "root"
            summary["path"] = (agent_json or {}).get("projectPath")
            summary["message"] = ("기술서 없이 프로젝트 루트를 직접 분석합니다.")
            return summary
        summary["message"] = (
            f"분석 기술서가 없습니다: {descriptor}. 빌드 플러그인으로 기술서를 "
            "먼저 만드세요 (statica-analyze-bootstrap 스킬의 '타 언어' 항목).")
        return summary

    data = workspace.read_json(descriptor)
    modules = (data or {}).get("modules")
    if not isinstance(modules, list) or not modules:
        summary["message"] = (
            f"기술서를 읽었지만 모듈이 하나도 없습니다: {descriptor}. 빌드가 "
            "실제로 소스를 컴파일했는지 확인하고 기술서를 다시 만드세요.")
        return summary
    summary["ok"] = True
    summary["modules"] = len(modules)
    summary["message"] = (f"기술서를 확인했습니다: 모듈 {len(modules)}개 "
                          f"({descriptor}).")
    return summary


def readiness(ws, agent_json):
    """이 워크스페이스가 분석을 시작할 수 있는 상태인가 — 언어를 가려 묻는다."""
    language = languages.get(languages.of_agent_json(agent_json))
    if languages.is_plugin(language.id):
        return _plugin_readiness(ws, agent_json, language)
    return capture.summarize(ws)


def verify(project_dir):
    """분석을 시작할 수 있는 상태인지 확인한다.

    C/C++ 은 빌드가 실제로 캡처를 남겼는지 본다 — 빌드가 성공했다는 것과 wrapper
    를 탔다는 것은 다른 이야기라, 여기서 거르지 않으면 분석할 것이 없는
    워크스페이스가 조용히 남는다. 타 언어는 캡처 대신 분석 기술서(또는 csharp 의
    솔루션 경로)가 준비됐는지 본다.
    """
    ws = _require_ws(project_dir)
    summary = readiness(ws, workspace.read_agent_json(ws) or {})
    return {"ok": summary["ok"], "command": "bootstrap-verify",
            "workspace": str(ws), "capture": summary,
            "message": summary["message"]}


def _same_spelling(text):
    """경로 비교용 정규화 — 구분자와 대소문자만 무시한다."""
    return text.replace("\\", "/").casefold()


def build_command_warning(agent_json):
    """`buildCommand` 가 wrapper 를 타지 않을 것 같으면 그 사실을 한 문장으로.

    커맨드라인 치환(A)은 `bootstrap-begin` 이 끝난 뒤에야 `wrapperDir` 을 알 수
    있어서, 스킬이 에이전트에게 `agent.json` 의 `buildCommand` 를 손으로 고치라고
    시킨다. 사람이(모델이) 하는 일이라 빠뜨릴 수 있고, 빠뜨리면 이후 재빌드가
    전부 wrapper 없이 돌아 새 소스가 영영 캡처되지 않는다 — 빌드는 성공하므로
    아무도 오류를 내지 않는다. 정확히 이 플러그인이 없애려던 침묵이다.

    **실패가 아니라 경고다.** 파일 치환(B)과 GUI 치환(C)은 원본 명령 그대로가
    맞다 — 치환이 Makefile 이나 IDE 설정에 남아 있어 원본 명령도 wrapper 를 탄다.
    여기서 판정할 수 있는 것은 "확실히 탄다"가 아니라 "탈 근거가 안 보인다"뿐이라,
    막으면 정상적인 B·C 프로젝트를 못 끝내게 된다.
    """
    command = workspace.build_command(agent_json)
    wrapper = workspace.wrapper_dir(agent_json)
    if not command or not wrapper:
        return None
    if _same_spelling(wrapper) in _same_spelling(command):
        return None
    # 구분자로 em dash 를 쓰지 않는다. cp949 로 인코딩되지 않아, 이 문장이 콘솔로
    # 나가는 경로에서 통째로 UnicodeEncodeError 를 낸다 (analyzer.exit_code_hint 와
    # 같은 이유이며, 그쪽도 같은 이유로 콜론을 쓴다).
    return (f"agent.json 의 buildCommand 에 wrapperDir({wrapper}) 이 없습니다: "
            "커맨드라인 치환(A)을 썼다면 이 명령을 치환된 명령으로 고치세요. "
            "고치지 않으면 이후 재빌드가 wrapper 를 거치지 않아 새로 추가한 소스가 "
            "캡처되지 않고 조용히 분석에서 빠집니다. 파일·GUI 치환(B·C)이라면 "
            "원본 명령 그대로가 맞으니 무시해도 됩니다.")


def finish(project_dir):
    """캡처를 다시 확인하고, 서버에 프로젝트를 만들고, ready 로 표시한다.

    서버 등록에 실패하면 상태를 그대로 `bootstrapping` 으로 둔다 — 그래야 다시
    부를 수 있고, 그 사이 분석이 시작되지 않는다.
    """
    ws = _require_ws(project_dir)
    result = {"ok": True, "command": "bootstrap-finish", "workspace": str(ws)}

    agent = workspace.read_agent_json(ws) or {}
    language = languages.get(languages.of_agent_json(agent))
    result["language"] = language.id

    summary = readiness(ws, agent)
    result["capture"] = summary
    if not summary["ok"]:
        result["ok"] = False
        result["stage"] = "verify"
        result["message"] = summary["message"]
        return result

    # 치환 경로 A 의 손편집이 빠졌는지 여기서 한 번 본다. 실패로 치지 않는다 —
    # B·C 는 원본 명령 그대로가 맞다 (build_command_warning 주석 참조).
    # 타 언어에는 wrapperDir 이 없어 언제나 None 이 나온다 (치환 자체가 없다).
    warning = build_command_warning(agent)
    if warning:
        result["buildCommandWarning"] = warning
    # 소유자는 서버가 accessKey 로 정한다. 그것이 누구인지는 v1 응답에 없어서
    # 우리도 말하지 않는다 - 모르는 것을 아는 척하면 사용자가 그 말을 믿는다.
    created = _create_server_project(ws, language)
    result["projectCreation"] = _safe_project_creation(created)
    if not (created or {}).get("ok"):
        result["ok"] = False
        result["stage"] = "project"
        result["message"] = (f"서버에 프로젝트를 만들지 못했습니다. "
                             f"{(created or {}).get('message') or ''}").strip()
        return result

    workspace.write_agent_json(ws, workspace.set_status(agent, workspace.STATUS_READY))
    snapshot.discard(ws)
    result["message"] = (f"부트스트랩을 마쳤습니다. 워크스페이스 {Path(ws).name} 가 "
                         "분석 준비 상태입니다.")
    if warning:
        # 결과 필드만으로는 읽히지 않는다 — 사람에게 닿는 문장에도 실어야 한다.
        result["message"] += f" 다만 {warning}"

    result["fullAnalysis"] = _full_analysis(project_dir)
    if result["fullAnalysis"].get("ok"):
        result["message"] += " 이어서 전체 분석과 업로드까지 마쳤습니다."
    else:
        result["message"] += (
            " 다만 이어서 돌린 전체 분석은 실패했습니다: "
            f"{result['fullAnalysis'].get('message') or ''}").rstrip()
    return result


def _full_analysis(project_dir):
    """finish 의 마지막 단계 — 워크스페이스 전체를 분석하고 서버에 올린다.

    왜 증분(analyze)이 아니라 전체(upload)인가. 부트스트랩 직후의 증분 분석은
    **언제나** "변경된 대상이 없습니다"로 끝난다 — 방금 돈 전체 빌드가 모든
    TU 캐시를 소스보다 나중으로 만들어 놓았기 때문이다. 그래서 여기서 한 번
    전체를 돌려 기준선을 만들지 않으면, 사용자는 부트스트랩을 끝까지 마치고도
    결과가 하나도 없는 프로젝트를 받는다. 서버 쪽도 마찬가지다 — 방금 만든
    프로젝트에 revision 이 없으면 웹 UI 에 보여줄 것이 없다.

    전체 분석이 무거운 작업이라 평소에는 `/statica:upload` 로만 들어오지만, 여기는
    프로젝트당 한 번뿐인 자리다. 사용자에게 물어보지 않는다.

    **어떤 실패도 밖으로 내지 않는다.** 여기까지 왔으면 워크스페이스는 이미
    `ready` 이고 서버 프로젝트도 만들어졌다 — 부트스트랩 자체는 끝난 것이다.
    분석만 다시 돌리면 되는 상황을 부트스트랩 실패로 보고하면, 에이전트가
    멀쩡히 끝난 것을 되돌리려 든다.
    """
    from . import upload
    try:
        return upload.run_upload(project_dir)
    except PluginError as e:
        return dict(e.to_dict(), command="upload")
    except Exception as e:
        # cli.main 과 같은 규율 — 원본 예외 텍스트는 담지 않는다.
        return {"ok": False, "command": "upload", "code": "INTERNAL_ERROR",
                "message": "전체 분석 중 예상치 못한 오류가 발생했습니다 "
                           f"({type(e).__name__})."}


def abort(project_dir, reason=""):
    """프로젝트 파일을 되돌리고 워크스페이스를 지운다.

    **되돌리기가 실패하면 아무것도 지우지 않는다.** 보관본이 워크스페이스 안에 있어서,
    지우는 순간 사용자의 원본이 세상에서 사라진다. 실패는 삼키지 말고 어떤 파일이
    남았고 보관본이 어디 있는지 그대로 올린다.

    이미 부트스트랩을 마친(`ready`) 워크스페이스는 건드리지 않는다 — 그것을 지우면
    캡처와 분석 캐시가 통째로 날아간다. abort 는 '진행 중인 시도를 물리는' 것이지
    '끝난 연결을 해제하는' 것이 아니다.
    """
    result = {"ok": True, "command": "bootstrap-abort", "reason": reason,
              "restore": None, "workspaceRemoved": False, "wrapperRemoval": None}
    ws = _find_ws(project_dir)
    if ws is None:
        result["message"] = "되돌릴 부트스트랩이 없습니다."
        return result
    result["workspace"] = str(ws)

    agent = workspace.read_agent_json(ws) or {}
    result["status"] = workspace.status(agent)
    if result["status"] != workspace.STATUS_BOOTSTRAPPING:
        # 프로젝트 파일도 건드리지 않는다 — 되돌릴 것이 있다면 그건 이 워크스페이스가
        # 진행 중이던 시절의 것이 아니다.
        result["ok"] = False
        result["stage"] = "already-bootstrapped"
        result["message"] = (
            f"워크스페이스 {Path(ws).name} 는 이미 부트스트랩을 마쳤습니다"
            f"(상태: {result['status']}). 되돌릴 것이 없어 아무것도 지우지 않았습니다.")
        result["hint"] = (
            "연결을 정말 끊으려면 사용자에게 확인한 뒤 **먼저 치환을 되돌리고** "
            "워크스페이스를 직접 지우세요. 순서가 중요합니다: finish 가 원본 보관본을 "
            "이미 버렸으므로, 파일을 고쳐 치환한 프로젝트(B)는 워크스페이스를 지운 뒤에는 "
            "되돌릴 근거가 남지 않고 사라진 wrapper 경로를 가리킨 채 빌드가 깨집니다. "
            "환경별 되돌리기 절차는 statica-analyze-bootstrap 스킬의 environments.md "
            "'되돌리기' 항목에 있습니다. 다시 캡처하려면 빌드 후 pre-analyze 를 실행하면 됩니다.")
        return result

    restored = snapshot.restore(ws)
    result["restore"] = restored
    if not restored["ok"]:
        result["ok"] = False
        result["snapshotDir"] = str(Path(ws) / snapshot.SNAPSHOT_REL)
        result["message"] = restored["message"]
        return result

    # wrapper 도 같이 지운다. 남겨 두면 같은 이름으로 다시 begin 할 때 forge 가 충돌한다.
    # 실패해도 abort 자체는 실패로 치지 않는다 — 남은 wrapper 하나 때문에 워크스페이스
    # 삭제를 포기하는 쪽이 더 나쁘다.
    #
    # 타 언어는 애초에 wrapper 를 만들지 않는다. 그런데도 부르면 wrapper-forge 가
    # "그런 이름 없다"로 실패하고, 그 실패가 abort 메시지에 붙어 사용자에게
    # 있지도 않았던 문제를 보고하게 된다.
    if languages.is_plugin(languages.of_agent_json(agent)):
        removal = {"ok": True, "name": None, "returncode": None, "output": "",
                   "message": "이 언어는 wrapper 를 만들지 않아 지울 것이 없습니다."}
    else:
        removal = remove_wrapper(agent.get("wrapperName") or Path(ws).name)
    result["wrapperRemoval"] = removal

    shutil.rmtree(ws, ignore_errors=True)
    result["workspaceRemoved"] = not Path(ws).exists()
    result["message"] = ("프로젝트 파일을 되돌리고 워크스페이스를 지웠습니다."
                         if result["workspaceRemoved"]
                         else "프로젝트 파일은 되돌렸으나 워크스페이스를 완전히 지우지 못했습니다.")
    if not removal["ok"]:
        result["message"] += (f" 다만 wrapper {removal['name']} 는 남아 있습니다: "
                              f"{removal['message']}")
    return result
