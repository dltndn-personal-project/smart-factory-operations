# 01 코어: 프로세스 구조, 상태, 설정, 시계

> 목적: 모듈 구조, 스레드와 큐, StateStore, 설정 로딩, 시계·timestamp, 로그, 수명 주기를 정한다.
> 읽어야 할 때: 패키지 골격(OPS-1), 스레드 사이 경계를 건드릴 때, 설정 키를 추가할 때.

## 1. 저장소 구조

```text
factory-operations/
├─ src/factory_operations/
│  ├─ __main__.py          # python -m factory_operations serve
│  ├─ config.py            # 설정 로딩(4절)
│  ├─ clock.py             # Clock, iso_ms, parse_ts (5절)
│  ├─ log.py               # JSON 로그, 같은 사유 억제(6절)
│  ├─ app.py               # 조립과 수명 주기(7절)
│  ├─ mqtt/                # client.py(paho만 import), topics.py, payloads.py (02)
│  ├─ domain/              # state.py, line.py, interlock.py, alarm.py, join.py, correlation.py, worker.py (03, 04)
│  ├─ store/               # db.py(DB 스레드), sql.py(SQL 문자열) (05)
│  └─ web/                 # api.py, snapshot.py, images.py, static/ (06)
├─ db/schema.sql           # DDL (05 3절)
├─ config/default.yaml     # 모든 설정 키의 기본값
├─ tests/unit/, tests/docker/, tests/fixtures/
├─ scripts/smoke.py, scripts/fake_feed.py
├─ Dockerfile, .dockerignore, compose.yaml, Makefile, pyproject.toml, requirements.txt, requirements-dev.txt, .env.example
└─ docs/, agent/           # 기존
```

`mqtt/client.py`만 paho를, `store/db.py`만 psycopg를, `web/api.py`만 FastAPI를 import한다. `domain/`과 `mqtt/payloads.py`, `web/snapshot.py`는 순수 로직이라 가짜 시계·가짜 발행기·가짜 DB 싱크로 단위 테스트한다.

## 2. 스레드와 큐

| 스레드 | 하는 일 | 입력 | 출력 |
|---|---|---|---|
| main (uvicorn, asyncio) | HTTP 응답 | HTTP 요청 | StateStore 읽기, 운영자 명령을 inbound 큐에 넣기 |
| paho 네트워크 (`loop_start`) | MQTT 송수신 | broker | 수신 메시지를 inbound 큐에 넣기만 한다 |
| 도메인 워커 (1개) | 파싱, 상태 갱신, Interlock·Alarm 판정, 발행, DB 쓰기 요청 | inbound 큐 | StateStore 쓰기, paho `publish`, DB 큐 |
| DB (1개) | DB 쓰기, 센서 배치, 요약·상관분석 주기 작업 | DB 큐 | DB, StateStore 쓰기(요약·상관분석 결과) |

- inbound 큐: `queue.Queue(maxsize=2000)`. 항목은 `Inbound(topic, payload: bytes, retain, recv_wall, recv_mono)` 또는 `OperatorCommand(command, future)`. 가득 차면 넣지 않고 버린 수를 세어 로그(6절)한다.
- 워커 루프: `get(timeout=0.1)`로 꺼내 처리하고, 꺼낸 것이 없어도 0.1초마다 `tick(now)`를 부른다(대기 중 STOP 시간 초과, `03-control.md` 3절).
- DB 큐: `queue.Queue(maxsize=10000)`. 항목은 `05-storage.md` 2절의 쓰기 작업. 가득 차면 버리고 센다. DB가 느리거나 끊겨도 워커(Interlock)는 막히지 않는다.
- JSON 파싱은 워커에서 한다. paho 콜백에서 하지 않는다.

## 3. StateStore

`domain/state.py`. `threading.Lock` 하나로 보호한다. 워커와 DB 스레드가 쓰고 HTTP가 읽는다. HTTP는 락 안에서 필요한 값의 참조·얕은 복사만 꺼내고(`snapshot_view()`), JSON 만들기와 진동 솎기는 락 밖에서 한다. 저장된 객체(파싱된 메시지, numpy 배열)는 만든 뒤 바꾸지 않는다.

| 항목 | 쓰는 쪽 | 내용 |
|---|---|---|
| `line` | 워커 | LineTracker 상태(`03-control.md` 1절): 최신 Line Status와 수신 시각, `line_state`, `reference_time`, `fault_level` 변화점 |
| `pdm_latest[sensor_id]` | 워커 | 마지막 PdM Result와 수신 시각(wall, mono) |
| `pdm_history[sensor_id]` | 워커 | PdM Result를 `timestamp` 순으로 최근 `pdm.history_s`(120초)만. 결합(04 1절)과 화면 추세에 쓴다 |
| `spectrum_latest` | 워커 | 라인 센서의 마지막 스펙트럼 패널(`02-mqtt.md` 3.6절)과 수신 시각 |
| `vibration_ring` | 워커 | 라인 센서 chunk 최근 `dashboard.vibration_window_chunks`(10)개. 축별 numpy float32 배열 |
| `interlock` | 워커 | 대기 중 STOP, 마지막 trigger, 판정 대상 결과(03 3절) |
| `mqtt_connected` | paho 콜백 | bool. 단순 대입이라 락 없이 쓴다 |
| `db_ok` | DB 스레드 | 연결되어 있고 스키마 확인(05 4절)을 통과했는지 |
| `summary` | DB 스레드 | 요약 조회 결과(05 5절)와 조회 시각 |
| `correlation` | DB 스레드 | 상관분석 결과(04 2절) |
| `counters` | 모두 | 버린 메시지 수(Topic·사유별), 큐 초과 수 |

메모리 상태는 재시작하면 사라진다. 재시작 직후 Line Status는 retain으로 바로 받고, PdM 상태는 다음 결과부터 다시 쌓는다. 요약·상관분석은 DB에서 다시 읽으므로 이어진다.

## 4. 설정

- `config/default.yaml`(commit)이 모든 키의 기본값을 가진다. `FOPS_DEFAULT_CONFIG`로 다른 기본 파일을, `FOPS_CONFIG`로 그 위에 깊은 병합할 overlay YAML을 줄 수 있다. 그다음 환경 변수(`07-runtime.md` 1절)가 해당 키를 덮어쓴다.
- pydantic 모델(`extra="forbid"`)로 검증한다. 모르는 키, 형식 오류, 범위 밖 값은 키 경로를 담은 메시지를 stderr에 쓰고 종료 코드 2로 끝낸다.
- 키의 원본(기본값과 의미를 적은 곳):

| 절 | 원본 |
|---|---|
| `http`, `mqtt.url`, `db.url`, `paths`, `logging` | `07-runtime.md` 1절 |
| `mqtt`의 나머지 | `02-mqtt.md` 1절 |
| `line`, `interlock` | `03-control.md` 5절 |
| `join`, `correlation` | `04-analysis.md` 3절 |
| `db`의 나머지 | `05-storage.md` 6절 |
| `pdm`, `dashboard` | `06-dashboard.md` 6절 |

키를 추가하면 원본 표와 `default.yaml`을 같은 PR에서 고친다.

## 5. 시계와 timestamp

- `Clock` 프로토콜: `wall() -> datetime`(UTC aware), `mono() -> float`(초, `time.monotonic`). 실제 구현 `SystemClock`, 테스트용 `FakeClock`(`advance(s)`로 둘 다 진행).
- `iso_ms(dt) -> str`: UTC, 밀리초 3자리, 밀리초 미만 버림, `Z` 접미사. 결과가 CONVENTIONS 정규식 `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`에 맞는다. `…59.9999`가 다음 초로 올라가지 않는다.
- `parse_ts(s) -> datetime`: 위 정규식에 맞는 문자열만 받는다(아니면 `ValueError`). 수신 Payload의 timestamp는 이 함수로 검사하고, DB에는 datetime으로 넣어 ms 값이 그대로 남는다.
- 시계 영역: Payload의 `timestamp`(Simulator 호스트 시계, PdM·Vision은 그 값을 유지)와 Operations가 만드는 시각(`received_at`, `generated_at`, Conveyor Control `timestamp`, Alarm Event `raised_at`)은 다른 시계에서 나온다. 판정 규칙은 **같은 영역의 값끼리만** 비교한다. Payload timestamp끼리(재가동 기준 시각과 PdM `timestamp`, 결합), Operations 시각끼리(대기 시간 초과, stale 판정은 `mono()`). Docker Desktop에서 두 시계는 같은 VM 시계지만 이 가정에 기대지 않는다.

## 6. 로그

- stdout에 한 줄 JSON: `{"ts": iso_ms, "level": "INFO", "logger": "...", "event": "...", ...필드}`. `logging.level` 이상만 쓴다.
- 이벤트 이름: `mqtt_connected`, `mqtt_disconnected`, `message_rejected`(topic, reason, payload 앞 200바이트), `queue_overflow`, `alarm_raised`, `command_published`, `command_result`, `interlock_pending_timeout`, `db_connected`, `db_error`, `db_schema_missing`, `correlation_done`(DEBUG).
- 같은 (event, topic, reason) 조합은 10초에 한 번만 쓰고, 그 사이 억제한 개수를 다음 줄의 `suppressed` 필드로 붙인다. 센서 메시지(초당 10개)가 계속 잘못되어도 로그가 넘치지 않게 하기 위해서다. 억제는 WARNING 이상 이벤트(`message_rejected`, `queue_overflow`, `db_error` 등)에 기본으로 적용하고, INFO 이하(`alarm_raised`, `command_published`, `command_result` 등 건마다 남겨야 하는 기록)는 억제하지 않는다. 호출에서 `throttle=`로 바꿀 수 있다(`DECISIONS.md` D-47).
- Production 모니터링 스택은 두지 않는다(Shared 13절).

## 7. 수명 주기

`python -m factory_operations serve`가 설정을 읽고 `uvicorn.run(app, host=http.host, port=http.port, log_config=None, access_log=False)`를 부른다. uvicorn 로그도 6절 JSON 형식으로 나오고, 요청마다의 access 로그는 쓰지 않는다(화면이 1초마다 요청하므로). FastAPI lifespan이 다음 순서로 시작하고 반대 순서로 끝낸다.

1. 설정·로그 준비, `StateStore` 생성, 시작 로그(설정 요약, `GIT_COMMIT`).
2. DB 스레드 시작. 연결 실패여도 기동은 계속한다(05 4절).
3. 도메인 워커 시작.
4. MQTT client 시작(`connect_async`, `loop_start`). Broker가 없어도 기동은 계속한다.
5. HTTP 응답 시작. `/healthz`는 이때부터 200.

종료(SIGTERM): MQTT `disconnect`·`loop_stop` → 워커에 종료 표시를 넣고 join(2초) → DB 스레드가 남은 센서 배치를 쓰고 연결을 닫은 뒤 join(5초). 제한 시간을 넘기면 로그만 남기고 끝낸다.
