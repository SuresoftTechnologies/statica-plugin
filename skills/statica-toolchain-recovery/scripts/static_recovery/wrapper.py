"""Plan and explicitly apply a verified candidate to one STATIC Wrapper."""

from __future__ import annotations

import difflib
import os
import tempfile
from pathlib import Path
from typing import Any

from .common import (
    RecoveryError,
    contained,
    digest_json,
    exclusive_file_lock,
    process_is_alive,
    read_json,
    read_text_preserved,
    reject_link_chain,
    sha256_bytes,
    sha256_file,
    tree_hashes,
    unique_child,
    utc_now,
    write_json,
)
from .config_editor import render_candidate, validate_candidate
from .workflow import _ensure_originals, case_lock, load_case, save_case


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


def _wrapper_lock(wrapper_root: Path, owner: Path):
    lock_path = wrapper_root / ".static-recovery.lock"
    return exclusive_file_lock(
        lock_path,
        owner=str(owner),
        busy_code="WrapperBusy",
        busy_message="다른 복구 작업이 이 Wrapper를 변경 중임",
    )


def _tracked_hashes(wrapper: dict[str, Any]) -> dict[str, str]:
    root = Path(str(wrapper.get("root") or ""))
    try:
        return tree_hashes(root, absolute=True, exclude_names={".static-recovery.lock"})
    except (OSError, RecoveryError) as exc:
        raise RecoveryError("WrapperChanged", f"Wrapper 파일 집합을 안전하게 읽을 수 없음: {root}") from exc


def plan_wrapper(run_dir: str | Path) -> dict[str, Any]:
    run = Path(run_dir).resolve()
    with case_lock(run):
        case = load_case(run)
        _ensure_originals(case)
        if case.get("state") != "Recovered" or not case.get("recovered_candidate"):
            raise RecoveryError("InvalidState", "복사본 검증이 Recovered인 case만 Wrapper 반영을 계획할 수 있음.")
        recovered = case["recovered_candidate"]
        candidate_path = Path(recovered["path"]).resolve()
        if not contained(candidate_path, run):
            raise RecoveryError("UnsafeCandidate", "검증된 candidate가 run_dir 밖에 있음.")
        candidate = read_json(candidate_path)
        validate_candidate(candidate)
        if _candidate_digest(candidate) != recovered["digest"]:
            raise RecoveryError("CandidateChanged", "복구 성공 뒤 candidate가 변경됨.")
        wrapper = case.get("wrapper") or {}
        wrapper_root = Path(str(wrapper.get("root") or "")).resolve()
        target = Path(str(wrapper.get("config_path") or "")).resolve()
        if not wrapper.get("trusted_layout") or not target.is_file() or not contained(target, wrapper_root):
            raise RecoveryError("UnsafeWrapperTarget", "검증된 Wrapper 설정 대상을 찾을 수 없음.")
        for raw_path, expected_hash in (wrapper.get("original_hashes") or {}).items():
            original = Path(raw_path)
            try:
                reject_link_chain(original)
            except (OSError, RecoveryError) as exc:
                raise RecoveryError("UnsafeWrapperTarget", f"Wrapper 구성 파일이 안전하지 않음: {original}") from exc
            if not original.is_file() or sha256_file(original) != expected_hash:
                raise RecoveryError("WrapperChanged", f"수집 뒤 Wrapper 구성 파일이 변경됨: {original}")
        expected_before = (wrapper.get("original_hashes") or {}).get(str(target))
        if not expected_before or sha256_file(target) != expected_before:
            raise RecoveryError("WrapperChanged", "수집 뒤 Wrapper 설정이 변경됨. 새 case가 필요함.")
        document = read_text_preserved(target)
        rendered, after_bytes = render_candidate(document, candidate)
        diff = "".join(
            difflib.unified_diff(
                document.text.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=str(target),
                tofile=str(target),
            )
        )
        plans_root = run / "wrapper-plans"
        plans_root.mkdir(exist_ok=True)
        plan_dir = unique_child(plans_root, "plan")
        plan_dir.mkdir()
        plan: dict[str, Any] = {
            "schema_version": 1,
            "created_at": utc_now(),
            "run_dir": str(run),
            "candidate_path": str(candidate_path),
            "candidate_digest": recovered["digest"],
            "candidate_id": candidate["id"],
            "candidate_reason": candidate["reason"],
            "candidate_risk": candidate["risk"],
            "candidate_changes": candidate.get("changes"),
            "wrapper_root": str(wrapper_root),
            "wrapper_name": wrapper_root.name,
            "target_config": str(target),
            "config_field": wrapper.get("config_field"),
            "before_sha256": expected_before,
            "after_sha256": sha256_bytes(after_bytes),
            "diff": diff,
            "wrapper_original_hashes": wrapper.get("original_hashes") or {},
            "caller_next_step": "Wrapper 반영 성공 뒤 호출자가 대상 프로그램을 rebuild하고 STATIC 재분석을 실행함.",
        }
        plan["plan_digest"] = digest_json(plan)
        plan_path = plan_dir / "publish-plan.json"
        write_json(plan_path, plan)
        return {"plan_path": str(plan_path), **plan}


def _error_record(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, RecoveryError):
        return exc.as_dict()
    return {"code": type(exc).__name__, "message": str(exc), "details": {}}


def _safe_hash(path: Path) -> str | None:
    try:
        return sha256_file(path) if path.is_file() else None
    except OSError:
        return None


def _relative_wrapper_hashes(wrapper_root: Path, hashes: dict[str, str]) -> dict[str, str]:
    relative_hashes: dict[str, str] = {}
    for raw_path, expected_hash in hashes.items():
        path = Path(raw_path).resolve()
        if not contained(path, wrapper_root):
            raise RecoveryError("UnsafeWrapperTarget", f"Wrapper 백업 대상이 루트 밖에 있음: {path}")
        relative = path.relative_to(wrapper_root).as_posix()
        if relative in relative_hashes:
            raise RecoveryError("UnsafeWrapperTarget", f"Wrapper 백업 경로가 중복됨: {relative}")
        relative_hashes[relative] = expected_hash
    return relative_hashes


def _backup_wrapper_tree(
    wrapper_root: Path,
    original_hashes: dict[str, str],
    backup_root: Path,
) -> dict[str, str]:
    relative_hashes = _relative_wrapper_hashes(wrapper_root, original_hashes)
    backup_root.mkdir()
    for relative, expected_hash in sorted(relative_hashes.items(), key=lambda item: item[0].casefold()):
        source = (wrapper_root / Path(relative)).resolve()
        try:
            reject_link_chain(source)
        except (OSError, RecoveryError) as exc:
            raise RecoveryError("WrapperBackupFailed", f"Wrapper 백업 대상이 안전하지 않음: {source}") from exc
        data = source.read_bytes()
        if sha256_bytes(data) != expected_hash:
            raise RecoveryError("WrapperChanged", f"백업 중 Wrapper 파일이 변경됨: {source}")
        destination = backup_root / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    if tree_hashes(backup_root) != relative_hashes:
        raise RecoveryError("WrapperBackupFailed", "Wrapper 전체 백업 해시를 확인하지 못함.")
    return relative_hashes


def _move_current_file_to_quarantine(
    path: Path,
    destination: Path,
    expected_hash: str,
    wrapper_root: Path,
) -> Path:
    """Move the exact current name away before any delete/restore operation."""

    reject_link_chain(path)
    descriptor, stage_name = tempfile.mkstemp(
        prefix=".static-recovery-quarantine-",
        dir=path.parent,
    )
    os.close(descriptor)
    stage = Path(stage_name)
    stage.unlink()
    try:
        # On the supported Windows host rename refuses an existing destination.
        # The unpredictable same-directory name keeps the move on one volume.
        os.rename(path, stage)
        reject_link_chain(stage)
        moved_data = stage.read_bytes()
        moved_hash = sha256_bytes(moved_data)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if stage.stat().st_dev == destination.parent.stat().st_dev:
            os.rename(stage, destination)
            preserved = destination
        else:
            with destination.open("xb") as stream:
                stream.write(moved_data)
                stream.flush()
                os.fsync(stream.fileno())
            persistent_root = wrapper_root.parent / ".static-recovery-quarantine" / sha256_bytes(
                str(destination).encode("utf-8")
            )
            persistent_root.mkdir(parents=True, exist_ok=False)
            preserved = persistent_root / path.name
            os.rename(stage, preserved)
        if sha256_file(destination) != moved_hash or _safe_hash(preserved) != moved_hash:
            raise RecoveryError(
                "ConcurrentWrapperChange",
                f"Wrapper 파일 격리 중 내용이 바뀜: {path}",
                {"preserved": str(preserved), "quarantine": str(destination)},
            )
        if moved_hash != expected_hash:
            raise RecoveryError(
                "ConcurrentWrapperChange",
                f"Wrapper 파일이 격리 시점 전에 다른 내용으로 교체됨: {path}",
                {
                    "quarantine": str(destination),
                    "preserved": str(preserved),
                    "moved_sha256": moved_hash,
                },
            )
        return preserved
    except BaseException:
        # Never delete an unverified moved file. Its path is included in the
        # error/tree snapshot for manual recovery when copying did not finish.
        raise


def _create_file_without_replace(path: Path, data: bytes, expected_hash: str) -> None:
    """Publish complete bytes only when the destination name is still absent."""

    reject_link_chain(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.restore-",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256_file(temporary) != expected_hash:
            raise RecoveryError("WrapperRestoreFailed", f"복원용 임시 파일 해시가 맞지 않음: {path}")
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise RecoveryError("ConcurrentWrapperChange", f"Wrapper 복원 중 같은 경로가 다시 생김: {path}") from exc
        if _safe_hash(path) != expected_hash:
            raise RecoveryError("ConcurrentWrapperChange", f"Wrapper 복원 직후 내용이 바뀜: {path}")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except OSError:
            pass


def _validate_wrapper_metadata(wrapper: dict[str, Any], target: Path) -> dict[str, str]:
    wrapper_root = Path(str(wrapper.get("root") or "")).resolve()
    metadata = Path(str(wrapper.get("metadata_path") or "")).resolve()
    field = wrapper.get("config_field")
    if field not in {"cconfigFile", "cppConfigFile"} or not contained(metadata, wrapper_root):
        raise RecoveryError("WrapperMetadataChanged", "Wrapper metadata 경로나 config field가 유효하지 않음.")
    try:
        reject_link_chain(metadata)
        value = read_json(metadata)
    except (OSError, RecoveryError) as exc:
        raise RecoveryError("WrapperMetadataChanged", "설정 저장 뒤 Wrapper metadata를 읽을 수 없음.") from exc
    toolchain = value.get("toolchain") if isinstance(value, dict) else None
    configured = toolchain.get(field) if isinstance(toolchain, dict) else None
    selection = "metadata"
    if not isinstance(configured, str) or not configured.strip():
        configured = "parser.c.conf" if field == "cconfigFile" else "parser.cpp.conf"
        selection = "conventional-fallback"
    configured_path = (wrapper_root / configured).resolve()
    if configured_path != target or not contained(configured_path, wrapper_root):
        raise RecoveryError("WrapperMetadataChanged", "설정 저장 뒤 Wrapper metadata의 config 연결이 바뀜.")
    return {
        "path": str(metadata),
        "config_field": field,
        "config_path": str(configured_path),
        "selection": selection,
    }


def _restore_wrapper_tree(
    *,
    wrapper: dict[str, Any],
    backup_root: Path,
    backup_dir: Path,
    quarantine_stage: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    wrapper_root = Path(str(wrapper.get("root") or "")).resolve()
    expected_hashes = wrapper.get("original_hashes") or {}
    record: dict[str, Any] = {
        "attempted": True,
        "restored": False,
        "backup_root": str(backup_root),
        "quarantined_added_files": [],
        "quarantined_changed_files": [],
        "persistent_quarantine_files": [],
        "error": None,
    }
    final_hashes: dict[str, str] = {}
    try:
        reject_link_chain(wrapper_root)
        relative_hashes = _relative_wrapper_hashes(wrapper_root, expected_hashes)
        if tree_hashes(backup_root) != relative_hashes:
            raise RecoveryError("WrapperBackupChanged", "원복용 Wrapper 전체 백업 해시가 바뀜.")
        current_hashes = _tracked_hashes(wrapper)
        extra_paths = sorted(set(current_hashes) - set(expected_hashes), key=str.casefold)
        quarantine_root = backup_dir / "rollback-quarantine" / quarantine_stage
        record["quarantine_root"] = str(quarantine_root)
        for raw_path in extra_paths:
            path = Path(raw_path).resolve()
            reject_link_chain(path)
            if not contained(path, wrapper_root) or _safe_hash(path) != current_hashes[raw_path]:
                raise RecoveryError("ConcurrentWrapperChange", f"추가 Wrapper 파일이 원복 직전에 바뀜: {path}")
            relative = path.relative_to(wrapper_root)
            destination = quarantine_root / "added" / relative
            preserved = _move_current_file_to_quarantine(
                path,
                destination,
                current_hashes[raw_path],
                wrapper_root,
            )
            record["quarantined_added_files"].append(str(destination))
            record["persistent_quarantine_files"].append(str(preserved))

        for raw_path, expected_hash in sorted(expected_hashes.items(), key=lambda item: item[0].casefold()):
            path = Path(raw_path).resolve()
            current_snapshot = current_hashes.get(raw_path)
            current_now = _safe_hash(path)
            if current_now == expected_hash:
                continue
            if current_now != current_snapshot:
                raise RecoveryError("ConcurrentWrapperChange", f"Wrapper 파일이 원복 직전에 바뀜: {path}")
            relative = path.relative_to(wrapper_root)
            if current_now is not None:
                destination = quarantine_root / "changed" / relative
                preserved = _move_current_file_to_quarantine(
                    path,
                    destination,
                    current_snapshot,
                    wrapper_root,
                )
                record["quarantined_changed_files"].append(str(destination))
                record["persistent_quarantine_files"].append(str(preserved))
            backup = backup_root / relative
            data = backup.read_bytes()
            if sha256_bytes(data) != expected_hash:
                raise RecoveryError("WrapperBackupChanged", f"원복용 백업 파일 해시가 바뀜: {backup}")
            reject_link_chain(path.parent)
            path.parent.mkdir(parents=True, exist_ok=True)
            _create_file_without_replace(path, data, expected_hash)
            if _safe_hash(path) != expected_hash:
                raise RecoveryError("WrapperRestoreFailed", f"Wrapper 파일 원복 해시가 맞지 않음: {path}")

        final_hashes = _tracked_hashes(wrapper)
        record["restored"] = final_hashes == expected_hashes
        if not record["restored"]:
            raise RecoveryError("WrapperRestoreFailed", "Wrapper 전체 파일 집합과 해시를 원본으로 되돌리지 못함.")
    except BaseException as exc:
        record["error"] = _error_record(exc)
        try:
            final_hashes = _tracked_hashes(wrapper)
        except (OSError, RecoveryError):
            final_hashes = {}
    return record, final_hashes


def _rollback_after_mutation(
    *,
    target: Path,
    plan: dict[str, Any],
    backup_dir: Path,
    wrapper_backup_root: Path,
    wrapper: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], bool]:
    rollback_attempts = backup_dir / "rollback-attempts"
    rollback_attempts.mkdir(exist_ok=True)
    rollback_dir = unique_child(rollback_attempts, "rollback")
    rollback_dir.mkdir()
    rollback: dict[str, Any] = {
        "config_restored": False,
        "config_restore_error": None,
        "current_config_sha256": _safe_hash(target),
        "attempt_dir": str(rollback_dir),
    }
    current_hash = rollback["current_config_sha256"]
    if current_hash == plan["after_sha256"]:
        config_owned = True
    elif current_hash == plan["before_sha256"]:
        config_owned = True
        rollback["config_restored"] = True
    elif current_hash is None:
        # A hard exit can land after this transaction atomically moved the
        # target away and before it published the next bytes. A validated
        # Applying journal plus full backup makes absence an owned state; the
        # no-replace restore below still refuses a concurrently recreated name.
        config_owned = True
        rollback["config_missing_during_transaction"] = True
    else:
        config_owned = False
        rollback["config_restore_error"] = {
            "code": "ConcurrentWrapperChange",
            "message": "현재 설정이 스킬이 쓴 해시와 달라 자동 덮어쓰기를 중단함.",
            "details": {"current_sha256": current_hash},
        }

    try:
        restored_hashes = _tracked_hashes(wrapper)
    except RecoveryError:
        restored_hashes = {}
    expected_hashes = wrapper.get("original_hashes") or {}
    if config_owned and restored_hashes != expected_hashes:
        tree_restore, restored_hashes = _restore_wrapper_tree(
            wrapper=wrapper,
            backup_root=wrapper_backup_root,
            backup_dir=rollback_dir,
            quarantine_stage="restore",
        )
        rollback["tree_restore"] = tree_restore
        rollback["config_restored"] = restored_hashes.get(str(target)) == plan["before_sha256"]
        if not rollback["config_restored"] and tree_restore.get("error"):
            rollback["config_restore_error"] = tree_restore["error"]
    else:
        rollback["tree_restore"] = {
            "attempted": False,
            "restored": restored_hashes == expected_hashes,
            "reason": "Wrapper 전체가 이미 원본이거나 config 소유권을 확인하지 못함.",
        }

    rollback_ok = bool(rollback["config_restored"]) and restored_hashes == expected_hashes
    return rollback, restored_hashes, rollback_ok


def _finish_failed_apply(
    *,
    result: dict[str, Any],
    case: dict[str, Any],
    run: Path,
    backup_dir: Path,
    target: Path,
    plan: dict[str, Any],
    wrapper: dict[str, Any],
    wrapper_backup_root: Path,
) -> dict[str, Any]:
    handoff_cleanup_error: dict[str, Any] | None = None
    handoff = run / "handoff.json"
    if handoff.exists():
        try:
            handoff.unlink()
        except OSError as exc:
            handoff_cleanup_error = _error_record(exc)
    rollback, restored_hashes, rollback_ok = _rollback_after_mutation(
        target=target,
        plan=plan,
        backup_dir=backup_dir,
        wrapper_backup_root=wrapper_backup_root,
        wrapper=wrapper,
    )
    result["rollback"] = rollback
    result["rollback_post_hashes"] = restored_hashes
    result["status"] = "ApplyFailedRolledBack" if rollback_ok else "RollbackIncomplete"
    result["finished_at"] = utc_now()
    if handoff_cleanup_error is not None:
        rollback_ok = False
        result["status"] = "RollbackIncomplete"
        result["handoff_cleanup_error"] = handoff_cleanup_error
    try:
        write_json(backup_dir / "apply-result.json", result)
    except BaseException as exc:
        result["audit_persistence_error"] = _error_record(exc)
    case["state"] = "Recovered" if rollback_ok else "SupportEscalation"
    case["blockers"] = [
        "Wrapper 반영 실패 후 원복 완료."
        if rollback_ok
        else "Wrapper 반영 실패 후 안전한 자동 원복과 상태 정리를 완전히 확인하지 못함."
    ]
    case["wrapper_apply"] = result
    case["active_wrapper_apply"] = None
    try:
        save_case(case)
    except BaseException as exc:
        result["case_persistence_error"] = _error_record(exc)
    return result


def _interrupted_apply_materials(
    *,
    case: dict[str, Any],
    run: Path,
) -> tuple[
    dict[str, Any],
    Path,
    Path,
    Path,
    dict[str, Any],
]:
    active = case.get("active_wrapper_apply")
    if not isinstance(active, dict):
        raise RecoveryError("InterruptedApplyUnknown", "중단된 Wrapper 반영 journal이 없음.")
    selected_plan = Path(str(active.get("plan_path") or "")).resolve()
    plans_root = (run / "wrapper-plans").resolve()
    if (
        not contained(selected_plan, plans_root)
        or selected_plan.name != "publish-plan.json"
        or selected_plan.parent.parent != plans_root
    ):
        raise RecoveryError("InterruptedApplyUnknown", "중단된 Wrapper 계획 경로가 안전하지 않음.")
    plan = read_json(selected_plan)
    stored_digest = plan.pop("plan_digest", None)
    if (
        not stored_digest
        or digest_json(plan) != stored_digest
        or stored_digest != active.get("plan_digest")
    ):
        raise RecoveryError("InterruptedApplyUnknown", "중단된 Wrapper 계획 digest가 맞지 않음.")
    plan["plan_digest"] = stored_digest

    backup_dir = Path(str(active.get("backup_dir") or "")).resolve()
    backups_root = (run / "wrapper-backups").resolve()
    wrapper_backup_root = Path(str(active.get("wrapper_backup_root") or "")).resolve()
    if (
        backup_dir.parent != backups_root
        or not contained(backup_dir, backups_root)
        or wrapper_backup_root != (backup_dir / "wrapper-tree").resolve()
    ):
        raise RecoveryError("InterruptedApplyUnknown", "중단된 Wrapper 백업 경로가 안전하지 않음.")

    wrapper = case.get("wrapper") or {}
    wrapper_root = Path(str(wrapper.get("root") or "")).resolve()
    target = Path(str(plan.get("target_config") or "")).resolve()
    expected_target = Path(str(wrapper.get("config_path") or "")).resolve()
    original_hashes = wrapper.get("original_hashes") or {}
    if (
        plan.get("run_dir") != str(run)
        or plan.get("wrapper_root") != str(wrapper_root)
        or plan.get("wrapper_original_hashes") != original_hashes
        or active.get("candidate_digest") != plan.get("candidate_digest")
        or active.get("candidate_digest") != (case.get("recovered_candidate") or {}).get("digest")
        or active.get("wrapper_root") != str(wrapper_root)
        or target != expected_target
        or not contained(target, wrapper_root)
        or active.get("target_config") != str(target)
        or active.get("before_sha256") != plan.get("before_sha256")
        or active.get("after_sha256") != plan.get("after_sha256")
    ):
        raise RecoveryError("InterruptedApplyUnknown", "중단된 Wrapper journal과 case/plan이 서로 다름.")
    try:
        reject_link_chain(wrapper_root)
        reject_link_chain(wrapper_backup_root)
        reject_link_chain(target)
    except (OSError, RecoveryError) as exc:
        raise RecoveryError("InterruptedApplyUnknown", "중단된 Wrapper 경로가 안전하지 않음.") from exc

    expected_backup_hashes = _relative_wrapper_hashes(wrapper_root, original_hashes)
    if active.get("wrapper_backup_hashes_digest") != digest_json(expected_backup_hashes):
        raise RecoveryError("InterruptedApplyUnknown", "중단된 Wrapper 백업 목록 digest가 journal과 다름.")
    if tree_hashes(wrapper_backup_root) != expected_backup_hashes:
        raise RecoveryError("WrapperBackupChanged", "중단된 반영의 Wrapper 전체 백업 해시가 맞지 않음.")
    backup = (wrapper_backup_root / target.relative_to(wrapper_root)).resolve()
    if not contained(backup, wrapper_backup_root) or not backup.is_file():
        raise RecoveryError("WrapperBackupChanged", "중단된 반영의 target 백업이 없음.")
    before_bytes = backup.read_bytes()
    if sha256_bytes(before_bytes) != plan.get("before_sha256"):
        raise RecoveryError("WrapperBackupChanged", "중단된 반영의 target 백업 해시가 맞지 않음.")

    rollback_journal_path = (backup_dir / "rollback.json").resolve()
    if active.get("rollback_journal") != str(rollback_journal_path):
        raise RecoveryError("InterruptedApplyUnknown", "중단된 rollback journal 경로가 다름.")
    rollback_journal = read_json(rollback_journal_path)
    if (
        rollback_journal.get("target_config") != str(target)
        or rollback_journal.get("before_sha256") != plan.get("before_sha256")
        or rollback_journal.get("planned_after_sha256") != plan.get("after_sha256")
        or rollback_journal.get("backup_path") != str(backup)
        or rollback_journal.get("wrapper_backup_root") != str(wrapper_backup_root)
        or rollback_journal.get("wrapper_backup_hashes") != expected_backup_hashes
    ):
        raise RecoveryError("InterruptedApplyUnknown", "중단된 반영의 rollback journal이 백업과 다름.")

    return (
        plan,
        backup_dir,
        wrapper_backup_root,
        target,
        wrapper,
    )


def _recover_interrupted_wrapper_apply(case: dict[str, Any], run: Path) -> dict[str, Any]:
    active = case.get("active_wrapper_apply")
    try:
        (
            plan,
            backup_dir,
            wrapper_backup_root,
            target,
            wrapper,
        ) = _interrupted_apply_materials(case=case, run=run)
    except (OSError, RecoveryError) as exc:
        error = exc if isinstance(exc, RecoveryError) else RecoveryError(
            "InterruptedApplyUnknown",
            f"중단된 Wrapper 반영 자료를 읽을 수 없음: {exc}",
        )
        case["state"] = "SupportEscalation"
        case.setdefault("blockers", []).append(error.message)
        case["wrapper_apply"] = {
            "status": "InterruptedApplyUnknown",
            "error": error.as_dict(),
            "active_wrapper_apply": active,
            "finished_at": utc_now(),
        }
        save_case(case)
        if error is exc:
            raise error
        raise error from exc

    wrapper_root = Path(str(wrapper.get("root") or "")).resolve()
    child_pid = active.get("child_pid") if isinstance(active, dict) else None
    if isinstance(child_pid, int) and not isinstance(child_pid, bool) and process_is_alive(child_pid):
        raise RecoveryError(
            "InterruptedApplyStillRunning",
            f"이전 반영 프로세스가 아직 실행 중이라 원복을 기다림: PID {child_pid}",
        )
    with _wrapper_lock(wrapper_root, run):
        handoff = run / "handoff.json"
        if handoff.exists():
            try:
                handoff.unlink()
            except OSError as exc:
                error = RecoveryError(
                    "HandoffCleanupFailed",
                    "중단된 반영의 ReadyForRebuild 인계 파일을 먼저 무효화하지 못함.",
                    {"error": str(exc)},
                )
                case["state"] = "SupportEscalation"
                case.setdefault("blockers", []).append(error.message)
                case["wrapper_apply"] = {
                    "status": "InterruptedApplyRollbackIncomplete",
                    "error": error.as_dict(),
                    "active_wrapper_apply": active,
                    "finished_at": utc_now(),
                }
                save_case(case)
                raise error from exc
        result: dict[str, Any] = {
            "status": "RecoveringInterruptedApply",
            "started_at": utc_now(),
            "interrupted_started_at": active.get("started_at") if isinstance(active, dict) else None,
            "interrupted_phase": active.get("phase") if isinstance(active, dict) else None,
            "plan_path": str(active.get("plan_path")) if isinstance(active, dict) else None,
            "plan_digest": plan["plan_digest"],
            "target_config": str(target),
            "before_sha256": plan["before_sha256"],
            "after_sha256": plan["after_sha256"],
            "backup_path": str(wrapper_backup_root / target.relative_to(wrapper_root)),
        }
        rollback, restored_hashes, rollback_ok = _rollback_after_mutation(
            target=target,
            plan=plan,
            backup_dir=backup_dir,
            wrapper_backup_root=wrapper_backup_root,
            wrapper=wrapper,
        )
        result["rollback"] = rollback
        result["rollback_post_hashes"] = restored_hashes
        result["status"] = "InterruptedApplyRolledBack" if rollback_ok else "InterruptedApplyRollbackIncomplete"
        result["finished_at"] = utc_now()
        try:
            write_json(backup_dir / "apply-result.json", result)
        except BaseException as exc:
            result["audit_persistence_error"] = _error_record(exc)
        case["state"] = "Recovered" if rollback_ok else "SupportEscalation"
        case["blockers"] = [
            "강제 종료된 Wrapper 반영을 원본으로 되돌림. 다시 반영하려면 명령을 한 번 더 실행해야 함."
            if rollback_ok
            else "강제 종료된 Wrapper 반영을 안전하게 완전히 되돌리고 상태를 정리했는지 확인하지 못함."
        ]
        case["wrapper_apply"] = result
        case["active_wrapper_apply"] = None
        save_case(case)
        return result


def _complete_wrapper_transaction(
    *,
    case: dict[str, Any],
    run: Path,
    selected_plan: Path,
    stored_digest: str,
    plan: dict[str, Any],
    candidate: dict[str, Any],
    recovered: dict[str, Any],
    wrapper: dict[str, Any],
    wrapper_root: Path,
    target: Path,
    after_bytes: bytes,
    backup_dir: Path,
    backup: Path,
    wrapper_backup_root: Path,
    started_at: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "started_at": started_at,
        "plan_path": str(selected_plan),
        "plan_digest": stored_digest,
        "candidate_id": candidate["id"],
        "candidate_reason": candidate["reason"],
        "candidate_risk": candidate["risk"],
        "target_config": str(target),
        "before_sha256": plan["before_sha256"],
        "after_sha256": plan["after_sha256"],
        "backup_path": str(backup),
        "rollback": None,
    }
    try:
        previous_target = backup_dir / "forward-quarantine" / target.relative_to(wrapper_root)
        preserved_previous = _move_current_file_to_quarantine(
            target,
            previous_target,
            plan["before_sha256"],
            wrapper_root,
        )
        result["forward_previous_target"] = str(previous_target)
        result["forward_previous_target_persistent"] = str(preserved_previous)
        _create_file_without_replace(target, after_bytes, plan["after_sha256"])
        written_hash = _safe_hash(target)
        result["post_config_sha256"] = written_hash
        if written_hash != plan["after_sha256"]:
            raise RecoveryError("WrapperWriteMismatch", "Wrapper 설정을 계획한 바이트로 저장하지 못함.")
        post_hashes = _tracked_hashes(wrapper)
        result["tracked_postcheck_error"] = None
        failure_reasons: list[str] = []
        if set(post_hashes) != set(wrapper.get("original_hashes") or {}):
            failure_reasons.append("설정 저장 뒤 Wrapper 파일 집합 변경")
        if post_hashes.get(str(target)) != plan["after_sha256"]:
            failure_reasons.append("추적한 target config 해시 불일치")
        unexpected_changes = sorted(
            (
                path
                for path, before_hash in (wrapper.get("original_hashes") or {}).items()
                if path != str(target)
                and post_hashes.get(path) != before_hash
            ),
            key=str.casefold,
        )
        result["unexpected_other_changes"] = unexpected_changes
        if unexpected_changes:
            failure_reasons.append("target 외 Wrapper 파일이 변경됨")
        try:
            result["wrapper_metadata_postcheck"] = _validate_wrapper_metadata(wrapper, target)
        except RecoveryError as exc:
            result["wrapper_metadata_postcheck"] = exc.as_dict()
            failure_reasons.append("설정 저장 뒤 Wrapper metadata 연결 검증 실패")
        if failure_reasons:
            result["failure_reasons"] = failure_reasons
            return _finish_failed_apply(
                result=result,
                case=case,
                run=run,
                backup_dir=backup_dir,
                target=target,
                plan=plan,
                wrapper=wrapper,
                wrapper_backup_root=wrapper_backup_root,
            )
        result["status"] = "ReadyForRebuild"
        result["post_hashes"] = post_hashes
        result["finished_at"] = utc_now()
        write_json(backup_dir / "apply-result.json", result)
        handoff = {
            "state": "ReadyForRebuild",
            "plan_digest": stored_digest,
            "requires_case_state": "ReadyForRebuild",
            "candidate": {
                "id": candidate["id"],
                "reason": candidate["reason"],
                "risk": candidate["risk"],
                "digest": recovered["digest"],
            },
            "wrapper": wrapper_root.name,
            "config": str(target),
            "diff": plan["diff"],
            "backup": str(backup),
            "next_steps": ["대상 프로그램 rebuild", "STATIC 재분석", "같은 파일의 분석 오류 해소 확인"],
            "not_run_by_skill": ["대상 프로그램 rebuild", "STATIC 재분석"],
        }
        write_json(run / "handoff.json", handoff)
        case["state"] = "ReadyForRebuild"
        case["wrapper_apply"] = result
        case["active_wrapper_apply"] = None
        save_case(case)
        return result
    except BaseException as exc:
        result["transaction_error"] = _error_record(exc)
        failed = _finish_failed_apply(
            result=result,
            case=case,
            run=run,
            backup_dir=backup_dir,
            target=target,
            plan=plan,
            wrapper=wrapper,
            wrapper_backup_root=wrapper_backup_root,
        )
        if not isinstance(exc, Exception):
            raise
        return failed


def apply_wrapper(
    run_dir: str | Path,
    plan_path: str | Path,
) -> dict[str, Any]:
    run = Path(run_dir).resolve()
    selected_plan = Path(plan_path).resolve()
    if not contained(selected_plan, run):
        raise RecoveryError("UnsafePlan", "publish-plan.json이 run_dir 밖에 있음.")
    with case_lock(run):
        case = load_case(run)
        if case.get("state") == "Applying":
            _ensure_originals(case, check_wrapper=False)
            return _recover_interrupted_wrapper_apply(case, run)
        _ensure_originals(case)
        if case.get("state") != "Recovered":
            raise RecoveryError("InvalidState", "Recovered 상태에서만 Wrapper를 반영할 수 있음.")
        plan = read_json(selected_plan)
        stored_digest = plan.pop("plan_digest", None)
        if not stored_digest or digest_json(plan) != stored_digest:
            raise RecoveryError("PlanChanged", "publish-plan.json digest가 맞지 않음.")
        plan["plan_digest"] = stored_digest
        recovered = case.get("recovered_candidate") or {}
        if plan.get("candidate_digest") != recovered.get("digest"):
            raise RecoveryError("PlanMismatch", "현재 복구 후보와 Wrapper 계획이 다름.")
        wrapper = case.get("wrapper") or {}
        wrapper_root = Path(str(wrapper.get("root") or "")).resolve()
        target = Path(str(plan.get("target_config") or "")).resolve()
        if target != Path(str(wrapper.get("config_path") or "")).resolve() or not contained(target, wrapper_root):
            raise RecoveryError("UnsafeWrapperTarget", "계획의 Wrapper 설정 대상이 case와 다름.")
        try:
            reject_link_chain(target)
        except (OSError, RecoveryError) as exc:
            raise RecoveryError("UnsafeWrapperTarget", "Wrapper 설정이 안전한 일반 파일이 아님.") from exc
        candidate_path = Path(str(plan.get("candidate_path") or "")).resolve()
        if not contained(candidate_path, run):
            raise RecoveryError("UnsafeCandidate", "계획의 candidate가 run_dir 밖에 있음.")
        candidate = read_json(candidate_path)
        validate_candidate(candidate)
        if _candidate_digest(candidate) != plan.get("candidate_digest"):
            raise RecoveryError("CandidateChanged", "계획 뒤 candidate가 바뀜.")
        candidate_changes = candidate.get("changes")
        if plan.get("candidate_changes") != candidate_changes:
            raise RecoveryError("PlanMismatch", "계획에 기록된 설정 변경이 검증 candidate와 다름.")
        if plan.get("wrapper_original_hashes") != (wrapper.get("original_hashes") or {}):
            raise RecoveryError("PlanMismatch", "계획에 기록된 Wrapper 전체 해시가 현재 case와 다름.")
        document = read_text_preserved(target)
        _, after_bytes = render_candidate(document, candidate)
        if sha256_bytes(after_bytes) != plan.get("after_sha256"):
            raise RecoveryError("PlanMismatch", "다시 계산한 Wrapper 설정이 계획과 다름.")
        with _wrapper_lock(wrapper_root, run):
            original_hashes = wrapper.get("original_hashes") or {}
            if _tracked_hashes(wrapper) != original_hashes:
                raise RecoveryError("WrapperChanged", "공유 잠금 획득 전후에 Wrapper 파일 집합이나 내용이 변경됨.")
            for raw_path, expected_hash in original_hashes.items():
                original = Path(raw_path)
                try:
                    reject_link_chain(original)
                except (OSError, RecoveryError) as exc:
                    raise RecoveryError("WrapperChanged", f"Wrapper 구성 파일이 안전하지 않음: {original}") from exc
                if not original.is_file() or sha256_file(original) != expected_hash:
                    raise RecoveryError("WrapperChanged", f"계획 뒤 Wrapper 구성 파일이 변경됨: {original}")
            before_bytes = target.read_bytes()
            if sha256_bytes(before_bytes) != plan.get("before_sha256"):
                raise RecoveryError("WrapperChanged", "계획 뒤 Wrapper 설정이 바뀜.")
            backups_root = run / "wrapper-backups"
            backups_root.mkdir(exist_ok=True)
            backup_dir = unique_child(backups_root, "backup")
            backup_dir.mkdir()
            wrapper_backup_root = backup_dir / "wrapper-tree"
            wrapper_backup_hashes = _backup_wrapper_tree(wrapper_root, original_hashes, wrapper_backup_root)
            backup = wrapper_backup_root / target.relative_to(wrapper_root)
            started_at = utc_now()
            write_json(
                backup_dir / "rollback.json",
                {
                    "created_at": started_at,
                    "target_config": str(target),
                    "before_sha256": sha256_bytes(before_bytes),
                    "planned_after_sha256": sha256_bytes(after_bytes),
                    "backup_path": str(backup),
                    "wrapper_backup_root": str(wrapper_backup_root),
                    "wrapper_backup_hashes": wrapper_backup_hashes,
                },
            )
            # 공유 lock 안에서도 외부 편집은 가능하므로 쓰기 바로 전에 다시 비교한다.
            if _tracked_hashes(wrapper) != original_hashes:
                raise RecoveryError("WrapperChanged", "전체 백업 뒤 Wrapper 파일 집합이나 내용이 바뀜.")
            if not target.is_file() or sha256_file(target) != plan["before_sha256"]:
                raise RecoveryError("WrapperChanged", "쓰기 직전 Wrapper 설정이 바뀜.")
            case["state"] = "Applying"
            case["active_wrapper_apply"] = {
                "phase": "MutationStarting",
                "plan_path": str(selected_plan),
                "plan_digest": stored_digest,
                "candidate_digest": recovered.get("digest"),
                "wrapper_root": str(wrapper_root),
                "target_config": str(target),
                "before_sha256": plan["before_sha256"],
                "after_sha256": plan["after_sha256"],
                "backup_dir": str(backup_dir),
                "wrapper_backup_root": str(wrapper_backup_root),
                "wrapper_backup_hashes_digest": digest_json(wrapper_backup_hashes),
                "rollback_journal": str(backup_dir / "rollback.json"),
                "started_at": started_at,
            }
            save_case(case)
            return _complete_wrapper_transaction(
                case=case,
                run=run,
                selected_plan=selected_plan,
                stored_digest=stored_digest,
                plan=plan,
                candidate=candidate,
                recovered=recovered,
                wrapper=wrapper,
                wrapper_root=wrapper_root,
                target=target,
                after_bytes=after_bytes,
                backup_dir=backup_dir,
                backup=backup,
                wrapper_backup_root=wrapper_backup_root,
                started_at=started_at,
            )
