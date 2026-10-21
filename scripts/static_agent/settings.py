import json
from collections import namedtuple
from pathlib import Path

from .errors import PluginError
from .paths import conf_path

ServerSetting = namedtuple("ServerSetting", "server access_key")


def read_server_setting(path=None):
    """conf/server.setting.json 을 읽는다. accessKey는 어떤 메시지에도 넣지 않는다."""
    p = Path(path) if path else conf_path("server.setting.json")
    try:
        # utf-8-sig: 이 파일은 Arachne 가 쓴다 — BOM 을 붙일지 말지는 우리 소관이
        # 아니다. utf-8-sig 는 BOM 이 있으면 벗기고 없으면 utf-8 과 똑같이 읽는다.
        # 그냥 utf-8 로 읽으면 BOM 이 앞에 남아 json 파싱이 깨지고, 훅은 설정
        # 실패를 "막지 않는다"로 처리하므로 자동 분석이 소리 없이 꺼진다.
        data = json.loads(p.read_text(encoding="utf-8-sig", errors="replace"))
    except FileNotFoundError:
        raise PluginError(
            "NO_SERVER_SETTING",
            f"서버 설정 파일이 없습니다: {p}",
            "Arachne 설정에서 서버 주소와 AccessKey를 등록하세요.",
        )
    except (OSError, json.JSONDecodeError) as e:
        raise PluginError("BAD_SERVER_SETTING", f"서버 설정을 읽을 수 없습니다: {p} ({e})")

    server = (data.get("server") or "").rstrip("/")
    access_key = data.get("accessKey") or ""
    if not server:
        raise PluginError("NO_SERVER_URL", f"서버 설정에 server 값이 없습니다: {p}",
                          "Arachne 설정에서 서버 주소를 등록하세요.")
    if not access_key:
        raise PluginError("NO_ACCESS_KEY", f"서버 설정에 accessKey가 없습니다: {p}",
                          "Arachne 설정에서 AccessKey를 등록하세요.")
    return ServerSetting(server, access_key)
