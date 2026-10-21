# CSA 실행과 회복 판정 계약

## 실행 파일 선택

현재 case의 최신 `*runtime.log`에 기록된 유효한 `CSA: CMD:` executable만 사용한다. 잘못된 최신 명령을 과거 정상 명령으로 대체하지 않는다.

다른 프로젝트나 과거 실행 경로를 재사용하지 않는다. 실행 파일은 원본 분석 경로에서 계산한 `static-arachne/works/<workspace>/.staticdata/analyzer/bin/csa.exe`여야 한다. 수집·실행 직전에 SHA-256과 유효한 Suresofttech Authenticode 서명을 확인한다.

## 명령 구성

로그 문자열을 셸 명령으로 실행하지 않는다. 인자 배열을 직접 만든다.

```text
argv[0] = <validated csa.exe>
argv[1] = /Work
argv[2] = <attempt-NNN/workspace>
argv[3] = <compile.capture.json sourceFile>
```

실행 형태는 다음과 같다.

```text
<csa.exe> /Work <복사한분석폴더> <원본소스경로>
```

- `argv[2]`는 반드시 현재 시도의 복사본이다.
- `argv[3]`은 읽기 전용 입력이며 수정하지 않는다.
- 현재 로그의 원래 analysis path를 그대로 사용하지 않는다.
- shell expansion, pipe, redirect, command substitution을 사용하지 않는다.
- 작업 디렉터리는 검증된 `csa.exe`의 디렉터리로 고정한다.

## 실행 전 스냅샷

과거 산출물이 성공 증거에 섞이지 않게 다음 파일을 현재 시도의 `baseline-generated`로 옮긴다.

- `tu.cache.json`: 원본 `parser.conf` 절대 경로와 해시가 캐시될 수 있으므로 재생성시킨다.
- 기존 `*.elog`
- 기존 `*runtime.log`

복사본 `parser.conf` 해시와 적용 diff, 실행 시작 시각도 기록한다. 기존 `.ci`와 `.cal`은 실행 전후 해시를 비교하고 실제로 새로 생기거나 바뀐 경우만 성공 증거로 쓴다.

## 실행 제한

- 기본 timeout: 600초
- stdout/stderr는 파일과 요약으로 보존
- 새 runtime log와 stdout/stderr 전체를 streaming 방식으로 검사해 큰 로그 중간의 실패 표시도 찾음
- Windows에서는 CSA의 긴 임시 경로 문제를 피하려고 짧은 전용 TEMP/TMP 디렉터리를 만들고 종료 뒤 제거
- timeout 시 `VerificationBlocked`
- 실행 파일 없음, 권한, license, 입력 파일 없음, 작업 디렉터리 문제도 `VerificationBlocked`
- 프로세스 비정상 종료와 parsing 실패를 구분

## PositiveControl 판정

후보 적용 전 baseline이 이미 정상이라면 결과는 `Recovered`가 아니라 `PositiveControl`이다. 0바이트가 아닌 `.elog`가 없어야 하고, 최신 CSA 명령 뒤 같은 실행 구간에 parsing 시작 → parsing 완료 → inspection 완료 → processing 완료가 순서대로 있어야 한다. 명령 시각 이후 생성된 0바이트가 아닌 `.ci`/`.cal`도 필요하다. 인접 `analyze.failed.json`이 있으면 module/file failure가 비어 있어야 한다. 빈 `.elog`는 파일 목록에는 남기되 실패 근거로 쓰지 않는다.

`PositiveControl`은 CSA 호출 방식과 성공 마커를 확인하는 기준 자료다. 후보 효과를 증명하지 않으며 `plan-wrapper` 입력으로 쓸 수 없다. 의도적으로 설정을 망가뜨린 테스트도 고객 오류 복구 증거가 아니다.

## Recovered 판정

종료 코드 0 하나만으로 성공하지 않는다. 다음을 모두 확인한다.

1. 현재 시도에서 CSA가 실제로 시작됐다.
2. 새 runtime log 또는 stdout/stderr에 parsing 시작 → 완료 → inspection 완료 → processing 완료가 순서대로 있다.
3. 현재 시도에 `Parsing Failed`가 없다.
4. 현재 시도에 0바이트가 아닌 `.elog`가 하나도 없다.
5. 실행한 analysis path가 복사본이다.
6. 복사본 `parser.conf`가 후보 적용본과 같은 해시다.
7. 0바이트가 아닌 새 `.ci` 또는 `.cal` 산출물이 있다.
8. 원본 오류 폴더와 원본 소스 해시가 바뀌지 않았다.
9. 실행 뒤에도 `csa.exe`의 경로·SHA-256·서명이 수집 시점과 같다.

새 parsing 오류가 생기면 `Recovered`가 아니라 `RecoveryFailed`다. 오류 수 감소만으로 성공 처리하지 않는다.

## 결과 JSON 핵심 필드

```json
{
  "attempt_dir": "<run_dir>/attempts/attempt-001",
  "candidate_id": "candidate-001",
  "status": "Recovered",
  "command": ["<csa.exe>", "/Work", "<workspace>", "<source>"],
  "started_at": "<ISO-8601>",
  "duration_seconds": 0,
  "exit_code": 0,
  "fresh_outputs": [],
  "success_gates": {},
  "parser_conf": {"sha256": "<sha256>", "unchanged_during_run": true},
  "blockers": []
}
```

전체 환경 변수나 원본 소스 내용은 결과 JSON에 저장하지 않는다.
