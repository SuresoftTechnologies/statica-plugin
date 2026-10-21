#!/usr/bin/env python3
"""Step 7: create the project on the STATIC server and fill app.data.json.

A freshly seeded workspace has `.staticdata/.app/app.data.json` with an empty
`projectKey`. That key links the workspace to a project on the STATIC server, so
before it means anything the project has to exist. This module:

  1. reads the STATIC client's `conf/server.setting.json` for the server URL and
     access key (the same ones the user entered in the client's Settings),
  2. derives the project key from the workspace name — strip everything but
     [A-Za-z0-9], drop leading digits, uppercase (e.g. `test_make_2` -> `TESTMAKE2`),
     matching the server's own `key.toUpperCase()` and every populated
     app.data.json on disk (DJTEST, TETRIS2, ZSTD, ...),
  3. POSTs ProjectCreationDto to `<server>/api/forward/open-api/projects` with
     `Authorization: Bearer <accessKey>` (HTTP bearer, per the open-api security
     scheme), and
  4. on success writes the key back into app.data.json's `projectKey`.

Stdlib only (urllib + ssl); the server is an internal host with a self-signed
cert, so TLS verification is disabled for this call.
"""

import json
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path


def _norm(p):
    return str(p).replace("\\", "/")


def project_key_from_name(name):
    """Workspace name -> server project key. See DTO regex ^[A-Za-z][A-Za-z0-9]*$,
    size 3..20, stored uppercased. Returns (key, error)."""
    stripped = re.sub(r"[^A-Za-z0-9]", "", name or "")
    stripped = re.sub(r"^[0-9]+", "", stripped)  # must start with a letter
    key = stripped.upper()[:20]
    if len(key) < 3:
        return None, (f"cannot derive a valid project key from workspace name '{name}': "
                      f"need >=3 alphanumeric chars starting with a letter (got '{key}').")
    return key, None


def load_server_setting(path):
    """Return (server, access_key, error) from conf/server.setting.json."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        return None, None, f"cannot read server setting {path}: {e}"
    server = (data.get("server") or "").rstrip("/")
    access_key = data.get("accessKey") or ""
    if not server or not access_key:
        return None, None, f"server setting {path} missing 'server' or 'accessKey'."
    return server, access_key, None


def _post_json(url, payload, access_key, timeout=30):
    """POST payload as JSON with bearer auth. Returns (status, body, error)."""
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {access_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    ctx = ssl.create_default_context()          # internal host, self-signed cert:
    ctx.check_hostname = False                  # verification would always fail,
    ctx.verify_mode = ssl.CERT_NONE             # so skip it for this call only.
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), None
    except urllib.error.URLError as e:
        return None, None, f"cannot reach server {url}: {e.reason}"


def fill_app_data_project_key(workspace, app_data_rel, key):
    """Set projectKey in the workspace's app.data.json. Returns (ok, path, error)."""
    p = Path(workspace) / app_data_rel
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        return False, _norm(p), f"cannot read {p}: {e}"
    data["projectKey"] = key
    try:
        p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        return False, _norm(p), f"cannot write {p}: {e}"
    return True, _norm(p), None


def create_and_fill(pc_cfg, workspace, workspace_name, email=None, server_setting=None):
    """Create the project on the server and, on success, fill app.data.json.

    Returns a result dict: ran, ok, status, key, created/existed, request (the DTO
    minus nothing sensitive), app_data (path filled), message.
    """
    out = {"ran": True, "ok": False, "key": None, "status": None, "message": None}

    key, err = project_key_from_name(workspace_name)
    if err:
        out.update(ok=False, message=err)
        return out
    out["key"] = key

    setting_path = server_setting or pc_cfg.get("server_setting")
    server, access_key, err = load_server_setting(setting_path)
    if err:
        out.update(ok=False, message=err)
        return out

    dto = {
        "key": key,
        "language": pc_cfg.get("language", "CCPP"),
        "email": email or pc_cfg.get("email"),
        "name": workspace_name,
        "isPrivate": bool(pc_cfg.get("is_private", False)),
        "description": pc_cfg.get("description", ""),
        "analyzerVersion": pc_cfg.get("analyzer_version", "5.0.0"),
        "projectType": pc_cfg.get("project_type", "GENERAL"),
    }
    out["request"] = dto
    url = server + pc_cfg.get("endpoint_path", "/api/forward/open-api/projects")
    out["url"] = url

    status, body, err = _post_json(url, dto, access_key)
    if err:
        out.update(ok=False, message=err)
        return out
    out["status"] = status
    out["body"] = (body or "").strip()

    # 200 = created; 409 = already exists (key taken) — in both cases the project
    # with this key exists, so linking app.data.json to it is valid.
    if status == 200:
        out["created"] = True
    elif status == 409:
        out["existed"] = True
    else:
        out.update(ok=False,
                   message=f"createProject returned HTTP {status}: {out['body'] or '(no body)'}")
        return out

    ok, path, ferr = fill_app_data_project_key(
        workspace, pc_cfg.get("app_data_rel", ".staticdata/.app/app.data.json"), key)
    out["app_data"] = path
    if not ok:
        out.update(ok=False, message=f"project ready (HTTP {status}) but {ferr}")
        return out
    out.update(ok=True,
               message=(f"project '{key}' created (HTTP 200)" if status == 200
                        else f"project '{key}' already existed (HTTP 409)")
                       + f"; app.data.json projectKey set to '{key}'.")
    return out
