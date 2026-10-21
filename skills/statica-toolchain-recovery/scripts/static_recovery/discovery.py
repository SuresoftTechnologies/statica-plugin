"""Discover STATIC analysis evidence without executing content from it."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import RecoveryError, read_text_preserved, sha256_file


CSA_COMMAND = re.compile(r"\bCSA:\s*CMD:\s*(?P<command>.+?)\s*$", re.IGNORECASE)
ERROR_LINE = re.compile(
    r"(?:\berror\b|fatal|failed|failure|exception|internal compiler|parse(?:r|ing)?.*error)",
    re.IGNORECASE,
)
SUCCESS_MARKERS = (
    "Main: Parsing Start",
    "Main: Parsing Finished",
    "Inspection: Processing Finished",
    "Main: Processing Finished",
)
RUN_FAILURE = re.compile(r"(?:Parsing\s+Failed|\[(?:Error|Fatal)\]|fatal\s+error|internal\s+(?:compiler|parser)\s+error)", re.I)
LOG_TIMESTAMP = re.compile(r"\b(?P<value>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?)\b")
KEY_SETTING = re.compile(
    r"^(?:target|gnu_version|microsoft_version|msvc_version|clang_version|cpp_standard|c_standard)\s*=",
    re.I,
)
TOOLCHAIN_EVIDENCE = re.compile(
    r"(?:gcc|g\+\+|clang|Microsoft.*Compiler|Target:|COLLECT_GCC|version\s+\d+\.\d+)",
    re.IGNORECASE,
)


def split_windows_commandline(command: str) -> list[str]:
    """Split the quoting rules used by Windows CommandLineToArgvW."""
    arguments: list[str] = []
    current: list[str] = []
    in_quotes = False
    index = 0
    length = len(command)
    while index < length:
        if command[index] in " \t" and not in_quotes:
            if current:
                arguments.append("".join(current))
                current = []
            index += 1
            continue
        backslashes = 0
        while index < length and command[index] == "\\":
            backslashes += 1
            index += 1
        if index < length and command[index] == '"':
            current.extend("\\" * (backslashes // 2))
            if backslashes % 2:
                current.append('"')
            else:
                in_quotes = not in_quotes
            index += 1
            continue
        current.extend("\\" * backslashes)
        if index < length:
            current.append(command[index])
            index += 1
    if in_quotes:
        raise RecoveryError("InvalidCsaCommand", "CSA 명령의 따옴표가 닫히지 않음.")
    if current:
        arguments.append("".join(current))
    return arguments


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def static_layout(analysis: str | Path) -> dict[str, str] | None:
    """Derive one exact STATIC install/workspace layout from an analysis path."""
    path = Path(analysis).resolve()
    parts = path.parts
    candidates: list[tuple[Path, str]] = []
    for index, part in enumerate(parts[:-1]):
        if part.casefold() != "works" or index + 1 >= len(parts):
            continue
        install = Path(*parts[:index])
        if install.name.casefold() == "static-arachne":
            candidates.append((install, parts[index + 1]))
    if len(candidates) != 1:
        return None
    install, workspace_name = candidates[0]
    workspace_root = install / "works" / workspace_name
    return {
        "install_root": str(install.resolve()),
        "workspace_name": workspace_name,
        "workspace_root": str(workspace_root.resolve()),
        "expected_csa": str((workspace_root / ".staticdata" / "analyzer" / "bin" / "csa.exe").resolve()),
        "wrapper_parent": str((install / "wrapper").resolve()),
        "expected_wrapper_root": str((install / "wrapper" / workspace_name).resolve()),
    }


def _command_record(
    raw: str,
    *,
    log_path: Path,
    line_number: int,
    expected_analysis: Path,
    expected_csa: Path,
    command_time_ns: int | None,
) -> dict[str, Any]:
    args = split_windows_commandline(raw)
    record: dict[str, Any] = {
        "raw": raw,
        "log_path": str(log_path),
        "line": line_number,
        "args": args,
        "valid": False,
        "blockers": [],
        "log_mtime_ns": log_path.stat().st_mtime_ns,
        "command_time_ns": command_time_ns,
    }
    if len(args) != 4:
        record["blockers"].append("CSA 명령은 executable /Work analysis source 네 인수여야 함.")
        return record
    executable = Path(args[0])
    work_indexes = [index for index, value in enumerate(args) if value.casefold() == "/work"]
    if work_indexes != [1]:
        record["blockers"].append("정확한 /Work <analysis> <source> 형태가 아님.")
        return record
    work_index = work_indexes[0]
    analysis_argument, source_argument = args[work_index + 1 : work_index + 3]
    record.update(
        {
            "executable": str(executable),
            "expected_executable": str(expected_csa),
            "work_index": work_index,
            "analysis_argument": analysis_argument,
            "source_argument": source_argument,
            "trusted_layout": executable.is_absolute() and _same_path(executable, expected_csa),
            "executable_exists": executable.is_file(),
            "analysis_matches_input": _same_path(analysis_argument, expected_analysis),
        }
    )
    if not Path(analysis_argument).is_absolute() or not Path(source_argument).is_absolute():
        record["blockers"].append("/Work 분석 경로와 소스 경로는 절대 경로여야 함.")
    if not record["trusted_layout"]:
        record["blockers"].append("현재 STATIC workspace의 정확한 .staticdata/analyzer/bin/csa.exe가 아님.")
    if not record["executable_exists"]:
        record["blockers"].append("로그의 csa.exe가 현재 컴퓨터에 없음.")
    if not record["analysis_matches_input"]:
        record["blockers"].append("/Work 분석 경로가 입력 분석 폴더와 다름.")
    record["valid"] = not record["blockers"]
    return record


def _log_timestamp_ns(line: str) -> int | None:
    match = LOG_TIMESTAMP.search(line)
    if not match:
        return None
    try:
        local_time = datetime.fromisoformat(match.group("value")).astimezone()
    except ValueError:
        return None
    return int(local_time.timestamp() * 1_000_000_000)


def _command_order(record: dict[str, Any]) -> tuple[int, int, int]:
    return (
        int(record.get("command_time_ns") or record.get("log_mtime_ns") or 0),
        int(record.get("log_mtime_ns") or 0),
        int(record.get("line") or 0),
    )


def _selected_run_evidence(selected: dict[str, Any] | None, root: Path, outputs: list[Path]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "log_path": None,
        "command_line": None,
        "segment_end_line": None,
        "marker_lines": {},
        "failure_lines": [],
        "ordered_success_markers": False,
        "fresh_outputs": [],
        "success": False,
    }
    if not selected:
        return result
    log = Path(selected["log_path"])
    lines = _text_lines(log)
    start = int(selected["line"]) - 1
    if start < 0 or start >= len(lines):
        return result
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if CSA_COMMAND.search(lines[index]):
            end = index
            break
    segment = lines[start:end]
    marker_lines: dict[str, int | None] = {}
    cursor = 0
    ordered = True
    for marker in SUCCESS_MARKERS:
        found = next(
            (index for index in range(cursor, len(segment)) if marker.casefold() in segment[index].casefold()),
            None,
        )
        if found is None:
            marker_lines[marker] = None
            ordered = False
            continue
        marker_lines[marker] = start + found + 1
        cursor = found + 1
    failure_lines = [
        start + index + 1
        for index, line in enumerate(segment)
        if RUN_FAILURE.search(line)
    ]
    threshold = int(selected.get("command_time_ns") or selected.get("log_mtime_ns") or 0)
    fresh_outputs = [
        {
            "path": _relative(path, root),
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
            "sha256": sha256_file(path),
        }
        for path in outputs
        if path.stat().st_mtime_ns >= threshold and path.stat().st_size > 0
    ]
    result.update(
        {
            "log_path": _relative(log, root),
            "command_line": start + 1,
            "segment_end_line": end,
            "marker_lines": marker_lines,
            "failure_lines": failure_lines,
            "ordered_success_markers": ordered,
            "fresh_outputs": fresh_outputs,
            "success": ordered and not failure_lines and bool(fresh_outputs),
        }
    )
    return result


def _adjacent_failure_state(original: Path) -> dict[str, Any]:
    path = original.parent.parent / "analyze.failed.json"
    record: dict[str, Any] = {"path": str(path), "exists": path.exists(), "valid": None, "clean": True}
    if not path.exists():
        return record
    if not path.is_file():
        record.update({"valid": False, "clean": False, "error": "일반 파일이 아님."})
        return record
    record["sha256"] = sha256_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        record.update({"valid": False, "clean": False, "error": str(exc)})
        return record
    module_failure = value.get("moduleFailure") if isinstance(value, dict) else None
    file_failures = value.get("fileFailures") if isinstance(value, dict) else None
    clean = isinstance(module_failure, dict) and not module_failure and isinstance(file_failures, dict) and not file_failures
    record.update(
        {
            "valid": isinstance(value, dict),
            "clean": clean,
            "module_failure_count": len(module_failure) if isinstance(module_failure, dict) else None,
            "file_failure_count": len(file_failures) if isinstance(file_failures, dict) else None,
        }
    )
    return record


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _text_lines(path: Path) -> list[str]:
    try:
        return read_text_preserved(path).text.splitlines()
    except (OSError, RecoveryError):
        return []


def _summarize_elog(path: Path, root: Path) -> dict[str, Any]:
    lines = _text_lines(path)
    selected = [
        {"line": number, "text": line[:500]}
        for number, line in enumerate(lines, 1)
        if ERROR_LINE.search(line)
    ][:30]
    if not selected:
        selected = [
            {"line": number, "text": line[:500]}
            for number, line in enumerate(lines[:20], 1)
            if line.strip()
        ]
    return {
        "path": _relative(path, root),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "representative_lines": selected,
    }


def _small_text_record(path: Path, root: Path, *, limit: int = 128 * 1024) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": _relative(path, root),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    try:
        document = read_text_preserved(path)
    except (OSError, RecoveryError) as exc:
        record.update({"readable": False, "error": str(exc)})
        return record
    text = document.text[:limit]
    record.update(
        {
            "readable": True,
            "encoding": document.encoding,
            "bom": bool(document.bom),
            "newline": repr(document.newline),
            "text": text,
            "truncated": len(document.text) > len(text),
        }
    )
    return record


def _capture_support_record(path: Path, root: Path) -> dict[str, Any]:
    record = _small_text_record(path, root)
    text = record.pop("text", "")
    if isinstance(text, str):
        record["toolchain_lines"] = [
            {"line": number, "text": line[:500]}
            for number, line in enumerate(text.splitlines(), 1)
            if TOOLCHAIN_EVIDENCE.search(line)
        ][:40]
    return record


def _load_capture(path: Path, root: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return {"path": _relative(path, root), "valid": False, "error": str(exc)}
    if not isinstance(value, dict):
        return {"path": _relative(path, root), "valid": False, "error": "최상위 값이 객체가 아님."}
    return {
        "path": _relative(path, root),
        "valid": True,
        "wrapper_path": value.get("wrapperPath"),
        "source_file": value.get("sourceFile"),
        "source_file_kind": value.get("sourceFileKind"),
        "working_directory": value.get("workingDirectory"),
        "compile_command": value.get("compileCommand"),
        "preprocess_command": value.get("preprocessCommand"),
    }


def _parser_summary(path: Path, root: Path) -> dict[str, Any]:
    try:
        document = read_text_preserved(path)
    except (OSError, RecoveryError) as exc:
        return {"path": _relative(path, root), "valid": False, "error": str(exc)}
    lines = document.text.splitlines()
    settings = [
        {"line": number, "text": line}
        for number, line in enumerate(lines, 1)
        if KEY_SETTING.match(line)
    ]
    duplicate_keys: dict[str, int] = {}
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        duplicate_keys[key] = duplicate_keys.get(key, 0) + 1
    return {
        "path": _relative(path, root),
        "valid": True,
        "sha256": sha256_file(path),
        "encoding": document.encoding,
        "bom": bool(document.bom),
        "newline": repr(document.newline),
        "settings": settings,
        "duplicate_keys": {key: count for key, count in duplicate_keys.items() if count > 1},
    }


def discover(analysis_copy: str | Path, original_analysis: str | Path) -> dict[str, Any]:
    root = Path(analysis_copy).resolve()
    original = Path(original_analysis).resolve()
    layout = static_layout(original)
    files = [path for path in root.rglob("*") if path.is_file()]
    parser_matches = [path for path in files if path.name.casefold() == "parser.conf"]
    capture_matches = [path for path in files if path.name.casefold() == "compile.capture.json"]
    runtime_logs = [path for path in files if path.name.casefold().endswith("runtime.log")]
    encodings = [path for path in files if path.name.casefold() in {".csencoding", ".csencodings"}]
    elogs = [path for path in files if path.suffix.casefold() == ".elog"]
    nonempty_elogs = [path for path in elogs if path.stat().st_size > 0]
    ci_files = [path for path in files if path.name.casefold() == "ci.ini"]
    analysis_outputs = [path for path in files if path.suffix.casefold() in {".ci", ".cal"}]
    capture_support_files = [
        path
        for path in files
        if path.parent.name.casefold() == ".capture"
        and path.name.casefold() != "compile.capture.json"
        and path.suffix.casefold() in {".command", ".stdout", ".stderr"}
    ]
    parser = next((path for path in parser_matches if path.parent == root), None)
    capture = next((path for path in capture_matches if path.parent.name.casefold() == ".capture"), None)
    if capture is None and len(capture_matches) == 1:
        capture = capture_matches[0]

    command_records: list[dict[str, Any]] = []
    runtime_evidence: list[dict[str, Any]] = []
    for log in sorted(runtime_logs, key=lambda path: str(path).casefold()):
        lines = _text_lines(log)
        markers = {
            marker: [number for number, line in enumerate(lines, 1) if marker.casefold() in line.casefold()]
            for marker in SUCCESS_MARKERS
        }
        runtime_evidence.append(
            {
                "path": _relative(log, root),
                "sha256": sha256_file(log),
                "success_markers": markers,
                "parsing_failed_lines": [
                    number for number, line in enumerate(lines, 1) if "parsing failed" in line.casefold()
                ],
            }
        )
        for number, line in enumerate(lines, 1):
            match = CSA_COMMAND.search(line)
            if match:
                if layout:
                    command_records.append(
                        _command_record(
                            match.group("command"),
                            log_path=log,
                            line_number=number,
                            expected_analysis=original,
                            expected_csa=Path(layout["expected_csa"]),
                            command_time_ns=_log_timestamp_ns(line),
                        )
                    )
    latest_command = max(command_records, key=_command_order) if command_records else None
    selected_command = latest_command if latest_command and latest_command["valid"] else None
    capture_summary = _load_capture(capture, root) if capture else None
    blockers: list[str] = []
    wrapper_blockers: list[str] = []
    if layout is None:
        blockers.append("분석 경로에서 static-arachne/works/<workspace> 기준점을 하나로 정할 수 없음.")
    if parser is None:
        blockers.append("parser.conf를 하나로 정할 수 없음.")
    if capture_summary is None or not capture_summary.get("valid"):
        blockers.append("유효한 .capture/compile.capture.json을 찾지 못함.")
    if selected_command is None:
        blockers.append("실행 가능한 STATIC csa.exe /Work 명령을 찾지 못함.")
    if capture_summary and capture_summary.get("valid"):
        source = capture_summary.get("source_file")
        kind = capture_summary.get("source_file_kind")
        wrapper = capture_summary.get("wrapper_path")
        if not isinstance(source, str) or not source:
            blockers.append("capture에 sourceFile이 없음.")
        elif not Path(source).is_file():
            blockers.append("capture의 sourceFile이 현재 컴퓨터에 없음.")
        if not isinstance(kind, str) or not kind:
            blockers.append("capture에 sourceFileKind가 없음.")
        if not isinstance(wrapper, str) or not wrapper:
            wrapper_blockers.append("capture에 wrapperPath가 없어 실제 Wrapper 반영 대상을 정할 수 없음.")
        if selected_command and isinstance(source, str) and not _same_path(selected_command["source_argument"], source):
            blockers.append("CSA 명령의 소스와 capture sourceFile이 다름.")

    selected_run = _selected_run_evidence(selected_command, root, analysis_outputs)
    adjacent_state = _adjacent_failure_state(original)
    positive_control = not nonempty_elogs and selected_run["success"] and adjacent_state["clean"]
    return {
        "analysis_copy": str(root),
        "original_analysis": str(original),
        "static_layout": layout,
        "artifacts": {
            "parser_conf": _relative(parser, root) if parser else None,
            "ci_ini": [_relative(path, root) for path in ci_files],
            "encoding_files": [_relative(path, root) for path in encodings],
            "runtime_logs": [_relative(path, root) for path in runtime_logs],
            "elog_files": [_relative(path, root) for path in elogs],
            "capture_files": [_relative(path, root) for path in capture_matches],
            "capture_support_files": [_relative(path, root) for path in capture_support_files],
        },
        "parser": _parser_summary(parser, root) if parser else None,
        "capture": capture_summary,
        "runtime": runtime_evidence,
        "csa_commands": command_records,
        "selected_csa": selected_command,
        "selected_run": selected_run,
        "elogs": [_summarize_elog(path, root) for path in elogs],
        "nonempty_elog_count": len(nonempty_elogs),
        "ci": [_small_text_record(path, root) for path in ci_files],
        "encodings": [_small_text_record(path, root, limit=16 * 1024) for path in encodings],
        "capture_support": [_capture_support_record(path, root) for path in capture_support_files],
        "adjacent_failure_state": adjacent_state,
        "positive_control": positive_control,
        "blockers": blockers,
        "wrapper_blockers": wrapper_blockers,
    }
