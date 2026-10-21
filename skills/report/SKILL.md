---
name: report
description: 보고서를 새로 만들어 내려받는다
user-invocable: true
disable-model-invocation: true
---

## 설치 경로와 호스트 연결

PLUGIN_ROOT는 이 진입점이 속한 설치 플러그인 루트다. skills/<id>/SKILL.md에서는 ../..이다. 공용 scripts/assets/tmpa는 플러그인 루트에 한 번만 배치한다. 스킬의 references와 보조 문서는 해당 스킬 파일 기준이다.

`${PLUGIN_ROOT}`와 `${PLUGIN_DATA}`가 셸에 자동 설정됐다고 가정하지 않는다. 로드한 파일의 실제 위치로 루트를 확인하고, 실행할 때 실제 절대경로로 대체하거나 동일 셸 호출에서 변수를 설정한다. PLUGIN_DATA는 호스트가 제공하는 영속 데이터 경로를 우선 사용하고, 없으면 사용자 데이터 디렉터리 아래 이 플러그인 전용 경로를 사용한다. 사용자의 분석 대상 작업 디렉터리는 바꾸지 않는다. bash 예제는 bash에서 실행한다.

SKILL_ROOT는 지금 읽은 SKILL.md의 부모 디렉터리다. 이 스킬 전용 scripts/assets는 SKILL_ROOT 아래에 있다. `${SKILL_ROOT}`는 설명용 표기이며 자동 설정된 환경변수가 아니다. 스크립트 실행 시 로드한 SKILL.md의 실제 위치로 절대경로를 구성한다. 프로젝트 작업 디렉터리를 스킬 폴더로 바꾸지 않는다.

## 실행 경로

`${SKILL_ROOT}`는 이 SKILL.md가 있는 디렉터리의 절대 경로로 바꿔 실행한다. 작업 디렉터리는 분석 대상 프로젝트에 유지한다. `scripts/run.py`는 이 플러그인의 공용 런타임을 사용하므로 스킬 폴더만 따로 복사하지 않는다.


**사용자에게는 한국어로 답하라.** 사용자가 다른 언어로 말을 걸었다면 그 언어를 따른다.

서버에 보고서를 **새로 만들게 하고**, 완성될 때까지 기다렸다가 내려받는다. 웹 UI 에서 Export 로 만들고 Outputs 에서 받던 것을 한 번에 한다.

대상은 **마지막으로 성공한 분석**이다. 서버가 정하므로 revision 을 고를 수 없다. 지금 코드 상태를 담고 싶으면 `/statica:upload` 를 먼저 돌려야 한다.

## 1. 무엇을 만들지 확정받는다

**추측하지 마라.** 만드는 데 시간이 걸리고, 잘못 만들면 처음부터 다시다.

**형식** — `DOC` · `PDF` · `HTML` · `EXCEL`

**종류** — 하나 이상. 번호가 아니라 이름으로 물어라.

| | | | |
|---|---|---|---|
| 1 프로젝트 요약 | 2 Remaining Defect | 3 Suppressed Defect | 4 Rule 별 Defect |
| 5 Ruleset 별 Defect | 6 Severity 별 Defect | 7 File 별 Defect | 8 모듈 메트릭 |
| 9 파일 메트릭 | 10 클래스 메트릭 | 11 함수 메트릭 | 12 Suppressed 메트릭 |

메트릭 종류(8~12)는 메트릭이 설정되어 있어야 내용이 찬다. 사용자가 목적을 말하지 않으면 무엇에 쓸 보고서인지 한 번 물어보는 편이 낫다 — 보고용이면 1번 위주, 결함 정리용이면 2·4·7 쪽이다.

## 2. 만들고 받는다

```bash
python "${SKILL_ROOT}/scripts/run.py" report --project-dir "$(pwd)" \
  --format EXCEL --kind 1 --kind 2
```

**이 명령 하나가 요청·대기·다운로드를 다 한다.** 생성은 비동기라 안에서 2초 간격으로 상태를 되묻는다. 기본 상한은 10분이고 `--timeout <초>` 로 바꾼다. 저장 위치는 `--out <경로>` 로 지정할 수 있다.

**시간이 걸린다는 것을 미리 말해라.** 프로젝트가 크면 분 단위다. 명령이 끝날 때까지 응답이 돌아오지 않는다.

## 3. 결과를 전한다

성공하면 `path` 에 zip 이 저장돼 있다. 기본 위치는 **`<프로젝트>/.static/reports/`** 이고, 같은 이름이 있으면 `_2`, `_3` 이 붙는다.

**저장소 안이므로 `.gitignore` 를 확인해라.** `.static/` 이 등록돼 있지 않으면 등록을 제안하라 — 보고서 zip 이 커밋에 섞이면 저장소가 금방 무거워진다. 등록은 사용자 승인을 받고 해라.

## 결과 해석

`stage` 로 어디까지 갔는지 알 수 있다. **생성은 됐는데 다운로드만 실패한 경우와 생성 자체가 안 된 경우는 사용자가 할 일이 다르다.**

- `stage: "done"` → 다 됐다. `path` 와 `waitedSeconds` 를 전해라.
- `stage: "request"` → 요청 자체가 거절됐다. 아래 코드를 보라.
- `stage: "wait"` → 요청은 접수됐다. 서버에 흔적이 남아 있으니 웹 UI 의 Outputs 에서 확인할 수 있다고 알려라.
- `stage: "download"` (그리고 `ok: false`) → **보고서는 만들어졌다.** 웹 UI 에서 받으면 된다고 안내하라.

- `code: "NO_ANALYSIS"` (409) → 이 프로젝트에 성공한 분석이 없다. `/statica:upload` 를 먼저 돌려야 한다.
- `code: "REPORT_FAILED"` / `"REPORT_CANCELLED"` → 서버가 생성을 실패했거나 누군가 취소했다. 다시 시도해 볼 수 있다.
- `code: "REPORT_TIMEOUT"` → 상한 안에 안 끝났다. **실패가 아니다** — 서버는 계속 만들고 있을 수 있다. 웹 UI 의 Outputs 를 확인하거나 `--timeout` 을 늘려 다시 부르라고 안내하라.
- `code: "EMPTY_REPORT"` → 서버가 빈 파일을 줬다. 0바이트 파일을 남기지 않으므로 받은 것은 없다.
- `code: "BAD_FORMAT"` · `"BAD_KIND"` → `message` 에 고를 수 있는 값이 있다. 그대로 보여주고 다시 물어라.
- `code: "NO_ACCESS_KEY"` (401) → Arachne 설정의 AccessKey 문제다. **키를 사용자에게 묻거나 파일에 쓰지 마라.**
- `code: "NEEDS_BOOTSTRAP"` → 이 프로젝트가 아직 STATIC 에 연결되지 않았다 (`statica-analyze-bootstrap` 스킬).

**보고서 내용을 읽어서 결함을 나열하지 마라.** 이 플러그인은 분석의 상태를 다루지 결함의 내용을 다루지 않는다 (`statica-analyze-overview` 의 경계). 파일을 만들어 건네주는 데서 멈춘다.
