"""wrapper-forge 가 받아들이는 ide/compiler 어휘.

`wrapper-forge add --help` 의 출력을 그대로 옮긴 것이다. 폐쇄 집합이므로
exe 를 부르기 전에 여기서 거른다 — 잘못된 조합으로 exe 를 부르면 에러 메시지가
사람이 읽기 어렵고, 워크스페이스를 이미 만든 뒤라 정리 비용이 든다.
"""
from .errors import PluginError

IDE_COMPILERS = {
    "ccs": ("cl2000", "c6000"),
    "microchips": ("xc8_avr", "xc8", "xc16", "xc32", "arm_gcc", "avr8", "avr32"),
    "mplab": ("xc8_avr", "xc8", "xc16", "xc32", "arm_gcc", "avr8", "avr32"),
    "stm32cubeide": ("arm_gcc",),
    "xilinx": ("arm_gcc", "arm64_gcc", "mb_gcc"),
    "gnu": ("gcc",),
    "visualstudio": ("cl",),
    "llvm": ("clang",),
    "codewarrior": ("mwccmcf", "mwcceppc", "gcc"),
    "aurix": ("cctc", "gcc"),
}


def known_ides():
    return tuple(sorted(IDE_COMPILERS))


def validate(ide, compiler):
    """유효하지 않으면 PluginError 를 던지고, 유효하면 None 을 돌려준다."""
    key = (ide or "").strip().casefold()
    value = (compiler or "").strip().casefold()
    if not key:
        raise PluginError("UNKNOWN_IDE", "ide 값이 비어 있습니다.",
                          f"가능한 값: {', '.join(known_ides())}")
    if key not in IDE_COMPILERS:
        raise PluginError("UNKNOWN_IDE", f"알 수 없는 ide 입니다: {ide}",
                          f"가능한 값: {', '.join(known_ides())}")
    allowed = IDE_COMPILERS[key]
    if not value:
        raise PluginError("BAD_COMPILER_FOR_IDE", "compiler 값이 비어 있습니다.",
                          f"{key} 에 가능한 값: {', '.join(allowed)}")
    if value not in allowed:
        raise PluginError("BAD_COMPILER_FOR_IDE",
                          f"{key} 에서 쓸 수 없는 compiler 입니다: {compiler}",
                          f"{key} 에 가능한 값: {', '.join(allowed)}")
    return None
