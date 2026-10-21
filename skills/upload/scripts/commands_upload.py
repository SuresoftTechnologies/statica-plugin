"""upload command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def cmd_upload(args):
    from . import upload
    return upload.run_upload(args.project_dir, parallel=args.parallel)
