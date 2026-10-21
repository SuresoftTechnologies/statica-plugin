"""scope command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def _scope_workspace(project_dir, command):
    """분석 범위를 만질 워크스페이스와 그 언어.

    룰셋과 달리 서버 프로젝트 키는 필요 없다 - 범위는 워크스페이스 안 파일이라
    아직 서버에 등록되지 않은 프로젝트에서도 설정할 수 있어야 한다.
    """
    from . import languages, pipeline, workspace
    ws = workspace.find_workspace_for(project_dir)
    if ws is None:
        raise pipeline.NeedsBootstrap(project_dir)
    return ws, languages.get(languages.of_agent_json(workspace.read_agent_json(ws)))


def _scope_entries(current):
    """지금 빠진 것과 되살린 것. 에이전트가 그대로 사람에게 읽어 줄 모양이다."""
    from . import scope
    excluded = (
        [{"path": p, "kind": scope.DIRECTORY, "state": scope.EXCLUDED}
         for p in current["exclusion"]["directories"]]
        + [{"path": p, "kind": scope.FILE, "state": scope.EXCLUDED}
           for p in current["exclusion"]["files"]])
    included = (
        [{"path": p, "kind": scope.DIRECTORY, "state": scope.INCLUDED}
         for p in current["inclusion"]["directories"]]
        + [{"path": p, "kind": scope.FILE, "state": scope.INCLUDED}
           for p in current["inclusion"]["files"]])
    return excluded, included


def _scope_result(command, ws, language, current, **extra):
    from . import scope
    excluded, included = _scope_entries(current)
    result = {
        "ok": True, "command": command, "workspace": str(ws),
        "language": language.id,
        "scopeFile": str(scope.path_for(ws, language)),
        "excluded": excluded, "included": included,
        "skippedModules": list(current.get("analysisSkipModules", [])),
    }
    result["modules"] = _module_rows(ws, language, current)
    result.update(extra)
    return result


def _module_rows(ws, language, current):
    """모듈 목록. C/C++ 이 아니면 빈 목록이다 - 모듈이라는 것이 없다.

    사용자가 무엇을 뺄지 고르려면 먼저 보여야 한다. `output` 이 --path 에
    넣을 값이고, `linkCommand` 는 빌드 도구가 만든 모듈을 알아보는 단서다.
    """
    from . import changes, scope
    from .languages import CCPP
    if language.id != CCPP:
        return []
    rows = []
    for row in changes.module_summaries(ws):
        output = row.get("output")
        rows.append(dict(row,
                         output=scope.normalize(output) if output else None,
                         skipped=bool(output and
                                      scope.is_module_skipped(current, output))))
    return rows


def _resolve_scope_targets(project_dir, paths_given, ws=None, language=None):
    """사용자가 말한 경로를 (절대경로, 종류) 로 확정한다.

    없는 경로는 여기서 막는다. 이 파일의 비교는 **완전 일치**라서, 오타가 있어도
    분석기는 아무 불평 없이 그냥 전부 분석한다 - 사용자는 제외했다고 믿고 있고
    아무도 틀린 것을 모른다. 종류(파일/디렉터리)를 묻지 않고 디스크에서 읽는
    것도 같은 이유다.

    ``ws`` · ``language`` 를 주면 "제외할 수 있는 것인가"까지 본다. 존재 검사만으로는
    부족하다는 것을 헤더로 겪었다 - 디스크에 있지만 분석 단위가 아니어서, 제외해도
    분석량이 그대로였다. 되돌리는 쪽(scope-include)은 이 검사를 태우지 않는다.
    이미 들어가 있는 잘못된 항목을 지울 길이 막히기 때문이다.
    """
    from . import scope
    root = Path(project_dir).resolve()
    targets, missing, rejected = [], [], []
    for given in paths_given:
        candidate = Path(given)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.exists():
            missing.append(given)
            continue
        kind = scope.DIRECTORY if candidate.is_dir() else scope.FILE
        resolved = scope.normalize(candidate.resolve())
        if language is not None:
            reason = scope.unanalyzable_reason(resolved, kind, ws, language)
            if reason:
                rejected.append({"path": given, "reason": reason})
                continue
        targets.append((resolved, kind))
    return targets, missing, rejected


def _cmd_scope_edit(args, command, operation):
    from . import pipeline, scope
    try:
        ws, language = _scope_workspace(args.project_dir, command)
    except pipeline.NeedsBootstrap as e:
        return _needs_bootstrap(command, e.project_dir)

    # 되돌리기는 검사하지 않는다: 이미 들어가 있는 잘못된 항목도 지울 수 있어야 한다.
    checked = language if operation is scope.exclude else None
    targets, missing, rejected = _resolve_scope_targets(
        args.project_dir, args.paths, ws=ws, language=checked)
    if missing:
        # 하나라도 틀리면 전부 멈춘다. 일부만 적용하면 무엇이 들어갔는지
        # 사용자가 다시 조회하기 전까지 알 수 없다.
        return {"ok": False, "command": command, "code": "NO_SUCH_PATH",
                "missing": missing, "workspace": str(ws),
                "message": "다음 경로를 찾을 수 없어 아무것도 바꾸지 않았습니다: "
                           + ", ".join(missing)}
    if rejected:
        return {"ok": False, "command": command, "code": "NOT_ANALYZABLE",
                "rejected": rejected, "workspace": str(ws),
                "message": "제외할 수 없는 경로가 있어 아무것도 바꾸지 않았습니다. "
                           + " ".join(f"{r['path']}: {r['reason']}" for r in rejected)}
    if not targets:
        return {"ok": False, "command": command, "code": "NO_PATHS",
                "workspace": str(ws), "message": "--path 를 하나 이상 주어야 합니다."}

    current = scope.read(ws, language)
    for path, kind in targets:
        current = operation(current, path, kind)
    scope.write(ws, language, current)

    verb = "제외했습니다" if operation is scope.exclude else "다시 포함했습니다"
    return _scope_result(command, ws, language, current,
                         changed=[p for p, _ in targets],
                         message=f"{len(targets)}개 경로를 {verb}.")


def cmd_scope_show(args):
    from . import pipeline, scope
    try:
        ws, language = _scope_workspace(args.project_dir, "scope-show")
    except pipeline.NeedsBootstrap as e:
        return _needs_bootstrap("scope-show", e.project_dir)
    return _scope_result("scope-show", ws, language, scope.read(ws, language))


def cmd_scope_exclude(args):
    from . import scope
    return _cmd_scope_edit(args, "scope-exclude", scope.exclude)


def cmd_scope_include(args):
    from . import scope
    return _cmd_scope_edit(args, "scope-include", scope.include)


def _resolve_modules(ws, language, paths_given):
    """사용자가 말한 값을 모듈의 산출물 경로로 확정한다.

    산출물 경로와 모듈 디렉터리 이름을 **둘 다** 받는다. 범위 파일에 들어가는
    것은 언제나 산출물 경로다 - 디렉터리 이름을 그대로 적으면 UI 가 적어 둔
    값과 안 맞아 아무 일도 일어나지 않는다(실측으로 겪었다). 그래서 여기서
    번역해 준다.

    모르는 값은 막는다. `scope-exclude` 가 없는 경로를 막는 것과 같은 이유로,
    통과시키면 아무것도 빠지지 않은 채 "제외했습니다" 가 된다.
    """
    from . import changes, scope
    from .languages import CCPP
    if language.id != CCPP:
        return [], [], []
    known = {}
    for row in changes.module_summaries(ws):
        output = row.get("output")
        if not output:
            continue
        written = scope.normalize(output)
        known[scope.key(output)] = written
        known[scope.key(row["name"])] = written
    targets, missing = [], []
    for given in paths_given:
        found = known.get(scope.key(given))
        if found is None:
            missing.append(given)
        elif found not in targets:
            targets.append(found)
    return targets, missing, sorted(set(known.values()))


def _cmd_scope_module(args, command, operation):
    from . import pipeline, scope
    from .languages import CCPP
    try:
        ws, language = _scope_workspace(args.project_dir, command)
    except pipeline.NeedsBootstrap as e:
        return _needs_bootstrap(command, e.project_dir)
    if language.id != CCPP:
        return {"ok": False, "command": command, "code": "NO_MODULES",
                "workspace": str(ws), "language": language.id,
                "message": "빌드 모듈은 C/C++ 에만 있습니다. "
                           "다른 언어는 scope-exclude 로 파일을 빼세요."}
    if not args.paths:
        return {"ok": False, "command": command, "code": "NO_PATHS",
                "workspace": str(ws),
                "message": "--path 를 하나 이상 주어야 합니다."}
    targets, missing, known = _resolve_modules(ws, language, args.paths)
    if missing:
        # 하나라도 틀리면 전부 멈춘다 (_cmd_scope_edit 와 같은 규율).
        return {"ok": False, "command": command, "code": "NO_SUCH_MODULE",
                "missing": missing, "knownModules": known, "workspace": str(ws),
                "message": "다음 모듈을 찾을 수 없어 아무것도 바꾸지 "
                           "않았습니다: " + ", ".join(missing)
                           + ". scope-show 의 modules 를 보세요."}

    current = scope.read(ws, language)
    for output in targets:
        current = operation(current, output)
    scope.write(ws, language, current)

    verb = "제외했습니다" if operation is scope.skip_module else "다시 포함했습니다"
    return _scope_result(command, ws, language, current, changed=targets,
                         message=f"모듈 {len(targets)}개를 {verb}.")


def cmd_scope_skip_module(args):
    from . import scope
    return _cmd_scope_module(args, "scope-skip-module", scope.skip_module)


def cmd_scope_unskip_module(args):
    from . import scope
    return _cmd_scope_module(args, "scope-unskip-module", scope.unskip_module)
