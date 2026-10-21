# Privacy Policy — Suresoft STATIC plugin (statica)

This policy covers the `statica` plugin: its skills, its Stop hook, and the Python scripts they run. It does not cover STATIC (Arachne) itself, which is a separate Suresoft Technologies product with its own terms and data handling.

**Last updated:** 2026-10-16

## What is collected

The plugin collects nothing for Suresoft Technologies. It has no telemetry, analytics, crash reporting, or update checks.

To work, it reads the following on your machine:

- The `ARACHNE_INSTALL_PATH` environment variable, to find your STATIC installation.
- `conf/server.setting.json` in that installation: the STATIC server URL and your AccessKey. These values are registered through STATIC's own settings. The plugin only reads them; it never asks you for the AccessKey and never writes it to any file, log, or message.
- Source files and build output of the project you are working in, so STATIC can analyze them.

## How data is used and stored

- **Analysis:** the plugin runs STATIC's analyzers (`analyzer-csa`, `analyzer-plugin`) on your machine. Results are stored in the STATIC workspace under your STATIC installation (`works/`).
- **Automatic analysis switch:** the on/off state for each project is stored in `~/.suresoft/data/plugins/static/state.json`.
- **First-time connection (bootstrap):** with your approval, connecting a C/C++ project to STATIC changes your project's build settings so that STATIC can capture the build. Original files are backed up in the STATIC workspace before they change, and the change can be reverted. Java, Kotlin, Python, and C# projects are not modified.
- **Toolchain recovery:** verification runs on copies. When a fix is verified, the plugin updates the STATIC wrapper configuration inside your STATIC installation and keeps a plan with before/after hashes and a diff.
- **Reports:** reports you request are downloaded to the path you choose.

## What leaves your machine

The plugin connects only to **the STATIC server configured in your STATIC installation**, which is usually operated by your organization. It sends:

- Your AccessKey, in the `Authorization` header of each request.
- Project registration data: project key, name, and language.
- Requests to read or change the server project's ruleset, code metrics, report generation, and exclusion settings, and to generate and download reports.
- Analysis results, **only** when you run `/statica:upload` or when you finish the first-time connection. STATIC's analyzer performs this upload, and the results can include file paths, code locations, and defect details. Automatic analysis after each response never uploads.

Connections to the STATIC server use HTTPS **without certificate verification**, because STATIC servers commonly use self-signed certificates on internal networks. Point STATIC only at a server you trust on a network you trust.

Separately, the plugin's output is shown in your Claude session. That output includes defect counts by rule, file paths, and status messages, and your Claude client sends it to the AI model provider under that provider's privacy policy (for Claude, Anthropic's privacy policy).

## Third parties

Suresoft Technologies receives nothing from this plugin and shares no data with third parties. Data sent to your STATIC server is governed by whoever operates that server.

## Retention

The plugin keeps no data of its own beyond the local files listed above, which remain until you delete them. Remove workspaces and server projects through STATIC; delete `~/.suresoft/data/plugins/static/` to clear the automatic-analysis state.

## Changes to this policy

Changes are tracked in this repository's commit history.

## Contact

Suresoft Technologies — [bizcenter@suresofttech.com](mailto:bizcenter@suresofttech.com) — <https://www.suresofttech.com>
