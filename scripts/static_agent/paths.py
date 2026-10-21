import os
from pathlib import Path

from .errors import PluginError

ENV_INSTALL = "ARACHNE_INSTALL_PATH"

# Arachne 는 OS 별로 패키지가 따로 있고, 둘의 차이는 실행 파일 확장자뿐이다
# (실측: linux_x64 tar 의 bin/ 에 analyzer-csa · analyzer-plugin · wrapper ·
# wrapper-forge · wrapper.spec — 이름은 같고 `.exe` 만 없다).
#
# 그래서 확장자를 아는 곳을 `bin_path` 하나로 묶는다. 호출하는 쪽은 언제나
# **확장자 없는 이름**을 넘긴다 — 그러지 않으면 리눅스 지원이 호출 지점마다
# 흩어지고, 한 군데만 빠뜨려도 그 경로가 리눅스에서만 조용히 깨진다.
EXE_SUFFIX = ".exe" if os.name == "nt" else ""


def is_windows():
    """지금 Windows 인가. 실행 파일 확장자 말고도 갈리는 것이 있다(출력 인코딩)."""
    return os.name == "nt"


def install_root():
    """Arachne 설치 루트. 환경변수 값 끝의 역슬래시를 제거한다."""
    raw = (os.environ.get(ENV_INSTALL) or "").strip().strip('"')
    if not raw:
        raise PluginError(
            "NO_INSTALL_PATH",
            f"{ENV_INSTALL} 환경변수가 설정되어 있지 않습니다.",
            "Arachne를 설치하거나 환경변수를 설정한 뒤 다시 시도하세요.",
        )
    root = Path(raw.rstrip("\\/"))
    if not root.is_dir():
        raise PluginError("INSTALL_PATH_NOT_FOUND",
                          f"{ENV_INSTALL} 경로를 찾을 수 없습니다: {root}")
    return root


def bin_path(name):
    """`bin/` 아래 실행 파일 경로. **확장자 없는 이름**을 넘겨라 (`analyzer-csa`).

    Windows 면 `.exe` 를 붙이고 리눅스면 그대로 둔다.
    """
    return install_root() / "bin" / (name + EXE_SUFFIX)


def works_root():
    return install_root() / "works"


def conf_path(name):
    return install_root() / "conf" / name
