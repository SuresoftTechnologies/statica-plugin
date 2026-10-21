"""플러그인 상태를 벤더와 무관하게 사용자별로 공유한다.

기본 경로: ~/.suresoft/data/plugins/static/state.json.
스킬과 훅 모두 공통 런타임의 기본값을 사용한다. 호스트의 PLUGIN_DATA와 설치
디렉터리에 의존하지 않는다.

프로젝트 경로가 키이며, 전역 슬롯이 OFF이면 모든 프로젝트에서 자동 분석을 끈다.
같은 사용자 계정의 다른 벤더에서도 이 설정을 공유한다.
"""
import json
import os
from pathlib import Path

GLOBAL_SLOT = "__global__"


def _data_dir():
    """모든 벤더가 공유하는 STATIC 실행 상태 디렉터리."""
    return Path.home() / ".suresoft" / "data" / "plugins" / "static"


# 진단·테스트용 명시적 재정의. 정상 스킬과 훅은 공통 기본값을 사용한다.
_state_dir_override = None


def set_state_dir(path):
    """CLI의 명시적 --state-dir 재정의. 빈 값은 무시한다."""
    global _state_dir_override
    text = str(path).strip() if path is not None else ""
    _state_dir_override = Path(text) if text else None


def state_file():
    override = os.environ.get("STATIC_AGENT_STATE")
    if override:
        return Path(override)
    if _state_dir_override is not None:
        return _state_dir_override / "state.json"
    return _data_dir() / "state.json"


def _load():
    path = state_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(data):
    p = state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _project_key(project_dir):
    return str(Path(project_dir)).rstrip("\\/").casefold()


def _slot(project_dir):
    return GLOBAL_SLOT if project_dir is None else _project_key(project_dir)


def _is_off(projects, slot):
    return bool((projects.get(slot) or {}).get("off", False))


def is_analysis_enabled(project_dir=None):
    """이 프로젝트에서 자동 분석이 켜져 있는지 본다.

    전역 슬롯은 오버라이드다 — 전역이 꺼져 있으면 어떤 프로젝트에서도 꺼진 것으로
    본다. ``--global`` 로 끈 사용자가 프로젝트별 설정 때문에 다시 켜지는 일이
    없어야 한다.
    """
    projects = _load().get("projects") or {}
    return not (_is_off(projects, GLOBAL_SLOT) or _is_off(projects, _slot(project_dir)))


def set_analysis_enabled(project_dir, enabled):
    """자동 분석을 켜거나 끈다. ``project_dir`` 가 None 이면 전역이다.

    전역으로 켜는 경우에는 모든 슬롯의 ``off`` 를 지운다 — 무엇이 껐든
    ``--global`` 로 켜면 실제로 다시 켜져야 한다.
    """
    data = _load()
    projects = data.setdefault("projects", {})
    slot = _slot(project_dir)
    if enabled and slot == GLOBAL_SLOT:
        for entry in projects.values():
            if isinstance(entry, dict):
                entry["off"] = False
    projects.setdefault(slot, {})["off"] = not enabled
    _save(data)
