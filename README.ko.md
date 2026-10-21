# STATICA — STATIC 정적분석을 위한 AI 에이전트

> English: [README.md](README.md)

STATICA(STATIC Intelligent Correction Agent)는 Claude Code에서 STATIC 정적분석을 사용할 수 있게 해 주는 AI 에이전트입니다. 코딩 세션에서 코드가 바뀌면 응답이 끝날 때마다 변경된 파일만 다시 분석해 결과를 알려 주므로, 전체 재빌드 없이 STATIC 워크스페이스를 최신 상태로 유지할 수 있습니다. 또한 새 프로젝트를 STATIC에 연결하고, STATIC 서버 프로젝트를 관리하며, STATIC이 파일을 분석하지 못하면 C/C++ 분석 설정을 교정합니다.

STATIC은 소스 코드를 실행하지 않고 코딩 규칙 위반, 런타임 오류, 잠재적 보안 취약점을 검출하는 정적분석 도구입니다. 분야별 코딩 규칙 세트와 소프트웨어 품질 메트릭도 제공합니다.

STATICA가 STATIC의 분석 결과를 대신하지는 않습니다. 분석을 수행하고 결과를 만드는 것은 STATIC이고, STATICA는 코딩 세션에서 그 분석을 준비하고 실행해 결과를 보고합니다. 보고하는 내용은 룰별 결함 건수 같은 분석 현황이며, 결함을 고치려고 소스 코드를 수정하지는 않습니다.

## STATIC과 STATICA로 할 수 있는 것

| 상황 | STATIC과 STATICA가 하는 일 |
|---|---|
| 코딩하면서 분석 결과를 최신으로 유지하고 싶을 때 | Claude의 응답이 끝날 때마다 Stop 훅이 변경된 파일만 분석하고, 룰별 결함 건수를 `[STATIC]` 한 줄 요약으로 보여 줍니다. |
| 원할 때 직접 확인하고 싶을 때 | `/statica:pre-analyze`가 변경된 파일을 분석해 결함을 요약합니다. 서버에 업로드하지는 않습니다. |
| 팀과 결과를 공유하고 싶을 때 | `/statica:upload`가 프로젝트 전체를 분석해 STATIC 서버에 revision을 만듭니다. 요청할 때만 실행합니다. |
| 새 프로젝트를 연결하고 싶을 때 | 부트스트랩이 빌드 환경과 컴파일러를 확인하고, 빌드를 캡처한 뒤, 서버에 프로젝트를 등록합니다. |
| 분석 오류를 바로잡고 싶을 때 | STATIC이 분석하지 못한 C/C++ 파일의 파서 설정 수정안을 복사본에서 먼저 검증한 뒤 STATIC wrapper에 반영합니다. |
| 서버 프로젝트 설정을 관리하고 싶을 때 | 룰셋, 코드 메트릭, 분석 제외 범위, 보고서 생성 설정을 조회하고 변경하며, 보고서를 만들어 내려받습니다. |

## 사용 흐름

1. 프로젝트에서 `/statica:pre-analyze`를 실행합니다. 아직 STATIC에 연결되지 않은 프로젝트라면 Claude가 부트스트랩 과정을 설명하고, 승인을 받은 뒤 시작합니다.
2. 평소처럼 작업합니다. 분석 대상 소스가 바뀐 응답이 끝나면 Stop 훅이 정해진 시간 안에서 분석하고 룰별 결함 건수를 알려 줍니다.
3. 팀과 결과를 공유하려면 `/statica:upload`를 실행합니다.
4. 설정 스킬로 룰셋, 메트릭, 분석 제외 범위, 보고서를 조정하고, `/statica:status`로 현재 상태를 확인합니다.

이 저장소의 스킬은 설치된 STATIC과 함께 동작하며, STATIC을 대신하지 않습니다.

## 설치

claude.ai의 Anthropic 플러그인 디렉터리(**Customize > Plugins**)에서 STATICA를 추가합니다. 추가한 플러그인은 계정 동기화를 통해 Claude Code에서도 사용할 수 있습니다. 설치하지 않고 로컬 사본으로 써 보려면, 저장소를 받은 폴더의 상위 폴더에서 다음 명령을 실행합니다. 이 경우 플러그인은 해당 세션에서만 로드됩니다.

```text
claude --plugin-dir ./statica-plugin
```

설치한 뒤에는 새 세션을 시작하고, Claude Code가 요청하면 `/hooks`에서 Stop 훅을 승인합니다. 자동 분석에는 이 훅이 필요합니다. 이전 사내 빌드(`static@agent-plugin-static`)를 사용 중이었다면, 훅이 두 번 실행되지 않도록 먼저 제거하세요.

STATICA는 Claude Code 전용입니다. 훅과 스크립트는 사용자 PC에서 실행되며, 그 PC에 설치된 STATIC을 사용합니다. STATIC이 설치되어 있지 않거나 설정이 빠져 있으면 명령은 설정 확인 단계에서 멈추고 무엇이 빠졌는지 알려 주며, Stop 훅은 아무것도 출력하지 않고 끝납니다. `/statica:status`를 실행하면 연결 상태, 자동 분석 설정, 서버 상태를 한 번에 확인할 수 있습니다.

## 요청 예시

응답은 AI 모델과 대화 맥락에 따라 달라질 수 있습니다. 원하는 결과가 나오지 않으면 요청을 더 구체적으로 바꿔 다시 시도해 보세요.

| 요청 | 스킬 |
|---|---|
| `방금 바꾼 코드 STATIC으로 분석해줘` | `pre-analyze` |
| `이 프로젝트를 STATIC에 연결해줘` | `statica-analyze-bootstrap` |
| `전체 분석해서 STATIC 서버에 올려줘` | `upload` |
| `third_party 폴더는 분석에서 빼줘` | `scope` |
| `STATIC 보고서 만들어서 받아줘` | `report` |
| `이 C 파일이 분석이 안 돼. 툴체인 설정 고쳐줘` | `statica-toolchain-recovery` |

## 스킬

모든 스킬은 STATIC과 연동되는 작업을 하려면 설치된 STATIC이 필요합니다.

| 스킬 | 하는 일 |
|---|---|
| `statica-analyze-overview` | 플러그인의 역할 범위, 사용 방법, 사전 조건을 안내합니다. |
| `statica-analyze-bootstrap` | 프로젝트를 STATIC 워크스페이스에 처음 연결합니다. |
| `pre-analyze` | 변경된 소스를 분석해 요약합니다. 서버에 업로드하지는 않습니다. |
| `upload` | 프로젝트 전체를 분석해 STATIC 서버에 업로드합니다. |
| `status` | 프로젝트의 STATIC 상태를 한눈에 보여 줍니다. |
| `analyze-on` / `analyze-off` | 응답마다 실행되는 자동 분석을 프로젝트 단위로 켜거나 끕니다. |
| `ruleset` | 프로젝트에 적용할 룰셋과 룰 표시 언어를 변경합니다. |
| `scope` | 분석에서 제외할 파일, 디렉터리, 빌드 모듈을 설정합니다. |
| `metric` | 측정할 코드 메트릭을 켜거나 끕니다. |
| `report` / `report-generator` | 보고서를 만들어 내려받고, 분석 후 자동 생성 여부를 설정합니다. |
| `statica-toolchain-recovery` | C/C++ 파서 설정 수정안을 검증하고 반영합니다. |

룰셋, 메트릭, 분석 제외 범위, 보고서 설정은 서버 프로젝트에 저장되므로, 변경하면 그 프로젝트를 쓰는 모든 사용자에게 적용됩니다.

## STATIC 연동 방식

이 저장소에는 스킬, Stop 훅, 그리고 사용자 PC에 설치된 STATIC을 실행하는 Python 스크립트가 들어 있습니다. STATIC 자체는 포함되어 있지 않습니다. 사용자 PC에서 실행되는 내용은 다음과 같습니다.

- **Stop 훅.** Claude의 응답이 끝날 때마다 실행됩니다. 프로젝트가 STATIC에 연결되어 있고, 자동 분석이 켜져 있고, 분석 대상 파일이 바뀐 경우에만 분석하며, 그 밖의 경우에는 1초 안에 끝납니다. 서버에 업로드하지 않고, 작업을 막지 않으며, 항상 정상 종료합니다.
- **분석.** STATIC의 분석기를 실행하고, 결과를 STATIC 워크스페이스에 저장합니다.
- **프로젝트 파일.** C/C++ 프로젝트를 연결할 때, STATIC이 빌드를 캡처할 수 있도록 빌드 설정을 변경합니다. 사용자의 승인을 받은 뒤에만 진행하며, 원본을 먼저 백업하므로 되돌릴 수 있습니다. Java, Kotlin, Python, C# 프로젝트는 수정하지 않습니다.
- **네트워크.** STATIC에 설정된 STATIC 서버에만 HTTPS로 접속하며, 이때 AccessKey를 사용합니다. STATIC 서버는 사내망에서 자체 서명 인증서를 쓰는 경우가 많아, 이 접속에서는 **인증서를 검증하지 않습니다**. 분석 결과는 `/statica:upload`를 실행하거나 부트스트랩을 마칠 때만 사용자 PC 밖으로 전송됩니다.
- **자격 증명.** 서버 주소와 AccessKey는 STATIC 자체 설정(`conf/server.setting.json`)에서 읽습니다. 사용자에게 AccessKey를 묻거나 따로 저장하지 않습니다.
- **로컬 상태.** 자동 분석 설정은 `~/.suresoft/data/plugins/static/state.json`에 저장합니다.

## 요구 사항

- STATIC 설치 및 라이선스. `ARACHNE_INSTALL_PATH` 환경 변수가 STATIC 설치 경로를 가리켜야 합니다.
- STATIC 설정에 등록된 STATIC 서버 주소와 AccessKey
- `PATH`에서 `python3` 또는 `python`으로 실행할 수 있는 Python 3.10 이상
- Windows 또는 Linux

제품 데모, 구매, 도입 상담은 [bizcenter@suresofttech.com](mailto:bizcenter@suresofttech.com)으로 문의하세요.

## 개인정보 처리방침

- STATICA는 Suresoft Technologies로 어떤 데이터도 보내지 않으며, 텔레메트리도 수집하지 않습니다.
- STATIC에 설정된 STATIC 서버로만 요청을 보내고, 분석 결과는 사용자가 요청할 때만 업로드합니다.
- 결함 건수, 파일 경로 같은 출력은 Claude 세션에 표시되며, Claude 클라이언트를 통해 AI 모델 제공자에게 전송됩니다.

전체 내용은 [PRIVACY.md](PRIVACY.md)를 참고하세요. 지원 및 문의는 [bizcenter@suresofttech.com](mailto:bizcenter@suresofttech.com)으로 연락하세요.

## 라이선스와 상표

이 저장소는 [MIT 라이선스](LICENSE)로 배포됩니다. 라이선스는 문서, 스킬 파일, 훅, 스크립트를 포함한 이 저장소의 모든 내용에 적용되며, STATIC 자체에는 적용되지 않습니다. STATIC과 STATICA는 Suresoft Technologies의 제품이며, 이 저장소는 어떠한 제품 기능이나 제품 라이선스도 제공하지 않습니다.

Claude와 Claude Code는 Anthropic의 상표입니다. 그 밖의 제품명은 각 소유자의 상표일 수 있습니다.
