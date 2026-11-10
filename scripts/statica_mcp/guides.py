"""스킬 문서를 MCP 로 내보낸다 - ``statica_get_guide`` 도구와 prompts.

부트스트랩에서 판단의 대부분(언어 · 환경 판별, 치환 유형, 언제 묻고 어디서
멈출지, 되돌리는 법)은 CLI 가 아니라 스킬 문서에 있다. 스킬이 없는 MCP
클라이언트도 같은 절차를 따르도록 **문서를 복사하지 않고 그 자리에서 읽어**
머리말 하나만 붙여 돌려준다. 스킬 문서를 고치면 MCP 쪽도 그대로 따라온다.

머리말은 두 가지를 옮긴다: 문서 속 `run.py <서브커맨드>` 셸 명령 → 대응하는 MCP
도구 (대응표에서 자동으로 만든다), 그리고 MCP 에서는 할 수 없는 일(빌드 실행,
파일 손편집, MSVC 셸 환경)을 어떻게 다룰지.
"""
import re
from pathlib import Path

from . import tools as catalog

# topic → (스킬 id, 파일). 스킬 id 는 SKILL.md frontmatter 의 name 이다.
TOPICS = {
    "bootstrap": ("statica-analyze-bootstrap", "SKILL.md"),
    "bootstrap-environments": ("statica-analyze-bootstrap", "environments.md"),
    "bootstrap-other-languages": ("statica-analyze-bootstrap",
                                  "other-languages.md"),
    "upload": ("upload", "SKILL.md"),
    "overview": ("statica-analyze-overview", "SKILL.md"),
}

# 문서끼리 가리킬 때 쓰는 파일 이름 → topic
_DOC_TOPICS = {"SKILL.md (statica-analyze-bootstrap)": "bootstrap",
               "environments.md": "bootstrap-environments",
               "other-languages.md": "bootstrap-other-languages"}

_FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
_NAME = re.compile(r"^name:\s*(\S+)\s*$", re.M)


def skills_root():
    """static_agent 패키지와 같은 규칙으로 skills/ 를 찾는다.

    개발 형상은 ``src/runtime/scripts`` + ``src/skills``, 설치 형상은
    ``<root>/scripts`` + ``<root>/skills`` 다 (static_agent/__init__.py 참조).
    """
    runtime = Path(__file__).resolve().parents[2]
    if runtime.name == "runtime" and runtime.parent.name == "src":
        return runtime.parent / "skills"
    return runtime / "skills"


def _skill_dir(skill_id):
    """스킬 디렉터리. 벤더 어댑터가 폴더 이름을 바꿨을 수 있어 frontmatter 로도 찾는다."""
    root = skills_root()
    direct = root / skill_id
    if (direct / "SKILL.md").is_file():
        return direct
    for skill_md in sorted(root.glob("*/SKILL.md")):
        try:
            head = skill_md.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        match = _NAME.search(head)
        if match and match.group(1).strip("'\"") == skill_id:
            return skill_md.parent
    return None


def _flag_table():
    rows = ["| 문서의 서브커맨드 | MCP 도구 | 플래그 → 인자 |", "|---|---|---|"]
    for spec in catalog.TOOLS:
        command = spec.get("command")
        if not command:
            continue
        flags = []
        for name, pspec in spec["params"].items():
            if pspec.get("flag") == "--project-dir":
                continue
            if pspec.get("kind") == "onoff":
                flags.append("`on`/`off` → `%s`" % name)
            elif pspec.get("flag"):
                flags.append("`%s` → `%s`" % (pspec["flag"], name))
        rows.append("| `%s` | `%s` | %s |" % (command, spec["name"],
                                              ", ".join(flags) or "-"))
    return "\n".join(rows)


def preamble(topic):
    docs = ", ".join("`%s` → topic `%s`" % (doc, t)
                     for doc, t in _DOC_TOPICS.items())
    return """\
> **MCP 에서 이 문서를 읽는 법** (statica_get_guide topic=%s)
>
> 아래는 STATICA 스킬이 따르는 절차 원문이다. 문서 속 셸 명령
> `python "${SKILL_ROOT}/scripts/run.py" <서브커맨드> --project-dir "$(pwd)" ...`
> 는 셸로 실행하지 말고 **대응하는 MCP 도구로 부른다.** `--project-dir "$(pwd)"`
> 는 `projectDir`(분석 대상 프로젝트의 절대경로)다. `/statica:upload` 는
> `statica_upload`, `/statica:pre-analyze` 는 `statica_pre_analyze` 다.
> "설치 경로와 호스트 연결" · "실행 경로" 절은 스크립트를 경로로 실행할 때의
> 이야기이므로 무시한다.
>
> 문서가 다른 문서를 가리키면 statica_get_guide 로 읽는다: %s.
>
> **도구가 없는 일** - 빌드 실행, Maven 플러그인 설치, Makefile · CMakeLists.txt
> 편집, `agent.json` 의 `buildCommand` 손편집, IDE 설정 변경 - 은 셸 · 파일 편집
> 도구가 있으면 그것으로 하고, 없으면 사용자에게 정확한 명령 · 파일 · 값을 주고
> 해 달라고 요청한 뒤 끝났다는 답을 기다린다. 해 주지 않은 일을 했다고 말하지 마라.
>
> **MSVC 셸 환경**: 문서는 "vcvars 를 먼저 실행한 같은 셸에서 bootstrap-begin"
> 을 부르라고 한다. MCP 도구는 이 MCP 서버 프로세스의 환경에서 돈다. 클라이언트가
> Developer Command Prompt 에서 시작되지 않았다면 컴파일러 검증이 실패하는데,
> 경로 문제가 아니다 - 사용자에게 클라이언트를 Developer Command Prompt 에서
> 다시 시작하도록 안내하라.

%s

---

""" % (topic, docs, _flag_table())


def read_guide(topic):
    """(본문, 오류). 둘 중 하나만 채워진다."""
    if topic not in TOPICS:
        return None, "unknown topic: %s (one of %s)" % (
            topic, ", ".join(TOPICS))
    skill_id, filename = TOPICS[topic]
    skill_dir = _skill_dir(skill_id)
    if skill_dir is None:
        return None, ("the %s skill is not installed next to this MCP server "
                      "(looked under %s)" % (skill_id, skills_root()))
    path = skill_dir / filename
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, "could not read %s (%s)" % (path, exc)
    return preamble(topic) + _FRONTMATTER.sub("", text, count=1).lstrip(), None


# --------------------------------------------------------------------------
# prompts - 사용자가 고르는 입구. 연결 · 업로드는 사용자가 시작할 일이라
# 클라이언트의 프롬프트 메뉴(슬래시 커맨드)로 내 둔다.
# --------------------------------------------------------------------------

PROJECT_ARG = {"name": "projectDir", "required": False,
               "description": "Absolute path of the project. Omit it and the "
                              "assistant will ask."}

PROMPTS = [
    {
        "name": "connect-project",
        "title": "Connect a project to STATIC",
        "description": "Connect a project to STATIC for the first time, "
                       "following STATICA's bootstrap procedure.",
        "arguments": [PROJECT_ARG],
        "text": (
            "{target} 를 STATIC 에 연결해 줘.\n\n"
            "먼저 `statica_get_guide` 를 topic=bootstrap 으로 읽고 그 절차를 "
            "그대로 따라라. `statica_bootstrap_begin` 을 부르기 전에 무엇을 "
            "하는지(프로젝트 빌드 설정 변경 가능성, 전체 빌드, 공용 STATIC "
            "서버에 프로젝트 생성과 첫 분석 업로드)를 설명하고 내 승인을 받아라. "
            "이미 진행 중인 연결이 있으면 처음부터 다시 하지 말고 이어서 해라."),
    },
    {
        "name": "upload-analysis",
        "title": "Upload a full analysis",
        "description": "Analyze the whole project and upload it to the STATIC "
                       "server as a new revision.",
        "arguments": [PROJECT_ARG],
        "text": (
            "{target} 의 전체 분석 결과를 STATIC 서버에 업로드해 줘.\n\n"
            "`statica_upload` 를 한 번 부르고, 결과는 `statica_get_guide` "
            "topic=upload 의 규칙대로 전해라."),
    },
]


def prompt_listing():
    return [{k: p[k] for k in ("name", "title", "description", "arguments")}
            for p in PROMPTS]


def get_prompt(name, arguments):
    """(결과, 오류)."""
    prompt = next((p for p in PROMPTS if p["name"] == name), None)
    if prompt is None:
        return None, "Unknown prompt: %s" % name
    project_dir = (arguments or {}).get("projectDir")
    target = ("`%s` 프로젝트" % project_dir) if project_dir \
        else ("내 프로젝트 (projectDir 를 주지 않았다. 먼저 분석할 프로젝트의 "
              "절대경로를 나에게 물어라 - 작업 디렉터리를 가정하지 마라)")
    return {"description": prompt["description"],
            "messages": [{"role": "user", "content": {
                "type": "text", "text": prompt["text"].format(target=target)}}]
            }, None
