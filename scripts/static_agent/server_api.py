"""STATIC 서버의 Open API v1 클라이언트.

`vendor/project_api.py` 를 대신한다. 그쪽은 v0 (`POST /api/forward/open-api/projects`)
를 부르는데, 그 엔드포인트는 **소유자 이메일을 요청 본문으로 요구한다.**
클라이언트가 알 수 없는 값이라 번들 설정에 주소를 하나 박아 두는 수밖에 없었고,
그것이 이 플러그인의 가장 오래된 지뢰였다 — 대상 서버에 그 계정이 없으면 빌드와
캡처를 다 끝낸 마지막 단계에서 404 로 죽는다.

v1 에서 그 요구가 사라졌다. `POST /v1/projects` 의 `email` 은 선택이고, 비우면
**서버가 accessKey 로 계정을 찾아 소유자로 삼는다.** 그래서 여기서는 이메일을
보내지 않는다.

v1 은 화면이 쓰는 API 를 그대로 열어 둔 것이라, 우리가 원하는 모양으로 한 번에
주지 않는 곳이 있다. 룰셋이 그렇다 — 선택된 것과 고를 수 있는 것이 다른
엔드포인트다. 그런 조립은 이 모듈이 감춘다. 부르는 쪽은 예전과 같은 모양을 받는다.

`vendor/project_api.py` 는 지우지 않는다 — `project_key_from_name` 이 아직
쓰이고 있고, vendor 자산은 원본 그대로 두는 것이 이 저장소의 규율이다.
"""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import settings, workspace
from .errors import PluginError
from .vendor.project_api import project_key_from_name

# 이 servlet 은 `@EnableInternalAccessSecurity` 가 직접 호출을 막는다. 반드시
# static-api 의 forward 를 거쳐야 하며, 그 경로가 accessKey 검증도 함께 건다
# (`SecurityWhitelistUrls.REQUIRES_ACCESS_KEY_URL` 의 `/forward/**`).
V1_PATH = "/api/forward/open-api/v1"
CREATE_PROJECT_PATH = V1_PATH + "/projects"
PROJECT_DETAIL_PATH_TEMPLATE = V1_PATH + "/projects/{key}"

# 룰셋 카탈로그. 프로젝트에 매이지 않아서 언어·분석기 버전·표시 언어를 질의로
# 받는다. 셋 다 프로젝트에서 읽어 채운다 — 우리가 고르면 이름이 딴 언어로 온다.
RULESET_CATALOG_PATH = V1_PATH + "/rulesets"


PROJECT_RULESET_PATH_TEMPLATE = V1_PATH + "/projects/{key}/ruleset"
SET_RULESET_PATH_TEMPLATE = PROJECT_RULESET_PATH_TEMPLATE


def project_ruleset_path(project_key):
    """이 프로젝트에 **선택된** 룰셋을 읽는 경로.

    고를 수 있는 전체 목록은 여기 없다 (`RULESET_CATALOG_PATH`). 조회와 변경이
    같은 경로이고, 변경이 **전체 교체**라 지금 켜져 있는 것을 모르는 채 일부만
    보내면 나머지가 조용히 꺼진다.
    """
    return PROJECT_RULESET_PATH_TEMPLATE.format(key=project_key)

# 서버 응답에서 결과 JSON 으로 옮겨도 되는 필드. 인증 정보를 만지는 경로이므로
# 새 필드가 늘어도 새지 않도록 화이트리스트로 받는다.
#
# v1 은 소유자를 돌려주지 않는다 (`ProjectDetailV1Dto`). 서버가 accessKey 로 정한
# 소유자가 누구인지 응답만으로는 알 수 없어서, 이제 그 말을 하지 않는다.
_RESPONSE_FIELDS = ("key",)

_TIMEOUT_SECONDS = 30


def _post_json(url, payload, access_key, timeout=_TIMEOUT_SECONDS, method="POST"):
    """JSON 을 보낸다. `(status, body, error)` 를 돌려준다.

    accessKey 는 헤더에만 싣고 어떤 반환값에도 넣지 않는다. ``payload`` 가 None
    이면 본문 없는 요청(GET)이다.
    """
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {access_key}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    # 사내 서버가 자체 서명 인증서를 쓴다. 검증을 켜면 언제나 실패하므로 이
    # 호출에서만 끈다 (vendor/project_api.py 가 하던 것과 같다).
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), None
    except urllib.error.URLError as e:
        return None, None, f"서버에 연결하지 못했습니다: {url} ({e.reason})"
    except OSError as e:
        return None, None, f"서버 호출에 실패했습니다: {url} ({type(e).__name__})"


def _fill_project_key(ws, key):
    """워크스페이스의 `app.data.json` 에 projectKey 를 기입한다.

    이 값이 없으면 분석기가 프로젝트를 찾지 못한다 (`NO_PROJECT_KEY`).
    """
    path = Path(ws) / workspace.APP_DATA_REL
    data = workspace.read_json(path)
    if not isinstance(data, dict):
        return False, f"app.data.json 을 읽을 수 없습니다: {path}"
    data["projectKey"] = key
    try:
        workspace.write_json(path, data)
    except OSError as e:
        return False, f"app.data.json 을 쓰지 못했습니다: {path} ({type(e).__name__})"
    return True, None


def create_project(ws, workspace_name, language, name=None):
    """서버에 프로젝트를 만들고 `app.data.json` 의 projectKey 를 채운다.

    **소유자 이메일을 보내지 않는다.** `email` 은 v1 에서 선택이고, 비우면 서버가
    accessKey 로 계정을 찾아 소유자로 삼는다. 그 계정이 누구인지는 응답에 없다.

    이미 있는 키(HTTP 409)는 성공으로 친다 — 같은 키의 프로젝트가 존재한다는
    사실 자체가 우리가 원하는 상태이고, java · kotlin 은 `begin` 과 `finish`
    두 번 부르므로 두 번째는 반드시 409 다.

    예외를 내지 않고 결과 dict 를 돌려준다. 호출하는 쪽(`bootstrap`)이 실패를
    단계 정보와 함께 보고해야 하기 때문이다.
    """
    out = {"ran": True, "ok": False, "key": None,
           "status": None, "message": None}

    key, error = project_key_from_name(workspace_name)
    if error:
        out["message"] = error
        return out
    out["key"] = key

    try:
        setting = settings.read_server_setting()
    except PluginError as e:
        out["message"] = e.message
        out["code"] = e.code
        return out

    # 보내는 것은 서버가 알 수 없는 것뿐이다. description · analyzerVersion ·
    # projectType · isPrivate 은 넘기지 않는다 — 서버 기본값(빈 설명, 최신
    # 분석기, GENERAL, 공개)이 우리가 박아 둘 값보다 언제나 낫다. 특히
    # analyzerVersion 을 고정하면 서버를 올려도 옛 분석기로 프로젝트가 생긴다.
    payload = {"key": key, "language": language.server}
    if name:
        payload["name"] = name
    out["request"] = dict(payload)

    url = setting.server + CREATE_PROJECT_PATH
    out["url"] = url

    status, body, error = _post_json(url, payload, setting.access_key)
    if error:
        out["message"] = error
        return out
    out["status"] = status
    out["body"] = (body or "").strip()[:1000]

    if status == 200:
        out["created"] = True
        parsed = _parse(body)
        for field in _RESPONSE_FIELDS:
            if parsed.get(field):
                out[field] = parsed[field]
    elif status == 409:
        out["existed"] = True
    elif status == 401:
        out["code"] = "NO_ACCESS_KEY"
        out["message"] = ("서버가 AccessKey 를 받아들이지 않았습니다(401). Arachne "
                          "설정의 AccessKey 가 이 서버의 것이 맞는지, 그 계정이 "
                          "활성 상태인지 확인하세요.")
        return out
    elif status == 404:
        # open-api v1 이 없는 구버전 서버일 가능성이 가장 크다. 예전처럼
        # "소유자 이메일이 없다"로 읽으면 엉뚱한 곳을 고치게 된다.
        out["code"] = "ENDPOINT_NOT_FOUND"
        out["message"] = (f"서버에 이 엔드포인트가 없습니다(404): {url}. "
                          "Open API v1 을 포함한 버전으로 서버를 올려야 합니다.")
        return out
    else:
        out["message"] = (f"프로젝트 생성이 실패했습니다(HTTP {status}): "
                          f"{out['body'] or '(응답 본문 없음)'}")
        return out

    filled, fill_error = _fill_project_key(ws, key)
    if not filled:
        out["message"] = f"프로젝트는 준비되었으나 {fill_error}"
        return out

    out["ok"] = True
    out["message"] = (f"프로젝트 {key} 를 만들었습니다." if status == 200
                      else f"프로젝트 {key} 가 이미 있어 그대로 연결했습니다.")
    return out


def _parse(body, allow_list=False):
    """본문을 dict 로 읽는다. 모양이 다르면 빈 dict 다.

    부르는 쪽이 전부 `.get()` 을 쓰므로 형식 검사를 여기서 한 번에 한다.
    ``allow_list`` 는 배열을 돌려주는 엔드포인트(`GET /v1/rulesets`) 하나를 위한
    문이다 — 기본을 열어 두면 다른 호출이 조용히 형식 검사를 잃는다.
    """
    try:
        data = json.loads(body or "{}")
    except json.JSONDecodeError:
        return {}
    if allow_list and isinstance(data, list):
        return data
    return data if isinstance(data, dict) else {}


def _call(path, payload=None, method="POST", forbidden_message=None, allow_list=False):
    """서버 설정을 읽어 한 번 호출한다. `(status, parsed, failure)`.

    `failure` 가 채워지면 그것을 그대로 결과로 돌려주면 된다 — 서버 설정 문제,
    연결 실패, 그리고 상태 코드로 이름 붙일 수 있는 실패가 여기서 처리된다.
    """
    try:
        setting = settings.read_server_setting()
    except PluginError as e:
        return None, {}, {"ok": False, "code": e.code, "message": e.message}

    url = setting.server + path
    status, body, error = _post_json(url, payload, setting.access_key, method=method)
    if error:
        return None, {}, {"ok": False, "message": error, "url": url}

    if status == 401:
        return status, {}, {
            "ok": False, "code": "NO_ACCESS_KEY", "status": status, "url": url,
            "message": ("서버가 AccessKey 를 받아들이지 않았습니다(401). Arachne "
                        "설정의 AccessKey 가 이 서버의 것이 맞는지, 그 계정이 "
                        "활성 상태인지 확인하세요.")}
    if status == 403:
        # 기본 문구는 어느 커맨드에서 와도 맞아야 한다. 무엇이 필요한 권한인지는
        # 호출하는 쪽만 아니까 `forbidden_message` 로 덮게 열어 둔다.
        return status, {}, {
            "ok": False, "code": "FORBIDDEN", "status": status, "url": url,
            "message": (forbidden_message
                        or "이 프로젝트에 대한 권한이 없습니다(403). 조회는 프로젝트 "
                           "멤버, 변경은 프로젝트 매니저 이상이어야 합니다.")}
    return status, _parse(body, allow_list=allow_list), None


def _project_not_found(out, project_key, status):
    """404 를 두 가지로 읽을 수 있어서 둘 다 말해 준다.

    프로젝트가 없는 경우와 **서버에 그 엔드포인트 자체가 없는** 경우가 같은 코드로
    온다. v1 은 나중에 붙은 것이라 구버전 서버에서는 후자가 흔하고, 그때 프로젝트만
    의심하면 영영 못 찾는다.
    """
    out.update(code="NOT_FOUND", status=status,
               message=(f"서버에 프로젝트 {project_key} 가 없거나 이 엔드포인트가 "
                        "없습니다(404). 서버가 Open API v1 을 포함한 버전인지 "
                        "확인하세요."))
    return out


def get_project_detail(project_key):
    """프로젝트의 기본 정보와 마지막으로 성공한 분석 회차.

    ``{"ok": True, "projectKey", "name", "language", "analyzerVersion",
       "progressStage", "latestFinishedRevision": {...}}``
    """
    out = {"ok": False, "projectKey": project_key}
    status, data, failure = _call(
        PROJECT_DETAIL_PATH_TEMPLATE.format(key=project_key), method="GET")
    if failure:
        out.update(failure)
        return out
    if status == 404:
        return _project_not_found(out, project_key, status)
    if status != 200:
        out.update(status=status,
                   message=f"프로젝트 조회에 실패했습니다(HTTP {status}).")
        return out

    revision = data.get("latestFinishedRevision")
    out.update(ok=True, status=status,
               name=data.get("name"),
               language=data.get("language"),
               analyzerVersion=data.get("analyzerVersion"),
               accessibility=data.get("accessibility"),
               projectType=data.get("type"),
               progressStage=data.get("status"),
               latestFinishedRevision=revision if isinstance(revision, dict) else None)
    return out


def _ruleset_catalog(language, analyzer_version, locale_language):
    """고를 수 있는 룰셋 전체. `(rulesets, note)`.

    셋 중 하나라도 비면 부르지 않는다 - 특히 ``locale_language`` 는 룰셋 **이름의
    언어**라, 아무 값이나 넣으면 화면과 다른 이름이 나와 사용자가 대조하지 못한다.
    """
    missing = [name for name, value in (("언어", language),
                                        ("분석기 버전", analyzer_version),
                                        ("룰 표시 언어", locale_language))
               if not value]
    if missing:
        return None, f"{' · '.join(missing)} 을(를) 알 수 없어 전체 목록은 읽지 않았습니다."

    query = urllib.parse.urlencode({"programLanguage": language,
                                    "analyzerVersion": analyzer_version,
                                    "localeLanguage": locale_language})
    status, data, failure = _call(f"{RULESET_CATALOG_PATH}?{query}", method="GET",
                                  allow_list=True)
    if failure:
        return None, failure.get("message") or "전체 목록을 읽지 못했습니다."
    if status != 200:
        return None, f"전체 목록을 읽지 못했습니다(HTTP {status})."
    # 이 경로만 배열을 그대로 돌려준다. `_call` 은 dict 만 통과시키므로 여기서
    # 다시 읽는다 - `_parse` 를 느슨하게 바꾸면 다른 호출이 형식 검사를 잃는다.
    if not isinstance(data, list):
        return None, "전체 목록의 응답 형식이 예상과 다릅니다."
    return [r for r in data if isinstance(r, dict)], None


def get_project_ruleset(project_key):
    """프로젝트에 쓸 수 있는 룰셋 전체와 지금 켜져 있는 것.

    ``{"ok": True, "projectKey", "language", "analyzerVersion",
       "localeLanguage", "catalogComplete",
       "rulesets": [{"id", "name", "enabled"}, ...]}``

    **바꾸기 전에 반드시 이것을 먼저 읽어야 한다.** `set_project_ruleset` 이
    전체 교체이기 때문이다.

    v1 은 이 답을 한 번에 주지 않는다. 선택된 것(`/v1/projects/{key}/ruleset`)과
    고를 수 있는 것(`/v1/rulesets`)이 다른 엔드포인트이고, 후자는 언어·분석기
    버전·표시 언어를 질의로 요구해서 프로젝트 상세까지 세 번 부른다.

    전체 목록을 못 읽어도 **선택된 것만으로 답한다** (`catalogComplete: False`).
    전체 교체 API 를 안전하게 부르는 데 꼭 필요한 것은 지금 켜져 있는 목록이고,
    그것은 이미 손에 있기 때문이다.
    """
    out = {"ok": False, "projectKey": project_key}
    status, data, failure = _call(project_ruleset_path(project_key), method="GET")
    if failure:
        out.update(failure)
        return out
    if status == 404:
        return _project_not_found(out, project_key, status)
    if status != 200:
        out.update(status=status,
                   message=f"룰셋 조회에 실패했습니다(HTTP {status}).")
        return out

    selected = data.get("rulesets")
    if not isinstance(selected, list):
        out["message"] = "룰셋 목록을 읽지 못했습니다(응답 형식이 예상과 다릅니다)."
        return out
    selected = [r for r in selected if isinstance(r, dict)]
    locale_language = data.get("localeLanguage")

    detail = get_project_detail(project_key)
    language = detail.get("language") if detail.get("ok") else None
    # 프로젝트 상세를 못 읽어도 선택된 룰셋이 분석기 버전을 들고 있다.
    analyzer_version = (detail.get("analyzerVersion") if detail.get("ok") else None) or next(
        (r.get("analyzerVersion") for r in selected if r.get("analyzerVersion")), None)

    catalog, note = _ruleset_catalog(language, analyzer_version, locale_language)
    selected_ids = {r.get("id") for r in selected}
    if catalog is None:
        rulesets = [{"id": r.get("id"), "name": r.get("name"), "enabled": True}
                    for r in selected]
    else:
        rulesets = [{"id": r.get("id"), "name": r.get("name"),
                     "enabled": r.get("id") in selected_ids}
                    for r in catalog]

    out.update(ok=True, status=status,
               language=language,
               analyzerVersion=analyzer_version,
               localeLanguage=locale_language,
               catalogComplete=catalog is not None,
               rulesets=rulesets)
    out["enabledCount"] = sum(1 for r in rulesets if r["enabled"])
    if catalog is None:
        out["message"] = (f"룰셋 {out['enabledCount']}개가 켜져 있습니다 "
                          f"· 룰 표시 언어 {locale_language} · {note}")
    else:
        out["message"] = (f"룰셋 {len(rulesets)}개 중 {out['enabledCount']}개가 "
                          f"켜져 있습니다 · 룰 표시 언어 {locale_language}")
    return out


def set_project_ruleset(project_key, ruleset_ids, locale_language):
    """프로젝트의 룰셋과 룰 표시 언어를 바꾼다.

    **전체 교체다.** ``ruleset_ids`` 에 없는 룰셋은 전부 꺼진다 — 호출하기 전에
    `get_project_ruleset` 으로 현재 선택을 읽고, 그 위에서 더하고 빼라.

    조회와 같은 경로다(`PUT /v1/projects/{key}/ruleset`). **매니저 권한**이 걸려
    있어 조회만 되고 변경이 막히는 경우가 있다.
    """
    out = {"ok": False, "projectKey": project_key}
    if not ruleset_ids:
        # 서버도 400 으로 막지만, 여기서 먼저 막아야 사용자가 "전부 끄기"를
        # 시도했을 때 무엇이 문제인지 분명해진다.
        out.update(code="EMPTY_RULESET",
                   message="룰셋을 최소 하나는 켜 두어야 합니다.")
        return out

    payload = {"localeLanguage": locale_language,
               "rulesetIds": [int(i) for i in ruleset_ids]}
    path = SET_RULESET_PATH_TEMPLATE.format(key=project_key)
    status, _data, failure = _call(path, payload=payload, method="PUT")
    if failure:
        out.update(failure)
        return out
    if status != 200:
        out.update(status=status,
                   message=f"룰셋 변경에 실패했습니다(HTTP {status}).")
        return out

    out.update(ok=True, status=status,
               rulesetIds=payload["rulesetIds"],
               localeLanguage=locale_language,
               message=(f"룰셋 {len(payload['rulesetIds'])}개를 적용했습니다 "
                        f"· 룰 표시 언어 {locale_language}"))
    return out


# ---------------------------------------------------------------------------
# 보고서
#
# 생성과 자동 생성 설정은 v1 이다. 조회와 변경이 같은 경로여서, 바꾸기 전에 지금
# 값을 보여주는 일이 처음으로 가능해졌다 - 예전에는 변경(PUT)만 있었다.
#
# 상태 · 다운로드는 v0 에 그대로 둔다. v1 에도 있지만 모양이 다르다 - 목록
# (`GET /v1/projects/{key}/reports`)에서 진행률을 찾아야 하고, 다운로드는
# reportId 를 요구한다. 지금 흐름(요청 → 마지막 것을 기다림 → 마지막 것을 받음)에
# 필요 없는 상태를 늘리게 되므로 건드리지 않는다.

REPORT_GENERATOR_PATH_TEMPLATE = V1_PATH + "/projects/{key}/settings/report-generator"
SET_REPORT_GENERATOR_PATH_TEMPLATE = REPORT_GENERATOR_PATH_TEMPLATE
GENERATE_REPORT_PATH_TEMPLATE = V1_PATH + "/projects/{key}/reports"
REPORT_STATUS_PATH_TEMPLATE = "/api/forward/open-api/projects/{key}/report/status"
REPORT_DOWNLOAD_PATH_TEMPLATE = "/api/forward/open-api/projects/{key}/report/download"

# `ReportFileFormat` 에서 DEFECTS_INQUIRY 를 뺐다. 그것은 zip 암호를 함께 받아야
# 하는데 이 경로는 암호를 받지 않는다 - 목록에 두면 고를 수 있는 것처럼 보인다.
REPORT_FORMATS = ("DOC", "PDF", "HTML", "EXCEL")

# ReportController 의 kinds 설명 그대로.
REPORT_KINDS = {
    1: "프로젝트 요약",
    2: "Remaining Defect",
    3: "Suppressed Defect",
    4: "Rule 별 Defect",
    5: "Ruleset 별 Defect",
    6: "Severity 별 Defect",
    7: "File 별 Defect",
    8: "모듈 메트릭",
    9: "파일 메트릭",
    10: "클래스 메트릭",
    11: "함수 메트릭",
    12: "Suppressed 메트릭",
}


def _validate_report_shape(out, file_format, kinds):
    """포맷과 종류를 서버에 보내기 전에 가른다.

    서버도 거절하지만, 거절 사유가 format 이 invalid 하다는 말로만 오면 무엇을
    골라야 하는지는 알 수 없다. 여기서 막으면 고를 수 있는 값을 함께 준다.
    """
    if file_format not in REPORT_FORMATS:
        out.update(code="BAD_FORMAT",
                   message=(f"보고서 형식 {file_format} 을 쓸 수 없습니다. "
                            f"가능한 값: {', '.join(REPORT_FORMATS)}"))
        return False
    if not kinds:
        out.update(code="EMPTY_KINDS", message="보고서 종류를 하나 이상 골라야 합니다.")
        return False
    unknown = [k for k in kinds if k not in REPORT_KINDS]
    if unknown:
        out.update(code="BAD_KIND",
                   message=(f"보고서 종류 {unknown} 을 쓸 수 없습니다. "
                            f"가능한 값: 1~{max(REPORT_KINDS)}"))
        return False
    return True


def get_report_generator(project_key):
    """분석이 끝나면 보고서를 자동으로 만들지에 대한 현재 설정.

    "한 번도 정한 적이 없다"와 "정했다가 껐다"를 **구분하지 못한다.** 서버가 설정
    없음을 `enable:false · format:"" · kinds:[]` 로 채워 돌려주는데
    (`ProjectReportGeneratorV1Dto.from(null)`), 우리가 끄면서 보내는 값과 똑같다.
    구분되는 척하지 않는다 - 사용자에게는 어느 쪽이든 "꺼져 있다"가 맞는 말이다.
    """
    out = {"ok": False, "projectKey": project_key}
    path = REPORT_GENERATOR_PATH_TEMPLATE.format(key=project_key)
    status, data, failure = _call(path, method="GET")
    if failure:
        out.update(failure)
        return out
    if status == 404:
        return _project_not_found(out, project_key, status)
    if status != 200:
        out.update(status=status,
                   message=f"자동 생성 설정 조회에 실패했습니다(HTTP {status}).")
        return out

    kinds = [k for k in (data.get("kinds") or []) if isinstance(k, int)]
    out.update(ok=True, status=status,
               enabled=bool(data.get("enable")),
               format=data.get("format") or "",
               kinds=kinds,
               kindNames=[REPORT_KINDS.get(k, str(k)) for k in kinds])
    if out["enabled"]:
        out["message"] = (f"분석이 끝나면 {out['format']} 형식으로 "
                          f"{len(kinds)}종을 자동 생성합니다.")
    else:
        out["message"] = "자동 생성이 꺼져 있습니다."
    return out


def set_report_generator(project_key, enabled, file_format, kinds):
    """자동 생성 설정을 바꾼다. 전체 교체다.

    끄기만 할 때는 형식과 종류를 묻지 않는다. 반대로 **켜면서 종류를 비우면
    막는다** - 서버는 그 조합을 저장은 하지만 분석 후 아무것도 만들지 않아서
    (`requestGenerateReport` 가 kinds 가 비면 건너뛴다), 사용자는 켜 둔 줄 알고
    영영 기다리게 된다.
    """
    out = {"ok": False, "projectKey": project_key}
    kinds = [int(k) for k in (kinds or [])]
    if enabled and not _validate_report_shape(out, file_format, kinds):
        return out

    payload = {"enable": bool(enabled),
               "format": file_format if enabled else "",
               "kinds": kinds if enabled else []}
    path = SET_REPORT_GENERATOR_PATH_TEMPLATE.format(key=project_key)
    status, _data, failure = _call(path, payload=payload, method="PUT")
    if failure:
        out.update(failure)
        return out
    if status != 200:
        out.update(status=status,
                   message=f"자동 생성 설정 변경에 실패했습니다(HTTP {status}).")
        return out

    out.update(ok=True, status=status, enabled=bool(enabled),
               format=payload["format"], kinds=payload["kinds"],
               message=("자동 생성을 껐습니다." if not enabled else
                        f"분석이 끝나면 {file_format} 형식으로 {len(kinds)}종을 "
                        "자동 생성합니다."))
    return out


def generate_report(project_key, file_format, kinds):
    """보고서 생성을 요청한다. **접수만 하고 돌아온다.**

    이어서 `get_report_status` 로 FINISH 를 기다리고 `download_report` 로 받아야
    한다. 대상 revision 은 서버가 정한다 - 마지막으로 성공한 분석이다.
    """
    out = {"ok": False, "projectKey": project_key}
    kinds = [int(k) for k in (kinds or [])]
    if not _validate_report_shape(out, file_format, kinds):
        return out

    payload = {"format": file_format, "kinds": kinds}
    path = GENERATE_REPORT_PATH_TEMPLATE.format(key=project_key)
    status, data, failure = _call(path, payload=payload, method="POST")
    if failure:
        out.update(failure)
        return out
    if status == 404:
        # 프로젝트가 없는 경우와 **성공한 분석이 없는** 경우가 같은 404 로 온다
        # (`resolveLatestFinishedRevision`). 사용자가 할 일이 완전히 다르므로
        # 서버 메시지로 가른다.
        if "revision" in json.dumps(data, ensure_ascii=False).lower():
            out.update(code="NO_ANALYSIS", status=status,
                       message=("이 프로젝트에 성공한 분석이 아직 없어 보고서를 만들 수 "
                                "없습니다. /statica:upload 로 먼저 분석 결과를 올리세요."))
            return out
        return _project_not_found(out, project_key, status)
    if status != 200:
        out.update(status=status,
                   message=f"보고서 생성 요청에 실패했습니다(HTTP {status}).")
        return out

    out.update(ok=True, status=status,
               reportId=data.get("reportId"),
               # v1 은 revision 을 회차 번호로 준다 (예전에는 내부 id 였다).
               # 사용자가 화면에서 보는 것도 이 번호다.
               revisionSequence=data.get("revisionSequence"),
               format=data.get("format") or file_format,
               kinds=kinds,
               kindNames=[REPORT_KINDS.get(k, str(k)) for k in kinds],
               reportStatus=data.get("progress"),
               message=f"보고서 생성을 요청했습니다 ({len(kinds)}종, {file_format}).")
    return out


def get_report_status(project_key):
    """가장 최근 보고서의 진행 상태. WAIT · INPROGRESS · CANCEL · ERROR · FINISH."""
    out = {"ok": False, "projectKey": project_key}
    path = REPORT_STATUS_PATH_TEMPLATE.format(key=project_key)
    status, data, failure = _call(path, method="GET")
    if failure:
        out.update(failure)
        return out
    if status != 200:
        out.update(status=status,
                   message=f"보고서 상태 조회에 실패했습니다(HTTP {status}).")
        return out
    out.update(ok=True, status=data.get("status"), httpStatus=status)
    return out


def _get_bytes(url, access_key, timeout=_TIMEOUT_SECONDS):
    """본문을 바이트로 받는다. `(status, body, error)`.

    `_post_json` 은 본문을 텍스트로 디코딩하므로 zip 에 쓸 수 없다.
    """
    headers = {"Authorization": f"Bearer {access_key}",
               "Accept": "application/octet-stream"}
    request = urllib.request.Request(url, method="GET", headers=headers)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
            return response.status, response.read(), None
    except urllib.error.HTTPError as e:
        return e.code, e.read(), None
    except urllib.error.URLError as e:
        return None, None, f"서버에 연결하지 못했습니다: {url} ({e.reason})"
    except OSError as e:
        return None, None, f"서버 호출에 실패했습니다: {url} ({type(e).__name__})"


def download_report(project_key, dest_path):
    """가장 최근 보고서를 내려받아 `dest_path` 에 저장한다.

    실패했거나 본문이 비면 **파일을 만들지 않는다.** 0바이트 파일을 남겨 두면
    사용자는 받은 줄 알고 열어 보게 된다.
    """
    out = {"ok": False, "projectKey": project_key, "path": str(dest_path)}
    try:
        setting = settings.read_server_setting()
    except PluginError as e:
        out.update(code=e.code, message=e.message)
        return out

    url = setting.server + REPORT_DOWNLOAD_PATH_TEMPLATE.format(key=project_key)
    status, body, error = _get_bytes(url, setting.access_key)
    if error:
        out.update(message=error, url=url)
        return out
    if status != 200:
        out.update(status=status,
                   message=f"보고서 다운로드에 실패했습니다(HTTP {status}).")
        return out
    if not body:
        out.update(code="EMPTY_REPORT", status=status,
                   message="서버가 빈 보고서를 돌려주었습니다. 저장하지 않았습니다.")
        return out

    dest = Path(dest_path)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
    except OSError as e:
        out.update(code="WRITE_FAILED",
                   message=f"보고서를 저장하지 못했습니다: {dest} ({type(e).__name__})")
        return out

    out.update(ok=True, status=status, bytes=len(body),
               message=f"보고서를 저장했습니다: {dest} ({len(body):,} bytes)")
    return out


# ---------------------------------------------------------------------------
# metric
#
# 조회와 일괄 변경이 한 경로다(`/v1/projects/{key}/metrics/settings`). 변경은 한
# 트랜잭션이라 **전부 되거나 전부 안 된다** - 여러 개를 바꾸다 절반만 반영되는 일이
# 없다. 화면에서 체크박스를 하나씩 누를 때와 달리 여기서는 그 보장이 중요하다.
#
# 섹션(scope) 목록은 따로 오지 않는다. 언어마다 다르므로(C/C++ 만 CLASS 가 있다)
# 우리가 외우지 않고 응답에 나온 순서대로 모은다.

METRICS_PATH_TEMPLATE = V1_PATH + "/projects/{key}/metrics/settings"


def _metric_state(out, data):
    metrics = data.get("metrics")
    if not isinstance(metrics, list):
        out["message"] = "metric 목록을 읽지 못했습니다(응답 형식이 예상과 다릅니다)."
        return False

    # 부르는 쪽이 오래 쓰던 이름을 유지한다 - scope→section, metricKey→key,
    # enabled→use. 서버 필드 이름이 커맨드 문서까지 번지면 다음 개편 때 또 번진다.
    items = [{"section": m.get("scope"), "key": m.get("metricKey"),
              "name": m.get("name"), "description": m.get("description"),
              "use": bool(m.get("enabled"))}
             for m in metrics if isinstance(m, dict)]

    # 커맨드가 섹션별 표로 보여주므로 여기서 묶어 둔다. 서버가 내려준 순서를 그대로
    # 따른다 - 화면과 같은 순서여야 사용자가 대조할 수 있다.
    sections = []
    for item in items:
        if item["section"] and item["section"] not in sections:
            sections.append(item["section"])

    grouped = {section: [] for section in sections}
    for item in items:
        grouped.setdefault(item["section"], []).append(item)

    out.update(ok=True, sections=sections,
               metrics=items, bySection=grouped,
               enabledCount=sum(1 for i in items if i["use"]))
    return True


def get_metrics(project_key):
    """이 프로젝트에서 쓸 수 있는 metric 전체와 지금 켜져 있는 것.

    **바꾸기 전에 먼저 읽어야 한다.** 변경은 key 로 지정하는데, 어떤 key 가 있는지는
    언어와 프로젝트 설정에 따라 다르다.
    """
    out = {"ok": False, "projectKey": project_key}
    status, data, failure = _call(
        METRICS_PATH_TEMPLATE.format(key=project_key), method="GET")
    if failure:
        out.update(failure)
        return out
    if status == 404:
        return _project_not_found(out, project_key, status)
    if status != 200:
        out.update(status=status,
                   message=f"metric 조회에 실패했습니다(HTTP {status}).")
        return out

    if not _metric_state(out, data):
        return out
    out["message"] = (f"metric {len(out['metrics'])}개 중 "
                      f"{out['enabledCount']}개가 켜져 있습니다.")
    return out


def set_metrics(project_key, uses):
    """여러 metric 의 사용 여부를 한 번에 바꾼다.

    ``uses`` 는 ``{"FUCYC": True, "FUNST": False}`` 다. **전체 교체가 아니다** -
    여기 없는 metric 은 그대로 둔다.

    서버가 한 트랜잭션으로 처리하므로 **전부 되거나 전부 안 된다.** 부분 적용을
    걱정하지 않아도 된다는 뜻이고, 실패 메시지도 그렇게 말해야 한다.
    """
    out = {"ok": False, "projectKey": project_key}
    if not uses:
        out.update(code="NO_CHANGES", message="바꿀 metric 을 하나 이상 지정해야 합니다.")
        return out

    payload = {"metrics": [{"metricKey": str(key), "enabled": bool(value)}
                           for key, value in uses.items()]}
    status, data, failure = _call(
        METRICS_PATH_TEMPLATE.format(key=project_key), payload=payload,
        method="PATCH",
        forbidden_message=("metric 설정 변경은 프로젝트 소유자만 할 수 있습니다(403). "
                           "이 프로젝트의 소유자에게 요청하세요."))
    if failure:
        out.update(failure)
        return out
    if status == 404:
        # 프로젝트가 없는 경우와 metric key 가 틀린 경우가 같은 404 로 온다.
        # 서버 메시지로 가른다 - 사용자가 할 일이 완전히 다르다.
        if "ProjectMetricMetadata" in json.dumps(data, ensure_ascii=False):
            out.update(code="UNKNOWN_METRIC", status=status,
                       message=("이 프로젝트에 없는 metric key 가 있습니다. "
                                "아무것도 바뀌지 않았습니다 - 먼저 조회해서 "
                                "정확한 key 를 확인하세요."))
        else:
            out.update(code="NOT_FOUND", status=status,
                       message=f"서버에 프로젝트 {project_key} 가 없습니다(404).")
        return out
    if status != 200:
        out.update(status=status,
                   message=(f"metric 변경에 실패했습니다(HTTP {status}). "
                            "한 트랜잭션이라 아무것도 바뀌지 않았습니다."))
        return out

    # v1 의 PATCH 는 본문 없이 200 만 돌려준다. 바뀐 뒤의 상태를 함께 보여주는 것이
    # 이 커맨드의 값이므로 여기서 한 번 더 읽는다 - 부르는 쪽에 두 번 부르라고
    # 시키면 언젠가 한쪽만 부른다.
    refreshed = get_metrics(project_key)
    if not refreshed.get("ok"):
        out.update(ok=True, status=status, changed=list(uses),
                   message=(f"metric {len(uses)}개를 바꿨습니다. "
                            "바뀐 뒤 상태는 읽지 못했습니다 - "
                            f"{refreshed.get('message') or '조회 실패'}"))
        return out

    for field in ("sections", "metrics", "bySection", "enabledCount"):
        out[field] = refreshed[field]
    out.update(ok=True, status=status, changed=list(uses))
    out["message"] = (f"metric {len(uses)}개를 바꿨습니다 · 이제 "
                      f"{out['enabledCount']}개가 켜져 있습니다.")
    return out


def get_project_status(project_key):
    """진행 상태와 **마지막으로 성공한 전체 분석**.

    로컬에는 이 값이 없다. 예전에 `agent.json` 의 `lastAnalyzedAt` 을 썼지만 그건
    플러그인이 돌린 분석만 셌고, C/C++ 의 `upload` 는 그것마저 갱신하지 않았다.
    "이 프로젝트가 마지막으로 분석된 게 언제냐" 에 모호하지 않게 답하는 것은
    서버의 revision 뿐이다.

    v0 의 `/projects/{key}/status` 는 이 답을 갖고 있지 않았다 - `ProjectStatusDto`
    에는 `status` 한 필드뿐이라 회차와 시각은 언제나 비어 있었다. v1 의 프로젝트
    상세가 `latestFinishedRevision` 을 함께 주면서 이제 실제로 채워진다.
    """
    detail = get_project_detail(project_key)
    out = {"ok": False, "projectKey": project_key}
    if not detail.get("ok"):
        out.update({k: v for k, v in detail.items() if k != "ok"})
        return out

    revision = detail.get("latestFinishedRevision") or {}
    finished = revision.get("finishedTime")
    out.update(ok=True,
               progressStage=detail.get("progressStage"),
               # 서버는 epoch millis 로 준다. 초로 맞춰 두어야 받는 쪽이 단위를
               # 다시 묻지 않는다.
               lastAnalyzedAt=(finished / 1000.0
                               if isinstance(finished, (int, float)) else None),
               lastRevisionSequence=revision.get("sequence"))
    return out
