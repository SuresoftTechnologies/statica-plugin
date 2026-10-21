# STATIC 부트스트랩 — 빌드 환경 레퍼런스

에이전트가 부트스트랩(빌드 환경 식별 → 원본 컴파일러 탐지 → wrapper 생성 → wrapper 를 통한 빌드 → 캡처 검증)을 수행할 때 읽는 단일 참조 파일이다.

출처는 두 갈래다.
- `${ARACHNE_INSTALL_PATH}/docs/ko/*.pdf` — Suresoft 가 배포하는 환경별 한국어 가이드 16종. 각 항목의 **원본 컴파일러 확인 / 치환 / 빌드 / 검증 / 되돌리기** 는 전부 여기서 왔다.
- 플러그인 자체 설정 — `${SKILL_ROOT}/assets/config/known_paths.json`(설치 경로 glob·실행 파일 시드), `${SKILL_ROOT}/assets/config/wrapper_forge.json`(forge 어휘·역매핑·치환 레시피). 각 항목의 **경로 형태 / 컴파일러 이름** 은 가이드의 예시 경로가 아니라 이 설정의 일반화된 glob 을 정본으로 쓴다.

Arachne 가 갱신되면 `tools/regen-environments.py` 가 PDF 원문 텍스트를 다시 추출한다. 추출본은 `tools/extracted-guides/`, 사람이 정리한 중간 산출물은 `tools/curated/` 에 있다.

표기 규약:
- `(가이드에 없음)` — 원문 가이드가 해당 정보를 제공하지 않음.
- `(미검증)` — 실제로 동작하는지 확인되지 않은 추정 절차. **자동 편집 금지, 사용자에게 GUI 안내로 갈 것.**
- `(가이드 외 출처 — 확인 필요)` — 가이드가 주장한 내용이 아니라 일반 지식으로 채운 필드.
- **자동 치환이 검증된 유일한 경로는 Makefile 의 `CC`/`CXX`/`AR` 교체뿐이다.** 나머지는 전부 안내만 한다.

---

## 1. forge 어휘 (폐쇄 집합)

`wrapper-forge` 는 아래 조합 밖의 값을 거부한다. IDE 화면에 보이는 `[Vendor]` 표시 문자열과 CLI `--ide` 값은 서로 다르므로(§6 참조) 반드시 아래 왼쪽 열의 값을 쓴다. `[Compiler Type]` 문자열은 GUI/CLI 가 동일하다.

| ide | 가능한 compiler |
|---|---|
| `ccs` | `cl2000`, `c6000` |
| `microchips` | `xc8_avr`, `xc8`, `xc16`, `xc32`, `arm_gcc`, `avr8`, `avr32` |
| `mplab` | `xc8_avr`, `xc8`, `xc16`, `xc32`, `arm_gcc`, `avr8`, `avr32` |
| `stm32cubeide` | `arm_gcc` |
| `xilinx` | `arm_gcc`, `arm64_gcc`, `mb_gcc` |
| `gnu` | `gcc` |
| `visualstudio` | `cl` |
| `llvm` | `clang` |
| `codewarrior` | `mwccmcf`, `mwcceppc`, `gcc` |
| `aurix` | `cctc`, `gcc` |

---

## 2. 실행 파일 → 환경 역매핑

컴파일러를 먼저 찾았고 환경 이름을 붙여야 할 때 쓴다. `wrapper_forge.json` 의 `by_exe` 순서 그대로이며 **위에서부터 fnmatch, 첫 일치가 이긴다** — `cl` 이 `cl2000`/`cl6x`/`clang` 보다 아래에, `gcc` 가 `tricore-*-gcc`/`aarch64-none-elf-gcc`/`mb-gcc` 보다 아래에 있는 것은 의도된 순서다.

| # | exe stem (fnmatch) | ide | compiler |
|---|---|---|---|
| 1 | `cl2000` | `ccs` | `cl2000` |
| 2 | `cl6x` | `ccs` | `c6000` |
| 3 | `cctc` | `aurix` | `cctc` |
| 4 | `tricore-*-gcc` | `aurix` | `gcc` |
| 5 | `aarch64-none-elf-gcc` | `xilinx` | `arm64_gcc` |
| 6 | `mb-gcc` | `xilinx` | `mb_gcc` |
| 7 | `mwccmcf` | `codewarrior` | `mwccmcf` |
| 8 | `mwcceppc` | `codewarrior` | `mwcceppc` |
| 9 | `xc8-cc` | `microchips` | `xc8` |
| 10 | `xc8` | `microchips` | `xc8` |
| 11 | `clang` | `llvm` | `clang` |
| 12 | `cl` | `visualstudio` | `cl` |
| 13 | `g++` | `gnu` | `gcc` |
| 14 | `gcc` | `gnu` | `gcc` |

> **경고 — `arm-none-eabi-gcc` 는 역매핑 대상이 아니다.**
> `wrapper_forge.json` 의 `ambiguous_exe` 에 등록돼 있다: *"arm-none-eabi-gcc ships with codewarrior (Kinetis), stm32cubeide, and xilinx. Pass --ide and --compiler explicitly."*
> 즉 이 실행 파일을 찾았다는 사실만으로는 환경이 결정되지 않는다. 프로젝트 산출물(`.ioc` → STM32CubeIDE, `vitis-comp.json`/`*.prj` → Vitis, `*.mcp`/Freescale 설치 경로 → CodeWarrior)로 판별하거나 **사용자에게 물어라. 추측하지 말 것.**
> 같은 exe 라도 ide 에 따라 compiler 값이 달라진다: `stm32cubeide`→`arm_gcc`, `xilinx`→`arm_gcc`, `codewarrior`→**`gcc`**(`arm_gcc` 아님, 폐쇄 집합에 없음).

> `mplab` 은 `by_exe` 에 등장하지 않는다. `xc8-cc`/`xc8` 은 전부 `microchips` 로 떨어지므로, MPLAB X 프로젝트임을 알고 있다면 `--ide mplab` 을 명시적으로 넘겨야 한다.

---

## 3. 환경별 항목 (13종)

### 3.1 Visual Studio C/C++

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `*.sln`, `*.vcxproj`. 가이드는 프로젝트 파일 glob 을 명시하지 않는다`(가이드에 없음)`. 원문 전제는 "Visual Studio 로 열리는 MSBuild 프로젝트"(속성 관리자에 프로젝트가 보이는 상태). 적용 환경: Windows 11 / VS 2022.
- **forge 어휘** — `ide=visualstudio`, `compiler=cl` (원문 `[Vendor]: VisualStudio`, `[Compiler Type]: cl`)
- **컴파일러 이름** — `cl.exe` (링커 `link.exe`, 아카이버 `lib.exe`)
- **경로 형태** — `C:/Program Files/Microsoft Visual Studio/*/*/VC/Tools/MSVC/*/bin/Host*/*`, `C:/Program Files (x86)/Microsoft Visual Studio/*/*/VC/Tools/MSVC/*/bin/Host*/*`
- **원본 컴파일러 확인** — [도구] → [옵션] → [프로젝트 및 솔루션] → [빌드 및 실행] 에서 "MSBuild 프로젝트 빌드 출력의 세부 정보 표시"와 "MSBuild 프로젝트 빌드 로그 파일의 세부 정보 표시"를 모두 **상세(자세히)** 로 변경 → 프로젝트 우클릭 [빌드](또는 소스 우클릭 [컴파일]) → 출력에서 `Ctrl+F` 로 `cl.exe` 검색.
- **치환 (유형 2)** — ① 한 번만: [보기] → [다른 창] → [속성 관리자] → 프로젝트 우클릭 → [기존 속성 시트 추가] → `${STATIC ARACHNE 설치 경로}\conf\static.vs.props` (기본 `C:\Suresoft\STATIC-5\static-arachne\conf\static.vs.props`) → static.vs 속성 적용 확인. ② 프로젝트 우클릭 → [속성] → [VC++ 디렉터리] → [실행 가능 디렉터리] **맨 앞**에 `<STATIC ARACHNE 설치 경로>\wrapper\<wrapper 이름>` 추가하고 뒤에 세미콜론(`;`)으로 기존 값과 구분.
- **파일 등가물** — `(가이드에 없음)` `(미검증)` — 속성 시트 Import 나 `.vcxproj` 의 ExecutablePath 직접 편집은 원문에 없다. **자동 편집하지 말고 위 GUI 안내로 갈 것.**
- **빌드** — 프로젝트 우클릭 → [다시 빌드] (GUI).
- **검증** — [출력] 창에서 호출된 컴파일러가 지정한 Wrapper 경로인지 + 빌드 성공 확인 → STATIC ARACHNE 에서 모듈 생성 확인.
- **되돌리기** — 이 가이드에는 되돌리기 절이 없다 `(가이드에 없음)`.

### 3.2 STM32CubeIDE

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `*.ioc`, `.cproject`, `.project`. 가이드는 glob 을 명시하지 않는다`(가이드에 없음)`. 적용 환경: Windows 11 / STM32CubeIDE 1.19.0 / arm-none-eabi-gcc 13.3.1.
  - ⚠ Eclipse 계열 공통: `.cproject`/`.project` 만으로는 STM32CubeIDE·CCS·CodeWarrior·AURIX·Vitis 를 구분할 수 없다. 컴파일러 실행 파일이나 설치 경로로 판별하거나 사용자에게 물어라.
- **forge 어휘** — `ide=stm32cubeide`, `compiler=arm_gcc` (원문 `[Vendor] : STM32CubeIDE`, `[Compiler Type] : arm_gcc`)
- **컴파일러 이름** — `arm-none-eabi-gcc.exe` (C++ `arm-none-eabi-g++.exe`/`arm-none-eabi-c++.exe`, 링커 `arm-none-eabi-ld.exe`, 아카이버 `arm-none-eabi-ar.exe`)
- **경로 형태** — `C:/ST/STM32CubeIDE_*/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.*/tools/bin` — 가이드는 같은 문서 안에서 `C:\ST\…` 와 `D:\ST\…` 를 모두 예시로 쓰므로 드라이브는 고정값이 아니다(§6).
- **원본 컴파일러 확인** — 프로젝트 우클릭 → [Properties] → [C/C++ Build] → [Environment] → [PATH] → [Value] 의 **앞부분**.
- **치환 (유형 3)** — 프로젝트 우클릭 → [Properties] → [C/C++ Build] → [Settings] → [Tool Settings] → [MCU/MPU Toolchain] → [Open Toolchain Manager] → [Add Local…] → `[Name]` 예 `STATIC_arm_gcc`, `[Prefix]` `arm-none-eabi-`(끝의 하이픈 포함 — 원문 추출본은 `arm-none-eabi` 로 잘려 보이나 `wrapper_forge.json` 은 `arm-none-eabi-` 로 적는다. §6), `[Location]` = `<STATIC ARACHNE 설치 경로>\wrapper\<wrapper 이름>` → [Finish] → [Apply and Close] → [Select what toolchain to use] 에서 **Fixed** + 추가한 툴체인 선택 → [Apply and Close].
- **파일 등가물** — `(가이드에 없음)` `(미검증)` — `.cproject`/`.mxproject` 직접 편집은 원문에 없다. **자동 편집하지 말고 GUI 안내로 갈 것.**
- **빌드** — 프로젝트 우클릭 → [Clean Project] → [Build Project] (GUI).
- **검증** — STATIC ARACHNE → 워크스페이스 선택 → 모듈 생성 확인.
- **되돌리기** — 가이드에 되돌리기 절 없음`(가이드에 없음)`. 실무상 [Select what toolchain to use] 를 원래 툴체인/Workspace Default 로 되돌린다.

### 3.3 Makefile (GCC/Clang)

- **탐지 단서** — `**/Makefile`(원문이 명시적으로 참조). 추가로 `(가이드 외 출처 — 확인 필요)` `Makefile`, `makefile`, `GNUmakefile`. 빌드 도구 예시: Windows Make 3.81 / Linux Make 4.2.1.
- **forge 어휘** — GCC `ide=gnu`, `compiler=gcc` / Clang `ide=llvm`, `compiler=clang`. Windows 가이드는 GUI `[Vendor] : GNU`, `[Compiler Type] : gcc` 만 예시로 들고, Clang 어휘의 근거는 Linux 가이드의 CLI 문자열 `wrapper-forge add --ide llvm --compiler clang` 이다.
- **컴파일러 이름** — Windows GCC `gcc.exe`/`g++.exe`/`ar.exe`, Clang `clang.exe`/`clang++.exe`/`llvm-ar.exe`. Linux 는 확장자 없음(`gcc`, `g++`, `ar`, `clang`, `clang++`, `llvm-ar`).
- **경로 형태** — GCC: `C:/MinGW/bin`, `C:/msys64/mingw64/bin`, `C:/msys64/mingw32/bin`. Clang: `C:/Program Files/LLVM/bin`, `C:/Program Files (x86)/LLVM/bin`. (가이드는 `C:\MinGW\bin` / `C:\Program Files\LLVM\bin` 만 들었다 — msys64·(x86) 은 설정 쪽 추가분.) Linux 는 설정에 없으므로 가이드값 `/usr/bin` 을 쓴다. Wrapper: `<설치 경로>\wrapper\<wrapper 이름>\<컴파일러 이름>`.
- **원본 컴파일러 확인** — ① Makefile 의 `CC`/`CXX` 확인 → ② 없으면 `make -n` 으로 실제 호출 확인 → ③ `where gcc`(Windows) / `which gcc`(Linux) 로 경로 확인.
- **치환 (유형 5)** — 원본 make 명령에 변수를 덧붙인다 (Windows 줄바꿈 `^`, Linux `\`):
  `make all ^ CC=<wrapper>\gcc.exe ^ CXX=<wrapper>\g++.exe ^ AR=<wrapper>\ar.exe` (Clang 은 `clang.exe`/`clang++.exe`/`llvm-ar.exe`). 되돌리기는 덧붙인 옵션 제거 후 원본 명령으로 빌드.
- **파일 등가물** — Makefile 에 컴파일러가 **하드코딩된 경우에만**: 원본 백업 후 `CC`/`CXX`/`AR` 값을 Wrapper 경로로 변경. **`(검증됨 — 자동 치환 대상)`** — 이 파일 전체에서 유일하게 자동 편집이 허용된 항목. 복구는 백업 Makefile 복원 후 재빌드.
- **빌드** — clean 후 재빌드 (`make clean` → 위 치환 명령).
- **검증** — 빌드 출력의 컴파일러 명령이 Wrapper 경로인지 확인. Windows: ARACHNE 에서 모듈 캡처 확인. Linux: 워크스페이스에서 `ls -a` 로 `.capture` 폴더와 모듈 디렉터리 확인.
- **OS 차이** — Wrapper 생성이 Windows 는 ARACHNE GUI([Settings] → [C/C++] → [+ Add Wrapper]), Linux 는 `static-arachne/bin/wrapper-forge add --ide … --compiler … --name … --path … --workspace …` CLI. Linux 는 빌드 쉘마다 설치 경로의 `setenv.sh` 를 `source` 해야 한다.

### 3.4 CMake (GCC/Clang)

- **탐지 단서** — `**/CMakeLists.txt`, `**/CMakeCache.txt`(원문이 명시적으로 참조). 추가로 `(가이드 외 출처 — 확인 필요)` `compile_commands.json`. 빌드 도구 예시: Windows CMake 3.28.1 / Linux 3.20.0.
- **forge 어휘** — GCC `ide=gnu`, `compiler=gcc` / Clang `ide=llvm`, `compiler=clang`. Windows 가이드 GUI 예시는 `[Vendor] : LLVM`, `[Compiler Type] : clang`.
- **컴파일러 이름** — Makefile 항목과 동일 (`gcc.exe`/`g++.exe`/`ar.exe`, `clang.exe`/`clang++.exe`/`llvm-ar.exe`).
- **경로 형태** — Makefile 항목과 동일한 glob (`C:/MinGW/bin`, `C:/msys64/mingw64/bin`, `C:/msys64/mingw32/bin`, `C:/Program Files/LLVM/bin`, `C:/Program Files (x86)/LLVM/bin`; Linux `/usr/bin`). CMake 옵션에는 Windows 에서도 `/` 구분자로 적는다.
- **원본 컴파일러 확인** — Make/Ninja generator: `CMakeCache.txt` 의 `CMAKE_C_COMPILER:` / `CMAKE_CXX_COMPILER:` (Linux 예 `grep -E "CMAKE_C_COMPILER:|CMAKE_CXX_COMPILER:" CMakeCache.txt`). VS generator(Windows 전용): MSBuild 출력/로그 세부 정보를 **상세(자세히)** 로 올린 뒤 빌드하고 출력에서 `clang-cl.exe` 검색.
- **치환 (유형 5; VS generator 는 유형 2)** — Make/Ninja: `cmake -S . -B build -G "<제너레이터>" -DCMAKE_C_COMPILER=<wrapper>/gcc[.exe] -DCMAKE_CXX_COMPILER=<wrapper>/g++[.exe] -DCMAKE_AR=<wrapper>/ar[.exe]` (Clang 은 `clang`/`clang++`/`llvm-ar`; 제너레이터 예시 Windows `"MinGW Makefiles"`, Linux `"Unix Makefiles"`). VS generator(Windows 전용): 먼저 static.vs.props 를 한 번 적용(원문은 `${STATIC SE 설치 경로}\conf\static.vs.props`, 기본 `C:\Suresoft\STATIC-5\static-standalone\conf\static.vs.props` — VS 가이드와 불일치, §6) 후 CMake 가 생성한 `.sln` 을 열고 프로젝트 [속성] → [VC++ 디렉터리] → [실행 가능 디렉터리] 에 Wrapper 디렉터리 추가 + `;` 구분.
- **파일 등가물** — `CMakeLists.txt` 에 `set(CMAKE_C_COMPILER <wrapper>/clang[.exe])`, `set(CMAKE_CXX_COMPILER <wrapper>/clang++[.exe])`, `set(CMAKE_AR <wrapper>/llvm-ar[.exe])` 추가. `(미검증)` — **자동 편집하지 말고 커맨드 옵션 치환 또는 GUI 안내로 갈 것.** 되돌리기는 추가한 `set(...)` 줄 제거. VS generator 쪽 파일 등가물은 `(가이드에 없음)` `(미검증)` — **GUI 안내로.**
- **빌드** — Make/Ninja: cmake 명령에 `--fresh` 를 추가해 컴파일러 치환을 반영한 뒤 재빌드. VS generator: 프로젝트 우클릭 → [다시 빌드].
- **검증** — 빌드 출력의 컴파일러가 Wrapper 인지 확인. Windows: ARACHNE 에서 모듈 생성 확인(VS generator 는 [출력] 창에서 Wrapper 사용 + 빌드 성공 확인). Linux: `ls -a` 로 `.capture` 폴더와 모듈 디렉터리 확인.
- **OS 차이** — Makefile 항목과 동일(줄바꿈 문자, 제너레이터 이름, GUI vs `wrapper-forge` CLI, `setenv.sh`). VS generator 절은 Windows 가이드에만 존재.

### 3.5 Code Composer Studio (Eclipse / Theia 공통)

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `.ccsproject`, `.cproject`, `*.projectspec`. 가이드는 프로젝트 파일 이름을 언급하지 않으며`(가이드에 없음)` 유일한 단서는 설치 경로 형태다.
  - ⚠ Eclipse 계열 공통: `.cproject`/`.project` 만으로는 CCS·STM32CubeIDE·CodeWarrior·AURIX·Vitis 를 구분할 수 없다. 컴파일러나 설치 경로로 판별하거나 사용자에게 물어라.
- **forge 어휘** — `ide=ccs`, `compiler=cl2000` (원문 `[Vendor] : Code Composer Studio` / `[Compiler Type] : cl2000`). `c6000` 이 아닌 이유: 두 가이드 모두 툴체인이 `ti-cgt-c2000_*` 이고 설정 항목이 `C2000 Compiler`/`C2000 Linker` 로 C2000 타깃임이 명시돼 있다. `cl6x` 계열이면 `compiler=c6000`.
- **컴파일러 이름** — 가이드는 `cl2000.exe` 만 다루지만 설정의 시드는 `cl2000.exe`, `cl430.exe`, `cl6x.exe`, `cl7x.exe`, `armcl.exe`, `tiarmclang.exe` (아카이버 `ar2000.exe`/`ar430.exe`/`ar6x.exe`/`armar.exe`). 여러 개인 것은 노이즈가 아니라 실제 타깃별 툴체인이다.
- **경로 형태** — `C:/ti/ccs*/ccs/tools/compiler/ti-cgt-*/bin` (가이드 예시는 `C:\ti\ccs1281\ccs\tools\compiler\ti-cgt-c2000_22.6.1.LTS\bin` 처럼 `ti-cgt-c2000_*` 한정이나, 설정은 모든 `ti-cgt-*` 로 일반화한다.)
- **원본 컴파일러 확인** — Eclipse: 프로젝트 우클릭 → [Rebuild Project] → [Console] 의 컴파일러·링커 경로. Theia: 프로젝트 우클릭 → [Properties…] → [General] → [Variables] → [Show both user-defined and system variables] 체크 → `[CG_TOOL_CL]` 값.
- **치환 (유형 1)** — Wrapper 경로는 `<STATIC 설치 루트>\static-arachne\wrapper\<wrapper 이름>\cl2000.exe`.
  Eclipse: 프로젝트 우클릭 → [Properties] → [Build] → [C2000 Compiler] → [Command] 를 Wrapper 경로로 → [Build] → [C2000 Linker] → [Command] 도 같은 경로 → [Apply and Close].
  Theia: [Properties…] → [Tools] → [C2000 Compiler] → [Command] 입력 → [C2000 Linker] 동일(가이드 주석: 프로젝트에 따라 동일하지 않을 수 있음) → [Save and Close].
- **파일 등가물** — `(가이드에 없음)` `(미검증)`. **자동 편집하지 말고 GUI 안내로 가라.**
- **빌드** — GUI. 프로젝트 우클릭 → Eclipse [Rebuild Project] / Theia [Rebuild Projects].
- **검증** — [Console] 명령어의 컴파일러가 지정한 Wrapper 인지 + [Console] 에 `Build Finished` 출력 확인(Eclipse 가이드 명시) → ARACHNE 워크스페이스에서 모듈 생성 확인.
- **되돌리기** — [Command] 를 `"${CG_TOOL_CL}"` 로 복원. (`wrapper_forge.json` 은 링커 복원값을 `${CG_TOOL_LNK}` 로 적으나 가이드 원문에는 없다. §6)

### 3.6 CodeWarrior — ColdFire (mwccmcf)

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `.project`, `*.mcp`. 가이드는 glob 을 언급하지 않고`(가이드에 없음)` IDE 이름 `CodeWarrior for MCU (v11.1)` 과 설치 경로 형태만 준다.
  - ⚠ Eclipse 계열 공통: `.cproject`/`.project` 만으로 환경을 확정하지 말 것.
- **forge 어휘** — `ide=codewarrior`, `compiler=mwccmcf` (원문 `[Vendor] : Code Warrior` — 공백 표기만 다름, `[Compiler Type] : mwccmcf`)
- **컴파일러 이름** — `mwccmcf.exe` (링커·아카이버 시드 모두 `mwldmcf.exe`)
- **경로 형태** — `C:/Freescale/CW MCU v*/MCU/ColdFire_Tools/Command_Line_Tools`
- **원본 컴파일러 확인** — 프로젝트 우클릭 → [Clean Project] → [Build Project] → [Console] 의 컴파일러 `.../Command_Line_Tools/mwccmcf`, 링커 `.../Command_Line_Tools/mwldmcf`.
- **치환 (유형 1)** — 프로젝트 우클릭 → [Properties] → [C/C++ Build] → [Settings] → [Tool Settings] → [ColdFire Compiler] - [Command] 를 `<STATIC 설치 루트>\static-arachne\wrapper\<wrapper 이름>\mwccmcf.exe` 로, [ColdFire Linker] - [Command] 를 같은 wrapper 의 `mwldmcf.exe` 로 변경 → [Apply] → [OK].
- **파일 등가물** — `(가이드에 없음)` `(미검증)`. **자동 편집하지 말고 GUI 안내로 가라.**
- **빌드** — GUI. 프로젝트 우클릭 → [Clean Project](가이드: 정리 필요) → [Build Project].
- **검증** — ARACHNE → 워크스페이스 선택 → 모듈 생성 확인.
- **되돌리기** — [ColdFire Compiler] → `"${CF_ToolsDir}/mwccmcf"`, [ColdFire Linker] → `"${CF_ToolsDir}/mwldmcf"`. (원문은 두 항목 모두 `mwldmcf` 로 적는 오타가 있다. §6)

### 3.7 CodeWarrior — Kinetis (arm-none-eabi-gcc)

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `.project`, `*.mcp`. 가이드는 glob 없음`(가이드에 없음)`; IDE 이름 `CodeWarrior for MCU (v11.1)` 과 경로 형태만.
  - ⚠ `arm-none-eabi-gcc` 는 ambiguous — STM32CubeIDE·Vitis 와 겹친다. `C:\Freescale\CW MCU v*` 설치 경로가 결정적 단서다.
- **forge 어휘** — `ide=codewarrior`, `compiler=gcc`. **실행 파일이 `arm-none-eabi-gcc` 라고 `arm_gcc` 를 쓰면 안 된다** — `codewarrior` 아래에 `arm_gcc` 는 존재하지 않고 원문도 `[Compiler Type] : gcc` 라고 명시한다.
- **컴파일러 이름** — `arm-none-eabi-gcc.exe` (C++ `arm-none-eabi-g++.exe`, 링커 `arm-none-eabi-ld.exe`, 아카이버 `arm-none-eabi-ar.exe`)
- **경로 형태** — `C:/Freescale/CW MCU v*/Cross_Tools/arm-none-eabi-gcc-*/bin`
- **원본 컴파일러 확인** — 프로젝트 우클릭 → [Clean Project] → [Build Project] → [Console] 의 경로 (예 `.../arm-none-eabi-gcc-4_7_3/bin/arm-none-eabi-gcc`).
- **치환 (유형 2)** — 같은 IDE 의 다른 변종과 달리 [Command] 가 아니라 **빌드 변수**를 바꾼다. 프로젝트 우클릭 → [Properties] → [C/C++ Build] → [Build Variables] → [Show system variables] 체크 → `[ARMSourceryDir]` 더블 클릭 → [Value] 를 Wrapper **디렉터리**(`<STATIC 설치 루트>\static-arachne\wrapper\<wrapper 이름>`, 실행 파일명 없이)로 설정 → [Apply] → [OK].
- **파일 등가물** — `(가이드에 없음)` `(미검증)`. **자동 편집하지 말고 GUI 안내로 가라.**
- **빌드** — GUI. 프로젝트 우클릭 → [Clean Project](가이드: 정리 필요) → [Build Project].
- **검증** — ARACHNE → 워크스페이스 선택 → 모듈 생성 확인.
- **되돌리기** — [Build Variables] 에서 `[ARMSourceryDir]` 선택 → [Delete]. **가이드 경고:** [Show system variables] 를 체크하지 않은 상태에서 이미 `[ARMSourceryDir]` 이 보였다면 원래 값을 반드시 기억해 두고 그 값으로 복원할 것.

### 3.8 CodeWarrior — Qorivva (mwcceppc)

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `.project`, `*.mcp`. 가이드는 glob 없음`(가이드에 없음)`; IDE 이름 `CodeWarrior for MCU (v11.1)` 과 경로 형태만.
- **forge 어휘** — `ide=codewarrior`, `compiler=mwcceppc` (원문 `[Vendor] : Code Warrior`, `[Compiler Type] : mwcceppc`)
- **컴파일러 이름** — `mwcceppc.exe` (링커·아카이버 시드 모두 `mwldeppc.exe`)
- **경로 형태** — `C:/Freescale/CW MCU v*/MCU/PA_Tools/Command_Line_Tools`
- **원본 컴파일러 확인** — 프로젝트 우클릭 → [Clean Project] → [Build Project] → [Console] 의 컴파일러 `.../Command_Line_Tools/mwcceppc`, 링커 `.../Command_Line_Tools/mwldeppc`.
- **치환 (유형 1)** — 프로젝트 우클릭 → [Properties] → [C/C++ Build] → [Settings] → [Tool Settings] → **[PowerPC Compiler]** - [Command] 를 `…\wrapper\<wrapper 이름>\mwcceppc.exe` 로, **[PowerPC Linker]** - [Command] 를 `…\wrapper\<wrapper 이름>\mwldeppc.exe` 로 변경 → [Apply] → [OK]. (`wrapper_forge.json` 은 라벨을 `Qorivva Compiler`/`Qorivva Linker` 로 적으나 가이드 원문 문자열은 `PowerPC …` 다. §6)
- **파일 등가물** — `(가이드에 없음)` `(미검증)`. **자동 편집하지 말고 GUI 안내로 가라.**
- **빌드** — GUI. 프로젝트 우클릭 → [Clean Project](가이드: 정리 필요) → [Build Project].
- **검증** — Wrapper 치환 경로 + 빌드 성공 확인 → ARACHNE → 워크스페이스 → 모듈 생성 확인. **가이드 주의:** 이후 분석 단계에서 비표준 문법 때문에 `__ppc_eabi_init.c` 가 에러를 내므로 이 파일을 [Exclude from analysis scope] 로 제외해야 한다.
- **되돌리기** — `"${PAToolsDir}/mwcceppc"`, `"${PAToolsDir}/mwldeppc"` 로 복원.

### 3.9 AURIX Development Studio — TASKING CCTC

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `.cproject`, `*.cbp`. 가이드는 glob 없음`(가이드에 없음)`; 단서는 빌드 구성 이름 `TriCore Debug (TASKING)` 과 경로 형태다.
  - ⚠ Eclipse 계열 공통: `.cproject`/`.project` 만으로 환경을 확정하지 말 것.
- **forge 어휘** — `ide=aurix`, `compiler=cctc` (원문 `[Vendor] : AURIX`, `[Compiler Type] : cctc`)
- **컴파일러 이름** — `cctc.exe`. 설정의 링커 시드는 `ltc.exe`, 아카이버 시드는 `artc.exe` 지만, **IDE 의 [TASKING Linker] - [Command] 에는 가이드대로 `cctc.exe` 를 넣는다**(TASKING 은 cctc 가 링크를 몰아 실행). §6
- **경로 형태** — `C:/Infineon/AURIX-Studio-*/tools/Compilers/Tasking_*/ctc/bin`
- **원본 컴파일러 확인** — 프로젝트 우클릭 → [Properties] → [C/C++ Build] → [Environment] → [Configuration] 을 `Tricore Debug (TASKING)` 로 → `PATH` 값 중 `ctc` 가 포함된 경로.
- **치환 (유형 1)** — ① 프로젝트 우클릭 → [Build Configurations] → [Set Active] → [TriCore Debug (TASKING)] ② [Properties] → [C/C++ Build] → [Settings] 의 [Configuration] 이 [TriCore Debug (TASKING)] 인지 확인 ③ [Tool Settings] → [TASKING C/C++ Compiler] → [Command] 를 `…\wrapper\<wrapper 이름>\cctc.exe` 로 ④ [TASKING Linker] → [Command] 도 **같은 `cctc.exe`** 경로로 ⑤ [Apply and Close].
- **파일 등가물** — `(가이드에 없음)` `(미검증)`. **자동 편집하지 말고 GUI 안내로 가라.**
- **빌드** — GUI. 프로젝트 우클릭 → [Clean Project] → [Build Project].
- **검증** — Console 명령어의 컴파일러가 Wrapper 인지 + Console 에 `Build Finished` 확인 → ARACHNE Workspace 에서 모듈 확인.
- **되돌리기** — [Properties] → [C/C++ Build] → [Settings] → [Restore Defaults] → [Apply and Close].

### 3.10 AURIX Development Studio — TriCore GCC

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `.cproject`, `*.cbp`. 가이드는 glob 없음`(가이드에 없음)`; 단서는 빌드 구성 이름 `TriCore Debug (GCC)` 와 경로 형태다.
- **forge 어휘** — `ide=aurix`, `compiler=gcc` (원문 그대로)
- **컴파일러 이름** — `tricore-*-gcc.exe` (가이드 예시 `tricore-elf-gcc.exe`; C++ `tricore-*-g++.exe`/`tricore-*-c++.exe`, 링커 `tricore-*-ld.exe`, 아카이버 `tricore-*-ar.exe`)
- **경로 형태** — `C:/Infineon/AURIX-Studio-*/tools/Compilers/tricore-gcc*/bin`
- **원본 컴파일러 확인** — 프로젝트 우클릭 → [Properties] → [C/C++ Build] → [Environment] → [Configuration] 을 Tricore 컴파일러로 → `PATH` 값 중 `tricore-gcc` 포함 경로.
- **Wrapper 생성 전 필수 선행 작업(이 환경 고유)** — 원본 컴파일러 `bin` 의 **상위 폴더**에서 `bin` 의 복사본을 만든다(예 `...\tricore-gcc11\bin_original`). Wrapper 의 `[Original Compiler Path]`(CLI `-p`) 에는 **`bin` 이 아니라 이 복사본 경로**를 넣어야 한다(가이드가 굵게 경고).
- **치환 (유형 6 — 파괴적)** — GUI 가 아니라 **파일 복사**다. ① Wrapper 폴더의 모든 파일을 원본 컴파일러 `bin` 에 덮어쓴다 ② 프로젝트 우클릭 → [Build Configurations] → [Set Active] → [TriCore Debug (GCC)].
- **파일 등가물** — 별도 등가물 없음 — 위 파일 복사 자체가 가이드 원문 절차다. 다만 IDE 설치 디렉터리를 훼손하며 복사본 없이는 복구가 불가능하므로 **자동 편집하지 말고 사용자에게 수동/GUI 안내로 가라.** `(미검증)`
- **빌드** — GUI. 프로젝트 우클릭 → [Clean Project] → [Build Project].
- **검증** — Console 에 `Build Finished` 정상 출력 확인 → ARACHNE Workspace 에서 모듈 확인.
- **되돌리기** — 치환된 `bin` 폴더를 삭제하고 `bin_original` 을 `bin` 으로 이름 변경.

### 3.11 MPLAB X IDE

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `nbproject/`, `*.X`. 가이드는 프로젝트 파일 이름/glob 을 명시하지 않는다`(가이드에 없음)`. 원문에서 간접 확인되는 것은 Makefile 기반 프로젝트라는 점뿐([Properties] → [Conf] → [Building] → `Use "clean" target from the Makefile` 옵션 존재).
- **forge 어휘** — `ide=mplab`, `compiler=xc8` (원문 Vendor `MPLAB X IDE`, Compiler Type `xc8`). 원문은 XC8 타깃 한정 — 타깃에 따라 `xc8_avr`, `xc16`, `xc32`, `arm_gcc`, `avr8`, `avr32` 중 선택. ⚠ 역매핑 표는 `xc8-cc` 를 `microchips` 로 떨어뜨리므로 MPLAB X 임을 알면 `--ide mplab` 을 명시할 것.
- **컴파일러 이름** — `xc8-cc.exe`, `xc8.exe` (아카이버 `xc8-ar.exe`; 링커도 `xc8-cc.exe`)
- **경로 형태** — `C:/Program Files/Microchip/xc8/v*/bin`, `C:/Program Files (x86)/Microchip/xc8/v*/bin` (가이드 예시 `v3.10`; (x86) 갈래는 설정 쪽 추가분)
- **원본 컴파일러 확인** — 프로젝트 우클릭 → [Clean and Build] → [Output] 창의 원본 컴파일러 경로.
- **치환 (유형 4 — IDE 전역 설정)** — ① [Tools] → [Options] ② [Embedded] → [Build Tools] → 목록에서 `XC8` 선택 ③ `C Compiler` 를 `<STATIC 설치경로>\static-arachne\wrapper\<wrapper 이름>\xc8-cc.exe` 로 ④ `Assembler` 도 같은 `xc8-cc.exe` 경로로 ⑤ 프로젝트 우클릭 → [Properties] → [Conf] → [Building] → `Use "clean" target from the Makefile` 토글(꺼져 있으면 켜고, 켜져 있으면 끈다). **프로젝트가 아니라 IDE 전역 설정을 바꾸는 유일한 환경** — 다른 프로젝트에도 영향이 간다.
- **파일 등가물** — `(가이드에 없음)` `(미검증)`. Build Tools 는 IDE 전역 설정이고 대응 파일이 원문에 없다. **자동 편집하지 말고 GUI 안내로 갈 것.**
- **빌드** — GUI. 프로젝트 우클릭 → [Clean and Build]. **Clean 을 반드시 거쳐야 캡처가 정상 진행**된다(원문 명시).
- **검증** — [Output] 에서 컴파일러가 wrapper 로 호출됐는지 확인 → ARACHNE 에서 해당 워크스페이스의 모듈 생성 확인.
- **되돌리기** — [Tools] → [Options] → [Embedded] → [Build Tools] → [Scan for Build Tools] 클릭 후 원본 컴파일러 확인.

### 3.12 Microchip Studio

- **탐지 단서** — `(가이드 외 출처 — 확인 필요)` `*.atsln`, `*.cproj`. 원문에 프로젝트 파일 이름/glob 언급 없음`(가이드에 없음)`. GUI 경로상 Atmel/Microchip Studio 프로젝트를 전제([Properties] → [Advanced] → [Flavour Configuration])하지만 파일명은 확정 불가.
- **forge 어휘** — `ide=microchips`, `compiler=xc8` (원문 Vendor `Microchip Studio`, Compiler Type `xc8`). 원문은 XC8 타깃 한정 — 타깃에 따라 `xc8_avr`, `xc16`, `xc32`, `arm_gcc`, `avr8`, `avr32` 중 선택.
- **컴파일러 이름** — `xc8-cc.exe`, `xc8.exe` (아카이버 `xc8-ar.exe`)
- **경로 형태** — `C:/Program Files/Microchip/xc8/v*/bin`, `C:/Program Files (x86)/Microchip/xc8/v*/bin` (가이드 예시 `v2.36`, 컴파일러 버전 표기 `Microchip MPLAB XC8 C Compiler V2.36`)
- **원본 컴파일러 확인** — 프로젝트 우클릭 → [Properties] → [Advanced] → [Flavour Configuration] → [Package Configuration] → 프로젝트가 쓰는 [Toolchain], [Flavour] 선택 후 [Path] 값 확인.
- **치환 (유형 3 — Flavour 추가)** — ① 프로젝트 우클릭 → [Properties] → [Advanced] → [Flavour Configuration] → [Package Configuration] ② 사용 중인 Toolchain 선택 → [Add Flavour] ③ `Package Name` 에 STATIC 용 이름(원문 예시 `XC8_2.36_STATIC`), `Package Base Path` 에 `<STATIC 설치경로>\static-arachne\wrapper\<wrapper 이름>` ④ [Toolchain Flavour] 를 방금 추가한 항목으로 변경.
- **파일 등가물** — `(가이드에 없음)` `(미검증)`. Flavour 설정 저장 위치가 원문에 없다. **자동 편집하지 말고 GUI 안내로 갈 것.**
- **빌드** — GUI. 프로젝트 우클릭 → [Rebuild Project].
- **검증** — [Output] 명령어의 컴파일러가 지정한 wrapper 인지 + `Build succeeded` 출력 확인 → ARACHNE 에서 워크스페이스 모듈 생성 확인.
- **되돌리기** — `(가이드에 없음)` — 이 가이드에는 되돌리기 절 자체가 없다. 실무상 [Toolchain Flavour] 를 원래 값으로 되돌리는 것이 대응되나 원문 근거는 없다.

### 3.13 Vitis Unified

- **탐지 단서** — 프로젝트에 `CMakeLists.txt` 가 있다(원문이 치환 대상으로 직접 지목). 그 외 프로젝트 파일 glob 은 `(가이드에 없음)` — `(가이드 외 출처 — 확인 필요)` `.cproject`, `*.prj`, `vitis-comp.json`.
  - ⚠ Eclipse 계열 공통: `.cproject`/`.project` 만으로는 다른 Eclipse 파생 IDE 와 구분되지 않는다. `vitis-comp.json` 이나 `C:\Xilinx\…` 설치 경로로 판별하거나 사용자에게 물어라.
- **forge 어휘** — `ide=xilinx`, `compiler=arm64_gcc` (원문 Vendor `Xilinx Vitis Unified`, Compiler Type `arm64_gcc`). 원문은 aarch64 타깃 한정 — 32비트 Cortex-A/R 은 `arm_gcc`, MicroBlaze 는 `mb_gcc`.
- **컴파일러 이름** — `aarch64-none-elf-gcc.exe`, `arm-none-eabi-gcc.exe`, `mb-gcc.exe` (동반 도구는 각 접두사 + `-g++.exe` / `-ld.exe` / `-ar.exe`). 여러 개인 것은 타깃별 실제 툴체인이다.
- **경로 형태** — `C:/Xilinx/*/gnu/aarch64/nt/aarch64-none/bin`, `C:/Xilinx/*/Vitis/*/gnu/aarch64/nt/aarch64-none/bin` — 설정은 원문 내부 불일치(`Vitis` 세그먼트 유무, §6)를 두 glob 으로 모두 커버한다.
- **원본 컴파일러 확인** — [FLOW] → [Component] 를 원본 프로젝트로 설정 → [Build] 실행 → [Output] 의 컴파일러/링커 경로.
- **치환 (유형 5 — 파일 편집)** — 프로젝트 [Settings] → `CMakeLists.txt` 열기 → 아래를 추가하고 저장:
  `set(CMAKE_C_COMPILER <STATIC 설치경로>\\static-arachne\\wrapper\\<wrapper 이름>\\aarch64-none-elf-gcc.exe)` 와 같은 형태로 `CMAKE_CXX_COMPILER`(`-g++.exe`), `CMAKE_LINKER`(`-ld.exe`), `CMAKE_AR`(`-ar.exe`). (원문은 Windows 경로를 `\\` 로 이스케이프해 적었다.) **CMake 계열이면서 커맨드라인 옵션 대안이 제시되지 않은 유일한 케이스.**
- **파일 등가물** — 해당 없음 — **치환 방법 자체가 파일 편집**이며 가이드 원문의 정규 절차다(GUI 대안은 `(가이드에 없음)`). 다만 사용자 소스인 `CMakeLists.txt` 를 고치는 것이므로 무단 자동 편집하지 말고 추가할 줄을 먼저 제시하고 확인을 받을 것.
- **빌드** — GUI. [FLOW] → [Component] 를 원본 프로젝트로 → [Build].
- **검증** — [Output] 명령어의 컴파일러가 지정한 wrapper 인지 + `Build Finished successfully` 출력 확인 → ARACHNE 에서 워크스페이스 모듈 생성 확인.
- **되돌리기** — 프로젝트 [Settings] → `CMakeLists.txt` → 추가했던 wrapper 설정 코드를 주석 처리 → 저장.

---

## 4. 치환 유형

표에 없는 환경을 만났을 때는 아래 6유형 중 어디에 해당하는지부터 판별한다.

> **핵심 — IDE 이름만으로 치환 유형을 추론하면 안 된다.** 동일한 CodeWarrior for MCU v11.1 안에서 ColdFire/Qorivva 는 컴파일러 [Command] 문자열을 바꾸고(유형 1), Kinetis 는 빌드 변수 `ARMSourceryDir` 을 바꾼다(유형 2). 판별 단위는 IDE 가 아니라 **툴체인**이다.

**유형 1 — Tool Settings 의 `[Command]` 문자열을 wrapper 실행 파일 경로로 교체** (Eclipse CDT 계열)
CCS Eclipse/Theia, AURIX CCTC, CodeWarrior ColdFire, CodeWarrior Qorivva. 컴파일러와 링커 두 항목을 모두 바꾼다(AURIX CCTC 는 링커에도 `cctc.exe`). 저장 위치는 Eclipse `.cproject` 로 추정되나 **어느 가이드도 파일을 언급하지 않는다** — 되돌리기 값이 IDE 변수(`${CG_TOOL_CL}`, `${CF_ToolsDir}/…`, `${PAToolsDir}/…`)인 것으로 보아 프로젝트 파일 안에 문자열로 들어 있을 가능성이 높다. `(미검증)` — GUI 안내로.

**유형 2 — 경로/디렉터리 변수 값만 wrapper 디렉터리로 교체** (실행 파일 이름은 건드리지 않음)
CodeWarrior Kinetis(`ARMSourceryDir`), Visual Studio([VC++ 디렉터리] → [실행 가능 디렉터리] 맨 앞 + `;`), CMake-Windows 의 VS generator(동일). VS 계열은 `.vcxproj`/props 로 표현 가능해 보이지만 원문 근거가 없다 `(미검증)`. **VS 계열만 추가로 `static.vs.props` 속성 시트를 한 번 붙여야 한다** — wrapper 외 부속 설정이 필요한 유일한 케이스.

**유형 3 — wrapper 를 새 툴체인/flavour 로 IDE 에 등록한 뒤 그것을 선택**
STM32CubeIDE(Toolchain Manager → Add Local… → Fixed), Microchip Studio(Package Configuration → Add Flavour). 등록 내용이 IDE 내부 설정 저장소로 들어가므로 파일 등가물을 추정할 근거가 원문에 전혀 없다 `(가이드에 없음)` `(미검증)`.

**유형 4 — IDE 전역 빌드 도구 설정 자체를 교체**
MPLAB X IDE([Tools] → [Options] → [Embedded] → [Build Tools] 의 XC8 `C Compiler`/`Assembler`). 프로젝트가 아니라 **IDE 전역**이라는 점이 위험 요소이며, 롤백도 `Scan for Build Tools` 라는 전역 재스캔이다.

**유형 5 — 빌드 스크립트/커맨드라인 치환** (자동화하기 가장 쉬운 유형)
Makefile(`make all CC=… CXX=… AR=…`, 하드코딩된 경우에만 파일 직접 수정 + 원본 백업 — **이 파일 편집만 `(검증됨)`**), CMake(`-DCMAKE_C_COMPILER=… -DCMAKE_CXX_COMPILER=… -DCMAKE_AR=…` 또는 `CMakeLists.txt` 의 `set(...)`; 반영에 `--fresh` 필요), Vitis Unified(`CMakeLists.txt` 의 `set(...)` 만, 커맨드라인 대안 없음). `CMakeLists.txt`/`Makefile` 은 사용자 소스이므로 백업·주석 처리 롤백 경로가 원문에 함께 제시돼 있다.

**유형 6 — 원본 `bin` 폴더를 wrapper 파일로 덮어쓴다 (파괴적)**
AURIX TriCore GCC 단독. 순서가 중요하다: ① 원본 `…/tricore-gcc*/bin` 을 `bin_original` 로 **복사** ② wrapper 생성의 `[Original Compiler Path]`(`-p`) 에 **`bin` 이 아니라 `bin_original`** 지정 ③ wrapper 폴더 전체를 원본 `bin` 에 덮어쓰기. 롤백은 치환된 `bin` 삭제 후 `bin_original` → `bin` 리네임. 파일 조작이라 자동화는 가능하지만 **IDE 설치 디렉터리를 훼손**하므로 반드시 별도 확인을 받을 것.

**유형과 무관하게 공통인 것**
- **빌드 전 Clean 이 사실상 필수.** MPLAB X 는 "Clean 을 해야 정상적으로 캡처가 진행"이라 명시하고, CCS/AURIX/CodeWarrior 는 `Clean Project → Build Project`, VS 계열은 [다시 빌드], CMake 는 `--fresh` 를 요구한다.
- **검증은 항상 2단계.** ① 빌드 로그에서 실제 호출된 컴파일러가 wrapper 경로인지 확인(+ `Build Finished` / `Build succeeded` / `Build Finished successfully` 성공 문자열) ② ARACHNE 워크스페이스에 모듈 생성 확인. Linux 는 ②가 워크스페이스 디렉터리에서 `ls -a` 로 `.capture` 폴더와 모듈 디렉터리 확인.
- **원본 컴파일러 확인 방법도 4가지로 갈린다.** A: 빌드 후 로그(Console/Output)에서 경로 읽기(가장 흔함, VS 계열은 로그 상세도를 먼저 올려야 함) / B: [C/C++ Build] → [Environment] → `PATH` 에서 읽기(AURIX ×2, STM32CubeIDE) / C: IDE 변수·툴체인 관리 화면에서 읽기(CCS Theia `CG_TOOL_CL`, Microchip Studio Flavour `Path`) / D: 빌드 산출물·스크립트 직접 읽기(`CMakeCache.txt`, `Makefile` + `make -n` + `where`/`which`) — **D 만 IDE 없이 완전 자동화 가능**하다.

---

## 5. 가이드 자체의 오류·불일치

원문(Suresoft 배포 PDF)에서 발견된 문제들. 에이전트는 아래를 알고 우회하고, 사람은 원본 문서를 고쳐야 한다.

**설치 경로·파일명**
- **`static-arachne` vs `static-standalone`.** Visual Studio 가이드는 속성 시트를 `${STATIC ARACHNE 설치 경로}\conf\…`(기본 `C:\Suresoft\STATIC-5\static-arachne\conf\…`)에서 찾으라 하고, CMake-Windows 가이드는 같은 파일을 `${STATIC SE 설치 경로}\conf\…`(기본 `C:\Suresoft\STATIC-5\static-standalone\conf\static.vs.props`)에서 찾으라 한다. CMake-Windows 는 wrapper 디렉터리도 `static-standalone\wrapper\static-clang` 으로 적는데 **같은 문서의 CMake 치환 예시는 `static-arachne\wrapper\…`** 다. → 플러그인 설정(`wrapper_forge.json`)은 `static-arachne` 를 정본으로 쓴다.
- **속성 시트 파일명 불일치.** VS 가이드 본문은 `static.vs.props` 인데 기본 경로 예시는 `static.vsprops` 로 적혀 있다. → 설정의 `vs_props` 는 `static.vs.props`.
- **STATIC 설치 드라이브가 한 문서 안에서 섞인다.** 적용 환경/Wrapper 절은 `C:\Suresoft\STATIC-5\…`, 치환 절 예시는 `D:\Suresoft\STATIC-5\…` 인 문서가 여럿(MPLAB X, Vitis Unified, CCS Theia, STM32CubeIDE). MPLAB X 만 "기본 설치 경로에 따라 경로는 바뀔 수 있음"이라 단서를 단다. → **경로는 전부 형태로만 취급할 것.**
- **STM32CubeIDE 컴파일러 경로 드라이브 불일치.** 적용 환경은 `C:\ST\…`, Wrapper 절의 Original Compiler Path 예시는 `D:\ST\…`.
- **Vitis Unified 내부 경로 불일치.** 적용 환경은 `C:\Xilinx\2025.1\gnu\aarch64\nt\aarch64-none\bin`, 원본 컴파일러 확인 절은 `C:\Xilinx\2025.1\Vitis\gnu\aarch64\nt\aarch64-none\bin\…` — `Vitis` 세그먼트 유무가 다르다. 실제 설치본에서 확인할 것.

**값·오타**
- **STM32CubeIDE `[Prefix]` 의 끝 하이픈.** 추출본에는 `arm-none-eabi` 로 보이지만 하이픈이 잘렸을 가능성이 높다(`wrapper_forge.json` 은 `arm-none-eabi-`). GUI 에서 실제 표기를 확인할 것.
- **CodeWarrior ColdFire 되돌리기 오타.** `[ColdFire Compiler] - [Command]` 를 `${CF_ToolsDir}/mwldmcf` 로 바꾸라고 두 번 적혀 있다. 두 번째는 `[ColdFire Linker]` 여야 맞다(치환 절과 대조 시 명백).
- **CCS Theia 되돌리기 절이 Eclipse 판 문구 그대로.** 치환은 `Properties → Tools → C2000 Compiler` 로 안내하면서 되돌리기는 `Properties → Build → C2000 Compiler` 라고 한다.
- **CMake-Windows 되돌리기 오타.** `llvm-ar.exe.exe`.
- **Makefile-Linux 는 "STATIC 서버 설정"(액세스 키 복사 + 서버 연결 설정) 절이 두 번 중복** 등장한다.

**어휘·라벨**
- **Add Wrapper 의 `Vendor` 표시 문자열이 CLI `--ide` 값과 다르다.** GUI: `MPLAB X IDE`, `Microchip Studio`, `Code Composer Studio`, `Code Warrior`, `AURIX`, `Xilinx Vitis Unified`, `STM32CubeIDE`, `VisualStudio`, `LLVM`, `GNU` → CLI: `mplab`, `microchips`, `ccs`, `codewarrior`, `aurix`, `xilinx`, `stm32cubeide`, `visualstudio`, `llvm`, `gnu`. `Compiler Type` 값만 GUI/CLI 가 동일하다.
- **`wrapper-forge` CLI 가 원문에 등장하는 가이드는 Linux 2종(CMake-Linux, Makefile-Linux)뿐**이고 나머지 14종은 전부 ARACHNE GUI 의 `[Settings] → [C/C++] → [+ Add Wrapper]` 로만 설명한다. Windows 에서도 CLI 는 동작하지만 원문 근거는 없다.

**가이드 ↔ 플러그인 설정 불일치 (설정 쪽을 정본으로 씀)**
- **CodeWarrior Qorivva Tool Settings 라벨.** 가이드 원문은 `[PowerPC Compiler]`/`[PowerPC Linker]`, `wrapper_forge.json` 의 params 는 `Qorivva Compiler`/`Qorivva Linker`. **가이드 문자열이 IDE 실제 라벨**이므로 위 항목은 PowerPC 로 적었다. 설정 쪽을 고칠 것.
- **AURIX CCTC Tool Settings 라벨.** 가이드는 `[TASKING C/C++ Compiler]`/`[TASKING Linker]`, 설정 params 는 `C/C++ Compiler`/`Linker`.
- **CCS 링커 복원값.** 설정은 `revert_linker: ${CG_TOOL_LNK}` 를 쓰지만 가이드 원문은 컴파일러의 `${CG_TOOL_CL}` 만 언급한다 — 링커 복원값은 미확인.
- **AURIX CCTC 링커 실행 파일.** `known_paths.json` 의 `linker_seeds` 는 `ltc.exe`(아카이버 `artc.exe`)인데 가이드는 IDE 의 [TASKING Linker] [Command] 에 `cctc.exe` 를 넣으라고 한다. 탐지 시드와 IDE 설정값의 역할이 다른 것이므로 둘 다 유효하다.
- **CCS 컴파일러 경로 glob.** 가이드는 `ti-cgt-c2000_*` 한정, 설정은 `ti-cgt-*` 로 일반화.
- **MinGW/LLVM 설치 경로.** 설정은 가이드에 없는 `C:/msys64/mingw64/bin`, `C:/msys64/mingw32/bin`, `C:/Program Files (x86)/LLVM/bin` 을 추가로 커버한다. Microchip 계열도 `(x86)` 갈래가 설정에만 있다.
- **`mplab` 역매핑 부재.** `by_exe` 에 `mplab` 엔트리가 없어 `xc8-cc`/`xc8` 은 모두 `microchips` 로 떨어진다. MPLAB X 프로젝트에서는 `--ide mplab` 을 명시해야 한다.
