#!/usr/bin/env python3
"""CLI entrypoint for STATIC C/C++ toolchain recovery."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from static_recovery.common import RecoveryError
from static_recovery.workflow import inspect_case, start_case, verify_candidate
from static_recovery.wrapper import apply_wrapper, plan_wrapper


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="STATIC C/C++ 분석 설정을 수집하고 복사본에서 csa.exe로 검증함."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", help="분석 자료를 새 run_dir에 보존 복사하고 증거를 수집함")
    start.add_argument("--analysis-path", required=True, type=Path)
    start.add_argument("--run-dir", required=True, type=Path)

    inspect = commands.add_parser("inspect", help="case 상태와 원본 무결성을 확인함")
    inspect.add_argument("--run-dir", required=True, type=Path)

    verify = commands.add_parser("verify", help="candidate를 새 복사본에 적용하고 csa.exe로 검증함")
    verify.add_argument("--run-dir", required=True, type=Path)
    verify.add_argument("--candidate", required=True, type=Path)
    verify.add_argument("--timeout", type=int, default=600)

    plan = commands.add_parser("plan-wrapper", help="검증된 변경의 Wrapper diff와 digest를 만듦")
    plan.add_argument("--run-dir", required=True, type=Path)

    apply = commands.add_parser("apply-wrapper", help="검증된 계획을 Wrapper 설정에 반영함")
    apply.add_argument("--run-dir", required=True, type=Path)
    apply.add_argument("--plan", required=True, type=Path)
    return parser


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "start":
        return start_case(args.analysis_path, args.run_dir)
    if args.command == "inspect":
        return inspect_case(args.run_dir)
    if args.command == "verify":
        return verify_candidate(args.run_dir, args.candidate, timeout_seconds=args.timeout)
    if args.command == "plan-wrapper":
        return plan_wrapper(args.run_dir)
    if args.command == "apply-wrapper":
        return apply_wrapper(args.run_dir, args.plan)
    raise RecoveryError("UnknownCommand", f"지원하지 않는 명령: {args.command}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = _parser().parse_args()
    try:
        result = _run(args)
    except RecoveryError as exc:
        print(json.dumps({"ok": False, "error": exc.as_dict()}, ensure_ascii=False, indent=2))
        return 2
    except OSError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": "OperatingSystemError", "message": str(exc), "details": {}}},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
