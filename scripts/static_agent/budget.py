"""자식 프로세스 실행 시간 예산.

이 값들은 ``hooks/hooks.json`` 의 Stop 훅 ``timeout`` 과 한 몸이다. 둘 중
하나를 바꾸면 반드시 다른 하나도 같이 봐야 한다 — 그래서 두 숫자를 각자
따로 두지 않고 여기 한 곳에 모아둔다.

왜 중요한가: Claude Code 는 예산이 지나면 훅을 "취소"한다. 취소가 훅이
띄운 손자 프로세스(analyzer-csa.exe)까지 죽이는지는 문서에 없으므로 고아가
될 수 있다고 가정한다. 고아가 되면 워크스페이스 잠금이 남고, 다음 실행이
종료 코드 120("워크스페이스가 잠겨 있습니다")으로 실패한다. 플러그인은 그
잠금을 풀 수단이 없다. 그러니 CLI 가 훅보다 반드시 먼저 끝나야 하고, 그래야
제한 시간 초과를 정상적인 결과로 보고할 수 있다.

여기 있는 값들은 **훅 경로 전용**이다. 자식 하나하나에 제한 시간을 거는 것만
으로는 부족하다 — 재빌드가 자기 몫을 다 쓰고 나서 TU 루프가 또 돌면 훅 예산을
확정적으로 넘긴다. 그래서 실행 전체에 걸리는 마감 시각(deadline)을 **호출한
쪽**이 정한다. 지금 훅 예산 아래에 있는지 아는 것은 호출한 쪽뿐이기 때문이다.
``hook.run_stop`` 은 ``RUN_BUDGET_SECONDS`` 로 마감을 만들어 넘기고,
``/statica:pre-analyze`` 슬래시 커맨드는 마감 없이(``deadline=None``) 부른다 —
슬래시 커맨드는 훅 예산에 묶이지 않으므로 전체 재빌드에 30분을 써도 된다.
"""

# hooks/hooks.json 의 Stop 훅 timeout(초). Claude Code 의 command 훅 기본값과 같다.
# 이 상수와 hooks/hooks.json 의 "timeout" 은 한 쌍이다. 한쪽만 고치면 아래 파생
# 값들이 전부 거짓말이 되므로, 둘을 반드시 같이 고쳐야 한다.
HOOK_TIMEOUT_SECONDS = 600

# 마지막 자식이 돌아온 뒤 CLI 가 결함을 집계하고 JSON 을 찍어 정상 종료하는 데
# 남겨두는 여유. 이 시간이 있어야 "제한 시간 초과"조차 정상적인 결과로 보고된다.
REPORT_HEADROOM_SECONDS = 60

# 훅 아래에서 도는 analyze 실행 하나가 통째로(재빌드 + TU 루프) 쓸 수 있는 벽시계
# 시간. hook.run_stop 이 time.monotonic() 에 이 값을 더해 deadline 으로 넘긴다.
RUN_BUDGET_SECONDS = HOOK_TIMEOUT_SECONDS - REPORT_HEADROOM_SECONDS

# 훅 아래에서 자식 하나에게 줄 수 있는 최대 제한 시간. 자식 하나가 실행 예산을
# 통째로 삼킬 수는 있어도 그보다 길 수는 없다. 실제로 자식에게 건네는 값은
# min(CHILD_TIMEOUT_SECONDS, 남은 예산) 이다.
CHILD_TIMEOUT_SECONDS = RUN_BUDGET_SECONDS

# 남은 예산이 이보다 짧으면 자식을 아예 시작하지 않는다. 3초짜리 제한 시간을 받은
# 분석기는 워크스페이스를 열자마자 강제 종료되고, 그 죽음이 바로 우리가 피하려는
# 잠금을 남긴다 — 시작하지 않는 편이 낫다. 15초는 분석기가 워크스페이스를 열고
# TU 하나를 끝내는 데 드는 최소한의 시간으로 잡은 하한선이다.
MIN_CHILD_SECONDS = 15

# 훅 예산에 묶이지 않는 경로(/statica:pre-analyze 슬래시 커맨드)에서 자식에게 주는
# 제한 시간. 훅 예산이 생기기 전 rebuild() 와 analyzer.run() 이 쓰던 값 그대로다 —
# 전체 재빌드는 원래 30분을 받을 자격이 있고, 슬래시 커맨드에서는 그대로 받는다.
UNBOUNDED_CHILD_TIMEOUT_SECONDS = 1800
