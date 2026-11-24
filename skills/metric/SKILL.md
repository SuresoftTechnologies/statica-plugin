---
name: metric
description: 'Turns individual code metrics on or off for measurement.'
user-invocable: true
disable-model-invocation: true
---

## 설치 경로와 실행 런타임

이 스킬 패키지에는 실행 코드가 없다. 실행 코드와 Python 런타임은 STATIC에 포함된 STATICA Agent Kit(`agent_kit`)에 있고, 이 스킬은 그 코드를 실행하도록 안내한다. 이 문서와 같은 폴더의 참고 문서 링크는 지금 읽은 SKILL.md의 부모 디렉터리(SKILL_ROOT) 기준이다.

첫 실행 전에 아래 값을 한 번 확인하고 같은 대화에서 재사용한다. `${...}` 표기는 설명용이며 자동 설정된 환경변수가 아니다. 실행할 때 실제 절대경로로 바꾸고 따옴표로 감싼다.

- `INSTALL_PATH`: 환경 변수 `ARACHNE_INSTALL_PATH`의 값이다. 값이 없거나 아래 확인에 실패하면 STATIC 설치 폴더 경로를 사용자에게 요청하고 입력을 기다린다. 다른 위치를 추측해 탐색하지 않는다. 실행 코드도 이 환경 변수로 STATIC을 찾으므로, 사용자가 알려 준 경로를 쓸 때는 같은 셸 호출 안에서만 `ARACHNE_INSTALL_PATH`를 그 값으로 설정해 실행하고 영구 환경변수는 수정하지 않는다.
- `KIT_PYTHON`: Agent Kit에 포함된 Python이다. Windows는 `${INSTALL_PATH}/agent_kit/python/python.exe`, Linux는 `${INSTALL_PATH}/agent_kit/python/bin/python3`이다. 시스템 Python이나 PATH의 Python을 쓰지 않는다.
- `KIT_ROOT`: `${INSTALL_PATH}/agent_kit/plugins`이다. 공용 CLI(`${KIT_ROOT}/scripts/run.py`)가 여기에 있다.
- `KIT_SKILL_ROOT`: `${KIT_ROOT}/skills/metric`이다. 이 스킬의 스크립트(`scripts/`)가 여기에 있다.

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

이 프로젝트가 측정할 **코드 메트릭**을 켜고 끈다. 순환복잡도·중첩깊이·LOC 같은 것들이다. 지금까지 Arachne UI 의 Project Settings 에서만 할 수 있던 일이다.

**이 커맨드가 다루는 것은 사용 여부뿐이다.** 경고 임계값(Diagnosis 단계)은 건드리지 않는다. 사용자가 "복잡도 10 넘으면 경고" 같은 것을 원하면 웹 UI 로 안내하라.

## 1. 지금 상태부터 읽는다

```bash
"${KIT_PYTHON}" "${KIT_SKILL_ROOT}/scripts/run.py" metric-show --project-dir "$(pwd)"
```

`bySection` 에 섹션별로 묶여 있다. **섹션 구성은 언어가 정한다** — C/C++ 은 `FUNCTION` · `FILE` · `CLASS` · `MODULE` 네 개이고, java·kotlin·python·csharp 은 `CLASS` 가 없다. 우리가 정하는 것이 아니라 서버가 내려주는 `sections` 를 그대로 따라라.

**표로 보여줘라.** 34개까지 나오므로 문장으로 나열하면 읽을 수 없다. 섹션마다 이렇게:

| | key | 이름 |
|---|---|---|
| ✓ | FUNST | Number of Statements |
| | FUCYC | Cyclomatic Complexity |

`key` 를 반드시 함께 보여라 — 다음 단계에서 그것으로 지정한다.

목록이 길면 **켜진 것을 먼저, 꺼진 것은 접어서** 보여주고 "전체를 보시겠습니까"로 물어도 좋다. 다만 사용자가 특정 섹션을 말했다면 그 섹션은 전부 펼쳐라.

## 2. 무엇을 켜고 끌지 확정받는다

**전체 교체가 아니다.** 말한 것만 바뀌고 나머지는 그대로다. 그래서 룰셋처럼 "최종 목록 전체"를 확인시킬 필요는 없고, **바뀌는 것만** 보여주면 된다.

사용자가 이름으로 말하면(`복잡도` 처럼) 목록에서 찾아 **어느 key 인지 확인시킨 뒤** 진행하라. 이름이 여러 개에 걸리면 물어라.

## 3. 적용한다

```bash
"${KIT_PYTHON}" "${KIT_SKILL_ROOT}/scripts/run.py" metric-set --project-dir "$(pwd)" \
  --on FUCYC --on FUMNC --off FUNGS
```

- `--on` · `--off` 는 반복한다. 한 번의 호출로 **한 트랜잭션**에서 처리된다.
- 같은 key 를 양쪽에 주면 `--off` 가 이긴다.

## 결과 해석

- `ok: true` → `message` 를 전하고, **다음 분석부터** 반영된다는 점을 알려라. 이미 올라간 revision 의 메트릭 값은 바뀌지 않는다.
- `code: "UNKNOWN_METRIC"` (404) → key 가 틀렸다. **아무것도 바뀌지 않았다** — 서버가 한 트랜잭션으로 처리하므로 부분 적용은 없다. 1번을 다시 읽어 정확한 key 를 확인하라.
- `code: "NO_CHANGES"` → `--on` · `--off` 를 하나도 주지 않았다.
- `code: "FORBIDDEN"` (403) → **metric 설정 변경은 프로젝트 소유자만 할 수 있다.** 조회는 됐는데 변경만 막혔다면 이 경우다.
- `code: "NO_ACCESS_KEY"` (401) → Arachne 설정의 AccessKey 문제다. **키를 사용자에게 묻거나 파일에 쓰지 마라.**
- `code: "NOT_FOUND"` (404) → 서버에 그 프로젝트가 없거나, 서버가 Open API v1 을 포함하지 않은 구버전이다.
- `code: "NEEDS_BOOTSTRAP"` → 이 프로젝트가 아직 STATIC 에 연결되지 않았다 (`statica-analyze-bootstrap` 스킬).

**메트릭을 끄면 그 지표가 사라진다.** 값이 좋아지는 것이 아니라 측정하지 않게 되는 것이다. 끄자고 제안할 때는 그 사실을 분명히 하고, 이후 분석 결과를 보고할 때도 지표가 줄어든 이유가 설정 변경임을 함께 말하라.
