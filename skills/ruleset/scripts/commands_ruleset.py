"""ruleset command handlers; shared engine stays in runtime."""
from pathlib import Path

from .errors import PluginError
from .cli_support import _needs_bootstrap, _with_project_key


def cmd_ruleset_show(args):
    from . import server_api
    return _with_project_key(args, "ruleset-show", server_api.get_project_ruleset)


def cmd_ruleset_set(args):
    return _with_project_key(args, "ruleset-set",
                             lambda key: _apply_ruleset(args, key))


def _apply_ruleset(args, key):
    from . import server_api
    locale = args.locale_language
    if not locale:
        # 표시 언어를 안 주면 지금 값을 그대로 유지한다. 변경 API 가 룰셋과 표시
        # 언어를 **함께** 받으므로, 읽어서 다시 넣지 않으면 룰셋만 바꾸려던
        # 호출이 표시 언어까지 덮어쓴다.
        current = server_api.get_project_ruleset(key)
        if not current.get("ok"):
            current["message"] = ("현재 설정을 읽지 못해 변경을 중단했습니다: "
                                  + (current.get("message") or ""))
            return current
        locale = current.get("localeLanguage")

    return server_api.set_project_ruleset(key, args.ruleset_ids, locale)
