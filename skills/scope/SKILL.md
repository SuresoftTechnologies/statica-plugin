---
name: scope
description: 분석에서 뺄 파일·디렉터리·빌드 모듈을 영구 설정한다
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

이 프로젝트의 **분석 범위**를 보여주고 바꾼다. 생성 코드·서드파티·테스트 픽스처처럼 결함을 봐도 고칠 생각이 없는 것들을 빼는 데 쓴다. 지금까지 Arachne UI 에서만 할 수 있던 일이다.

설정은 워크스페이스의 `analysis.scope.json` 에 남고 **Arachne UI 와 같은 파일을 공유한다.** 여기서 바꾸면 UI 에도 그대로 보인다.

## 1. 지금 상태부터 읽는다. 예외 없다.

```bash
python "${SKILL_ROOT}/scripts/run.py" scope-show --project-dir "$(pwd)"
```

- `excluded` 는 지금 빠져 있는 것, `included` 는 **빠진 폴더 안에서 되살려 둔 예외**다.
- `scopeFile` 은 실제로 읽고 쓰는 파일이다. 위치가 언어마다 달라서(`C/C++` 은 `.staticdata/config/` 아래, 나머지는 워크스페이스 루트) 뭔가 이상할 때 제일 먼저 볼 값이다.
- `modules` 는 C/C++ 빌드 모듈 목록이다 (다른 언어에서는 빈 목록). `output` 이 모듈의 식별자이자 `--path` 에 넣을 값이고, `skipped` 가 지금 빠져 있는지다. `capturedSources` 와 `analyzedTus` 가 어긋나면 아직 분석되지 않은 소스가 있다는 뜻이다.
- `skippedModules` 는 지금 통째로 빠져 있는 모듈들이다. **파일·디렉터리 제외와 축이 다르다** — 소스 경로가 아니라 그 모듈이 만들어 내는 **빌드 산출물 경로**가 들어간다. Arachne UI 도 같은 값을 쓴다.

## 2. 규칙을 알고 다뤄라. 여기서 틀리면 조용히 어긋난다.

**가장 가까운 조상이 이긴다.** 폴더를 빼면 그 아래가 전부 빠진다. 그 안에서 하나만 되살리려면 `scope-include` 로 예외를 만든다. 그래서 `included` 목록은 화이트리스트가 아니라 **예외 목록**이다.

**glob 은 받지 않는다.** `**/*.test.py` 같은 건 안 된다. 비교가 완전 일치라서다. 사용자가 패턴으로 말하면 **먼저 매칭되는 실제 경로를 찾아 목록으로 보여주고 확정받아라.** 폴더 하나로 묶을 수 있으면 그게 낫다: 항목 40개보다 디렉터리 1개가 유지 가능하다.

**없는 경로는 거부된다**(`NO_SUCH_PATH`). 오타를 그냥 받으면 아무것도 제외되지 않은 채로 "제외했습니다"가 되기 때문이다.

**제외는 분석 대상 목록에만 걸린다. 헤더는 뺄 수 없다**(`NOT_ANALYZABLE`). C/C++ 의 분석 단위는 TU, 즉 빌드에서 컴파일된 소스다. `.h` 는 거기 없으므로 목록에 넣어도 아무 일도 일어나지 않는다 (실측: 헤더를 넣고 분석해도 6/6 그대로였다). **헤더의 결함을 없애려면 범위가 아니라 다른 수단이 필요하다** — 그 헤더를 include 한 소스를 빼거나, 서버에서 결함을 억제하는 것이다. 사용자가 헤더를 빼달라고 하면 이 사실을 먼저 말해라. Arachne UI 에서도 헤더는 애초에 고를 수 없다.

**모듈 단위 제외가 나은 경우가 있다.** 빌드 도구 자신이 만든 모듈이 대표적이다 — CMake 는 구성 단계에서 컴파일러를 시험하느라 `CMakeCXXCompilerId.cpp` · `CMakeCXXCompilerABI.cpp` 를 컴파일하고, 그것들이 wrapper 를 거치면서 **캡처에 그대로 들어온다** (실측: 결함의 65%가 이 파일들이었다). 이런 것은 파일을 하나씩 빼는 것보다 모듈을 통째로 빼는 쪽이 짧고 유지 가능하다. `linkCommand` 가 `-Wl,--help` 이거나 `CMakeC*CompilerId` 를 가리키면 그 모듈이다.

**다만 사용자가 정할 일이다.** `build/` 아래에 `configure_file` 로 만든 진짜 소스를 두는 프로젝트도 있다. 무엇이 노이즈인지 우리가 단정하지 말고, `modules` 를 보여주고 확정받아라.

## 3. 적용한다

```bash
python "${SKILL_ROOT}/scripts/run.py" scope-exclude --project-dir "$(pwd)" \
  --path src/generated --path third_party
```

```bash
python "${SKILL_ROOT}/scripts/run.py" scope-include --project-dir "$(pwd)" \
  --path src/generated/keep_this.c
```

- `--path` 는 반복한다. 프로젝트 기준 상대경로도 되고 절대경로도 된다.
- 파일인지 디렉터리인지는 **말하지 않아도 된다.** 디스크를 보고 정한다.
- 하나라도 없는 경로가 섞이면 **아무것도 쓰지 않고 멈춘다.** 일부만 적용되면 무엇이 들어갔는지 알 수 없어서다.
- 룰셋과 달리 **전체 교체가 아니다.** 지금 목록에 더하고 빼는 방식이라, 빼려는 것만 말하면 된다.

### 모듈 단위 (C/C++ 만)

```bash
python "${SKILL_ROOT}/scripts/run.py" scope-skip-module --project-dir "$(pwd)" \
  --path /proj/build/CMakeFiles/3.28.3/CompilerIdCXX/a.exe
```

```bash
python "${SKILL_ROOT}/scripts/run.py" scope-unskip-module --project-dir "$(pwd)" \
  --path /proj/build/libcalc.a
```

- `--path` 는 `scope-show` 의 `modules[].output` 이다. 모듈 디렉터리 이름(`libcalc.a_FFBA68…`)도 받아 주지만, **파일에 적히는 값은 언제나 산출물 경로다** — 디렉터리 이름을 그대로 적으면 UI 가 적어 둔 값과 안 맞아 아무 일도 일어나지 않는다.
- 모르는 값은 거부된다(`NO_SUCH_MODULE`). `knownModules` 에 쓸 수 있는 값이 들어 있다.
- 파일·디렉터리 제외와 **섞이지 않는다.** 모듈을 빼도 `excluded` 는 그대로다.

## 4. 바뀌었으면 전체 재분석을 물어본다

3번이 `ok: true` 이고 실제로 목록이 달라졌을 때만 묻는다.

**제외해도 이미 서버에 올라간 결함은 사라지지 않는다.** 다음 분석부터 빠진다. 지금 정리하려면 전체 재분석이 필요하다.

물을 때 비용을 함께 말해라: revision 이 하나 더 생기고, 라이선스 슬롯을 점유하고, 전체를 다시 도는 작업이라 시간이 걸린다.

**언어에 따라 권할 이유가 다르다.**

- **C/C++** : `/statica:pre-analyze` 는 바뀐 TU 만 돈다. 재분석하지 않으면 **손대지 않은 파일의 옛 결함이 계속 남는다.** 권할 이유가 있다.
- **java · kotlin · python · csharp** : `pre-analyze` 자체가 전량이라 다음 분석에 저절로 맞춰진다.

**하겠다고 했을 때만 실행한다. 아니라고 하면 아무것도 하지 말고 끝내라.**

```bash
python "${PLUGIN_ROOT}/scripts/run.py" upload --project-dir "$(pwd)"
```

- `ok: true` → `message` 를 전한다. 이 결과는 **새 범위로 나온 것**이다.
- `returncode: 113` (이미 분석 중) / `114` (라이선스 한도) → 잠시 후 다시 시도하도록 안내하되, **범위 변경 자체는 이미 저장됐다**고 분명히 해라.
- 그 밖의 실패도 `hint` 를 전하면서 범위 변경은 성공했다고 말해라.

## 결과 해석

- `code: "NO_SUCH_PATH"` → `missing` 에 못 찾은 경로가 있다. 오타이거나 이미 지워진 파일이다. **아무것도 바뀌지 않았다.**
- `code: "NOT_ANALYZABLE"` → 있긴 하지만 제외해 봐야 소용없는 것이다. `rejected[].reason` 에 이유가 있으니 **그대로 전해라.** 헤더가 대부분이다. **아무것도 바뀌지 않았다.**
- `code: "NO_PATHS"` → `--path` 를 하나도 주지 않았다.
- `code: "NO_SUCH_MODULE"` → 그런 모듈이 없다. `knownModules` 를 보여주고 다시 고르게 하라. **아무것도 바뀌지 않았다.**
- `code: "NO_MODULES"` → 빌드 모듈은 C/C++ 에만 있다. 다른 언어는 `scope-exclude` 로 파일을 뺀다.
- `code: "NEEDS_BOOTSTRAP"` → 이 프로젝트가 아직 STATIC 에 연결되지 않았다 (`statica-analyze-bootstrap` 스킬).

**범위를 바꾼 뒤 결함 수가 달라진 것은 코드가 아니라 범위가 바뀐 결과다.** 결과를 보고할 때 반드시 함께 말하라. 말하지 않으면 사용자는 자기 코드가 좋아졌다고 읽는다. 특히 **제외는 결함을 없앤 것이 아니라 보지 않기로 한 것**이라는 점을 흐리지 마라.
