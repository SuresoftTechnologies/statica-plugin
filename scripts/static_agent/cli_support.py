"""Shared CLI project lookup."""
from pathlib import Path

from .errors import PluginError


def _project_key_for(project_dir):
    """이 프로젝트에 연결된 서버 프로젝트 키. 없으면 PluginError.

    룰셋 커맨드는 워크스페이스가 있어야만 의미가 있다 — 서버 프로젝트 키를
    알아야 어느 프로젝트의 룰셋을 만질지 정해지기 때문이다.
    """
    from . import pipeline, workspace
    ws = workspace.find_workspace_for(project_dir)
    if ws is None:
        raise pipeline.NeedsBootstrap(project_dir)
    key = workspace.project_key(ws)
    if not key:
        raise PluginError(
            "NO_PROJECT_KEY",
            f"{workspace.APP_DATA_REL} 에 projectKey 가 없습니다: {ws}",
            "부트스트랩이 아직 끝나지 않았습니다. bootstrap-finish 를 실행하세요.")
    return ws, key


def _needs_bootstrap(command, project_dir):
    """부트스트랩이 안 된 프로젝트의 공통 응답.

    `pre-analyze` 만 이것을 쓰지 않는다 - 거기서는 절차 전체를 안내하는 긴 hint 가
    붙고, 그 안내가 이 커맨드들에는 맞지 않는다.
    """
    return {"ok": False, "command": command, "code": "NEEDS_BOOTSTRAP",
            "projectDir": str(project_dir),
            "message": "이 프로젝트에 연결된 STATIC 워크스페이스가 없습니다."}


def _with_project_key(args, command, run):
    """서버 프로젝트 키를 확정하고 ``run(key)`` 를 부른다.

    보고서 커맨드들은 전부 "이 프로젝트의 서버 쪽 무언가"를 다루므로 앞단이 같다.
    """
    from . import pipeline
    try:
        ws, key = _project_key_for(args.project_dir)
    except pipeline.NeedsBootstrap as e:
        return _needs_bootstrap(command, e.project_dir)
    result = run(key)
    result["command"] = command
    result["workspace"] = str(ws)
    return result
