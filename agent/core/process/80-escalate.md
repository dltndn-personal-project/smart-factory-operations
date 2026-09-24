# 80 멈춤과 보고

## 멈춤 조건

| stops 값 | 상황 |
|---|---|
| ambiguity | 동작에 영향을 주는 요구나 acceptance가 모호하거나 모순된다 |
| contract | 필요한 계약이 없거나 모순된다. `contract_ref`가 설정되지 않았다 |
| scope | scope 밖 또는 다른 Component를 바꿔야 한다 |
| irreversible | 되돌릴 수 없는 작업, 운영 데이터·외부 서비스 변경, 자격증명이 필요하다 |
| unverifiable | acceptance를 검증할 방법이 없다 |
| repeated-failure | 같은 검증이 `budget.verify_attempts`회, 같은 step이 3회 실패했다 |
| budget | 세션 예산을 다 썼다 |
| tool | 도구나 검사 오류를 스스로 고칠 수 없다 |

## 멈출 때

1. 추측으로 진행하지 않는다. 지금까지의 변경을 commit한다.
2. 사용자가 회고를 요청했으면 `agent.py retro --result blocked`로 회고를 만들고 `stops`에 분류, `friction`에 원인을 쓴다.
3. `agent.py block --reason "<stops 분류>: <무엇이 막혔나>" --unblock-when "<해제 조건>" --owner "<결정할 사람이나 Component>"`.
4. commit하고 PR 또는 브랜치를 남긴다. PR 본문에 사람에게 필요한 질문을 선택지와 함께 적는다.
5. 독립적인 다음 task로 넘어간다(`00-session.md`).

더 할 가치가 없는 task는 `agent.py drop --reason "<이유>"`. 회고를 요청받았으면 먼저 `agent.py retro --result dropped`.

해제: 사람이 해제 조건을 해결하고 `agent/tasks/<id>.yaml`을 삭제하면 다시 시작할 수 있다. 필요하면 PLAN의 task를 고친다.

## 세션 보고

세션을 끝낼 때 사용자에게 다음을 알린다. 해당 없는 항목은 생략한다.

- 완료: task ID, PR 링크, 증거 요약
- 사람 확인 대기(manual): task ID와 확인 방법
- 차단: task ID, 질문, 담당
- 승인 대기: proposed task와 milestone
- 개선 제안: PR 링크와 경로(자동 채택, 사람 리뷰, Shared)
- 실패한 조회·게시·push
