"""사용자 프로젝트 파일을 고치기 전에 원본을 보관하고, 실패하면 되돌린다.

원본은 프로젝트가 아니라 **워크스페이스 안에** 둔다. 사용자 저장소에 `.bak`
파일을 흩뿌리지 않기 위해서다.

되돌리기 실패는 이 플러그인에서 가장 나쁜 결말이다 — 사용자 프로젝트가 고쳐진
채 남는다. 그래서 restore 는 실패를 삼키지 않고 어떤 파일이 어떻게 실패했는지
그대로 보고한다.
"""
import hashlib
import json
import shutil
from pathlib import Path

SNAPSHOT_REL = Path(".staticdata") / ".app" / "snapshot"
_INDEX = "index.json"


class _IndexCorrupt(Exception):
    """인덱스 파일이 있는데 읽거나 파싱할 수 없다.

    파일이 아예 없는 것("아직 스냅샷한 적 없음")과는 다른 상태다 — 있어야 할
    기록을 잃어버린 것이라 값을 지어내면 안 된다.
    """


def _dir(ws):
    return Path(ws) / SNAPSHOT_REL


def _key(path):
    return hashlib.md5(str(Path(path)).casefold().encode("utf-8")).hexdigest()


def _read_index(ws):
    """스냅샷 인덱스를 읽는다.

    인덱스 파일이 없으면 "아직 스냅샷한 적 없음" 이라는 뜻이므로 빈 딕셔너리를
    돌려준다. 파일은 있는데 읽을 수 없거나, 파싱은 되어도 모양이 딕셔너리가
    아니면 그건 손상이다 — 스냅샷이 있었는지 없었는지 알 수 없는 위험한
    상태이므로 조용히 `{}` 로 뭉개지 않고 `_IndexCorrupt` 를 던진다.
    """
    path = _dir(ws) / _INDEX
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise _IndexCorrupt(f"스냅샷 인덱스를 읽을 수 없습니다: {path} ({type(e).__name__})") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise _IndexCorrupt(f"스냅샷 인덱스가 손상되었습니다: {path} ({e})") from e
    if not isinstance(data, dict):
        raise _IndexCorrupt(f"스냅샷 인덱스 형식이 이상합니다 (딕셔너리가 아님): {path}")
    return data


def _write_index(ws, index):
    """인덱스를 원자적으로 쓴다.

    빌드 도중 프로세스가 죽는 것(Ctrl+C, 빌드 스텝이 CLI 를 죽임, OOM)은 이
    플러그인이 흔히 겪는 일이다. 임시 파일에 다 쓴 뒤 교체해야 그 시점에
    죽어도 기존 인덱스가 절반만 쓰인 채로 남지 않는다. `state.py` 의
    `_save` 와 같은 패턴이다.
    """
    d = _dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    target = d / _INDEX
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)


def take(ws, files):
    """편집 전 원본을 보관한다. 이미 보관된 파일은 덮어쓰지 않는다.

    이미 보관된 것을 덮어쓰면 두 번째 편집 시도 때 '원본' 이 첫 편집 결과로
    바뀌어 되돌리기가 무의미해진다.

    인덱스가 손상되어 있으면 이 함수는 `_IndexCorrupt` 를 그대로 던진다 —
    일부러 잡지 않는다. 스냅샷을 남길 수 있다고 보장할 수 없는 상태에서
    "성공했다"는 결과 딕셔너리를 돌려주면 호출자를 속이는 셈이다. 실패-안전
    계약(예외를 삼키고 상태를 보고하는 것)은 `restore()` 에만 있다.
    """
    index = _read_index(ws)
    d = _dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    entries = []
    for raw in files:
        path = Path(raw)
        key = _key(path)
        if key in index:
            entries.append(dict(index[key], skipped=True))
            continue
        record = {"path": str(path), "saved": f"{key}.bin", "existed": path.is_file()}
        if record["existed"]:
            shutil.copy2(path, d / record["saved"])
        index[key] = record
        entries.append(record)
    _write_index(ws, index)
    return {"count": len(index), "entries": entries}


def restore(ws):
    """보관해 둔 원본으로 되돌린다. 실패한 파일은 숨기지 않고 보고한다.

    인덱스 자체를 읽을 수 없는 경우는 "복구할 파일이 하나도 없다" 가 아니라
    "무엇을 복구해야 하는지 알 수 없다" 는 뜻이다. 이걸 `restored: 0, ok: True`
    로 보고하면 호출자가 아무 문제 없다고 믿고 워크스페이스를 지워버릴 수
    있다 — 백업 `.bin` 이 아직 디스크에 남아 있는데도. 그래서 이 경우는 반드시
    `ok: False` 로, 그리고 보관 디렉터리 위치와 (있다면) 남아 있는 백업 파일
    이름을 메시지에 실어 사람이 손으로라도 복구할 수 있게 한다.
    """
    d = _dir(ws)
    try:
        index = _read_index(ws)
    except _IndexCorrupt as e:
        blobs = sorted(p.name for p in d.glob("*.bin")) if d.is_dir() else []
        message = f"{e} 프로젝트 파일이 고쳐진 채로 남아 있을 수 있습니다."
        if blobs:
            message += (f" 원본 백업 {len(blobs)}개가 아직 {d} 에 있으니 "
                        f"손으로 복구하세요: {', '.join(blobs)}")
        else:
            message += f" 보관 디렉터리를 직접 확인하세요: {d}"
        return {"ok": False, "restored": 0, "failed": [], "message": message}

    result = {"ok": True, "restored": 0, "failed": [], "message": ""}
    if not index:
        result["message"] = "되돌릴 스냅샷이 없습니다."
        return result

    for record in index.values():
        path = Path(record.get("path", ""))
        try:
            if record.get("existed"):
                saved = d / record.get("saved", "")
                if not saved.is_file():
                    raise FileNotFoundError(f"보관본이 없습니다: {saved}")
                shutil.copy2(saved, path)
            elif path.exists():
                path.unlink()
            result["restored"] += 1
        except OSError as e:
            result["ok"] = False
            result["failed"].append({"path": str(path), "error": f"{type(e).__name__}: {e}"})

    if result["ok"]:
        result["message"] = f"프로젝트 파일 {result['restored']}개를 원래대로 되돌렸습니다."
    else:
        result["message"] = (
            f"{len(result['failed'])}개 파일을 되돌리지 못했습니다. "
            f"보관본은 {d} 에 그대로 있으니 직접 복구하세요.")
    return result


def discard(ws):
    """보관본을 지운다. 부트스트랩이 성공했을 때만 부른다."""
    shutil.rmtree(_dir(ws), ignore_errors=True)
