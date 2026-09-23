# 50 회고

task가 끝나거나(done) 멈출 때(blocked, dropped) 반드시 쓴다. `agent.py retro --result <결과>`가 초안을 만든다. 예시는 `agent/core/examples/retros/`.

## 작성

- `signals`: 도구가 채운 숫자는 고치지 않는다. `stops`에는 멈춘 이유(`80-escalate.md`의 분류), `deviations`에는 절차나 계획과 다르게 한 일을 쓴다.
- `friction`: 시간을 쓰게 만든 원인마다 하나. 없으면 빈 배열이 정상이다. 만들어내지 않는다.
  - `tag`: 원인에 붙이는 kebab-case 이름. 도구가 보여준 기존 tag와 원인이 같으면 재사용한다. 증상이 아니라 원인으로 짓는다(`test-failed`가 아니라 `db-not-running`).
  - `cause`: 아래 표에서 고른다.
  - `severity`: high는 scope 위반, 검증 우회, 계약 오독, 되돌릴 수 없는 작업이나 그 위험. 그 외는 low.
  - `what`, `evidence`: 명령 출력, 파일 경로 같은 사실. `proposal`: 재발을 막을 구체적 변경 또는 null.
  - `doc`: cause가 PROCESS면 문제가 된 `agent/core/` 파일. 그 외는 null.
- `lessons_applied`: `next`가 보여준 lesson 중 실제로 따른 것.
- `share`: 다른 Component가 알아야 할 사실이 있으면 SHARED(`90-shared.md` 5절로 MESSAGE 게시), 이 Component에만 해당하면 COMPONENT_LOCAL, 없으면 NONE.

| cause | 뜻 |
|---|---|
| AGENT | Agent의 판단·습관 문제 (추측, 확인 누락) |
| ENVIRONMENT | 실행 환경, 검증 명령, 의존 서비스 |
| DOMAIN_DOC | `docs/COMPONENT.md`가 없거나 틀림 |
| PLAN | task 정의(acceptance, scope, 크기, 순서)가 틀림 |
| PROCESS | `agent/core`의 절차나 도구가 없거나 틀림 |
| CONTRACT | Shared 계약이 모호하거나 틀림 |
| EXTERNAL | 통제 밖의 일시적 장애 |

## 다음

- done이면 `agent.py finish`. 개선 후보가 출력되면 `60-improve.md`.
- blocked나 dropped이면 `agent.py block ...` 또는 `agent.py drop ...` (`80-escalate.md`).

회고 파일은 merge된 뒤 수정하지 않는다. CI가 검사한다. 나중에 알게 된 사실은 다음 회고에 쓴다.
