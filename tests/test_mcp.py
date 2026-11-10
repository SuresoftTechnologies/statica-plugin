"""STATICA MCP 서버 테스트. 표준 라이브러리만 쓴다.

    python -m unittest discover -s tests -v

세 갈래를 본다:

1. 대응표 ↔ CLI: 도구가 만든 argv 를 **실제 argparse** 가 받아들이고, CLI 의
   모든 서브커맨드가 도구이거나 EXCLUDED_COMMANDS 에 있는가. CLI 와 MCP 가
   조용히 어긋나는 것을 막는 테스트다.
2. 인자 검사: 디스크 없이.
3. 프로토콜: 실제 서버 프로세스를 띄워 stdio 로 주고받는다. STATIC 이 없는
   머신에서도 통과해야 한다 (doctor 는 ok=false 를 낼 뿐이다).
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from statica_mcp import guides  # noqa: E402
from statica_mcp import server as mcp_server  # noqa: E402
from statica_mcp import tools as catalog  # noqa: E402
from static_agent import cli  # noqa: E402

SAMPLE = {"string": "sample", "integer": 3, "boolean": True}
# Claude Code 가 플러그인 MCP 도구에 붙이는 접두사. 도구 이름 전체는 64자 이하여야
# 하는 클라이언트가 많다.
CLAUDE_CODE_PREFIX = "mcp__plugin_statica_statica-mcp__"
CLI_TOOLS = [t for t in catalog.TOOLS if t.get("command")]


def _subparsers(parser):
    action = next(a for a in parser._actions
                  if a.__class__.__name__ == "_SubParsersAction")
    return action.choices


def _sample_value(pspec):
    if pspec["type"] == "array":
        item = pspec["items"]
        return [_sample_value(item), _sample_value(item)]
    if "enum" in pspec:
        return pspec["enum"][0]
    if pspec["type"] == "integer":
        return max(pspec.get("minimum", 1), min(3, pspec.get("maximum", 3)))
    return SAMPLE[pspec["type"]]


def _full_arguments(spec):
    args = {name: _sample_value(p) for name, p in spec["params"].items()}
    if "projectDir" in args:
        args["projectDir"] = str(ROOT)
    if spec["command"] == "switch":
        args.pop("global")  # projectDir 와 함께 줄 수 없다
    return args


def _minimal_arguments(spec):
    if spec["command"] == "switch":
        # projectDir 는 조건부 필수다 (global 이 아니면 필수)
        return {"enabled": True, "global": True}
    full = _full_arguments(spec)
    return {name: full[name] for name in catalog.input_schema(spec).get("required", [])}


def _always(_path):
    return True


class CatalogMatchesCli(unittest.TestCase):
    def setUp(self):
        self.parser = cli.build_parser()
        self.commands = _subparsers(self.parser)

    def test_every_cli_command_is_a_tool_or_excluded(self):
        exposed = {t["command"] for t in CLI_TOOLS}
        excluded = set(catalog.EXCLUDED_COMMANDS)
        self.assertFalse(exposed & excluded, "both exposed and excluded")
        missing = set(self.commands) - exposed - excluded
        self.assertFalse(missing, "CLI commands with no MCP decision: %s; add "
                                  "them to TOOLS or EXCLUDED_COMMANDS" % missing)
        stale = (exposed | excluded) - set(self.commands)
        self.assertFalse(stale, "names that are not CLI commands: %s" % stale)

    def test_names_are_unique_and_prefixed(self):
        names = [t["name"] for t in catalog.TOOLS]
        self.assertEqual(len(names), len(set(names)))
        for name in names:
            self.assertTrue(name.startswith("statica_"), name)
            self.assertLessEqual(len(CLAUDE_CODE_PREFIX + name), 64, name)

    def test_upload_and_bootstrap_are_exposed_with_consent_hints(self):
        for name in ("statica_upload", "statica_bootstrap_begin",
                     "statica_bootstrap_finish", "statica_bootstrap_abort"):
            ann = catalog.by_name(name)["annotations"]
            self.assertFalse(ann["readOnlyHint"], name)
        for name in ("statica_bootstrap_begin", "statica_bootstrap_finish",
                     "statica_bootstrap_abort"):
            self.assertTrue(catalog.by_name(name)["annotations"]
                            ["destructiveHint"], name)
        for name in ("statica_upload", "statica_bootstrap_finish"):
            self.assertTrue(catalog.by_name(name)["annotations"]
                            ["openWorldHint"], name)

    def test_long_running_tools_outlast_the_cli_child_limit(self):
        for name in ("statica_upload", "statica_bootstrap_finish",
                     "statica_pre_analyze"):
            self.assertGreater(catalog.timeout_for(catalog.by_name(name), {}),
                               1800, name)

    def _parse(self, spec, arguments):
        self.assertIsNone(catalog.validate(spec, arguments, _always, _always))
        argv = catalog.to_argv(spec, arguments)
        try:
            return self.parser.parse_args(argv)
        except SystemExit:
            self.fail("argparse rejected %s -> %s" % (spec["name"], argv))

    def test_full_arguments_parse_and_land_on_the_right_dest(self):
        for spec in CLI_TOOLS:
            with self.subTest(tool=spec["name"]):
                arguments = _full_arguments(spec)
                ns = self._parse(spec, arguments)
                self.assertEqual(ns.command, spec["command"])
                sub = self.commands[spec["command"]]
                by_flag = {o: a for a in sub._actions for o in a.option_strings}
                for name, pspec in spec["params"].items():
                    if name not in arguments:
                        continue
                    value = arguments[name]
                    if pspec["kind"] == "onoff":
                        self.assertEqual(ns.enabled, "on" if value else "off")
                        continue
                    action = by_flag.get(pspec["flag"])
                    self.assertIsNotNone(action, "%s has no %s"
                                         % (spec["command"], pspec["flag"]))
                    got = getattr(ns, action.dest)
                    if pspec["kind"] == "repeat":
                        self.assertEqual([str(v) for v in got],
                                         [str(v) for v in value])
                    elif pspec["kind"] == "flag":
                        self.assertIs(got, True)
                    else:
                        self.assertEqual(str(got), str(value))

    def test_minimal_arguments_satisfy_argparse(self):
        # 스키마의 required 가 argparse 의 필수 인자를 모두 덮는가
        for spec in CLI_TOOLS:
            with self.subTest(tool=spec["name"]):
                self._parse(spec, _minimal_arguments(spec))

    def test_dash_leading_path_is_not_read_as_an_option(self):
        spec = catalog.by_name("statica_scope_exclude")
        ns = self._parse(spec, {"projectDir": str(ROOT),
                                "paths": ["-weird", "--also"]})
        self.assertEqual(ns.paths, ["-weird", "--also"])

    def test_schema_hides_private_keys_and_has_annotations(self):
        for spec in catalog.TOOLS:
            listing = catalog.tool_listing(spec)
            for pspec in listing["inputSchema"]["properties"].values():
                self.assertNotIn("flag", pspec)
                self.assertNotIn("kind", pspec)
            ann = listing["annotations"]
            self.assertEqual(ann["title"], spec["title"])
            self.assertIn("readOnlyHint", ann)
            if not ann["readOnlyHint"]:
                self.assertIn("destructiveHint", ann)


class ArgumentValidation(unittest.TestCase):
    def check(self, name, arguments, isabs=_always, isdir=_always):
        return catalog.validate(catalog.by_name(name), arguments, isabs, isdir)

    def test_switch_never_falls_back_to_global(self):
        self.assertIn("required unless global",
                      self.check("statica_set_auto_analysis", {"enabled": False}))
        self.assertIn("not both", self.check(
            "statica_set_auto_analysis",
            {"enabled": False, "global": True, "projectDir": "/p"}))
        self.assertIsNone(self.check("statica_set_auto_analysis",
                                     {"enabled": True, "global": True}))

    def test_project_dir_must_be_absolute_and_exist(self):
        self.assertIn("absolute", self.check(
            "statica_status", {"projectDir": "rel"}, isabs=lambda p: False))
        self.assertIn("existing directory", self.check(
            "statica_status", {"projectDir": "/nope"}, isdir=lambda p: False))
        self.assertIn("missing required", self.check("statica_status", {}))

    def test_types_enums_and_counts(self):
        self.assertIn("type integer", self.check(
            "statica_pre_analyze", {"projectDir": "/p", "parallel": True}))
        self.assertIn("type boolean", self.check(
            "statica_status", {"projectDir": "/p", "local": 1}))
        self.assertIn("one of", self.check(
            "statica_report", {"projectDir": "/p", "format": "pdf", "kinds": [1]}))
        self.assertIn("<= 12", self.check(
            "statica_report", {"projectDir": "/p", "format": "PDF", "kinds": [13]}))
        self.assertIn("at least 1", self.check(
            "statica_ruleset_set", {"projectDir": "/p", "rulesetIds": []}))
        self.assertIn("unknown argument", self.check(
            "statica_status", {"projectDir": "/p", "stateDir": "/x"}))
        self.assertIn("must be an object", self.check("statica_doctor", []))

    def test_report_timeout_covers_the_wait(self):
        spec = catalog.by_name("statica_report")
        self.assertGreater(catalog.timeout_for(spec, {"timeout": 900}), 900)
        self.assertGreater(catalog.timeout_for(spec, {}),
                           catalog.REPORT_WAIT_DEFAULT)


class InProcessServer(unittest.TestCase):
    """취소 · 파이썬 버전 문 · 예외 처리. 하위 프로세스 대신 가짜 runner."""

    def setUp(self):
        self.sent = []
        self.gate = threading.Event()
        self.started = threading.Event()

        def runner(argv, cwd=None, timeout=None, on_tick=None):
            self.started.set()
            self.gate.wait(5)
            if on_tick is not None:
                on_tick(15)
                on_tick(30)
            if argv[0] == "status":
                raise RuntimeError("boom")
            return {"ok": True, "command": argv[0]}, None

        self.server = mcp_server.Server(self.sent.append, runner)

    def tearDown(self):
        self.gate.set()
        self.server.close()
        self.server.join(5)

    def call(self, rid, name, arguments):
        self.server.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}))

    def cancel(self, rid):
        self.server.handle_line(json.dumps({
            "jsonrpc": "2.0", "method": "notifications/cancelled",
            "params": {"requestId": rid}}))

    def wait_for(self, rid):
        for _ in range(100):
            for m in self.sent:
                if m.get("id") == rid:
                    return m
            time.sleep(0.05)
        return None

    def test_cancelled_calls_get_no_reply(self):
        self.call(1, "statica_doctor", {})        # 도는 중에 취소
        self.assertTrue(self.started.wait(5))
        self.call(2, "statica_doctor", {})        # 대기 중에 취소
        self.call(3, "statica_doctor", {})        # 취소하지 않는다
        self.cancel(1)
        self.cancel(2)
        self.cancel(99)                           # 모르는 id 는 무시
        self.gate.set()
        reply = self.wait_for(3)
        self.assertIsNotNone(reply)
        self.assertFalse(reply["result"]["isError"])
        ids = [m.get("id") for m in self.sent]
        self.assertNotIn(1, ids)
        self.assertNotIn(2, ids)

    def test_unexpected_exception_becomes_a_tool_error(self):
        self.gate.set()
        self.call(5, "statica_status", {"projectDir": str(ROOT)})
        reply = self.wait_for(5)
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("RuntimeError", reply["result"]["content"][0]["text"])

    def test_bad_arguments_are_a_tool_result_not_a_protocol_error(self):
        self.call(6, "statica_status", {"projectDir": "relative/path"})
        reply = self.wait_for(6)
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("absolute", reply["result"]["content"][0]["text"])

    def test_progress_is_sent_only_when_asked(self):
        self.gate.set()
        self.server.handle_line(json.dumps({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "statica_doctor", "arguments": {},
                       "_meta": {"progressToken": "tok"}}}))
        self.assertIsNotNone(self.wait_for(7))
        self.call(8, "statica_doctor", {})
        self.assertIsNotNone(self.wait_for(8))
        progress = [m for m in self.sent
                    if m.get("method") == "notifications/progress"]
        self.assertEqual([p["params"]["progress"] for p in progress], [15, 30])
        self.assertTrue(all(p["params"]["progressToken"] == "tok"
                            for p in progress))
        reply_at = next(i for i, m in enumerate(self.sent) if m.get("id") == 7)
        self.assertTrue(all(self.sent.index(p) < reply_at for p in progress))

    def test_guide_is_answered_while_the_worker_is_busy(self):
        self.call(9, "statica_doctor", {})
        self.assertTrue(self.started.wait(5))     # 작업자가 붙잡혀 있다
        self.call(10, "statica_get_guide", {"topic": "bootstrap"})
        reply = self.wait_for(10)
        self.assertIsNotNone(reply)
        self.assertIsNone(self.wait_for_quick(9))
        self.gate.set()

    def wait_for_quick(self, rid):
        return next((m for m in self.sent if m.get("id") == rid), None)

    def test_old_python_is_reported_not_run(self):
        original = mcp_server.python_ok
        mcp_server.python_ok = lambda: False
        try:
            result = mcp_server.call_tool(catalog.by_name("statica_doctor"), {},
                                          runner=None)
        finally:
            mcp_server.python_ok = original
        self.assertTrue(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["code"], "PYTHON_TOO_OLD")


class RunCliProcess(unittest.TestCase):
    """run_cli 의 대기 루프 · 진행 알림 · 시간 초과를 실제 프로세스로 본다.

    run.py 대신 잠깐 자고 JSON 을 내는 대역 스크립트를 쓴다.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="statica-runcli-")
        self.script = Path(self.dir) / "fake_run.py"
        self.script.write_text(
            "import json, sys, time\n"
            "time.sleep(float(sys.argv[1]))\n"
            "print('noise before payload')\n"
            "print(json.dumps({'ok': True, 'command': 'fake', "
            "'msg': '\\ud55c\\uae00'}))\n", encoding="utf-8")
        self.saved = (mcp_server.RUN_PY, mcp_server.PROGRESS_INTERVAL)
        mcp_server.RUN_PY = self.script
        mcp_server.PROGRESS_INTERVAL = 0.3

    def tearDown(self):
        mcp_server.RUN_PY, mcp_server.PROGRESS_INTERVAL = self.saved
        self.script.unlink()
        os.rmdir(self.dir)

    def test_ticks_while_waiting_and_parses_the_payload(self):
        ticks = []
        payload, failure = mcp_server.run_cli(["1.2"], timeout=30,
                                              on_tick=ticks.append)
        self.assertIsNone(failure)
        self.assertEqual(payload["msg"], "한글")
        self.assertGreaterEqual(len(ticks), 2)
        self.assertEqual(ticks, sorted(ticks))

    def test_timeout_stops_the_process(self):
        started = time.monotonic()
        payload, failure = mcp_server.run_cli(["30"], timeout=1)
        self.assertIsNone(payload)
        self.assertIn("did not finish within 1 seconds", failure)
        self.assertLess(time.monotonic() - started, 20)


class InstallEnv(unittest.TestCase):
    """STATICA_INSTALL_PATH → ARACHNE_INSTALL_PATH. 빈 값은 기존 설정을 덮지 않는다."""

    def test_empty_override_keeps_existing(self):
        env = mcp_server.install_env(
            {"ARACHNE_INSTALL_PATH": "/real", "STATICA_INSTALL_PATH": "  "})
        self.assertEqual(env["ARACHNE_INSTALL_PATH"], "/real")

    def test_filled_override_wins(self):
        env = mcp_server.install_env(
            {"ARACHNE_INSTALL_PATH": "/old", "STATICA_INSTALL_PATH": "/new"})
        self.assertEqual(env["ARACHNE_INSTALL_PATH"], "/new")

    def test_absent_both_is_untouched(self):
        env = mcp_server.install_env({"PATH": "x"})
        self.assertNotIn("ARACHNE_INSTALL_PATH", env)

    def test_source_mapping_is_not_mutated(self):
        src = {"STATICA_INSTALL_PATH": "/new"}
        mcp_server.install_env(src)
        self.assertNotIn("ARACHNE_INSTALL_PATH", src)


class Packaging(unittest.TestCase):
    """등재용 메타데이터가 서로, 그리고 코드와 어긋나지 않는지."""

    def _load(self, name):
        return json.loads((ROOT / name).read_text(encoding="utf-8"))

    def test_versions_agree(self):
        server = self._load("server.json")
        manifest = self._load("manifest.json")
        plugin = self._load(".claude-plugin/plugin.json")
        import re
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        pyver = re.search(r'version\s*=\s*"([^"]+)"', pyproject).group(1)
        versions = {server["version"], manifest["version"], plugin["version"],
                    pyver, mcp_server.SERVER_INFO["version"]}
        self.assertEqual(len(versions), 1, "version mismatch: %s" % versions)

    def test_server_json_shape(self):
        server = self._load("server.json")
        self.assertEqual(server["name"],
                         "io.github.SuresoftTechnologies/statica-mcp")
        self.assertLessEqual(len(server["description"]), 100)
        pkg = server["packages"][0]
        self.assertEqual(pkg["registryType"], "mcpb")
        self.assertIn("mcp", pkg["identifier"])  # 레지스트리 요건
        self.assertIn("v%s/" % server["version"], pkg["identifier"])
        self.assertRegex(pkg["fileSha256"], r"^[a-f0-9]{64}$")

    def test_manifest_entry_point_and_install_var(self):
        manifest = self._load("manifest.json")
        self.assertEqual(manifest["server"]["entry_point"],
                         "scripts/mcp_server.py")
        env = manifest["server"]["mcp_config"]["env"]
        self.assertIn(mcp_server.INSTALL_PATH_ENV, env)

    def test_bundle_excludes_plugin_only_paths(self):
        ignore = (ROOT / ".mcpbignore").read_text(encoding="utf-8")
        for path in (".claude-plugin/", "hooks/", "tests/", ".mcp.json",
                     "scripts/statica-mcp.cmd"):
            self.assertIn(path, ignore)

    def test_bundle_keeps_the_runtime_the_server_needs(self):
        # 번들에서 빠지면 안 되는 것: statica_get_guide 가 읽는 스킬 문서와 CLI
        # 핸들러. .mcpbignore 가 이들을 지우지 않는지 본다.
        ignore_lines = {ln.strip() for ln in
                        (ROOT / ".mcpbignore").read_text(encoding="utf-8")
                        .splitlines() if ln.strip() and not ln.startswith("#")}
        for needed in ("skills/", "scripts/", "scripts/run.py"):
            self.assertNotIn(needed, ignore_lines)


class Guides(unittest.TestCase):
    def test_every_topic_reads_and_maps_commands_to_tools(self):
        for topic in catalog.GUIDE_TOPICS:
            with self.subTest(topic=topic):
                text, failure = guides.read_guide(topic)
                self.assertIsNone(failure)
                self.assertIn("MCP 에서 이 문서를 읽는 법", text)
                body = text.split("\n---\n", 1)[1]
                self.assertFalse(body.lstrip().startswith("---"),
                                 "frontmatter left in")
                for spec in CLI_TOOLS:
                    self.assertIn("`%s`" % spec["name"], text)

    def test_topics_match_the_schema_enum(self):
        self.assertEqual(sorted(guides.TOPICS), sorted(catalog.GUIDE_TOPICS))

    def test_bootstrap_guide_is_the_skill_text(self):
        text, _ = guides.read_guide("bootstrap")
        skill = (ROOT / "skills" / "statica-analyze-bootstrap" / "SKILL.md"
                 ).read_text(encoding="utf-8")
        self.assertIn("## 7. 마무리", skill)
        self.assertIn("## 7. 마무리", text)

    def test_unknown_topic(self):
        text, failure = guides.read_guide("nope")
        self.assertIsNone(text)
        self.assertIn("unknown topic", failure)

    def test_prompts(self):
        names = [p["name"] for p in guides.prompt_listing()]
        self.assertEqual(names, ["connect-project", "upload-analysis"])
        value, _ = guides.get_prompt("connect-project", {"projectDir": "/p/x"})
        text = value["messages"][0]["content"]["text"]
        self.assertIn("/p/x", text)
        self.assertIn("statica_get_guide", text)
        value, _ = guides.get_prompt("upload-analysis", {})
        self.assertIn("절대경로를 나에게 물어라",
                      value["messages"][0]["content"]["text"])
        self.assertIsNone(guides.get_prompt("nope", {})[0])


class StdioProtocol(unittest.TestCase):
    """실제 프로세스. `python scripts/mcp_server.py` 를 stdio 로 몬다."""

    @classmethod
    def setUpClass(cls):
        cls.project = tempfile.mkdtemp(prefix="statica-mcp-test-")
        requests = [
            {"id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"method": "notifications/initialized"},
            {"id": 2, "method": "tools/list"},
            {"id": 3, "method": "ping"},
            {"id": 4, "method": "resources/list"},
            {"id": 5, "method": "tools/call",
             "params": {"name": "nope", "arguments": {}}},
            {"id": 6, "method": "tools/call",
             "params": {"name": "statica_doctor", "arguments": {}}},
            # 연결되지 않은 빈 디렉터리: 서버를 부르지 않고 linked=false 로 답한다
            {"id": 7, "method": "tools/call",
             "params": {"name": "statica_status",
                        "arguments": {"projectDir": cls.project, "local": True}}},
            {"id": 8, "method": "initialize",
             "params": {"protocolVersion": "1999-01-01"}},
            {"id": 9, "method": "prompts/list"},
            {"id": 10, "method": "prompts/get",
             "params": {"name": "connect-project",
                        "arguments": {"projectDir": cls.project}}},
            {"id": 11, "method": "prompts/get", "params": {"name": "nope"}},
            {"id": 12, "method": "tools/call",
             "params": {"name": "statica_get_guide",
                        "arguments": {"topic": "bootstrap-environments"}}},
            {"id": 13, "method": "tools/call",
             "params": {"name": "statica_get_guide",
                        "arguments": {"topic": "nope"}}},
        ]
        lines = "".join(json.dumps(dict(r, jsonrpc="2.0")) + "\n" for r in requests)
        lines += "this is not json\n"
        env = dict(os.environ, PYTHONUTF8="1")
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "mcp_server.py")], input=lines,
            capture_output=True, text=True, encoding="utf-8", timeout=120,
            env=env)
        cls.returncode = proc.returncode
        cls.stderr = proc.stderr
        cls.raw = proc.stdout
        cls.replies = {}
        cls.orphans = []
        for line in proc.stdout.splitlines():
            msg = json.loads(line)  # stdout 의 모든 줄은 JSON-RPC 여야 한다
            if msg.get("id") is None:
                cls.orphans.append(msg)
            else:
                cls.replies[msg["id"]] = msg

    @classmethod
    def tearDownClass(cls):
        os.rmdir(cls.project)

    def test_exits_cleanly_on_eof(self):
        self.assertEqual(self.returncode, 0, self.stderr)

    def test_stdout_is_ascii_only(self):
        self.assertTrue(all(ord(c) < 128 for c in self.raw))

    def test_initialize(self):
        result = self.replies[1]["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "statica-mcp")
        self.assertIn("tools", result["capabilities"])
        self.assertIn("prompts", result["capabilities"])
        self.assertIn("statica_get_guide", result["instructions"])
        self.assertEqual(self.replies[8]["result"]["protocolVersion"],
                         mcp_server.SUPPORTED_PROTOCOLS[0])

    def test_notification_gets_no_reply(self):
        self.assertEqual(sorted(self.replies), list(range(1, 14)))

    def test_tools_list(self):
        listed = self.replies[2]["result"]["tools"]
        self.assertEqual([t["name"] for t in listed],
                         [t["name"] for t in catalog.TOOLS])
        names = {t["name"] for t in listed}
        for name in ("statica_upload", "statica_bootstrap_begin",
                     "statica_bootstrap_finish", "statica_get_guide"):
            self.assertIn(name, names)

    def test_prompts_over_the_wire(self):
        listed = [p["name"] for p in self.replies[9]["result"]["prompts"]]
        self.assertEqual(listed, ["connect-project", "upload-analysis"])
        message = self.replies[10]["result"]["messages"][0]
        self.assertEqual(message["role"], "user")
        self.assertIn(self.project, message["content"]["text"])
        self.assertEqual(self.replies[11]["error"]["code"], -32602)

    def test_guide_over_the_wire(self):
        result = self.replies[12]["result"]
        self.assertFalse(result["isError"])
        self.assertIn("statica_bootstrap_begin", result["content"][0]["text"])
        # enum 밖의 topic 은 인자 검사에서 걸린다
        self.assertTrue(self.replies[13]["result"]["isError"])

    def test_ping_and_errors(self):
        self.assertEqual(self.replies[3]["result"], {})
        self.assertEqual(self.replies[4]["error"]["code"], -32601)
        self.assertEqual(self.replies[5]["error"]["code"], -32602)
        self.assertEqual([o["error"]["code"] for o in self.orphans], [-32700])

    def test_doctor_reports_the_interpreter(self):
        result = self.replies[6]["result"]
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["command"], "doctor")
        self.assertEqual(result["isError"], payload["ok"] is False)
        self.assertEqual(payload["mcpServer"]["python"]["executable"],
                         sys.executable)

    def test_status_on_unlinked_project(self):
        result = self.replies[7]["result"]
        payload = json.loads(result["content"][0]["text"])
        if payload.get("code") == "NO_INSTALL_PATH":
            # STATIC 이 없는 머신: CLI 의 설치 오류가 도구 오류로 그대로 온다
            self.assertTrue(result["isError"])
            return
        self.assertFalse(result["isError"])
        self.assertFalse(payload["project"]["linked"])


if __name__ == "__main__":
    unittest.main()
