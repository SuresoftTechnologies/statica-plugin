"""플러그인 진입점. 설치 없이 실행할 수 있도록 scripts/ 를 sys.path 에 올린다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from static_agent.cli import main  # noqa: E402


def _force_utf8():
    """표준 스트림을 UTF-8 로 고정한다.

    이 프로세스의 소비자(Claude Code)는 Node 기반이라 UTF-8 을 가정하지만,
    Windows 에서 파이프에 연결된 파이썬 스트림은 활성 코드페이지(예: CP949)를
    쓴다. 그대로 두면 한국어 메시지가 전부 깨지고, 특히 부트스트랩 안내처럼
    모델에게 그대로 전달되는 텍스트가 무의미해진다.

    reconfigure 는 Python 3.7+ 에만 있으므로 없으면 조용히 넘어간다.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    _force_utf8()
    sys.exit(main())
