---
name: statica-analyze-bootstrap
description: 'pre-analyze 가 `code: NEEDS_BOOTSTRAP` 을 돌려줬을 때, `reason: BOOTSTRAP_IN_PROGRESS`
  로 부트스트랩이 아직 안 끝났다고 할 때, 또는 프로젝트가 STATIC 워크스페이스에 아직 연결되지 않았을 때 읽어라. 언어를 먼저 가른 뒤(C/C++
  인가 java · kotlin · python · csharp 인가) 환경 식별 · 원본 컴파일러 확정 · wrapper 생성 · 치환 · 캡처
  검증 · 서버 등록으로 이어지는 단계를 순서대로 지시하고, 중단된 부트스트랩을 이어서 마치는 법과 되돌리는 법도 담고 있다. 환경별 컴파일러 경로
  · 치환 · 되돌리기 절차는 같은 디렉터리의 environments.md, C/C++ 이 아닌 언어의 절차는 other-languages.md
  에 있다.'
user-invocable: true
disable-model-invocation: false
---

## 설치 경로와 호스트 연결

PLUGIN_ROOT는 이 진입점이 속한 설치 플러그인 루트다. skills/<id>/SKILL.md에서는 ../..이다. 공용 scripts/assets/tmpa는 플러그인 루트에 한 번만 배치한다. 스킬의 references와 보조 문서는 해당 스킬 파일 기준이다.

`${PLUGIN_ROOT}`와 `${PLUGIN_DATA}`가 셸에 자동 설정됐다고 가정하지 않는다. 로드한 파일의 실제 위치로 루트를 확인하고, 실행할 때 실제 절대경로로 대체하거나 동일 셸 호출에서 변수를 설정한다. PLUGIN_DATA는 호스트가 제공하는 영속 데이터 경로를 우선 사용하고, 없으면 사용자 데이터 디렉터리 아래 이 플러그인 전용 경로를 사용한다. 사용자의 분석 대상 작업 디렉터리는 바꾸지 않는다. bash 예제는 bash에서 실행한다.

SKILL_ROOT는 지금 읽은 SKILL.md의 부모 디렉터리다. 이 스킬 전용 scripts/assets는 SKILL_ROOT 아래에 있다. `${SKILL_ROOT}`는 설명용 표기이며 자동 설정된 환경변수가 아니다. 스크립트 실행 시 로드한 SKILL.md의 실제 위치로 절대경로를 구성한다. 프로젝트 작업 디렉터리를 스킬 폴더로 바꾸지 않는다.

## 실행 경로

`${SKILL_ROOT}`는 이 SKILL.md가 있는 디렉터리의 절대 경로로 바꿔 실행한다. 작업 디렉터리는 분석 대상 프로젝트에 유지한다. `scripts/run.py`는 이 플러그인의 공용 런타임을 사용하므로 스킬 폴더만 따로 복사하지 않는다.


**사용자에게는 한국어로 답하라.** 사용자가 다른 언어로 말을 걸었다면 그 언어를 따른다.

# 부트스트랩 절차

부트스트랩은 한 번에 끝나지 않는다. 치환이 GUI 조작인 환경이 대부분이라 중간에 사용자를 기다려야 한다. 각 단계는 별도의 CLI 서브커맨드이고, 진행 상태는 워크스페이스의 `agent.json` 에 남으니 중단됐다가 이어가도 된다. 어느 단계든 프로젝트 경로 하나로 자기 워크스페이스를 되찾는다.

**시작 전에 반드시 사용자 승인을 받아라.** 부트스트랩은 사용자 프로젝트 파일을 고치고, 전체 빌드를 돌리고, 공용 STATIC 서버에 프로젝트를 만든다. 거절하면 그냥 하지 않는다 — Stop 훅은 연결되지 않은 프로젝트에서 아무 말도 하지 않으므로 따로 기록할 것이 없다.

**accessKey 는 어디서도 다루지 않는다.** 사용자에게 묻지도, 파일에 쓰지도 마라 — Arachne 자신의 설정에 이미 있다.

## 1. 증거를 모은다

```bash
python "${SKILL_ROOT}/scripts/run.py" detect --project-dir "$(pwd)"
```

`artifacts` 가 프로젝트에서 보이는 C/C++ 빌드 시스템 단서, `languageArtifacts` 가 C/C++ 이 아닐 가능성을 가리키는 단서(`build.gradle`, `pom.xml`, `*.csproj`, `pyproject.toml` …), `detection` 이 기존 탐지기가 본 것이다. `detection` 이 `null` 이거나 `detectionError` 가 채워져 있어도 실패가 아니다 — 판단은 네 몫이다.

## 1-1. 언어부터 가른다

**이 문서의 나머지(2번 이후)는 전부 C/C++ 전용이다.** java · kotlin · python · csharp 은 절차가 아예 다르다 — wrapper 도, 치환도, 컴파일러 확정도 없다. 그쪽이면 **지금 같은 디렉터리의 `other-languages.md` 로 가고, 아래는 읽지 마라.**

- `languageArtifacts` 만 나오고 `artifacts` 가 비어 있다 → 그 언어다.
- `*.sln` 은 양쪽에 다 잡힌다. 안에 든 것이 `.vcxproj` 면 C/C++, `.csproj` 면 csharp 이다.
- 한 저장소에 여러 언어가 섞여 있으면 **사용자에게 무엇을 분석할지 물어라.** 워크스페이스는 언어마다 하나씩이고, 한 프로젝트 경로에 워크스페이스는 하나만 붙는다 — 지금은 그중 하나만 고를 수 있다.

## 2. 환경을 고른다

같은 디렉터리의 `environments.md` 를 읽어라. 13개 환경의 forge 어휘(`ide`/`compiler`) · 컴파일러 이름 · 경로 형태 · 원본 컴파일러 확인 절차 · 치환 절차 · 빌드 · 검증이 전부 거기 있다. 여기서 되풀이하지 않는다.

세 가지 함정:

- **`arm-none-eabi-gcc` 를 찾았다는 사실만으로는 아무것도 정해지지 않는다.** CodeWarrior Kinetis · STM32CubeIDE · Xilinx Vitis 가 모두 이 실행 파일을 쓴다. 게다가 같은 exe 라도 ide 에 따라 compiler 값이 달라진다(`stm32cubeide`→`arm_gcc`, `xilinx`→`arm_gcc`, `codewarrior`→`gcc`). 프로젝트 산출물(`*.ioc`, `vitis-comp.json`, `C:\Freescale\CW MCU v*`)로 판별하거나 **사용자에게 물어라.**
- **`.cproject`/`.project` 만으로 Eclipse 파생 IDE 들을 구분할 수 없다.** CCS · STM32CubeIDE · CodeWarrior · AURIX · Vitis 가 전부 같은 파일을 쓴다.
- 단서가 여러 환경을 가리키면 **추측하지 말고 물어라.**

## 3. 컴파일러를 확정한다

아래 순서로 시도하고 찾는 즉시 멈춘다.

1. **빌드 산출물** — `CMakeCache.txt` 의 `CMAKE_C_COMPILER:`, `compile_commands.json`, `Makefile` 의 `CC`/`CXX`(+ `make -n`). 이 프로젝트가 실제로 쓰는 값이라 가장 강한 증거다.
2. **`environments.md` 의 경로 형태를 glob** — 버전·에디션 자리는 `*` 로.
3. **가이드의 IDE별 확인 절차** — 대개 IDE 설정 화면에 실제 경로가 적혀 있다. 사용자에게 그 화면을 봐 달라고 요청해도 좋다.
4. **`where`/`which`, `PATH`** — 이름만으로 찾는 것이라 가장 약하다. 같은 이름의 다른 컴파일러를 집을 수 있다.
5. 그래도 못 찾으면 **사용자에게 경로를 물어라. 지어내지 마라.**

## 4. 워크스페이스와 wrapper 를 만든다

**AURIX TriCore GCC 라면 여기 오기 전에 §5 의 해당 절을 먼저 읽어라.** 그 환경만은 `bootstrap-begin` **이전에** 원본 `bin` 을 복사해 두고 `--compiler-path` 를 그 복사본으로 넘겨야 하며, 이 선택은 `begin` 이 끝나면 되돌릴 수 없다.

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-begin \
  --project-dir "$(pwd)" --name "<워크스페이스 이름>" \
  --ide <ide> --compiler <compiler> \
  --compiler-path "<컴파일러 실행 파일 절대경로>" \
  --build-command "<빌드 커맨드>"
```

**`--name` 은 서버 프로젝트 키가 된다.** 영숫자만 남기고 앞의 숫자를 떼었을 때 3자 이상 남아야 한다 — `c++`, `3d` 같은 이름은 쓸 수 없다. 경로 구분자도 안 된다(디렉터리 이름으로 그대로 쓰인다). CLI 가 `bootstrap-begin` 첫머리에서 막고 `code: "BAD_WORKSPACE_NAME"` 을 돌려주니, 그때는 프로젝트 폴더 이름을 영숫자로 다듬어 다시 부르면 된다.

`--build-command` 만 선택이다. 나머지 넷은 필수다. **선택 인자는 값이 없으면 플래그째로 빼라** — 빈 문자열(`--build-command ""`)을 넘기지 마라. GUI 빌드처럼 커맨드가 없는 환경이면 그냥 생략한다.

**소유자 이메일은 묻지 않는다.** 서버가 accessKey 로 계정을 찾아 그 계정을 프로젝트 소유자로 삼는다.

CLI 는 컴파일러를 실제로 실행해 확인한 뒤에야 워크스페이스를 만든다. 실패하면(`stage: "verify-compiler"`) 아무것도 남기지 않는다. 성공하면 결과의 **`wrapperDir` 이 치환에서 가리켜야 할 경로**다.

**MSVC 는 셸 환경이 초기화돼 있어야 한다.** `cl.exe` 는 Developer Command Prompt 밖에서 부르면 필요한 DLL 이 PATH 에 없어 실행 자체가 실패하는 일이 흔하다. **이때의 검증 실패는 경로가 틀렸다는 뜻이 아니다** — 3번으로 돌아가 봐야 같은 경로가 다시 나오고 무한히 맴돈다. `Developer Command Prompt for VS` 에서 실행하거나, `<VS 설치 경로>\VC\Auxiliary\Build\vcvars64.bat` 를 먼저 실행한 **같은 셸에서** `bootstrap-begin` 을 부르라. 그 밖의 환경에서 검증이 실패했다면 그때는 경로 문제이니 3번으로 돌아간다.

**`code: "AGENT_JSON_CORRUPT"` 이 나오면 워크스페이스가 없는 것이 아니라 그 `agent.json` 이 깨진 것이다.** 메시지에 파일 경로가 있다. **여기서 부트스트랩을 새로 시작하지 마라** — 같은 프로젝트에 워크스페이스와 wrapper 가 둘씩 생기고, 사용자의 치환은 여전히 첫 번째를 가리킨다. JSON 문법을 바로잡아 살리거나(§7 · 5번의 손편집이 깨뜨렸을 가능성이 높다), 살릴 수 없으면 사용자에게 확인하고 그 워크스페이스를 지운 뒤 다시 시작하라.

이미 워크스페이스가 있는 프로젝트에서는 `ok: false`, `stage: "existing-workspace"` 와 함께 그 워크스페이스 이름·상태를 돌려주고 아무것도 만들지 않는다. 상태가 `bootstrapping` 이면 이어서 하고(5번 이후), 처음부터 다시 하려면 abort 한다. 상태가 `ready` 면 이미 끝난 프로젝트다 — 부트스트랩할 것이 없다.

## 5. 치환한다

먼저 이 환경의 치환이 **A · B · C 중 무엇인지 정하라.** `environments.md` 의 해당 항목과 §4 치환 유형을 보면 알 수 있다. 셋은 손대는 대상이 다르고, 따라서 guard 여부와 되돌리는 방법이 전부 다르다.

**A. 커맨드라인 치환 — 파일을 고치지 않는다. guard 하지 않는다.**
Makefile·CMake 가이드의 **정규 절차**이고 셋 중 제일 쉽다. 원본 빌드 명령에 변수만 덧붙인다:

```
make all CC=<wrapperDir>\gcc.exe CXX=<wrapperDir>\g++.exe AR=<wrapperDir>\ar.exe
```

(Clang 은 `clang.exe`/`clang++.exe`/`llvm-ar.exe`.) CMake 는 `-DCMAKE_C_COMPILER=… -DCMAKE_CXX_COMPILER=… -DCMAKE_AR=…` 에 `--fresh` 를 붙인다. **Makefile·CMake 프로젝트라면 이것부터 시도하라** — 고친 파일이 없으니 되돌릴 것도 없다. (예외: CMake 를 **Visual Studio 제너레이터**로 쓰는 경우는 유형 2 라 커맨드라인으로 안 되고 C 로 가야 한다. Make/Ninja 제너레이터만 A 가 통한다.)

**A 를 썼으면 `agent.json` 의 `buildCommand` 를 치환된 명령으로 고쳐라.** `--build-command` 는 `bootstrap-begin` 에만 있는데 그 시점엔 `wrapperDir` 이 아직 없어서, 거기 넘긴 값은 **치환되지 않은 원본 명령**이다. 이후 훅이 신규 파일을 캡처하려고 돌리는 재빌드는 `agent.json` 의 이 값을 그대로 실행하므로, 고치지 않으면 **매번 wrapper 없이 빌드되고 그 파일들은 영영 캡처되지 않는다**(빌드는 성공하므로 아무도 에러를 내지 않고, 결국 그 파일들은 분석 대상에서 조용히 제외된다). 워크스페이스의 `.staticdata/.app/agent.json` 을 열어 `buildCommand` 를 위의 **치환된 전체 명령**으로 바꾼다. B·C 는 치환이 파일이나 IDE 설정에 남아 있어 원본 명령 그대로도 wrapper 를 타므로 손댈 필요가 없다.

**B. 파일 편집 — guard 를 먼저 하고 고친다.** 이 두 경우뿐이다.

- **Makefile 에 컴파일러가 하드코딩돼 있어 A 가 먹지 않을 때** — `CC`/`CXX`/`AR` 값을 wrapper 경로로 바꾼다. 이 편집만 `(검증됨)` 이다.
- **Vitis Unified** — `CMakeLists.txt` 에 `set(CMAKE_C_COMPILER …)` 등을 추가하는 것이 **가이드의 정규 절차**다(`environments.md` 3.13: 파일 등가물 "해당 없음", GUI 대안은 `(가이드에 없음)`). 여기서 GUI 를 안내하면 존재하지 않는 절차를 시키는 것이 된다. 다만 사용자 소스이므로 **추가할 줄을 먼저 보여 주고 동의를 받은 뒤** guard → 편집한다.

파일을 고치기 직전에:

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-guard \
  --project-dir "$(pwd)" --file "<고칠 파일>" --file "<또 있으면>"
```

**B 에서는 예외 없이 guard 가 먼저다.** 건너뛰면 되돌릴 것이 없다. `--file` 은 반복 가능하고 최소 하나가 필수다.

**C. GUI 치환 — `bootstrap-guard` 를 실행하지 마라.**
Visual Studio, STM32CubeIDE, CCS(Eclipse·Theia), CodeWarrior(ColdFire·Kinetis·Qorivva), AURIX CCTC, MPLAB X, Microchip Studio 가 여기다. 바꾸는 것이 IDE 설정이라 **보관할 프로젝트 파일이 없다.** `--file` 이 필수 인자라고 해서 경로를 지어내지 마라 — 존재하지 않는 파일을 보관하면 나중에 되돌리기가 "원래 없던 파일"로 보고 **그 파일을 지운다.** 대신 `environments.md` 해당 항목의 GUI 절차를 사용자에게 그대로 안내하고, 끝났다고 알려줄 때까지 기다려라. **사용자가 어느 화면의 무엇을 바꿨는지 기록해 두라** — 되돌릴 수 있는 사람은 사용자뿐이고, Visual Studio 와 Microchip Studio 는 가이드에 되돌리기 절 자체가 없어(`(가이드에 없음)`) **그 기록이 유일한 복구 근거다.**

**AURIX TriCore GCC 는 A·B·C 어디에도 넣지 마라 — 자동화하지 않는다.**
치환이 GUI 조작이 아니라 **원본 컴파일러 `bin` 폴더를 wrapper 파일로 덮어쓰는 파괴적 파일 복사**(유형 6)이고, 그래서 **`bootstrap-begin` 보다 먼저** 해야 하는 단계가 있다: `…/tricore-gcc*/bin` 을 같은 상위 폴더에 `bin_original` 로 복사하고, `--compiler-path` 를 **그 복사본 안의 컴파일러**로 지정해야 한다(CLI 가 `--compiler-path` 의 상위 디렉터리를 wrapper 의 원본 경로로 쓰므로, `begin` 이 끝난 뒤에는 되돌릴 수 없는 선택이다). 이 순서를 어기고 `bin` 을 덮어쓰면 wrapper 가 자기 자신을 가리키게 되고 가이드의 롤백(`bin` 삭제 후 `bin_original` 리네임)도 쓸 수 없게 된다. 이 환경을 만나면 **각 단계를 사용자에게 설명하고, 툴체인 디렉터리를 덮어쓰는 단계 앞에서는 반드시 별도 확인을 받아라.** 어느 단계도 대신 실행하지 마라.

`environments.md` 의 "파일 등가물" 은 B 의 두 경우를 빼면 전부 `(미검증)` 이다. **추정으로 자동 편집하지 마라.**

**IDE 이름으로 치환 유형을 추론하지 마라.** 같은 CodeWarrior v11.1 안에서도 ColdFire·Qorivva 는 컴파일러 `[Command]` 문자열을 바꾸고 Kinetis 는 빌드 변수 `ARMSourceryDir` 을 바꾼다. 판별 단위는 IDE 가 아니라 툴체인이다. 표에 없는 환경은 `environments.md` §4 의 6유형으로 따져라.

## 6. 빌드하고 캡처를 확인한다

빌드 커맨드가 있으면 실행하고, GUI 빌드면 사용자에게 요청한다. 대부분의 환경은 **Clean 이 사실상 필수**다. 그 다음:

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-verify --project-dir "$(pwd)"
```

**빌드가 성공했다는 것과 wrapper 를 탔다는 것은 다른 이야기다.** 여기서 `ok: false` 면 빌드가 wrapper 를 거치지 않은 것이다 — 분석할 것이 없는 워크스페이스가 조용히 남는 원래의 버그가 바로 이것이다. 대응은 방금 쓴 치환 방식에 따라 갈린다.

**치환이 A(커맨드라인)였다면** — 고친 파일이 없으니 abort 할 것도 없다. 덧붙인 변수가 실제로 먹었는지(`make -n`, CMake 는 `--fresh` 를 빠뜨리지 않았는지) 확인하고 Clean 후 다시 빌드한 뒤 `bootstrap-verify` 를 다시 실행한다. 그래도 안 되면 B 또는 C 로 옮긴다.

**치환이 B(파일 편집)였다면** — `bootstrap-abort` 로 되돌린다. 단 **abort 는 wrapper 와 워크스페이스까지 지운다. `wrapperDir` 이 사라지므로 다시 하려면 `bootstrap-begin` 부터 새로 시작해야 한다.** 순서는 이렇다:

1. `bootstrap-abort` → 프로젝트 파일 원복.
2. 원래 빌드 명령으로 한 번 더 빌드해 본다. 여전히 실패하면 **원래 빌드가 깨져 있던 것**이니 사용자에게 알리고 멈춰라(우리 문제가 아니다). 성공하면 우리 치환이 원인이다.
3. `bootstrap-begin` 을 다시 실행해 **새 wrapper 를 받는다.** 그 결과의 새 `wrapperDir` 을 가지고 C(GUI 안내)로 전환한다. 이 단계를 빠뜨리면 사용자에게 이미 삭제된 경로를 불러 주게 된다.

**치환이 이미 C(GUI)였다면 abort 하지 마라.** wrapper 와 워크스페이스는 멀쩡하고 잘못된 것은 사용자의 IDE 설정뿐이다. 지우면 사용자가 방금 입력한 wrapper 경로가 가리킬 곳이 없어지고, 처음부터 다시 해야 한다. 대신 `environments.md` 해당 항목의 **검증** 절대로 사용자와 함께 확인하라 — 빌드 로그에서 실제 호출된 컴파일러가 wrapper 경로인지, Clean 을 거쳤는지. 설정을 고쳐 다시 빌드한 뒤 `bootstrap-verify` 를 다시 실행한다. 몇 번이든 다시 부를 수 있다.

## 7. 마무리

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-finish --project-dir "$(pwd)"
```

캡처를 다시 확인하고, 서버에 프로젝트를 만들고, 워크스페이스를 `ready` 로 표시한다.

**`stage: "project"` 로 실패했다면 캡처는 멀쩡하고 서버 등록만 실패한 것이다. 여기서 abort 하지 마라 — 다 끝낸 빌드와 캡처를 통째로 버리게 된다.** 상태가 `bootstrapping` 으로 남아 있으므로 원인을 고치고 `bootstrap-finish` 를 몇 번이든 다시 부르면 된다. `projectCreation.code` 가 원인을 짚어 준다:

| `code` | 뜻과 대응 |
| --- | --- |
| `NO_ACCESS_KEY` | 서버가 AccessKey 를 거절했다(401). Arachne 설정의 키가 이 서버의 것이 맞는지, 그 계정이 활성 상태인지 확인하도록 안내하라. **키를 사용자에게 묻거나 파일에 쓰지 마라.** |
| `ENDPOINT_NOT_FOUND` | 서버에 Open API v1 이 없다(404). 서버가 구버전이다 — 올려야 한다. 소유자 이메일 문제가 아니다. |
| `NO_SERVER_SETTING` · `NO_SERVER_URL` | Arachne 설정에 서버 주소가 없다. |
| (없음) | 메시지에 HTTP 상태와 서버 응답 본문이 그대로 들어 있다. 그것을 전하라. |

**결과에 `buildCommandWarning` 이 있으면 그 문장을 사용자에게 그대로 전하라.** `agent.json` 의 `buildCommand` 에 `wrapperDir` 이 보이지 않는다는 뜻이다 — 커맨드라인 치환(A)을 썼는데 §5 의 손편집을 빠뜨렸다면 지금 고쳐야 한다(고치고 `bootstrap-finish` 를 다시 부를 필요는 없다. 값만 고치면 된다). 파일·GUI 치환(B·C)이면 원본 명령 그대로가 맞으니 그렇다고 답하고 넘어가라. **실패가 아니다** — `ok` 는 참이고 부트스트랩은 끝난 것이다.

**`finish` 는 성공하는 순간 `bootstrap-guard` 로 보관해 둔 원본을 지운다.** 되돌릴 것이 남지 않았다는 뜻이므로, 이 뒤로 연결을 끊는 일은 abort 가 대신해 주지 않는다. 파일을 고쳐 치환한 프로젝트(B)나 IDE 설정을 바꾼 프로젝트(C)에서 나중에 STATIC 을 떼어내려면 **먼저 치환을 되돌리고**(환경별 절차는 `environments.md` 의 "되돌리기" 항목) 그 다음에 워크스페이스를 지워야 한다. 순서를 바꾸면 사용자의 Makefile·IDE 설정이 사라진 wrapper 경로를 가리킨 채 남아 빌드가 깨진다.

**`finish` 가 전체 분석과 서버 업로드까지 같이 끝낸다.** 결과의 `fullAnalysis` 가 그 결과다 — `/statica:upload` 와 같은 모양이다. 사용자가 원한 것은 워크스페이스가 아니라 분석 결과이므로, 프로젝트당 한 번뿐인 이 자리에서는 **물어보지 않고 그냥 돌린다.**

- **`finish` 뒤에 `pre-analyze` 를 다시 부르지 마라.** 방금 돈 전체 빌드가 모든 TU 캐시를 소스보다 나중으로 만들어 놓아서 증분 분석은 언제나 "변경된 대상이 없습니다"로 끝난다. 그것을 사용자에게 보고하면 분석이 안 된 것처럼 읽힌다.
- `fullAnalysis.ok` 가 참이면 결함 요약을 전하고, 웹 UI 에서 revision 을 볼 수 있다고 알려라.
- `fullAnalysis.ok` 가 거짓이어도 **부트스트랩은 끝난 것이다**(`result.ok` 는 참이고 상태는 `ready`). 되돌리려 하지 마라 — 분석만 다시 돌리면 된다. `hint` 를 전하고 `/statica:upload` 로 재시도하도록 안내하라.

## 중단된 부트스트랩 이어가기

세션이 끊겼거나 `pre-analyze` 가 `reason: "BOOTSTRAP_IN_PROGRESS"` 를 돌려줬다면 **처음부터 다시 하지 마라.** 이전 세션의 판단은 전부 워크스페이스에 남아 있다.

먼저 워크스페이스를 찾는다. `bootstrap-verify --project-dir "$(pwd)"` 가 결과에 `workspace` 를 담아 준다. `bootstrap-begin` 을 다시 불러도 되는데, 그러면 아무것도 만들지 않고 `stage: "existing-workspace"` 와 함께 `workspace` · `workspaceName` · `status` 를 알려준다.

그 워크스페이스의 `.staticdata/.app/agent.json` 에 이어가는 데 필요한 값이 전부 있다:

| 키 | 쓸모 |
|---|---|
| `wrapperDir` | 치환이 가리켜야 할 경로 (§5) |
| `wrapperName` | wrapper 이름 |
| `ide` · `compiler` · `compilerPath` | 2·3번에서 이미 내린 판단 — 다시 정하지 마라 |
| `buildCommand` | 6번에서 돌릴 빌드 명령 (`null` 이면 GUI 빌드) |
| `status` | `bootstrapping` 이면 미완, `ready` 면 끝난 것 |

여기서 읽어 §5 또는 §6 부터 이어간다.

## 되돌리기

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-abort --project-dir "$(pwd)" --reason "<이유>"
```

보관해 둔 프로젝트 파일을 되돌리고, wrapper 와 워크스페이스를 지운다.

- **GUI 로 치환한 환경(C)은 abort 만으로 끝나지 않는다.** 보관한 파일이 없으니 abort 는 되돌릴 것이 없다며 `ok: true` 를 돌려주지만, 사용자의 IDE 는 여전히 **방금 삭제된 wrapper 디렉터리**를 가리키고 있다 — 그대로 두면 사용자의 빌드가 깨지고, 우리는 성공했다고 보고한 셈이 된다. **abort 하기 전에(늦어도 직후에) `environments.md` 해당 항목의 "되돌리기" 절을 사용자에게 안내하라.** 항목마다 값이 적혀 있다 — 예컨대 CCS 는 `[Command]` 를 `${CG_TOOL_CL}` 로, CodeWarrior Kinetis 는 `ARMSourceryDir` 삭제, AURIX CCTC 는 [Restore Defaults], MPLAB X 는 [Scan for Build Tools]. **abort 의 `ok: true` 는 "워크스페이스를 지웠다"는 뜻이지 "사용자 환경이 깨끗하다"는 뜻이 아니다.**
- **`ok: false` 면 사용자 프로젝트가 고쳐진 채로 남아 있다.** `restore.failed` 의 파일 목록과 `snapshotDir` 의 보관본 위치를 **요약하지 말고 그대로 전하라.** 이것이 이 플러그인에서 가장 나쁜 결말이다. 이때는 워크스페이스를 지우지 않는다 — 유일한 원본 사본이 그 안에 있다.
- **`ready` 워크스페이스는 abort 하지 않는다.** `stage: "already-bootstrapped"` 와 함께 거절하고 아무것도 지우지 않는다. abort 는 진행 중인 시도를 물리는 것이지 끝난 연결을 해제하는 것이 아니다. 끝난 연결을 정말 끊어야 한다면 §7 의 순서를 지켜라 — **치환을 먼저 되돌리고**, 그 다음에 워크스페이스를 지운다. `hint` 도 같은 말을 한다.
