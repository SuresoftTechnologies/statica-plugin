"""statica-analyze-bootstrap command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def cmd_bootstrap_begin(args):
    from . import bootstrap, languages
    language = languages.normalize(args.language)
    if not languages.is_plugin(language):
        # C/C++ 만 wrapper 를 만든다. 이 셋이 없으면 만들 수 없고, 없는 채로
        # 진행하면 치환할 대상이 없는 워크스페이스가 남는다.
        missing = [flag for flag, value in (("--ide", args.ide),
                                            ("--compiler", args.compiler),
                                            ("--compiler-path", args.compiler_path))
                   if not value]
        if missing:
            return {"ok": False, "command": "bootstrap-begin",
                    "code": "MISSING_ARGUMENT",
                    "message": f"C/C++ 부트스트랩에는 {', '.join(missing)} 가 "
                               "필요합니다.",
                    "hint": "타 언어라면 --language java|kotlin|python|csharp 를 "
                            "주세요."}
    return bootstrap.begin(args.project_dir, args.name, args.ide, args.compiler,
                           args.compiler_path, args.build_command,
                           language=language, input_path=args.input,
                           csharp_configuration=args.csharp_configuration,
                           csharp_target=args.csharp_target)


def cmd_bootstrap_guard(args):
    from . import bootstrap
    return bootstrap.guard(args.project_dir, args.files)


def cmd_bootstrap_verify(args):
    from . import bootstrap
    return bootstrap.verify(args.project_dir)


def cmd_bootstrap_finish(args):
    from . import bootstrap
    return bootstrap.finish(args.project_dir)


def cmd_bootstrap_abort(args):
    from . import bootstrap
    return bootstrap.abort(args.project_dir, args.reason)


def cmd_detect(args):
    from . import toolchain
    result = toolchain.gather(args.project_dir)
    result["ok"] = True
    result["command"] = "detect"
    result["message"] = (
        f"C/C++ 단서 {len(result['artifacts'])}종, 타 언어 단서 "
        f"{len(result.get('languageArtifacts') or [])}종을 찾았습니다. "
        "언어와 환경을 고르고 컴파일러를 확정하는 것은 에이전트의 판단입니다.")
    return result
