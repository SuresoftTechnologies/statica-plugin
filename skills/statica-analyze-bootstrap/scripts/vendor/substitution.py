#!/usr/bin/env python3
"""Step 5: make a project build through the generated wrapper.

The wrapper is a DIRECTORY (`<wrapper_dir>/<name>`) of shim exes named exactly
like the originals (gcc.exe/g++.exe/ar.exe, clang.exe/clang++.exe/llvm-ar.exe,
or the vendor's exe for embedded IDEs). "Substitution" = make the build invoke
those shims instead of the real compiler. The method depends on the BUILD
SYSTEM, per the official docs under docs_dir:

  - make  : override CC/CXX/AR on the command line (preferred), or edit a
            hardcoded Makefile (with a backup).
  - cmake : configure with -DCMAKE_{C,CXX}_COMPILER / -DCMAKE_AR + --fresh
            (or, with the Visual Studio generator, use the VS method below).
  - vs    : add the static.vs.props property sheet (once) and prepend the
            wrapper directory to Project > VC++ Directories > Executable
            Directories. GUI, but deterministic — emitted as instructions.
  - ide_gui (embedded vendor IDEs): point the project's toolchain/compiler
            path at the wrapper directory. The steps DIFFER per IDE, so each
            environment names a `method` in config (eclipse_command,
            overwrite_bin, microchip_flavour, mplab_build_tools, build_variable,
            cmake_file_edit). The method's step/revert templates are baked into
            config and expanded here with the env's params + the wrapper dir, so
            the plan carries concrete, ready-to-follow steps — the PDF (`doc`) is
            only the authoritative source, not a runtime dependency.

This module only PLANS (and optionally applies the safe Makefile edit); it does
not run builds.
"""

import glob
import os
import re
import subprocess
from pathlib import Path


def _norm(p):
    return str(p).replace("\\", "/")


def detect_build_system(project_dir):
    """cmake | make | vs | None, by what build files the project contains.

    CMake wins when CMakeLists.txt is present even if it also has generated
    Makefiles or a .sln, because the CMake flow is what regenerates those.
    """
    root = Path(project_dir)
    def has(*names):
        return any((root / n).exists() for n in names)
    def glob_any(pat):
        return bool(glob.glob(str(root / pat))) or bool(glob.glob(str(root / "**" / pat), recursive=True))

    if has("CMakeLists.txt", "CMakeCache.txt") or glob_any("CMakeLists.txt"):
        return "cmake"
    if glob_any("*.sln") or glob_any("*.vcxproj"):
        return "vs"
    if has("Makefile", "makefile", "GNUmakefile"):
        return "make"
    return None


def _win(path):
    """Backslash form for shells/Makefiles that expect Windows paths."""
    return path.replace("/", "\\")


class _SafeDict(dict):
    """format_map helper: leave unknown {placeholders} untouched instead of raising."""
    def __missing__(self, key):
        return "{" + key + "}"


def _expand(templates, params):
    """Fill a list of step/revert template strings with params (missing keys kept)."""
    return [str(t).format_map(_SafeDict(params)) for t in (templates or [])]


def plan(ide, compiler, environment, project_dir, wrapper_name, wf_cfg):
    """Build a substitution plan for the resolved wrapper (ide/compiler) + project.

    Flow is decided by `ide` (so --ide/--compiler overrides are honored), while
    `environment` (when known) only sharpens which doc to point at.
    """
    sub = wf_cfg["substitution"]
    wrapper_dir = _norm(Path(sub["wrapper_dir"]) / wrapper_name)
    by_env = sub.get("by_environment", {})
    env_entry = by_env.get(environment, {}) if environment else {}

    # flow from the IDE value (gnu/llvm build via build system; visualstudio via
    # property sheet; every vendor IDE is a per-IDE GUI flow)
    if ide in ("gnu", "llvm"):
        flow = "build_system"
        compiler_kind = "clang" if (ide == "llvm" or compiler == "clang") else "gcc"
        entry = {"flow": flow, "compiler_kind": compiler_kind,
                 "doc_by_build": env_entry.get("doc_by_build")
                 or by_env.get("mingw-gcc", {}).get("doc_by_build", {})}
    elif ide == "visualstudio":
        flow = "vs"
        entry = {"flow": flow, "doc": env_entry.get("doc")
                 or by_env.get("visual-studio-msvc", {}).get("doc")}
    else:
        flow = "ide_gui"
        entry = {"flow": flow, "doc": env_entry.get("doc")}
    out = {"flow": flow, "wrapper_dir": wrapper_dir, "method": None,
           "doc": None, "ready_commands": [], "instructions": [], "files": []}
    docs_dir = sub.get("docs_dir")

    def doc_path(name):
        return _norm(Path(docs_dir) / name) if (docs_dir and name) else None

    if flow == "build_system":
        kind = entry.get("compiler_kind", compiler)
        exes = sub.get("wrapper_exes", {}).get(kind)
        bs = detect_build_system(project_dir)
        out["build_system"] = bs
        out["doc"] = doc_path(entry.get("doc_by_build", {}).get(bs) if bs else None)
        if not exes:
            out["method"] = "manual"
            out["instructions"].append(
                f"No wrapper exe names known for compiler kind '{kind}'. "
                f"Point the build at the wrapper directory: {wrapper_dir}")
            return out
        cc = _norm(Path(wrapper_dir) / exes["CC"])
        cxx = _norm(Path(wrapper_dir) / exes["CXX"])
        ar = _norm(Path(wrapper_dir) / exes["AR"])
        if bs == "make":
            out["method"] = "make_cmdline"
            out["ready_commands"].append(
                f'make CC="{_win(cc)}" CXX="{_win(cxx)}" AR="{_win(ar)}"')
            out["instructions"].append(
                "PERMANENT substitution (default): the project's Makefile CC/CXX/AR are "
                "rewritten to the wrapper exes (a Makefile.bak backup is written), so plain "
                "`make` builds through the wrapper with no overrides. Pass "
                "--no-apply-substitution to instead keep the Makefile untouched and build "
                "with the one-shot override line in ready_commands.")
        elif bs == "cmake":
            out["method"] = "cmake_cmdline"
            out["ready_commands"].append(
                f'cmake -S . -B build -DCMAKE_C_COMPILER="{cc}" '
                f'-DCMAKE_CXX_COMPILER="{cxx}" -DCMAKE_AR="{ar}" --fresh')
            out["ready_commands"].append("cmake --build build")
            out["instructions"].append(
                "Reconfigure with these -D options and --fresh so the compiler "
                "swap takes effect, then build. If you generate with the Visual "
                "Studio generator instead, use the VS method (property sheet + "
                "Executable Directories) from the doc.")
        else:
            out["method"] = "manual"
            out["instructions"].append(
                "Could not tell the build system (no Makefile/CMakeLists/.sln "
                f"found). Point your build at the wrapper exes in {wrapper_dir} "
                "or see the doc.")
        return out

    if flow == "vs":
        out["method"] = "vs_gui"
        out["doc"] = doc_path(entry.get("doc"))
        out["instructions"] = [
            "1) Apply the property sheet ONCE: View > Other Windows > Property "
            f"Manager > right-click the project > Add Existing Property Sheet > "
            f"select {sub.get('vs_props')}",
            "2) Substitute the compiler: right-click project > Properties > VC++ "
            f"Directories > Executable Directories > prepend `{_win(wrapper_dir)}` "
            "(separate from existing entries with a semicolon ;).",
            "3) Rebuild and confirm the Output window shows the wrapper compiler.",
        ]
        return out

    # ide_gui (embedded vendor IDEs) — expand the env's baked-in method
    out["doc"] = doc_path(env_entry.get("doc"))
    out["guide"] = sub.get("guide")
    method_id = env_entry.get("method")
    methods = sub.get("methods", {})
    if method_id and method_id in methods:
        m = methods[method_id]
        params = dict(env_entry.get("params") or {})
        params["wrapper"] = _win(wrapper_dir)       # backslash form for Windows GUIs
        params["wrapper_fwd"] = wrapper_dir          # forward-slash form for CMake
        out["method"] = method_id
        out["method_label"] = m.get("label")
        out["instructions"] = _expand(m.get("steps"), params)
        out["revert"] = _expand(m.get("revert"), params)
        if method_id == "overwrite_bin":
            # this method changes the forge step too: -p must be a copy of the
            # original bin (bin_original), not the original, so the shims can
            # still call through. Flag it so the caller/user doesn't miss it.
            out["forge_note"] = (
                "이 환경(overwrite_bin)은 wrapper 생성 시 -p 를 원본 bin 의 복사본"
                "(bin_original)으로 지정해야 한다. 먼저 원본 bin 을 bin_original 로 복사한 뒤"
                " 그 경로로 forge 를 실행하라.")
    else:
        # no environment id to pick a precise method (e.g. detected via by_exe):
        # fall back to the generic goal + the human guide.
        out["method"] = "ide_gui"
        out["instructions"] = [
            "이 IDE는 GUI/프로젝트 설정으로 치환하며 환경마다 절차가 다르다. "
            f"references/substitution.md (또는 doc) 의 해당 IDE 절을 따른다.",
            f"목표: 프로젝트의 툴체인/컴파일러 경로를 wrapper 디렉터리 {wrapper_dir} "
            "(shim exe 들이 원본과 같은 이름)로 가리킨 뒤 rebuild 해 확인.",
        ]
    return out


def build(plan, project_dir):
    """Build the project THROUGH the wrapper, for command-line substitution flows.

    Runs the plan's `ready_commands` in the project dir (make: one line; cmake:
    configure + build). GUI flows (vs_gui / ide_gui) can't be driven headless, so
    they are reported as skipped with the manual instructions left to the caller.

    Returns a dict: {ran, ok, method, commands, steps?, message}. Each step in
    `steps` carries the command, returncode, stdout, stderr.
    """
    method = plan.get("method")
    cmds = plan.get("ready_commands") or []
    if method not in ("make_cmdline", "cmake_cmdline") or not cmds:
        return {
            "ran": False,
            "ok": False,
            "method": method,
            "commands": cmds,
            "message": (
                f"Build flow '{method}' is GUI/manual; not auto-built. "
                "Follow the substitution instructions to build in the IDE."),
        }

    steps = []
    overall_ok = True
    for cmd in cmds:
        # Force a real rebuild so the wrapper is actually exercised. Without this,
        # `make` reports "Nothing to be done" when stale artifacts are newer than
        # the sources — a no-op that looks like success but never calls the wrapper.
        run_cmd = cmd
        if run_cmd.lstrip().lower().startswith("make "):
            run_cmd = run_cmd.replace("make ", "make -B ", 1)
        proc = subprocess.run(run_cmd, cwd=project_dir, shell=True,
                              capture_output=True, text=True)
        steps.append({
            "command": run_cmd,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        })
        if proc.returncode != 0:
            overall_ok = False
            break  # don't run the build step if configure failed
    return {
        "ran": True,
        "ok": overall_ok,
        "method": method,
        "commands": cmds,
        "steps": steps,
        "message": "build succeeded" if overall_ok else "build failed",
    }


def apply_makefile(project_dir, wrapper_dir, compiler_kind, wf_cfg):
    """Rewrite hardcoded CC/CXX/AR in the project's Makefile (with backup).

    Returns (ok, message, changes). Only touches assignment lines; leaves the
    rest of the Makefile alone. Use when the compiler is hardcoded rather than
    overridable on the command line.
    """
    exes = wf_cfg["substitution"].get("wrapper_exes", {}).get(compiler_kind)
    if not exes:
        return False, f"no wrapper exe names for kind '{compiler_kind}'", []
    root = Path(project_dir)
    mk = next((root / n for n in ("Makefile", "makefile", "GNUmakefile")
               if (root / n).exists()), None)
    if not mk:
        return False, "no Makefile in project root", []
    targets = {
        "CC": _win(_norm(Path(wrapper_dir) / exes["CC"])),
        "CXX": _win(_norm(Path(wrapper_dir) / exes["CXX"])),
        "AR": _win(_norm(Path(wrapper_dir) / exes["AR"])),
    }
    text = mk.read_text(errors="replace")
    changes = []

    def repl(m):
        var, sep = m.group("var"), m.group("sep")
        changes.append(var)
        return f"{m.group('lead')}{var}{sep}{targets[var]}"

    pattern = re.compile(r"^(?P<lead>\s*)(?P<var>CC|CXX|AR)(?P<sep>\s*[:?]?=\s*).*$",
                         re.MULTILINE)
    new_text = pattern.sub(lambda m: repl(m) if m.group("var") in targets else m.group(0), text)
    if not changes:
        return False, "no CC/CXX/AR assignments found to edit", []
    bak = mk.with_suffix(mk.suffix + ".bak")
    if not bak.exists():
        bak.write_text(text)
    mk.write_text(new_text)
    return True, f"edited {mk.name} (backup: {bak.name})", sorted(set(changes))
