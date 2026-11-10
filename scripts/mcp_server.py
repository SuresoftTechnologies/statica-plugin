"""STATICA MCP 서버 진입점 (stdio). run.py 와 같이 설치 없이 실행된다.

    python scripts/mcp_server.py

클라이언트 설정은 플러그인 루트의 .mcp.json 이 맡는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from statica_mcp.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
