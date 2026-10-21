---
name: upload
description: 프로젝트 전체를 분석해 STATIC 서버에 업로드한다
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

현재 프로젝트의 분석 결과를 서버에 반영한다. 라이선스 슬롯을 점유하고 revision을 만드는 무거운 작업이므로 **사용자가 명시적으로 요청했을 때만** 실행한다. `/statica:upload` 호출뿐 아니라 "서버로 업로드해 줘" 같은 자연어 요청도 여기에 해당한다.

```bash
python "${SKILL_ROOT}/scripts/run.py" upload --project-dir "$(pwd)"
```

- `ok: true` → `message` 를 전하고, 웹 UI에서 revision과 결함 추이를 확인할 수 있다고 알린다.
- `returncode: 113` → 같은 프로젝트가 이미 분석 중이다. 잠시 후 다시 시도하도록 안내한다.
- `returncode: 114` → 라이선스 동시 실행 한도 초과다. 다른 분석이 끝나기를 기다려야 한다.
- 그 밖의 실패는 `hint` 를 그대로 전한다.

**`language` 가 있으면(java · kotlin · python · csharp)** 변경 여부와 무관하게 전량 분석하고 서버에 업로드한다. 일반 분석·Stop 훅의 `--no-upload` 는 이 경로에서 사용하지 않는다. 성공 시 `uploaded: true` 이고, 결함 집계는 프로젝트 전체(`defects.scope: "allSourceFiles"`)다. 실패했다면 업로드가 완료됐다고 말하지 마라.
