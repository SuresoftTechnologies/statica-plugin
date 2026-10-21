"""탐지 결과를 wrapper-forge 의 -i/-c 인자로 매핑한다.

기존 스킬 forge_wrapper.py 의 map_to_wrapper_forge 를 그대로 옮긴 것이다 (로직 변경 없음).
원본 파일은 최상위에서 `import detect_toolchain as dt` 등을 썼지만, 이 함수 본문은
`dt` 를 참조하지 않으므로(=존재하는 모듈 참조를 relative import 로 바꿀 대상이 없으므로)
실제로 쓰이는 fnmatch/Path 임포트만 유지한다.
"""
import fnmatch
from pathlib import Path


def map_to_wrapper_forge(result, wf_cfg, ide_override=None, compiler_override=None):
    """Return (ide, compiler, error). error is set when it can't be resolved."""
    comp_path = result.get("compiler")
    stem = Path(comp_path).stem.lower() if comp_path else ""

    ide = ide_override
    compiler = compiler_override

    env = result.get("environment")
    if not ide and env and env in wf_cfg.get("by_environment", {}):
        m = wf_cfg["by_environment"][env]
        ide = m["ide"]
        if "compiler" in m:
            compiler = m["compiler"]
        else:
            for pat, val in m.get("by_exe", {}).items():
                if fnmatch.fnmatch(stem, pat.lower()):
                    compiler = val
                    break

    # exe-based inference (cmake_cache / compile_commands / env_path, or env miss)
    if not ide or not compiler:
        if stem in {k.lower() for k in wf_cfg.get("ambiguous_exe", {})}:
            msg = wf_cfg["ambiguous_exe"].get(stem) or wf_cfg["ambiguous_exe"].get(
                Path(comp_path).stem)
            return None, None, msg or f"'{stem}' is ambiguous; pass --ide/--compiler."
        for rule in wf_cfg.get("by_exe", []):
            if fnmatch.fnmatch(stem, rule["match"].lower()):
                ide = ide or rule["ide"]
                compiler = compiler or rule["compiler"]
                break

    if not ide or not compiler:
        return None, None, (
            f"Could not map compiler '{comp_path}' to wrapper-forge -i/-c. "
            "Pass --ide and --compiler explicitly.")

    # sanity-check against the allowed table
    allowed = wf_cfg.get("allowed", {})
    if ide in allowed and compiler not in allowed[ide]:
        return None, None, (
            f"compiler '{compiler}' is not valid for ide '{ide}'. "
            f"Allowed: {allowed[ide]}")
    return ide, compiler, None
