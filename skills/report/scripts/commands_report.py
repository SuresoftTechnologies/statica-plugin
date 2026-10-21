"""report command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def cmd_report(args):
    from . import report
    return _with_project_key(
        args, "report",
        lambda key: report.run_report(
            args.project_dir, key, args.format, args.kinds,
            out_path=args.out, timeout=args.timeout))
