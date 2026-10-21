"""Lossless, exact-line parser.conf editing."""

from __future__ import annotations

import difflib
from collections import Counter
from pathlib import Path
from typing import Any

from .common import RecoveryError, TextDocument, atomic_write_bytes, encode_text_preserved, read_text_preserved


MANUAL_ONLY_PREFIXES = ("cs_ignore_", "cs_replace_code", "cs_disable_keyword", "cs_allow_")


def _manual_only(line: str) -> bool:
    key = line.strip().split("=", 1)[0].strip().casefold()
    return any(key.startswith(prefix) for prefix in MANUAL_ONLY_PREFIXES)


def _changes(candidate: dict[str, Any]) -> dict[str, Any]:
    value: Any = candidate.get("changes")
    if not isinstance(value, dict):
        raise RecoveryError("InvalidCandidate", "설정 변경 내용은 JSON 객체여야 함.")
    replacements = value.get("replacements", [])
    additions = value.get("append_lines", [])
    if not isinstance(replacements, list) or not isinstance(additions, list):
        raise RecoveryError("InvalidCandidate", "replacements와 append_lines는 배열이어야 함.")
    if not replacements and not additions:
        raise RecoveryError("InvalidCandidate", "최소 한 개의 설정 변경이 필요함.")
    return {"replacements": replacements, "append_lines": additions}


def validate_candidate(candidate: dict[str, Any]) -> None:
    if candidate.get("schema_version", 1) != 1:
        raise RecoveryError("InvalidCandidate", "지원하지 않는 candidate schema_version임.")
    if not isinstance(candidate.get("id"), str) or not candidate["id"].strip():
        raise RecoveryError("InvalidCandidate", "후보 id가 필요함.")
    if not isinstance(candidate.get("reason"), str) or not candidate["reason"].strip():
        raise RecoveryError("InvalidCandidate", "후보 reason이 필요함.")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise RecoveryError("InvalidCandidate", "근거 evidence가 한 개 이상 필요함.")
    for item in evidence:
        if isinstance(item, str) and item.strip():
            continue
        if isinstance(item, dict) and isinstance(item.get("path"), str) and item["path"].strip():
            continue
        raise RecoveryError("InvalidCandidate", "각 evidence에는 비어 있지 않은 path 또는 문자열 근거가 필요함.")
    if candidate.get("risk") not in {"low", "medium", "high"}:
        raise RecoveryError("InvalidCandidate", "risk는 low, medium, high 중 하나여야 함.")
    if "wrapper_changes" in candidate:
        raise RecoveryError(
            "InvalidCandidate",
            "복사본에서 검증하지 않은 별도 wrapper_changes는 허용하지 않음. 같은 changes만 Wrapper 계획에 사용함.",
        )
    changes = _changes(candidate)
    additions_seen: set[str] = set()
    for item in changes["replacements"]:
        if not isinstance(item, dict) or not isinstance(item.get("old"), str) or not isinstance(item.get("new"), str):
            raise RecoveryError("InvalidCandidate", "각 replacement에는 문자열 old와 new가 필요함.")
        old, new = item["old"], item["new"]
        if not old.strip() or not new.strip() or any(mark in old + new for mark in ("\r", "\n", "\x00")):
            raise RecoveryError("InvalidCandidate", "replacement는 비어 있지 않은 한 줄 전체만 바꿀 수 있음.")
        occurrence = item.get("occurrence")
        if occurrence is not None and (isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 1):
            raise RecoveryError("InvalidCandidate", "occurrence는 1 이상의 정수여야 함.")
    for line in changes["append_lines"]:
        if not isinstance(line, str) or not line.strip() or any(mark in line for mark in ("\r", "\n", "\x00")):
            raise RecoveryError("InvalidCandidate", "append_lines의 각 값은 비어 있지 않은 한 줄 문자열이어야 함.")
        if line in additions_seen:
            raise RecoveryError("DuplicateSetting", f"같은 줄을 두 번 추가할 수 없음: {line}")
        additions_seen.add(line)
    lines = [
        *(item.get("old", "") for item in changes["replacements"] if isinstance(item, dict)),
        *(item.get("new", "") for item in changes["replacements"] if isinstance(item, dict)),
        *changes["append_lines"],
    ]
    if any(isinstance(line, str) and _manual_only(line) for line in lines):
        raise RecoveryError(
            "ManualReviewRequired",
            "cs_ignore_*, cs_replace_code*, cs_disable_keyword, cs_allow_* 계열은 자동 복구 후보에서 제외함.",
        )


def render_candidate(
    document: TextDocument,
    candidate: dict[str, Any],
) -> tuple[str, bytes]:
    validate_candidate(candidate)
    changes = _changes(candidate)
    if document.newline == "mixed":
        raise RecoveryError("MixedNewlines", "줄바꿈 형식이 섞인 설정 파일은 자동 변경하지 않음.")
    lines = document.text.splitlines(keepends=True)
    bodies = [line.rstrip("\r\n") for line in lines]
    requested_indexes: set[int] = set()
    replacement_by_index: dict[int, str] = {}
    for item in changes["replacements"]:
        if not isinstance(item, dict) or not isinstance(item.get("old"), str) or not isinstance(item.get("new"), str):
            raise RecoveryError("InvalidCandidate", "각 replacement에는 문자열 old와 new가 필요함.")
        old, new = item["old"], item["new"]
        if not old.strip() or not new.strip() or any(mark in old + new for mark in ("\r", "\n", "\x00")):
            raise RecoveryError("InvalidCandidate", "replacement는 한 줄 전체만 바꿀 수 있음.")
        matches = [index for index, body in enumerate(bodies) if body == old]
        occurrence = item.get("occurrence")
        if occurrence is None:
            if len(matches) != 1:
                raise RecoveryError(
                    "AmbiguousReplacement",
                    f"old가 정확히 한 줄과 일치해야 함(현재 {len(matches)}개): {old}",
                )
            selected = matches[0]
        else:
            if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 1:
                raise RecoveryError("InvalidCandidate", "occurrence는 1 이상의 정수여야 함.")
            if occurrence > len(matches):
                raise RecoveryError("MissingReplacement", f"요청한 occurrence가 없음: {old} #{occurrence}")
            selected = matches[occurrence - 1]
        if selected in requested_indexes:
            raise RecoveryError("DuplicateReplacement", f"같은 줄을 두 번 바꿀 수 없음: {old}")
        requested_indexes.add(selected)
        replacement_by_index[selected] = new

    additions_seen: set[str] = set()
    for line in changes["append_lines"]:
        if not isinstance(line, str) or not line.strip() or any(mark in line for mark in ("\r", "\n", "\x00")):
            raise RecoveryError("InvalidCandidate", "append_lines의 각 값은 한 줄 문자열이어야 함.")
        if line in additions_seen:
            raise RecoveryError("DuplicateSetting", f"같은 줄을 두 번 추가할 수 없음: {line}")
        additions_seen.add(line)
        if line in bodies:
            raise RecoveryError("DuplicateSetting", f"이미 있는 줄은 추가할 수 없음: {line}")

    before_counts = Counter(bodies)
    final_bodies = [replacement_by_index.get(index, body) for index, body in enumerate(bodies)]
    final_bodies.extend(changes["append_lines"])
    after_counts = Counter(final_bodies)
    introduced_duplicates = [
        line
        for line, count in after_counts.items()
        if line and count > 1 and count > before_counts.get(line, 0)
    ]
    if introduced_duplicates:
        raise RecoveryError(
            "DuplicateSetting",
            f"변경 결과 같은 줄이 새로 중복됨: {introduced_duplicates[0]}",
        )

    rendered_parts: list[str] = []
    for index, line in enumerate(lines):
        body = bodies[index]
        ending = line[len(body) :]
        rendered_parts.append(replacement_by_index.get(index, body) + ending)
    rendered = "".join(rendered_parts)
    additions = changes["append_lines"]
    if additions:
        newline = document.newline or "\n"
        had_final_newline = document.text.endswith(("\r", "\n"))
        if rendered and not had_final_newline:
            rendered += newline
        rendered += newline.join(additions)
        if had_final_newline:
            rendered += newline
    if rendered == document.text:
        raise RecoveryError("NoConfigChange", "후보가 설정을 바꾸지 않음.")
    return rendered, encode_text_preserved(document, rendered)


def apply_candidate(path: str | Path, candidate: dict[str, Any]) -> dict[str, Any]:
    target = Path(path)
    document = read_text_preserved(target)
    rendered, encoded = render_candidate(document, candidate)
    diff = "".join(
        difflib.unified_diff(
            document.text.splitlines(keepends=True),
            rendered.splitlines(keepends=True),
            fromfile=str(target),
            tofile=str(target),
        )
    )
    atomic_write_bytes(target, encoded)
    return {
        "path": str(target.resolve()),
        "encoding": document.encoding,
        "bom": bool(document.bom),
        "newline": repr(document.newline),
        "diff": diff,
    }
