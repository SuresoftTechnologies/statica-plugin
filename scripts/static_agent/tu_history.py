"""TU 를 마지막으로 분석한 시각. **우리 기록이지 분석기 산출물이 아니다.**

## 왜 따로 들고 있는가

예전에는 분석이 끝나면 그 TU 의 `tu.cache.json` 을 현재 시각으로 touch 했다.
우리는 mtime 으로 stale 을 판정하는데 분석기는 내용 해시로 판정해서, mtime 만
밀리고 내용은 그대로인 파일이 하나라도 있으면(브랜치 왕복, 되돌린 편집, 변경
없이 무조건 쓰는 에디터) 둘의 답이 갈리기 때문이다 — 우리는 "변경됨", 분석기는
"할 일 없음". 분석기가 건너뛰면 캐시를 다시 쓰지 않으므로 그 TU 는 **진짜 내용
변경이 올 때까지 매 응답마다 다시 분석 대상**이 됐다.

touch 는 그걸 풀었지만 남의 산출물에 손을 대는 방식이었다. 그래서 기준선을 우리
쪽으로 옮긴다. `tu.cache.json` 은 계속 읽는다 — "이 TU 에 어떤 소스가 들어갔나"는
거기밖에 없고 전처리에 딸려 온 헤더까지 그 목록에 있다. 바뀌는 것은 **비교 기준
하나**뿐이다.

## 그냥 매번 분석기에 넘기면 되지 않나

안 된다. 캐시 히트도 싸지 않다 (실측, analyzer-csa 5.0.0 · TU 1개):

    3.4초    벽시계
    86.8MB   디스크 쓰기 (rule.db 41.5MB 를 config 와 TU 디렉터리 양쪽에)
    2회      서버 호출 (project info · project config)

그중 "캐시라서 건너뛴다" 판정은 0.31초뿐이고 나머지 3초는 캐시든 아니든 매 실행
치르는 준비 비용이다. `-t` `-m` `-w` 는 상호 배타라 TU N개는 프로세스 N개이고,
준비 비용도 N번이다. TU 150개가 그 상태면 훅 예산 540초를 그것만으로 다 쓴다.

## 파일

`.staticdata/.app/tu.analyzed.json` — `agent.json` 옆, 워크스페이스마다 하나다.

`agent.json` 안에 넣지 않는 이유가 둘 있다. 첫째, `workspace.find_workspace_for`
가 커맨드와 훅마다 **모든 워크스페이스의** `agent.json` 을 읽어 `projectPath` 를
맞춰 본다 — 거기에 TU 맵이 들어가면 지금 작업과 무관한 프로젝트의 TU 수천 개까지
매번 파싱한다. 둘째, `agent.json` 은 잃으면 워크스페이스를 못 찾는 파일이라
(`AGENT_JSON_CORRUPT` 를 따로 둘 만큼 조심한다) 매 분석마다 다시 쓰는 고빈도
데이터와 한 파일에 두지 않는다.

키는 **워크스페이스 기준 상대경로**다. 워크스페이스를 옮겨도 살아남고, 절대경로
보다 짧아 TU 하나당 100 바이트쯤이다 (3000개 ≈ 330KB).
"""
import json
import os
import time
from pathlib import Path

from .workspace import read_json

REL = Path(".staticdata") / ".app" / "tu.analyzed.json"


def path_for(ws):
    return Path(ws) / REL


def key(ws, tu_dir):
    """워크스페이스 기준 상대경로. 구분자와 대소문자 차이를 지운다.

    분석기는 TU 디렉터리 이름을 대문자 hex 로 쓰지만 우리 쪽 철자가 어디서 오든
    같은 TU 로 읽혀야 한다. 상대경로를 만들지 못하면(다른 드라이브 등) 준 값을
    그대로 쓴다 — 여기서 예외를 내면 조회가 죽는다.
    """
    try:
        rel = Path(tu_dir).resolve().relative_to(Path(ws).resolve())
    except (ValueError, OSError):
        rel = Path(tu_dir)
    return str(rel).replace("\\", "/").casefold()


def read(ws):
    """{키: 시각}. 파일이 없거나 깨졌으면 빈 값이다.

    깨진 파일에서 죽지 않는다. 기록을 잃으면 그 TU 들이 한 번 더 분석될 뿐이고,
    그건 손해지 고장이 아니다.
    """
    data = read_json(path_for(ws))
    if not isinstance(data, dict):
        return {}
    return {k: float(v) for k, v in data.items()
            if isinstance(k, str) and isinstance(v, (int, float))
            and not isinstance(v, bool)}


def analyzed_at(ws, tu_dir, history=None):
    """이 TU 를 마지막으로 분석한 시각. 한 번도 없으면 None.

    기록이 없으면 `tu.cache.json` 의 mtime 으로 물러선다. **이사 경로다** — 이
    기능이 생기기 전의 워크스페이스에는 기록이 없고, 물러서지 않으면 플러그인을
    올리자마자 전체 재분석이 한 번 돈다. 한 번이라도 우리가 기록하면 그 뒤로는
    우리 값이 이긴다.
    """
    if history is None:
        history = read(ws)
    stamp = history.get(key(ws, tu_dir))
    if stamp is not None:
        return stamp
    try:
        return (Path(tu_dir) / "tu.cache.json").stat().st_mtime
    except OSError:
        return None


def now():
    """분석을 시작하기 **직전에** 찍을 시각.

    끝난 뒤의 시각을 쓰면 안 된다. 분석이 도는 동안 저장된 편집이 그 시각보다
    과거가 되어 영영 stale 로 잡히지 않는다 — 사용자가 방금 고친 코드가 검사되지
    않은 채로 남는다. 시작 시각을 쓰면 그 편집은 다음 실행이 잡는다.
    """
    return time.time()


def record(ws, stamps):
    """{TU 디렉터리: 시각} 을 기존 기록에 얹어 저장하고, 없어진 TU 는 지운다.

    **성공한 분석만 넘겨야 한다.** 실패까지 적으면 다음 실행이 재시도하지 못한다.

    정리는 지금 존재하는 TU 디렉터리를 기준으로 한다. 빌드가 바뀌면 TU 디렉터리
    이름(소스경로 해시)이 갈리므로, 정리하지 않으면 죽은 항목이 영영 쌓인다.
    """
    if not stamps:
        return {}
    from .changes import tu_dirs          # 순환 참조를 피해 여기서 부른다

    history = read(ws)
    for tu_dir, stamp in stamps.items():
        history[key(ws, tu_dir)] = float(stamp)
    alive = {key(ws, tu) for tu in tu_dirs(ws)}
    history = {k: v for k, v in history.items() if k in alive}
    _write(ws, history)
    return history


def _write(ws, history):
    """원자적으로 쓴다.

    훅과 슬래시 커맨드가 겹칠 수 있고, 쓰다 끊긴 JSON 은 기록 전체를 날린다.
    임시 파일에 쓰고 바꿔치는 것이 그 창을 없앤다.
    """
    path = path_for(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    os.replace(tmp, path)
    return path
