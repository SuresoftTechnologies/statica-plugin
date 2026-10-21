"""보고서 생성의 비동기 흐름 — 요청, 기다리기, 받기.

서버는 접수만 하고 바로 돌아온다. 실제 생성은 뒤에서 돌고, 진행 상태는
`WAIT · INPROGRESS · CANCEL · ERROR · FINISH` 로 바뀐다. 그래서 사람이 쓰려면
누군가 기다려 줘야 하는데, 그 기다림을 여기 둔다.

**이 모듈은 훅에서 부르지 않는다.** 훅은 사용자의 턴을 막지 않는 것이 규칙이고
(`statica-analyze-overview`), 보고서는 분 단위로 걸릴 수 있다. 커맨드 전용이다.
"""
import time
from pathlib import Path

from . import server_api

# 커맨드에서만 도는 값이라 훅 예산과 무관하다. 그래도 상한은 반드시 있어야 한다 -
# 서버가 상태를 영영 바꾸지 않는 경우(생성기가 죽는 등)에 갇히면, 사용자는
# 커맨드가 멈춘 것인지 서버가 느린 것인지 구분할 수 없다.
DEFAULT_INTERVAL_SECONDS = 2
DEFAULT_TIMEOUT_SECONDS = 600

# 끝을 뜻하는 상태들. 이 둘 중 어느 것도 아니면 기다린다 - 서버가 새 상태를
# 늘려도 모르는 값에 갇히지 않고 상한에 걸려 빠져나온다.
DONE = "FINISH"
FAILED = {"ERROR": ("REPORT_FAILED", "서버가 보고서 생성에 실패했습니다."),
          "CANCEL": ("REPORT_CANCELLED", "보고서 생성이 취소되었습니다.")}

# 저장 위치. 저장소 안이라 사용자가 바로 열거나 첨부할 수 있다. 커맨드가
# .gitignore 등록을 함께 안내한다.
REPORTS_REL = Path(".static") / "reports"


def _sleep(seconds):
    """테스트가 갈아끼울 수 있도록 한 겹 둔다."""
    time.sleep(seconds)


def wait_for_report(project_key, interval=DEFAULT_INTERVAL_SECONDS,
                    timeout=DEFAULT_TIMEOUT_SECONDS):
    """FINISH 가 될 때까지 상태를 되묻는다.

    끝나는 길은 넷이다: FINISH, ERROR, CANCEL, 그리고 상한 초과. 어느 쪽이든
    **반드시 끝난다** — 모르는 상태가 와도 상한에 걸린다.
    """
    out = {"ok": False, "projectKey": project_key}
    waited = 0
    last = None
    while True:
        current = server_api.get_report_status(project_key)
        if not current.get("ok"):
            current["projectKey"] = project_key
            return current

        last = current.get("status")
        if last == DONE:
            return {"ok": True, "projectKey": project_key, "status": DONE,
                    "waitedSeconds": waited}
        if last in FAILED:
            code, message = FAILED[last]
            out.update(code=code, status=last, waitedSeconds=waited, message=message)
            return out
        if waited >= timeout:
            break

        _sleep(interval)
        waited += interval

    out.update(code="REPORT_TIMEOUT", status=last, waitedSeconds=waited,
               message=(f"{timeout}초 안에 보고서가 완성되지 않았습니다 "
                        f"(마지막 상태 {last}). 서버에서 계속 만들고 있을 수 있으니 "
                        "웹 UI 의 Outputs 에서 확인하세요."))
    return out


def destination(project_dir, project_key):
    """저장할 파일 경로. 같은 프로젝트를 여러 번 받아도 덮어쓰지 않게 번호를 붙인다."""
    folder = Path(project_dir) / REPORTS_REL
    base = f"{project_key}_report"
    candidate = folder / f"{base}.zip"
    index = 2
    while candidate.exists():
        candidate = folder / f"{base}_{index}.zip"
        index += 1
    return candidate


def run_report(project_dir, project_key, file_format, kinds, out_path=None,
               interval=DEFAULT_INTERVAL_SECONDS, timeout=None):
    """요청 → 기다리기 → 받기. 커맨드가 부르는 하나의 입구다.

    중간에 실패해도 **어디까지 갔는지** 알려 준다. 생성은 됐는데 다운로드만
    실패한 경우와 생성 자체가 안 된 경우는 사용자가 할 일이 다르기 때문이다.
    """
    # CLI 는 값을 안 주면 None 을 넘긴다. 여기서 기본값으로 되돌리지 않으면
    # 상한 비교에서 터진다.
    timeout = DEFAULT_TIMEOUT_SECONDS if timeout is None else timeout

    requested = server_api.generate_report(project_key, file_format, kinds)
    if not requested.get("ok"):
        requested["stage"] = "request"
        return requested

    waited = wait_for_report(project_key, interval=interval, timeout=timeout)
    if not waited.get("ok"):
        waited.update(stage="wait", reportId=requested.get("reportId"),
                      revisionSequence=requested.get("revisionSequence"))
        return waited

    dest = Path(out_path) if out_path else destination(project_dir, project_key)
    saved = server_api.download_report(project_key, dest)
    saved["stage"] = "download"
    saved.update(reportId=requested.get("reportId"),
                 revisionSequence=requested.get("revisionSequence"),
                 format=requested.get("format"),
                 kinds=requested.get("kinds"),
                 kindNames=requested.get("kindNames"),
                 waitedSeconds=waited.get("waitedSeconds"))
    if saved.get("ok"):
        saved["stage"] = "done"
    return saved
