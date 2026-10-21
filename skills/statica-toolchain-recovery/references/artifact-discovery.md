# STATIC 오류 자료 계약

## 입력 경로

`analysis_path`는 STATIC이 한 translation unit의 분석 오류를 내보낸 디렉터리다. 사용자 샘플은 구조 참고용이며 실제 경로나 명령의 기본값이 아니다.

경로가 없거나 디렉터리가 아니면 `MissingAnalysis` 오류로 종료한다. 비슷한 이름의 다른 폴더를 임의 선택하지 않는다.

## 수집 대상

하위 폴더를 포함해 다음 파일을 찾는다.

| 종류 | 패턴 | 용도 |
| --- | --- | --- |
| 오류 | `*.elog` | 최초 parsing 오류, 소스와 줄, 반복·cascade 오류 |
| 분석 설정 | `parser.conf` | 이번 translation unit에 실제 적용된 PA 설정 |
| CI 설정 | `ci.ini` | CSA 입력과 분석 조건 보조 확인 |
| 캡처 | `.capture/compile.capture.json` | Wrapper, 원본 소스, 언어, 컴파일러 명령 |
| 인코딩 | `.csencoding`, `.csencodings` | 소스와 분석 입력 encoding 확인 |
| 실행 로그 | `*runtime.log` | `CSA: CMD:`, parsing 시작·종료·실패 확인 |

`*runtime.log`는 `runtime.log`, `analyzer.runtime.log`, `<source>_runtime.log`를 포함한다. 각 명령 기록을 증거로 남기고 명령 시각·로그 수정 시각·줄 번호 순으로 최신 기록 하나를 선택한다.

## compile.capture.json 필드

JSON을 문자열 일부가 아니라 구조로 읽는다. 최소 필드는 다음과 같다.

- `wrapperPath`: 캡처에 사용된 실제 compiler Wrapper 실행 파일
- `sourceFile`: CSA가 분석할 원본 소스 절대 경로
- `sourceFileKind`: `C` 또는 C++ 계열 구분
- `compileCommand`: 실제 컴파일 인자
- `preprocessCommand`: 실제 컴파일러 실행 파일과 전처리 인자
- `workingDirectory`: 원래 컴파일 작업 경로

환경 변수 전체나 비공개 소스 내용은 보고서에 복사하지 않고 compiler·target·언어 단서만 요약한다.

## CSA 명령 후보

runtime log의 다음 형식만 후보로 인식한다.

```text
... CSA: CMD: "<absolute-csa-path>" "/Work" "<analysis-path>" "<source-path>"
```

다음을 모두 확인한다.

1. 최신 `CSA: CMD:` 기록이어야 한다. 최신 기록이 잘못됐다고 과거 정상 기록으로 되돌아가지 않는다.
2. 명령은 executable, `/Work`, 분석 폴더, 소스 경로의 정확히 네 인수다.
3. 실행 파일은 현재 `static-arachne/works/<workspace>/.staticdata/analyzer/bin/csa.exe`의 절대 경로이며 실제 파일이다.
4. 로그의 소스 경로가 `compile.capture.json.sourceFile`과 같은 파일이다.
5. 로그의 분석 경로가 입력 오류 폴더와 같은 경로를 가리킨다.
6. 수집 때 실행 파일 SHA-256과 Windows가 `Valid`로 판정한 Authenticode의 정확한 Suresofttech 발급 주체(CN·O)와 인증서 지문을 확인한다.

검증에서는 로그 전체 문자열을 실행하지 않고 확인한 executable과 새 인자 배열로 명령을 다시 만든다.

## 상태와 누락 처리

- `Ready`: 비어 있지 않은 `.elog`와 자동 검증에 필요한 필수 자료를 확인함
- `PositiveControl`: 후보 적용 전부터 오류가 없고 최신 runtime 실행 구간이 정상 완료된 healthy baseline. 실제 오류 복구와 분리함
- `GuidanceOnly`: 자료 누락 또는 근거 부족으로 자동 검증할 수 없지만 수집 결과와 안내는 남길 수 있음
- `MissingAnalysis`: 입력 경로가 없거나 디렉터리가 아닐 때의 시작 오류

`.elog`나 `parser.conf`가 없으면 후보를 확정하지 않는다. `compile.capture.json` 또는 유효한 CSA 명령이 없으면 진단만 계속하고 자동 검증은 하지 않는다. Wrapper 경로나 metadata만 없으면 복사본 검증은 계속하되 `plan-wrapper`에서 blocker로 멈춘다.

`PositiveControl`은 "이미 정상"이라는 분류다. 최신 명령 뒤 같은 실행 구간에 parsing 시작 → 완료 → inspection 완료 → processing 완료가 있고 실패 표시가 없어야 하며, 명령 시각 이후 생성된 내용 있는 `.ci` 또는 `.cal`도 필요하다. 과거 성공 로그만 있거나 실패 기록이 모호하면 자동 분류하지 않는다. `analyze.failed.json`이 있으면 module/file failure도 확인한다. 이 상태에서 후보나 Wrapper 변경을 만들지 않는다.

## 원본 불변 증거

`start`에서 분석 폴더 전체의 SHA-256을 `case.json`에 기록한다. `evidence.json` digest, 원본 소스·인접 `analyze.failed.json`·확인 가능한 Wrapper 전체의 SHA-256도 고정한다. 진단 대상 파일의 경로·크기·해시와 줄 위치는 필요한 만큼 `evidence.json`에 기록한다.

- 모든 `*.elog`
- `parser.conf`
- `ci.ini`
- `.capture/compile.capture.json`
- `.csencoding`, `.csencodings`
- 선택한 `*runtime.log`
- `compile.capture.json`에서 확인한 원본 소스

이후 단계는 원본 분석 폴더·수집 복사본·원본 소스·인접 상태 파일·Wrapper 전체의 파일 집합과 해시를 다시 확인한다. 기존 파일이나 실행 폴더를 삭제·덮어쓰지 않는다.
