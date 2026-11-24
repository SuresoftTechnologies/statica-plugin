---
name: report-generator
description: 'Sets whether a report is generated automatically when an analysis finishes.'
user-invocable: true
disable-model-invocation: true
---

## 설치 경로와 실행 런타임

이 스킬 패키지에는 실행 코드가 없다. 실행 코드와 Python 런타임은 STATIC에 포함된 STATICA Agent Kit(`agent_kit`)에 있고, 이 스킬은 그 코드를 실행하도록 안내한다. 이 문서와 같은 폴더의 참고 문서 링크는 지금 읽은 SKILL.md의 부모 디렉터리(SKILL_ROOT) 기준이다.

첫 실행 전에 아래 값을 한 번 확인하고 같은 대화에서 재사용한다. `${...}` 표기는 설명용이며 자동 설정된 환경변수가 아니다. 실행할 때 실제 절대경로로 바꾸고 따옴표로 감싼다.

- `INSTALL_PATH`: 환경 변수 `ARACHNE_INSTALL_PATH`의 값이다. 값이 없거나 아래 확인에 실패하면 STATIC 설치 폴더 경로를 사용자에게 요청하고 입력을 기다린다. 다른 위치를 추측해 탐색하지 않는다. 실행 코드도 이 환경 변수로 STATIC을 찾으므로, 사용자가 알려 준 경로를 쓸 때는 같은 셸 호출 안에서만 `ARACHNE_INSTALL_PATH`를 그 값으로 설정해 실행하고 영구 환경변수는 수정하지 않는다.
- `KIT_PYTHON`: Agent Kit에 포함된 Python이다. Windows는 `${INSTALL_PATH}/agent_kit/python/python.exe`, Linux는 `${INSTALL_PATH}/agent_kit/python/bin/python3`이다. 시스템 Python이나 PATH의 Python을 쓰지 않는다.
- `KIT_ROOT`: `${INSTALL_PATH}/agent_kit/plugins`이다. 공용 CLI(`${KIT_ROOT}/scripts/run.py`)가 여기에 있다.
- `KIT_SKILL_ROOT`: `${KIT_ROOT}/skills/report-generator`이다. 이 스킬의 스크립트(`scripts/`)가 여기에 있다.

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

**분석이 성공하면 서버가 알아서 보고서를 만들어 두는** 기능을 켜고 끈다. 여기서 설정만 해두면 그 뒤로는 손댈 것이 없다.

**`/statica:report` 와 관계가 없다.** 그쪽은 "지금 하나 만들어서 받기"고, 이쪽은 "앞으로 매번 자동으로"다. 이 설정을 읽어서 `/statica:report` 를 부르는 식으로 엮지 마라 — 서버가 분석 후에 직접 만든다.

## 1. 지금 설정부터 읽는다

```bash
"${KIT_PYTHON}" "${KIT_SKILL_ROOT}/scripts/run.py" report-generator-show --project-dir "$(pwd)"
```

- `enabled: false` → 꺼져 있다. **"한 번도 정한 적이 없다"와 구분되지 않는다** — 서버가 두 경우를 같은 값으로 돌려주므로 구분되는 척하지 마라.
- `enabled: true` → `format` 과 `kindNames` 로 무엇이 만들어지는지 함께 보여라.

## 2. 무엇을 만들지 확정받는다

**끄기만 할 거면 아무것도 묻지 마라.** 바로 3번으로 간다.

켜거나 바꾼다면 두 가지를 받아야 한다.

**형식** — `DOC` · `PDF` · `HTML` · `EXCEL`

**종류** — 하나 이상. 번호가 아니라 이름으로 물어라.

| | | | |
|---|---|---|---|
| 1 프로젝트 요약 | 2 Remaining Defect | 3 Suppressed Defect | 4 Rule 별 Defect |
| 5 Ruleset 별 Defect | 6 Severity 별 Defect | 7 File 별 Defect | 8 모듈 메트릭 |
| 9 파일 메트릭 | 10 클래스 메트릭 | 11 함수 메트릭 | 12 Suppressed 메트릭 |

**전체 교체다.** 1번에서 읽은 것에 더하는 게 아니라, 여기서 정한 것이 전부가 된다. 최종 목록을 보여주고 승인을 받아라.

## 3. 적용한다

```bash
"${KIT_PYTHON}" "${KIT_SKILL_ROOT}/scripts/run.py" report-generator-set on --project-dir "$(pwd)" \
  --format EXCEL --kind 1 --kind 2
```

```bash
"${KIT_PYTHON}" "${KIT_SKILL_ROOT}/scripts/run.py" report-generator-set off --project-dir "$(pwd)"
```

- `off` 에는 `--format` · `--kind` 가 필요 없다.
- `on` 인데 `--kind` 가 없으면 거부된다(`EMPTY_KINDS`). 서버는 그 조합을 저장은 하지만 **분석 후 아무것도 만들지 않는다** — 켜 둔 줄 알고 영영 기다리게 되므로 여기서 막는다.

## 결과 해석

- `ok: true` → `message` 를 전하고, **다음 분석부터** 적용된다는 점을 알려라. 이미 끝난 분석은 소급되지 않는다.
- `code: "EMPTY_KINDS"` → 위 참조.
- `code: "BAD_FORMAT"` · `"BAD_KIND"` → `message` 에 고를 수 있는 값이 들어 있다. 그대로 보여주고 다시 물어라.
- `code: "FORBIDDEN"` (403) → **이 설정 변경은 프로젝트 매니저 권한이다.** 조회는 됐는데 변경만 막혔다면 이 경우다. 매니저에게 요청하도록 안내하라.
- `code: "NO_ACCESS_KEY"` (401) → Arachne 설정의 AccessKey 문제다. **키를 사용자에게 묻거나 파일에 쓰지 마라.**
- `code: "NOT_FOUND"` (404) → 서버에 그 프로젝트가 없거나, 서버가 Open API v1 을 포함하지 않은 구버전이다.
- `code: "NEEDS_BOOTSTRAP"` → 이 프로젝트가 아직 STATIC 에 연결되지 않았다 (`statica-analyze-bootstrap` 스킬).

자동 생성을 켜 두면 **분석마다 보고서가 쌓인다.** 서버 저장 용량을 쓰는 일이니, 매 분석이 아니라 가끔 필요한 것이라면 `/statica:report` 로 그때그때 만드는 편이 낫다는 점을 한 번은 알려 줘라.
