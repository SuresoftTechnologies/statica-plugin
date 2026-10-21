"""metric command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def cmd_metric_show(args):
    from . import server_api
    return _with_project_key(args, "metric-show", server_api.get_metrics)


def cmd_metric_set(args):
    """--on / --off 를 하나의 지시로 합친다.

    같은 key 가 양쪽에 오면 --off 가 이긴다. 끄려는 의도를 살리는 쪽이 안전하다 -
    켜는 것을 놓치면 결과가 비고, 끄는 것을 놓치면 원치 않는 경고가 계속 나온다.
    """
    from . import server_api
    uses = {key: True for key in args.on}
    uses.update({key: False for key in args.off})
    return _with_project_key(
        args, "metric-set", lambda key: server_api.set_metrics(key, uses))
