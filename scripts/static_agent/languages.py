"""언어별로 갈리는 것만 모아 둔다. 나머지는 전부 공통이다.

이 플러그인은 두 갈래의 분석기를 부린다.

    C/C++      analyzer-csa    빌드 캡처 -> TU 단위 증분 분석 -> upload 때만 업로드
    그 외 4종  analyzer-plugin 기술서(descriptor) -> 전량 분석 -> upload 때만 업로드

두 갈래가 실제로 다른 것은 셋뿐이다: **무엇을 실행하는가**, **무엇을 기준선으로
변경을 재는가**, **결함을 어디서 읽는가**. 워크스페이스 조회 · 상태 · 스위치 ·
Stop 훅 · 슬래시 커맨드는 두 갈래가 그대로 공유한다. 그래서 갈림길을 여기 한
군데로 모으고, 바깥에서는 `is_plugin()` 한 번만 묻는다.

**언어는 워크스페이스의 성질이지 프로젝트의 성질이 아니다.** `agent.json` 의
`language` 에 적히고, 필드가 없으면 `ccpp` 다 — 이 필드가 생기기 전에 만들어진
C/C++ 워크스페이스가 전부 그렇고, 그것들을 다른 언어로 잘못 읽으면 분석이
통째로 엉뚱한 실행 파일로 간다.
"""
import collections
from pathlib import Path

from .errors import PluginError

CCPP = "ccpp"
LANGUAGE_KEY = "language"

# agent.json 에 들어가는 언어별 부속 필드. 이름을 아는 곳을 이 모듈로 한정한다.
INPUT_PATH_KEY = "inputPath"                 # csharp: .sln / .csproj 절대경로
CSHARP_CONFIGURATION_KEY = "csharpConfiguration"
CSHARP_TARGET_KEY = "csharpTarget"

# analyzer-plugin 이 만드는 산출물. 네 언어가 전부 같은 이름을 쓴다 (실측).
SOURCEFILES_DB = "sourcefiles.db"
DEFECT_JSON = "defect.json"

Language = collections.namedtuple("Language", (
    "id",            # agent.json 에 적히는 값, analyzer-plugin 의 서브커맨드 이름
    "server",        # 서버 ProjectCreationDto.language
    "descriptor",    # 워크스페이스 안 기술서 파일 이름 (없으면 None)
    "extensions",    # 프로젝트 트리에서 이 언어의 소스로 볼 확장자
    "skip_dirs",     # 이 언어에서 추가로 건너뛸 디렉터리 이름
    "descriptor_required",   # 기술서 없이는 분석을 시작할 수 없는가
    "scope_rel",     # 워크스페이스 기준 analysis.scope.json 위치
))

# 분석 범위 파일이 어디 놓이는가. 두 값 다 실측이다 - C/C++ 은 Arachne 가
# `.staticdata/config/` 만 읽고 쓰며(workspaceService.ts), analyzer-plugin 언어들은
# 워크스페이스 루트에 두고 `.staticdata/` 자체를 안 만든다.
_CCPP_SCOPE = ".staticdata/config/analysis.scope.json"
_PLUGIN_SCOPE = "analysis.scope.json"

# python 만 기술서가 선택이다. `analyzer-plugin python` 은 `-r <루트>` 로도 돌아가고
# (`-r` 과 `-i` 는 상호 배타다 - 실측), 루트 모드면 가상환경 탐색을 분석기가 알아서
# 한다. 기술서는 가상환경 경로를 손으로 지정하고 싶을 때만 쓴다.
_PLUGIN_LANGUAGES = {
    "java": Language(
        "java", "JAVA", ".STATICJAVA", (".java",),
        ("build", "out", "target", "bin"), True, _PLUGIN_SCOPE),
    "kotlin": Language(
        "kotlin", "KOTLIN", ".STATICKOTLIN", (".kt", ".kts"),
        ("build", "out", "target", "bin"), True, _PLUGIN_SCOPE),
    "python": Language(
        "python", "PYTHON", ".STATICPYTHON", (".py",),
        ("venv", "site-packages", "eggs"), False, _PLUGIN_SCOPE),
    "csharp": Language(
        "csharp", "CSHARP", None, (".cs",),
        ("bin", "obj", "packages"), False, _PLUGIN_SCOPE),
}

_CCPP_LANGUAGE = Language(CCPP, "CCPP", None, (), (), False, _CCPP_SCOPE)

# 사람과 에이전트가 쓸 목록. 정렬해 두어야 오류 메시지가 실행마다 흔들리지 않는다.
PLUGIN_IDS = tuple(sorted(_PLUGIN_LANGUAGES))
ALL_IDS = (CCPP,) + PLUGIN_IDS


def is_plugin(language_id):
    """analyzer-plugin 이 다루는 언어인가 (= C/C++ 이 아닌가)."""
    return language_id in _PLUGIN_LANGUAGES


def get(language_id):
    """언어 정의. 모르는 값이면 예외 - 조용히 ccpp 로 되돌리지 않는다.

    되돌리면 java 워크스페이스에 analyzer-csa 를 물리게 되고, 그쪽은 캡처가
    없으니 "변경된 분석 대상이 없습니다"만 영원히 돌려준다. 아무도 오류를 내지
    않는 종류의 고장이라, 여기서 크게 실패하는 편이 낫다.
    """
    if language_id == CCPP:
        return _CCPP_LANGUAGE
    try:
        return _PLUGIN_LANGUAGES[language_id]
    except KeyError:
        raise PluginError(
            "UNKNOWN_LANGUAGE",
            f"모르는 언어입니다: {language_id}",
            f"쓸 수 있는 값: {', '.join(ALL_IDS)}") from None


def of_agent_json(agent_json):
    """이 워크스페이스의 언어 id. 필드가 없으면 `ccpp`.

    기본값이 `ccpp` 인 것은 하위 호환이다 (`workspace.status` 와 같은 규칙).
    """
    value = (agent_json or {}).get(LANGUAGE_KEY)
    return value if isinstance(value, str) and value.strip() else CCPP


def normalize(raw):
    """사용자/에이전트가 넘긴 언어 값을 id 로 정규화한다. 비어 있으면 `ccpp`."""
    text = (raw or "").strip().casefold()
    if not text:
        return CCPP
    # 서버 표기(JAVA, CCPP)와 흔한 별칭도 받아 준다 - 여기서 막으면 에이전트가
    # 철자를 세 번 시도하는 동안 사용자는 아무것도 못 한다.
    aliases = {"c": CCPP, "cpp": CCPP, "c++": CCPP, "c/c++": CCPP, "ccpp": CCPP,
               "cs": "csharp", "c#": "csharp", "py": "python", "kt": "kotlin"}
    text = aliases.get(text, text)
    get(text)                       # 모르는 값이면 여기서 예외
    return text


def descriptor_path(ws, language):
    """워크스페이스 안 기술서 파일 경로. 기술서가 없는 언어면 None."""
    if not language.descriptor:
        return None
    return Path(ws) / language.descriptor


def input_path(agent_json):
    """csharp 의 분석 입력(.sln / .csproj). 지정된 적이 없으면 None."""
    value = (agent_json or {}).get(INPUT_PATH_KEY)
    return Path(value) if isinstance(value, str) and value.strip() else None


def analyze_args(ws, language, project_key, agent_json, project_dir, *, upload=False):
    """`analyzer-plugin` 에 넘길 인자 목록.

    `-o` 를 **언제나** 명시한다. 생략하면 출력이 `works/{projectKey}` 로 가는데,
    워크스페이스 이름과 프로젝트 키는 같으리라는 보장이 없다 -
    `free_workspace_name` 이 이름 충돌에 `_2` 를 붙이면 `myproj_2` 워크스페이스의
    결과가 `MYPROJ2` 디렉터리로 새어 나가고, 우리가 보는 워크스페이스에는 산출물이
    영영 생기지 않는다. Windows 는 대소문자를 안 가려 우연히 맞는 경우가 많아서
    더 나쁘다 - 리눅스에서만 깨진다.
    """
    args = [language.id, "-k", project_key, "-o", str(ws)]
    # 서버 연결은 필요하지만, 명시적 업로드 외에는 결과를 로컬에만 저장한다.
    if not upload:
        args.append("--no-upload")
    descriptor = descriptor_path(ws, language)

    if language.id == "csharp":
        source = input_path(agent_json)
        if source is None:
            raise PluginError(
                "NO_ANALYSIS_INPUT",
                f"csharp 워크스페이스에 분석 입력(.sln 또는 .csproj)이 없습니다: {ws}",
                "bootstrap-begin 을 --input <솔루션 경로> 로 다시 실행하세요.")
        args += ["-i", str(source)]
        configuration = (agent_json or {}).get(CSHARP_CONFIGURATION_KEY)
        if isinstance(configuration, str) and configuration.strip():
            args += ["-c", configuration.strip()]
        target = (agent_json or {}).get(CSHARP_TARGET_KEY)
        if isinstance(target, str) and target.strip():
            args += ["-t", target.strip()]
        return args

    if descriptor is not None and descriptor.is_file():
        args += ["-i", str(descriptor)]
        return args

    if language.descriptor_required:
        raise PluginError(
            "NO_DESCRIPTOR",
            f"분석 기술서가 없습니다: {descriptor}",
            f"{language.id} 는 빌드 플러그인이 만든 기술서가 있어야 분석할 수 "
            "있습니다. statica-analyze-bootstrap 스킬의 타 언어 절차를 따르세요.")

    # python 루트 모드. `-r` 과 `-i` 는 상호 배타라 여기서만 붙는다.
    args += ["-r", str(project_dir)]
    return args


def is_skipped_dir(name, language):
    """이 언어의 소스 탐색에서 통째로 건너뛸 디렉터리인가.

    공통 규칙(`changes.is_skipped_dir`)에 언어별 목록을 더한다. `bin` · `obj` 를
    공통 목록에 넣지 않는 이유는 C/C++ 때문이다 - 거기서는 `bin` 아래에 진짜
    소스를 두는 프로젝트가 있고, 그것을 건너뛰면 신규 파일이 조용히 사라진다.
    """
    from .changes import is_skipped_dir as common_skipped
    return common_skipped(name) or name in language.skip_dirs
