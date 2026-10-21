"""Shared engine plus skill-owned modules, independent of vendor skill names."""
from pathlib import Path

_runtime = Path(__file__).resolve().parents[2]
_skills = (_runtime.parent / "skills" if _runtime.name == "runtime"
           and _runtime.parent.name == "src" else _runtime / "skills")
# Skill implementations live directly in scripts/. Keep their static_agent.*
# import identity while leaving shared implementations in this package.
# Only modules shipped within this plugin participate; never scan cwd or PATH.
__path__ = [str(Path(__file__).resolve().parent)] + [
    str(path) for path in sorted(_skills.glob("*/scripts"))
    if path.is_dir()
]
