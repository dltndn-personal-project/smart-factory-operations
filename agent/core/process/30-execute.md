# 30 실행

1. `steps`를 순서대로 수행한다. step이 끝나면 그 `check`를 실행하고 `done: true`로 바꾼 뒤 commit한다.
2. task의 `scope` 밖 파일은 바꾸지 않는다. 필요해지면 되돌리고 `80-escalate.md`의 scope로 멈춘다.
3. 계획과 다르게 진행했으면 그 step의 `note`에 이유를 쓴다. 회고를 쓰면 `deviations`로 옮긴다.
4. 새 step이 필요하면 추가한다. step이 8개를 넘으면 `20-plan.md` 3절대로 분해를 제안한다.
5. 같은 step이 3번 실패하거나 원인을 설명할 수 없으면 `80-escalate.md`의 repeated-failure로 멈춘다.
6. 검증에 필요한 artifact(보고서, 빌드 결과)를 만드는 명령도 step으로 두고 실행한다.
7. 모든 step이 done이면 `40-verify.md`로 간다.

## 세션을 중단할 때

`SESSION.yaml`의 `next_action`에 다음 한 행동을 구체적으로 쓴다. 예: "`src/events/publisher.py`의 flush 순서를 바꾸고 step 3을 확인". "계속 진행"처럼 재개할 수 없는 문장은 쓰지 않는다.

## 하지 않는 일

- 테스트를 삭제·skip하거나 기대값을 바꿔서 통과시키지 않는다. 기대값이 틀렸다고 판단되면 근거와 함께 멈춘다.
- 되돌릴 수 없는 작업(운영 데이터·외부 서비스 변경, 강제 push, 이력 재작성)을 하지 않는다.
- 자격증명을 파일이나 로그에 남기지 않는다.
