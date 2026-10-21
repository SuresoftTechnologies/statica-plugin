"""report-generator command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def cmd_report_generator_show(args):
    from . import server_api
    return _with_project_key(args, "report-generator-show",
                             server_api.get_report_generator)


def cmd_report_generator_set(args):
    from . import server_api
    enabled = args.enabled == "on"
    return _with_project_key(
        args, "report-generator-set",
        lambda key: server_api.set_report_generator(
            key, enabled, args.format, args.kinds))
