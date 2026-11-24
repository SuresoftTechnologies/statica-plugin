---
name: status
description: 'Shows this project''s STATIC status at a glance.'
user-invocable: true
disable-model-invocation: true
---

## 설치 경로와 실행 런타임

이 스킬 패키지에는 실행 코드가 없다. 실행 코드와 Python 런타임은 STATIC에 포함된 STATICA Agent Kit(`agent_kit`)에 있고, 이 스킬은 그 코드를 실행하도록 안내한다. 이 문서와 같은 폴더의 참고 문서 링크는 지금 읽은 SKILL.md의 부모 디렉터리(SKILL_ROOT) 기준이다.

첫 실행 전에 아래 값을 한 번 확인하고 같은 대화에서 재사용한다. `${...}` 표기는 설명용이며 자동 설정된 환경변수가 아니다. 실행할 때 실제 절대경로로 바꾸고 따옴표로 감싼다.

- `INSTALL_PATH`: 환경 변수 `ARACHNE_INSTALL_PATH`의 값이다. 값이 없거나 아래 확인에 실패하면 STATIC 설치 폴더 경로를 사용자에게 요청하고 입력을 기다린다. 다른 위치를 추측해 탐색하지 않는다. 실행 코드도 이 환경 변수로 STATIC을 찾으므로, 사용자가 알려 준 경로를 쓸 때는 같은 셸 호출 안에서만 `ARACHNE_INSTALL_PATH`를 그 값으로 설정해 실행하고 영구 환경변수는 수정하지 않는다.
- `KIT_PYTHON`: Agent Kit에 포함된 Python이다. Windows는 `${INSTALL_PATH}/agent_kit/python/python.exe`, Linux는 `${INSTALL_PATH}/agent_kit/python/bin/python3`이다. 시스템 Python이나 PATH의 Python을 쓰지 않는다.
- `KIT_ROOT`: `${INSTALL_PATH}/agent_kit/plugins`이다. 공용 CLI(`${KIT_ROOT}/scripts/run.py`)가 여기에 있다.
- `KIT_SKILL_ROOT`: `${KIT_ROOT}/skills/status`이다. 이 스킬의 스크립트(`scripts/`)가 여기에 있다.

`KIT_PYTHON`, `${KIT_SKILL_ROOT}/scripts/run.py`, `${KIT_ROOT}/scripts/run.py`가 모두 있어야 진행한다.
하나라도 없으면 분석·업로드·서버 연결·설정 변경을 시작하지 말고 아래 안내를 보여준 뒤 멈춘다. 실행 코드를 다른 곳에서 내려받거나 직접 작성해 대신하지 않는다.

```text
[설치 확인]
• 확인한 STATIC 설치 경로: {INSTALL_PATH 또는 "설정되지 않음"}
• 필요: STATICA Agent Kit(agent_kit)이 포함된 STATIC 5.0.1(5 Service Pack 1) 이상
• 제품 설치·지원: bizcenter@suresofttech.com
```

사용자의 분석 대상 작업 디렉터리는 바꾸지 않는다. bash 예제는 bash에서 실행한다.

**사용자에게는 한국어로 답하라.** 사용자가 다른 언어로 말을 걸었다면 그 언어를 따른다.

이 프로젝트가 STATIC 과 어떤 관계인지, 설정이 어떻게 되어 있는지 한 번에 보여준다. **아무것도 바꾸지 않는다.**

커맨드가 여럿이 되면서 설정이 흩어졌다 — 룰셋·범위·metric·자동 리포트가 각자 조회 커맨드를 갖고 있고 훅 스위치는 또 별개다. 이 커맨드는 그것들을 모아 볼 뿐 새로 하는 일이 없다.

```bash
"${KIT_PYTHON}" "${KIT_SKILL_ROOT}/scripts/run.py" status --project-dir "$(pwd)"
```

서버를 네 번 조회하므로 잠깐 걸린다. 로컬만 빠르게 보려면 `--local` 을 붙인다.

## 읽는 법

**`project`** — `linked: false` 면 여기서 끝이다. 이 프로젝트는 STATIC 에 연결되지 않았고, 나머지 항목은 아예 없다. 그것이 답이니 "실패" 로 전하지 마라.

**`analysis`**
- `bootstrapStatus` 가 `ready` 가 아니면 **부트스트랩이 안 끝난 것이다.** 분석이 안 되는 이유가 대개 여기 있다.
- `hookEnabled` 와 `hookEnabledGlobally` 를 **둘 다 보여줘라.** 프로젝트만 껐는지 전역으로 껐는지 구분되지 않으면 "왜 자동 분석이 안 도나" 를 답할 수 없다.
- 이 Claude 디렉터리 배포본에는 Stop 훅이 없으므로, 이 두 값은 같은 PC에 따로 설치된 STATICA Stop 훅이 있을 때만 의미가 있다. 켜져 있어도 이 배포본만으로는 응답마다 자동 분석이 돌지 않는다는 점을 함께 알려라.

**`server.analysis`** — **마지막 전체 분석**이다. `lastRevisionSequence` 는 웹 History 에 보이는 번호(#8 등)이고, `lastAnalyzedAt` 은 그 시각(초 단위 epoch)이다. 둘 다 `null` 이면 **성공한 분석이 아직 없다.** 이 값은 경로를 가리지 않는다 — 웹에서 돌렸든 커맨드로 돌렸든 revision 이 생겼으면 잡힌다.

**`scope`** — 제외 건수. 0 이 아니면 **분석에서 빠진 것이 있다는 뜻**이므로, 결함 수를 함께 이야기할 때 반드시 언급하라.

**`server`** — 조각마다 `error` 가 따로 붙는다. 하나가 실패해도 나머지는 유효하다. 전부 실패했다면 서버가 내려갔거나 AccessKey 문제다.

## 어떻게 보여줄까

**표 하나로 압축해라.** 항목이 열 개가 넘으므로 문장으로 늘어놓으면 읽히지 않는다.

| | |
|---|---|
| 프로젝트 | `TETRISSH4` · C/C++ |
| 자동 분석 | 켜짐 |
| 마지막 전체 분석 | #10 · 2026-08-19 13:50 |
| 분석 제외 | 3건 |
| 룰셋 | 2 / 30 (ko_KR) |
| metric | 20 / 34 |
| 자동 리포트 | 꺼짐 |

**이상한 값을 먼저 짚어라.** 사용자가 이 커맨드를 부르는 이유는 대개 뭔가 예상과 다르기 때문이다:

- 훅이 꺼져 있다
- `bootstrapStatus` 가 `ready` 가 아니다
- 제외 건수가 예상보다 많다
- 룰셋이 1개거나 전부(30/30)다 — 전부 켜면 룰 버전 충돌로 분석이 실패할 수 있다
- 서버 조각에 `error` 가 있다

이런 게 없으면 표만 보여주고 끝내라. 굳이 조언을 덧붙이지 마라.

## 결과 해석

- `linked: false` → 연결되지 않았다. 부트스트랩을 원하면 `statica-analyze-bootstrap` 스킬로 안내하되, **먼저 제안하지는 마라.**
- `server.error: "NO_SERVER_SETTING"` → Arachne 설정에 서버가 없다. 설치 문제다.
- 조각별 `error: "NO_ACCESS_KEY"` (401) → AccessKey 문제다. **키를 사용자에게 묻거나 파일에 쓰지 마라.**
- 조각별 `error: "NOT_FOUND"` (404) → 서버에 프로젝트가 없거나 서버가 구버전이다. 여러 조각이 함께 404 면 후자일 가능성이 높다.
