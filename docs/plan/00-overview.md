# 00 계획 개요

> 목적: 단계(= milestone M1~M6)의 결과와 종료 조건, 모든 task의 의존 관계, 완료 정의 C-01~C-10을 어느 task가 만족시키는지 정한다.
> 읽어야 할 때: 계획을 등록·수정할 때, 다음에 무엇을 할지 정할 때, milestone 완료를 판단할 때. 같이 읽을 spec: `docs/spec/00-overview.md`.

## 1. 단계

단계 하나가 milestone 하나다. spec 00 6절의 milestone 이름을 그대로 쓰고, 큰 task 넷(OPS-3, OPS-4, OPS-7, OPS-9)을 A·B로 나눴다(D-37, D-45). M0(BOOT-1)은 이 계획 PR에서 끝났다.

| 단계 | 결과 | task | 새 verify 명령 | 필요한 환경 | 공통 verify 시간(추정) |
|---|---|---|---|---|---|
| M1 코어 | 설정·시계·로그, Payload 파서·생성, LineTracker·결합, Interlock·Alarm·워커 처리 함수가 MQTT·DB 없이 가짜로 동작 | OPS-1, OPS-2, OPS-3A, OPS-3B | `unit` | Python 3.12, 인터넷(첫 pip) | 30초 미만(첫 설치 +1~2분) |
| M2 저장과 분석 | DDL, DB 스레드(쓰기·배치·요약·재연결), 상관분석 | OPS-4A, OPS-4B, OPS-5 | `docker` | + Docker Desktop, `timescale/timescaledb:2.30.1-pg17` | 1.5~2분 |
| M3 연동 | 스냅숏·HTTP API, 실제 Mosquitto·DB에 연결한 앱, broker 재연결, Interlock·Dashboard 지연 측정 | OPS-6, OPS-7A, OPS-7B | 없음(`docker`에 테스트 추가) | + `eclipse-mosquitto:2.1.2-alpine` | 3~4분(Dashboard 측정 60초 포함) |
| M4 화면과 패키징 | 화면, 이미지 smoke, 개발용 compose와 가짜 입력 | OPS-8, OPS-9A, OPS-9B | `smoke` | + 인터넷(`python:3.12-slim`, 이미지 안 pip), `sips` | 5~6분(첫 이미지 빌드는 수 분 더) |
| M5 계약 채택 | Shared 확정본(PdM Result·PdM Spectrum·Alarm Event, `cb6dc3c`)을 `contract_ref`로 채택하고 파서를 맞춤 | OPS-10 | 없음 | + `gh` 로그인(Shared merge는 충족) | OPS-2 바로 뒤면 30초 미만, M4 뒤면 5~6분 |
| M6 사람 확인 | 사람이 Dashboard 확인 목록을 통과시킴 | HUM-1 (`owner: human`) | 없음 | 맥북 Chrome·Safari, Docker | 없음(사람 약 20분) |

M5는 M4 뒤에 두었지만 다른 단계를 막지 않는다(HUM-1은 OPS-10에 의존하지 않는다). 착수 조건인 Shared merge는 이 계획 PR 작성 중에 충족되었다(`cb6dc3c`). 그래서 조율 agent가 OPS-2 바로 뒤로 끼워 넣는 것을 권장한다(`README.md` 4절, `02-mqtt.md` 5절). 실제로 OPS-2 바로 뒤에 실행했다(조율 C-21, D-48).

PLAN.yaml에 넣을 milestone 블록(M0은 그대로 둔다. D-02·D-03):

```yaml
  - id: M1
    outcome: 설정·시계·로그, 입력 Payload 파서 6종과 발행 Payload 생성, LineTracker·시간 결합, Interlock·Alarm·워커 처리 함수가 MQTT·DB 없이 가짜 시계·발행기·DB 싱크로 동작한다
    exit_criteria:
      - make test가 통과하고 C-01(test_payloads.py), C-02(test_interlock.py S-01~S-12, test_alarm.py L-01~L-11) 테스트가 그 안에 있다
      - 저장소 루트에서 .venv/bin/python -m factory_operations serve가 Broker·DB 없이 기동해 /healthz가 200이다
      - agent/config.yaml verify에 unit이 있다
  - id: M2
    outcome: db/schema.sql이 TimescaleDB initdb로 적용되고, DB 스레드가 쓰기 작업·센서 배치·요약 조회·재연결을 하며, 상관분석이 DB 데이터로 주기 계산된다
    exit_criteria:
      - make docker-test가 통과하고 C-03(test_schema.py) 테스트가 그 안에 있다
      - make test에 C-07(test_correlation.py 알려진 lag 13초) 테스트가 있다
      - agent/config.yaml verify에 docker가 있다
  - id: M3
    outcome: 실제 Mosquitto·TimescaleDB에 연결한 앱이 입력을 기록·결합하고, CRITICAL에 1초 안에 STOP과 Alarm Event를 내며, 명령 결과를 기록하고, /api/snapshot이 5초 안에 갱신된다
    exit_criteria:
      - make docker-test가 통과하고 C-04·C-06(test_app_flow.py), C-05(test_interlock_latency.py), C-08(test_dashboard_latency.py), broker 재시작 복구(test_broker_restart.py) 테스트가 그 안에 있다
      - Broker·DB 없이 기동한 앱의 /readyz가 503이고, paho·psycopg·FastAPI를 import하는 모듈이 각각 하나다
  - id: M4
    outcome: 브라우저 Dashboard가 스냅숏으로 모든 칸을 그리고, 이미지 smoke가 컨테이너 안의 앱을 자동 확인하며, 개발용 compose와 가짜 입력으로 다른 Component 없이 화면 전체를 볼 수 있다
    exit_criteria:
      - make smoke가 통과한다 (C-09)
      - 개발용 compose와 fake_feed로 띄운 앱의 스냅숏에 라인·PdM·스펙트럼·진동·검사가 LIVE로 나오고 STOP이 적용된다 (OPS-9B A4)
      - docs/COMPONENT.md 실행 절이 실제 실행 방법과 같다
      - agent/config.yaml verify에 smoke가 있다
  - id: M5
    outcome: PdM Result·PdM Spectrum·Alarm Event가 확정된 Shared commit을 contract_ref로 채택하고, 파서·fixture·spec이 그 확정본과 맞다
    exit_criteria:
      - SHARED_CONFIG.json contract_ref가 cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8이고 validate.py --remote가 통과한다
      - contract_ref의 INTERFACES 예시로 만든 fixture를 파서가 받고 거부 예를 거부하며, build_alarm의 키가 Shared Alarm Event 예시와 같고, 확정본의 필수 필드·배열 규칙을 검사한다
  - id: M6
    outcome: 사람이 맥북 브라우저에서 Dashboard 확인 목록을 통과시켰다
    exit_criteria:
      - HUM-1의 M-01~M-10이 모두 통과다 (C-10)
```

## 2. task 목록과 의존

PLAN 순서(= `agent.py next`의 우선순위):

| # | task | 단계 | 선행 | size | 내용 | 계획 파일 |
|---|---|---|---|---|---|---|
| 1 | BOOT-1 | M0 | - | M | 이 계획 PR에서 완료(A3는 D-02로 갈음) | `README.md` 6절 |
| 2 | OPS-1 | M1 | BOOT-1 | M | 골격, 설정(모든 키), 시계, 로그, `/healthz`, Makefile, 공용 fixture, verify `unit` | `01-core.md` |
| 3 | OPS-2 | M1 | OPS-1 | M | 입력 파서 6종, 발행 Payload 생성, 스펙트럼 패널, Payload fixture | `02-mqtt.md` |
| 4 | OPS-3A | M1 | OPS-2 | M | StateStore, LineTracker, 시간 결합 | `03-control.md` |
| 5 | OPS-3B | M1 | OPS-3A | M | Interlock, AlarmManager, 워커 처리 함수(Processor), DB 쓰기 작업 타입, S·L 시나리오 | `03-control.md` |
| 6 | OPS-4A | M2 | OPS-1 | S | `db/schema.sql`, Docker DB fixture, `make docker-test`, verify `docker` | `05-storage.md` |
| 7 | OPS-4B | M2 | OPS-3B, OPS-4A | M | DB 스레드(쓰기 작업·센서 배치·요약·주기 작업·재연결) | `05-storage.md` |
| 8 | OPS-5 | M2 | OPS-4B | S | 상관분석, DB 주기 계산 확인 | `04-analysis.md` |
| 9 | OPS-6 | M3 | OPS-4B | M | 스냅숏, HTTP API, 이미지 응답, 예시 이미지 fixture | `06-dashboard.md` |
| 10 | OPS-7A | M3 | OPS-5, OPS-6 | M | paho client, 워커 스레드, 앱 조립, Docker 앱 fixture, 흐름 연동 테스트(C-04, C-06) | `02-mqtt.md` |
| 11 | OPS-7B | M3 | OPS-7A | M | broker 재시작 복구, Interlock 지연(C-05), Dashboard 갱신 지연(C-08) | `08-verification.md` |
| 12 | OPS-8 | M4 | OPS-6 | M | 화면(`web/static/`) | `06-dashboard.md` |
| 13 | OPS-9A | M4 | OPS-7A | M | Dockerfile, `.dockerignore`, `scripts/smoke.py`, verify `smoke` | `07-runtime.md` |
| 14 | OPS-9B | M4 | OPS-9A, OPS-8 | M | 개발용 compose, `scripts/fake_feed.py`, `make feed`, COMPONENT.md 실행 절 | `07-runtime.md` |
| 15 | OPS-10 | M5 | OPS-2 (착수 조건 충족: Shared `cb6dc3c`) | M | `contract_ref` 채택, 확정본과 파서·fixture·spec 맞춤. OPS-2 바로 뒤 권장 | `02-mqtt.md` 5절 |
| 16 | HUM-1 | M6 | OPS-9B | M | Dashboard 확인 M-01~M-10 (`owner: human`) | `08-verification.md` 3절 |

의존 그래프(화살표는 "먼저 끝나야 한다"):

```text
BOOT-1 ─▶ OPS-1 ─┬─▶ OPS-2 ─┬─▶ OPS-3A ─▶ OPS-3B ─┐
                 │          │                      ├─▶ OPS-4B ─┬─▶ OPS-5 ─┐
                 └─▶ OPS-4A ┼──────────────────────┘           └─▶ OPS-6 ─┼─▶ OPS-7A ─┬─▶ OPS-7B
                            │                                             │           └─▶ OPS-9A ─┐
                            │                                             └─▶ OPS-8 ──────────────┴─▶ OPS-9B ─▶ HUM-1
                            └─▶ OPS-10   (Shared merge 알림 충족 cb6dc3c. OPS-2 바로 뒤 권장)
```

- `depends_on`은 실제 선행만 적는다. 그래서 한 줄기가 막혀도(`agent.py block`) `next`가 다른 줄기의 task를 고른다.
- OPS-4B가 OPS-3B 뒤인 것은 DB 쓰기 작업 타입(`store/jobs.py`)을 OPS-3B가 만들기 때문이다(D-37). 단계 경계를 넘는 의존을 만들지 않으려고 작업 타입을 M1에 두었다. OPS-4A(DDL·Docker 기반)는 OPS-1만 필요해 M1과 병렬로 할 수 있다(D-45).
- OPS-10과 HUM-1은 서로 의존하지 않는다. 어느 쪽이 먼저 끝나도 된다.
- 병렬로 돌릴 수 있는 조합은 `README.md` 4절.

## 3. 완료 정의 대응

모든 C-xx가 하나 이상의 task acceptance로 덮인다. "테스트"는 acceptance가 가리키는 이름 붙은 pytest node id다(D-42).

| ID | 확인 | task(acceptance) |
|---|---|---|
| C-01 | 파서 6종의 받음·거부, Conveyor Control·Alarm Event 생성 형식 | OPS-2(A2~A7), OPS-10(A3 Shared 확정 예시, A4 확정 규칙) |
| C-02 | S-01~S-12, L-01~L-11 | OPS-3B(A2, A3) |
| C-03 | initdb 적용·재실행, 테이블 8개·view·hypertable | OPS-4A(A2, A3 DDL이 spec과 같음) |
| C-04 | 실제 broker·DB에서 표대로 행, 결합 값 | OPS-7A(A3 `test_rows_and_joins`), OPS-4B(A2 작업별 행) |
| C-05 | CRITICAL → STOP 1.0초(5회 최댓값), Alarm Event 수신, 발행 순서는 L-07 | OPS-7B(A1), OPS-3B(A3 `test_l07`) |
| C-06 | Line Status 결과로 `control.result`, 대기 STOP 종료 | OPS-7A(A3 `test_stop_result_recorded`), OPS-3B(A2 S-03, A4) |
| C-07 | 알려진 lag 13 ± 1초, 표본 부족 null | OPS-5(A2, A3) |
| C-08 | Dashboard 갱신 지연 최댓값 5.0초 | OPS-7B(A2) |
| C-09 | `make smoke` | OPS-9A(A1) |
| C-10 | M-01~M-10 사람 통과 | HUM-1(M01~M10) |

한 번 들어간 verify 명령은 이후 모든 task에서 돈다. 그래서 C-01·C-02·C-07(`unit`), C-03~C-06·C-08(`docker`), C-09(`smoke`)는 해당 task 뒤의 모든 변경에서 다시 확인된다. OPS-10 전의 C-01은 A-05·A-06 가정(PdM 아키텍처 초안 예시) 기준이다.

## 4. 사람 task나 다른 Component에서 문제가 나오면

- HUM-1에서 실패한 항목은 조율 agent가 해당 영역의 `type: fix` task(ID `FIX-<번호>`, milestone M6, scope는 그 영역, acceptance는 가능한 한 command)로 추가한다. 수정이 merge되면 사람은 실패했던 항목만 다시 확인한다(spec 08 7절, `08-verification.md` 3절).
- integration E2E나 Shared 확정에서 형식 차이가 나오면 OPS-10(아직이면) 또는 새 FIX task로 맞춘다. 교차 약속(`AGREEMENTS.md`)을 바꾸는 일이면 조율 agent가 먼저 정한다.
