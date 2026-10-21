"""부트스트랩 판단에 쓸 기계적 증거를 모으고, 고른 컴파일러를 검증한다.

여기서는 결정하지 않는다 — 무엇이 보이는지만 보고한다. 환경을 고르고
컴파일러를 확정하는 것은 에이전트의 몫이다. 그래서 이 모듈의 모든 함수는
실패해도 예외를 밖으로 내지 않고, 못 본 것을 못 봤다고 말한다.
"""
import json
import subprocess
from pathlib import Path

from .analyzer import decode
from .changes import SKIP_DIR_NAMES, is_skipped_dir
from .paths import install_root, is_windows
from .vendor import detect_toolchain as dt

# (glob 패턴, 환경 힌트). 힌트는 environments.md 의 제목과 맞춘다.
ARTIFACT_HINTS = (
    ("*.sln", "Visual Studio C/C++"),
    ("*.vcxproj", "Visual Studio C/C++"),
    ("CMakeLists.txt", "CMake"),
    ("CMakeCache.txt", "CMake"),
    ("compile_commands.json", "CMake"),
    ("Makefile", "Makefile"),
    ("makefile", "Makefile"),
    ("GNUmakefile", "Makefile"),
    ("*.ioc", "STM32CubeIDE"),
    (".cproject", "Eclipse 계열 (STM32CubeIDE · CCS · CodeWarrior · Vitis)"),
    ("*.X", "MPLAB X IDE"),
    ("*.atsln", "Microchip Studio"),
    ("*.cbp", "AURIX Development Studio"),
)

# 타 언어(analyzer-plugin)의 단서. 위와 나눠 두는 이유는 답이 다르기 때문이다 —
# 위쪽은 "어떤 IDE 의 wrapper 를 만들까"에 답하고, 이쪽은 "애초에 C/C++ 이 맞나"에
# 답한다. 섞으면 java 프로젝트의 build.gradle 이 컴파일러 탐색 근거로 읽힌다.
#
# `*.sln` 이 양쪽에 다 있는 것은 실제로 양쪽 다이기 때문이다: Visual Studio 의
# C++ 솔루션일 수도, C# 솔루션일 수도 있다. 무엇인지는 안에 든 프로젝트 파일
# (`.vcxproj` 대 `.csproj`)이 가른다.
LANGUAGE_ARTIFACT_HINTS = (
    ("build.gradle", "java"),
    ("build.gradle.kts", "kotlin"),
    ("settings.gradle", "java"),
    ("settings.gradle.kts", "kotlin"),
    ("pom.xml", "java"),
    ("*.csproj", "csharp"),
    ("*.sln", "csharp"),
    ("pyproject.toml", "python"),
    ("requirements.txt", "python"),
    ("setup.py", "python"),
)

# Bootstrap 전용 설정은 스킬의 assets/config에 있다. bootstrap 모듈을
# import하지 않고 직접 읽어 순환 참조를 피한다.
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "assets" / "config"


def _detect_config():
    """vendor detect_toolchain.detect() 의 두 번째 인자로 넘길 known_paths.json."""
    path = _CONFIG_DIR / "known_paths.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _is_under_skipped_dir(path, root):
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return True
    return any(is_skipped_dir(part) for part in parts)


def project_artifacts(project_dir, hints=ARTIFACT_HINTS):
    """프로젝트 트리에서 보이는 빌드 시스템 단서들."""
    root = Path(project_dir)
    if not root.is_dir():
        return []
    out = []
    for pattern, hint in hints:
        files = []
        try:
            for match in root.rglob(pattern):
                if not match.is_file() and not match.is_dir():
                    continue
                if _is_under_skipped_dir(match, root):
                    continue
                files.append(str(match))
                if len(files) >= 5:      # 증거는 몇 개면 충분하다
                    break
        except OSError:
            continue
        if files:
            out.append({"pattern": pattern, "hint": hint, "files": sorted(files)})
    return out


def mechanical_detect(project_dir):
    """검증된 기존 탐지기를 그대로 부른다. 실패는 gather 가 흡수한다."""
    config = _detect_config()
    return dt.detect(str(project_dir), config, sysroot=None, verify_run=False)


def guides_dir():
    return install_root() / "docs" / "ko"


def gather(project_dir):
    """에이전트에게 줄 증거 묶음. 무엇도 결정하지 않는다.

    이 함수는 Stop 훅으로 이어지는 경로에서 불린다 — 여기서 나는 어떤 예외도
    사용자의 턴을 끊어서는 안 된다. 그래서 하위 호출 하나하나를 개별 try/except
    로 감싼다: project_artifacts 하나가 이상한 파일 시스템 상태(예: 권한 오류로
    걸러지지 않는 예외)에서 죽더라도, detection·guidesDir 은 계속 채워져야 한다.
    """
    try:
        project_dir_str = str(Path(project_dir))
    except Exception:
        project_dir_str = str(project_dir)
    result = {
        "projectDir": project_dir_str,
        "artifacts": [],
        "artifactsError": None,
        "languageArtifacts": [],
        "detection": None,
        "detectionError": None,
        "guidesDir": None,
        "skippedDirs": sorted(SKIP_DIR_NAMES),
    }
    try:
        result["artifacts"] = project_artifacts(project_dir)
    except Exception as e:                       # 단서 탐색 실패가 나머지를 막지 않는다
        result["artifactsError"] = f"{type(e).__name__}: {e}"
    try:
        # C/C++ 이 아닐 가능성을 여기서 함께 보고한다. 이 단서가 없으면 에이전트는
        # java 프로젝트에서도 컴파일러부터 찾기 시작한다 — 찾지 못하고, 왜 못 찾는지
        # 알 방법도 없다.
        result["languageArtifacts"] = project_artifacts(
            project_dir, LANGUAGE_ARTIFACT_HINTS)
    except Exception as e:
        result["languageArtifactsError"] = f"{type(e).__name__}: {e}"
    try:
        result["detection"] = mechanical_detect(project_dir)
    except Exception as e:                      # 탐지 실패가 안내를 막지 않는다
        result["detectionError"] = f"{type(e).__name__}: {e}"
    try:
        result["guidesDir"] = str(guides_dir())
    except Exception:
        result["guidesDir"] = None
    return result


# 컴파일러마다 버전을 묻는 플래그가 다르다. 순서대로 시도한다.
#
# `/?` 는 Windows 에서만 넣는다. cl.exe 가 `--version` 을 모르기 때문에 필요한
# 것인데, 리눅스에서는 `/?` 가 "루트의 ? 라는 파일" 로 읽혀 컴파일러가 엉뚱한
# 오류를 내거나(gcc: no such file) 최악의 경우 뭔가를 만들려 든다.
_VERSION_FLAGS = ((["--version"], ["/?"], ["-v"]) if is_windows()
                  else (["--version"], ["-v"]))


def verify_compiler(compiler_path, timeout=30):
    """컴파일러를 실제로 실행해 살아 있는지 확인한다.

    에이전트가 경로를 고르게 하는 이상, 고른 것이 진짜 그 컴파일러인지는
    실행해서 확인하는 수밖에 없다. 예외는 밖으로 내지 않는다 — 판정만 돌려준다.
    """
    path = Path(compiler_path)
    result = {"ok": False, "path": str(path), "exists": False,
              "ran": False, "returncode": None, "output": "", "message": ""}
    if not path.is_file():
        result["message"] = f"컴파일러 실행 파일을 찾을 수 없습니다: {path}"
        return result
    result["exists"] = True

    for flags in _VERSION_FLAGS:
        try:
            proc = subprocess.run([str(path)] + flags, capture_output=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            result["ran"] = True
            result["message"] = f"컴파일러가 {timeout}초 안에 응답하지 않았습니다: {path}"
            return result
        except OSError as e:
            result["message"] = f"컴파일러를 실행할 수 없습니다: {path} ({type(e).__name__})"
            return result
        result["ran"] = True
        result["returncode"] = proc.returncode
        text = (decode(proc.stdout) + "\n" + decode(proc.stderr)).strip()
        result["output"] = text[:2000]
        if proc.returncode == 0 and text:
            result["ok"] = True
            result["message"] = "컴파일러 실행을 확인했습니다."
            return result

    result["message"] = (f"컴파일러를 실행했지만 버전 정보를 얻지 못했습니다: {path}. "
                         "경로가 맞는지 확인하세요.")
    return result
