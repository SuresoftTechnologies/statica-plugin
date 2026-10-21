# Wrapper 반영과 되돌리기

## 단계 경계

Wrapper 반영은 복사본 CSA 검증과 별도 명령이다. 복구 작업은 `Recovered` 확인 후 계획·적용까지 추가 승인 없이 이어간다. 진단·로컬 검증만 요청했거나 `case.json`이 `Recovered`가 아니면 계획·적용을 하지 않는다.

```text
python "${SKILL_ROOT}/scripts/static_recovery.py" plan-wrapper --run-dir <실행폴더>
python "${SKILL_ROOT}/scripts/static_recovery.py" apply-wrapper --run-dir <실행폴더> --plan <publish-plan.json>
```

`plan-wrapper`는 읽기만 하며 `apply-wrapper`만 실제 설정을 바꾼다. 대상 외 Wrapper 파일은 유지한다.

## 대상 찾기

`.capture/compile.capture.json`을 기준으로 한다.

1. `wrapperPath`가 현재 STATIC 설치의 `wrapper/<name>` 아래에 있는 실제 Wrapper 실행 파일인지 확인한다.
2. 부모 디렉터리를 Wrapper 루트로 사용한다. Wrapper 폴더명과 workspace 폴더명이 같다고 가정하지 않는다.
3. `wrapper.toolchain.json.workspace`가 현재 STATIC workspace를 가리키는지 확인한다. 구형 metadata에 이 필드가 없을 때만 `wrapper/<workspace>` 관례명을 fallback으로 인정한다.
4. `wrapper.toolchain.json`의 `toolchain` 객체를 읽는다.
5. `sourceFileKind == C`이면 `cconfigFile`을 선택한다.
6. `C++`, `CPP`, `CXX`, `CC`이면 `cppConfigFile`을 선택한다.
7. metadata 값이 없을 때만 `parser.c.conf` 또는 `parser.cpp.conf`를 fallback으로 쓴다.

종류가 없거나 모호하면 확장자만으로 강행하지 않는다. config는 Wrapper 루트 안에 있어야 하며 링크·junction·부모 경로 탈출·없는 대상 파일 생성은 차단한다.

## publish-plan.json

계획에는 다음을 넣는다.

- 검증된 candidate 경로와 digest
- Wrapper 루트, 이름, C/C++ config field
- 대상 config의 현재 SHA-256과 적용 뒤 SHA-256
- before/after diff
- 복사본에서 성공한 동일 `changes`와 후보 id·reason·risk
- Wrapper 전체 파일의 현재 SHA-256
- 전체 계획의 canonical `plan_digest`

계획은 `wrapper-plans/plan-NNN/publish-plan.json`에 새로 만든다. 이후 candidate나 Wrapper 파일 집합·내용이 바뀌면 적용을 중단한다.

## apply-wrapper

별도 승인 옵션 없이 검증된 계획을 적용한다. 계획·후보·현재 Wrapper의 일치 여부는 반영 직전에 다시 확인한다.

적용 순서:

1. 계획의 `plan_digest`를 다시 계산한다.
2. 검증 candidate와 대상 config를 다시 읽어 after SHA-256을 재계산한다.
3. 같은 Wrapper를 쓰는 다른 case와 겹치지 않도록 Wrapper별 공유 잠금을 잡는다.
4. Wrapper 전체 파일 해시를 다시 확인한다.
5. `wrapper-backups/backup-NNN/wrapper-tree`에 Wrapper 전체 원본 바이트와 해시를 보존하고 `rollback.json`을 만든다.
6. 첫 변경 전에 `case.json`을 `Applying`으로 바꾸고 plan·target·before/after·전체 백업 경로와 digest를 `active_wrapper_apply` journal에 저장한다.
7. 현재 target을 먼저 고유 격리 경로로 원자 이동해 before 해시를 확인한 뒤, target 이름이 비어 있을 때만 encoding, BOM, 줄바꿈, 주석, 중복 key를 보존한 새 바이트를 게시한다. 그 사이 같은 이름이 다시 생기면 덮어쓰지 않는다.
8. 저장 직후 계획한 SHA-256과 같은지 확인한다.
9. 설정 저장 뒤 Wrapper 파일 이름 집합이 그대로인지 확인한다. target config 외 metadata·다른 설정·모든 실행 파일의 변경은 성공으로 인정하지 않는다.
10. `wrapper.toolchain.json`을 다시 읽어 C/C++ config field 또는 같은 관례명 fallback이 동일 target을 가리키는지 확인한다.
11. 설정과 Wrapper 전체의 사후 해시를 기록한 뒤 `active_wrapper_apply`를 지우는 것과 함께 `handoff.json`과 `ReadyForRebuild`를 만든다.

이 명령은 target project rebuild와 STATIC 재분석을 실행하지 않는다.

## 실패와 원복

설정 저장·사후 검증 실패, 예외·취소는 하나의 트랜잭션 실패로 처리하고 다음 순서로 원복한다.

1. 현재 config 해시가 스킬이 방금 쓴 planned-after/before 해시인지 확인한다. 검증된 `Applying` journal에서 target 이동 직후 중단된 경우에는 target 부재도 이 트랜잭션이 소유한 중간 상태로 다룬다.
2. 소유를 확인했을 때만 target을 포함한 변경 파일을 같은 볼륨의 고유 임시 이름으로 먼저 옮기고, 옮긴 해시를 확인해 backup 폴더에 격리한다. 다른 내용으로 바뀌었거나 같은 경로가 다시 생기면 덮어쓰지 않는다.
3. 다른 Wrapper 파일도 바뀐 경우 새 파일과 내용이 바뀐 기존 파일을 같은 방식으로 먼저 격리하고, 전체 백업을 빈 경로에만 복원한다.
4. config와 Wrapper 전체가 원본 해시로 돌아왔을 때만 `ApplyFailedRolledBack`과 `Recovered`로 끝낸다.
5. 하나라도 원본 해시와 다르거나 상태 정리를 완료하지 못하면 `RollbackIncomplete`와 `SupportEscalation`으로 멈춘다.

적용 후보를 바꾸거나 무한 재시도하지 않는다. 취소·인터럽트에서도 원복과 감사 기록을 시도하고, 인터럽트는 기록 뒤 다시 전달한다. `rollback.json`, `apply-result.json`을 보존한다.

격리 파일은 데이터 유실을 피하려고 즉시 삭제하지 않는다. Wrapper와 `run_dir`이 같은 볼륨이면 `run_dir`의 rollback/forward quarantine이 보존본이다. 볼륨이 다르면 같은 볼륨에서 원자 이동할 수 있도록 Wrapper 부모의 `.static-recovery-quarantine/<digest>`에도 파일을 남기고, 그 절대 경로를 `apply-result.json`의 `persistent_quarantine_files` 또는 `forward_previous_target_persistent`에 기록한다. 정리 여부는 rebuild·재분석과 수동 확인 뒤 호출자가 결정한다.

프로세스 강제 종료 뒤 `Applying`이 남으면 다음 `apply-wrapper`는 전달받은 새 계획을 적용하지 않는다. 저장된 journal·plan digest·전체 백업을 먼저 검증하고 고유한 `rollback-attempts/rollback-NNN`에서 보수적으로 원복만 수행한다. 원복을 확인하면 `InterruptedApplyRolledBack`/`Recovered`로 끝나며, 실제 반영은 명령을 한 번 더 실행해야 한다. 이전 반영 프로세스 PID가 살아 있거나, journal·백업·현재 target의 소유권을 확인할 수 없으면 파일을 덮어쓰지 않고 기다리거나 `SupportEscalation`으로 멈춘다.

## 호출자 인계

`handoff.json`에는 다음을 기록한다.

- 상태 `ReadyForRebuild`
- 변경한 Wrapper와 config
- 백업 경로
- 다음 단계: 대상 프로그램 rebuild → STATIC 재분석 → 같은 파일의 오류 해소 확인
- 이 스킬이 아직 실행하지 않은 단계

`handoff.json` 하나만 보고 rebuild하지 않는다. `case.json.state`, `case.json.wrapper_apply.status`가 모두 `ReadyForRebuild`이고 두 파일의 `plan_digest`가 일치해야 인계가 유효하다. 성공 commit 전 강제 종료나 원복 시작 시에는 `case.json`의 비준비 상태가 우선한다.
