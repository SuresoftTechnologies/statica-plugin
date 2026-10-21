import argparse
import json
import sys
from pathlib import Path

from .errors import PluginError

# Re-export handlers for the existing CLI API; implementations belong to skills.
from .commands_pre_analyze import cmd_analyze
from .commands_statica_analyze_bootstrap import (
    cmd_bootstrap_begin, cmd_bootstrap_guard, cmd_bootstrap_verify,
    cmd_bootstrap_finish, cmd_bootstrap_abort, cmd_detect)
from .commands_upload import cmd_upload
from .commands_status import (_status_section, cmd_status, _status_message)
from .commands_metric import (cmd_metric_show, cmd_metric_set)
from .commands_report_generator import (
    cmd_report_generator_show, cmd_report_generator_set)
from .commands_report import cmd_report
from .commands_scope import (
    _scope_workspace, _scope_entries, _scope_result, _module_rows,
    _resolve_scope_targets, _cmd_scope_edit, cmd_scope_show, cmd_scope_exclude,
    cmd_scope_include, _resolve_modules, _cmd_scope_module,
    cmd_scope_skip_module, cmd_scope_unskip_module)
from .commands_ruleset import (cmd_ruleset_show, cmd_ruleset_set, _apply_ruleset)
from .cli_support import (_project_key_for, _needs_bootstrap, _with_project_key)


def _emit(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def cmd_doctor(_args):
    import platform

    from . import paths, settings, state
    result = {"ok": True, "command": "doctor", "checks": {}}
    # Arachne 는 OS 별 패키지가 따로다. 실행 파일을 못 찾을 때 가장 먼저 볼 것이
    # "어느 쪽으로 찾고 있었나" 이므로 드러내 둔다.
    result["checks"]["platform"] = platform.system()
    result["checks"]["exeSuffix"] = paths.EXE_SUFFIX or "(없음)"
    # 커맨드와 훅이 서로 다른 파일을 보면 스위치가 통째로 무반응이 된다. 조용히
    # 어긋나는 종류라 여기서 실제로 보고 있는 경로를 드러낸다.
    result["checks"]["stateFile"] = str(state.state_file())
    try:
        root = paths.install_root()
        result["checks"]["installRoot"] = str(root)
    except PluginError as e:
        result["ok"] = False
        result["checks"]["installRoot"] = e.to_dict()
        return result
    for exe in ("analyzer-csa", "analyzer-plugin", "wrapper-forge"):
        result["checks"][exe] = paths.bin_path(exe).is_file()
    result["checks"]["worksRoot"] = str(paths.works_root())
    try:
        s = settings.read_server_setting()
        result["checks"]["server"] = s.server
        result["checks"]["accessKeySet"] = True
    except PluginError as e:
        result["ok"] = False
        result["checks"]["server"] = e.to_dict()
        result["checks"]["accessKeySet"] = False
    missing = [k for k, v in result["checks"].items() if v is False]
    if missing:
        result["ok"] = False
    result["message"] = "환경 점검 통과" if result["ok"] and not missing \
        else "환경 점검에서 문제가 발견되었습니다."
    return result


def cmd_switch(args):
    from . import state
    on = args.enabled == "on"
    scope = None if args.glob else args.project_dir
    state.set_analysis_enabled(scope, on)
    where = "모든 프로젝트에서" if scope is None else "이 프로젝트에서"
    result = {"ok": True, "command": "switch",
              "scope": "global" if scope is None else "project",
              "projectDir": None if scope is None else str(scope),
              "enabled": on,
              "message": (f"{where} 자동 분석을 켰습니다." if on
                          else f"{where} 자동 분석을 껐습니다. "
                               "커맨드로는 계속 실행됩니다.")}
    return result


def build_parser():
    parser = argparse.ArgumentParser(prog="statica")
    sub = parser.add_subparsers(dest="command", required=True)
    parser.add_argument(
        "--state-dir", default=None,
        help="진단·테스트용 상태 디렉터리 재정의. 기본값은 "
             "~/.suresoft/data/plugins/static. 정상 스킬·훅은 지정하지 않는다.")
    sub.add_parser("doctor", help="설치 경로와 서버 설정을 점검한다")

    analyze = sub.add_parser("pre-analyze", help="변경된 대상만 분석한다")
    analyze.add_argument("--project-dir", required=True)
    analyze.add_argument("--parallel", type=int, default=None)
    analyze.add_argument("--force", action="store_true")

    # 부트스트랩은 한 번에 끝나지 않는다 — 치환이 GUI 조작인 환경이 있어서 중간에
    # 사람을 기다린다. 그래서 단계마다 별도의 서브커맨드다 (에이전트가 순서를 몬다).
    bb = sub.add_parser("bootstrap-begin", help="워크스페이스와 wrapper 를 만든다")
    bb.add_argument("--project-dir", required=True)
    bb.add_argument("--name", required=True)
    # 아래 셋은 C/C++ 에서만 필수다. argparse 로 강제하지 않고 cmd_bootstrap_begin
    # 이 언어를 보고 판정한다 — required=True 로 두면 타 언어에서 쓰지도 않을 값을
    # 지어내서 넘겨야 한다.
    bb.add_argument("--ide", default=None)
    bb.add_argument("--compiler", default=None)
    bb.add_argument("--compiler-path", default=None)
    bb.add_argument("--language", default="ccpp",
                    help="ccpp(기본) · java · kotlin · python · csharp")
    bb.add_argument("--input", default=None,
                    help="csharp 전용: 분석할 .sln 또는 .csproj 경로")
    bb.add_argument("--csharp-configuration", default=None,
                    help="csharp 전용: 빌드 구성 (예: Debug, Release)")
    bb.add_argument("--csharp-target", default=None,
                    help="csharp 전용: framework 또는 sdk")
    bb.add_argument("--build-command", default=None)

    bg = sub.add_parser("bootstrap-guard", help="프로젝트 파일 원본을 보관한다")
    bg.add_argument("--project-dir", required=True)
    bg.add_argument("--file", action="append", required=True, dest="files")

    bv = sub.add_parser("bootstrap-verify", help="캡처가 생겼는지 확인한다")
    bv.add_argument("--project-dir", required=True)

    bf = sub.add_parser("bootstrap-finish", help="서버 프로젝트 생성 후 마무리한다")
    bf.add_argument("--project-dir", required=True)

    ba = sub.add_parser("bootstrap-abort", help="원복하고 워크스페이스를 지운다")
    ba.add_argument("--project-dir", required=True)
    ba.add_argument("--reason", default="")

    det = sub.add_parser("detect", help="부트스트랩 판단용 증거를 모은다")
    det.add_argument("--project-dir", required=True)

    upload_p = sub.add_parser("upload", help="전체 분석 후 서버에 업로드한다")
    upload_p.add_argument("--project-dir", required=True)
    upload_p.add_argument("--parallel", type=int, default=None)

    rs = sub.add_parser("ruleset-show", help="프로젝트의 룰셋 선택 상태를 조회한다")
    rs.add_argument("--project-dir", required=True)

    ru = sub.add_parser("ruleset-set", help="프로젝트의 룰셋을 통째로 교체한다")
    ru.add_argument("--project-dir", required=True)
    ru.add_argument("--ruleset-id", type=int, action="append", default=[],
                    dest="ruleset_ids",
                    help="켤 룰셋 id. 반복 가능. **여기 없는 룰셋은 전부 꺼진다**: "
                         "먼저 ruleset-show 로 현재 선택을 읽어라.")
    ru.add_argument("--locale-language", default=None,
                    help="룰 표시 언어 (ko_KR, en_US ...). 생략하면 현재 값을 유지한다.")

    st = sub.add_parser("status", help="이 프로젝트의 STATIC 상태를 한 번에 본다")
    st.add_argument("--project-dir", required=True)
    st.add_argument("--local", action="store_true",
                    help="서버를 부르지 않고 로컬 상태만 본다.")

    ms = sub.add_parser("metric-show", help="프로젝트 metric 사용 설정을 조회한다")
    ms.add_argument("--project-dir", required=True)

    mu = sub.add_parser("metric-set", help="metric 사용 여부를 한 번에 바꾼다")
    mu.add_argument("--project-dir", required=True)
    mu.add_argument("--on", action="append", default=[],
                    help="켤 metric key (FUCYC ...). 반복 가능.")
    mu.add_argument("--off", action="append", default=[],
                    help="끌 metric key. 반복 가능.")

    rgs = sub.add_parser("report-generator-show",
                         help="분석 후 보고서 자동 생성 설정을 조회한다")
    rgs.add_argument("--project-dir", required=True)

    rgu = sub.add_parser("report-generator-set",
                         help="분석 후 보고서 자동 생성 설정을 바꾼다")
    rgu.add_argument("--project-dir", required=True)
    rgu.add_argument("enabled", choices=["on", "off"])
    rgu.add_argument("--format", default="", help="DOC | PDF | HTML | EXCEL")
    rgu.add_argument("--kind", type=int, action="append", default=[], dest="kinds",
                     help="보고서 종류 1~12. 반복 가능. on 이면 하나 이상 필요하다.")

    rp = sub.add_parser("report", help="보고서를 새로 만들어 내려받는다")
    rp.add_argument("--project-dir", required=True)
    rp.add_argument("--format", required=True, help="DOC | PDF | HTML | EXCEL")
    rp.add_argument("--kind", type=int, action="append", default=[], dest="kinds",
                    required=True, help="보고서 종류 1~12. 반복 가능.")
    rp.add_argument("--out", default=None,
                    help="저장 경로. 생략하면 <project>/.static/reports/ 아래.")
    rp.add_argument("--timeout", type=int, default=None,
                    help="완성을 기다릴 최대 초. 생략하면 600.")

    ss = sub.add_parser("scope-show", help="분석에서 빠진 파일 · 디렉터리를 조회한다")
    ss.add_argument("--project-dir", required=True)

    for name, verb in (("scope-exclude", "분석에서 뺀다"),
                       ("scope-include", "분석 대상으로 되돌린다")):
        sp = sub.add_parser(name, help=f"파일 · 디렉터리를 {verb}")
        sp.add_argument("--project-dir", required=True)
        sp.add_argument("--path", action="append", default=[], dest="paths",
                        help="프로젝트 기준 상대경로 또는 절대경로. 반복 가능. "
                             "glob 은 받지 않는다: 실제 경로를 그대로 주어야 한다.")

    for name, verb in (("scope-skip-module", "분석에서 통째로 뺀다"),
                       ("scope-unskip-module", "다시 분석 대상으로 돌린다")):
        sp = sub.add_parser(name, help=f"C/C++ 빌드 모듈을 {verb}")
        sp.add_argument("--project-dir", required=True)
        sp.add_argument("--path", action="append", default=[], dest="paths",
                        help="모듈의 빌드 산출물 경로(scope-show 의 modules[].output) "
                             "또는 모듈 디렉터리 이름. 반복 가능.")

    sw = sub.add_parser("switch", help="자동 분석을 프로젝트 단위로 켜고 끈다")
    sw.add_argument("enabled", choices=["on", "off"])
    sw.add_argument("--project-dir", default=None)
    sw.add_argument("--global", dest="glob", action="store_true",
                    help="이 프로젝트가 아니라 전부에 적용한다")

    sub.add_parser("hook-stop", help="Stop 훅 진입점 (stdin 으로 payload JSON)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    from . import state as _state
    _state.set_state_dir(getattr(args, "state_dir", None))

    if args.command == "hook-stop":
        import os
        from . import hook
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception:
            # JSON 이 깨진 경우뿐 아니라 stdin 읽기 자체가 실패하는 경우까지 삼킨다.
            # 훅은 어떤 이유로도 사용자의 턴을 깨뜨리면 안 된다.
            payload = {}
        code, message, stdout_payload = hook.run_stop(payload, os.getcwd())
        if message:
            # 지금은 항상 빈 문자열이다 (훅은 종료 코드 0 만 낸다). 통로는 남겨 둔다.
            sys.stderr.write(message)
        if stdout_payload:
            # 종료 코드 0 에서 stdout JSON 이 유일한 통로다 —
            # systemMessage 는 사용자에게, hookSpecificOutput.additionalContext 는
            # 모델에게 간다 (stderr 는 디버그 로그로만 간다). 무엇을 담을지는
            # hook.run_stop 이 정하고, 여기서는 그대로 실어 보내기만 한다.
            _emit(stdout_payload)
        return code

    handlers = {"doctor": cmd_doctor, "pre-analyze": cmd_analyze,
                "detect": cmd_detect, "upload": cmd_upload,
                "bootstrap-begin": cmd_bootstrap_begin,
                "bootstrap-guard": cmd_bootstrap_guard,
                "bootstrap-verify": cmd_bootstrap_verify,
                "bootstrap-finish": cmd_bootstrap_finish,
                "bootstrap-abort": cmd_bootstrap_abort,
                "ruleset-show": cmd_ruleset_show,
                "ruleset-set": cmd_ruleset_set,
                "status": cmd_status,
                "metric-show": cmd_metric_show,
                "metric-set": cmd_metric_set,
                "report-generator-show": cmd_report_generator_show,
                "report-generator-set": cmd_report_generator_set,
                "report": cmd_report,
                "scope-show": cmd_scope_show,
                "scope-exclude": cmd_scope_exclude,
                "scope-include": cmd_scope_include,
                "scope-skip-module": cmd_scope_skip_module,
                "scope-unskip-module": cmd_scope_unskip_module,
                "switch": cmd_switch}
    try:
        payload = handlers[args.command](args)
    except PluginError as e:
        payload = dict(e.to_dict(), command=args.command)
    except Exception as e:
        # "stdout 에 JSON 객체 하나만" 계약을 예외에서도 지킨다. 트레이스백을 뱉고
        # 1 로 죽으면 커맨드 쪽에서 파싱할 것이 없어진다.
        #
        # 원본 예외 텍스트는 담지 않는다 — accessKey 같은 민감정보를 물고 있을 수
        # 있다는 것을 배제할 수 없으므로, 예외 타입과 실패한 커맨드 이름만 남긴다
        # (bootstrap.py 가 쓰는 것과 같은 규율이다).
        payload = {
            "ok": False, "code": "INTERNAL_ERROR", "command": args.command,
            "message": f"'{args.command}' 실행 중 예상치 못한 오류가 발생했습니다 "
                       f"({type(e).__name__}).",
            "hint": "다시 시도하거나 관리자에게 문의하세요.",
        }
    _emit(payload)
    return 0
