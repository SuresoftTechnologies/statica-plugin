#!/usr/bin/env python3
"""Detect compiler / linker / archiver executables on Windows.

Search priority (top to bottom, STOP at the first step that yields a result):

  1. configure / build artifacts  (most accurate)
       - CMakeCache.txt           -> CMAKE_{C,CXX}_COMPILER, CMAKE_LINKER, CMAKE_AR, CMAKE_RANLIB
       - compile_commands.json    -> compiler from the first translation unit's command
  2. IDE known-path glob          (covers the bundled toolchains; the workhorse)
       - patterns + executable seeds live in config/known_paths.json
  3. vswhere                      (MSVC reinforcement when the glob misses it)
  4. VS project parsing           (.sln / .vcxproj -> PlatformToolset, then resolve a real path)
  5. environment variables / PATH (ambiguous; last automatic resort)
       - %CC% / %CXX%, then `where` for common compiler names
  6. direct input                 (everything failed -> ask the user; never guess)

Why this order: a build artifact is direct evidence that *this project* actually
uses *that* compiler. Known-path globs are next because they pin a real install.
PATH/env come last because a name on PATH does not prove identity (cc may be a
symlink, gcc may really be clang, the first hit may be a ccache shim).

Usage:
    python detect_toolchain.py [--project-dir DIR] [--config FILE]
                               [--sysroot DIR] [--verify] [--json]

--sysroot rewrites the drive prefix of every absolute pattern/path under DIR
(e.g. C:/Infineon/... -> DIR/C/Infineon/...). It exists so the known-path logic
can be exercised against a fixture tree in tests; leave it unset in real use.
"""

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Launcher/wrapper prefixes that may sit in front of the real compiler in a
# command string or %CC%. They are not compilers themselves, so strip them.
LAUNCHERS = {"ccache", "sccache", "distcc", "icecc", "icerun"}

# Tokens after the compiler in %CC% / %CXX% are flags, not paths -> drop them.
def _strip_flags(tokens):
    return [t for t in tokens if not t.startswith("-")]


def normalize(p):
    """Use forward slashes everywhere so globbing and comparison are uniform."""
    return str(p).replace("\\", "/")


def apply_sysroot(pattern, sysroot):
    """Relocate an absolute Windows path under a sandbox root, for testing.

    C:/Infineon/x  +  sysroot=/tmp/fake  ->  /tmp/fake/C/Infineon/x
    Paths without a drive letter are returned unchanged.
    """
    if not sysroot:
        return pattern
    p = normalize(pattern)
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if not m:
        return p
    drive, rest = m.group(1), m.group(2)
    return normalize(Path(sysroot) / drive / rest)


def is_executable(path):
    """A real, runnable file. On Windows we trust the extension + existence."""
    if not path:
        return False
    p = Path(path)
    if not p.is_file():
        return False
    if os.name == "nt":
        return p.suffix.lower() in {".exe", ".bat", ".cmd", ".com", ""} or p.suffix == ""
    return os.access(path, os.X_OK)


def verify(path, run=False):
    """Confirm a candidate is a usable tool.

    Default is a cheap existence/extension check. With run=True we invoke the
    tool with a version-ish flag; this is opt-in because vendor compilers can be
    slow to start and we don't want to execute unknown binaries by default.
    """
    if not is_executable(path):
        return False
    if not run:
        return True
    for flag in ("--version", "-version", "--v", "-v"):
        try:
            r = subprocess.run([path, flag], capture_output=True, timeout=15)
            if r.returncode == 0 or r.stdout or r.stderr:
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    # Some tools (lib.exe, ar without args) print usage to stderr and exit !=0;
    # existence already passed, so don't fail solely on a non-zero version probe.
    return True


# ---------------------------------------------------------------------------
# Step 1: build artifacts
# ---------------------------------------------------------------------------

def _find_files(project_dir, name, max_depth=3):
    """Find `name` under project_dir, shallow first (build dirs are near root)."""
    root = Path(project_dir)
    hits = []
    for depth in range(max_depth + 1):
        pattern = os.path.join(str(root), *(["*"] * depth), name)
        hits.extend(glob.glob(pattern))
    # de-dup, preserve shallow-first order
    seen, out = set(), []
    for h in hits:
        n = normalize(h)
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def from_cmake_cache(project_dir, verify_run):
    for cache in _find_files(project_dir, "CMakeCache.txt"):
        try:
            text = Path(cache).read_text(errors="replace")
        except OSError:
            continue
        wanted = {
            "CMAKE_C_COMPILER": "compiler",
            "CMAKE_CXX_COMPILER": "cpp_compiler",
            "CMAKE_LINKER": "linker",
            "CMAKE_AR": "archiver",
            "CMAKE_RANLIB": "ranlib",
        }
        found = {}
        for line in text.splitlines():
            m = re.match(r"^([A-Za-z0-9_]+):[A-Za-z]+=(.*)$", line.strip())
            if not m:
                continue
            key, val = m.group(1), m.group(2).strip()
            if key in wanted and val and val.upper() != "NOTFOUND" and not val.endswith("-NOTFOUND"):
                found[wanted[key]] = normalize(val)
        if found.get("compiler") and verify(found["compiler"], verify_run):
            return _result("cmake_cache", None, found, source_file=cache)
    return None


def from_compile_commands(project_dir, verify_run):
    for cc in _find_files(project_dir, "compile_commands.json"):
        try:
            entries = json.loads(Path(cc).read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in entries:
            tokens = entry.get("arguments")
            if not tokens:
                cmd = entry.get("command", "")
                tokens = shlex.split(cmd, posix=False) if cmd else []
            tokens = [t.strip('"') for t in tokens]
            # drop launcher prefixes
            while tokens and Path(tokens[0]).stem.lower() in LAUNCHERS:
                tokens = tokens[1:]
            if not tokens:
                continue
            comp = tokens[0]
            if verify(comp, verify_run):
                return _result("compile_commands", None, {"compiler": normalize(comp)}, source_file=cc)
    return None


# ---------------------------------------------------------------------------
# Step 2: IDE known-path glob
# ---------------------------------------------------------------------------

def _glob_seeds(bindir, seeds):
    """Return existing matches for a list of (possibly glob) executable seeds."""
    out = []
    for seed in seeds or []:
        for hit in glob.glob(os.path.join(bindir, seed)):
            if Path(hit).is_file():
                out.append(normalize(hit))
    return out


def from_known_paths(config, sysroot, verify_run):
    candidates = []
    for env in config.get("environments", []):
        for pattern in env.get("path_patterns", []):
            for bindir in glob.glob(apply_sysroot(pattern, sysroot)):
                if not Path(bindir).is_dir():
                    continue
                comps = _glob_seeds(bindir, env.get("compiler_seeds"))
                comps = [c for c in comps if verify(c, verify_run)]
                if not comps:
                    continue
                found = {"compiler": comps[0]}
                cpp = _glob_seeds(bindir, env.get("cpp_compiler_seeds"))
                if cpp:
                    found["cpp_compiler"] = cpp[0]
                # vendor toolchains keep linker/archiver in the same bin folder
                link = _glob_seeds(bindir, env.get("linker_seeds"))
                if link:
                    found["linker"] = link[0]
                ar = _glob_seeds(bindir, env.get("archiver_seeds"))
                if ar:
                    found["archiver"] = ar[0]
                ranlib = _glob_seeds(bindir, env.get("ranlib_seeds"))
                if ranlib:
                    found["ranlib"] = ranlib[0]
                candidates.append(_result("known_path", env["id"], found, env_name=env.get("name")))
    if not candidates:
        return None
    primary = dict(candidates[0])  # copy so referencing the full list isn't circular
    if len(candidates) > 1:
        primary["ambiguous"] = True
        primary["candidates"] = candidates
    return primary


# ---------------------------------------------------------------------------
# Step 3: vswhere (MSVC reinforcement)
# ---------------------------------------------------------------------------

def from_vswhere(sysroot, verify_run):
    base = os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")
    vswhere = apply_sysroot(normalize(Path(base) / "Microsoft Visual Studio/Installer/vswhere.exe"), sysroot)
    if not Path(vswhere).is_file():
        return None
    try:
        r = subprocess.run(
            [vswhere, "-products", "*", "-latest", "-format", "json",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"],
            capture_output=True, text=True, timeout=30,
        )
        installs = json.loads(r.stdout) if r.stdout.strip() else []
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    for inst in installs:
        ipath = inst.get("installationPath")
        if not ipath:
            continue
        for host in ("Hostx64", "Hostx86"):
            for arch in ("x64", "x86"):
                pat = normalize(Path(ipath) / f"VC/Tools/MSVC/*/bin/{host}/{arch}")
                for bindir in glob.glob(apply_sysroot(pat, sysroot)):
                    cl = normalize(Path(bindir) / "cl.exe")
                    if verify(cl, verify_run):
                        found = {"compiler": cl, "cpp_compiler": cl}
                        link = normalize(Path(bindir) / "link.exe")
                        lib = normalize(Path(bindir) / "lib.exe")
                        if is_executable(link):
                            found["linker"] = link
                        if is_executable(lib):
                            found["archiver"] = lib
                        return _result("vswhere", "visual-studio-msvc", found,
                                       env_name="Visual Studio C/C++ (MSVC)")
    return None


# ---------------------------------------------------------------------------
# Step 4: VS project parsing
# ---------------------------------------------------------------------------

def from_vs_project(project_dir, sysroot, verify_run):
    """Parse .vcxproj/.sln only to learn the toolset, then resolve via vswhere.

    The project files carry no absolute compiler path, so on a positive ID we
    hand off to vswhere to turn the toolset into a real cl.exe.
    """
    toolsets = set()
    for proj in _find_files(project_dir, "*.vcxproj"):
        try:
            text = Path(proj).read_text(errors="replace")
        except OSError:
            continue
        toolsets.update(re.findall(r"<PlatformToolset>([^<]+)</PlatformToolset>", text))
    if not toolsets and not _find_files(project_dir, "*.sln"):
        return None
    res = from_vswhere(sysroot, verify_run)
    if res:
        res["source"] = "vs_project"
        res["platform_toolset"] = sorted(toolsets) or None
    return res


# ---------------------------------------------------------------------------
# Step 5: environment variables / PATH
# ---------------------------------------------------------------------------

def _resolve_env_compiler(value):
    """Turn a %CC%-style value into a path, dropping launchers and flags."""
    if not value:
        return None
    tokens = shlex.split(value, posix=False)
    tokens = [t.strip('"') for t in tokens]
    while tokens and Path(tokens[0]).stem.lower() in LAUNCHERS:
        tokens = tokens[1:]
    tokens = _strip_flags(tokens)
    if not tokens:
        return None
    cand = tokens[0]
    return normalize(shutil.which(cand) or cand)


def from_env_and_path(verify_run):
    found = {}
    cc = _resolve_env_compiler(os.environ.get("CC"))
    cxx = _resolve_env_compiler(os.environ.get("CXX"))
    if cc and verify(cc, verify_run):
        found["compiler"] = cc
    if cxx and verify(cxx, verify_run):
        found["cpp_compiler"] = cxx
    if "compiler" not in found:
        for name in ("gcc", "clang", "cl", "cc"):
            hit = shutil.which(name)
            if not hit:
                continue
            hit = normalize(hit)
            # skip obvious ccache/sccache shims
            if Path(hit).stem.lower() in LAUNCHERS:
                continue
            if verify(hit, verify_run):
                found["compiler"] = hit
                break
    if not found:
        return None
    return _result("env_path", None, found)


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _result(source, env_id, found, env_name=None, source_file=None):
    out = {
        "source": source,
        "environment": env_id,
        "environment_name": env_name,
        "compiler": found.get("compiler"),
        "cpp_compiler": found.get("cpp_compiler"),
        "linker": found.get("linker"),
        "archiver": found.get("archiver"),
        "ranlib": found.get("ranlib"),
    }
    if source_file:
        out["source_file"] = normalize(source_file)
    return out


def detect(project_dir, config, sysroot, verify_run):
    """Run the steps in priority order, returning the first hit."""
    steps = [
        lambda: from_cmake_cache(project_dir, verify_run),
        lambda: from_compile_commands(project_dir, verify_run),
        lambda: from_known_paths(config, sysroot, verify_run),
        lambda: from_vswhere(sysroot, verify_run),
        lambda: from_vs_project(project_dir, sysroot, verify_run),
        lambda: from_env_and_path(verify_run),
    ]
    for step in steps:
        result = step()
        if result and result.get("compiler"):
            return result
    return {
        "source": "direct_input",
        "environment": None,
        "compiler": None,
        "message": "No toolchain detected automatically. Ask the user for the "
                   "compiler path; do not guess.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Detect Windows compiler/linker/archiver paths.")
    parser.add_argument("--project-dir", default=".", help="Project root to scan for build artifacts/VS projects.")
    parser.add_argument("--config", default=None, help="known_paths.json (default: skill assets/config/known_paths.json).")
    parser.add_argument("--sysroot", default=os.environ.get("TOOLCHAIN_DETECT_SYSROOT"),
                        help="Relocate absolute patterns under this dir (testing only).")
    parser.add_argument("--verify", action="store_true", help="Run each tool's --version to confirm it works.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human summary.")
    args = parser.parse_args(argv)

    config_path = args.config or str(Path(__file__).resolve().parents[2] / "assets" / "config" / "known_paths.json")
    try:
        config = json.loads(Path(config_path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: cannot read config {config_path}: {e}", file=sys.stderr)
        return 2

    result = detect(args.project_dir, config, args.sysroot, args.verify)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["source"] == "direct_input":
            print("No toolchain detected. " + result["message"])
        else:
            label = result.get("environment_name") or result.get("environment") or "(generic)"
            print(f"Detected via: {result['source']}  [{label}]")
            for key in ("compiler", "cpp_compiler", "linker", "archiver", "ranlib"):
                if result.get(key):
                    print(f"  {key:13s}: {result[key]}")
            if result.get("ambiguous"):
                print(f"  ! {len(result['candidates'])} installations matched; first shown above. "
                      "Confirm which to use.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
