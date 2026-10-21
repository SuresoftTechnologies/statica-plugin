"""status command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def _status_section(call):
    """서버 조회 하나를 상태 조각으로 옮긴다.

    실패해도 예외로 만들지 않는다. 서버가 잠깐 내려갔다고 로컬 상태까지 못 보면
    정작 진단이 필요한 순간에 아무것도 알 수 없다.
    """
    result = call()
    if not result.get("ok"):
        return {"error": result.get("code") or "FAILED",
                "message": result.get("message")}
    return result


def cmd_status(args):
    """이 프로젝트가 지금 어떤 상태인가. 새로 하는 일은 없고 모아서 보여준다.

    다른 커맨드와 달리 **연결되지 않은 프로젝트에서도 답한다.** "연결 안 됐다" 는
    것이야말로 이 커맨드가 알려줘야 할 상태이기 때문이다.
    """
    from . import languages, scope, server_api, settings, state, workspace

    project_dir = str(Path(args.project_dir).resolve())
    ws = workspace.find_workspace_for(args.project_dir)
    result = {"ok": True, "command": "status",
              "project": {"dir": project_dir, "linked": ws is not None}}

    if ws is None:
        result["project"]["message"] = (
            "이 프로젝트는 STATIC 워크스페이스에 연결되지 않았습니다. "
            "분석하려면 부트스트랩이 먼저 필요합니다.")
        result["message"] = "STATIC 에 연결되지 않은 프로젝트입니다."
        return result

    agent_json = workspace.read_agent_json(ws)
    language = languages.get(languages.of_agent_json(agent_json))
    key = workspace.project_key(ws)
    result["project"].update(
        workspace=str(ws), language=language.id, projectKey=key)

    result["analysis"] = {
        "bootstrapStatus": workspace.status(agent_json),
        # 마지막 분석 시각은 여기 없다. 로컬에는 믿을 만한 값이 없어서
        # (`get_project_status` 의 docstring 참조) 서버 조각에서 채운다.
        #
        # 훅은 프로젝트별로도, 전역으로도 꺼진다. 둘을 합친 값만 보여주면
        # "왜 꺼져 있지" 를 답할 수 없다.
        "hookEnabled": state.is_analysis_enabled(project_dir),
        "hookEnabledGlobally": state.is_analysis_enabled(None),
    }

    current = scope.read(ws, language)
    result["scope"] = {
        "file": str(scope.path_for(ws, language)),
        "excluded": (len(current["exclusion"]["directories"])
                     + len(current["exclusion"]["files"])),
        "included": (len(current["inclusion"]["directories"])
                     + len(current["inclusion"]["files"])),
        "skippedModules": len(current.get("analysisSkipModules", [])),
    }

    try:
        result["server"] = {"url": settings.read_server_setting().server}
    except PluginError as e:
        result["server"] = {"error": e.code, "message": e.message}
        return _status_message(result)

    if args.local or not key:
        if not key:
            result["server"]["message"] = (
                "서버 프로젝트 키가 아직 없어 서버 설정을 조회하지 않았습니다.")
        return _status_message(result)

    analysis = _status_section(lambda: server_api.get_project_status(key))
    if "error" not in analysis:
        analysis = {"progressStage": analysis.get("progressStage"),
                    "lastAnalyzedAt": analysis.get("lastAnalyzedAt"),
                    "lastRevisionSequence": analysis.get("lastRevisionSequence")}
    ruleset = _status_section(lambda: server_api.get_project_ruleset(key))
    if "error" not in ruleset:
        ruleset = {"enabled": ruleset.get("enabledCount"),
                   "total": len(ruleset.get("rulesets") or []),
                   # 전체 목록을 못 읽으면 total 이 "켜져 있는 수"와 같아진다.
                   # 그 사실을 함께 넘겨야 읽는 쪽이 오해하지 않는다.
                   "catalogComplete": ruleset.get("catalogComplete"),
                   "localeLanguage": ruleset.get("localeLanguage")}
    metric = _status_section(lambda: server_api.get_metrics(key))
    if "error" not in metric:
        metric = {"enabled": metric.get("enabledCount"),
                  "total": len(metric.get("metrics") or [])}
    generator = _status_section(lambda: server_api.get_report_generator(key))
    if "error" not in generator:
        generator = {"enabled": generator.get("enabled"),
                     "format": generator.get("format"),
                     "kinds": len(generator.get("kinds") or [])}

    result["server"].update(analysis=analysis, ruleset=ruleset, metric=metric,
                            reportGenerator=generator)
    return _status_message(result)


def _status_message(result):
    """사람이 먼저 읽을 한 줄. 나머지는 에이전트가 표로 옮긴다."""
    project = result["project"]
    analysis = result.get("analysis") or {}
    hook = "자동 분석 켜짐" if analysis.get("hookEnabled") else "자동 분석 꺼짐"
    result["message"] = (f"{project.get('projectKey') or '(키 없음)'} · "
                         f"{project.get('language')} · {hook}")
    return result
