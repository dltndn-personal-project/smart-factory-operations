# 00 세션

## 시작

1. `python3 agent/core/tools/agent.py next`를 실행한다. 검사 오류가 나오면 그 파일부터 고친다. 스스로 고칠 수 없으면 `80-escalate.md`.
2. 진행 중인 task가 있으면 그 브랜치(`agent/<task-id>`)에서 출력된 단계 문서를 읽고 `next_action`부터 이어간다.
3. 새 task가 제시되면 최신 main에서 `agent/<task-id>` 브랜치를 만들고 `agent.py start <task-id>`를 실행한다.
4. 진행할 task가 없으면 `80-escalate.md`의 세션 보고로 끝낸다.

## 루프

```text
start → plan → execute → verify → (요청 시 retro) → finish → (개선 제안) → 다음 task
```

- 단계 전환은 `agent.py phase <단계>`로 한다. verify와 retro는 도구가 단계를 바꾼다.
- 회고(retro)는 사용자가 명시적으로 요청했을 때만 쓴다(`50-reflect.md`). 요청이 없으면 verify 다음에 바로 finish한다.
- task 하나 = 브랜치 하나 = PR 하나. 다음 task는 최신 main에서 새 브랜치로 시작한다. 따라서 merge되지 않은 task에 의존하는 task는 시작할 수 없다.
- finish가 개선 후보를 출력하면 `60-improve.md`를 수행한 뒤 다음 task로 간다.
- `agent/config.yaml`의 `budget.tasks_per_session`만큼 끝냈거나 멈춤 조건만 남으면 세션을 끝낸다.

## commit과 PR

- step마다 commit한다. 메시지는 `<task-id>: <한 일>`.
- finish 후 `agent/tasks/`, `agent/retros/`, `agent/SESSION.yaml` 변경까지 commit하고 PR을 만든다.
- PR 제목은 `<task-id>: <title>`. 본문에는 acceptance별 결과와 증거, 회고 파일 경로(작성한 경우), manual 검증 방법, 제안한 개선 PR 링크를 적는다.
- Agent는 PR을 merge하지 않는다. 코드 변경은 사람이 리뷰하고, 학습 층(`agent/LESSONS.yaml`, 새 회고)만 바꾼 PR은 CI가 승인한다.
- push나 PR 생성이 실패하면 완료로 보고하지 않는다.

## 종료

- 진행 중인 task가 남으면 `SESSION.yaml`의 `next_action`에 다음 한 행동을 구체적으로 쓰고 commit·push한다.
- `80-escalate.md`의 세션 보고 형식으로 사용자에게 알린다.
