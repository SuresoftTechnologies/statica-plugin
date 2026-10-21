"""java · kotlin · python · csharp 의 analyze / upload.

C/C++ 쪽(`pipeline.run_analyze`)과 **결과 모양이 같아야 한다.** 이 값을 받아 쓰는
곳 - 훅의 요약 문장, 커맨드 본문의 해석 규칙, 모델에게 가는 보고문 - 이 전부 한
벌뿐이기 때문이다. 언어마다 다른 키를 돌려주기 시작하면 그 셋을 갈래마다 다시
써야 하고, 그러면 어느 한쪽이 조용히 낡는다.

같은 모양을 지키되, 여기서 **비어 있는 채로 남는** 필드가 있다. 그것들은 C/C++
전용 개념이라 이 갈래에 대응물이 없다.

    rebuild / rebuildNote      캡처가 없다. 빌드를 대신 돌려 줄 이유가 없다.
    analyzerFailures           모듈별 analyze.failed.json 이 없다.
    skippedTus                 TU 라는 단위가 없다 (실행 하나가 전부다).

일반 분석과 Stop 훅은 --no-upload 로 로컬 결과만 저장한다.
명시적 upload 와 bootstrap-finish 의 전체 분석만 서버에 업로드한다.
"""
from pathlib import Path

from . import analyzer, changes, defects, workspace
from .budget import MIN_CHILD_SECONDS

# C/C++ 갈래와 같은 키를 갖되 이쪽에서는 늘 비어 있는 자리들. 한곳에서 만들어
# 복사해 쓴다 - 경로마다 따로 채우면 어느 한 경로가 키를 빠뜨린다.
_NOT_APPLICABLE = {
    "rebuild": {"ran": False, "ok": False, "command": None,
                "returncode": None, "stdout": "", "stderr": "",
                "message": "이 언어는 빌드 캡처를 쓰지 않아 재빌드가 없습니다."},
    "rebuildNote": "",
    "analyzerFailures": {},
    "skippedTus": 0,
}

_EMPTY_DEFECTS = {"total": 0, "active": 0, "suppressed": 0, "files": [],
                  "topRules": [], "bySeverity": {}}


def _base_result(ws, key, project_dir, language, command):
    result = {
        "ok": True, "command": command,
        "workspace": str(ws), "projectKey": key, "projectDir": str(project_dir),
        "language": language.id,
        "analyzed": 0, "failures": [],
        "budgetExhausted": False, "budgetNote": "",
        "uncapturedNewFiles": [], "newlyUncapturedFiles": [], "uncapturedNote": "",
        "uploaded": False,
    }
    result.update(_NOT_APPLICABLE)
    return result


# 서버가 "이 프로젝트는 이미 분석 중" 이라고 거절할 때 응답에 들어오는 문구.
# 코드로 가려낼 수 없어서 (analyzer-plugin 의 종료 코드 체계는 analyzer-csa 와
# 다르고 공개된 표가 없다) 본문을 본다.
_BUSY_MARKERS = ("already being analyzed", "response code: 409")


def _busy_hint(run_result):
    """같은 프로젝트를 다른 실행이 붙잡고 있어 거절당한 것인가.

    --no-upload 여도 서버 연결은 필요하다. 서버가 동시 분석을 거절하면
    업로드 여부와 무관하게 원인을 전달한다.
    """
    text = ((run_result.get("stdout") or "") + (run_result.get("stderr") or "")).casefold()
    if any(marker in text for marker in _BUSY_MARKERS):
        return ("같은 프로젝트를 다른 실행이 분석 중입니다(훅과 커맨드가 겹쳤을 "
                "수 있습니다). 잠시 뒤 다시 시도하세요.")
    return None


def _out_of_scope_note(files):
    """분석 범위에 들어오지 못한 신규 소스가 있다는 사실 - 사건을 말하는 한 절.

    C/C++ 의 `_newly_uncaptured_note` 와 같은 자리이고 같은 규율이다: **이번
    실행에서** 새로 알게 된 것만 말한다. 억제된 파일이 남아 있는 내내 같은 말을
    붙이면 잔소리가 되어 읽히지 않는다.

    원인은 다르다. C/C++ 은 빌드가 컴파일하지 않아서고, 여기는 기술서의 소스
    루트나 `analysis.scope.json` 의 제외 규칙이 그 파일을 덮지 않아서다.
    """
    return (f"신규 파일 {len(files)}개가 분석 범위에 없어 이번에도 분석되지 "
            "않았습니다(기술서의 소스 루트나 제외 설정을 확인하세요)")


def _out_of_scope_detail(files):
    return (f"신규 파일 {len(files)}개가 분석 범위에 없습니다: "
            + ", ".join(str(f) for f in files))


def run(project_dir, ws, agent_json, language, key, force=False, deadline=None,
        command="pre-analyze", *, upload=False):
    """전량 분석한다. 변경이 없으면 아무것도 하지 않는다.

    ``force`` 는 변경 판정만 건너뛴다. 업로드는 별도의 ``upload`` 로 결정한다.

    ``deadline`` 은 `pipeline._now()`(단조 시계) 기준 절대 시각이다. 훅에서
    들어온 호출만 값이 있고, 슬래시 커맨드는 None 이다. 실행이 하나뿐이라 중간에
    잘라 낼 곳은 없지만, **그 하나에 남은 예산을 반드시 씌운다** - CLI 가 훅보다
    먼저 끝나야 하기 때문이다. 넘기면 Claude Code 가 훅을 취소하고, 취소가
    손자 프로세스까지 죽인다는 보장이 없어 워크스페이스 잠금이 고아로 남는다
    (budget.py 모듈 docstring).
    """
    from .pipeline import _budget_note, _now

    project_dir = Path(project_dir)
    result = _base_result(ws, key, project_dir, language, command)

    if workspace.status(agent_json) == workspace.STATUS_BOOTSTRAPPING:
        result["reason"] = "BOOTSTRAP_IN_PROGRESS"
        result["message"] = ("이 프로젝트는 아직 부트스트랩 중입니다. "
                             "분석 기술서를 준비한 뒤 bootstrap-finish 를 실행하세요.")
        result["defects"] = dict(_EMPTY_DEFECTS)
        return result

    detected = changes.plugin_changes(ws, project_dir, language)
    result["changedSources"] = detected["stale"]
    result["newFiles"] = detected["newFiles"]
    result["missingSources"] = detected["missing"]

    triggered = bool(detected["stale"] or detected["missing"])
    if not triggered and not force:
        result["reason"] = "NO_CHANGES"
        result["message"] = "변경된 소스가 없습니다."
        result["defects"] = dict(_EMPTY_DEFECTS)
        return result

    # 실행은 하나뿐이라 여기서 한 번만 예산을 잰다.
    timeout = analyzer.PLUGIN_TIMEOUT_SECONDS
    if deadline is not None:
        remaining = deadline - _now()
        if remaining < MIN_CHILD_SECONDS:
            result["budgetExhausted"] = True
            result["skippedTus"] = 1
            result["budgetNote"] = _budget_note(1)
            result["message"] = f"분석을 시작하지 못했습니다 ({result['budgetNote']}.)"
            result["defects"] = dict(_EMPTY_DEFECTS)
            return result
        timeout = min(timeout, remaining)

    # 분석 **전에** 신규 파일 목록을 적어 둔다. 분석이 끝나면 sourcefiles.db 가
    # 다시 쓰여서 "무엇이 이번에 새로 들어왔는지" 물을 수 없게 된다.
    triggered_new = {str(p) for p in detected["newFiles"]} & set(detected["stale"])

    run_result = analyzer.analyze_plugin(ws, language, key, agent_json, project_dir,
                                         timeout=timeout, upload=upload)
    if not run_result["ok"]:
        # 여기서는 `ok` 를 거짓으로 내린다. C/C++ 갈래는 TU 하나가 실패해도 다른
        # TU 는 성공했을 수 있어 `ok` 를 참으로 두지만, 이쪽은 실행이 하나뿐이라
        # 실패 = 아무것도 못 했음이다. 참으로 두면 "ok: true" 와 "분석에
        # 실패했습니다" 가 같은 응답에 담겨, 받아 읽는 쪽이 성공으로 처리한다.
        hint = run_result.get("hint") or "원인을 알 수 없습니다."
        result["ok"] = False
        result["code"] = "ANALYZE_FAILED"
        result["failures"].append({
            "returncode": run_result["returncode"],
            "hint": hint,
            "stderr": (run_result.get("stderr") or "")[-2000:],
            "stdout": (run_result.get("stdout") or "")[-2000:],
        })
        result["message"] = f"분석에 실패했습니다: {hint}"
        busy = _busy_hint(run_result)
        if busy:
            result["hint"] = busy
            result["message"] += f" {busy}"
        result["hookSummary"] = f"분석 실패 · {hint}"
        result["defects"] = dict(_EMPTY_DEFECTS)
        return result

    result["uploaded"] = upload
    # "대상 몇 개" 는 분석기가 실제로 본 소스 파일 수다. 읽지 못하면 1 로 둔다 -
    # 0 이면 훅이 "할 말이 없다"고 판단해 방금 끝난 분석을 통째로 삼킨다.
    analyzed_paths = changes.analyzed_sources(ws)
    result["analyzed"] = len(analyzed_paths) or 1

    # 업로드는 항상 전체 집계. 로컬 분석은 변경된 파일이 있으면 거기로 좁힌다.
    only = None if upload else (detected["stale"] or None)
    result["defects"] = defects.summarize_defect_json(ws, only_paths=only)

    # 이번에 새로 들어온 소스가 분석 뒤에도 db 에 없으면 분석 범위 밖이다.
    known_after = {p.replace("\\", "/").casefold() for p in analyzed_paths}
    still_out = sorted(p for p in triggered_new
                       if p.replace("\\", "/").casefold() not in known_after)
    all_out = sorted(str(p) for p in detected["newFiles"]
                     if str(p).replace("\\", "/").casefold() not in known_after)
    result["uncapturedNewFiles"] = all_out
    result["newlyUncapturedFiles"] = still_out
    if still_out:
        result["uncapturedNote"] = _out_of_scope_note(still_out)


    summary = result["defects"]
    result["hookSummary"] = (f"{result['analyzed']}개 파일 분석 완료 · 결함 "
                             f"{summary['active']}건")
    if upload:
        result["hookSummary"] += " · 서버 업로드됨"
    destination = "서버에 업로드했습니다" if upload else "로컬에 저장했습니다"
    result["message"] = (f"{result['analyzed']}개 파일을 분석하고 {destination} "
                         f"· 결함 {summary['active']}건 "
                         f"· 프로젝트 {key}")
    if result["uncapturedNewFiles"]:
        result["message"] += f" · {_out_of_scope_detail(result['uncapturedNewFiles'])}"
    return result


def run_upload(project_dir, ws, agent_json, language, key):
    """명시적 업로드와 bootstrap-finish: 변경 여부와 무관하게 전량 분석·업로드."""
    result = run(project_dir, ws, agent_json, language, key, force=True,
                 command="upload", upload=True)
    if result.get("uploaded"):
        result["message"] = (f"전체 분석과 업로드를 마쳤습니다 · 프로젝트 {key} "
                             f"· {result['analyzed']}개 파일 · 결함 "
                             f"{result['defects']['active']}건")
    return result
