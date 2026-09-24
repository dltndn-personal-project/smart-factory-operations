# 60 개선

`agent.py scan`(finish가 자동으로 실행)이 후보를 출력하면 수행한다. 후보는 사용자 요청으로 작성된 회고에서만 나온다. **제안은 항상 자동으로 하고, 채택은 아래 표를 따른다.** 한 세션에서는 `budget.improvements_per_session`건까지 올리고, 나머지는 세션 보고에 남긴다.

후보 하나 = 브랜치 `agent/improve-<tag>` 하나 = PR 하나. task 작업과 섞지 않는다. PR 본문에는 근거 회고, 가설(무엇이 줄어야 하나), 되돌리는 방법을 적는다.

| cause | 제안 | 채택 |
|---|---|---|
| AGENT | `agent/LESSONS.yaml`에 trial lesson 추가 | CI 자동 승인 (학습 층만 바꾼 PR) |
| ENVIRONMENT | `agent/config.yaml`이나 환경 설정 수정 | 사람 리뷰 |
| DOMAIN_DOC | `docs/COMPONENT.md` 보완 | 사람 리뷰 |
| PLAN | PLAN 수정안 (`proposed: true`) | 사람 리뷰 |
| PROCESS | Shared `agent-core` DOCUMENT_CHANGE (`90-shared.md` 7절) | Shared CODEOWNERS 승인 → 모든 Component에 전파 |
| CONTRACT | Shared 계약 DOCUMENT_CHANGE 또는 MESSAGE | 기존 계약 절차 |
| EXTERNAL | 없음 | - |

ENVIRONMENT, DOMAIN_DOC, PLAN 제안이 사람 리뷰를 기다리는 동안 반복을 막아야 하면 trial lesson을 함께 추가할 수 있다.

## lesson 작성

```yaml
- id: L-<다음 번호>
  tag: <후보 tag>
  rule: <한 문장 명령형. 언제 무엇을 하는지>
  applies_to: [plan | execute | verify | reflect | all]
  source: [<후보를 만든 회고 ID>]   # repeat개 이상, 또는 high 1건
  status: trial
  introduced_at: '<현재 UTC>'
```

- 상위 규칙(`AGENTS.md`, `agent/core`)과 충돌하거나, 검증·멈춤 조건을 약하게 만드는 lesson은 만들지 않는다. 그런 필요는 PROCESS 제안으로 올린다.
- lesson이 `improvement.max_lessons`에 도달하면 새 lesson을 넣기 전에 비슷한 것을 통합하거나 효과 없는 것을 삭제한다.

## lesson 평가

scan이 평가를 알리면 같은 방식의 PR로 반영한다.

- 재발: 규칙을 구체적으로 고치거나 삭제한다. 규칙으로 해결할 수 없으면 원인 경로(ENVIRONMENT, PROCESS 등)로 제안한다.
- 사용되지 않음: 삭제한다.
- 효과 있음: `status: adopted`.
- 다른 Component에도 유효할 adopted lesson은 PROCESS 제안으로 승격한다. Shared에 반영되어 채택하면 lesson을 삭제한다.

## 하지 않는 일

- 검증 명령 삭제, 예산 완화, 멈춤 조건 완화, `AGENTS.md`·`agent/core`·`.github` 변경을 학습 층 PR에 섞지 않는다.
- 근거 회고 없이 규칙을 추가하지 않는다.
