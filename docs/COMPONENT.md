# Factory Operations & Control — Component 도메인 설명

시스템 내 책임은 Shared `docs/ARCHITECTURE.md` 4.4절과 17절(Responsibility Summary)이 기준이다. 이 파일은 그 범위 안에서 저장소 수준의 세부를 적는다.

Agent가 계획·구현·검증할 때 참조하는 이 Component의 도메인 슬롯이다. `agent/core`의 절차는 도메인을 모르므로 도메인 지식은 이 파일에만 둔다. `<미정: ...>` 표시가 모두 사라지면 bootstrap이 끝난다(`agent/core/process/10-bootstrap.md`). 사람이 리뷰한다.

## 목적과 책임

<미정: 이 Component가 하는 일을 한두 문장으로>

## 경계

- 하지 않는 일: <미정>
- 소유하는 데이터·자원: <미정>
- Integration Component라면: 조합·검증 책임과 대상 Component 목록

## 용어

| 용어 | 뜻 |
|---|---|
| <미정: 도메인 용어> | |

## 구조

<미정: 주요 디렉터리와 역할. task scope glob의 기준이 된다>

## 외부 의존과 계약

- Shared 계약: task의 `contract`에 적고 `agent/core/process/90-shared.md` 1절로 `contract_ref` 기준 문서를 읽는다.
- 그 외 의존: <미정: 외부 서비스, 데이터, 라이브러리>

## 실행·검증 환경

<미정: 로컬 실행 방법과 필요한 서비스>. 공통 검증 명령은 `agent/config.yaml`의 `verify`에 둔다.
