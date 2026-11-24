---
name: upload
description: 'Analyzes the whole project and uploads it to the STATIC server.'
user-invocable: true
disable-model-invocation: true
---

## 설치 경로와 실행 런타임

이 스킬 패키지에는 실행 코드가 없다. 실행 코드와 Python 런타임은 STATIC에 포함된 STATICA Agent Kit(`agent_kit`)에 있고, 이 스킬은 그 코드를 실행하도록 안내한다. 이 문서와 같은 폴더의 참고 문서 링크는 지금 읽은 SKILL.md의 부모 디렉터리(SKILL_ROOT) 기준이다.

첫 실행 전에 아래 값을 한 번 확인하고 같은 대화에서 재사용한다. `${...}` 표기는 설명용이며 자동 설정된 환경변수가 아니다. 실행할 때 실제 절대경로로 바꾸고 따옴표로 감싼다.

- `INSTALL_PATH`: 환경 변수 `ARACHNE_INSTALL_PATH`의 값이다. 값이 없거나 아래 확인에 실패하면 STATIC 설치 폴더 경로를 사용자에게 요청하고 입력을 기다린다. 다른 위치를 추측해 탐색하지 않는다. 실행 코드도 이 환경 변수로 STATIC을 찾으므로, 사용자가 알려 준 경로를 쓸 때는 같은 셸 호출 안에서만 `ARACHNE_INSTALL_PATH`를 그 값으로 설정해 실행하고 영구 환경변수는 수정하지 않는다.
- `KIT_PYTHON`: Agent Kit에 포함된 Python이다. Windows는 `${INSTALL_PATH}/agent_kit/python/python.exe`, Linux는 `${INSTALL_PATH}/agent_kit/python/bin/python3`이다. 시스템 Python이나 PATH의 Python을 쓰지 않는다.
- `KIT_ROOT`: `${INSTALL_PATH}/agent_kit/plugins`이다. 공용 CLI(`${KIT_ROOT}/scripts/run.py`)와 자동 분석 Stop hook(`${KIT_ROOT}/hooks/`)이 여기에 있다.
- `KIT_SKILL_ROOT`: `${KIT_ROOT}/skills/upload`이다. 이 스킬의 스크립트(`scripts/`)가 여기에 있다.

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

현재 프로젝트의 분석 결과를 서버에 반영한다. 라이선스 슬롯을 점유하고 revision을 만드는 무거운 작업이므로 **사용자가 명시적으로 요청했을 때만** 실행한다. `/statica:upload` 호출뿐 아니라 "서버로 업로드해 줘" 같은 자연어 요청도 여기에 해당한다.

```bash
"${KIT_PYTHON}" "${KIT_SKILL_ROOT}/scripts/run.py" upload --project-dir "$(pwd)"
```

- `ok: true` → `message` 를 전하고, 웹 UI에서 revision과 결함 추이를 확인할 수 있다고 알린다.
- `returncode: 113` → 같은 프로젝트가 이미 분석 중이다. 잠시 후 다시 시도하도록 안내한다.
- `returncode: 114` → 라이선스 동시 실행 한도 초과다. 다른 분석이 끝나기를 기다려야 한다.
- 그 밖의 실패는 `hint` 를 그대로 전한다.

**`language` 가 있으면(java · kotlin · python · csharp)** 변경 여부와 무관하게 전량 분석하고 서버에 업로드한다. 일반 분석·Stop 훅의 `--no-upload` 는 이 경로에서 사용하지 않는다. 성공 시 `uploaded: true` 이고, 결함 집계는 프로젝트 전체(`defects.scope: "allSourceFiles"`)다. 실패했다면 업로드가 완료됐다고 말하지 마라.
