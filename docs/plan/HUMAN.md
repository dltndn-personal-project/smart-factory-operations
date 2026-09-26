# 사람이 할 일의 시점

> 목적: spec `HUMAN.md`의 H-1·H-2가 계획의 어느 시점에 필요한지 적는다. 방법과 건너뛸 때의 영향은 spec `HUMAN.md`가 원본이다(여기서 반복하지 않는다).
> 읽어야 할 때: 조율 agent가 다음 task를 시작하기 전, 책임자가 언제 무엇을 해야 하는지 볼 때.

| ID | 계획에서의 시점 | 필요한 task | 준비가 안 됐을 때 |
|---|---|---|---|
| 등록 | 이 계획 PR(등록 포함, `README.md` 6절)의 merge. OPS-1 전 | 모든 task | 이 PR이 main에 merge되어야 `agent.py next`가 OPS-1을 고른다 |
| H-1 | 계속. 특히 아래 task를 시작하기 전 | 아래 표 | 해당 task의 verify가 실패해 task가 멈춘다(`80-escalate.md` tool). 잘못 통과하지는 않는다 |
| H-2 | OPS-9B merge 뒤 | HUM-1 | C-10 미충족 |

Shared DOCUMENT_CHANGE(Alarm Event 포함) 게시·merge와 PR merge는 조율 agent가 한다(조율 C-01·C-04). 사람 할 일이 아니다. OPS-10의 착수 조건(Shared merge 알림)은 2026-09-27에 충족되었다(`cb6dc3c`).

## H-1이 특히 필요한 시점

| 시작 전 task | 필요한 것 | 이유 |
|---|---|---|
| OPS-1 | 인터넷(pip) | 첫 `make venv`(numpy·scipy wheel) |
| OPS-2, OPS-10 | `gh auth status` 로그인 | Shared·PdM 원문을 원격 Contents API로 읽는다 |
| OPS-4A | Docker Desktop 실행, `timescale/timescaledb:2.30.1-pg17`(없으면 인터넷) | Docker 연동 테스트. 이후 모든 task의 verify에 들어간다 |
| OPS-7A | `eclipse-mosquitto:2.1.2-alpine`(없으면 인터넷) | broker 연동 테스트 |
| OPS-9A, OPS-9B | Docker Desktop, 인터넷(`python:3.12-slim`, 이미지 안 pip) | 이미지 빌드. OPS-9A 뒤 모든 task의 verify에 smoke가 들어간다 |
| 모든 task | `gh auth status` 로그인 | push, PR, `validate.py --remote` |

2026-09-27 기준 이 맥에는 `timescale/timescaledb:2.30.1-pg17`, `eclipse-mosquitto:2.1.2-alpine`이 있고 `python:3.12-slim`은 없다(`python:3.12-slim-bookworm`만 있음). OPS-9A 첫 빌드 때 받는다.

## H-2의 기록

`08-verification.md` 4·5절(HUM-1 블록, 결과 문서 형식, 완료 기록 방법).
