import json
from pathlib import Path

from .errors import PluginError
from .paths import works_root

AGENT_JSON_REL = Path(".staticdata") / ".app" / "agent.json"
APP_DATA_REL = Path(".staticdata") / ".app" / "app.data.json"


def read_json(path):
    # utf-8-sig 로 읽는다. 여기로 들어오는 파일 중 app.data.json,
    # module.capture.json, tu.cache.json, analyze.failed.json 은 분석기가 쓴 것이라
    # BOM 이 붙어도 우리가 막을 수 없다. BOM 이 없으면 utf-8 과 결과가 같으므로,
    # 우리가 쓰는 agent.json 을 읽는 데도 아무 차이가 없다.
    # (쓰기는 그대로 utf-8 — 우리가 소유한 파일에 BOM 을 새로 붙이지는 않는다.)
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def read_agent_json(ws):
    return read_json(Path(ws) / AGENT_JSON_REL)


# agent.json 이 있는데 읽히지 않을 때의 오류 코드. "워크스페이스가 없다" 와 반드시
# 구별되어야 한다 — 없다고 답하면 호출한 쪽이 "부트스트랩을 시작하세요" 로 안내하고,
# 그 말을 따르면 같은 프로젝트에 워크스페이스가 둘, wrapper 가 둘이 된다.
AGENT_JSON_CORRUPT = "AGENT_JSON_CORRUPT"


def _agent_json_corrupt(path, detail):
    return PluginError(
        AGENT_JSON_CORRUPT,
        f"워크스페이스의 agent.json 을 읽을 수 없습니다: {path} ({detail})",
        "이 파일을 손으로 고쳤다면 JSON 문법을 바로잡고, 되살릴 수 없으면 지운 뒤 "
        "다시 시도하세요. 부트스트랩을 새로 시작하지는 마세요: 같은 프로젝트에 "
        "워크스페이스가 둘 생깁니다.")


def _read_agent_json_strict(ws):
    """조회용 agent.json 읽기. 파일이 없으면 None, 있는데 못 읽으면 예외.

    `snapshot._read_index` 와 같은 규율이다. `read_json` 은 어떤 실패든 None 으로
    뭉개는데, 조회 경로에서 그것은 "이 워크스페이스는 없는 셈 치자" 와 같은 말이라
    사람이 손으로 고치다 깨뜨린 파일 하나가 워크스페이스를 통째로 숨겨 버린다.
    """
    path = Path(ws) / AGENT_JSON_REL
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise _agent_json_corrupt(path, type(e).__name__) from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise _agent_json_corrupt(path, e) from e
    if not isinstance(data, dict):
        raise _agent_json_corrupt(path, "최상위가 객체가 아닙니다")
    return data


def write_agent_json(ws, data):
    return write_json(Path(ws) / AGENT_JSON_REL, data)


def read_app_data(ws):
    return read_json(Path(ws) / APP_DATA_REL)


def project_key(ws):
    data = read_app_data(ws) or {}
    return data.get("projectKey") or None


# 부트스트랩 진행 상태. 워크스페이스는 만들어진 순간부터 wrapper·치환·빌드·캡처
# 검증·서버 등록을 다 마칠 때까지 "분석해서는 안 되는" 상태로 존재한다 — 그 사이를
# 구분하지 못하면 캡처가 비어 있는 워크스페이스를 분석하려 들게 된다.
STATUS_BOOTSTRAPPING = "bootstrapping"
STATUS_READY = "ready"
_STATUS_KEY = "status"


def status(agent_json):
    """명시된 부트스트랩 상태만 허용한다. 누락·오류를 ready 로 간주하지 않는다."""
    value = agent_json.get(_STATUS_KEY) if isinstance(agent_json, dict) else None
    if value not in (STATUS_BOOTSTRAPPING, STATUS_READY):
        raise PluginError(AGENT_JSON_CORRUPT,
                          "agent.json의 status는 bootstrapping 또는 ready여야 합니다.")
    return value


def set_status(agent_json, value):
    """상태를 채운 사본을 돌려준다. 원본은 건드리지 않는다."""
    data = dict(agent_json or {})
    data[_STATUS_KEY] = value
    return data


def build_command(agent_json):
    """agent.json 에서 재빌드 명령을 꺼낸다. 없으면 None."""
    return (agent_json or {}).get("buildCommand") or None


def wrapper_dir(agent_json):
    """이 워크스페이스의 wrapper 디렉터리. 없으면 None.

    치환이 가리켜야 하는 경로이고, 커맨드라인 치환(A)을 쓴 프로젝트라면
    `buildCommand` 안에도 이 경로가 들어 있어야 한다 (`bootstrap.finish` 가 본다).
    """
    value = (agent_json or {}).get("wrapperDir")
    return value if isinstance(value, str) and value.strip() else None


def _norm(path):
    return str(Path(path)).rstrip("\\/").casefold()


# 재빌드를 이미 시도해 본 신규 파일들. 빌드가 끝내 캡처하지 못하는 소스(빌드에서
# 제외된 파일, 벤더링된 서드파티 .c, 테스트 픽스처 …)는 영원히 "신규"로 남는데,
# 그때마다 전체 재빌드를 돌리면 매 응답이 몇 분씩 걸린다. 한 번 시도했으면 기록해
# 두고, 정말 처음 보는 파일이 생겼을 때만 다시 빌드한다.
#
# 기록은 {정규화한 경로: {attempts, mtime, rebuildOk}} 다. "시도했다"가 아니라
# "무슨 일이 있었다"를 남기는 것이 요점이다 — 성공한 빌드가 끝내 잡지 못한 파일과,
# 애초에 빌드가 깨져서 잡히지 못한 파일은 운명이 달라야 한다.
REBUILD_ATTEMPTED_KEY = "rebuildAttemptedFiles"

# 재빌드가 실패한 파일을 다시 시도해 볼 횟수의 상한.
#
# 빌드 실패는 대개 일시적이다 — 에이전트가 방금 그 파일에 컴파일 오류를 넣었고,
# 다음 응답에서 고친다. 그래서 한 번 실패했다고 영영 포기하면 안 된다. 반대로
# 영영 고쳐지지 않는 빌드에 매 Stop 훅마다 전체 `make -B` 를 물리면 응답마다 몇
# 분씩 날아간다. 그 사이를 끊는 값이라 작아야 한다: 세 번이면 "방금 넣은 오류를
# 고칠 기회"로는 넉넉하고, 깨진 빌드에 물리는 대가로는 유한하다.
MAX_REBUILD_ATTEMPTS = 3

# 레코드 안쪽 필드 이름. agent.json 의 스키마는 이 모듈이 소유한다 — 바깥에서
# 이 문자열을 알 필요가 없도록, 판정은 전부 아래 함수들이 한다.
_ATTEMPTS = "attempts"
_MTIME = "mtime"
_REBUILD_OK = "rebuildOk"


def _mtime_of(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def _record(attempts, mtime, rebuild_ok):
    return {_ATTEMPTS: attempts, _MTIME: mtime, _REBUILD_OK: rebuild_ok}


def _records(agent_json):
    """재빌드 기록을 {정규화한 경로: 레코드} 로 읽는다.

    기록이 없으면 빈 객체로 시작한다. 기록은 객체 형식만 허용하며,
    개별 레코드의 잘못된 값은 결과 미상으로 취급한다.
    """
    raw = (agent_json or {}).get(REBUILD_ATTEMPTED_KEY, {})
    if not isinstance(raw, dict):
        raise PluginError(AGENT_JSON_CORRUPT,
                          "agent.json의 rebuildAttemptedFiles는 객체여야 합니다.")
    out = {}
    for path, rec in raw.items():
        if not isinstance(path, str):
            continue
        if not isinstance(rec, dict):
            rec = {}
        attempts = rec.get(_ATTEMPTS)
        mtime = rec.get(_MTIME)
        ok = rec.get(_REBUILD_OK)
        out[_norm(path)] = _record(
            attempts if isinstance(attempts, int) and attempts > 0 else 1,
            float(mtime) if isinstance(mtime, (int, float)) else None,
            ok if isinstance(ok, bool) else None)
    return out


def _wants_rebuild(record, path):
    """이 신규 파일 하나 때문에 재빌드를 돌릴 만한가."""
    if record is None:
        return True                             # 시도해 본 적이 없다
    mtime = _mtime_of(path)
    if record[_MTIME] is not None and mtime is not None and mtime != record[_MTIME]:
        return True                             # 지난 시도 뒤로 사용자가 고쳤다
    if record[_REBUILD_OK]:
        # 빌드가 성공했는데도 캡처되지 않았다 = 애초에 빌드에 속하지 않는 소스다.
        # 다시 빌드해도 결과는 같으므로 영구히 억제하는 것이 옳다.
        return False
    # 실패했거나 결과를 모르거나 — 정해진 횟수까지만 더 해 본다.
    return record[_ATTEMPTS] < MAX_REBUILD_ATTEMPTS


def needs_rebuild_for(agent_json, new_files):
    """재빌드를 돌려 볼 만한 신규 파일이 하나라도 있으면 True."""
    records = _records(agent_json)
    return any(_wants_rebuild(records.get(_norm(p)), p) for p in new_files)


# 포기한 이유. 사용자가 할 일이 갈리므로 부르는 쪽이 반드시 구분해서 말해야 한다.
OUTSIDE_BUILD = "outsideBuild"   # 빌드는 성공했는데 컴파일조차 하지 않았다
BUILD_FAILED = "buildFailed"     # 빌드가 깨져서 못 잡았고, 재시도 횟수를 다 썼다


def suppressed_new_files(agent_json, new_files):
    """다시 빌드해도 소용없다고 판정해 포기한 신규 파일들.

    ``needs_rebuild_for`` 의 여집합이다. 이 파일들은 캡처되지 않은 채로 남고
    따라서 분석되지 않는다 — 조용히 지나가면 안 되므로 호출한 쪽이 사람에게 알린다.
    """
    records = _records(agent_json)
    return [p for p in new_files if not _wants_rebuild(records.get(_norm(p)), p)]


def suppressed_by_reason(agent_json, new_files):
    """포기한 파일을 이유별로 나눈다 — ``{OUTSIDE_BUILD: [...], BUILD_FAILED: [...]}``

    한 문장으로 뭉치면 안 된다. 두 경우는 **사용자가 할 일이 정반대**다.

        빌드 밖 소스   그냥 두면 된다. 이 프로젝트가 애초에 빌드하지 않는 파일이다.
        빌드 실패      빌드를 고쳐야 한다. 고치면 다음 실행이 다시 잡는다.

    실측(GNU hello + gnulib): 서브모듈로 받아온 소스 3479개가 한꺼번에 여기로
    잡혔다. 그때 "빌드가 캡처하지 못했습니다" 라고만 말하면 읽는 사람은 자기 빌드가
    깨진 줄 알고 고칠 곳을 찾아 나선다 — 고칠 것이 없는데도.
    """
    records = _records(agent_json)
    out = {OUTSIDE_BUILD: [], BUILD_FAILED: []}
    for path in new_files:
        record = records.get(_norm(path))
        if record is None or _wants_rebuild(record, path):
            continue
        # 성공한 빌드가 안 잡았으면 빌드 밖이고, 그 밖은 전부 재시도 소진이다.
        out[OUTSIDE_BUILD if record[_REBUILD_OK] else BUILD_FAILED].append(path)
    return out


def mark_rebuild_attempted(ws, agent_json, new_files, rebuild_ok):
    """이번 재빌드가 다룬 신규 파일들을, 그 재빌드의 성패와 함께 기록한다.

    ``rebuild_ok`` 는 이 파일들과 함께 돌아간 재빌드가 성공했는지다. 성패를 남기지
    않으면 "빌드가 깨져서 못 잡은 파일"과 "빌드 밖의 파일"을 구별할 수 없고, 전자를
    영영 분석하지 않게 된다.

    실제로 돌아간 재빌드만 여기로 와야 한다. 시작조차 못 한 빌드(예산 부족,
    buildCommand 없음)를 실패로 적으면 "빌드가 이 파일을 못 잡았다"고 거짓을
    기록하는 것이고, 그 거짓이 쌓여 파일을 은퇴시킨다.

    갱신된 agent.json 을 돌려준다 — 호출한 쪽은 반드시 이 반환값을 이어서 써야
    한다. 안 그러면 뒤따르는 저장이 낡은 사본을 써서 방금 쓴 기록을
    도로 지워버린다.
    """
    agent_json = dict(agent_json or {})
    records = _records(agent_json)
    for path in new_files:
        key = _norm(path)
        previous = records.get(key)
        if previous and previous[_REBUILD_OK] and not rebuild_ok:
            # 이 파일은 이미 "성공한 빌드조차 잡지 못했다" = 빌드 밖의 소스라는
            # 판정을 받았다. 그 판정을 뒤집는 것은 이 파일에 대한 새 증거뿐인데,
            # 다른 파일 때문에 돌다가 깨진 빌드는 이 파일에 대해 아무 말도 하지
            # 않는다. 기록을 통째로 그대로 둔다 — 횟수도 mtime 도 건드리지 않아야,
            # 사용자가 이 파일을 고쳤을 때 mtime 규칙이 제대로 다시 열어 준다.
            continue
        attempts = (previous[_ATTEMPTS] if previous else 0) + 1
        records[key] = _record(attempts, _mtime_of(path), bool(rebuild_ok))
    agent_json[REBUILD_ATTEMPTED_KEY] = {k: records[k] for k in sorted(records)}
    write_agent_json(ws, agent_json)
    return agent_json


def iter_workspaces():
    root = works_root()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))


def resolve_path(path):
    """경로를 절대 경로로 편다 (심볼릭 링크·정션·상대 경로·8.3 단축 이름).

    워크스페이스 조회는 경로 **문자열** 비교다. 한쪽만 펴면 두 철자가 갈리고,
    갈린 두 철자는 서로를 부정한다: Stop 훅은 `os.getcwd()`(정션 철자)로 "워크스페이스가
    없다"며 매 턴 부트스트랩을 요구하고, `bootstrap-begin` 은 편 철자로 "이미 있다"며
    거절한다. 어느 명령도 그 교착을 깨지 못한다.

    그래서 편다/안 편다를 호출자마다 정하지 않는다 — 조회 지점 한 곳에서 양쪽을
    똑같이 펴고, 그 결과만 비교한다.

    풀 수 없는 경로는 원래 값을 그대로 돌려준다. 여기서 예외를 내면 조회가 죽는다.
    """
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


def find_workspace_for(project_dir):
    """agent.json 의 projectPath 로 워크스페이스를 역조회한다.

    저장된 철자와 물어보는 철자를 **둘 다** 편 뒤에 비교한다. 저장된 값은 이미
    펴져 있는 것이 보통이지만(`bootstrap.begin` 이 그렇게 넣는다), 그 필드가
    펴지기 전에 만들어진 워크스페이스와 손으로 적어 넣은 값이 있다.

    agent.json 이 있는데 읽히지 않는 워크스페이스는 조용히 건너뛰지 않는다.
    다만 곧바로 죽지도 않는다 — 찾는 프로젝트가 멀쩡한 다른 워크스페이스에
    있다면 그 조회는 성공해야 한다. 남의 워크스페이스가 깨진 것 때문에 이
    프로젝트의 분석이 멈출 이유는 없다. 끝까지 못 찾았을 때만 올린다.
    """
    target = _norm(resolve_path(project_dir))
    corrupt = None
    for ws in iter_workspaces():
        try:
            agent = _read_agent_json_strict(ws)
        except PluginError as e:
            corrupt = corrupt or e
            continue
        stored = (agent or {}).get("projectPath")
        if not isinstance(stored, str) or not stored.strip():
            continue
        if _norm(resolve_path(stored)) == target:
            return ws
    if corrupt is not None:
        raise corrupt
    return None


def free_workspace_name(base):
    """이름이 이미 쓰이면 _2, _3 … 을 붙인다 (기존 스킬과 동일한 규칙)."""
    root = works_root()
    if not (root / base).exists():
        return base
    n = 2
    while (root / f"{base}_{n}").exists():
        n += 1
    return f"{base}_{n}"
