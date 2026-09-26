# Factory Operations & Control — Component 도메인 설명

시스템 내 책임은 Shared `docs/ARCHITECTURE.md` 4.4절과 17절(Responsibility Summary)이 기준이다. 이 파일은 그 범위 안에서 저장소 수준의 세부를 적는다. 구현 기준은 `docs/spec/`(먼저 `docs/spec/README.md`)이고, 작업 순서는 `docs/plan/`(먼저 `docs/plan/README.md`)이다. 설계의 배경과 근거는 `docs/ARCHITECTURE.md`, 화면 배치는 `docs/WIREFRAME.html`에 있다.

Agent가 계획·구현·검증할 때 참조하는 이 Component의 도메인 슬롯이다. `agent/core`의 절차는 도메인을 모르므로 도메인 지식은 이 파일에만 둔다. 사람이 리뷰한다.

## 목적과 책임

Smart Factory의 중앙 운영 Component다. MQTT로 Simulator의 센서·제품·라인 상태, PdM의 설비 상태와 스펙트럼, Vision의 검사 결과를 받아 PostgreSQL+TimescaleDB에 기록하고, 설비 상태가 `CRITICAL`이면 Conveyor에 `STOP`을 보낸다(Interlock). `WARNING`·`CRITICAL` 진입은 Alarm으로 기록·발행하고, 설비 상태와 불량의 상관관계를 계산해 브라우저 Dashboard(1초 polling)로 보여 준다. 운영자는 Dashboard에서 라인을 다시 돌린다(`START`). 완료 정의는 `docs/spec/00-overview.md` 2절 C-01~C-10이다.

## 경계

- 하지 않는 일: FFT·Feature Extraction(RMS 등)·Health Index 계산(PdM), 결함 판정·Grad-CAM(Vision), Fault Level 조작과 물리적 정지(Simulator), Ground Truth 파일 읽기와 Ground Truth를 판단 입력으로 쓰기, 자동 `START`, 시스템 compose·Broker·DB·볼륨의 실행 정의와 시스템 E2E(integration), 인증·TLS·재시도·중복 제거·HA·백업(`docs/spec/00-overview.md` 4절).
- 소유하는 데이터·자원: DB 스키마(`db/schema.sql`)와 모든 DB 기록(Operations가 DB에 쓰는 유일한 Component), Conveyor Control·Alarm Event 발행, Interlock·Alarm 규칙, 시간 결합(`fault_level`, `health_index_at_time`)과 상관분석, Dashboard(HTTP 8080). Image Storage는 읽기만 한다(`:ro`).
- Integration Component가 아니다. 저장소의 `compose.yaml`과 `scripts/fake_feed.py`는 이 Component 단독 개발·사람 확인용이다.

## 용어

| 용어 | 뜻 |
|---|---|
| Interlock | 판정 대상 PdM Result의 `state`가 `CRITICAL`이면 Conveyor에 `STOP`(`reason: INTERLOCK_CRITICAL`)을 보내는 규칙(`docs/spec/03-control.md` 3절) |
| 재가동 기준 시각 (`reference_time`) | `RUNNING`이 아니던 라인이 `RUNNING`이 된 Line Status의 `timestamp`. 이보다 뒤 `timestamp`의 PdM Result만 Interlock·Alarm 판단에 쓴다(03 1.2절) |
| 판정 대상 / Alarm 대상 | Interlock에 쓰는 PdM Result(라인 센서, 기준 시각 이후) / Alarm 평가에 쓰는 PdM Result(03 2절) |
| 재가동 이벤트 | 마지막으로 본 `conveyor`가 `STOPPED`였다가 `RUNNING`이 됨(사이의 offline 허용). 라인 센서 Alarm 이전 상태를 비운다 |
| 대기 중 STOP (`pending`) | 결과(Line Status `last_command`)를 기다리는 STOP. 5초 뒤 시간 초과 |
| 라인 센서 | Line Status의 `sensor_id`(없으면 설정 `line.sensor_id` = `motor01`) |
| stale | 수신 뒤 일정 시간(PdM 2초, Line Status·스펙트럼 3초, 진동 1초)이 지나 현재 값이 아닌 표시(06 4절) |
| 시간 결합 | chunk에 Line Status as-of `fault_level`, 검사에 캡처 시각 기준 `health_index_at_time`을 붙이는 규칙(04 1절) |
| 스냅숏 | `GET /api/snapshot`의 JSON. 화면과 갱신 지연 측정이 쓴다(06 3절) |
| StateStore | 워커·DB 스레드가 쓰고 HTTP가 읽는 메모리 상태(01 3절) |

## 구조

task `scope` glob의 기준이다. 경로별 파일은 해당 task가 만든다(`docs/plan/00-overview.md` 2절, 세부 배치는 `docs/spec/01-core.md` 1절).

| 경로 | 역할 |
|---|---|
| `src/factory_operations/` | Python 프로세스 하나. `config.py`(설정), `clock.py`(시계·`iso_ms`), `log.py`(JSON 로그), `app.py`(조립·수명 주기), `__main__.py`(`serve`) |
| `src/factory_operations/mqtt/` | `client.py`(paho를 import하는 유일한 모듈), `topics.py`, `payloads.py`(입력 파서 6종과 발행 Payload 생성. PdM Result·PdM Spectrum 형식 의존은 이 파일에 모은다) |
| `src/factory_operations/domain/` | `state.py`(StateStore), `line.py`, `interlock.py`, `alarm.py`, `join.py`, `correlation.py`, `worker.py`. 순수 로직, 가짜 시계·발행기·DB 싱크로 단위 테스트 |
| `src/factory_operations/store/` | `db.py`(DB 스레드, psycopg를 import하는 유일한 모듈), `sql.py`(SQL 문자열), 쓰기 작업 타입 |
| `src/factory_operations/web/` | `api.py`(FastAPI를 import하는 유일한 모듈), `snapshot.py`, `images.py`, `static/`(index.html, app.js, plot.js, style.css) |
| `db/schema.sql` | DDL 한 파일(스키마 버전 1). integration이 initdb로 적용한다 |
| `config/default.yaml` | 모든 설정 키의 기본값 |
| `tests/unit/`, `tests/docker/`, `tests/fixtures/` | 단위 테스트, Docker(Mosquitto·TimescaleDB) 연동 테스트(마커 `docker`), Payload 예시·예시 이미지 |
| `scripts/` | `smoke.py`(이미지 smoke), `fake_feed.py`(Simulator·PdM·Vision 흉내) |
| `Dockerfile`, `.dockerignore`, `compose.yaml`, `Makefile`, `pyproject.toml`, `requirements*.txt`, `.env.example`, `.gitignore` | 빌드·개발용 compose·검증 진입점 |
| `docs/` | spec, plan, 리뷰 기록, 아키텍처 초안, 와이어프레임, 이 파일 |

## 외부 의존과 계약

- 교차 Component 항목(MQTT Topic·Payload·QoS, DB 스키마와 적용 방식, 실행 조건, 관찰 지점)은 `docs/spec/AGREEMENTS.md`가 구현 기준이다. Shared에 확정된 Interface(Sensor Vibration, Product Created, Vision Result, Conveyor Control, Line Status, PdM Result, PdM Spectrum, Alarm Event)와 CONVENTIONS는 Shared가 원본이다. 계약 기준 Shared commit(`contract_ref`)은 `cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8`이다(OPS-10). Alarm Event는 이 Component가 생산자이고 `AGREEMENTS.md` A-02가 Shared 확정본과 같다. PdM Result·PdM Spectrum의 Operations 해석은 A-05·A-06이다.
- `SHARED_CONFIG.json`의 `contract_ref`는 Shared PR #7(PdM Result·PdM Spectrum·Alarm Event 확정)의 merge commit `cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8`이다(OPS-10, 조율 C-05, spec D-04·D-48). task의 `contract` 문서는 `agent/core/process/90-shared.md` 1절로 이 commit을 지정해 읽는다.
- 그 외 의존: MQTT Broker(Mosquitto 2.1.2, `eclipse-mosquitto:2.1.2-alpine`), PostgreSQL 17 + TimescaleDB 2.30.1(`timescale/timescaledb:2.30.1-pg17`), Image Storage named volume(읽기 전용), Python 3.12와 FastAPI·uvicorn·paho-mqtt·psycopg·numpy·scipy·pydantic·PyYAML(버전은 `docs/spec/07-runtime.md` 7절), Docker(연동 테스트·smoke·실행), 맥북 Chrome(화면 확인 기준 브라우저). 외부 CDN·Node 빌드는 쓰지 않는다.

## 실행·검증 환경

실행 방법의 원본은 `docs/spec/07-runtime.md`(설정 키·환경 변수 1절, 로컬 실행 2절, Dockerfile 3절, 개발용 compose 4절, 가짜 입력 5절, Makefile 6절)다. 구현이 끝나면 OPS-9B가 이 절을 실제 실행 방법으로 갱신한다.

- 로컬 실행(계획): `make venv` → `docker compose up -d mosquitto db` → `.venv/bin/python -m factory_operations serve`(http://localhost:8080) → `.venv/bin/python scripts/fake_feed.py`.
- 컨테이너: 저장소 루트 `Dockerfile`, 컨테이너 포트 8080, 필수 환경 변수 `MQTT_URL`, `DATABASE_URL`, `IMAGE_ROOT`. 기동 확인은 `/healthz`(프로세스), 준비 확인은 `/readyz`(MQTT 연결 + DB 스키마 확인)다(`docs/spec/AGREEMENTS.md` A-09).
- 필요한 도구: Python 3.12(venv·pip), Docker Desktop, GNU Make, `gh`(로그인). 호스트의 `mosquitto`·`psql`은 쓰지 않는다(컨테이너 안의 것을 쓴다).
- 공통 검증 명령은 `agent/config.yaml`의 `verify`에 둔다. 영역별로 추가할 명령(`make test`, `make docker-test`, `make smoke`)과 시점은 `docs/spec/08-verification.md` 5절이다.
