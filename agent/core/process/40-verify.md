# 40 검증

1. 모든 변경을 commit한다. `agent.py verify`는 상태 파일 외에 commit하지 않은 변경이 있으면 거부한다. 증거는 commit에 묶이기 때문이다.
2. `agent.py verify`를 실행한다. task의 acceptance와 `agent/config.yaml`의 공통 `verify` 명령을 모두 실행하고, HEAD 기준 결과를 `SESSION.yaml`의 `evidence`에 기록한다.
3. 실패하면 출력으로 원인을 찾아 고치고 commit한 뒤 다시 verify한다.
   - artifact 검사는 파일이 있는지만 본다. 파일을 만드는 명령은 execute의 step으로 실행한다.
   - 검사를 약하게 바꾸거나 건너뛰어 통과시키지 않는다.
4. 같은 항목이 `budget.verify_attempts`회 실패하면 도구가 멈춤을 알린다. `80-escalate.md`의 repeated-failure로 멈춘다.
5. manual 항목은 pending으로 남는다. 확인 방법을 PR 본문에 적는다. 사람이 확인하면 `agent/tasks/<id>.yaml`을 done으로 바꾼다.
6. 모두 pass(또는 manual pending)면 `agent.py retro --result done`을 실행하고 `50-reflect.md`로 간다.

회고를 쓴 뒤 상태 파일이 아닌 파일을 바꾸면 finish가 거부한다. 그 경우 verify부터 다시 한다.
