---
name: statica-analyze-overview
description: STATIC 정적분석에 손대기 전에 먼저 읽어라. /statica:pre-analyze·/statica:upload 같은 이
  플러그인의 커맨드를 쓰려 할 때, 응답이 끝난 뒤 [STATIC] 요약이나 부트스트랩 안내가 저절로 나타나 이유가 궁금할 때, STATIC이 보고한
  결함을 근거로 코드를 고칠지 판단하려 할 때 사용한다. 이 플러그인의 범위와 금지선, 두 진입점, 전제 조건을 알려준다.
user-invocable: true
disable-model-invocation: false
---

## 설치 경로와 호스트 연결

PLUGIN_ROOT는 이 진입점이 속한 설치 플러그인 루트다. skills/<id>/SKILL.md에서는 ../..이다. 공용 scripts/assets/tmpa는 플러그인 루트에 한 번만 배치한다. 스킬의 references와 보조 문서는 해당 스킬 파일 기준이다.

`${PLUGIN_ROOT}`와 `${PLUGIN_DATA}`가 셸에 자동 설정됐다고 가정하지 않는다. 로드한 파일의 실제 위치로 루트를 확인하고, 실행할 때 실제 절대경로로 대체하거나 동일 셸 호출에서 변수를 설정한다. PLUGIN_DATA는 호스트가 제공하는 영속 데이터 경로를 우선 사용하고, 없으면 사용자 데이터 디렉터리 아래 이 플러그인 전용 경로를 사용한다. 사용자의 분석 대상 작업 디렉터리는 바꾸지 않는다. bash 예제는 bash에서 실행한다.

**사용자에게는 한국어로 답하라.** 사용자가 다른 언어로 말을 걸었다면 그 언어를 따른다.

# statica 플러그인 개요

## 무엇을 하는가, 그리고 어디서 멈추는가

작업 디렉터리의 프로젝트에 연결된 STATIC 워크스페이스의 분석 결과를 **항상 최신으로 유지**한다. 변경된 소스만 골라 다시 분석하고, 결함 건수와 룰별 요약을 보고하고, 요청이 있으면 서버에 반영한다.

**결함을 읽고 코드를 고치는 일은 이 플러그인의 몫이 아니다.** 그 작업은 별도 플러그인에서 다룬다. 이것은 선택이 아니라 설계상의 경계다.

- 이 플러그인의 출력(결함 건수, `topRules`, `.ci` 집계)을 근거로 **소스 파일을 편집하지 마라.**
- **결함을 파일별로 나열하지 마라.** 보고하는 것은 분석의 상태이지 결함의 내용이 아니다.
- 사용자가 결함 수정을 원하면, 그것은 이 플러그인 밖의 일임을 알리고 사용자의 지시를 받아라.

## C/C++ 분석 오류 복구

사용자가 툴체인 복구를 요청하거나 C/C++ 분석 오류를 발견하면 같은 플러그인의 `statica-toolchain-recovery` 스킬을 사용한다. 확보된 분석 오류 폴더로 설정 후보를 복사본에서 검증하고 Wrapper 설정을 반영하는 절차이며, 소스 결함 수정과는 다르다. 오류 폴더가 없으면 경로를 확인하고, 진단·설명만 요청받았으면 그 범위를 넘지 않는다. Stop 훅 자체가 복구 CLI를 자동 실행하는 것은 아니다. 복구 후 재빌드·전체 재분석은 별도 작업으로 인계한다.

## 두 갈래의 분석기

지원 언어는 다섯이고, 그 아래 분석기는 둘이다. **어느 갈래인지는 워크스페이스가 정한다** (`agent.json` 의 `language`, 없으면 C/C++). 결과 JSON 에 `language` 필드가 있으면 아래 오른쪽 칸이다.

| | C/C++ | java · kotlin · python · csharp |
| --- | --- | --- |
| 분석기 | `analyzer-csa` | `analyzer-plugin` |
| 연결 방법 | 빌드를 wrapper 로 가로채 캡처 | 기술서(빌드 플러그인이 생성) 또는 프로젝트 루트 |
| 프로젝트 파일 수정 | 있다 | **없다** |
| 분석 단위 | 변경된 TU 만 | 언제나 전량 |
| 서버 업로드 | 명시적 upload 또는 bootstrap-finish | 명시적 upload 또는 bootstrap-finish |

**모든 언어의 pre-analyze와 Stop 훅은 서버에 업로드하지 않는다.** Java·Kotlin·Python·C#은 `analyzer-plugin --no-upload` 로 전량 분석 결과를 로컬에 저장한다. 이 옵션을 지원하는 바이너리가 필요하며, 서버 연결도 여전히 필요하다. `/statica:upload` 호출이나 "서버에 업로드해 줘"라는 명시적 요청은 upload 스킬로 처리한다. 최초 연결의 `bootstrap-finish` 도 전체 분석·업로드를 수행한다.

## 두 진입점, 하나의 CLI

스킬은 자기 폴더의 `scripts/run.py`를 통해 공용 CLI를 부르고, 자동 훅은 공용 CLI(`${PLUGIN_ROOT}/scripts/run.py`)를 직접 부른다. 전용 실행 코드와 bootstrap 설정·템플릿은 해당 스킬 안에 있으며, 분석 엔진·업로드·서버 API·상태 관리는 공유한다. 아래의 여러 기능을 함께 보여주는 예시는 공용 CLI 경로를 사용한다.

**1. Stop 훅 (자동)** — `hooks/hooks.json` 이 매 응답 종료마다 `hooks/stop-hook.cmd` 를 돌린다. 값싼 게이트를 순서대로 통과해야만 실제 분석까지 간다. 대부분의 응답은 밀리초 안에 빠져나온다.

1. `stop_hook_active` — 훅으로 인한 재진입이면 즉시 종료
2. 이 프로젝트의 자동 분석 스위치가 꺼져 있으면 종료 (`switch off`, **프로젝트 단위**다. `--global` 로 끈 경우도 여기서 걸린다)
3. Arachne 서버 설정을 읽지 못하면 조용히 종료 — 설정 문제로 작업을 막지 않는다
4. 이 프로젝트에 연결된 워크스페이스가 없으면 **조용히 종료**
5. 변경된 분석 대상(TU)이 없으면 조용히 종료
6. 분석한 대상이 있거나, 시간 예산에 걸렸거나, 새로 캡처 실패한 신규 파일이 있을 때만 말한다 — **사용자에게는 `systemMessage` 로 한 줄, 너에게는 `hookSpecificOutput.additionalContext` 로 룰별 집계까지.** 그 컨텍스트가 오면 그것을 사용자에게 보고하는 것이 네 일이다. 이미 끝난 분석이므로 `pre-analyze` 나 `upload` 를 다시 부르지 마라.

훅은 시간 예산에 묶여 있고, **결코 `upload` 까지 가지 않는다.** 어떤 예외도 사용자의 턴을 깨뜨리지 않도록 전부 삼킨다.

**훅이 실제로 분석까지 가면 몇 초 걸린다** (실측: TU 하나에 7초). 그동안 응답은 이미 화면에 다 그려져 있고, `[STATIC]` 요약은 그 뒤에 붙는다. 조용히 빠지는 경우는 0.3~0.5초다.

그래서 **네가 소스를 고친 응답의 바로 다음 턴에 `/statica:pre-analyze` 를 돌리면 대개 "변경된 분석 대상이 없습니다"가 나온다.** 훅이 이미 그 TU 를 분석했기 때문이며, 정상이다. 이것을 "분석이 안 됐다"로 읽고 재빌드나 `upload` 를 제안하지 마라.

**2. 슬래시 커맨드 (명시적)** — 사용자가 직접 부른다. 훅 예산에 묶이지 않으므로 전체 재빌드가 오래 걸려도 된다.

## 훅은 연결된 프로젝트에서만 말한다

**훅은 사용자의 턴을 절대 막지 않는다. 종료 코드는 언제나 0 이다.**

Stop 훅은 디렉터리를 가리지 않고 모든 세션의 모든 응답 끝에 돈다. 그래서 워크스페이스가 없는 프로젝트에서는 **아무 말도 하지 않는다.**

**최초 연결은 사용자가 시작한다.** 사용자가 `/statica:pre-analyze` 를 부르면 `code: "NEEDS_BOOTSTRAP"` 이 돌아오고, 그때 부트스트랩이 무엇을 하는지 설명하고 **승인을 받은 뒤** `statica-analyze-bootstrap` 스킬의 절차를 따른다. 한 줄 명령이 아니다.

## 커맨드

| 상황 | 커맨드 |
| --- | --- |
| 변경분만 분석하고 요약을 보고 싶다 | `/statica:pre-analyze` |
| 자동 분석이 거슬린다 (직접 실행은 계속 가능) | `/statica:analyze-off` |
| 자동 분석을 다시 켠다 | `/statica:analyze-on` |
| 전체를 분석해 서버에 revision 을 올린다 | `/statica:upload` (사용자 명시 요청 시에만) |
| 적용할 룰셋과 룰 표시 언어를 바꾼다 | `/statica:ruleset` |
| 분석에서 뺄 파일 · 디렉터리를 정한다 | `/statica:scope` |
| 어떤 코드 메트릭을 측정할지 켜고 끈다 | `/statica:metric` |
| 보고서를 만들어 내려받는다 | `/statica:report` |
| 분석 후 보고서를 자동 생성할지 정한다 | `/statica:report-generator` |
| 지금 어떤 상태인지 한 번에 본다 | `/statica:status` |

각 커맨드의 결과 해석 규칙은 그 커맨드 파일 본문에 있다 — 여기서 되풀이하지 않는다.

자동 분석 ON/OFF 상태는 모든 벤더가 공유하는 `~/.suresoft/data/plugins/static/state.json`에 둔다. PLUGIN_DATA나 `--state-dir`로 경로를 따로 지정하지 않는다. 동일 사용자·프로젝트의 설정은 벤더를 바꿔도 유지된다.

직접 부를 때의 실제 호출:

```bash
python "${PLUGIN_ROOT}/scripts/run.py" pre-analyze --project-dir "$(pwd)"
python "${PLUGIN_ROOT}/scripts/run.py" upload --project-dir "$(pwd)"
python "${PLUGIN_ROOT}/scripts/run.py" switch on|off --project-dir "$(pwd)"
python "${PLUGIN_ROOT}/scripts/run.py" status --project-dir "$(pwd)"
python "${PLUGIN_ROOT}/scripts/run.py" doctor
```

설정 계열은 **조회 · 변경이 짝**이고, 변경 전에 조회하는 것이 규칙이다. `ruleset-show`/`ruleset-set`, `scope-show`/`scope-exclude`·`scope-include`, `metric-show`/`metric-set`, `report-generator-show`/`report-generator-set`. 보고서 생성은 `report` 하나가 요청 · 대기 · 다운로드를 다 한다.

**설정 계열은 전부 서버 프로젝트의 것이라 팀 전체에 영향이 간다.** 그리고 둘은 전체 교체다 — `ruleset-set` 은 넘긴 id 만 남기고, `report-generator-set` 도 마찬가지다. 그래서 바꾸기 전에 반드시 현재 값을 읽어야 한다. `scope` 와 `metric` 은 증분이라 말한 것만 바뀐다. 자세한 규칙은 각 커맨드 본문에 있고 여기서 되풀이하지 않는다.

부트스트랩 서브커맨드(`detect`, `bootstrap-begin`, `bootstrap-guard`, `bootstrap-verify`, `bootstrap-finish`, `bootstrap-abort`)는 여기 적지 않는다 — 순서와 인자는 `statica-analyze-bootstrap` 스킬에 있다.

## 부트스트랩은 승인이 필요하고, 한 번에 끝나지 않는다

프로젝트를 STATIC 워크스페이스에 처음 연결하는 작업이다. **사용자 프로젝트 파일을 수정하고**(고치기 전에 원본을 워크스페이스 안에 보관한다), **전체 빌드를 돌리며**, **공용 STATIC 서버에 프로젝트를 생성한다.** 사용자 승인 없이 실행하지 마라.

C/C++ 절차는 환경 식별 → 컴파일러 확정 → wrapper 생성 → 치환 → 빌드 → 캡처 검증 → 서버 등록으로 이어지는 여러 단계이고, 치환이 GUI 조작인 환경에서는 **사용자가 IDE 에서 직접 해 줄 때까지 기다려야 한다.** 진행 상태는 워크스페이스에 남으니 중단했다 이어가도 된다.

**타 언어는 절차가 훨씬 짧고, 사용자 프로젝트 파일을 전혀 고치지 않는다** (wrapper 도 치환도 없다). 대신 java · kotlin 은 빌드 플러그인을 태워 분석 기술서를 뽑는 단계가 있다.

실제 명령과 순서는 **`statica-analyze-bootstrap` 스킬**에 있으니 그대로 따르고, 여기서 추측해 명령을 만들지 마라. 그 스킬은 언어부터 가른 뒤 C/C++ 은 본문으로, 나머지는 `other-languages.md` 로 보낸다.

사용자가 원하지 않으면 그냥 하지 않는다 — 훅은 연결되지 않은 프로젝트에서 아무 말도 하지 않으므로 따로 기록할 것이 없다. 컴파일러를 찾지 못했으면 추측하지 말고 사용자에게 경로를 물어라.

## upload 는 비싸다

워크스페이스 전체를 스코프로 도는 실행이다. **라이선스 슬롯을 점유하고, 워크스페이스를 잠그고, 팀 전체가 보는 revision 을 서버에 만든다.** 사용자가 명시적으로 요청했을 때만 실행하고, 먼저 제안하지 마라. 훅은 여기에 절대 닿지 않는다.

Java·Kotlin·Python·C#의 upload도 변경 여부와 무관하게 전량 분석하고 서버에 업로드한다. pre-analyze의 로컬 분석과 구분하며, upload의 결함 집계는 프로젝트 전체다.

## CLI 출력 읽기

모든 서브커맨드는 **stdout 에 JSON 객체를 정확히 하나** 찍는다(실패해도, 내부 오류가 나도 마찬가지다). 사람이 읽을 문장은 `message` 에 있다. 실패는 `ok: false` 와 `code`(`NEEDS_BOOTSTRAP`, `NO_PROJECT_KEY`, `NO_ACCESS_KEY` 등) + `hint` 로 온다.

**주의:** `defects` 는 **이번 실행이 분석한 범위의 집계**다. 프로젝트 전체 누적 결함 수가 아니다 — C/C++ 은 이번에 돈 TU 들의 것이고, 타 언어는 전량 분석 결과에서 이번에 변경된 파일에 달린 것만 골라낸 것이다. 어느 쪽인지는 `defects.scope` 가 말한다(`changedFiles` / `allSourceFiles`). 매 실행마다 값이 달라지는 것이 정상이며, 이것을 누적 총계인 것처럼 보고하면 사용자를 실제로 오도한다.

## 전제 조건

- **`ARACHNE_INSTALL_PATH`** 환경변수가 Arachne(STATIC) 설치 경로를 가리켜야 한다. 그 아래 `bin/`, `works/`, `conf/` 를 쓴다. 없으면 `NO_INSTALL_PATH`.
- **서버 주소와 AccessKey** 는 Arachne 자신의 설정(`conf/server.setting.json`)에 등록되어 있어야 한다. 이 플러그인은 읽기만 한다.
  - **사용자에게 AccessKey 를 묻지 마라. 어떤 파일에도 쓰지 마라.** `NO_SERVER_SETTING`·`NO_SERVER_URL`·`NO_ACCESS_KEY` 가 나오면 Arachne 설정에서 등록하도록 안내하는 것이 전부다.
- 환경이 의심스러우면 점검한다: `python "${PLUGIN_ROOT}/scripts/run.py" doctor`
