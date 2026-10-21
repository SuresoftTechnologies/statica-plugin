"""빌드가 실제로 wrapper 를 타고 캡처를 남겼는지 판정한다.

빌드가 성공해도 캡처가 없을 수 있다 — 치환이 먹지 않아 원본 컴파일러로 빌드된
경우다. 이건 아무도 에러를 내지 않아서 조용히 지나가고, 그 결과 분석할 것이
없는 워크스페이스가 남는다. 부트스트랩은 반드시 이걸 확인해야 한다.
"""
from pathlib import Path

from .changes import iter_linking_objects, module_dirs


def summarize(ws):
    """캡처 결과 요약. `ok` 는 '분석할 것이 생겼는가' 를 뜻한다."""
    ws = Path(ws)
    modules = module_dirs(ws)
    sources = 0
    for _module, obj in iter_linking_objects(ws):
        if obj.get("sourceFile"):
            sources += 1

    result = {
        "ok": bool(modules) and sources > 0,
        "modules": len(modules),
        "sources": sources,
        "moduleNames": [m.name for m in modules],
    }
    if result["ok"]:
        result["message"] = f"모듈 {result['modules']}개, 소스 {sources}개가 캡처되었습니다."
    elif not modules:
        result["message"] = (
            "캡처된 모듈이 없습니다. 빌드가 wrapper 를 거치지 않았을 가능성이 높습니다. "
            "치환이 실제로 적용됐는지 확인하세요.")
    else:
        result["message"] = (
            f"모듈 {result['modules']}개가 있으나 캡처된 소스가 없습니다. "
            "빌드가 wrapper 를 거치지 않았을 가능성이 높습니다.")
    return result
