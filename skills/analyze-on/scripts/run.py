"""Run this skill through the plugin's shared CLI (source tree or installed ZIP)."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    # The skill directory may be renamed by the vendor adapter.
    root = Path(__file__).resolve().parents[2].parent
    candidates = (root / "runtime/scripts/run.py", root / "scripts/run.py")
    entrypoint = next((path for path in candidates if path.is_file()), None)
    if entrypoint is None:
        raise SystemExit("Shared STATIC runtime missing; install the whole plugin.")
    runpy.run_path(str(entrypoint), run_name="__main__")
