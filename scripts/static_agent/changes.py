import re
import sqlite3
from pathlib import Path

from . import tu_history
from .workspace import read_json

# TU 디렉터리 이름은 `{소스경로MD5}_{N}` 이다. **N 은 그 TU 의 재분석 회차가 아니라
# 모듈 안에서 매겨진 일련번호다** — 실측 워크스페이스에서 `_1`…`_6` 의 hash 가 전부
# 다르다. 그래서 "N 이 가장 큰 것이 최신" 같은 규칙은 성립하지 않고, hash 하나에
# 대응하는 디렉터리는 모듈당 정확히 하나다.
TU_DIR_RE = re.compile(r"^([0-9A-Fa-f]{32})_(\d+)$")
SOURCE_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".c++")

# 빌드가 절대 컴파일하지 않을 소스가 들어 있는 디렉터리. 여기 있는 파일을 "신규"로
# 보면 캡처가 영원히 따라잡지 못해 매 응답마다 전체 재빌드가 돈다.
SKIP_DIR_NAMES = {".git", ".svn", "node_modules", "__pycache__", "build", "out"}

# 이름이 고정되지 않은 디렉터리는 접두사로 거른다 (예: CLion 의 cmake-build-debug,
# cmake-build-release). 위의 정확 일치 목록과 함께 쓰인다.
SKIP_DIR_PREFIXES = ("cmake-build-",)


def is_skipped_dir(name):
    """신규 파일 탐색에서 통째로 건너뛸 디렉터리 이름인지 본다."""
    return (name in SKIP_DIR_NAMES
            or name.startswith(".")
            or any(name.startswith(prefix) for prefix in SKIP_DIR_PREFIXES))


def module_dirs(ws):
    """워크스페이스 루트의 {moduleName}_{hash} 디렉터리들."""
    ws = Path(ws)
    if not ws.is_dir():
        return []
    return sorted(
        p for p in ws.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and (p / "module.capture.json").is_file()
    )


def iter_linking_objects(ws):
    """워크스페이스의 모든 모듈에서 (module_dir, linkingObject) 쌍을 순회한다."""
    for module in module_dirs(ws):
        data = read_json(module / "module.capture.json") or {}
        for obj in (data.get("linkingObjects") or []):
            yield module, obj


def module_tu_dirs(module):
    """모듈 하나가 가진 TU 디렉터리들."""
    analyze = Path(module) / ".analyze"
    if not analyze.is_dir():
        return []
    return sorted(p for p in analyze.iterdir()
                  if p.is_dir() and TU_DIR_RE.match(p.name))


def tu_dirs(ws):
    out = []
    for module in module_dirs(ws):
        out.extend(module_tu_dirs(module))
    return out


def module_identity(module):
    """분석 범위가 이 모듈을 부르는 이름 = `module.capture.json` 의 `output`.

    디렉터리 이름(`libcalc.a_FFBA…`)이 아니다. Arachne UI 가 모듈 노드의 `path` 를
    `normalizePath(capture.output)` 로 만들고(`buildWorkspaceTree.ts` 의 모듈 노드
    생성부), `analysisSkipModules` 에는 그 `path` 가 그대로 들어간다
    (`analysisScopeUtils.excludeNode`). 실측 대응:

        libcalc.a_FFBA6847…  ->  /opt/cmake_test/build/libcalc.a
        cmTC_47a51_93F02FF6…  ->  /opt/cmake_test/build/CMakeFiles/.../cmTC_47a51

    디렉터리 이름으로 맞추면 UI 가 적어 둔 값과 영영 안 맞는다.
    """
    data = read_json(Path(module) / "module.capture.json") or {}
    return data.get("output") or None


def module_summaries(ws):
    """모듈 목록. 사용자가 무엇을 뺄지 고르려면 이것부터 보여야 한다.

    `output` 이 분석 범위가 쓰는 식별자다(module_identity 참조). `linkCommand` 를
    같이 주는 이유는, 빌드가 아니라 빌드 도구가 만든 모듈을 그것으로 알아보기
    때문이다 - 실측: CMake 의 컴파일러 시험이 `-Wl,--help` 나
    `CMakeCXXCompilerId.cpp` 를 링크 커맨드로 남긴다.
    """
    out = []
    for module in module_dirs(ws):
        data = read_json(module / "module.capture.json") or {}
        sources = {str(Path(obj["sourceFile"])).casefold()
                   for obj in (data.get("linkingObjects") or [])
                   if obj.get("sourceFile")}
        out.append({
            "name": module.name,
            "output": data.get("output"),
            "linkCommand": " ".join(str(x) for x in (data.get("linkCommand") or [])),
            "capturedSources": len(sources),
            "analyzedTus": len(module_tu_dirs(module)),
            "moduleDir": str(module),
        })
    return out


def analyzable_sources(ws, module, current=None):
    """이 모듈에서 **실제로 분석될** 캡처 소스들.

    분석 범위에서 뺀 소스는 TU 가 아예 만들어지지 않는다 (실측: extra2.c 를 뺀 채
    `analyze -m` 을 돌리면 `File(1/3)`…`(3/3)` 으로 건너뛰고 TU 도 `.ci` 도 생기지
    않는다). 그래서 범위를 무시하고 캡처만 세면 캡처>TU 가 **영원히** 풀리지 않고,
    modules_missing_tus 가 매 실행마다 같은 모듈에 -m 을 건다.
    """
    from . import scope
    from .languages import CCPP, get
    if current is None:
        current = scope.read(ws, get(CCPP))
    data = read_json(Path(module) / "module.capture.json") or {}
    # 같은 소스가 linkingObjects 에 두 번 올라와도 TU 는 하나다. 키로 접는다.
    sources = {}
    for obj in (data.get("linkingObjects") or []):
        src = obj.get("sourceFile")
        if src:
            sources.setdefault(str(Path(src)).casefold(), src)
    return {k: v for k, v in sources.items()
            if scope.resolve(current, v, scope.FILE) in (scope.ACTIVE, scope.INCLUDED)}


def modules_missing_tus(ws):
    """캡처된 소스보다 TU 디렉터리가 적은 모듈들 = `analyze -m` 을 돌려야 할 곳.

    TU 디렉터리를 만드는 것은 빌드가 아니라 **분석기다** (실측: 빌드는
    module.capture.json 만 쓰고 간다). 그래서 새로 추가된 소스는 재빌드로 캡처까지는
    들어가지만 TU 가 없어 `is_tu_stale` 의 시야 밖에 있고, `-t` 는 없는 TU 를 받지
    못한다 - 어느 관문에도 걸리지 않은 채 영영 분석되지 않는다. 그 구멍을 막는 함수다.

    세는 것은 **분석될 소스의 수**다. 소스 하나에 TU 디렉터리 하나가 대응하므로
    (TU_DIR_RE 주석 참조) 이 둘이 어긋났다는 것은 곧 TU 가 없는 소스가 있다는
    뜻이다. 반대로 어긋나는 쪽(TU 가 더 많음)은 소스가 지워졌거나 빌드에서 빠진
    경우, 혹은 나중에 범위에서 뺀 경우라 여기서 할 일이 없다.

    범위에서 뺀 소스를 세지 않는 이유는 analyzable_sources 에 적어 두었다.
    모듈 단위 제외(`analysisSkipModules`)도 같은 이유로 통째로 건너뛴다.
    """
    from . import scope
    from .languages import CCPP, get
    current = scope.read(ws, get(CCPP))
    skipped = {scope.key(name)
               for name in (current.get("analysisSkipModules") or [])}
    out = []
    for module in module_dirs(ws):
        identity = module_identity(module)
        if identity and scope.key(identity) in skipped:
            continue
        if len(analyzable_sources(ws, module, current)) > len(module_tu_dirs(module)):
            out.append(module)
    return out


def is_tu_stale(ws, tu_dir, history=None):
    """이 TU 를 다시 분석해야 하는지 본다.

    기준선은 **우리가 적어 둔 마지막 분석 시각**이다 (`tu_history`). 예전에는
    `tu.cache.json` 의 mtime 을 기준선으로 쓰면서 분석 뒤에 그 파일을 touch 했는데,
    남의 산출물에 손대는 방식이었고 그 이유는 `tu_history` 모듈 docstring 에 있다.

    보수적으로 판단한다 — 애매하면 후보로 넘기고 최종 판정은 분석기의 TU 캐시에 맡긴다.

    역할 분담: **헤더 변경을 잡는 쪽이 여기다.** tu.cache.json 의 sourceFiles 에는
    전처리에 들어간 파일이 전부 들어 있어서 (실측: main.c 하나의 TU 에 18개, 그중
    16개가 헤더) .h 만 고쳐도 여기서 stale 로 걸린다. 반대로 아직 한 번도 컴파일된
    적 없는 신규 소스는 TU 자체가 없어 여기 걸리지 않으며, 그건 new_source_files 몫이다.
    """
    cache = Path(tu_dir) / "tu.cache.json"
    if not cache.is_file():
        return True  # 분석기가 아직 이 TU 를 만들지 않았다
    base = tu_history.analyzed_at(ws, tu_dir, history)
    if base is None:
        return True
    data = read_json(cache) or {}
    for src in (data.get("sourceFiles") or {}):
        try:
            if Path(src).stat().st_mtime > base:
                return True
        except OSError:
            return True  # 캡처된 소스가 사라짐
    return False


def stale_sources(ws, tu_dir, history=None):
    """이 TU 에서 마지막 분석보다 새로운 소스들의 경로.

    `is_tu_stale` 이 "이 TU 를 다시 봐야 하나"에 예/아니오로 답한다면, 이쪽은
    "그중 무엇이 새로운가"에 답한다. 결함 집계를 그 파일들로 좁히는 데 쓴다
    (`defects.summarize` 의 `changed_by_tu`).

    캐시가 없거나 기준선이 없으면 빈 리스트다 — 처음 분석하는 TU 라 무엇이
    바뀌었는지 말할 근거가 없다. 그때 무엇으로 집계할지는 `defects` 가 정한다.
    """
    cache = Path(tu_dir) / "tu.cache.json"
    if not cache.is_file():
        return []
    base = tu_history.analyzed_at(ws, tu_dir, history)
    if base is None:
        return []
    data = read_json(cache) or {}
    out = []
    for src in (data.get("sourceFiles") or {}):
        try:
            if Path(src).stat().st_mtime > base:
                out.append(src)
        except OSError:
            continue                 # 사라진 소스는 집계 대상이 아니다
    return sorted(out)


def changed_tu_dirs(ws):
    """다시 분석해야 하는 TU 들. 기록은 한 번만 읽어 전부에 돌려 쓴다."""
    history = tu_history.read(ws)
    return [tu for tu in tu_dirs(ws) if is_tu_stale(ws, tu, history)]


def captured_sources(ws):
    """module.capture.json 의 linkingObjects 에 등록된 소스 절대경로 집합."""
    out = set()
    for module, obj in iter_linking_objects(ws):
        src = obj.get("sourceFile")
        if src:
            out.add(str(Path(src)).casefold())
    return out


# ---------------------------------------------------------------------------
# analyzer-plugin 언어(java · kotlin · python · csharp)의 변경 탐지
#
# C/C++ 과 묻는 방식은 같다 - **기준선 파일 하나의 mtime** 과 소스의 mtime 을
# 비교한다. 다른 것은 기준선이 무엇이냐뿐이다:
#
#     C/C++      <모듈>/.analyze/<TU>/tu.cache.json   (TU 마다 하나씩)
#     그 외      <워크스페이스>/sourcefiles.db        (워크스페이스에 하나)
#
# 그리고 여기에는 `mark_tu_analyzed` 에 해당하는 것이 **없다.** analyzer-plugin 은
# 변경이 하나도 없어도 산출물을 전부 다시 쓴다 (실측: 소스를 건드리지 않고 재실행
# 했더니 sourcefiles.db · defect.json · metric.json 의 mtime 이 전부 갱신됐고 내용은
# md5 까지 같았다). 즉 기준선이 언제나 전진하므로, C/C++ 에서 겪은 "매 응답마다
# 같은 대상을 다시 분석하는" 스핀이 구조적으로 생기지 않는다.
# ---------------------------------------------------------------------------


def plugin_baseline(ws):
    """analyzer-plugin 워크스페이스의 변경 판정 기준선 시각. 없으면 None.

    None 은 "한 번도 분석된 적 없다" 는 뜻이고, 그때는 모든 소스가 변경으로 잡힌다.
    """
    from .languages import SOURCEFILES_DB
    try:
        return (Path(ws) / SOURCEFILES_DB).stat().st_mtime
    except OSError:
        return None


def analyzed_sources(ws):
    """지난 분석이 실제로 본 소스 파일들의 경로.

    `sourcefiles.db` 의 `sourcefile` 표에서 읽는다. 제외된 파일(`is_excluded`)은
    빼는데, 그것들은 이번에도 분석되지 않을 것이므로 고쳐도 재분석할 이유가 없다.

    읽지 못하면 빈 리스트다 - 그러면 호출한 쪽이 프로젝트 트리만 보고 판정한다.
    """
    from .languages import SOURCEFILES_DB
    db = Path(ws) / SOURCEFILES_DB
    if not db.is_file():
        return []
    try:
        con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    except (sqlite3.Error, ValueError, OSError):
        return []
    try:
        rows = con.execute(
            "SELECT path FROM sourcefile WHERE IFNULL(is_excluded,0)=0").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [r[0] for r in rows if r[0]]


def project_sources(project_dir, language):
    """프로젝트 트리에서 이 언어의 소스로 보이는 파일들.

    `analyzed_sources` 가 지난 분석의 시야라면 이쪽은 지금 디스크의 사실이다.
    둘의 차이가 신규 파일이다.
    """
    from . import languages as langs
    root = Path(project_dir)
    if not root.is_dir() or not language.extensions:
        return []
    found = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in language.extensions:
            continue
        relative_dirs = path.relative_to(root).parts[:-1]
        if any(langs.is_skipped_dir(part, language) for part in relative_dirs):
            continue
        found.append(path)
    return sorted(found)


def plugin_changes(ws, project_dir, language):
    """이 워크스페이스를 다시 분석해야 하는가, 그렇다면 무엇 때문인가.

    ``{"stale": [...], "newFiles": [...], "missing": [...], "baseline": float|None}``
    을 돌려준다. 셋 중 하나라도 비어 있지 않으면 다시 분석해야 한다.

    - ``stale``    기준선보다 새로운 소스. 분석된 적 있는 파일과 신규 파일 양쪽에서 온다.
    - ``newFiles`` 지난 분석이 보지 못한 소스. 분석 범위 밖인지 판정하는 데 쓴다.
    - ``missing``  지난 분석이 봤는데 지금은 없는 소스. 지워진 파일의 결함이 서버에
                   남지 않도록 이것도 재분석 사유로 친다.

    기준선이 없으면(첫 분석) 모든 프로젝트 소스가 ``stale`` 이다.
    """
    baseline = plugin_baseline(ws)
    known = analyzed_sources(ws)
    known_norm = {_norm_source(p) for p in known}
    current = project_sources(project_dir, language)

    new_files = [p for p in current if _norm_source(p) not in known_norm]
    missing = [p for p in known if not Path(p).is_file()]

    if baseline is None:
        return {"stale": [str(p) for p in current], "newFiles": [str(p) for p in new_files],
                "missing": missing, "baseline": None}

    stale = []
    for path in current:
        try:
            if path.stat().st_mtime > baseline:
                stale.append(str(path))
        except OSError:
            continue                 # 방금 사라진 파일 - missing 이 아니라 무시한다
    return {"stale": sorted(stale), "newFiles": [str(p) for p in new_files],
            "missing": missing, "baseline": baseline}


def _norm_source(path):
    """`sourcefiles.db` 의 철자와 우리 철자를 맞춘다.

    분석기는 경로를 슬래시로 적고(`C:/Users/...`) 우리는 OS 구분자로 든다.
    대소문자도 갈릴 수 있다. 그 둘만 지우고 더 손대지 않는다 - 여기서
    `resolve()` 를 부르면 사라진 파일에서 엉뚱한 값이 나온다.
    """
    return str(path).replace("\\", "/").casefold()


def new_source_files(project_dir, ws):
    """프로젝트 트리에 있으나 캡처되지 않은 소스 = 신규 파일.

    역할 분담: 이 함수가 답하는 질문은 "한 번도 컴파일된 적 없어서 재캡처가 필요한
    파일은 무엇인가"뿐이다. 그래서 SOURCE_EXTENSIONS 만 훑는 것이 맞다 — 헤더는
    linkingObjects 에 절대 올라오지 않으므로 여기 포함시키면 모든 헤더가 영원히
    "신규"로 보고되어 매번 전체 재빌드가 돈다. 헤더 *변경* 은 is_tu_stale 이 잡는다.
    """
    known = captured_sources(ws)
    root = Path(project_dir)
    found = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        relative_dirs = path.relative_to(root).parts[:-1]
        if any(is_skipped_dir(part) for part in relative_dirs):
            continue
        if str(path).casefold() not in known:
            found.append(path)
    return sorted(found)
