# 분석과 후보 작성 기준

## 핵심 원칙

PA 설정은 분석 PC가 아니라 **원본 소스를 실제로 컴파일한 환경**에 맞춘다. `.elog`, 캡처, 설정과 가이드가 함께 가리키는 값만 후보로 사용한다.

## 진단 순서

1. `.elog`의 가장 이른 오류를 고른다.
2. 같은 파일의 뒤따르는 오류는 cascade인지 구분한다.
3. `compile.capture.json`에서 소스 언어, Wrapper, 실제 compiler, 인자를 읽는다.
4. `parser.conf`의 target, compiler version, language mode, include, macro, builtin, ABI 관련 줄을 비교한다.
5. `.csencodings`와 encoding 관련 오류를 연결한다.
6. `*runtime.log`로 이번 오류와 실행 조건을 확인한다.
7. 동봉된 [CSA·parser.conf 옵션 참고서](pa-options.md)에서 옵션의 정확한 문법과 허용값을 확인한다.
8. 한 번에 하나의 원인 가설만 검증할 최소 후보를 만든다.

과거 사례는 검색 힌트일 뿐 오류 문구가 비슷하다고 설정값을 복사하지 않는다.

## PA·툴체인 가이드 근거

후보 값은 현재 STATIC/PA 버전에 맞는 공식 또는 설치 동봉 가이드에서 확인한다. 고객 샘플·과거 답변·모델 기억은 가이드가 아니다.

- 옵션 철자·예제·확인 한계: [CSA·parser.conf 옵션 참고서](pa-options.md)
- 원문 조회 시점과 불일치 기록: [분석 가이드 출처와 적용 범위](guide-sources.md)
- 복사본 실행과 성공 판정: [CSA 실행 계약](csa-runtime.md)

- `evidence`에 가이드 이름, 제품 버전, 절 또는 검색어를 남긴다.
- 가이드가 설명하는 compiler family, version 표기법, target, 언어 모드를 현재 capture와 대조한다.
- 다른 제품 버전의 문법은 그대로 복사하지 않는다.
- 해당 버전의 가이드나 허용값을 확정할 수 없으면 실행 후보 대신 필요한 근거를 보고한다.
- 가이드가 놓인 고객별 절대 경로를 후보나 재사용 문서에 하드코딩하지 않는다.

## 점검 축

- target과 ABI: `target`, pointer/long/size 관련 설정
- compiler family와 version: `gnu_version`, `microsoft_version`, `clang_version`
- 언어 모드: C, C99, C++ 표준, compiler 확장
- include·macro·preinclude: 실제 전처리 환경과의 차이
- builtin·vendor 확장: compiler builtin, pragma, asm, 특수 keyword
- encoding: `.csencodings`, 원본 파일과 문자열 진단
- 소스 의미: 원본 compiler도 같은 오류를 내는지
- PA 내부 오류: 동일 입력 재현과 엔진 결함 가능성

## 후보 생성 조건

실행 가능한 후보는 다음을 모두 만족해야 한다.

- 현재 오류와 직접 연결되는 근거가 있다.
- 변경할 `parser.conf` 줄과 새 값을 정확히 표현할 수 있다.
- 새 값이 capture 또는 가이드로 확인된다.
- 제품 소스를 바꾸지 않는다.
- 변경 범위가 원인 가설에 필요한 최소치다.
- 스킬의 고정 checkpoint로 검증 성공·실패를 판정할 수 있다.

값을 확정할 수 없으면 후보 대신 필요한 자료를 기록한다. 필수 실행 자료가 부족한 case는 `GuidanceOnly`이며 `verify` 입력이 아니다.

## 자동 후보에서 제외하는 설정

다음 계열은 parsing을 통과시켜도 분석 의미나 결함 탐지 범위를 바꿀 수 있다.

- `cs_ignore_*`
- `cs_replace_code*`
- `cs_disable_keyword*`
- `cs_allow_*`
- 광범위한 macro 제거·치환

이 계열은 자동 후보 JSON에 넣지 않는다. 실제 결함이나 코드 의미를 숨길 수 있기 때문이다. 필요 가능성은 `diagnosis.md`에만 기록하고 `verify`와 Wrapper 반영에서는 거부한다.

## 설정 텍스트 보존

`parser.conf`는 같은 key가 여러 번 나올 수 있다. dict로 단순 변환하지 않는다.

- 줄 순서와 주석 유지
- encoding, BOM, CRLF/LF 유지
- exact `old`/`new` 한 줄로 교체 위치 고정
- 같은 줄이 여러 번 나오면 1부터 시작하는 `occurrence`를 명시
- `occurrence`가 없을 때 일치 줄이 0개 또는 여러 개면 자동 변경 중단
- 추가할 줄이 이미 있으면 중복 추가 중단

## 진단 문서

`diagnosis.md`를 다음처럼 나눈다.

- 확인된 사실
- 원인 가설
- 후보와 근거
- 위험과 영향
- 부족한 자료
- 검증 checkpoint

일반 compiler 경고나 소스 한 줄만으로 PA 원인을 확정하지 않는다.
