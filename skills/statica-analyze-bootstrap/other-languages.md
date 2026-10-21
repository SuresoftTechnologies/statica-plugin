# C/C++ 이 아닌 언어의 부트스트랩 — java · kotlin · python · csharp

`SKILL.md` 의 2번 이후는 읽지 마라. 여기가 그 자리를 대신한다.

**시작 전에 사용자 승인을 받아라.** C/C++ 보다 건드리는 것이 적지만(프로젝트 파일은 전혀 고치지 않는다) **공용 STATIC 서버에 프로젝트를 만드는 것은 똑같다.**

**accessKey 는 어디서도 다루지 않는다.** 사용자에게 묻지도, 파일에 쓰지도 마라.

## 무엇이 다른가

| | C/C++ | 여기 네 언어 |
| --- | --- | --- |
| 분석기 | `analyzer-csa` | `analyzer-plugin` |
| 빌드 가로채기 | wrapper 생성 + 치환 + 캡처 | **없다.** 소스와 기술서만 본다 |
| 프로젝트 파일 수정 | 있다 (`guard` 로 원본 보관) | **없다** |
| 분석 단위 | 변경된 TU 만 증분 | 언제나 전량 |
| 서버 업로드 | 명시적 upload 또는 bootstrap-finish | 명시적 upload 또는 bootstrap-finish |

일반 분석과 Stop 훅은 `analyzer-plugin --no-upload` 로 로컬 결과만 저장한다. 이 옵션을 지원하는 바이너리가 필요하며 서버 연결은 여전히 필요하다. 첫 분석은 아래 `bootstrap-finish` 에서 서버에 업로드한다.

## 1. 워크스페이스를 만든다

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-begin \
  --project-dir "$(pwd)" --name "<워크스페이스 이름>" \
  --language <java|kotlin|python|csharp>
```

`--ide` · `--compiler` · `--compiler-path` 는 여기서 쓰이지 않는다. 넘기지 마라.

**`--name` 규칙은 C/C++ 과 똑같다** (`SKILL.md` §4 참조). 영숫자만 남기고 앞의 숫자를 뗐을 때 3자 이상 남아야 한다. **소유자 이메일은 묻지 않는다** — 서버가 accessKey 로 계정을 찾아 소유자로 삼는다.

**csharp 은 분석할 솔루션을 함께 넘긴다.**

```bash
  --language csharp --input "<절대경로>\App.sln" \
  --csharp-configuration Release --csharp-target sdk
```

`--input` 은 `.sln` 또는 `.csproj`다. `--csharp-configuration`(`Debug`/`Release`)과 `--csharp-target`(`framework`/`sdk`, 기본 `framework`)은 선택이다 — **값이 없으면 플래그째 빼라.** .NET 5 이상 / SDK 스타일 프로젝트면 `--csharp-target sdk` 다.

결과의 **`projectKey` 를 기억해라.** 다음 단계에서 빌드 도구에 넘길 값이고, `--name` 에서 뽑은 값과 다를 수 있다(이름이 이미 쓰이고 있으면 `_2` 가 붙는다).

**java · kotlin 은 이 단계에서 서버에 프로젝트까지 만든다.** 다른 두 언어와 다른 점이고, 이유는 아래 2번에 있다. `stage: "project"` 로 실패하면 `projectCreation.code` 로 원인을 짚고(`SKILL.md` §7 의 표) 고친 뒤 **`bootstrap-abort` 하지 말고** 그대로 이어서 하라 — 워크스페이스는 남겨 두었다.

## 2. 분석 입력을 준비한다

### python · csharp — 준비할 것이 없다

바로 3번으로 간다. python 은 분석기가 프로젝트 루트를 직접 훑고, csharp 은 방금 넘긴 솔루션 경로를 쓴다.

(가상환경이 표준 위치에 없어서 손으로 지정해야 한다면, `bootstrap-begin` 이 알려준 경로에 `.STATICPYTHON` 을 만들면 된다. 있으면 그쪽이 우선한다. 형태는 `rootDir` 과 `modules[].{moduleName, baseDir, pythonVersion, virtualEnvironmentDirs}` 다.)

### java · kotlin — 빌드 플러그인으로 기술서를 만든다

분석에 **빌드 결과 클래스 파일이 필요하다.** 그래서 소스만으로는 안 되고, 프로젝트를 실제로 빌드하면서 STATIC 빌드 플러그인을 함께 태워 기술서(`.STATICJAVA` / `.STATICKOTLIN`)를 뽑아야 한다. 기술서 안에는 소스 루트 · 의존 jar 전체 목록 · 컴파일된 클래스 디렉터리 · JDK 경로가 들어간다.

**빌드 명령은 사용자에게 먼저 묻지 말고, 프로젝트 근거로 유추한다.** 프로젝트 루트부터 조사하되 빌드 파일이 하위 디렉터리에 있으면 실제 실행 위치도 함께 찾는다.

1. README · CI 설정 · 빌드 스크립트에서 프로젝트가 사용하는 명령과 실행 위치를 찾는다.
2. Gradle/Maven Wrapper, `build.gradle(.kts)` · `settings.gradle(.kts)` · `pom.xml` 에서 태스크 · 모듈 · 프로파일과 JDK 요구사항을 확인한다. `pom.xml` 이 있다는 이유만으로 별도 빌드 스크립트를 무시하지 마라.
3. 기존 빌드 로그 · 결과물과 현재 JDK · 환경 설정으로 후보를 검증한다. `.class` · JAR 가 있다는 사실만으로 원래 명령이나 옵션을 확정하거나, 현재 소스의 빌드가 성공했다고 보지 마라.

프로젝트 Wrapper가 있으면 우선 사용하고 OS에 맞는 실행 파일을 고른다. **초기 부트스트랩 승인을 받았고 근거가 충분하면, 선택한 명령 · 실행 위치 · 근거를 짧게 알린 뒤 직접 원본 빌드를 실행한다.** 유추한 명령이라는 이유만으로 다시 확인받지 않는다. 대상 모듈 · 프로파일 등 중요한 선택을 근거로 결정할 수 없거나, 필요한 JDK가 없어 설치 등 추가 조치가 필요할 때만 구체적으로 질문한다.

**원본 빌드가 먼저 성공해야 한다.** 실패하면 로그와 프로젝트 설정으로 원인을 조사한다. 성공시키려고 임의로 JDK 요구사항이나 프로젝트 설정을 낮추거나, 테스트를 건너뛰거나, 오류를 무시하거나, 빌드 · 분석 대상을 축소하지 마라. 배포 · 게시(`deploy`/`publish`)는 부트스트랩에 포함하지 않는다.

아래 `clean build` · `clean package` 는 예시이지 고정 명령이 아니다. **확인한 원본 빌드 명령의 태스크 · 프로파일 · 대상 범위를 유지한 채** STATIC 옵션과 태스크/goal 을 추가한다.

**Gradle** — 원본 빌드 명령에 STATIC 옵션과 `static` 태스크를 붙인다.

```bash
./gradlew clean build \
  --init-script="${ARACHNE_INSTALL_PATH}/bin/build-plugin/gradle/static.gradle" \
  -Dstatic.key=<projectKey> \
  "-Dstatic.output=<bootstrap-begin 이 알려준 workspace 경로>" \
  -Dstatic.skipAnalysis=true \
  static
```

**Maven** — 플러그인을 한 번 설치한 뒤 goal 을 붙인다.

```bash
"${ARACHNE_INSTALL_PATH}/bin/build-plugin/maven/install.bat"     # 최초 1회 (Linux 는 install.sh)
./mvnw clean package \
  com.sst.st:static-maven-plugin:5.0.0-SNAPSHOT:static \
  -Dstatic.key=<projectKey> \
  "-Dstatic.output=<workspace 경로>" \
  -Dstatic.skipAnalysis=true
```

각 옵션이 왜 있는지:

- `-Dstatic.key` — **서버에 이미 있는 키여야 한다.** 없으면 기술서를 쓰기도 전에 `response code: 500` 으로 죽는다(실측). `bootstrap-begin` 이 java · kotlin 에서만 서버 등록을 앞당기는 이유가 이것이다.
- `-Dstatic.output` — 기술서를 우리 워크스페이스에 떨어뜨린다. 빼면 `works/<projectKey>` 로 가는데, 워크스페이스 디렉터리 이름과 프로젝트 키가 같으리라는 보장이 없다(`myproj_2` 의 키는 `MYPROJ2`). Windows 는 대소문자를 안 가려 우연히 맞는 일이 많아서 **리눅스에서만 조용히 깨진다.**
- `-Dstatic.skipAnalysis=true` — 기술서만 만들고 분석·업로드는 하지 않는다. 여기서 분석까지 해 버리면 아직 `bootstrapping` 인 워크스페이스에 revision 이 생긴다. 첫 분석은 4번의 `bootstrap-finish` 가 한다.

`install.bat`/`install.sh` 는 `mvn` 을 PATH 에서 찾는다. 프로젝트가 다른 maven 을 쓴다면 그 스크립트를 고쳐 실행하라는 것이 공식 안내다.

**함정: `JAVA_HOME` 과 toolchain JDK.** Gradle/Maven 실행 JVM과 프로젝트 컴파일용 JDK 요구사항을 구분해 확인한다. `JAVA_HOME` · 설치된 JDK · Wrapper 버전 · 프로젝트 toolchain 설정을 조사하고, 이미 설치된 호환 JDK를 사용할 수 있으면 해당 빌드 프로세스의 환경에 적용한다. 전역 환경이나 프로젝트 요구 버전은 임의로 바꾸지 않는다. 필요한 JDK가 없으면 부족한 버전과 근거를 알리고 설치 등 필요한 조치만 질문한다. 원본 빌드와 STATIC 기술서 생성에는 같은 검증된 환경을 사용한다.

**`BUILD SUCCESSFUL` 만으로 끝났다고 보지 마라.** `static` 태스크가 실제로 돌았는지(`> Task :static`) 확인하고, 기술서 파일이 생겼는지 다음 단계로 확인한다.

## 3. 입력을 확인한다

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-verify --project-dir "$(pwd)"
```

`ok: true` 면 분석할 것이 생긴 것이다. java · kotlin 은 기술서를 열어 모듈이 하나 이상인지까지 본다 — 모듈이 0개면 빌드가 소스를 하나도 컴파일하지 않은 것이니 2번으로 돌아간다.

## 4. 마무리한다

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-finish --project-dir "$(pwd)"
```

서버에 프로젝트를 만들고(java · kotlin 은 이미 있으므로 확인만 한다), 워크스페이스를 `ready` 로 바꾸고, **이어서 전체 분석과 업로드까지 한다.** 사용자에게 따로 묻지 않는다 — 첫 revision 이 없으면 서버 화면에 보여줄 것이 없다.

`fullAnalysis.ok` 가 거짓이어도 부트스트랩 자체는 끝난 것이다. 되돌리지 말고 원인만 보고하라(`/statica:upload` 로 다시 시도할 수 있다).

## 그 뒤 — 무엇이 달라지는가

- **Stop 훅**: 소스 mtime 이 `<workspace>/sourcefiles.db` 보다 새로우면 `--no-upload` 로 전량 다시 분석하고 로컬에만 저장한다.
- **`/statica:pre-analyze`**: 훅과 같은 일을 즉시 한다. 서버에 업로드하지 않는다.
- **`/statica:upload`**: 변경 여부와 무관하게 전량 분석하고 서버에 업로드한다. 자연어로 서버 업로드를 명시적으로 요청해도 이 경로를 사용한다.
- **결함 집계**: 분석은 전량이지만 보고하는 수는 **이번에 변경된 파일에 달린 것만**이다. 전체 수가 보고 싶으면 `/statica:upload` 를 쓴다.

**의존성이 바뀌면 기술서가 낡는다** (java · kotlin). jar 를 추가하거나 모듈을 늘렸는데 새 코드가 분석되지 않으면, 2번의 빌드 명령을 다시 돌려 기술서를 새로 만들어라. 소스만 고치는 동안에는 다시 만들 필요가 없다.

## 되돌리기

```bash
python "${SKILL_ROOT}/scripts/run.py" bootstrap-abort --project-dir "$(pwd)" --reason "<이유>"
```

C/C++ 과 달리 **프로젝트에서 되돌릴 것이 없다** — 치환도 wrapper 도 만든 적이 없으므로 워크스페이스만 지운다. 상태가 이미 `ready` 면 거절한다(끝난 연결을 끊는 것은 abort 의 일이 아니다).

**서버에 만든 프로젝트는 지우지 않는다.** java · kotlin 은 `begin` 에서 이미 만들어졌으므로, abort 해도 서버에는 빈 프로젝트가 남는다. 사용자에게 알리고, 정리는 STATIC 웹에서 직접 하도록 안내하라.
