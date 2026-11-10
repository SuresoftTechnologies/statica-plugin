# STATICA — AI Agent for STATIC Static Analysis

> 한국어: [README.ko.md](README.ko.md)

STATICA (STATIC AI Agent) is an AI agent that lets you use STATIC static analysis in coding agents such as Claude Code, Codex CLI, Cursor, and GitHub Copilot. Whenever code changes during a coding session, STATICA re-analyzes only the changed files and reports the result, so your STATIC workspace stays current without a full rebuild. It also connects new projects to STATIC, manages the STATIC server project, and corrects C/C++ analysis configuration when STATIC can't analyze a file.

STATIC is a static analysis tool that detects coding rule violations, runtime errors, and potential security vulnerabilities without executing the source code. It also provides domain-specific coding rule sets and software quality metrics.

STATICA does not replace STATIC's analysis results. STATIC performs the analysis and produces the findings; STATICA prepares, runs, and reports that analysis from inside the coding session. STATICA reports the state of the analysis, such as defect counts by rule, and does not edit source code to fix defects.

## What STATIC and STATICA add

| Need | STATIC and STATICA workflow |
|---|---|
| Keep analysis current while coding | Analyzes only the changed files and posts a one-line `[STATIC]` summary with defect counts by rule. A Stop hook runs it automatically. |
| Check on demand | `/statica:pre-analyze` analyzes the changed files and summarizes defects without uploading. |
| Share results with the team | `/statica:upload` analyzes the whole project and creates a revision on the STATIC server, only when you ask. |
| Connect a new project | A guided bootstrap identifies the build environment and compiler, captures the build, and registers the project on the server. |
| Correct analysis errors | For C/C++ files STATIC couldn't analyze, verifies a parser configuration fix on copies, then applies it to the STATIC wrapper. |
| Manage the server project | View and change rulesets, code metrics, exclusions, and report generation; generate and download reports. |

## Workflow at a glance

1. Run `/statica:pre-analyze` in a project. If it isn't connected to STATIC yet, the coding agent explains the bootstrap and asks for your approval before starting.
2. Work as usual. After each response that changed analyzable sources, the Stop hook analyzes them within a time budget and reports defect counts by rule.
3. When the team should see the result, run `/statica:upload`.
4. Adjust rulesets, metrics, exclusions, and reports with the setting skills, or check `/statica:status`.

The skills in this repository work with a STATIC installation. They are not a replacement for STATIC.

## Install

Add STATICA from Anthropic's plugin directory on claude.ai (**Customize > Plugins**). It loads in Claude Code through account sync. To try a local copy without installing, load it for one session from the folder that contains your checkout:

```text
claude --plugin-dir ./statica-plugin
```

Start a new session after installing, and approve the Stop hook in `/hooks` if asked; automatic analysis needs it.

Its scripts and Stop hook run on your machine against a local STATIC installation. Without STATIC, or when its settings are missing, a command stops at its setup check and says what is missing, and the Stop hook stays silent. Run `/statica:status` to see the connection, automatic-analysis switch, and server state at once.

## Example requests

Responses can vary with the AI model and the conversation. If the result isn't what you expected, rephrase the request with more detail.

| Request | Skill |
|---|---|
| `Analyze what I just changed with STATIC.` | `pre-analyze` |
| `Connect this project to STATIC.` | `statica-analyze-bootstrap` |
| `Upload the full analysis to the STATIC server.` | `upload` |
| `Exclude the third_party folder from analysis.` | `scope` |
| `Generate a STATIC report and download it.` | `report` |
| `This C file fails to analyze. Fix the toolchain settings.` | `statica-toolchain-recovery` |

## Skills

All skills need a STATIC installation for their product-backed actions.

| Skill | Workflow stage |
|---|---|
| `statica-analyze-overview` | Explain the plugin's scope, entry points, and prerequisites. |
| `statica-analyze-bootstrap` | Connect a project to a STATIC workspace for the first time. |
| `pre-analyze` | Analyze changed sources and summarize, without uploading. |
| `upload` | Analyze the whole project and upload it to the STATIC server. |
| `status` | Show the project's STATIC state at a glance. |
| `analyze-on` / `analyze-off` | Turn automatic analysis after each response on or off for the project. |
| `ruleset` | Change the project's ruleset and rule display language. |
| `scope` | Exclude files, directories, or build modules from analysis. |
| `metric` | Turn individual code metrics on or off. |
| `report` / `report-generator` | Generate and download reports; set automatic report generation. |
| `statica-toolchain-recovery` | Verify and apply C/C++ parser configuration fixes. |

Ruleset, metric, exclusion, and report settings belong to the server project, so changes apply to everyone who uses that project.

## MCP server

STATICA also ships an MCP server that exposes the same actions to any MCP client — Claude Desktop, Cursor, VS Code, and others — not only to agents that load the skills. A client with no skills still gets the full flow: connect a project, analyze, upload, and manage the server project. The procedure the skills follow is served back through a tool (`statica_get_guide`), so a skill-less client has the same guidance to work from.

It is listed in the official MCP registry as `io.github.SuresoftTechnologies/statica-mcp`.

Three ways to run it:

- **With the plugin.** Installing STATICA registers the server automatically (`.mcp.json`), so in Claude Code the tools are available alongside the skills.
- **As a bundle.** Download `statica-mcp.mcpb` from this repository's releases and open it with a client that installs MCP bundles. It resolves its own Python, so nothing has to be installed first.
- **Point a client at the interpreter.** Run `scripts/mcp_server.py` with Python 3.10 or later. The launcher `scripts/statica-mcp.cmd` picks a working interpreter on Windows and Linux.

The tools mirror the skills:

| Group | Tools |
|---|---|
| Read-only | `statica_doctor`, `statica_status`, `statica_scope_show`, `statica_ruleset_show`, `statica_metric_show`, `statica_report_generator_show`, `statica_get_guide` |
| Analyze and report | `statica_pre_analyze`, `statica_report`, `statica_upload`, `statica_set_auto_analysis` |
| Server-project settings | `statica_scope_exclude` / `_include` / `_skip_module` / `_unskip_module`, `statica_ruleset_set`, `statica_metric_set`, `statica_report_generator_set` |
| Connect a project | `statica_bootstrap_detect`, `_begin`, `_guard`, `_verify`, `_finish`, `_abort` |

Two prompts, `connect-project` and `upload-analysis`, start the guided flows. Connecting a project and uploading a full analysis change project files or the shared server, so they carry consent hints and ask for your approval first; read `statica_get_guide` before connecting. Without STATIC the server still starts and `statica_doctor` reports what is missing, so it is safe to leave configured on any machine.

The bundle reads the STATIC installation from `ARACHNE_INSTALL_PATH`. When that is not already set on the machine, supply the path through the bundle's `STATICA_INSTALL_PATH` configuration; an empty value leaves the machine's own setting untouched.

## Product-backed workflow

This repository contains the skills, a Stop hook, an MCP server, and Python scripts that drive a local STATIC installation. It does not include STATIC itself. What runs on your machine:

- **Stop hook.** Runs at the end of every response. It exits within a fraction of a second unless the project is connected to STATIC, automatic analysis is on, and analyzable files changed. It never uploads, never blocks your turn, and always exits successfully.
- **Analysis.** Runs STATIC's own analyzers and stores results in the STATIC workspace.
- **Project files.** Connecting a C/C++ project changes its build settings so STATIC can capture the build, only after you approve. Originals are backed up first and the change can be reverted. Java, Kotlin, Python, and C# projects are not modified.
- **Network.** Connects only to the STATIC server configured in your STATIC installation, over HTTPS with your AccessKey. **Certificate verification is disabled** for this connection because STATIC servers commonly use self-signed certificates on internal networks. Analysis results leave your machine only when you run `/statica:upload` or finish bootstrap.
- **Credentials.** Reads the server URL and AccessKey from STATIC's own settings (`conf/server.setting.json`). Never asks for or stores the AccessKey.
- **Local state.** The automatic-analysis switch is stored in `~/.suresoft/data/plugins/static/state.json`.

## Requirements

- STATIC installed and licensed, with `ARACHNE_INSTALL_PATH` pointing to the installation
- The STATIC server URL and AccessKey registered in STATIC's settings
- Python 3.10 or later as `python3` or `python` on `PATH`
- Windows or Linux

For a product demo, purchase, or deployment consultation, contact [bizcenter@suresofttech.com](mailto:bizcenter@suresofttech.com).

## Privacy Policy

- STATICA sends nothing to Suresoft Technologies and has no telemetry. The MCP server has none of its own either; it forwards each call to the local runtime and makes no network call of its own.
- It sends requests only to the STATIC server configured in your STATIC installation, and uploads analysis results only when you ask.
- Its output, such as defect counts and file paths, appears in your coding agent session and is sent to the AI model provider by your coding agent client.

The full policy is in [PRIVACY.md](PRIVACY.md). For support and questions, contact [bizcenter@suresofttech.com](mailto:bizcenter@suresofttech.com).

## License and trademarks

This repository is licensed under the [MIT License](LICENSE). The license covers everything in this repository: the documentation, the skill files, the hook, and the scripts. It does not cover STATIC itself. STATIC and STATICA are Suresoft Technologies products, and no product functionality or product license is granted by this repository.

Claude and Claude Code are trademarks of Anthropic. Other product names may be trademarks of their respective owners.
