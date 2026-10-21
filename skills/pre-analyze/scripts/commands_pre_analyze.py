"""pre-analyze command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def cmd_analyze(args):
    from . import pipeline
    try:
        return pipeline.run_analyze(args.project_dir, parallel=args.parallel,
                                    force=args.force)
    except pipeline.NeedsBootstrap as e:
        return {
            "ok": False, "command": "pre-analyze", "code": "NEEDS_BOOTSTRAP",
            "projectDir": str(e.project_dir),
            "message": "이 프로젝트에 연결된 STATIC 워크스페이스가 없습니다.",
            # 부트스트랩은 한 줄 명령이 아니라 여러 단계다 (환경에 따라 사용자의 GUI
            # 조작을 기다리기도 한다). 명령을 하나 찍어 주면 그 절차를 건너뛰게 된다.
            "hint": "statica-analyze-bootstrap 스킬의 절차를 따르세요. 환경 식별부터 "
                    "bootstrap-begin · 치환 · 빌드 · bootstrap-verify · bootstrap-finish "
                    "까지 여러 단계이며 사용자 승인을 먼저 받아야 합니다. 원하지 않으면 "
                    "그냥 하지 않으면 됩니다. 훅은 연결되지 않은 프로젝트에서 아무 말도 "
                    "하지 않습니다.",
        }
