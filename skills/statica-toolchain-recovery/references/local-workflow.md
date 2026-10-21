# 로컬 작업과 데이터 계약

## 실행 폴더

각 실행은 기존 경로와 겹치지 않는 새 `run_dir`을 쓴다.

```text
<run_dir>/
  case.json
  evidence.json
  diagnosis.md                  # Agent가 별도로 작성
  inputs/
    analysis/
    adjacent-state/
      analyze.failed.json
    wrapper-snapshot/
  attempts/
    attempt-001/
      candidate.json
      proposal.diff
      baseline-generated/
      workspace/
        .csa-run/
          stdout.log
          stderr.log
      verification.json
  wrapper-plans/
    plan-001/publish-plan.json
  wrapper-backups/
    backup-001/
      rollback.json
      apply-result.json
      wrapper-tree/
        <Wrapper 전체 원본 파일>
      forward-quarantine/
        <적용 전 target 보존본>
      rollback-attempts/
        rollback-001/
          rollback-quarantine/
  handoff.json
```

기존 `run_dir`이나 시도 폴더를 삭제·재사용하지 않는다.

## 시작과 조회

```text
python "${SKILL_ROOT}/scripts/static_recovery.py" start --analysis-path <분석폴더> --run-dir <새실행폴더>
python "${SKILL_ROOT}/scripts/static_recovery.py" inspect --run-dir <실행폴더>
```

`start`는 분석 폴더 전체를 `inputs/analysis`로 복사하고 다음을 `case.json`에 기록한다.

- 원본과 보존 복사본의 SHA-256
- `compile.capture.json`에서 얻은 소스 경로·종류·해시
- 최신 유효 `csa.exe /Work` 인자, 고정 설치 경로, 실행 파일 해시·서명
- 인접 `analyze.failed.json` 상태와 보존 복사본
- `wrapperPath`, Wrapper metadata, C/C++ 설정 대상과 Wrapper 전체 파일 해시
- `evidence.json` digest
- 현재 상태, blocker, 시도 목록

`evidence.json`에는 `.elog`, 설정, capture, encoding, runtime 요약을 기록한다. `inspect`는 파일을 쓰지 않고 case와 원본 무결성을 JSON으로 출력한다.

## 후보 JSON

한 파일은 한 개의 독립 후보만 담는다.

```json
{
  "schema_version": 1,
  "id": "candidate-001",
  "reason": "현재 오류와 설정 차이를 연결한 원인 가설",
  "evidence": [
    {
      "path": ".capture/compile.capture.json",
      "field": "preprocessCommand",
      "fact": "실제 compiler 버전"
    }
  ],
  "risk": "low",
  "changes": {
    "replacements": [
      {
        "old": "gnu_version=<old>",
        "new": "gnu_version=<new>"
      }
    ],
    "append_lines": []
  }
}
```

규칙:

- `risk`는 `low`, `medium`, `high` 중 하나다.
- `reason`과 하나 이상의 `evidence`가 필요하다.
- 필수 필드는 `id`, `reason`, `evidence`, `risk`, `changes`다. 성공 checkpoint는 스킬에 고정돼 있다.
- `old`와 `new`는 줄바꿈이 없는 한 줄 전체다.
- `old`가 여러 번 나오면 1부터 시작하는 `occurrence`를 추가한다.
- `changes`는 복사한 분석 폴더의 `parser.conf`에 적용한다.
- 복사본에서 성공한 바로 그 `changes`만 실제 Wrapper 계획에 사용한다. 별도 `wrapper_changes`는 거부한다.
- 빈·중복 줄, 소스 변경, 임의 명령은 거부한다.
- `cs_ignore_*`, `cs_replace_code*`, `cs_disable_keyword`, `cs_allow_*` 계열은 자동 후보에서 제외한다.

## 검증

```text
python "${SKILL_ROOT}/scripts/static_recovery.py" verify --run-dir <실행폴더> --candidate <후보.json> --timeout 600
```

1. case, evidence digest, 원본·소스·Wrapper 해시, candidate 계약을 확인한다.
2. 새 `attempt-NNN/workspace`에 보존 복사본을 다시 복사한다.
3. 후보를 복사본 `parser.conf`에만 적용하고 diff를 기록한다.
4. 복사본의 `tu.cache.json`, 과거 `.elog`, `*runtime.log`를 `baseline-generated`로 옮긴다.
5. 설치 구조에 고정한 서명된 `csa.exe`의 해시·서명을 다시 확인한다.
6. `/Work` 분석 인자만 현재 workspace로 바꾸고 `shell=False`로 CSA를 실행한다.
7. 순서가 맞는 새 성공 마커, 0바이트가 아닌 새 `.ci`/`.cal`, 비어 있지 않은 `.elog` 부재, 전체 로그의 새 오류를 판정한다.
8. 원본 분석 폴더, 보존 복사본, 원본 소스, Wrapper 전체 해시를 다시 확인한다.

판정하는 서로 다른 후보는 최대 3개다. `VerificationBlocked`는 이 한도에 포함하지 않는다. 분석 실패 후보는 같은 내용으로 반복하지 않으며, 차단 원인을 해결한 뒤 같은 후보부터 재검증한다. 매 시도는 보존 입력에서 시작하고 이전 변경이 필요하면 현재 후보 JSON에 포함한다.

## 상태

```text
GuidanceOnly
Ready → Verifying → RecoveryFailed → Retrying
                  → VerificationBlocked
                  → Recovered → Applying → ReadyForRebuild
                                 └─ 중단/실패 원복 → Recovered 또는 SupportEscalation
PositiveControl
SupportEscalation
```

- `GuidanceOnly`: 자동 검증에 필요한 증거가 부족함
- `PositiveControl`: 이미 정상인 기준 자료. 후보·Wrapper 반영으로 이어지지 않음
- `RecoveryFailed`: CSA는 실행됐지만 새 parsing 오류가 남음
- `VerificationBlocked`: 실행 파일, 권한, 라이선스, timeout, 입력 문제로 후보를 판정할 수 없음
- `Recovered`: 복사본에서 새 성공 증거와 오류 해소를 함께 확인함
- `Applying`: 전체 백업과 journal을 저장한 뒤 Wrapper 설정 변경을 수행 중임
- `SupportEscalation`: 후보 3개 실패 또는 원복 불완전처럼 자동 진행을 멈춰야 함
- `ReadyForRebuild`: 검증된 Wrapper 설정 반영이 끝나 호출자 rebuild를 기다림

환경 문제가 생기면 다음 후보로 넘어가지 않는다. `PositiveControl`을 `Recovered`로 바꾸지 않으며 Wrapper 반영 전에는 `ReadyForRebuild`로 보고하지 않는다.

검증 중 강제 종료가 남긴 `Verifying`은 다음 `verify`에서 `VerificationBlocked`로 기록하고 같은 후보만 다시 받는다. `Applying`이 남으면 `apply-wrapper`가 새 변경 없이 전체 백업 원복부터 시도한다. 원복을 확인하면 `Recovered`, journal·백업·파일 소유권을 확인할 수 없으면 `SupportEscalation`이다.
