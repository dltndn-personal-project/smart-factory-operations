# 20 계획

## task 계획 (phase: plan)

1. `agent/PLAN.yaml`의 task 정의와 `docs/COMPONENT.md`의 관련 절을 읽는다. `contract`가 있으면 `90-shared.md` 1절로 `contract_ref` 기준 문서를 읽는다. `next`가 출력한 lesson을 적용한다.
2. acceptance를 만족하는 가장 작은 변경을 `SESSION.yaml`의 `steps`에 쓴다. step마다 `do`(할 일), `check`(끝났음을 확인하는 방법이나 acceptance ID), `done: false`.
3. 다음 중 하나라도 해당하면 실행하지 않고 멈춘다(`80-escalate.md`).
   - scope 밖이나 다른 Component를 바꿔야 한다
   - acceptance가 모호하거나 서로 모순된다
   - 필요한 계약이 없거나 모순된다
   - step이 8개를 넘는다: 분해안을 `proposed: true` task로 PLAN에 추가하고 현재 task는 block한다
4. `agent.py phase execute`.

## plan task (type: plan)

milestone을 task로 분해한다. scope에 `agent/PLAN.yaml`이 있어야 한다.

- 새 milestone과 task에는 `proposed: true`를 붙인다. 사람이 PR 리뷰에서 지운다.
- 각 task는 착수 조건을 채운다. 검사 스크립트가 proposed가 아닌 task에 강제한다.
  - acceptance: 관찰할 수 있는 결과. "잘 동작한다"처럼 확인할 수 없는 문장은 쓰지 않는다
  - check: `command`, `artifact`, `metric`, `manual` 중 하나 (`10-bootstrap.md`)
  - scope: 바꿀 수 있는 파일 glob. `*`는 `/`를 포함한다 (`src/**`는 src 아래 전부)
  - size: S(한 세션 일부) 또는 M(한 세션). L은 더 쪼갠다
  - depends_on: 반드시 먼저 끝나야 하는 task
  - owner: 사람이 해야 하는 일(권한, 결정, 외부 작업)은 `human`
- 순서가 곧 우선순위다. `next`는 조건을 만족하는 첫 task를 고른다.
- 계약 변경이 필요한 task는 Shared DOCUMENT_CHANGE를 게시하는 task와 그것을 채택하는 task로 나눈다.

## PLAN 수정

- 승인된 task의 acceptance, check, scope를 Agent가 바꾸지 않는다. 바꿔야 하면 수정안을 PR로 제안하고 해당 task는 block한다.
- 새 사실로 task가 불필요해지면 `agent.py drop --reason`으로 기록한다. PLAN에서 지우지 않는다.
