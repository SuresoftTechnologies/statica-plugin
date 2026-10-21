import subprocess
import time
from pathlib import Path

from . import analyzer, changes, defects, languages, tu_history, workspace
from .budget import (CHILD_TIMEOUT_SECONDS, MIN_CHILD_SECONDS,
                     UNBOUNDED_CHILD_TIMEOUT_SECONDS)
from .errors import PluginError

# 결함 집계가 비어 있을 때의 모양. NO_CHANGES 로 일찍 빠지는 경로도 성공 경로와
# 같은 키를 갖도록, 성공 경로가 defects.summarize() 로 채우는 자리를 여기서 메운다.
_EMPTY_DEFECTS = {"total": 0, "active": 0, "suppressed": 0, "files": [], "topRules": []}


class NeedsBootstrap(Exception):
    """이 프로젝트에 연결된 워크스페이스가 없다. 부트스트랩이 필요하다."""

    def __init__(self, project_dir):
        super().__init__(f"워크스페이스가 연결되어 있지 않습니다: {project_dir}")
        self.project_dir = Path(project_dir)


# rebuild() 가 실행되지 않았거나 실행할 수 없을 때 돌려주는 기본 모양.
# {ran, ok, command, returncode, stdout, stderr} 계약을 모든 경로에서 지키기 위해
# 여기서 한 번만 정의하고 필요할 때마다 복사해서 쓴다.
_REBUILD_NOT_RUN = {
    "ran": False, "ok": False, "command": None,
    "returncode": None, "stdout": "", "stderr": "",
}


def _now():
    """단조 증가 시계.

    ``time.time()`` 이 아니라 ``time.monotonic()`` 을 쓴다 — 실행 도중 시스템
    시각이 바뀌면 벽시계는 뒤로 갈 수 있고, 그러면 마감 계산이 통째로 망가진다.
    테스트가 시계를 갈아끼울 수 있도록 한 겹 감싸 둔다.
    """
    return time.monotonic()


def _child_timeout(deadline):
    """이번 자식에게 건넬 제한 시간(초). ``None`` 이면 "시작하지 마라"는 뜻이다.

    ``deadline`` 은 ``_now()`` 기준 절대 시각이거나 None(전체 제한 없음)이다.
    남은 예산이 ``MIN_CHILD_SECONDS`` 아래로 내려가면 자식을 띄우지 않는다 —
    이유는 budget.py 에 적어 두었다.
    """
    if deadline is None:
        return UNBOUNDED_CHILD_TIMEOUT_SECONDS
    remaining = deadline - _now()
    if remaining < MIN_CHILD_SECONDS:
        return None
    return min(CHILD_TIMEOUT_SECONDS, remaining)


def _budget_note(skipped):
    """예산에 걸려 중단했다는 사실을 사람에게 설명하는 한 문장.

    이 문장을 만드는 곳은 여기 하나뿐이다. ``result["budgetNote"]`` 로 실어
    보내면 hook 도 자기 요약 뒤에 이 값을 그대로 붙인다 — 같은 문장을 두 군데서
    각자 조립하면 서로 어긋난다. 실제로 어긋났었다: 남은 대상이 0인데도 hook 이
    "0개 대상을 남기고 중단했습니다"라고 말했다.
    """
    if skipped:
        return f"시간 예산이 다 되어 {skipped}개 대상을 남기고 중단했습니다"
    # 남긴 대상이 없는 경우 — 재빌드를 시작하지 못한 채 분석할 것도 없었다.
    return "남은 시간 예산이 없어 재빌드를 시작하지 못했습니다"


def _uncaptured_note(by_reason):
    """지금 캡처되지 않은 채 남아 있는 소스가 몇 개인지 — 상태를 말하는 문장.

    ``/statica:pre-analyze`` 의 ``message`` 앞머리다. 세는 대상은 언제 포기했든 상관없이
    현재 억제된 파일 **전부**다.

    **원인별로 나눠 말한다.** 빌드 밖 소스는 할 일이 없고 빌드 실패는 고쳐야 하는데,
    한 문장으로 뭉치면 읽는 사람이 그 둘을 구분할 수 없다 (`workspace.suppressed_by_reason`).
    """
    return " · ".join(_reason_clauses(by_reason))


def _reason_clauses(by_reason, event=False):
    """원인별 절. 문장을 만드는 곳을 여기 하나로 모은다.

    ``event`` 는 훅이 쓰는 판이다 — 지금 상태가 아니라 방금 일어난 일로 적는다.
    """
    outside = by_reason.get(workspace.OUTSIDE_BUILD) or []
    failed = by_reason.get(workspace.BUILD_FAILED) or []
    clauses = []
    if outside:
        clauses.append(
            f"소스 {len(outside)}개를 분석 대상에서 새로 제외했습니다(빌드에 포함되지 않음)"
            if event else
            f"소스 {len(outside)}개가 빌드에 포함되지 않아 분석 대상이 아닙니다")
    if failed:
        clauses.append(f"소스 {len(failed)}개가 빌드 실패로 캡처되지 않았습니다"
                       "(빌드를 고치면 다시 잡힙니다)")
    return clauses


def _origin_clause(summary, created):
    """신규 소스와 변경 영향을 나눠 말하는 절.

    두 갈래는 **세는 기준이 다르다** - 신규 소스는 그 파일 전부를, 변경된 TU 는
    바뀐 파일에 달린 것만 센다(defects.summarize 주석). 각자는 맞는 답이지만
    한 숫자로 합치면 그 수가 무엇의 수인지 말할 수 없다. 실측으로 겪은 모양이:
    "결함 83건" 이 사실은 신규 power.cpp 57건 + 헤더 변경 영향 13건이었고,
    사용자는 그 83을 "서로 다른 코드 문제 83개" 로 읽었다.

    그래서 둘이 섞였을 때만 나눠 말한다. 한 갈래뿐이면 앞머리가 이미 그 답이다.
    """
    origins = summary.get("byOrigin") or {}
    fresh = origins.get(defects.NEW_SOURCES) or {}
    changed = origins.get(defects.CHANGED_FILES) or {}
    clauses = [f"새 소스 {len(created)}개 {fresh.get('active', 0)}건"]
    if changed.get("active"):
        clauses.append(f"변경 영향 {changed['active']}건")
    return " · ".join(clauses)


def _newly_uncaptured_note(by_reason):
    """이번 실행에서 새로 포기한 파일이 몇 개인지 — 사건을 말하는 짧은 한 절.

    hook 의 시스템 메시지에 그대로 붙는다 — 그래서 경로를 나열하지 않는다.
    ``_budget_note`` 와 같은 규칙이다: 이 문장을 만드는 곳은 여기 하나뿐이고,
    hook 은 ``result["uncapturedNote"]`` 를 받아 쓰기만 한다.

    hook 이 받는 것이 "이번에 포기한 파일"뿐인 이유는, 훅이 매 응답마다 돌기
    때문이다. 억제된 파일이 남아 있는 내내 같은 절을 붙이면 잔소리가 되고,
    반복되는 잔소리는 읽히지 않는다 — 침묵을 깨자고 한 일이 도로 침묵이 된다.

    그래서 문장도 상태가 아니라 사건으로 적는다. 세는 범위가 다른 두 문장을 똑같이
    "소스 N개가 …" 로 적으면, 같은 사실을 두고 훅은 1개 /statica:pre-analyze 는
    2개라고 말하는 꼴이 된다 — 문장 주인을 하나로 모은 이유가 바로 그 어긋남이었다.
    """
    return " · ".join(_reason_clauses(by_reason, event=True))


_NO_BUILD_COMMAND = "agent.json 에 buildCommand 가 없어 재빌드를 건너뜁니다."


def _no_build_command_note(files):
    """빌드 커맨드가 없어 신규 파일을 잡지 못했다는 사실 — 사람에게 닿는 한 문장.

    GUI 로만 빌드하는 환경(Visual Studio, MPLAB X …)은 `buildCommand` 가 정당하게
    비어 있다. 그러면 재빌드가 아예 돌지 않고, 돌지 않았으니 시도 기록도 남지
    않고, 기록이 없으니 `suppressed_new_files` 도 비어서 `uncapturedNewFiles` 가
    빈 채로 남는다 — 사용자가 새로 만든 `.c` 는 분석되지도, 언급되지도 않는다.
    이 플러그인이 없애려던 침묵과 정확히 같은 모양이라, 여기서 반드시 말한다.

    문장의 주인은 pipeline 하나다 (`_budget_note` · `_uncaptured_note` 와 같은 규칙).
    """
    return (f"agent.json 에 buildCommand 가 없어 재빌드를 건너뛰었고, 신규 파일 "
            f"{len(files)}개가 캡처되지 않아 이번에도 분석되지 않았습니다 "
            f"(IDE 에서 직접 빌드한 뒤 다시 실행하세요)")


# 경로를 몇 개까지 늘어놓을지. gnulib 같은 vendored 트리가 딸려 오면 수천 개가
# 잡히는데(실측 3479개), 그걸 다 늘어놓으면 message 가 사람이 읽을 수 없게 된다.
_DETAIL_LIMIT = 20


def _uncaptured_detail(by_reason):
    """``message`` 에 들어가는 긴 판 — 상태 문장 뒤에 경로를 그대로 붙인다.

    경로까지만이다. 어떤 결함이 있는지는 말하지 않는다 — 이 플러그인이 보고하는
    것은 분석의 상태이지 결함의 내용이 아니다.
    """
    files = [p for key in (workspace.OUTSIDE_BUILD, workspace.BUILD_FAILED)
             for p in (by_reason.get(key) or [])]
    shown = [str(f) for f in files[:_DETAIL_LIMIT]]
    rest = len(files) - len(shown)
    listing = ", ".join(shown) + (f" 외 {rest}개" if rest > 0 else "")
    return f"{_uncaptured_note(by_reason)}: {listing}"


def rebuild(project_dir, agent_json, timeout=None):
    """신규 파일을 캡처하기 위해 프로젝트를 다시 빌드한다.

    ``timeout`` 은 호출자가 정한다 — None 이면 훅 예산에 묶이지 않는 기본값이다.
    """
    command = workspace.build_command(agent_json)
    if not command:
        return dict(_REBUILD_NOT_RUN, message=_NO_BUILD_COMMAND)
    if timeout is None:
        timeout = UNBOUNDED_CHILD_TIMEOUT_SECONDS
    try:
        proc = subprocess.run(command, cwd=str(project_dir), shell=True,
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return {
            "ran": True,
            "ok": False,
            "command": command,
            "returncode": -1,
            "stdout": analyzer.decode(e.stdout or b"").strip()[-4000:],
            "stderr": analyzer.decode(e.stderr or b"").strip()[-4000:],
        }
    return {
        "ran": True,
        "ok": proc.returncode == 0,
        "command": command,
        "returncode": proc.returncode,
        "stdout": analyzer.decode(proc.stdout).strip()[-4000:],
        "stderr": analyzer.decode(proc.stderr).strip()[-4000:],
    }


def run_analyze(project_dir, parallel=None, force=False, deadline=None):
    """변경된 TU만 골라 재분석하고 결함을 모아 돌려준다.

    ``result["defects"]`` 는 이번 실행에서 분석한 TU들만의 집계다 — 프로젝트
    전체 누적 결함 총계가 아니므로, 매 실행마다 값이 달라질 수 있다.

    ``deadline`` 은 ``_now()``(단조 시계) 기준 절대 시각으로, 이 실행 전체가
    끝나야 하는 시점이다. ``None`` 이면 전체 제한이 없다는 뜻이고, 그게
    ``/statica:pre-analyze`` 슬래시 커맨드의 올바른 동작이다 — 훅 예산에 묶이지
    않으므로 전체 재빌드가 30분을 써도 된다. 훅에서 들어오는 호출만
    ``hook.run_stop`` 이 계산한 마감을 넘긴다.

    ``result["uncapturedNewFiles"]`` 는 재빌드로도 끝내 캡처하지 못해 이번에도
    분석되지 않은 신규 소스 **전부**다. 언제 포기했든 상관없이 매번 전부 싣는다 —
    ``/statica:pre-analyze`` 는 사용자가 "지금 상태가 어떤가"를 물으러 오는 곳이고,
    그 물음에는 언제나 온전히 답해야 한다. ``message`` 도 이 전부를 나열한다.

    ``result["rebuildNote"]`` 는 재빌드가 돌지 **못했다**는 사실을 말하는 자리다.
    지금은 한 경우뿐이다: 신규 파일이 있는데 ``buildCommand`` 가 없어 재빌드를
    시작조차 못 한 경우. 그때는 시도 기록이 남지 않아 ``uncapturedNewFiles`` 도
    비므로, 이 문장이 없으면 사용자가 방금 추가한 소스가 분석되지 않았다는 사실을
    말해 주는 곳이 아무 데도 없다.

    ``result["newlyUncapturedFiles"]`` 는 그중 **이번 실행에서** 포기한 것들이고,
    ``uncapturedNote`` 는 그것이 있을 때만 채워진다. 훅은 이 절만 말한다 — 매
    응답마다 같은 말을 반복하면 잔소리가 되어 아무도 읽지 않는다.

    마감에 걸려 중단해도 그것은 오류가 아니다 — ``ok`` 는 참으로 남고, 이미
    끝난 분석은 평소대로 보고한다. 다만 ``budgetExhausted`` 와 ``skippedTus``
    로, 그리고 ``message`` 로 실행이 잘렸다는 사실을 반드시 알린다.
    """
    project_dir = Path(project_dir)
    ws = workspace.find_workspace_for(project_dir)
    if ws is None:
        raise NeedsBootstrap(project_dir)

    agent_json = workspace.read_agent_json(ws) or {}

    # 상태를 프로젝트 키보다 **먼저** 본다. 부트스트랩이 끝나기 전의 app.data.json
    # 은 projectKey 가 비어 있으므로, 순서를 뒤집으면 진행 중인 부트스트랩이
    # "projectKey 가 없습니다" 라는 엉뚱한 오류로 보고된다 — 사용자는 설정이
    # 깨진 줄 알고 워크스페이스를 지우려 든다. 실제 상태는 "아직 하는 중" 이다.
    if workspace.status(agent_json) == workspace.STATUS_BOOTSTRAPPING:
        # 변경 탐지도, 재빌드도 시작하지 않는다. 캡처가 없는 워크스페이스를
        # 분석하려 들면 매 Stop 훅마다 혼란스러운 잡음만 남긴다.
        return {
            "ok": True, "command": "pre-analyze",
            "workspace": str(ws), "projectDir": str(project_dir),
            "projectKey": workspace.project_key(ws),
            "reason": "BOOTSTRAP_IN_PROGRESS",
            "message": ("이 프로젝트는 아직 부트스트랩 중입니다. "
                        "남은 단계를 마친 뒤 bootstrap-finish 를 실행하세요."),
            "rebuild": dict(_REBUILD_NOT_RUN), "analyzed": 0, "failures": [],
            "budgetExhausted": False, "skippedTus": 0, "skippedModules": 0,
            "budgetNote": "", "newTus": [],
            "uncapturedNewFiles": [], "newlyUncapturedFiles": [],
            "uncapturedByReason": {}, "newlyUncapturedByReason": {},
            "uncapturedNote": "", "rebuildNote": "",
            "defects": dict(_EMPTY_DEFECTS), "analyzerFailures": {},
        }

    key = workspace.project_key(ws)
    if not key:
        raise PluginError("NO_PROJECT_KEY",
                          f"{workspace.APP_DATA_REL} 에 projectKey 가 없습니다: {ws}")

    # 갈림길은 여기 하나뿐이다. 아래 본문은 전부 C/C++ (analyzer-csa) 전용이다 -
    # 캡처 · TU · 재빌드는 그쪽에만 있는 개념이라, 타 언어를 여기로 흘려보내면
    # "변경된 분석 대상이 없습니다" 만 영원히 돌려주는 조용한 고장이 된다.
    language_id = languages.of_agent_json(agent_json)
    if languages.is_plugin(language_id):
        from . import plugin_pipeline
        return plugin_pipeline.run(project_dir, ws, agent_json,
                                   languages.get(language_id), key,
                                   force=force, deadline=deadline)

    result = {
        "ok": True, "command": "pre-analyze",
        "workspace": str(ws), "projectKey": key, "projectDir": str(project_dir),
        "rebuild": dict(_REBUILD_NOT_RUN), "analyzed": 0, "failures": [],
        "budgetExhausted": False, "skippedTus": 0, "skippedModules": 0,
        "budgetNote": "", "newTus": [],
        "uncapturedNewFiles": [], "newlyUncapturedFiles": [],
        "uncapturedByReason": {}, "newlyUncapturedByReason": {},
        "uncapturedNote": "",
        "rebuildNote": "",
    }

    new_files = changes.new_source_files(project_dir, ws)
    if new_files:
        result["newFiles"] = [str(p) for p in new_files]
        # 이번 실행에 손대기 **전에** 이미 포기해 둔 파일들. 나중에 "이번에 포기한
        # 것"만 골라내는 기준이 된다. 따로 상태를 더 만들지 않는다 — 이미 남기고
        # 있는 기록(시도 횟수와 성패)에 대고 실행 전후로 두 번 물어볼 뿐이다.
        already_given_up = {
            str(p) for p in workspace.suppressed_new_files(agent_json, new_files)}
        # 빌드가 끝내 캡처하지 못하는 소스는 계속 "신규"로 남는다. 아직 가망이 있는
        # 파일이 있을 때만 재빌드해서, 같은 파일로 매번 전체 빌드가 도는 것을 막는다.
        if workspace.needs_rebuild_for(agent_json, new_files):
            timeout = _child_timeout(deadline)
            if timeout is None:
                # 예산이 없다. 재빌드를 시도했다고 기록하지도 않는다 — 정말로
                # 시도한 적이 없으므로, 다음 실행이 다시 시도할 수 있어야 한다.
                result["budgetExhausted"] = True
                result["rebuild"] = dict(_REBUILD_NOT_RUN,
                                         message=_budget_note(0) + ".")
            else:
                result["rebuild"] = rebuild(project_dir, agent_json, timeout=timeout)
                if result["rebuild"]["ran"]:
                    agent_json = workspace.mark_rebuild_attempted(
                        ws, agent_json, new_files, result["rebuild"]["ok"])
                    # 방금 돈 빌드가 잡아간 파일은 더 이상 신규가 아니다. 다시 재어야
                    # 캡처된 파일을 "캡처되지 않았다"고 잘못 보고하지 않는다.
                    new_files = changes.new_source_files(project_dir, ws)
                # 시작조차 못 한 빌드는 아무것도 기록하지 않는다 — 바로 위 예산
                # 분기와 같은 이유다. buildCommand 가 없어 돌지 못한 것을 "빌드가
                # 실패했다"로 적으면, 시도 횟수만 까먹다 파일이 은퇴하고, 나중에
                # buildCommand 를 채워 넣어도 되살아나지 않는다.
                #
                # 다만 기록하지 않는다는 것과 말하지 않는다는 것은 다르다. 기록이
                # 없으면 아래 suppressed_new_files 도 비어서 uncapturedNewFiles 가
                # 빈 채로 남는다 — GUI 환경(buildCommand 가 정당하게 없는 환경)의
                # 신규 파일이 분석되지도 언급되지도 않는 침묵이 여기서 생긴다.
                elif not workspace.build_command(agent_json):
                    result["rebuildNote"] = _no_build_command_note(new_files)
        else:
            result["rebuild"] = dict(
                _REBUILD_NOT_RUN,
                message="이미 재빌드를 시도한 신규 파일뿐이라 재빌드를 건너뜁니다.")

        # 재시도를 다 쓴 파일과, 성공한 빌드가 끝내 잡지 못한 파일. 둘 다 캡처되지
        # 않은 채로 남아 영영 분석되지 않는다 — 조용히 지나가면 사용자는 자기가
        # 추가한 파일이 검사되고 있다고 믿는다.
        by_reason = workspace.suppressed_by_reason(agent_json, new_files)
        result["uncapturedByReason"] = {k: [str(p) for p in v]
                                        for k, v in by_reason.items()}
        result["uncapturedNewFiles"] = [p for v in result["uncapturedByReason"].values()
                                        for p in v]
        # 훅이 말하는 것은 상태가 아니라 사건이다 — 방금 포기한 파일만 고른다.
        result["newlyUncapturedByReason"] = {
            k: [p for p in v if p not in already_given_up]
            for k, v in result["uncapturedByReason"].items()}
        result["newlyUncapturedFiles"] = [
            p for v in result["newlyUncapturedByReason"].values() for p in v]
        if result["newlyUncapturedFiles"]:
            result["uncapturedNote"] = _newly_uncaptured_note(
                result["newlyUncapturedByReason"])

    # 변경과 신규는 서로 다른 파일이 답한다 - 변경은 tu.cache.json(그 TU 가 읽은
    # 파일들의 mtime), 신규는 module.capture.json(캡처됐는데 TU 가 없는 소스)이다.
    # 둘 다 **분석을 시작하기 전에** 떠 둔다. 분석이 끝나면 기준선이 앞으로 가서
    # 같은 질문에 다시 답할 수 없다.
    history = tu_history.read(ws)
    stale_tus = [tu for tu in changes.tu_dirs(ws)
                 if changes.is_tu_stale(ws, tu, history)]
    # 어떤 파일 때문에 이 TU 가 대상이 됐는지. 기록은 한 번만 읽어 전부에 돌려 쓴다.
    changed_by_tu = {str(tu): changes.stale_sources(ws, tu, history)
                     for tu in stale_tus}
    pending_modules = changes.modules_missing_tus(ws)

    if not stale_tus and not pending_modules:
        result["reason"] = "NO_CHANGES"
        result["message"] = "변경된 분석 대상이 없습니다."
        result["defects"] = dict(_EMPTY_DEFECTS)
        result["analyzerFailures"] = {}
        if result["budgetExhausted"]:
            # 여기까지 왔다면 분석할 대상 자체가 없었다 — 남기고 온 것은 없다.
            result["budgetNote"] = _budget_note(result["skippedTus"] + result["skippedModules"])
            result["message"] += f" ({result['budgetNote']}.)"
        if result["rebuildNote"]:
            result["message"] += f" ({result['rebuildNote']}.)"
        if result["uncapturedNewFiles"]:
            result["message"] += (
                f" ({_uncaptured_detail(result['uncapturedByReason'])}.)")
        return result

    attempted = []
    # 성공한 TU -> 그 분석을 **시작한** 시각. 끝난 시각을 쓰면 분석 도중에 저장된
    # 편집이 영영 묻힌다 (tu_history.now 참조).
    analyzed_at = {}

    # 모듈 분석을 먼저 돌린다. 여기 걸린 소스는 **한 번도 분석된 적이 없고**,
    # 변경된 TU 는 낡았을지언정 결과가 이미 있다. 예산이 모자랄 때 무엇을 먼저
    # 살릴지의 문제라, 아무 결과도 없는 쪽이 우선이다.
    before = set(changes.tu_dirs(ws))
    covered = set()
    for index, module in enumerate(pending_modules):
        timeout = _child_timeout(deadline)
        if timeout is None:
            result["budgetExhausted"] = True
            result["skippedModules"] = len(pending_modules) - index
            break
        started = tu_history.now()
        run = analyzer.analyze_module(ws, module, key, parallel=parallel,
                                      force=force, timeout=timeout)
        if run["ok"]:
            covered.add(module)
            # -m 은 모듈의 TU 를 전부 훑는다. 새로 만든 것뿐 아니라 원래 있던
            # 것도 이 시점에 최신이 되므로 기준선을 다 같이 옮긴다.
            for tu in changes.module_tu_dirs(module):
                analyzed_at[tu] = started
        else:
            result["failures"].append({
                "module": str(module),
                "returncode": run["returncode"],
                "hint": run.get("hint"),
                "stderr": run.get("stderr", "")[-2000:],
            })

    # 새로 생긴 TU = 이번에 처음 분석된 소스. 실패한 모듈이 남긴 것은 믿지 않는다.
    created = [tu for tu in changes.tu_dirs(ws)
               if tu not in before and tu.parent.parent in covered]
    result["newTus"] = [str(tu) for tu in created]
    attempted.extend(created)
    # 성공한 모듈의 TU 는 -m 이 이미 돌렸다. 여기서 걸러내지 않으면 같은 TU 를 두
    # 번 분석한다. 실패했거나 예산에 걸려 못 돈 모듈은 그대로 -t 로 내려간다.
    targets = []
    for tu in stale_tus:
        if tu.parent.parent in covered:
            attempted.append(tu)
        else:
            targets.append(tu)
    result["analyzed"] += len(attempted)

    for index, tu in enumerate(targets):
        # 자식을 띄우기 직전마다 남은 예산을 다시 잰다. 앞선 자식이 얼마나
        # 걸렸는지는 돌려보기 전에는 알 수 없다.
        timeout = _child_timeout(deadline)
        if timeout is None:
            result["budgetExhausted"] = True
            result["skippedTus"] = len(targets) - index
            break
        attempted.append(tu)
        started = tu_history.now()
        run = analyzer.analyze_tu(ws, tu, key, parallel=parallel, force=force,
                                  timeout=timeout)
        if run["ok"]:
            result["analyzed"] += 1
            analyzed_at[tu] = started
        else:
            result["failures"].append({
                "tu": str(tu),
                "returncode": run["returncode"],
                "hint": run.get("hint"),
                "stderr": run.get("stderr", "")[-2000:],
            })

    # 기록은 루프가 끝난 뒤 한 번만 쓴다. 중간에 프로세스가 죽으면 그 TU 들이 다음
    # 실행에 한 번 더 돌 뿐이라(손해지 고장이 아니다) 매번 쓸 이유가 없다.
    tu_history.record(ws, analyzed_at)

    # 시작조차 못 한 TU 의 .ci 는 지난 실행이 남긴 낡은 결과다. 이번 실행이 실제로
    # 돌린 것만 집계해야 "이번 실행의 결함"이라는 의미가 유지된다.
    result["defects"] = defects.summarize(attempted, changed_by_tu=changed_by_tu,
                                          new_tus=created)
    result["analyzerFailures"] = analyzer.read_failures(ws)
    result["message"] = (
        f"{result['analyzed']}개 대상 분석 완료 · 결함 "
        f"{result['defects']['active']}건(억제 {result['defects']['suppressed']}건)")
    # 훅이 사용자에게 한 줄로 붙이는 문장. 여기서 만들어 실어 보낸다 - 훅이 자기
    # 손으로 조립하면 갈래마다(C/C++ · 타 언어) 같은 문장을 두 번 쓰게 되고, 두
    # 판본은 반드시 어긋난다 (`_budget_note` 와 같은 규율이다).
    result["hookSummary"] = (f"{result['analyzed']}개 대상 분석 완료 · 결함 "
                             f"{result['defects']['active']}건")
    # 새로 추가된 소스가 처음 분석에 들어갔다는 것은 사건이다. 지금까지 이 소스는
    # 어느 관문에도 걸리지 않아 조용히 빠져나갔다 (changes.modules_missing_tus).
    # 그리고 그때는 앞머리의 합계가 두 기준을 섞은 수라서, 반드시 갈라 말한다.
    if created:
        clause = _origin_clause(result["defects"], created)
        result["message"] += f" · {clause}"
        result["hookSummary"] += f" · {clause}"
    if result["budgetExhausted"]:
        result["budgetNote"] = _budget_note(result["skippedTus"] + result["skippedModules"])
        result["message"] += f" · {result['budgetNote']}"
    if result["rebuildNote"]:
        result["message"] += f" · {result['rebuildNote']}"
    if result["uncapturedNewFiles"]:
        result["message"] += f" · {_uncaptured_detail(result['uncapturedByReason'])}"
    return result
