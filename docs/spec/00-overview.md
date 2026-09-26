# 00 개요

> 목적: 무엇을 만들고 언제 끝났다고 하는지 정한다.
> 읽어야 할 때: 계획(PLAN) 작업, milestone 완료 판단, 범위가 애매할 때.

## 1. 목표

Smart Factory의 중앙 운영 Component를 만든다. MQTT로 Simulator의 센서·제품·라인 상태, PdM의 설비 상태와 스펙트럼, Vision의 검사 결과를 받아 PostgreSQL+TimescaleDB에 기록하고, 설비 상태가 `CRITICAL`이면 Conveyor에 `STOP`을 보낸다(Interlock). `WARNING`·`CRITICAL` 진입은 Alarm으로 기록·발행한다. 설비 상태와 불량의 상관관계를 계산하고, 브라우저 Dashboard(1초 polling)로 모두 보여 준다. 운영자는 Dashboard에서 라인을 다시 돌린다(`START`).

Python 프로세스 하나(MQTT·판단·DB·HTTP)와 정적 화면으로 만든다(`01-core.md`).

## 2. 완료 정의

아래가 모두 참이면 이 Component는 완료다. 다른 Component의 구현이나 Shared 반영은 조건이 아니다(Shared 반영은 `AGREEMENTS.md`, `HUMAN.md`).

| ID | 관찰할 수 있는 결과 | 확인 |
|---|---|---|
| C-01 | 입력 여섯 Topic의 Payload 파서가 `02-mqtt.md` 3절 규칙대로 받거나 거부하고, Conveyor Control·Alarm Event 생성 결과가 `AGREEMENTS.md` A-02·A-03과 같다 | 단위(자동) |
| C-02 | `03-control.md`의 Interlock 시나리오 표(S-01~S-12)와 Alarm 시나리오 표(L-01~L-11)가 모두 기대대로다 | 단위(자동, 가짜 시계) |
| C-03 | `db/schema.sql`을 `timescale/timescaledb:2.30.1-pg17`의 initdb로 적용하면 테이블 8개(`schema_info` 포함)·view 1개·hypertable 1개가 생기고, 같은 파일을 한 번 더 실행해도 오류가 없다 | 연동(자동, Docker) |
| C-04 | 실제 Mosquitto·DB와 연결한 앱에 각 Topic 메시지를 보내면 `05-storage.md` 2절 표대로 행이 생긴다. `sensor_chunk.fault_level`과 `inspection.health_index_at_time`이 `04-analysis.md` 1절 결합 규칙과 같다 | 연동(자동, Docker) |
| C-05 | `CRITICAL` PdM Result를 broker에 발행한 뒤 1.0초 안에 `STOP`(`reason: INTERLOCK_CRITICAL`)이 broker에 나오고 같은 결과의 Alarm Event도 나온다. 5회 반복의 최댓값으로 판정한다. Alarm Event를 STOP보다 먼저 발행하는 것은 단위 테스트(L-07)의 발행 호출 순서로 확인한다(서로 다른 Topic의 수신 순서는 보장되지 않는다) | 연동(자동, Docker) |
| C-06 | 가짜 Simulator가 Line Status `last_command`로 결과를 돌려주면 `control.result`가 채워지고 대기 중인 STOP이 끝난다 | 연동(자동, Docker) |
| C-07 | 알려진 lag(13초)로 만든 합성 데이터에서 상관분석의 최대 |Pearson| lag가 13 ± 1초다. 표본 부족 조건에서 계수가 null이다 | 단위(자동) |
| C-08 | Dashboard 갱신 지연(`08-verification.md` 4절 방법)의 최댓값이 5.0초 이하다 | 연동(자동, Docker) |
| C-09 | `make smoke`: 이미지 빌드 후 컨테이너가 뜬 뒤 30초 안에 `/readyz`가 200이고, 컨테이너 안의 앱이 MQTT·DB·Image Storage(`:ro`)와 연결해 STOP 발행·DB 기록·이미지 응답을 한다 | smoke(자동) |
| C-10 | Dashboard 확인 목록(`08-verification.md` 6절 M-01~M-10)을 사람이 통과시켰다 | 사람 task |

## 3. 시연에서 이 Component의 역할

전체 시연은 시스템 compose(integration 소유)로 네 Component를 함께 띄운 상태에서 한다. simulator 시연(simulator `docs/spec/00-overview.md` 3절)의 3:00 수동 STOP을 Interlock이 대신한다. Operations 쪽에서 보여 줄 것:

| 단계 | 조작(사람) | Dashboard에서 보여 줄 것 |
|---|---|---|
| 1 | 시작(Fault Level 0) | Conveyor `RUNNING`, Current Fault Level 0(평가용 표시), Equipment State `NORMAL`, 실시간 진동·FFT Spectrum, 검사 결과가 2초마다 늘어남 |
| 2 | simulator 화면에서 Fault Level 3 | 진동·스펙트럼 변화, Health Index 하락, State `CAUTION`(Alarm 없음) |
| 3 | Fault Level 6, 약 1분 30초 유지 | State `WARNING`, Alarm History에 `WARNING` 1건, 불량 검사 결과·Defect Rate 증가, 상관관계 계수가 "표본 부족"에서 값으로 바뀜 |
| 4 | Fault Level 9 | 1~2초 안에 `CRITICAL` Alarm, Interlock `STOP`, Conveyor `STOPPED`, Control History에 `INTERLOCK_CRITICAL`·`APPLIED`. PdM 칸이 "마지막 판정"으로 바뀜 |
| 5 | Fault Level 0으로 내린 뒤 Dashboard `START` | Control History에 `OPERATOR_START`·`APPLIED`, 약 1초 뒤 새 판정 `NORMAL` |

Fault Level과 State의 대응은 PdM의 Health Index 보정(목표 `100·(1−(f/10)^1.3)`, 조율 C-13)을 따른 예상값이다. 실제 값은 PdM 모델에 따라 조금 다를 수 있다.

## 4. 범위

| 한다 | 하지 않는다 |
|---|---|
| 여섯 Topic 구독과 검증, DB 기록(DDL 소유) | FFT, Feature Extraction(RMS 등), Health Index 계산(PdM) |
| Line Status 추적, Interlock STOP, 운영자 START/STOP, 명령 결과 확인 | 결함 판정, Grad-CAM(Vision) |
| Alarm 판정·기록·발행(`factory/alarm/event`) | Fault Level 조작, 물리적 정지(Simulator) |
| 시간 결합(`fault_level`, `health_index_at_time`), 상관분석 | Ground Truth 파일 읽기, Ground Truth를 판단 입력으로 쓰기 |
| Dashboard(HTTP + 정적 화면 + 1초 polling), 이미지 읽기(`:ro`) | 시스템 compose, Broker·DB·볼륨 실행 정의, 시스템 E2E(integration) |
| 저장소 Dockerfile, 개발용 compose, 가짜 입력 스크립트 | 인증·TLS, 재시도·중복 제거·멱등성, HA, 백업, 운영 수준 성능 |

## 5. 경계와 외부 의존

- 외부와 주고받는 것은 `AGREEMENTS.md`가 전부다. HTTP API(`06-dashboard.md`)는 브라우저와 검증 도구만 쓴다. 다른 Runtime Component는 호출하지 않는다.
- 소유: DB 스키마와 모든 DB 기록, Conveyor Control·Alarm Event 발행, Interlock·Alarm 규칙, Dashboard.
- 의존: MQTT Broker(Mosquitto 2.1.2), PostgreSQL 17 + TimescaleDB 2.30.1(`timescale/timescaledb:2.30.1-pg17`), Image Storage named volume(읽기 전용), 맥북 Chrome(화면 확인 기준 브라우저).

## 6. 구현 순서 (계획 입력)

계획 작업이 `agent/PLAN.yaml`로 옮길 milestone과 task 후보다. task 하나가 PR 하나이고 앞 task가 merge된 뒤 시작한다(조율 C-06). acceptance는 자동 검사만 쓴다(`DECISIONS.md` D-03). BOOT-1(`docs/COMPONENT.md` 채우기)은 계획 작업이 먼저 끝낸다(조율 C-09).

| milestone | task | 내용 | scope(glob) | 읽을 spec |
|---|---|---|---|---|
| M1 코어 | OPS-1 골격 | 패키지, `pyproject.toml`, requirements, `Makefile`, `.gitignore`, 설정 로더, 시계·`iso_ms`, JSON 로그, `/healthz`만 있는 HTTP 앱, verify에 `unit` 추가 | `src/**`, `config/**`, `tests/**`, `pyproject.toml`, `requirements*.txt`, `Makefile`, `.gitignore`, `.env.example`, `agent/config.yaml` | 01, 07, 08 |
| | OPS-2 Payload | 입력 파서 6종, Conveyor Control·Alarm Event 생성, 스펙트럼 패널 변환 | `src/**`, `tests/**` | 02, AGREEMENTS |
| | OPS-3 판단 로직 | LineTracker, Interlock, AlarmManager, 결합(`join.py`), StateStore (MQTT·DB 없이 가짜로) | `src/**`, `tests/**` | 01, 03, 04 1절 |
| M2 저장과 분석 | OPS-4 DB | `db/schema.sql`, DB 스레드(쓰기·배치·요약·재연결), Docker fixture, verify에 `docker` 추가 | `db/**`, `src/**`, `tests/**`, `Makefile`, `agent/config.yaml` | 05, 08 |
| | OPS-5 상관분석 | `correlation.py`와 DB 스레드 주기 작업 | `src/**`, `tests/**` | 04 2절, 05 |
| M3 연동 | OPS-6 MQTT와 워커 | paho client, 도메인 워커, 앱 조립(lifespan), 운영자 명령 경로, Docker 연동 테스트(C-04~C-06) | `src/**`, `tests/**` | 01, 02, 03 |
| | OPS-7 HTTP API | `/readyz`, `/api/snapshot`, `/api/images`, `/api/conveyor`, 갱신 지연 테스트(C-08) | `src/**`, `tests/**` | 06, 08 |
| M4 화면과 패키징 | OPS-8 Dashboard 화면 | `web/static/`(index.html, app.js, plot.js, style.css) | `src/factory_operations/web/static/**`, `tests/**` | 06, `docs/WIREFRAME.html` |
| | OPS-9 컨테이너 | Dockerfile, `.dockerignore`, `compose.yaml`, `scripts/fake_feed.py`, `scripts/smoke.py`, 테스트 이미지 fixture, verify에 `smoke` 추가, `docs/COMPONENT.md` 실행 절 갱신 | `Dockerfile`, `.dockerignore`, `compose.yaml`, `scripts/**`, `tests/**`, `Makefile`, `agent/config.yaml`, `docs/COMPONENT.md` | 07, 08 |
| M5 계약 채택 | OPS-10 `contract_ref` | PdM Result·PdM Spectrum·Alarm Event가 Shared에 확정된 뒤 그 commit을 채택하고, 확정본과 이 spec의 차이를 고친다(조율 C-05) | `SHARED_CONFIG.json`, `src/**`, `tests/**`, `docs/spec/**` | AGREEMENTS 끝 절 |
| M6 사람 확인 | HUM-1 (`owner: human`) | Dashboard 확인 M-01~M-10 | 없음 | 08 6절 |

- 최종 분해·순서·scope는 `docs/plan/00-overview.md` 2절이다(`DECISIONS.md` D-37). OPS-3·4·7·9를 A·B로 나누고, 흐름 연동 테스트가 `/readyz`와 스냅숏을 쓰므로 HTTP API(OPS-6)를 MQTT 조립(OPS-7A)보다 먼저 하며, 예시 이미지 fixture는 OPS-6이 만든다.
- M5는 Shared DOCUMENT_CHANGE merge가 착수 조건이다. 그 전에 M4까지 끝나도 된다. PdM 확정본이 이 spec의 가정과 다르면 OPS-10에서 맞춘다(`AGREEMENTS.md` A-05·A-06).
- 발견된 결함은 해당 영역의 수정 task로 추가한다. 사람 task에서 발견한 문제도 같다.
