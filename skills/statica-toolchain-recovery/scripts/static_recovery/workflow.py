"""Persistent state machine for local STATIC recovery attempts."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .common import (
    RecoveryError,
    assert_hashes,
    authenticode_info,
    contained,
    digest_json,
    exclusive_file_lock,
    read_json,
    require_contained,
    reject_link_chain,
    sha256_file,
    tree_hashes,
    unique_child,
    utc_now,
    write_json,
)
from .config_editor import apply_candidate, validate_candidate
from .discovery import discover
from .verification import invalidate_cached_evidence, run_csa


SCHEMA_VERSION = 1
MAX_CANDIDATES = 3


def case_lock(run_dir: str | Path):
    lock_path = Path(run_dir).resolve() / "case.lock"
    return exclusive_file_lock(
        lock_path,
        owner=str(Path(run_dir).resolve()),
        busy_code="CaseBusy",
        busy_message="다른 복구 작업이 이 case를 사용 중임",
    )


def _case_path(run_dir: str | Path) -> Path:
    return Path(run_dir).resolve() / "case.json"


def load_case(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    case = read_json(_case_path(run_dir))
    if case.get("schema_version") != SCHEMA_VERSION:
        raise RecoveryError("UnsupportedCase", "지원하지 않는 case.json 버전임.")
    if case.get("run_dir") != str(run_dir):
        raise RecoveryError("UnsafeCase", "case.json의 run_dir이 실제 폴더와 다름.")
    expected_input = (run_dir / "inputs" / "analysis").resolve()
    if case.get("input_root") != str(expected_input):
        raise RecoveryError("UnsafeCase", "case.json의 input_root가 고정된 수집 폴더와 다름.")
    return case


def save_case(case: dict[str, Any]) -> None:
    run_dir = Path(str(case.get("run_dir", ""))).resolve()
    if not run_dir.is_dir():
        raise RecoveryError("UnsafeCase", "case run_dir이 없음.")
    case["updated_at"] = utc_now()
    write_json(run_dir / "case.json", case)


def _wrapper_snapshot(evidence: dict[str, Any], run_dir: Path) -> tuple[dict[str, Any], list[str]]:
    capture = evidence.get("capture") or {}
    raw_wrapper = capture.get("wrapper_path")
    source_kind = str(capture.get("source_file_kind") or "")
    info: dict[str, Any] = {
        "wrapper_path": raw_wrapper,
        "root": None,
        "metadata_path": None,
        "config_path": None,
        "config_field": None,
        "source_file_kind": source_kind,
        "trusted_layout": False,
        "original_hashes": {},
    }
    blockers: list[str] = []
    if not isinstance(raw_wrapper, str) or not raw_wrapper:
        return info, ["wrapperPath가 없어 Wrapper 대상을 정할 수 없음."]
    raw_wrapper_path = Path(raw_wrapper)
    try:
        reject_link_chain(raw_wrapper_path)
    except (OSError, RecoveryError) as exc:
        return info, [f"Wrapper 경로에 링크 또는 읽을 수 없는 항목이 있음: {exc}"]
    wrapper_path = raw_wrapper_path.resolve()
    root = wrapper_path.parent
    layout = evidence.get("static_layout") or {}
    wrapper_parent = Path(str(layout.get("wrapper_parent") or "")).resolve()
    expected_root = Path(str(layout.get("expected_wrapper_root") or "")).resolve()
    expected_workspace = Path(str(layout.get("workspace_root") or "")).resolve()
    trusted_location = bool(layout) and root.parent == wrapper_parent
    info.update({"wrapper_path": str(wrapper_path), "root": str(root)})
    if not trusted_location:
        return info, ["capture Wrapper가 현재 STATIC 설치의 wrapper/<name> 직속 실행 파일이 아님."]
    if not wrapper_path.is_file():
        return info, ["capture의 Wrapper 실행 파일이 현재 컴퓨터에 없음."]
    metadata_path = root / "wrapper.toolchain.json"
    info["metadata_path"] = str(metadata_path)
    if not metadata_path.is_file():
        return info, ["wrapper.toolchain.json이 없음."]
    try:
        reject_link_chain(metadata_path)
    except (OSError, RecoveryError) as exc:
        return info, [f"Wrapper metadata가 안전한 일반 파일이 아님: {exc}"]
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return info, [f"wrapper.toolchain.json을 읽을 수 없음: {exc}"]
    toolchain = metadata.get("toolchain") if isinstance(metadata, dict) else None
    if not isinstance(toolchain, dict):
        return info, ["wrapper.toolchain.json의 toolchain 객체가 없음."]
    if "workspace" in metadata:
        raw_metadata_workspace = metadata.get("workspace")
        if not isinstance(raw_metadata_workspace, str) or not raw_metadata_workspace:
            return info, ["wrapper.toolchain.json의 workspace가 유효한 절대 경로가 아님."]
        metadata_workspace = Path(raw_metadata_workspace)
        if not metadata_workspace.is_absolute() or metadata_workspace.resolve() != expected_workspace:
            return info, ["wrapper.toolchain.json의 workspace가 현재 STATIC workspace와 다름."]
        workspace_binding = "metadata"
        info["metadata_workspace"] = str(metadata_workspace.resolve())
    elif root == expected_root:
        workspace_binding = "conventional-name-fallback"
        info["metadata_workspace"] = None
    else:
        return info, ["Wrapper 폴더 이름이 workspace와 다르고 metadata workspace 연결도 없음."]
    info.update({"trusted_layout": True, "workspace_binding": workspace_binding})
    normalized_kind = source_kind.strip().casefold()
    if normalized_kind == "c":
        config_field = "cconfigFile"
    elif normalized_kind in {"c++", "cpp", "cxx", "cc"}:
        config_field = "cppConfigFile"
    else:
        return info, [f"지원 여부를 확인할 수 없는 sourceFileKind임: {source_kind or '<empty>'}"]
    config_name = toolchain.get(config_field)
    if not isinstance(config_name, str) or not config_name:
        config_name = "parser.c.conf" if config_field == "cconfigFile" else "parser.cpp.conf"
    config_path = (root / config_name).resolve()
    if not contained(config_path, root) or not config_path.is_file():
        return info, [f"Wrapper 설정 파일을 안전하게 찾을 수 없음: {config_name}"]
    try:
        reject_link_chain(config_path)
    except (OSError, RecoveryError) as exc:
        return info, [f"Wrapper 설정이 안전한 일반 파일이 아님: {exc}"]
    original_hashes = tree_hashes(root, absolute=True, exclude_names={".static-recovery.lock"})
    snapshot = run_dir / "inputs" / "wrapper-snapshot"
    snapshot.mkdir(parents=True)
    shutil.copy2(metadata_path, snapshot / "wrapper.toolchain.json")
    shutil.copy2(config_path, snapshot / config_path.name)
    info.update(
        {
            "metadata_path": str(metadata_path),
            "config_path": str(config_path),
            "config_field": config_field,
            "original_hashes": original_hashes,
            "snapshot": str(snapshot),
        }
    )
    return info, blockers


def _ensure_originals(case: dict[str, Any], *, check_wrapper: bool = True) -> None:
    assert_hashes(case["analysis_path"], case["analysis_original_hashes"], absolute=True)
    assert_hashes(case["input_root"], case["input_hashes"])
    source = case.get("source") or {}
    if source.get("path") and source.get("sha256"):
        path = Path(source["path"])
        try:
            reject_link_chain(path)
        except (OSError, RecoveryError) as exc:
            raise RecoveryError("OriginalChanged", f"분석 소스를 안전하게 다시 읽을 수 없음: {path}") from exc
        if not path.is_file() or sha256_file(path) != source["sha256"]:
            raise RecoveryError("OriginalChanged", f"분석 소스가 바뀌었거나 사라짐: {path}")
    adjacent = case.get("adjacent_failure_state") or {}
    adjacent_raw_path = adjacent.get("path")
    adjacent_path = Path(adjacent_raw_path) if isinstance(adjacent_raw_path, str) and adjacent_raw_path else None
    if adjacent.get("exists"):
        if adjacent_path is None or not adjacent_path.is_file() or sha256_file(adjacent_path) != adjacent.get("sha256"):
            raise RecoveryError("OriginalChanged", f"analyze.failed.json이 바뀌었거나 사라짐: {adjacent_path}")
        snapshot = Path(str(adjacent.get("snapshot") or ""))
        if not snapshot.is_file() or sha256_file(snapshot) != adjacent.get("sha256"):
            raise RecoveryError("CollectedEvidenceChanged", "수집한 analyze.failed.json 복사본이 바뀜.")
    elif adjacent_path is not None and adjacent_path.exists():
        raise RecoveryError("OriginalChanged", f"수집 뒤 analyze.failed.json이 새로 생김: {adjacent_path}")
    if not check_wrapper:
        return
    wrapper = case.get("wrapper") or {}
    expected_wrapper_hashes = wrapper.get("original_hashes") or {}
    applied = case.get("wrapper_apply") or {}
    if case.get("state") == "ReadyForRebuild" and applied.get("status") == "ReadyForRebuild":
        expected_wrapper_hashes = applied.get("post_hashes") or {}
        if not expected_wrapper_hashes:
            raise RecoveryError("WrapperChanged", "반영 뒤 Wrapper 기준 해시가 없음.")
    if expected_wrapper_hashes:
        wrapper_root = Path(str(wrapper.get("root") or ""))
        try:
            current_wrapper_hashes = tree_hashes(
                wrapper_root,
                absolute=True,
                exclude_names={".static-recovery.lock"},
            )
        except (OSError, RecoveryError) as exc:
            raise RecoveryError("WrapperChanged", f"Wrapper 파일 집합을 안전하게 다시 읽을 수 없음: {wrapper_root}") from exc
        if current_wrapper_hashes != expected_wrapper_hashes:
            expected_names = set(expected_wrapper_hashes)
            current_names = set(current_wrapper_hashes)
            raise RecoveryError(
                "WrapperChanged",
                f"수집 또는 반영 뒤 Wrapper 파일 집합이나 내용이 변경됨: {wrapper_root}",
                {
                    "added": sorted(current_names - expected_names, key=str.casefold),
                    "removed": sorted(expected_names - current_names, key=str.casefold),
                    "changed": sorted(
                        (
                            name
                            for name in expected_names & current_names
                            if expected_wrapper_hashes[name] != current_wrapper_hashes[name]
                        ),
                        key=str.casefold,
                    ),
                },
            )


def start_case(analysis_path: str | Path, run_dir: str | Path) -> dict[str, Any]:
    analysis = Path(analysis_path).resolve()
    run = Path(run_dir).resolve()
    try:
        reject_link_chain(analysis)
        reject_link_chain(run)
    except (OSError, RecoveryError) as exc:
        raise RecoveryError("UnsafePath", "입력 또는 run_dir 경로에 링크/reparse point가 있음.") from exc
    if not analysis.is_dir():
        raise RecoveryError("MissingAnalysis", f"분석 오류 폴더가 없음: {analysis}")
    if run.exists():
        raise RecoveryError("WorkspaceExists", f"run_dir은 새 경로여야 함: {run}")
    if contained(run, analysis):
        raise RecoveryError("UnsafePath", "run_dir을 입력 분석 폴더 안에 만들 수 없음.")
    original_hashes = tree_hashes(analysis, absolute=True)
    run.mkdir(parents=True)
    input_root = run / "inputs" / "analysis"
    try:
        shutil.copytree(analysis, input_root)
    except OSError as exc:
        raise RecoveryError("ArtifactCopyFailed", f"분석 자료를 복사할 수 없음: {exc}") from exc
    assert_hashes(analysis, original_hashes, absolute=True)
    evidence = discover(input_root, analysis)
    blockers = list(evidence.get("blockers", []))
    selected_csa = evidence.get("selected_csa")
    if selected_csa:
        executable = Path(selected_csa["executable"])
        try:
            reject_link_chain(executable)
            selected_csa["executable_sha256"] = sha256_file(executable)
            selected_csa["authenticode"] = authenticode_info(executable)
            if not selected_csa["authenticode"]["valid"]:
                blockers.append("csa.exe의 유효한 Suresofttech Authenticode 서명을 확인하지 못함.")
        except (OSError, RecoveryError) as exc:
            selected_csa["valid"] = False
            selected_csa.setdefault("blockers", []).append(str(exc))
            blockers.append(f"csa.exe가 안전한 일반 파일이 아님: {exc}")
    capture = evidence.get("capture") or {}
    source_path = capture.get("source_file")
    source_hash = None
    if isinstance(source_path, str) and Path(source_path).is_file():
        try:
            reject_link_chain(Path(source_path))
            source_hash = sha256_file(source_path)
        except (OSError, RecoveryError) as exc:
            blockers.append(f"원본 소스가 안전한 일반 파일이 아님: {exc}")
    source = {
        "path": source_path,
        "kind": capture.get("source_file_kind"),
        "sha256": source_hash,
    }
    if selected_csa:
        selected_csa["source_sha256"] = source_hash
    adjacent_state = dict(evidence.get("adjacent_failure_state") or {})
    if adjacent_state.get("exists"):
        adjacent_path = Path(str(adjacent_state.get("path") or ""))
        try:
            reject_link_chain(adjacent_path)
            adjacent_snapshot = run / "inputs" / "adjacent-state" / "analyze.failed.json"
            adjacent_snapshot.parent.mkdir(parents=True)
            shutil.copy2(adjacent_path, adjacent_snapshot)
            adjacent_state["snapshot"] = str(adjacent_snapshot)
        except (OSError, RecoveryError) as exc:
            blockers.append(f"analyze.failed.json을 안전하게 수집할 수 없음: {exc}")
    wrapper, wrapper_blockers = _wrapper_snapshot(evidence, run)
    wrapper_blockers = [*evidence.get("wrapper_blockers", []), *wrapper_blockers]
    wrapper["blockers"] = wrapper_blockers
    evidence_digest = digest_json(evidence)
    if blockers:
        state = "GuidanceOnly"
    elif evidence.get("positive_control"):
        state = "PositiveControl"
    elif evidence.get("nonempty_elog_count", 0) > 0:
        state = "Ready"
    else:
        state = "GuidanceOnly"
        blockers.append("오류 `.elog` 또는 정상 완료 근거가 없어 복구 필요 여부를 정할 수 없음.")
    case: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "case_id": run.name,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "state": state,
        "analysis_path": str(analysis),
        "run_dir": str(run),
        "input_root": str(input_root),
        "analysis_original_hashes": original_hashes,
        "input_hashes": tree_hashes(input_root),
        "evidence_digest": evidence_digest,
        "source": source,
        "adjacent_failure_state": adjacent_state,
        "csa": selected_csa,
        "wrapper": wrapper,
        "blockers": blockers,
        "attempts": [],
        "active_attempt": None,
        "active_wrapper_apply": None,
        "recovered_candidate": None,
    }
    assert_hashes(analysis, original_hashes, absolute=True)
    write_json(run / "evidence.json", evidence)
    write_json(run / "case.json", case)
    return case


def inspect_case(run_dir: str | Path) -> dict[str, Any]:
    case = load_case(run_dir)
    try:
        _ensure_originals(case)
        integrity = "Unchanged"
    except RecoveryError as exc:
        integrity = exc.as_dict()
    return {"case": case, "integrity": integrity}


def _candidate_digest(candidate: dict[str, Any]) -> str:
    return digest_json(
        {
            "id": candidate.get("id"),
            "reason": candidate.get("reason"),
            "evidence": candidate.get("evidence"),
            "risk": candidate.get("risk"),
            "changes": candidate.get("changes"),
        }
    )


def _recover_stale_verification(case: dict[str, Any], run: Path) -> None:
    if case.get("state") != "Verifying":
        return
    active = case.get("active_attempt")
    try:
        if not isinstance(active, dict):
            raise RecoveryError("InterruptedVerificationUnknown", "중단된 검증의 active_attempt 기록이 없음.")
        attempt = Path(str(active.get("attempt_dir") or "")).resolve()
        attempts_root = (run / "attempts").resolve()
        if not contained(attempt, attempts_root) or attempt.parent != attempts_root:
            raise RecoveryError("InterruptedVerificationUnknown", "중단된 검증 시도 경로가 안전하지 않음.")
        candidate_path = attempt / "candidate.json"
        candidate = read_json(candidate_path)
        validate_candidate(candidate)
        digest = _candidate_digest(candidate)
        if digest != active.get("candidate_digest"):
            raise RecoveryError("InterruptedVerificationUnknown", "중단된 검증 candidate가 active_attempt와 다름.")
    except (OSError, RecoveryError) as exc:
        case["state"] = "SupportEscalation"
        case.setdefault("blockers", []).append(f"중단된 검증 상태를 안전하게 복구하지 못함: {exc}")
        save_case(case)
        raise RecoveryError(
            "InterruptedVerificationUnknown",
            "이전 검증이 비정상 종료됐고 시도 기록을 안전하게 복구하지 못함.",
        ) from exc

    finished_at = utc_now()
    recovery = {
        "status": "VerificationBlocked",
        "code": "PreviousVerificationInterrupted",
        "message": "이전 검증 프로세스가 최종 상태 저장 전에 종료됨. 같은 후보를 새 시도에서 재검증해야 함.",
        "attempt_dir": str(attempt),
        "candidate_id": candidate["id"],
        "candidate_digest": digest,
        "recovered_at": finished_at,
    }
    write_json(attempt / "interrupted-recovery.json", recovery)
    case.setdefault("attempts", []).append(
        {
            "attempt_dir": str(attempt),
            "candidate_id": candidate["id"],
            "candidate_digest": digest,
            "status": "VerificationBlocked",
            "finished_at": finished_at,
        }
    )
    case["active_attempt"] = None
    case["state"] = "VerificationBlocked"
    case.setdefault("blockers", []).append(recovery["message"])
    save_case(case)


def verify_candidate(
    run_dir: str | Path,
    candidate_path: str | Path,
    *,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    run = Path(run_dir).resolve()
    candidate_file = Path(candidate_path).resolve()
    if candidate_file.stat().st_size > 1024 * 1024:
        raise RecoveryError("CandidateTooLarge", "candidate JSON은 1 MiB를 넘을 수 없음.")
    candidate = read_json(candidate_file)
    validate_candidate(candidate)
    digest = _candidate_digest(candidate)
    with case_lock(run):
        case = load_case(run)
        _ensure_originals(case)
        _recover_stale_verification(case, run)
        if case["state"] not in {"Ready", "Retrying", "VerificationBlocked"}:
            raise RecoveryError("InvalidState", f"현재 상태에서는 후보를 검증할 수 없음: {case['state']}")
        attempt_history = list(case.get("attempts", []))
        if case["state"] == "VerificationBlocked":
            latest = attempt_history[-1] if attempt_history else None
            if (
                not isinstance(latest, dict)
                or latest.get("status") != "VerificationBlocked"
                or latest.get("candidate_digest") != digest
            ):
                raise RecoveryError(
                    "BlockedCandidatePending",
                    "환경 문제로 막힌 마지막 후보를 먼저 같은 내용으로 재검증해야 함.",
                )
        completed_digests = {
            item.get("candidate_digest")
            for item in case.get("attempts", [])
            if item.get("status") != "VerificationBlocked"
        }
        previous_same = [item for item in case.get("attempts", []) if item.get("candidate_digest") == digest]
        if previous_same and previous_same[-1].get("status") != "VerificationBlocked":
            raise RecoveryError("DuplicateCandidate", "이미 판정이 끝난 같은 후보임.")
        if digest not in completed_digests and len(completed_digests) >= MAX_CANDIDATES:
            raise RecoveryError("CandidateLimit", f"서로 다른 후보는 최대 {MAX_CANDIDATES}개까지 검증함.")
        attempts_root = run / "attempts"
        attempts_root.mkdir(exist_ok=True)
        attempt = unique_child(attempts_root, "attempt")
        workspace = attempt / "workspace"
        attempt.mkdir()
        shutil.copytree(case["input_root"], workspace)
        write_json(attempt / "candidate.json", candidate)
        evidence = read_json(run / "evidence.json")
        if digest_json(evidence) != case.get("evidence_digest"):
            raise RecoveryError("CollectedEvidenceChanged", "수집한 evidence.json이 바뀜.")
        parser_relative = evidence["artifacts"]["parser_conf"]
        if not isinstance(parser_relative, str) or not parser_relative or Path(parser_relative).is_absolute():
            raise RecoveryError("MissingParserConfig", "parser.conf 경로가 case에 없음.")
        parser = require_contained(workspace / Path(parser_relative), workspace)
        try:
            reject_link_chain(parser)
        except (OSError, RecoveryError) as exc:
            raise RecoveryError("UnsafeParserConfig", "복사본 parser.conf가 안전한 일반 파일이 아님.") from exc
        if not parser.is_file():
            raise RecoveryError("MissingParserConfig", "복사본 parser.conf가 없음.")
        edit = apply_candidate(parser, candidate)
        (attempt / "proposal.diff").write_text(edit["diff"], encoding="utf-8", newline="\n")
        baseline = attempt / "baseline-generated"
        invalidated = invalidate_cached_evidence(workspace, baseline)
        command = dict(case.get("csa") or {})
        if not command:
            raise RecoveryError("MissingCsa", "case에 검증할 csa 명령이 없음.")
        case["state"] = "Verifying"
        case["active_attempt"] = {
            "attempt_dir": str(attempt),
            "candidate_id": candidate["id"],
            "candidate_digest": digest,
            "started_at": utc_now(),
        }
        save_case(case)
        pending_interrupt: BaseException | None = None
        try:
            result = run_csa(workspace, command, parser, timeout_seconds=timeout_seconds)
        except (OSError, RecoveryError) as exc:
            error = exc.as_dict() if isinstance(exc, RecoveryError) else {
                "code": "OperatingSystemError",
                "message": str(exc),
                "details": {},
            }
            result = {
                "status": "VerificationBlocked",
                "blockers": [error],
                "started_at": utc_now(),
                "finished_at": utc_now(),
                "workspace": str(workspace),
            }
        except BaseException as exc:
            pending_interrupt = exc
            result = {
                "status": "VerificationBlocked",
                "blockers": [
                    {
                        "code": "VerificationInterrupted",
                        "message": "CSA 검증이 인터럽트되어 같은 후보의 재검증이 필요함.",
                        "details": {"exception_type": type(exc).__name__},
                    }
                ],
                "started_at": utc_now(),
                "finished_at": utc_now(),
                "workspace": str(workspace),
            }
        result.update(
            {
                "attempt_dir": str(attempt),
                "candidate_id": candidate["id"],
                "candidate_digest": digest,
                "config_edit": edit,
                "invalidated_cache_and_old_evidence": invalidated,
            }
        )
        write_json(attempt / "verification.json", result)
        originals_intact = True
        try:
            _ensure_originals(case)
        except RecoveryError as exc:
            originals_intact = False
            result["status"] = "VerificationBlocked"
            result.setdefault("blockers", []).append(exc.as_dict())
            write_json(attempt / "verification.json", result)
            case["state"] = "SupportEscalation"
            case.setdefault("blockers", []).append(exc.message)
        summary = {
            "attempt_dir": str(attempt),
            "candidate_id": candidate["id"],
            "candidate_digest": digest,
            "status": result["status"],
            "finished_at": result.get("finished_at"),
        }
        case["attempts"].append(summary)
        if not originals_intact:
            case["state"] = "SupportEscalation"
        elif result["status"] == "Recovered":
            case["state"] = "Recovered"
            case["recovered_candidate"] = {
                "path": str(attempt / "candidate.json"),
                "digest": digest,
                "attempt_dir": str(attempt),
            }
        elif result["status"] == "RecoveryFailed":
            new_completed = completed_digests | {digest}
            case["state"] = "SupportEscalation" if len(new_completed) >= MAX_CANDIDATES else "Retrying"
        else:
            case["state"] = "VerificationBlocked"
        case["active_attempt"] = None
        save_case(case)
        if pending_interrupt is not None:
            raise pending_interrupt
        return result
