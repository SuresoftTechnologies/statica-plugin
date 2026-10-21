"""`.ci`(분석기가 만든 SQLite)에서 결함을 집계한다.

**집계 범위는 "그 TU 의 위반 전부"가 아니라 "변경된 파일에 달린 위반"이다.**
`.ci` 의 `Violation` 은 `idSourceFile` 로 `SourceFile` 을 가리키고, 한 TU 의
`SourceFile` 에는 전처리에 들어간 파일이 전부 들어 있다 — 실측으로 TU 하나에
161개, 그중 159개가 Windows SDK/CRT 헤더였다. 그래서 필터 없이 `COUNT(*)` 를
세면 `.c` 한 줄 고치고 "결함 2710건" 같은 수가 나온다. 그 수의 대부분은 사용자가
건드리지도 않은 시스템 헤더의 것이다.

`only_paths` 를 주면 그 경로들의 `idSourceFile` 로만 좁힌다. 주지 않으면 예전대로
전부 센다 (`upload` 처럼 "이 워크스페이스 전체"가 맞는 자리가 있다).
"""
import json
import sqlite3
from pathlib import Path

# TU 단위 결과에 반드시 따라붙어야 하는 단서. TU 분석은 그 번역 단위 안에서만
# 판단하므로, 여러 TU 를 함께 봐야 알 수 있는 규칙은 링크 분석에서 결과가 달라진다.
LINK_DIFFERS_NOTE = ("TU 단위 분석 결과입니다. 여러 번역 단위를 함께 봐야 하는 "
                     "규칙은 링크 분석에서 결과가 달라질 수 있습니다.")


def ci_files(tu_dir):
    tu = Path(tu_dir)
    if not tu.is_dir():
        return []
    return sorted(p for p in tu.iterdir() if p.is_file() and p.suffix == ".ci")


def _connect(ci_path):
    """.ci 는 분석기가 만든 SQLite 파일. 읽기 전용으로만 연다."""
    return sqlite3.connect(Path(ci_path).resolve().as_uri() + "?mode=ro", uri=True)


def _norm(path):
    """`SourceFile.path` 와 우리 경로를 비교하기 위한 정규화.

    분석기가 넣은 철자와 우리가 들고 있는 철자가 구분자·대소문자에서 갈릴 수
    있다. 그것 말고는 손대지 않는다 — 여기서 `resolve()` 를 부르면 존재하지 않는
    경로에서 엉뚱한 값이 나온다.
    """
    return str(path).replace("/", "\\").casefold()


def target_source_ids(ci_path, paths):
    """집계 대상이 될 `SourceFile.idSourceFile` 목록.

    `paths` 에 해당하는 것을 찾아 돌려준다. 하나도 못 찾으면 (처음 분석하는 TU라
    무엇이 바뀌었는지 알 수 없는 경우 등) **`isPrimary` 인 소스로 되돌아간다** —
    그 번역 단위 자신의 `.c` 다.

    되돌아가는 자리에서 "필터 없음"을 고르지 않는 것이 요점이다. 그러면 사용자가
    건드리지도 않은 시스템 헤더 159개의 결함이 다시 합계에 들어온다.
    """
    wanted = {_norm(p) for p in paths or ()}
    try:
        con = _connect(ci_path)
    except (sqlite3.Error, ValueError):
        return []
    try:
        rows = con.execute(
            "SELECT idSourceFile, path, IFNULL(isPrimary,0) FROM SourceFile").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    matched = [r[0] for r in rows if r[1] and _norm(r[1]) in wanted]
    if matched:
        return matched
    return [r[0] for r in rows if r[2]]


def _where(ids):
    """`ids` 가 None 이면 전체, 리스트면 그 `idSourceFile` 로 좁히는 절."""
    if ids is None:
        return "", ()
    if not ids:
        return " AND 1=0", ()          # 대상이 없다 = 셀 것도 없다
    marks = ",".join("?" * len(ids))
    return f" AND idSourceFile IN ({marks})", tuple(ids)


# 같은 결함을 두 번 세지 않기 위한 신원. 헤더의 위반은 그 헤더를 include 한 **모든**
# TU 의 `.ci` 에 한 벌씩 들어가고(실측: calculator.h 의 13건이 main.cpp · calculator.cpp
# · power.cpp 세 TU 에 각각), 링크 결과에서는 한 파일 안에서도 TU 수만큼 반복된다
# (실측: libcalc 의 link.result.ci 는 26행인데 고유 해시는 13개). 행을 세면 헤더 하나를
# 고쳤을 때 결함이 TU 수만큼 부풀어 오른다.
#
# `violationHash` 가 그 신원이다 - TU 를 건너, `.ci` 파일을 건너 같은 값이다(실측:
# 세 TU 의 13개 해시 교집합이 13). 컬럼이 없는 옛 분석기 산출물에서는 행마다 고유한
# 키를 만들어 예전처럼 행을 세는 쪽으로 조용히 물러선다.
def _violation_keys(ci_path, ids=None):
    """`(키, 억제여부, ruleName, ruleSet)` 목록. 키가 같으면 같은 결함이다."""
    try:
        con = _connect(ci_path)
    except (sqlite3.Error, ValueError):
        return []
    clause, params = _where(ids)
    try:
        has_hash = any(r[1] == "violationHash"
                       for r in con.execute("PRAGMA table_info(Violation)"))
        column = "violationHash" if has_hash else "NULL"
        rows = con.execute(
            f"SELECT {column}, IFNULL(isSuppression,0), ruleName, ruleSet"
            f" FROM Violation WHERE 1=1{clause}", params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    out = []
    for index, (key, suppressed, rule, rule_set) in enumerate(rows):
        # 해시가 없거나 비면 이 행만의 키를 준다 = 중복 제거가 일어나지 않는다.
        out.append((key or ("row", str(ci_path), index),
                    bool(suppressed), rule, rule_set))
    return out


def count_violations(ci_path, ids=None):
    """이 `.ci` 하나의 집계. 같은 결함은 한 번만 센다."""
    return _counts(_violation_keys(ci_path, ids=ids))


def _counts(keys):
    """`_violation_keys` 결과를 {total, active, suppressed} 로.

    한 결함이 어느 TU 에서는 억제되고 다른 TU 에서는 아닐 수 있다. 그때는
    **활성으로 본다** - 억제는 그것을 적어 둔 자리에서만 참이고, 한 군데라도
    살아 있으면 사용자가 봐야 하는 결함이다.
    """
    every = {k for k, _, _, _ in keys}
    active = {k for k, suppressed, _, _ in keys if not suppressed}
    return {"total": len(every), "active": len(active),
            "suppressed": len(every) - len(active)}


def top_rules(ci_path, limit=5, ids=None):
    ordered = _rank(_violation_keys(ci_path, ids=ids), limit)
    return ordered


def _rank(keys, limit):
    """규칙별 집계. 여기서도 같은 결함은 한 번만 센다."""
    per_rule = {}
    for key, suppressed, rule, rule_set in keys:
        if suppressed:
            continue
        per_rule.setdefault((rule, rule_set), set()).add(key)
    ordered = sorted(per_rule.items(),
                     key=lambda kv: (-len(kv[1]), kv[0][0] or ""))[:limit]
    return [{"ruleName": k[0], "ruleSet": k[1], "count": len(v)} for k, v in ordered]


# 결과를 나눠 말하는 두 갈래. 세는 기준이 서로 달라서 한 숫자로 합치면 그 수가
# 무엇의 수인지 말할 수 없게 된다 - 신규 소스는 **그 파일 전부**를 세고(비교할
# 이전 상태가 없으니 isPrimary 로 폴백한다), 변경된 TU 는 **바뀐 파일에 달린 것만**
# 센다. 둘 다 각자 맞는 답이고, 합계만이 틀린 답이었다.
NEW_SOURCES = "newSources"
CHANGED_FILES = "changedFiles"


def summarize(tu_dirs, limit=5, changed_by_tu=None, new_tus=None):
    """분석한 TU 들의 결함 집계.

    ``changed_by_tu`` 는 ``{tu_dir 문자열: [변경된 소스 경로, ...]}`` 다. 주면 그
    TU 에서는 **그 파일들에 달린 위반만** 센다. 주지 않으면 전부 센다.

    ``new_tus`` 는 이번에 처음 분석된 TU 들이다. 주면 집계를 ``byOrigin`` 으로
    갈라 담는다 - 위의 주석 참조.

    합계는 **중복을 지운 값**이다. 헤더 하나의 결함이 여러 TU 에 걸쳐 있어도
    한 번만 센다. 그래서 ``files`` 의 건수를 다 더한 값보다 작을 수 있고,
    그것이 맞는 동작이다.

    ``scope`` 로 어느 쪽이었는지 밝힌다. 이 값이 없으면 받아 보는 쪽이 "이 수가
    무엇의 수인지" 알 방법이 없다.
    """
    fresh = {str(tu) for tu in (new_tus or ())}
    files = []
    every = []
    by_origin = {NEW_SOURCES: [], CHANGED_FILES: []}
    scoped = False
    for tu in tu_dirs:
        changed = None if changed_by_tu is None else (changed_by_tu.get(str(tu)) or [])
        origin = NEW_SOURCES if str(tu) in fresh else CHANGED_FILES
        for ci in ci_files(tu):
            ids = None
            if changed is not None:
                ids = target_source_ids(ci, changed)
                scoped = True
            keys = _violation_keys(ci, ids=ids)
            counts = _counts(keys)
            every.extend(keys)
            by_origin[origin].extend(keys)
            files.append({
                "file": ci.name[:-3],           # main.c.ci -> main.c
                "ciPath": str(ci),
                "origin": origin,
                "total": counts["total"],
                "active": counts["active"],
            })
    result = dict(_counts(every))
    result.update({
        "files": files,
        "topRules": _rank(every, limit),
        "scope": "changedFiles" if scoped else "allSourceFiles",
        "note": LINK_DIFFERS_NOTE,
    })
    if new_tus is not None:
        result["byOrigin"] = {
            name: dict(_counts(keys),
                       tus=len({f["ciPath"] for f in files if f["origin"] == name}))
            for name, keys in by_origin.items()
        }
    return result


# ---------------------------------------------------------------------------
# analyzer-plugin 언어(java · kotlin · python · csharp)의 결함 집계
#
# 여기는 `.ci` 가 없다. 분석기가 워크스페이스 루트에 `defect.json` 을 통째로
# 떨어뜨리고, 그 안에 프로젝트 **전체** 의 결함이 평평한 리스트로 들어 있다
# (실측: 네 언어가 전부 같은 스키마 - startLine · severity · ruleSet · rule ·
# path · message). 그래서 파일별로 좁히는 일이 SQL 이 아니라 필터링이 된다.
# ---------------------------------------------------------------------------

# 결함 파일만으로 업로드 여부를 알 수 없다. 실행 결과의 uploaded 필드와 구분한다.
PLUGIN_ANALYSIS_NOTE = "전량 분석 결과에서 집계했습니다. 집계 범위는 scope 필드를 확인하세요."


def read_defect_json(ws):
    """워크스페이스의 `defect.json`. 없거나 깨졌으면 빈 리스트.

    실패를 예외로 올리지 않는다. 분석 자체는 성공했는데 집계를 못 읽는 상황이라
    보고할 수는 있고, 여기서 죽으면 방금 끝난 분석까지 실패로 보고된다.
    """
    from .languages import DEFECT_JSON
    try:
        data = json.loads(
            (Path(ws) / DEFECT_JSON).read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def summarize_defect_json(ws, only_paths=None, limit=5):
    """`defect.json` 집계. `summarize()` 와 **같은 모양**을 돌려준다.

    같은 모양이어야 하는 이유는 이것을 받아 쓰는 쪽이 언어를 모르기 때문이다 -
    `pipeline` 의 message 조립도, `hook._model_report` 도, 커맨드 본문의 해석
    규칙도 한 벌뿐이다. 언어마다 다른 키를 돌려주면 그 셋을 전부 갈래로 쪼개야 한다.

    `only_paths` 를 주면 그 파일들에 달린 결함만 센다 (`scope: changedFiles`).
    주지 않으면 프로젝트 전체다.

    `suppressed` 는 언제나 0 이다. `defect.json` 에는 억제 여부가 없고
    (`suppressionHash` 는 서버가 억제를 대조할 때 쓰는 해시일 뿐이다) 억제 목록은
    서버에 있다. 0 으로 두면 `active == total` 이라 사람에게 가는 문장이
    "결함 N건(억제 0건)" 이 되는데, 이것은 거짓이 아니라 **우리가 여기서 알 수
    있는 전부**다.
    """
    defects = read_defect_json(ws)
    wanted = {_norm(p) for p in only_paths} if only_paths is not None else None

    per_file = {}
    rule_counts = {}
    severities = {}
    total = 0
    for item in defects:
        if not isinstance(item, dict):
            continue
        path = item.get("path") or ""
        if wanted is not None and _norm(path) not in wanted:
            continue
        total += 1
        per_file[path] = per_file.get(path, 0) + 1
        key = (item.get("rule"), item.get("ruleSet"))
        rule_counts[key] = rule_counts.get(key, 0) + 1
        severity = item.get("severity")
        severities[severity] = severities.get(severity, 0) + 1

    ordered = sorted(rule_counts.items(), key=lambda kv: (-kv[1], str(kv[0][0])))[:limit]
    files = [{"file": Path(p).name, "path": p, "total": c, "active": c}
             for p, c in sorted(per_file.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {
        "total": total,
        "active": total,
        "suppressed": 0,
        "files": files,
        "topRules": [{"ruleName": k[0], "ruleSet": k[1], "count": v}
                     for k, v in ordered],
        "bySeverity": {str(k): v for k, v in sorted(
            severities.items(), key=lambda kv: str(kv[0]))},
        "scope": "changedFiles" if wanted is not None else "allSourceFiles",
        "note": PLUGIN_ANALYSIS_NOTE,
    }
