# Releasing the MCP bundle

The MCP server in `scripts/` is distributed as an MCP Bundle (`.mcpb`) attached
to a GitHub release and listed in the official MCP registry through
`server.json`. The Claude Code plugin (skills, Stop hook, `.mcp.json`) is a
separate distribution and is not affected by these steps.

**Releasing is automated.** A maintainer bumps the version in the tracked files
and pushes a tag. `.github/workflows/publish-mcp-registry.yml` then builds the
bundle, creates the GitHub release, uploads the bundle, hashes it, and publishes
`server.json` to the registry. There is no manual bundle build or hash step.

## Per release

1. Bump the version to `X.Y.Z` in every file below and commit to `main`:

   - `server.json`
   - `manifest.json`
   - `pyproject.toml`
   - `.claude-plugin/plugin.json`
   - `SERVER_INFO` in `scripts/statica_mcp/server.py`

   `test_versions_agree` checks they match; run the suite first:

   ```
   python -m unittest discover -s tests
   ```

   To find any stragglers:

   ```
   grep -rn 'X\.Y\.Z' server.json manifest.json pyproject.toml \
     .claude-plugin/plugin.json scripts/statica_mcp/server.py
   ```

2. Tag that commit and push the tag:

   ```
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

3. Watch the workflow and confirm the registry entry:

   ```
   gh run watch "$(gh run list --workflow publish-mcp-registry.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
   curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.SuresoftTechnologies"
   ```

That is the whole release. The tag's version must match the tracked files or the
workflow stops at its first step.

## What the workflow does

On a pushed `v*` tag (or `workflow_dispatch` with a tag):

1. **Version guard** — the tag must equal the version in `server.json`, and
   `manifest.json`, `pyproject.toml`, `.claude-plugin/plugin.json` and
   `SERVER_INFO` must all agree. A mismatch fails here, before anything is
   published.
2. **Pack** — `mcpb pack` builds `statica-mcp.mcpb`. The name contains `mcp`
   because the registry requires the package URL to. `.mcpbignore` decides the
   contents (see below).
3. **Release** — creates the GitHub release for the tag (if absent) and uploads
   the bundle.
4. **Hash** — computes `fileSha256` from the uploaded bundle and writes it, with
   the tag's download URL, into `server.publish.json` (a publish-only copy; the
   repo's `server.json` is never rewritten).
5. **Publish** — validates and publishes `server.publish.json` to the registry
   over GitHub OIDC.

`mcpb pack` is not reproducible — the same tree packs to different bytes each
time — so the bundle is built once in CI and that exact file is both released
and hashed. The registry does not check the hash; MCP clients do. Computing it
from the released bytes removes any chance of a stale hash reaching clients.

The `fileSha256` in the committed `server.json` is a permanent placeholder
(`0000…`). It is never the real hash: the real value exists only on the release
and is injected at publish time. Do not try to keep it current by hand.

## What goes in the bundle

`.mcpbignore` decides this. The bundle keeps `scripts/` (the server and the
shared CLI) and `skills/` — the CLI command handlers live in `skills/*/scripts`,
and `statica_get_guide` serves the `SKILL.md` and reference text. It drops the
Claude Code plugin surface (`.claude-plugin/`, `hooks/`, `.mcp.json`,
`scripts/statica-mcp.cmd`) and repo tooling (`tests/`, `.github/`, this file).

## Why the `uv` server type

`manifest.json` declares `server.type: "uv"`, the one MCPB type where the host
provides Python ("Host application manages Python and dependencies
automatically", MCPB README). The server has no third-party dependencies, so uv
fetches its own CPython and runs `scripts/mcp_server.py` with nothing to
install. `python` would need an interpreter the user already has (and on Windows
the `python` alias is often the Microsoft Store stub); `node` would mean
rewriting the server; `binary` needs a per-platform build.

`mcp_config` passes `--project`, not `--directory`, so the child's working
directory stays the user's project rather than the bundle.

## The install path

The CLI finds STATIC through `ARACHNE_INSTALL_PATH`. The bundle exposes a
`STATICA_INSTALL_PATH` user config instead, and the server copies it to
`ARACHNE_INSTALL_PATH` **only when it is non-empty** (`install_env` in
`scripts/statica_mcp/server.py`). An empty user config must not overwrite an
`ARACHNE_INSTALL_PATH` already set on the machine, which is why the names differ.

## Re-publishing a tag

`workflow_dispatch` re-runs the whole flow for an existing tag (pass the tag as
input). It re-uploads the bundle with `--clobber` and republishes. Prefer a new
version number over re-cutting one that is already public.

## One-time setup

- Actions enabled on the repository.
- Nothing else: OIDC needs no stored secret, and the bundle has no dependencies
  to configure.
