# 10 Bootstrap

새 Component 또는 새 도메인에서 한 번 수행한다(`type: bootstrap`). 절차는 도메인을 모르므로, 도메인은 아래 네 슬롯으로만 들어온다.

| 슬롯 | 위치 | 채우는 사람 |
|---|---|---|
| 도메인 설명 | `docs/COMPONENT.md` | Agent가 초안, 사람이 리뷰 |
| 검증 명령 | `agent/config.yaml`의 `verify` | Agent가 찾아 실행해 보고 제안, 사람이 리뷰 |
| 목표 | `agent/PLAN.yaml`의 milestone | 사람. Agent는 proposed로 초안만 쓴다 |
| 계약 | Shared `docs/`와 `contract_ref` | 기존 Shared 절차 |

## 절차

1. 저장소 구조, README, 빌드 파일, 기존 테스트를 읽는다. 추측한 내용은 쓰지 않는다.
2. `docs/COMPONENT.md`의 `<미정: ...>`을 채운다. 저장소에서 확인할 수 없는 목적·경계는 사람에게 질문으로 남기고 `80-escalate.md`의 ambiguity로 멈춘다.
3. build·test·lint 명령을 찾아 **실제로 실행**한다. 통과하는 명령만 `verify`에 넣는다. 실패하는 명령은 원인과 함께 PR 본문에 적는다.
4. 사람에게 받은 목표나 저장소의 문서에 있는 목표로 milestone과 첫 task 분해를 `proposed: true`로 추가한다(`20-plan.md`의 plan task 규칙).
5. `agent.py verify` → 회고 → finish. A3(manual)은 사람이 proposed 표시를 지워 승인할 때까지 verifying으로 남는다.

## 도메인에 자동 테스트가 없을 때

검증 방법을 네 가지 check 유형 중 하나로 표현한다: `command`(종료 코드), `artifact`(파일 생성), `metric`(명령 출력 마지막 줄의 숫자와 min/max), `manual`(사람 확인). manual만 가능한 task가 많으면 자동 검증 수단을 만드는 task를 먼저 제안한다.
