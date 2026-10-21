"""Run a logged STATIC csa.exe command in a copied analysis workspace."""

from __future__ import annotations

import codecs
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .common import (
    RecoveryError,
    authenticode_info,
    contained,
    decode_output,
    reject_link_chain,
    sha256_file,
    utc_now,
)
from .discovery import static_layout


OBSERVED_SUFFIXES = (".log", ".elog", ".ci", ".cal")
PARSING_FAILURE = re.compile(
    r"(?:Parsing\s+Failed|\[(?:Error|Fatal)\]|fatal\s+error|internal\s+(?:compiler|parser)\s+error)",
    re.IGNORECASE,
)
ENVIRONMENT_FAILURE = re.compile(
    r"(?:license.*(?:fail|error|invalid|expired)|cannot\s+(?:find|load).*(?:\.dll|library)|"
    r"cannot\s+get\s+temporary\s+directory|access\s+is\s+denied|permission\s+denied|"
    r"not\s+recognized\s+as|no\s+such\s+file)",
    re.IGNORECASE,
)
START_MARKER = re.compile(r"Main:\s*Parsing\s+Start", re.IGNORECASE)
FINISH_MARKER = re.compile(r"Main:\s*Parsing\s+Finished", re.IGNORECASE)
INSPECTION_FINISH = re.compile(r"Inspection:\s*Processing\s+Finished", re.IGNORECASE)
PROCESSING_FINISH = re.compile(r"Main:\s*Processing\s+Finished", re.IGNORECASE)


def _observed_files(root: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in OBSERVED_SUFFIXES
            and ".csa-run" not in {part.casefold() for part in path.parts}
        ],
        key=lambda path: str(path).casefold(),
    )


def _snapshot(root: Path) -> dict[str, dict[str, Any]]:
    return {
        path.relative_to(root).as_posix(): {
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
            "sha256": sha256_file(path),
        }
        for path in _observed_files(root)
    }


def _fresh(root: Path, before: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in _observed_files(root):
        name = path.relative_to(root).as_posix()
        current = {
            "path": name,
            "size": path.stat().st_size,
            "mtime_ns": path.stat().st_mtime_ns,
            "sha256": sha256_file(path),
        }
        previous = before.get(name)
        if previous is None or any(current[key] != previous[key] for key in ("size", "mtime_ns", "sha256")):
            current["change"] = "created" if previous is None else "modified"
            result.append(current)
    return result


def _read_limited(path: Path, limit: int = 4 * 1024 * 1024) -> bytes:
    with path.open("rb") as stream:
        size = path.stat().st_size
        if size <= limit:
            return stream.read()
        half = limit // 2
        head = stream.read(half)
        stream.seek(max(0, size - half))
        tail = stream.read(half)
        return head + b"\n[...middle omitted...]\n" + tail


def _fresh_text(workspace: Path, fresh: list[dict[str, Any]], stdout: Path, stderr: Path) -> str:
    chunks = [decode_output(_read_limited(stdout)), decode_output(_read_limited(stderr))]
    for item in fresh:
        path = workspace / item["path"]
        if path.suffix.casefold() in {".log", ".elog"}:
            chunks.append(decode_output(_read_limited(path)))
    return "\n".join(chunks)


def _stream_encoding(sample: bytes) -> str:
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    even = sample[0::2]
    odd = sample[1::2]
    if odd and odd.count(0) > len(odd) // 3:
        return "utf-16-le"
    if even and even.count(0) > len(even) // 3:
        return "utf-16-be"
    # CP949 keeps all failure/environment keywords as ASCII bytes. Replacing
    # undecodable non-ASCII bytes does not change those keywords.
    return "utf-8"


def _scan_output_files(paths: list[Path]) -> dict[str, str | None]:
    """Apply the real classifiers to complete outputs with bounded memory."""
    findings: dict[str, str | None] = {"failure": None, "environment": None}
    patterns = {"failure": PARSING_FAILURE, "environment": ENVIRONMENT_FAILURE}
    for path in paths:
        try:
            with path.open("rb") as stream:
                sample = stream.read(4096)
                stream.seek(0)
                decoder = codecs.getincrementaldecoder(_stream_encoding(sample))(errors="replace")
                carry = ""
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    window = carry + decoder.decode(chunk)
                    for name, pattern in patterns.items():
                        if findings[name] is None:
                            match = pattern.search(window)
                            if match:
                                findings[name] = f"{path}: {match.group(0)[:300]}"
                    carry = window[-64 * 1024 :]
                window = carry + decoder.decode(b"", final=True)
                for name, pattern in patterns.items():
                    if findings[name] is None:
                        match = pattern.search(window)
                        if match:
                            findings[name] = f"{path}: {match.group(0)[:300]}"
        except OSError as exc:
            raise RecoveryError("UnreadableCsaOutput", f"CSA 출력 전체를 검사할 수 없음: {path}") from exc
        if all(findings.values()):
            break
    return findings


def _scan_failure_files(paths: list[Path]) -> str | None:
    return _scan_output_files(paths)["failure"]


def _kill_tree(process: subprocess.Popen[Any]) -> str:
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            completed = subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                shell=False,
                check=False,
            )
            process.wait(timeout=10)
            return f"taskkill-exit-{completed.returncode}"
        except (OSError, subprocess.SubprocessError):
            process.kill()
            process.wait(timeout=10)
            return "parent-killed-only"
    try:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
        return "process-group-killed"
    except (OSError, subprocess.SubprocessError):
        process.kill()
        process.wait(timeout=10)
        return "parent-killed-only"


def _verification_temp(run_dir: Path) -> tuple[Path, bool]:
    if os.name == "nt":
        return Path(tempfile.mkdtemp(prefix="sr-")), True
    path = run_dir / "tmp"
    path.mkdir()
    return path, False


def _cleanup_verification_temp(path: Path, external: bool) -> dict[str, Any]:
    record: dict[str, Any] = {"path": str(path), "external": external, "removed": False, "error": None}
    if not external:
        return record
    try:
        shutil.rmtree(path)
        record["removed"] = True
    except OSError as exc:
        record["error"] = str(exc)
    return record


def invalidate_cached_evidence(workspace: Path, baseline_dir: Path) -> list[str]:
    """Move generated evidence away so only the new run can satisfy success gates."""
    invalidated: list[str] = []
    candidates = [
        path
        for path in workspace.rglob("*")
        if path.is_file()
        and (
            path.name.casefold() == "tu.cache.json"
            or path.suffix.casefold() == ".elog"
            or path.name.casefold().endswith("runtime.log")
        )
    ]
    for path in sorted(candidates, key=lambda item: str(item).casefold()):
        relative = path.relative_to(workspace)
        destination = baseline_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        invalidated.append(relative.as_posix())
    return invalidated


def _classify(
    *,
    exit_code: int | None,
    timed_out: bool,
    fresh: list[dict[str, Any]],
    text: str,
    parser_unchanged: bool,
    failure_evidence: str | None = None,
    environment_evidence: str | None = None,
    execution_trust_ok: bool = True,
) -> tuple[str, list[dict[str, Any]], dict[str, bool]]:
    marker_matches = [
        START_MARKER.search(text),
        FINISH_MARKER.search(text),
        INSPECTION_FINISH.search(text),
        PROCESSING_FINISH.search(text),
    ]
    ordered_markers = all(marker_matches) and all(
        marker_matches[index].start() < marker_matches[index + 1].start()
        for index in range(len(marker_matches) - 1)
    )
    gates = {
        "parsing_started": bool(marker_matches[0]),
        "parsing_finished": bool(marker_matches[1]),
        "inspection_finished": bool(marker_matches[2]),
        "processing_finished": bool(marker_matches[3]),
        "ordered_success_markers": bool(ordered_markers),
        "no_parsing_failure": not bool(PARSING_FAILURE.search(text)) and failure_evidence is None,
        "no_nonempty_elog": not any(
            item["path"].casefold().endswith(".elog") and item["size"] > 0 for item in fresh
        ),
        "fresh_analysis_output": any(
            item["path"].casefold().endswith((".ci", ".cal")) and item["size"] > 0 for item in fresh
        ),
        "parser_unchanged_during_run": parser_unchanged,
        "csa_unchanged_after_run": execution_trust_ok,
    }
    blockers: list[dict[str, Any]] = []
    if timed_out:
        blockers.append({"code": "CsaTimeout", "message": "csa.exe 실행 제한 시간을 넘김."})
        return "VerificationBlocked", blockers, gates
    if not execution_trust_ok:
        blockers.append(
            {
                "code": "CsaChangedAfterRun",
                "message": "실행 뒤 csa.exe 해시 또는 서명을 다시 확인하지 못함.",
            }
        )
        return "VerificationBlocked", blockers, gates
    environment = ENVIRONMENT_FAILURE.search(text)
    if environment or environment_evidence:
        blockers.append(
            {
                "code": "CsaEnvironmentFailure",
                "message": "라이선스, DLL, 권한 또는 실행 환경 문제로 검증할 수 없음.",
                "evidence": environment.group(0)[:300] if environment else environment_evidence,
            }
        )
        return "VerificationBlocked", blockers, gates
    failure = PARSING_FAILURE.search(text)
    nonempty_elog = next(
        (
            item
            for item in fresh
            if item["path"].casefold().endswith(".elog") and item["size"] > 0
        ),
        None,
    )
    if failure or failure_evidence or nonempty_elog:
        blockers.append(
            {
                "code": "CsaAnalysisFailure",
                "message": "이번 실행에서 분석 오류가 다시 발생함.",
                "evidence": (
                    failure.group(0)[:300]
                    if failure
                    else failure_evidence
                    if failure_evidence
                    else nonempty_elog["path"]
                ),
            }
        )
        return "RecoveryFailed", blockers, gates
    if exit_code != 0:
        blockers.append(
            {
                "code": "UnclassifiedCsaExit",
                "message": "분석 오류 근거 없이 csa.exe가 비정상 종료함.",
                "exit_code": exit_code,
            }
        )
        return "VerificationBlocked", blockers, gates
    missing = [name for name, passed in gates.items() if not passed]
    if missing:
        blockers.append(
            {
                "code": "MissingSuccessEvidence",
                "message": "종료 코드 0만으로는 복구 성공을 확정하지 않음.",
                "failed_gates": missing,
            }
        )
        return "VerificationBlocked", blockers, gates
    return "Recovered", blockers, gates


def _validate_csa_command(workspace: Path, command: dict[str, Any]) -> tuple[list[str], Path]:
    args = list(command.get("args") or [])
    if len(args) != 4 or command.get("work_index") != 1 or str(args[1]).casefold() != "/work":
        raise RecoveryError("InvalidCsaCommand", "실행 직전 명령이 csa.exe /Work analysis source 네 인수와 다름.")
    analysis_argument = command.get("analysis_argument")
    if (
        not isinstance(analysis_argument, str)
        or not Path(analysis_argument).is_absolute()
        or os.path.normcase(str(Path(args[2]).resolve())) != os.path.normcase(str(Path(analysis_argument).resolve()))
    ):
        raise RecoveryError("InvalidCsaCommand", "수집 때 고정한 원본 분석 경로 인자가 아님.")
    layout = static_layout(analysis_argument)
    if not layout:
        raise RecoveryError("UnsafeCsa", "원본 분석 경로에서 STATIC workspace 기준점을 정할 수 없음.")
    executable = Path(args[0])
    expected_executable = Path(layout["expected_csa"])
    recorded_executable = Path(str(command.get("expected_executable") or ""))
    if (
        not executable.is_absolute()
        or executable.resolve() != expected_executable.resolve()
        or recorded_executable.resolve() != expected_executable.resolve()
        or executable.name.casefold() != "csa.exe"
        or not command.get("trusted_layout")
    ):
        raise RecoveryError("UnsafeCsa", "현재 STATIC workspace에 고정된 csa.exe가 아님.")
    try:
        reject_link_chain(executable)
    except (OSError, RecoveryError) as exc:
        raise RecoveryError("UnsafeCsa", "csa.exe 경로에 링크 또는 reparse point가 있음.") from exc
    executable = executable.resolve()
    if not executable.is_file() or contained(executable, workspace):
        raise RecoveryError("UnsafeCsa", "csa.exe가 없거나 검증 자료 폴더 안에 있음.")
    source = command.get("source_argument")
    if (
        not isinstance(source, str)
        or not Path(source).is_absolute()
        or os.path.normcase(str(Path(args[3]).resolve())) != os.path.normcase(str(Path(source).resolve()))
    ):
        raise RecoveryError("InvalidCsaCommand", "수집 때 고정한 원본 소스 인자가 아님.")
    source_path = Path(source)
    try:
        reject_link_chain(source_path)
    except (OSError, RecoveryError) as exc:
        raise RecoveryError("UnsafeSource", "원본 소스 경로에 링크 또는 reparse point가 있음.") from exc
    expected_source_hash = command.get("source_sha256")
    if not source_path.is_file() or not isinstance(expected_source_hash, str) or not expected_source_hash:
        raise RecoveryError("MissingSourceFingerprint", "수집한 원본 소스 SHA-256이 없음.")
    if sha256_file(source_path) != expected_source_hash:
        raise RecoveryError("SourceChanged", "수집 후 원본 소스가 변경됨.")
    expected_fingerprint = command.get("executable_sha256")
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        raise RecoveryError("MissingCsaFingerprint", "수집한 csa.exe SHA-256이 없음.")
    if sha256_file(executable) != expected_fingerprint:
        raise RecoveryError("CsaChanged", "수집 후 csa.exe가 변경됨.")
    expected_signature = command.get("authenticode")
    current_signature = authenticode_info(executable)
    if (
        not isinstance(expected_signature, dict)
        or not expected_signature.get("valid")
        or not current_signature.get("valid")
        or current_signature.get("thumbprint") != expected_signature.get("thumbprint")
        or current_signature.get("subject") != expected_signature.get("subject")
    ):
        raise RecoveryError("UntrustedCsaSignature", "csa.exe의 Suresofttech 서명이 없거나 수집 시점과 다름.")
    args[0] = str(executable)
    args[2] = str(workspace)
    return args, executable


def run_csa(
    workspace: str | Path,
    command: dict[str, Any],
    expected_parser: str | Path,
    *,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    workspace = Path(workspace).resolve()
    parser = Path(expected_parser).resolve()
    if not workspace.is_dir() or not parser.is_file() or parser.parent != workspace:
        raise RecoveryError("UnsafeVerificationInput", "검증 workspace와 parser.conf 관계가 올바르지 않음.")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise RecoveryError("InvalidTimeout", "timeout은 1초 이상의 정수여야 함.")
    args, executable = _validate_csa_command(workspace, command)
    parser_hash = sha256_file(parser)
    before = _snapshot(workspace)
    run_dir = workspace / ".csa-run"
    if run_dir.exists():
        raise RecoveryError("AttemptAlreadyUsed", "이 검증 workspace는 이미 실행됨.")
    run_dir.mkdir()
    temporary, external_temporary = _verification_temp(run_dir)
    stdout_path, stderr_path = run_dir / "stdout.log", run_dir / "stderr.log"
    env = os.environ.copy()
    env.update({"TEMP": str(temporary), "TMP": str(temporary), "TMPDIR": str(temporary)})
    popen_options: dict[str, Any]
    if os.name == "nt":
        popen_options = {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        }
    else:
        popen_options = {"start_new_session": True}
    started_at = utc_now()
    started = time.monotonic()
    timed_out = False
    termination = "not-needed"
    exit_code: int | None = None
    launch_error: OSError | None = None
    try:
        with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
            process = subprocess.Popen(
                args,
                cwd=str(executable.parent),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                **popen_options,
            )
            try:
                exit_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                termination = _kill_tree(process)
                exit_code = process.returncode
            except BaseException:
                _kill_tree(process)
                raise
    except OSError as exc:
        launch_error = exc
    finally:
        temporary_result = _cleanup_verification_temp(temporary, external_temporary)
    if launch_error is not None:
        return {
            "status": "VerificationBlocked",
            "blockers": [{"code": "CsaLaunchFailed", "message": str(launch_error)}],
            "command": args,
            "command_shell": False,
            "started_at": started_at,
            "finished_at": utc_now(),
            "workspace": str(workspace),
            "temporary_directory": temporary_result,
        }
    fresh = _fresh(workspace, before)
    text = _fresh_text(workspace, fresh, stdout_path, stderr_path)
    failure_paths = [stdout_path, stderr_path]
    failure_paths.extend(
        workspace / item["path"]
        for item in fresh
        if item["path"].casefold().endswith((".log", ".elog"))
    )
    full_scan = _scan_output_files(failure_paths)
    expected_signature = command.get("authenticode")
    csa_postcheck: dict[str, Any] = {
        "path": str(executable),
        "expected_sha256": command.get("executable_sha256"),
        "actual_sha256": None,
        "authenticode": None,
        "trusted": False,
        "error": None,
    }
    try:
        reject_link_chain(executable)
        actual_csa_hash = sha256_file(executable)
        actual_signature = authenticode_info(executable)
        csa_postcheck.update({"actual_sha256": actual_csa_hash, "authenticode": actual_signature})
        csa_postcheck["trusted"] = (
            actual_csa_hash == command.get("executable_sha256")
            and isinstance(expected_signature, dict)
            and expected_signature.get("valid")
            and actual_signature.get("valid")
            and actual_signature.get("subject") == expected_signature.get("subject")
            and actual_signature.get("thumbprint") == expected_signature.get("thumbprint")
        )
    except (OSError, RecoveryError) as exc:
        csa_postcheck["error"] = str(exc)
    parser_unchanged = parser.is_file() and sha256_file(parser) == parser_hash
    status, blockers, gates = _classify(
        exit_code=exit_code,
        timed_out=timed_out,
        fresh=fresh,
        text=text,
        parser_unchanged=parser_unchanged,
        failure_evidence=full_scan["failure"],
        environment_evidence=full_scan["environment"],
        execution_trust_ok=bool(csa_postcheck["trusted"]),
    )
    return {
        "status": status,
        "blockers": blockers,
        "started_at": started_at,
        "finished_at": utc_now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "timeout_seconds": timeout_seconds,
        "timed_out": timed_out,
        "process_tree_termination": termination,
        "temporary_directory": temporary_result,
        "command": args,
        "command_shell": False,
        "workspace": str(workspace),
        "exit_code": exit_code,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "csa_postcheck": csa_postcheck,
        "parser_conf": {"path": str(parser), "sha256": parser_hash, "unchanged_during_run": parser_unchanged},
        "success_gates": gates,
        "fresh_outputs": fresh,
    }
