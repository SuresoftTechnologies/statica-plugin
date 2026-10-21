"""Shared project API and bootstrap-owned vendor helpers."""
from pathlib import Path
from .. import __path__ as _parent_paths

__path__ = [str(Path(path) / "vendor") for path in _parent_paths
            if (Path(path) / "vendor").is_dir()]
