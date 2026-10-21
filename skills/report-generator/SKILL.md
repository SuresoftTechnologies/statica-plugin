---
name: report-generator
description: 분석이 끝나면 보고서를 자동 생성할지 설정한다
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

**분석이 성공하면 서버가 알아서 보고서를 만들어 두는** 기능을 켜고 끈다. 여기서 설정만 해두면 그 뒤로는 손댈 것이 없다.

**`/statica:report` 와 관계가 없다.** 그쪽은 "지금 하나 만들어서 받기"고, 이쪽은 "앞으로 매번 자동으로"다. 이 설정을 읽어서 `/statica:report` 를 부르는 식으로 엮지 마라 — 서버가 분석 후에 직접 만든다.

## 1. 지금 설정부터 읽는다

```bash
python "${SKILL_ROOT}/scripts/run.py" report-generator-show --project-dir "$(pwd)"
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
python "${SKILL_ROOT}/scripts/run.py" report-generator-set on --project-dir "$(pwd)" \
  --format EXCEL --kind 1 --kind 2
```

```bash
python "${SKILL_ROOT}/scripts/run.py" report-generator-set off --project-dir "$(pwd)"
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
