"""분석 범위(`analysis.scope.json`) 를 읽고 고친다.

**이 파일은 Arachne UI 와 공유하는 자료다.** 우리가 쓴 것을 UI 가 읽고, UI 가 쓴
것을 우리가 읽는다. 그래서 형식과 의미를 우리 마음대로 정할 수 없고,
`analysisScopeUtils.ts` 의 규칙을 그대로 따라야 한다. 어긋나면 두 쪽이 서로의
설정을 조용히 뭉갠다.

핵심 규칙은 하나다. **가장 가까운 조상이 이긴다.**

    exclusion.directories 에 `src/gen` 이 있으면 그 아래는 전부 빠진다.
    그 아래 `src/gen/keep.c` 를 되살리려면 inclusion.files 에 넣는다.

그래서 `inclusion` 은 화이트리스트가 **아니다** — 제외된 조상을 뚫는 예외 목록이다.
비어 있는 `inclusion` 은 "아무것도 포함하지 않는다"가 아니라 "예외가 없다"는 뜻이다.
이걸 화이트리스트로 오해하고 다루면, 제외된 폴더 밑 파일의 제외를 푸는 동작이
아무 일도 하지 않는다.
"""
from pathlib import Path

from .workspace import read_json, write_json

FILE = "file"
DIRECTORY = "directory"

# `resolve` 가 돌려주는 값. 앞의 둘은 결과가 같지만(빠진다) 사용자가 할 일이
# 다르다 - 직접 제외는 그 항목을 지우면 되고, 조상 제외는 예외로 되살려야 한다.
ACTIVE = "active"
EXCLUDED = "excluded"
EXCLUDED_BY_ANCESTOR = "excludedByAncestor"
INCLUDED = "included"


def normalize(path):
    """`analysisScopeUtils.ts` 의 `normalizePath` 와 같은 결과를 낸다.

    드라이브 루트(`C:/`)만 예외로 끝 슬래시를 남긴다. 거기서까지 떼면 `C:` 가
    되는데, 그것은 경로가 아니라 드라이브 이름이라 조상 탐색이 어긋난다.
    """
    text = str(path).strip().replace("\\", "/")
    if len(text) == 3 and text[1:] == ":/" and text[0].isalpha():
        return text
    return text.rstrip("/") or text


def key(path):
    """비교용 키. Windows 경로라 대소문자를 가리지 않는다."""
    return normalize(path).lower()


def empty():
    """빈 범위. `EMPTY` 를 그대로 넘기면 호출자끼리 같은 리스트를 나눠 갖는다."""
    return {
        "analysisSkipModules": [],
        "exclusion": {"directories": [], "files": []},
        "inclusion": {"directories": [], "files": []},
    }


def _copy(current):
    """읽은 것을 그대로 고치지 않는다 - 실패해도 원본이 남아 있어야 한다."""
    return {
        "analysisSkipModules": list(current.get("analysisSkipModules", [])),
        "exclusion": {
            "directories": list(current["exclusion"]["directories"]),
            "files": list(current["exclusion"]["files"]),
        },
        "inclusion": {
            "directories": list(current["inclusion"]["directories"]),
            "files": list(current["inclusion"]["files"]),
        },
    }


def _bucket(kind):
    return "directories" if kind == DIRECTORY else "files"


def _add(paths, path):
    """이미 있으면 그대로 둔다. 먼저 적힌 표기를 이긴 것으로 삼는다."""
    if any(key(p) == key(path) for p in paths):
        return paths
    return paths + [normalize(path)]


def _remove(paths, path):
    return [p for p in paths if key(p) != key(path)]


def closest_ancestor(path, excluded_dirs, included_dirs):
    """가장 가까운 조상 디렉터리의 판정. 없으면 None.

    `buildWorkspaceTree.ts` 의 `findClosestAncestorScope` 와 같다. 위로 한 칸씩
    올라가며 **먼저 만나는** 쪽이 이긴다 - 그래서 먼 exclusion 을 가까운
    inclusion 이 덮을 수 있다.
    """
    current = key(path)
    while True:
        cut = current.rfind("/")
        if cut <= 0:
            return None
        current = current[:cut]
        if current in included_dirs:
            return "included"
        if current in excluded_dirs:
            return "excluded"


def _ancestor_excludes(current, path):
    return closest_ancestor(
        path,
        {key(p) for p in current["exclusion"]["directories"]},
        {key(p) for p in current["inclusion"]["directories"]},
    ) == "excluded"


def exclude(current, path, kind):
    """이 경로를 분석에서 뺀다."""
    result = _copy(current)
    bucket = _bucket(kind)
    result["exclusion"][bucket] = _add(result["exclusion"][bucket], path)
    # 제외하면서 예외 목록에 남겨 두면 두 목록이 서로를 부정한다.
    result["inclusion"][bucket] = _remove(result["inclusion"][bucket], path)
    return result


def include(current, path, kind):
    """이 경로를 다시 분석 대상으로 돌린다.

    직접 제외를 지우는 것만으로는 부족하다. 조상 폴더가 여전히 빠져 있으면
    이 경로도 따라 빠진 채라서, 그때는 예외 목록에 올려야 실제로 되살아난다.
    """
    result = _copy(current)
    bucket = _bucket(kind)
    result["exclusion"][bucket] = _remove(result["exclusion"][bucket], path)
    if _ancestor_excludes(result, path):
        result["inclusion"][bucket] = _add(result["inclusion"][bucket], path)
    return result


# 모듈 단위 제외는 파일 · 디렉터리와 **축이 다르다**. 여기 들어가는 값은 소스
# 경로가 아니라 그 모듈이 만들어 내는 **빌드 산출물 경로**다 - Arachne UI 가
# 모듈 노드의 path 를 `normalizePath(capture.output)` 으로 만들고
# (`buildWorkspaceTree.ts`), `excludeNode` 가 그 path 를 그대로 넣는다
# (`analysisScopeUtils.ts`). 그래서 exclusion/inclusion 과 섞지 않고 따로 둔다.
#
#     libcalc.a_FFBA6847…  ->  /opt/proj/build/libcalc.a
#
# 조상 규칙도 여기엔 없다. 모듈은 트리의 뿌리라 위로 올라갈 곳이 없다.
def skip_module(current, output):
    """이 빌드 모듈을 통째로 분석에서 뺀다."""
    result = _copy(current)
    result["analysisSkipModules"] = _add(result["analysisSkipModules"], output)
    return result


def unskip_module(current, output):
    """이 빌드 모듈을 다시 분석 대상으로 돌린다."""
    result = _copy(current)
    result["analysisSkipModules"] = _remove(result["analysisSkipModules"], output)
    return result


def is_module_skipped(current, output):
    """이 산출물 경로가 지금 제외돼 있나."""
    return any(key(p) == key(output)
               for p in (current.get("analysisSkipModules") or []))


def resolve(current, path, kind):
    """이 경로가 지금 분석 대상인가, 아니라면 무엇 때문인가.

    직접 지정이 조상보다 우선한다. `analysisSkipModules` 는 보지 않는다 - 그것은
    C/C++ 빌드 모듈 단위라 파일 · 디렉터리 판정과 축이 다르다.
    """
    bucket = _bucket(kind)
    if any(key(p) == key(path) for p in current["exclusion"][bucket]):
        return EXCLUDED
    if any(key(p) == key(path) for p in current["inclusion"][bucket]):
        return INCLUDED
    return EXCLUDED_BY_ANCESTOR if _ancestor_excludes(current, path) else ACTIVE


def path_for(ws, language):
    """이 워크스페이스의 `analysis.scope.json` 경로."""
    return Path(ws).joinpath(*language.scope_rel.split("/"))


def read(ws, language):
    """현재 범위. 파일이 없으면 빈 값이다 - Arachne 도 그렇게 읽는다.

    `exclusion` · `inclusion` 이 통째로 빠진 파일도 받아 준다. 손으로 고친 파일을
    만나 KeyError 로 죽으면 조회조차 못 하게 된다.
    """
    path = path_for(ws, language)
    if not path.is_file():
        return empty()
    raw = read_json(path) or {}
    result = empty()
    result["analysisSkipModules"] = list(raw.get("analysisSkipModules") or [])
    for side in ("exclusion", "inclusion"):
        given = raw.get(side) or {}
        for bucket in ("directories", "files"):
            result[side][bucket] = list(given.get(bucket) or [])
    return result


def write(ws, language, current):
    """범위를 저장한다. 우리가 모르는 필드는 남긴다.

    Arachne 가 이 파일에 필드를 늘려도 우리가 지워서는 안 된다 - 우리 쪽이
    한 번 저장하는 것만으로 UI 설정이 사라지는 일이 생긴다.
    """
    path = path_for(ws, language)
    merged = read_json(path) if path.is_file() else {}
    merged = dict(merged or {})
    merged.update(current)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, merged)


def _captured_keys(ws):
    """이 워크스페이스가 실제로 분석하는 C/C++ 단위(TU)들. 비교용 키로 준다."""
    from .changes import captured_sources
    return {key(p) for p in captured_sources(ws)}


def _has_source_under(directory, language):
    from .languages import is_skipped_dir
    root = Path(directory)
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in language.extensions:
            continue
        if any(is_skipped_dir(part, language)
               for part in path.relative_to(root).parts[:-1]):
            continue
        return True
    return False


def unanalyzable_reason(path, kind, ws, language):
    """제외 대상이 될 수 없으면 그 이유, 될 수 있으면 None.

    이 검사가 없어서 실제로 당했다. 헤더를 제외했더니 CLI 는 성공이라 답했는데
    분석량은 그대로였고 결함도 그대로 올라갔다. 제외는 **분석 대상 목록**에만
    걸리는데 헤더는 그 목록에 없기 때문이다 (`changes.new_source_files` 의 주석이
    같은 사실을 이미 적어 두고 있었다).

    Arachne UI 에서는 애초에 고를 수 없는 것들이다 - 트리를 캡처된 TU 로만 만든다
    (`buildWorkspaceTree.ts`). 우리도 같은 것만 받아야 UI 와 어긋나지 않는다.
    """
    from .languages import CCPP

    if language.id == CCPP:
        # 캡처가 정답지다. 무엇이 분석되는지 추측할 필요가 없다.
        captured = _captured_keys(ws)
        if kind == DIRECTORY:
            prefix = key(path) + "/"
            if any(k.startswith(prefix) for k in captured):
                return None
            return "이 폴더 아래에 캡처된 분석 단위(TU)가 없습니다."
        if key(path) in captured:
            return None
        if Path(path).suffix.lower() in (".h", ".hpp", ".hh", ".hxx", ".inc"):
            return ("헤더는 분석 단위(TU)가 아니라 제외할 수 없습니다. "
                    "헤더의 결함은 그 헤더를 include 한 소스를 분석할 때 나오므로, "
                    "그 소스를 제외하거나 서버에서 결함을 억제해야 합니다.")
        return ("빌드 캡처에 없는 파일이라 제외해도 분석량이 달라지지 않습니다. "
                "캡처된 소스만 제외할 수 있습니다.")

    # 캡처가 없는 언어. 가진 정보는 확장자뿐이다.
    listed = ", ".join(language.extensions)
    if kind == DIRECTORY:
        if _has_source_under(path, language):
            return None
        return f"이 폴더 아래에 {language.id} 소스({listed})가 없습니다."
    if Path(path).suffix.lower() in language.extensions:
        return None
    return f"{language.id} 의 분석 대상 확장자가 아닙니다 ({listed})."
