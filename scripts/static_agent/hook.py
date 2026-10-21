import time

from . import budget, pipeline, settings, state
from .errors import PluginError

EXIT_OK = 0

# 훅은 **연결된 프로젝트에서만** 말한다.
#
# Stop 훅은 디렉터리를 가리지 않고 모든 세션의 모든 응답 끝에 돈다. 예전에는
# 워크스페이스가 없으면 exit 2 로 부트스트랩 안내를 모델에게 밀어 넣었는데,
# 그러면 STATIC 과 아무 상관 없는 작업 중에도 끼어든다 — 다른 제품의 브랜치를
# 조사하던 세션이 부트스트랩 제안으로 끊기는 일이 실제로 있었다. 날씨를 물어봐도
# 뜬다.
#
# 최초 연결은 사용자가 시작할 일이지 훅이 아무 데서나 권할 일이 아니다. 그래서
# 워크스페이스가 없으면 조용히 빠진다. 연결하고 싶으면 `/statica:pre-analyze` 가
# `NEEDS_BOOTSTRAP` 으로 그 자리에서 안내한다.


_REPORT_RULES = """\

이 결과를 사용자에게 전하라. 지킬 것:
- 이 집계는 **이번 실행이 분석한 범위**의 것이다. 프로젝트 전체 누적 결함 수가 아니며,
  그 점을 함께 밝혀라.
- 결함을 파일별로 나열하지 마라. 이 플러그인의 역할은 분석까지다.
- **분석은 이미 끝났다. pre-analyze 나 upload 를 다시 실행하지 마라.** 방금 이 훅이 돌렸으므로
  지금 pre-analyze 를 부르면 "변경 없음"만 나온다.
"""

# 변경된 파일로 좁혔다는 사실을 말하는 한 줄. 이유가 갈래마다 다르다 - C/C++ 은
# TU 에 전처리로 딸려 온 시스템 헤더를 빼야 해서고 (실측: TU 하나에 헤더 159개),
# 타 언어는 전량 분석 결과에서 방금 건드린 파일만 골라내야 해서다.
_SCOPE_NOTE_CCPP = ("이 집계는 **이번에 변경된 파일에 달린 위반**만 센 것이다 "
                    "(TU 에 딸려 온 시스템 헤더의 결함은 제외).")
_SCOPE_NOTE_PLUGIN = ("이 집계는 프로젝트 전체 분석 결과에서 **이번에 변경된 "
                      "파일에 달린 위반**만 골라 센 것이다.")


def _model_report(result, text):
    """모델 컨텍스트에 넣을 보고문.

    사용자에게 가는 한 줄(``text``)을 그대로 머리로 쓰고 룰별 집계를 덧붙인다.
    문장을 새로 짓지 않는다 — 같은 말을 두 군데서 조립하면 두 판본이 어긋난다.
    """
    lines = [text]
    summary = result.get("defects") or {}
    if summary.get("scope") == "changedFiles":
        lines.append("")
        lines.append(_SCOPE_NOTE_PLUGIN if result.get("language")
                     else _SCOPE_NOTE_CCPP)
    if summary.get("note"):
        lines.append(summary["note"])
    rules = ((result.get("defects") or {}).get("topRules") or [])
    if rules:
        lines.append("")
        lines.append("룰별 상위:")
        for rule in rules:
            lines.append(f"  - {rule.get('ruleName')} "
                         f"({rule.get('ruleSet')}) {rule.get('count')}건")
    lines.append(_REPORT_RULES)
    return "\n".join(lines)


def run_stop(payload, cwd):
    """Stop 훅 본체. ``(exit_code, stderr, stdout_payload)`` 를 돌려준다.

    **종료 코드는 언제나 0 이다.** 훅은 사용자의 턴을 막지 않는다. ``stderr`` 는
    남아 있지만 지금은 항상 빈 문자열이다 — 종료 코드 0 의 stderr 는 디버그
    로그로만 가고 아무도 읽지 않으므로, 할 말은 전부 stdout 으로 나간다.

    - ``stdout_payload`` 는 할 말이 있을 때만 채워진다. 호출한 쪽(cli.main)이 이
      dict 를 그대로 stdout 에 JSON 으로 실어 보낸다. 두 키가 들어간다.

      ``systemMessage`` 는 **사용자** 채널이다. 응답 아래에 한 줄로 붙는다.
      ``hookSpecificOutput.additionalContext`` 는 **모델** 채널이다. 같은 결과를
      모델 컨텍스트에도 넣어 준다.

      둘 다 필요하다. systemMessage 만 보내면 사용자는 한 줄을 보지만 모델은
      훅이 무엇을 찾았는지 전혀 모른다 — 바로 다음 턴에 "방금 분석 결과 보여
      줘" 라고 하면 아무 것도 답하지 못하고, ``pre-analyze`` 를 다시 돌려 봐야 이미
      최신이라 "변경된 대상 없음"만 나온다. 실제로 그렇게 막혔다.

      Stop 의 ``additionalContext`` 는 대화를 이어가게 하므로, 훅이 분석을 한
      응답 뒤에는 모델의 보고 턴이 하나 더 붙는다. 그 턴이 끝날 때의 훅은
      ``stop_hook_active`` 게이트에서 즉시 빠지므로 반복되지 않는다.

    할 말이 없는 경로는 payload 가 빈 dict 다 — 조용히 지나가야 한다.

    바깥쪽 try/except 는 백스톱이다 — payload 가 기형이거나 게이트 체인 안쪽
    어딘가에서 예상 못 한 예외가 나와도 여기서 걸러져 EXIT_OK 가 된다.
    """
    try:
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            return EXIT_OK, "", {}              # 기형 payload — 아무 것도 하지 않는다
        session_id = payload.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            session_id = str(session_id)        # state 조회가 해시 가능하도록 강제
        if payload.get("stop_hook_active"):
            return EXIT_OK, "", {}              # 훅으로 인한 재진입 — 즉시 빠진다
        # 스위치는 프로젝트 단위다. 훅은 세션 id 도 받지만 그것으로 조회하지
        # 않는다 — 슬래시 커맨드가 아는 것은 작업 디렉터리뿐이고, 양쪽이 같은 키를
        # 봐야 스위치가 실제로 닿는다 (state.py 모듈 docstring 참조).
        if not state.is_analysis_enabled(cwd):
            return EXIT_OK, "", {}
        try:
            settings.read_server_setting()
        except PluginError:
            return EXIT_OK, "", {}              # 설정 문제로 작업을 막지 않는다

        try:
            # 훅 예산 아래에서 도는 유일한 경로다. 실행 전체의 마감을 여기서
            # 정해 넘긴다 — 지금 훅 예산 안에 있다는 것을 아는 것은 여기뿐이다.
            deadline = time.monotonic() + budget.RUN_BUDGET_SECONDS
            result = pipeline.run_analyze(cwd, deadline=deadline)
        except pipeline.NeedsBootstrap:
            # 연결되지 않은 프로젝트에서는 아무 말도 하지 않는다 (모듈 상단 주석).
            return EXIT_OK, "", {}
        except PluginError:
            return EXIT_OK, "", {}
        except Exception:
            return EXIT_OK, "", {}              # 도구 고장이 코딩을 막지 않는다

        # 예산이 다 되어 잘린 실행은 분석한 대상이 하나도 없더라도 반드시 말한다 —
        # 조용히 지나가면 사용자는 분석이 다 끝난 줄 안다.
        #
        # 예산 문장 자체는 만들지 않고 pipeline 이 만든 것을 그대로 붙인다. 같은
        # 문장을 여기서 또 조립하면 두 판본이 어긋난다 — 실제로 어긋났었다.
        note = result.get("budgetNote") or ""
        # 캡처되지 않은 신규 파일도 마찬가지다 — 사용자가 추가한 파일이 분석에서
        # 빠졌는데 아무 말도 하지 않으면, 그 파일은 검사된 것으로 오해된다.
        #
        # 다만 이 절은 pipeline 이 "이번 실행에서 포기한 파일"이 있을 때만 채운다.
        # 훅은 매 응답마다 도니까, 억제된 파일이 남아 있는 내내 같은 말을 붙이면
        # 잔소리가 되고 결국 읽히지 않는다. 지금 상태 전체가 궁금하면
        # /statica:pre-analyze 가 uncapturedNewFiles 로 언제나 온전히 답한다.
        #
        # 문장은 여기서 만들지 않는다. pipeline 이 만든 것을 그대로 붙인다.
        uncaptured = result.get("uncapturedNote") or ""
        # 분석이 실패했으면 반드시 말한다. 조용히 지나가면 사용자는 분석이 계속
        # 도는 줄 알고 코딩을 이어간다 - 이 플러그인이 없애려던 침묵 그 자체다.
        # 고쳐질 때까지 매 응답에 붙는 것은 감수한다: 망가진 분석은 잔소리를
        # 들을 자격이 있고, 고치면 곧바로 멈춘다.
        if result.get("analyzed") or note or uncaptured or result.get("failures"):
            summary = result.get("defects") or {}
            # 요약 문장은 pipeline 이 만든다 - 갈래마다 세는 단위가 다르기
            # 때문이다 (C/C++ 은 TU, 타 언어는 소스 파일 수 + 업로드 사실).
            # 여기서 조립하면 그 차이가 훅에만 반영되지 않는다.
            text = "[STATIC] " + (
                result.get("hookSummary")
                or f"{result.get('analyzed') or 0}개 대상 분석 완료 · "
                   f"결함 {summary.get('active', 0)}건")
            if note:
                text += f" · {note}"
            if uncaptured:
                text += f" · {uncaptured}"
            return EXIT_OK, "", {
                "systemMessage": text,
                "hookSpecificOutput": {
                    "hookEventName": "Stop",
                    "additionalContext": _model_report(result, text),
                },
            }
        return EXIT_OK, "", {}
    except Exception:
        return EXIT_OK, "", {}                  # 백스톱 — 여기까지 온 예외는 무조건 통과시키지 않는다
