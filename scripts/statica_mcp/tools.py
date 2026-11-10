"""MCP 도구 ↔ `run.py` 서브커맨드 대응표.

여기 있는 것이 MCP 로 보이는 전부다. 각 항목은 세 가지를 정한다:

1. 모델에게 보일 이름 · 설명 · 입력 스키마 · 동의 힌트
2. 인자를 CLI argv 로 옮기는 법 (``flag`` · ``kind``)
3. 하위 프로세스에 줄 시간 상한

부트스트랩 · 업로드도 도구로 연다 (DVERA 와 같은 방식). 스킬 없이 MCP 만 쓰는
클라이언트도 프로젝트를 연결하고 결과를 올릴 수 있어야 하기 때문이다. 대신:

- 되돌리기 어렵거나 밖으로 나가는 단계는 ``destructiveHint`` / ``openWorldHint``
  로 표시해 클라이언트가 매번 승인을 받게 하고, 설명에 승인 조건을 적는다.
- 절차(언제 무엇을 묻고 어디서 멈출지)는 CLI 가 아니라 스킬 문서에 있다. 그것을
  ``statica_get_guide`` 도구와 MCP prompts 로 그대로 내보낸다 (``guides.py``).
  DVERA 는 절차를 MCP 로 전하지 않아 MCP 클라이언트가 규칙을 모른다 - 그 틈을
  메우는 부분이다.
- 단계 순서를 어긴 호출은 CLI 가 이미 막는다 (기존 워크스페이스, ``ready`` 에서의
  abort 거절, 컴파일러 실행 검증 등). 서버에서 다시 막지 않는다.

tests/test_mcp.py 가 "CLI 의 모든 서브커맨드는 여기 있거나 EXCLUDED_COMMANDS 에
있다"를 검사하므로, CLI 에 명령이 늘면 어느 쪽인지 정해야 테스트가 통과한다.
"""

# 서브커맨드 → 도구로 열지 않는 이유.
EXCLUDED_COMMANDS = {
    "hook-stop": "Stop hook entry point, not a tool",
}

# 하위 프로세스 시간 상한(초). 넘기면 프로세스 트리를 끊는다.
DEFAULT_TIMEOUT = 300
# CLI 는 분석기 하위 프로세스 하나에 1800초까지 준다 (budget.UNBOUNDED_CHILD_
# TIMEOUT_SECONDS). finish · upload 는 분석과 업로드를 잇달아 돌리므로 그 위에
# 여유를 둔다.
ANALYZE_TIMEOUT = 3600

LANGUAGES = ["ccpp", "java", "kotlin", "python", "csharp"]
GUIDE_TOPICS = ["bootstrap", "bootstrap-environments",
                "bootstrap-other-languages", "upload", "overview"]
# report 는 서버 생성을 기다린다. 그 대기 상한(--timeout, 기본 600)에 내려받기
# 여유를 더한다.
REPORT_WAIT_DEFAULT = 600
REPORT_MARGIN = 120

REPORT_FORMATS = ["DOC", "PDF", "HTML", "EXCEL"]

PROJECT_DIR = {
    "type": "string",
    "description": "Absolute path of the project directory being analyzed "
                   "(usually the session's working directory).",
    "flag": "--project-dir",
    "kind": "value",
}


def _ann(read_only=False, destructive=False, idempotent=False, open_world=False):
    """MCP tool annotations. 읽기 전용이면 나머지 힌트는 의미가 없어 뺀다."""
    if read_only:
        return {"readOnlyHint": True, "openWorldHint": open_world}
    return {"readOnlyHint": False, "destructiveHint": destructive,
            "idempotentHint": idempotent, "openWorldHint": open_world}


def _paths_param(what):
    return {
        "type": "array", "items": {"type": "string"}, "minItems": 1,
        "description": what, "flag": "--path", "kind": "repeat",
    }


TOOLS = [
    {
        "name": "statica_doctor",
        "command": "doctor",
        "title": "Check STATIC environment",
        "description": (
            "Check that the local STATIC installation, analyzers, server URL and "
            "AccessKey are usable, and report which Python this MCP server runs "
            "on. Needs no project. Run this first when other STATICA tools fail "
            "with setup errors."),
        "params": {},
        "annotations": _ann(read_only=True),
    },
    {
        "name": "statica_status",
        "command": "status",
        "title": "Show project STATIC status",
        "description": (
            "Show how this project relates to STATIC in one call: link state, "
            "bootstrap status, automatic-analysis switch (per project and "
            "global), scope exclusions, and the server's ruleset, metric, "
            "report-generator and last-analysis state. Changes nothing. "
            "project.linked=false is a valid answer (not connected), not a "
            "failure. Server sections carry their own 'error'; one failing does "
            "not invalidate the rest."),
        "params": {
            "projectDir": PROJECT_DIR,
            "local": {"type": "boolean", "flag": "--local", "kind": "flag",
                      "description": "Skip the server queries and report local "
                                     "state only (faster)."},
        },
        "annotations": _ann(read_only=True, open_world=True),
    },
    {
        "name": "statica_pre_analyze",
        "command": "pre-analyze",
        "title": "Analyze changed files",
        "description": (
            "Run STATIC on the files that changed since the last analysis and "
            "summarize defects by rule. Never uploads. For C/C++ only changed "
            "translation units run; Java, Kotlin, Python and C# are analyzed in "
            "full and the summary is narrowed to changed files. Counts cover "
            "this run's scope, not the project total - say so when reporting, "
            "and do not list defects file by file. reason=NO_CHANGES usually "
            "means the Stop hook already analyzed the edit; do not suggest a "
            "rebuild or upload for it. code=NEEDS_BOOTSTRAP means the project is "
            "not connected: offer to connect it (statica_get_guide "
            "topic=bootstrap) and start only after the user agrees. "
            "reason=BOOTSTRAP_IN_PROGRESS means a connection was started "
            "earlier: resume it per the guide, never start over."),
        "params": {
            "projectDir": PROJECT_DIR,
            "parallel": {"type": "integer", "minimum": 1, "flag": "--parallel",
                         "kind": "value",
                         "description": "Analyzer parallelism. Omit for the "
                                        "default."},
            "force": {"type": "boolean", "flag": "--force", "kind": "flag",
                      "description": "Re-analyze even when nothing changed."},
        },
        "annotations": _ann(idempotent=True),
        "timeout": ANALYZE_TIMEOUT,
    },
    {
        "name": "statica_set_auto_analysis",
        "command": "switch",
        "title": "Turn automatic analysis on or off",
        "description": (
            "Turn the Stop-hook analysis after each response on or off, for "
            "this project or globally. Commands such as statica_pre_analyze "
            "keep working either way. Local setting only."),
        "params": {
            "enabled": {"type": "boolean", "kind": "onoff",
                        "description": "true to turn automatic analysis on, "
                                       "false to turn it off."},
            "projectDir": dict(PROJECT_DIR, description=(
                "Absolute path of the project. Required unless global is "
                "true.")),
            "global": {"type": "boolean", "flag": "--global", "kind": "flag",
                       "description": "Apply to every project instead of this "
                                      "one."},
        },
        "required": ["enabled"],
        "annotations": _ann(idempotent=True),
    },
    {
        "name": "statica_scope_show",
        "command": "scope-show",
        "title": "Show analysis scope",
        "description": (
            "List the files and directories excluded from analysis, the "
            "exceptions re-included inside excluded directories, and (C/C++ "
            "only) the build modules with their skip state. Changes nothing. "
            "Read this before changing the scope."),
        "params": {"projectDir": PROJECT_DIR},
        "annotations": _ann(read_only=True),
    },
    {
        "name": "statica_scope_exclude",
        "command": "scope-exclude",
        "title": "Exclude paths from analysis",
        "description": (
            "Exclude files or directories from analysis. Adds to the current "
            "list. Real paths only (no globs); if any path is missing nothing "
            "is written (NO_SUCH_PATH). Headers cannot be excluded "
            "(NOT_ANALYZABLE). Defects already on the server stay until the "
            "next full analysis; when reporting later counts, say they changed "
            "because the scope changed, not the code. Confirm the exact paths "
            "with the user first."),
        "params": {
            "projectDir": PROJECT_DIR,
            "paths": _paths_param("Paths relative to the project or absolute. "
                                  "File or directory is detected from disk."),
        },
        "required": ["projectDir", "paths"],
        "annotations": _ann(idempotent=True),
    },
    {
        "name": "statica_scope_include",
        "command": "scope-include",
        "title": "Re-include paths in analysis",
        "description": (
            "Return files or directories to analysis, or re-include an "
            "exception inside an excluded directory. Real paths only; if any "
            "path is missing nothing is written."),
        "params": {
            "projectDir": PROJECT_DIR,
            "paths": _paths_param("Paths relative to the project or absolute."),
        },
        "required": ["projectDir", "paths"],
        "annotations": _ann(idempotent=True),
    },
    {
        "name": "statica_scope_skip_module",
        "command": "scope-skip-module",
        "title": "Skip C/C++ build modules",
        "description": (
            "C/C++ only: skip whole build modules. Pass modules[].output from "
            "statica_scope_show. Unknown values are rejected (NO_SUCH_MODULE) "
            "with knownModules listed. Which modules are noise is the user's "
            "call; show the list and confirm first."),
        "params": {
            "projectDir": PROJECT_DIR,
            "paths": _paths_param("Module build-output paths "
                                  "(modules[].output)."),
        },
        "required": ["projectDir", "paths"],
        "annotations": _ann(idempotent=True),
    },
    {
        "name": "statica_scope_unskip_module",
        "command": "scope-unskip-module",
        "title": "Un-skip C/C++ build modules",
        "description": "C/C++ only: return skipped build modules to analysis.",
        "params": {
            "projectDir": PROJECT_DIR,
            "paths": _paths_param("Module build-output paths "
                                  "(modules[].output)."),
        },
        "required": ["projectDir", "paths"],
        "annotations": _ann(idempotent=True),
    },
    {
        "name": "statica_ruleset_show",
        "command": "ruleset-show",
        "title": "Show project rulesets",
        "description": (
            "Show which rulesets the server project enables and the rule "
            "display language. Changes nothing."),
        "params": {"projectDir": PROJECT_DIR},
        "annotations": _ann(read_only=True, open_world=True),
    },
    {
        "name": "statica_ruleset_set",
        "command": "ruleset-set",
        "title": "Replace project rulesets",
        "description": (
            "Replace the server project's ruleset selection. FULL REPLACEMENT: "
            "every ruleset not listed is turned off, so call "
            "statica_ruleset_show first and build on its current selection. At "
            "least one id is required. Applies to everyone using the server "
            "project; confirm the final list with the user before calling."),
        "params": {
            "projectDir": PROJECT_DIR,
            "rulesetIds": {"type": "array", "items": {"type": "integer"},
                           "minItems": 1, "flag": "--ruleset-id",
                           "kind": "repeat",
                           "description": "Ids of every ruleset that should be "
                                          "on after the call."},
            "localeLanguage": {"type": "string", "flag": "--locale-language",
                               "kind": "value",
                               "description": "Rule display language such as "
                                              "ko_KR or en_US. Omit to keep the "
                                              "current one."},
        },
        "required": ["projectDir", "rulesetIds"],
        "annotations": _ann(destructive=True, idempotent=True, open_world=True),
    },
    {
        "name": "statica_metric_show",
        "command": "metric-show",
        "title": "Show code metrics",
        "description": "Show which code metrics the server project enables. "
                       "Changes nothing.",
        "params": {"projectDir": PROJECT_DIR},
        "annotations": _ann(read_only=True, open_world=True),
    },
    {
        "name": "statica_metric_set",
        "command": "metric-set",
        "title": "Turn code metrics on or off",
        "description": (
            "Turn individual code metrics on or off by key (for example "
            "FUCYC). Metrics not named keep their state. Applies to everyone "
            "using the server project; confirm with the user first."),
        "params": {
            "projectDir": PROJECT_DIR,
            "on": {"type": "array", "items": {"type": "string"}, "flag": "--on",
                   "kind": "repeat", "description": "Metric keys to turn on."},
            "off": {"type": "array", "items": {"type": "string"},
                    "flag": "--off", "kind": "repeat",
                    "description": "Metric keys to turn off."},
        },
        "annotations": _ann(destructive=True, idempotent=True, open_world=True),
    },
    {
        "name": "statica_report_generator_show",
        "command": "report-generator-show",
        "title": "Show automatic report settings",
        "description": "Show whether the server generates a report after each "
                       "analysis, and in which format and kinds. Changes "
                       "nothing.",
        "params": {"projectDir": PROJECT_DIR},
        "annotations": _ann(read_only=True, open_world=True),
    },
    {
        "name": "statica_report_generator_set",
        "command": "report-generator-set",
        "title": "Set automatic report generation",
        "description": (
            "Turn automatic report generation after each analysis on or off. "
            "Turning it on needs a format and at least one kind (1-12). Applies "
            "to everyone using the server project; confirm with the user "
            "first."),
        "params": {
            "projectDir": PROJECT_DIR,
            "enabled": {"type": "boolean", "kind": "onoff",
                        "description": "true to turn it on, false to turn it "
                                       "off."},
            "format": {"type": "string", "enum": REPORT_FORMATS,
                       "flag": "--format", "kind": "value",
                       "description": "Report format."},
            "kinds": {"type": "array",
                      "items": {"type": "integer", "minimum": 1, "maximum": 12},
                      "flag": "--kind", "kind": "repeat",
                      "description": "Report kinds 1-12."},
        },
        "required": ["projectDir", "enabled"],
        "annotations": _ann(destructive=True, idempotent=True, open_world=True),
    },
    {
        "name": "statica_report",
        "command": "report",
        "title": "Generate and download a report",
        "description": (
            "Ask the server to generate a report from the latest revision, wait "
            "for it, and download it (default <project>/.static/reports/). Can "
            "take minutes. Kinds: 1 project summary, 2 remaining defects, 3 "
            "suppressed defects, 4 by rule, 5 by ruleset, 6 by severity, 7 by "
            "file, 8 module metrics, 9 file metrics, 10 class metrics, 11 "
            "function metrics, 12 suppressed metrics. On failure 'stage' tells "
            "how far it got."),
        "params": {
            "projectDir": PROJECT_DIR,
            "format": {"type": "string", "enum": REPORT_FORMATS,
                       "flag": "--format", "kind": "value",
                       "description": "Report format."},
            "kinds": {"type": "array",
                      "items": {"type": "integer", "minimum": 1, "maximum": 12},
                      "minItems": 1, "flag": "--kind", "kind": "repeat",
                      "description": "Report kinds 1-12."},
            "out": {"type": "string", "flag": "--out", "kind": "value",
                    "description": "Where to save the file. An existing file "
                                   "there is replaced. Omit for the default "
                                   "location."},
            "timeout": {"type": "integer", "minimum": 1, "maximum": 3600,
                        "flag": "--timeout", "kind": "value",
                        "description": "Seconds to wait for generation "
                                       "(default 600)."},
        },
        "required": ["projectDir", "format", "kinds"],
        "annotations": _ann(open_world=True),
    },
    {
        "name": "statica_upload",
        "command": "upload",
        "title": "Analyze and upload to the server",
        "description": (
            "Analyze the whole project and upload the result to the STATIC "
            "server as a new revision the whole team sees. Holds a licence slot "
            "and takes time. Call ONLY when the user explicitly asks to upload "
            "or publish results to the server; never as a follow-up to "
            "pre-analyze, a scope change or NO_CHANGES. returncode 113: the "
            "project is already being analyzed; 114: licence limit reached - "
            "ask the user to retry later. If ok is false, do not say the upload "
            "happened."),
        "params": {
            "projectDir": PROJECT_DIR,
            "parallel": {"type": "integer", "minimum": 1, "flag": "--parallel",
                         "kind": "value",
                         "description": "Analyzer parallelism. Omit for the "
                                        "default."},
        },
        "annotations": _ann(open_world=True),
        "timeout": ANALYZE_TIMEOUT,
        "guide": "upload",
    },
    # ---- 부트스트랩 ----------------------------------------------------
    # 순서: detect → (언어 · 환경 · 컴파일러 판단) → begin → (치환; 파일을
    # 고칠 때만 guard) → (빌드) → verify → finish. 실패 시 abort.
    # 절차 전체는 statica_get_guide topic=bootstrap 에 있다.
    {
        "name": "statica_bootstrap_detect",
        "command": "detect",
        "title": "Gather bootstrap evidence",
        "description": (
            "Step 1 of connecting a project to STATIC: collect build-system "
            "clues (artifacts: C/C++; languageArtifacts: Java, Kotlin, Python, "
            "C#) and the existing toolchain detector's view. Changes nothing. "
            "Choosing the language, environment and compiler from it is your "
            "judgement; follow statica_get_guide topic=bootstrap, and ask the "
            "user when clues point to more than one environment."),
        "params": {"projectDir": PROJECT_DIR},
        "annotations": _ann(read_only=True),
        "guide": "bootstrap",
    },
    {
        "name": "statica_bootstrap_begin",
        "command": "bootstrap-begin",
        "title": "Create STATIC workspace and wrapper",
        "description": (
            "Start connecting a project: verify the compiler by running it, "
            "then create the STATIC workspace and (C/C++) the compiler wrapper "
            "whose wrapperDir the build must be pointed at. Java and Kotlin "
            "also create the server project here. Does not edit project files. "
            "BEFORE CALLING: read statica_get_guide topic=bootstrap and get the "
            "user's approval for the whole connection - it later edits project "
            "build settings, runs a full build and creates a project on the "
            "shared server. C/C++ needs ide, compiler and compilerPath; other "
            "languages pass language and none of those. stage=existing-"
            "workspace means a workspace already exists: resume it "
            "(bootstrapping) or stop (ready), never start a second one."),
        "params": {
            "projectDir": PROJECT_DIR,
            "name": {"type": "string", "flag": "--name", "kind": "value",
                     "description": "Workspace name; becomes the server "
                                    "project key. Alphanumerics, at least 3 "
                                    "after dropping leading digits."},
            "language": {"type": "string", "enum": LANGUAGES,
                         "flag": "--language", "kind": "value",
                         "description": "Project language. Default ccpp "
                                        "(C/C++)."},
            "ide": {"type": "string", "flag": "--ide", "kind": "value",
                    "description": "C/C++ only: forge ide value from the "
                                   "environments guide."},
            "compiler": {"type": "string", "flag": "--compiler",
                         "kind": "value",
                         "description": "C/C++ only: forge compiler value from "
                                        "the environments guide."},
            "compilerPath": {"type": "string", "flag": "--compiler-path",
                             "kind": "value",
                             "description": "C/C++ only: absolute path of the "
                                            "original compiler executable. "
                                            "Never guess it."},
            "buildCommand": {"type": "string", "flag": "--build-command",
                             "kind": "value",
                             "description": "Build command, if the build is "
                                            "not GUI-only. Omit rather than "
                                            "passing an empty string."},
            "input": {"type": "string", "flag": "--input", "kind": "value",
                      "description": "C# only: absolute path of the .sln or "
                                     ".csproj to analyze."},
            "csharpConfiguration": {"type": "string",
                                    "flag": "--csharp-configuration",
                                    "kind": "value",
                                    "description": "C# only: build "
                                                   "configuration such as "
                                                   "Debug or Release."},
            "csharpTarget": {"type": "string", "enum": ["framework", "sdk"],
                             "flag": "--csharp-target", "kind": "value",
                             "description": "C# only: sdk for .NET 5+ / "
                                            "SDK-style projects, else "
                                            "framework (default)."},
        },
        "required": ["projectDir", "name"],
        "annotations": _ann(destructive=True, open_world=True),
        "guide": "bootstrap",
    },
    {
        "name": "statica_bootstrap_guard",
        "command": "bootstrap-guard",
        "title": "Back up project files before editing",
        "description": (
            "C/C++ only, and only when the substitution edits project files "
            "(guide type B: a hard-coded Makefile, Vitis CMakeLists.txt): keep "
            "the originals so statica_bootstrap_abort can restore them. Call "
            "right before editing. Do NOT call for command-line (A) or IDE/GUI "
            "(C) substitution, and never invent a file to satisfy the argument: "
            "a guarded file that did not exist is deleted on abort."),
        "params": {
            "projectDir": PROJECT_DIR,
            "files": {"type": "array", "items": {"type": "string"},
                      "minItems": 1, "flag": "--file", "kind": "repeat",
                      "description": "Existing project files about to be "
                                     "edited."},
        },
        "required": ["projectDir", "files"],
        "annotations": _ann(),
        "guide": "bootstrap",
    },
    {
        "name": "statica_bootstrap_verify",
        "command": "bootstrap-verify",
        "title": "Check the build was captured",
        "description": (
            "After substituting the compiler and building (C/C++), or "
            "preparing the build descriptor (Java/Kotlin), check that STATIC "
            "has something to analyze. A successful build is not proof it went "
            "through the wrapper; ok=false means it did not. What to do next "
            "depends on the substitution type - see the guide (do not abort a "
            "GUI substitution). Also returns the workspace when resuming. Can "
            "be called any number of times."),
        "params": {"projectDir": PROJECT_DIR},
        "annotations": _ann(read_only=True),
        "guide": "bootstrap",
    },
    {
        "name": "statica_bootstrap_finish",
        "command": "bootstrap-finish",
        "title": "Register project and run first analysis",
        "description": (
            "Last step of connecting a project: re-check the capture, create "
            "the server project, mark the workspace ready, then run the full "
            "analysis and UPLOAD it (fullAnalysis). Deletes the backups taken "
            "by statica_bootstrap_guard once it succeeds. Covered by the "
            "user's approval of the connection; no separate upload question. "
            "stage=project means only server registration failed: fix the "
            "cause and call again, do not abort. Do not run pre-analyze "
            "afterwards. Pass on buildCommandWarning verbatim."),
        "params": {"projectDir": PROJECT_DIR},
        "annotations": _ann(destructive=True, open_world=True),
        "timeout": ANALYZE_TIMEOUT,
        "guide": "bootstrap",
    },
    {
        "name": "statica_bootstrap_abort",
        "command": "bootstrap-abort",
        "title": "Cancel an unfinished connection",
        "description": (
            "Undo an unfinished connection: restore files kept by "
            "statica_bootstrap_guard, then delete the wrapper and workspace. "
            "Refuses ready workspaces. For IDE/GUI substitution it cannot undo "
            "the IDE settings - walk the user through the guide's revert steps "
            "too. If ok is false the project is still modified: relay "
            "restore.failed and snapshotDir verbatim. Confirm with the user "
            "first."),
        "params": {
            "projectDir": PROJECT_DIR,
            "reason": {"type": "string", "flag": "--reason", "kind": "value",
                       "description": "Why the connection is being "
                                      "cancelled."},
        },
        "annotations": _ann(destructive=True),
        "guide": "bootstrap",
    },
    # ---- 절차 안내 (CLI 가 아니라 서버가 직접 답한다) -------------------
    {
        "name": "statica_get_guide",
        "builtin": "guide",
        "title": "Read a STATICA procedure",
        "description": (
            "Return the procedure STATICA's own skills follow, adapted for MCP: "
            "which tool runs each step, what to ask the user and where to stop. "
            "Read topic=bootstrap before connecting a project and follow it; it "
            "points to bootstrap-environments (C/C++ environments, compiler "
            "paths, substitution and revert steps) and bootstrap-other-"
            "languages (Java, Kotlin, Python, C#). upload explains when to "
            "upload; overview explains the plugin's scope."),
        "params": {
            "topic": {"type": "string", "enum": GUIDE_TOPICS, "kind": "value",
                      "description": "Which procedure to read."},
        },
        "required": ["topic"],
        "annotations": _ann(read_only=True),
    },
]

# 스키마에 내보내지 않는 내부 키
_PRIVATE_KEYS = ("flag", "kind")


def _required(spec):
    if "required" in spec:
        return list(spec["required"])
    return ["projectDir"] if "projectDir" in spec["params"] else []


def input_schema(spec):
    props = {}
    for name, pspec in spec["params"].items():
        props[name] = {k: v for k, v in pspec.items() if k not in _PRIVATE_KEYS}
    schema = {"type": "object", "properties": props,
              "additionalProperties": False}
    required = _required(spec)
    if required:
        schema["required"] = required
    return schema


def tool_listing(spec):
    """tools/list 에 실을 모양."""
    annotations = dict(spec["annotations"], title=spec["title"])
    return {"name": spec["name"], "title": spec["title"],
            "description": spec["description"],
            "inputSchema": input_schema(spec), "annotations": annotations}


def by_name(name):
    return next((t for t in TOOLS if t["name"] == name), None)


def timeout_for(spec, arguments):
    if spec["command"] == "report":
        wait = arguments.get("timeout") or REPORT_WAIT_DEFAULT
        return wait + REPORT_MARGIN
    return spec.get("timeout", DEFAULT_TIMEOUT)


# --------------------------------------------------------------------------
# 인자 검사
# --------------------------------------------------------------------------

def _type_ok(expected, value):
    # bool 은 int 의 하위 타입이다. 플래그를 숫자로, 숫자를 플래그로 받지 않는다.
    if expected == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False
    if expected == "integer":
        return isinstance(value, int)
    if expected == "number":
        return isinstance(value, (int, float))
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def _check_value(label, pspec, value):
    expected = pspec.get("type")
    if not _type_ok(expected, value):
        return "%s must be of type %s" % (label, expected)
    if "enum" in pspec and value not in pspec["enum"]:
        return "%s must be one of %s" % (label, ", ".join(map(str, pspec["enum"])))
    if expected in ("integer", "number"):
        if "minimum" in pspec and value < pspec["minimum"]:
            return "%s must be >= %s" % (label, pspec["minimum"])
        if "maximum" in pspec and value > pspec["maximum"]:
            return "%s must be <= %s" % (label, pspec["maximum"])
    if expected == "string" and not value.strip():
        return "%s must not be empty" % label
    if expected == "array":
        if len(value) < pspec.get("minItems", 0):
            return "%s needs at least %d item(s)" % (label, pspec["minItems"])
        item_spec = pspec.get("items") or {}
        for i, item in enumerate(value):
            bad = _check_value("%s[%d]" % (label, i), item_spec, item)
            if bad:
                return bad
    return None


def validate(spec, arguments, isabs, isdir):
    """``arguments`` 가 맞지 않으면 사람이 읽을 오류 문자열, 맞으면 None.

    경로 검사 함수는 주입받는다 - 테스트가 디스크 없이 돌 수 있게.
    """
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    params = spec["params"]
    unknown = sorted(set(arguments) - set(params))
    if unknown:
        return "unknown argument(s): %s" % ", ".join(unknown)
    for name in _required(spec):
        if arguments.get(name) is None:
            return "missing required argument: %s" % name
    for name, value in arguments.items():
        if value is None:
            continue
        bad = _check_value(name, params[name], value)
        if bad:
            return bad

    project_dir = arguments.get("projectDir")
    if spec.get("command") == "switch":
        # CLI 는 --project-dir 도 --global 도 없으면 **전역**으로 처리한다.
        # 모델이 projectDir 를 빠뜨렸다고 모든 프로젝트의 스위치가 바뀌면 안 된다.
        if arguments.get("global") and project_dir is not None:
            return "pass either projectDir or global=true, not both"
        if not arguments.get("global") and project_dir is None:
            return "projectDir is required unless global is true"
    if project_dir is not None:
        if not isabs(project_dir):
            return "projectDir must be an absolute path: %s" % project_dir
        if not isdir(project_dir):
            return "projectDir is not an existing directory: %s" % project_dir
    return None


def to_argv(spec, arguments):
    """검사를 통과한 인자를 ``run.py`` 뒤에 붙일 argv 로 옮긴다."""
    argv = [spec["command"]]
    # 위치 인자(on/off)는 서브커맨드 바로 뒤에 둔다.
    for name, pspec in spec["params"].items():
        if pspec["kind"] == "onoff" and arguments.get(name) is not None:
            argv.append("on" if arguments[name] else "off")
    for name, pspec in spec["params"].items():
        value = arguments.get(name)
        kind = pspec["kind"]
        if value is None or kind == "onoff":
            continue
        if kind == "flag":
            if value:
                argv.append(pspec["flag"])
        # `--flag=value` 로 붙여 쓴다. `-` 로 시작하는 경로를 argparse 가 다른
        # 옵션으로 읽지 않게.
        elif kind == "value":
            argv.append("%s=%s" % (pspec["flag"], value))
        elif kind == "repeat":
            for item in value:
                argv.append("%s=%s" % (pspec["flag"], item))
        else:  # pragma: no cover - 표를 잘못 적었을 때만
            raise ValueError("unknown param kind %r on %s" % (kind, name))
    return argv
