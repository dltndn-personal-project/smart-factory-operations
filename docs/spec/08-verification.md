# 08 검증

> 목적: 테스트 전략, 영역별 테스트, 과제 성능 기준(Dashboard 5초)과 Interlock 지연의 측정 방법, `agent/config.yaml` `verify` 명령과 추가 시점, 사람 확인 목록을 정한다.
> 읽어야 할 때: 모든 구현 task의 acceptance를 정할 때, verify를 추가할 때, 사람 task(HUM-1).

## 1. 원칙

- task acceptance는 `command`·`artifact`·`metric`만 쓴다. 사람 확인은 6절 목록으로 모아 M6의 사람 task에서 한 번 한다(`DECISIONS.md` D-03).
- 판단 로직(Interlock, Alarm, 결합, 상관분석, 스냅숏)은 가짜 시계·가짜 발행기·가짜 DB 싱크로 단위 테스트한다. 실제 시간을 기다리는 것은 Docker 연동 테스트와 smoke뿐이다.
- Docker가 없거나 이미지를 받을 수 없으면 해당 테스트는 **실패**한다. 건너뛰어 통과로 만들지 않는다.
- 무작위 데이터는 seed를 고정한다.
- 이 맥에서 확인한 도구(2026-09-27): Python 3.12.13(`python3`, venv·pip 있음, uv 없음), Docker 28.3.0 + Compose v2.38.1(Docker Desktop, arm64), GNU Make 3.81, Node 23.11(쓰지 않음), `gh` 2.20.2, `codex-cli` 0.155.0-alpha.16.4. 호스트에 `mosquitto`·`psql`은 없다(컨테이너 안의 것을 쓴다).

## 2. 도구와 `Makefile`

저장소 루트 `Makefile`(OPS-1이 만들고 task가 대상을 추가한다. `07-runtime.md` 6절의 `run`·`feed`도 여기 있다):

| 대상 | 하는 일 |
|---|---|
| `venv` | `.venv/.installed`가 `requirements*.txt`보다 오래됐거나 없으면 `python3 -m venv .venv && .venv/bin/python -m pip install -q --disable-pip-version-check -r requirements-dev.txt`, `src/` 경로 `.pth` 작성(07 2절), `touch .venv/.installed` |
| `test` | `venv` 후 `.venv/bin/python -m pytest -q -m "not docker" tests` |
| `docker-test` | `venv` 후 `.venv/bin/python -m pytest -q -m docker tests` |
| `smoke` | `venv` 후 `.venv/bin/python scripts/smoke.py` |

- `pyproject.toml` `[tool.pytest.ini_options]`: `pythonpath = ["src"]`, `testpaths = ["tests"]`, `markers = ["docker: Docker로 Mosquitto·TimescaleDB를 띄우는 연동 테스트"]`.
- 공용 fixture(`tests/conftest.py`): `FakeClock`, `FakePublisher`(`publish` 호출을 `(topic, payload, qos, retain)` 목록으로, `connected` 조절), `FakeDbSink`(DB 큐 작업 목록), `tmp_image_root`(`products/P-00000001.jpg` 복사본), `payload_examples`(`tests/fixtures/payloads/*.json`: Shared INTERFACES 예시 5개, PdM 아키텍처 6.2절 예시, 스펙트럼 예시 3종). Sensor Vibration 예시는 원문 배열에 설명 문자열(`"… 1000개"`)이 있어 그대로 쓸 수 없으므로, 원문의 스칼라 필드와 seed 고정 난수 축별 1000개(소수 4자리)로 만든 파일을 쓴다. 나머지 예시는 원문 그대로다.
- Docker fixture(`tests/docker/conftest.py`, 모두 `@pytest.mark.docker` 테스트에서만):
  - 호스트 포트: 테스트가 빈 포트를 골라(`socket.bind(("127.0.0.1", 0))`) `-p 127.0.0.1:<port>:<컨테이너 포트>`로 고정한다. Docker 임의 포트(`-p 127.0.0.1::1883`)는 `docker restart` 뒤 새로 배정되어 재연결 테스트가 옛 포트를 보게 된다(`DECISIONS.md` D-43). 재시작 테스트(`test_db_writer.py` DB 재시작, `test_broker_restart.py`)는 세션 컨테이너를 흔들지 않도록 자기 컨테이너를 쓴다.
  - `mqtt_broker`(session): `docker run -d --rm --name fops-test-mqtt-<hex8> -p 127.0.0.1:<port>:1883 eclipse-mosquitto:2.1.2-alpine mosquitto -c /mosquitto-no-auth.conf`, TCP 연결이 될 때까지 최대 10초.
  - `timescale_db`(session): `docker run -d --rm --name fops-test-db-<hex8> -e POSTGRES_USER=factory -e POSTGRES_PASSWORD=factory -e POSTGRES_DB=factory -p 127.0.0.1:<port>:5432 -v <저장소>/db/schema.sql:/docker-entrypoint-initdb.d/100_factory_operations.sql:ro timescale/timescaledb:2.30.1-pg17`. psycopg 연결과 `schema_info` 버전 1 확인이 될 때까지 최대 60초.
  - `clean_db`(function): `TRUNCATE sensor_chunk, line_status_change, product, inspection, equipment_state, alarm, control RESTART IDENTITY`.
  - `running_app`(function): 실제 조립(DB 스레드, 워커, paho client, uvicorn을 스레드에서 `127.0.0.1`의 빈 포트로)으로 앱을 띄우고 `/readyz`가 200이 될 때까지(최대 15초) 기다린 뒤 base URL을 준다. `IMAGE_ROOT`는 `tmp_image_root`. 끝나면 `01-core.md` 7절 종료 순서로 멈춘다.
  - `harness`: 테스트용 paho client(발행·구독, 수신 메시지를 `(time.monotonic(), topic, payload)`로 기록). 구독은 SUBACK을 받은 뒤 반환한다. QoS 1 발행은 `wait_for_publish()`로 PUBACK까지 기다린다.
  - `wait_snapshot(pred, timeout)`: `/api/snapshot`을 0.1초 간격으로 불러 조건이 참이 될 때까지 기다린다. 선행 메시지의 처리를 확인한 뒤 다음 메시지를 보낼 때 쓴다(Topic이 다르면 도착 순서가 보장되지 않으므로). 예: Line Status를 보낸 뒤 `line.fault_level == 3`이고 `interlock.reference_time`이 그 timestamp인지, STOP 결과를 보낸 뒤 `interlock.pending_stop == null`인지.
  - 컨테이너는 id로만 지운다(`docker rm -f <id>`). 이름 패턴으로 지우지 않는다.

## 3. 영역별 테스트

### 3.1 코어 (`tests/unit/test_config.py`, `test_clock.py`, `test_log.py`)

- 설정: 기본값 로드, overlay 깊은 병합, 환경 변수 우선, 모르는 키·범위 밖 값(예: `interlock.pending_timeout_s: 0`, `correlation.default_lag_s: 40`)이 키 경로와 함께 종료 코드 2.
- `iso_ms`: 밀리초 3자리, 버림(`…59.9999`가 다음 초로 올라가지 않음), `Z`, 정규식. `parse_ts`: 정규식 밖 입력(`…13Z`, `…13.4Z`, `+00:00`) 거부.
- 로그: 같은 (event, topic, reason) 11번이 10초 안에 오면 한 줄, 10초 뒤 다음 줄에 `suppressed: 10`.

### 3.2 Payload (`test_payloads.py`)

- Shared 예시 5개와 PdM 예시가 받아지고 값이 같다. 각 표(02 3.2~3.7절)의 필드를 하나씩 빼거나 틀리게 하면 정해진 사유(`missing_field:<이름>`, `invalid_field:<이름>`, `topic_mismatch`, `unsupported_schema_version`, `invalid_json`)로 거부된다. 선택 필드는 틀려도 받고 null이 된다.
- Line Status `online:false`(다른 필드 없음) 받음. `last_command.result`가 틀리면 `last_command`만 null.
- Vision Result에서 `confidence`·`bbox`·`gradcam_path` 키가 없어도 받음.
- 스펙트럼: (a) `spectrum_x/y/z` + `freq_step_hz` → 패널 1개·계열 3개, x_step 1.0 Hz (b) + `envelope_y` → 패널 2개 (c) 간격 필드 없음 → `x_unit: "bin"` (d) 배열 없음 → `no_series` (e) 300 KB → `too_large`.
- 생성: `build_conveyor`·`build_alarm`의 키 집합과 값이 `AGREEMENTS.md` A-02·A-03 예시 형식과 같고, timestamp가 정규식에 맞으며 `command_id`가 UUID4다.
- 이미지 경로: `products/../x.jpg`, `/data/products/a.jpg`, `products/.P-1.jpg.tmp`, `gradcam/a.jpg`(products 자리), `products/a.gif` 거부.

### 3.3 판단 (`test_line.py`, `test_interlock.py`, `test_alarm.py`)

- LineTracker: 1.2절 규칙. 기동 뒤 첫 `RUNNING`이 기준 시각을 잡음, `STOPPED → RUNNING`과 `offline → RUNNING`이 기준 시각을 새로 잡음, 1초 주기 메시지는 `line_status_change`를 만들지 않음, `fault_changes`는 값이 바뀔 때만 늘어남.
- `fault_changes`: 가짜 시계로 Fault Level을 700초 동안 바꾸지 않아도 `fault_level_at(현재)`가 그 값이다(오래된 변화점 하나 보존).
- `03-control.md` 6절 시나리오 S-01~S-12, L-01~L-11 전부.

### 3.4 분석 (`test_join.py`, `test_correlation.py`)

- `fault_level_at`: 변화점과 같은 timestamp이면 그 값(≤), 첫 변화점 이전은 null.
- `health_index_at_time`: 차가 정확히 `max_gap_s`이면 붙고 1 ms 넘으면 null, 미래 결과(`timestamp > vision.timestamp`)는 쓰지 않음, 결과가 없으면 null이고 `sensor_id`는 라인 센서.
- 상관분석 합성 데이터(seed 고정): 설비 점수 0.5초 간격 600초, 30초마다 무작위 수준으로 바뀌는 계단. 제품 2초 간격, 불량 확률 = `0.05 + 0.6 × score(t − 13)`. 기대: `best.lag_s`가 12~14, `at_default.pearson > 0.3`. 표본 19개 → `insufficient_samples`, 모두 양품 → `single_class`, 점수 상수 → `constant_score`. `bins`가 30초 구간으로 나뉘고 각 `defect_rate`가 직접 센 값과 같다. |Pearson|이 같은 두 lag 중 작은 lag가 `best`.

### 3.5 HTTP와 스냅숏 (`test_snapshot.py`, `test_api.py`, `test_static.py`)

- 스냅숏: `pdm.status`가 `age_s` 2.0에서 `LIVE`, 2.1에서 `STALE`, `before_restart` 판정, `line.status` `NONE`/`OFFLINE`/`STALE`/`LIVE`, 진동 구간 min/max(알려진 배열, 샘플 수 < 구간 수 경우 포함), 목록 길이 상한, 모든 시각 필드가 정규식에 맞음.
- API(FastAPI `TestClient`, 가짜 StateStore·가짜 워커): `/healthz` 200, `/readyz` 503(끊김)·200, `/api/snapshot`의 `Cache-Control: no-store`, `/api/images` 200(`image/jpeg`)·400(경로 형식)·404(없음), `/api/conveyor` 202·422·503·504.
- 정적 파일: `index.html`에 `06-dashboard.md` 5절 화면 칸의 id(`line`, `pdm`, `vibration`, `spectrum`, `quality`, `correlation`, `alarms`, `controls`)가 있다. `app.js`에 `const POLL_INTERVAL_MS = 1000;`이 있다. 정적 파일에 `http://`·`https://` 외부 URL이 없다.

### 3.6 Docker 연동 (`tests/docker/`)

- `test_schema.py`(C-03): 테이블 8개·view `defect_result`·hypertable `sensor_chunk`·`schema_info` 버전 1. `docker exec -i <db> psql -v ON_ERROR_STOP=1 -U factory -d factory < db/schema.sql`을 한 번 더 실행해 종료 코드 0.
- `test_db_writer.py`: 2절 표의 작업마다 행 확인, 중복 무시, 센서 25개를 넣으면 2번 이상의 배치로 모두 기록. DB 컨테이너 `docker restart` 뒤 `db_ok`가 false가 되었다가 15초 안에 true로 돌아오고 이후 쓰기가 된다.
- `test_app_flow.py`(C-04, C-06): `running_app`에 harness가 Line Status(retain, `RUNNING`, `fault_level 3`)를 보내고 `wait_snapshot`으로 반영을 확인한 뒤 센서 chunk 20개(`seq` 연속), PdM Result 4개(`NORMAL`), Product Created·Vision Result 2쌍을 보낸다. 5초 안에: `sensor_chunk` 20행 `fault_level = 3`, `equipment_state` 4행, `product`·`inspection` 2행이고 `health_index_at_time`이 캡처 시각 이하 가장 최근 PdM 값, `line_status_change` 1행. 이어서 `CRITICAL` → harness가 받은 STOP의 `command_id`로 Line Status(`STOPPED`, `last_command` `APPLIED`)를 보내면 3초 안에 `control.result = 'APPLIED'`.
- `test_interlock_latency.py`(C-05): 4.2절.
- `test_broker_restart.py`: Mosquitto 컨테이너 `docker restart` → 15초 안에 `/readyz` 200, 이후 보낸 PdM Result가 `equipment_state`에 기록.
- `test_dashboard_latency.py`(C-08): 4.1절.

### 3.7 smoke (`scripts/smoke.py`, C-09)

1. `docker build -t factory-operations:smoke --build-arg GIT_COMMIT=$(git rev-parse HEAD) .` 빌드 시간을 출력만 한다.
2. 이름 접미사 `<hex8>`로 network `fops-smoke-<hex8>`, volume `fops-smoke-img-<hex8>`을 만들고 `image-seed`와 같은 방식(07 4절)으로 예시 이미지를 넣는다.
3. Mosquitto(`--network-alias mosquitto`, `-p 127.0.0.1::1883`), DB(`--network-alias db`, schema initdb 마운트)를 띄우고 `docker exec <db> pg_isready -h 127.0.0.1 -U factory -d factory`가 성공할 때까지 최대 60초.
4. `docker run -d` Operations(`MQTT_URL=mqtt://mosquitto:1883`, `DATABASE_URL=postgresql://factory:factory@db:5432/factory`, `-v <volume>:/data:ro`, `-p 127.0.0.1::8080`). 이 명령이 끝난 시각부터 `/readyz`를 0.5초 간격으로 부르고 200까지 30초 이하인지 확인한다. `/healthz`의 `commit`이 빌드 인자와 같다.
5. harness: Line Status(retain, `RUNNING`, `fault_level 9`) → PdM `CRITICAL` → 2초 안에 Alarm Event(A-02 필드)와 STOP(A-03 필드) 수신 → Line Status `STOPPED`·`APPLIED` 응답 → Product Created·Vision Result(`P-00000001`) → 5초 안에 `/api/snapshot` `inspections`에 그 제품, `/api/images/products/P-00000001.jpg` 200 `image/jpeg`.
6. `docker exec <db> psql -tAc`로 `control.result = 'APPLIED'`, `alarm` 1행, `inspection` 1행 확인.
7. 성공·실패와 무관하게 컨테이너·network·volume을 id·이름으로 지운다. 실패하면 Operations 컨테이너 로그 마지막 100줄을 출력하고 종료 코드 1.

## 4. 성능 기준 측정

### 4.1 Dashboard 데이터 5초 이내 갱신 (Shared 2절, C-08)

**정의**: 입력 이벤트 E가 broker에서 나온 뒤 브라우저 화면 데이터에 반영될 때까지의 최대 시간이 5초 이하다.

**측정 방법**: 같은 broker를 구독하는 측정 도구가
1. E를 받은 시각 `t_rx(E)`를 자기 `monotonic`으로 기록한다.
2. `GET /api/snapshot`을 0.2초 간격으로 부르고, 응답을 받은 시각에 아래 반영 조건이 처음 참이 된 시각을 `t_seen(E)`로 둔다.
3. `D(E) = t_seen(E) − t_rx(E) + P + r_max + R`.
   - `P = 1.0`초: 브라우저 polling 간격(`app.js` `POLL_INTERVAL_MS`, 3.5절이 고정을 검사). 반영된 스냅숏이 생긴 뒤 브라우저가 다음 요청을 시작하기까지의 최악 대기다.
   - `r_max`: 측정 중 잰 `/api/snapshot` 응답 시간(요청 시작 → 응답 끝)의 최댓값. 브라우저 요청이 끝나기까지의 시간이다. 판정 조건에 `r_max ≤ 0.5`초를 함께 둔다. 이 조건이 참이면 브라우저 요청이 1초 간격 안에 끝나므로 "이전 요청이 진행 중이면 건너뜀"(`06-dashboard.md` 5절)이 일어나지 않는다.
   - `R = 0.2`초: 브라우저 렌더링 예산. 자동으로 재지 않고(headless 브라우저 없음, D-34) `?debug=1` 화면의 마지막 렌더링 시간이 200 ms 미만인지 사람이 M-02에서 확인한다.
   - 시작점 `t_rx`는 측정 도구의 수신 시각이라 broker가 메시지를 받은 시각보다 로컬 전달 지연(수 ms)만큼 늦다. Operations도 같은 broker에서 같은 시점에 받으므로 이 차이는 무시한다.
4. 판정: 모든 표본의 `max D ≤ 5.0`초이고 `r_max ≤ 0.5`초. p50·p95·max를 출력한다.

| 이벤트 | 반영 조건 | 경로 |
|---|---|---|
| Line Status(`fault_level` 변경) | `line.timestamp ≥ E.timestamp` | 메모리 |
| PdM Result | `pdm.timestamp ≥ E.timestamp` | 메모리 |
| PdM Spectrum | `spectrum.timestamp ≥ E.timestamp` | 메모리 |
| Sensor Vibration | `vibration.timestamp ≥ E.timestamp` | 메모리 |
| Vision Result | `inspections`에 `E.product_id`가 있고 `production.inspected`가 E 이전 값보다 큼 | DB 요약 |
| Alarm Event | `alarms`에 `E.alarm_id` | DB 요약 |
| 명령 결과(Line Status `last_command`) | `controls`에 같은 `command_id`이고 `result`가 null이 아님 | DB 요약 |

예상 최악값: DB 요약 경로 = 워커(0.1초 이하) + DB 쓰기 + 요약 주기(2.0초) + 측정 간격(0.2초) → `t_seen − t_rx` 약 2.4초, `D` 약 2.4 + 1.0 + 0.1 + 0.2 = 3.7초.

**Component 테스트**(`test_dashboard_latency.py`): `running_app`에 60초 동안 Line Status 변경 5초마다(12개), 센서 0.1초마다, PdM Result 0.5초마다, 스펙트럼 1초마다, Product·Vision 2초마다(30개), `CRITICAL` 1회(Alarm·STOP)와 명령 결과 1회를 보내고 위 방법으로 모든 표본을 잰다. `max D ≤ 5.0`.

**시스템 수준**: integration이 같은 방법(같은 반영 조건, `P = 1.0`)으로 네 Component를 함께 띄운 환경에서 잰다(`AGREEMENTS.md` A-10, Shared 19.1).

### 4.2 Interlock 지연 (C-05, 이 Component의 목표)

- `test_interlock_latency.py`: 5회 반복. 매회 harness가 Line Status `STOPPED` → `RUNNING`(새 timestamp, 재가동 기준 시각)을 보내고, 그보다 나중 `timestamp`의 PdM `CRITICAL`을 발행한다. 발행 직전 `monotonic`부터 harness가 STOP을 받은 시각까지 ≤ 1.0초. 같은 회차의 Alarm Event도 받는다(서로 다른 Topic이라 수신 순서는 검사하지 않는다. 발행 순서는 단위 테스트 L-07). STOP을 받으면 `APPLIED`·`STOPPED`로 응답하고 `wait_snapshot`으로 `pending_stop == null`과 `line_state == STOPPED`를 확인한 뒤 다음 회차로 간다. `RUNNING`을 보낸 뒤에도 `reference_time`이 새 값인지 확인하고 PdM을 보낸다.
- 측정은 broker 왕복(발행 → Operations → broker → harness)을 포함하므로 실제 처리 시간보다 크다.

## 5. verify 명령과 추가 시점

각 영역을 처음 만드는 task가 `agent/config.yaml`의 `verify`에 아래 명령을 그대로 추가한다(`DECISIONS.md` D-05). 먼저 실제로 실행해 통과를 확인한다.

| 순서 | 추가하는 task | 항목 |
|---|---|---|
| 기존 | | `{name: agent-files, run: "python3 agent/core/tools/validate.py"}` |
| 1 | OPS-1 | `{name: unit, run: "make test"}` |
| 2 | OPS-4 | `{name: docker, run: "make docker-test"}` |
| 3 | OPS-9A | `{name: smoke, run: "make smoke"}` |

- 전제: Docker Desktop이 실행 중이다(`HUMAN.md` H-1). 처음에는 이미지 받기와 빌드 때문에 수 분 걸린다(`check_timeout` 1800초 안).
- `docker` 대상은 OPS-4 이후 task마다 테스트가 늘어난다. 한 번 실행 약 3분(Dashboard 지연 60초 포함)을 넘지 않게 한다.

## 6. 수동 확인 목록 (사람 task HUM-1)

준비: `docker compose up -d --build`, `make feed`(07 5절), 맥북 Chrome으로 `http://localhost:8080`. 시나리오가 약 3분 걸린다. 항목마다 통과/실패와 메모를 task 결과에 남긴다.

| ID | 확인 | 통과 기준 |
|---|---|---|
| M-01 | 첫 화면 | 5초 안에 모든 칸이 보이고 콘솔 오류가 없다. 개발자 도구 Network에 외부 도메인 요청이 없다 |
| M-02 | 갱신 | 상단 "N초 전 갱신"이 0~1초를 오간다. 진동·스펙트럼·PdM 추세가 매초 움직이고 화면이 깜빡이거나 스크롤이 튀지 않는다. `http://localhost:8080/?debug=1`의 마지막 렌더링 시간이 1분 동안 200 ms 미만이다(4.1절 `R`) |
| M-03 | 라인 | Current Fault Level이 시나리오대로 0 → 3 → 6 → 9로 바뀌고 "평가용" 표기가 보인다. RUNNING/STOPPED 색이 구별된다 |
| M-04 | 설비 상태 | NORMAL → CAUTION → WARNING 배지 색과 HI·Anomaly Score 값이 바뀌고, 추세 그래프에 경계선 80/60/40이 보인다. WARNING 진입 때 Alarm History에 1건 |
| M-05 | Interlock | Fault Level 9 뒤 2초 안에 CRITICAL Alarm, Conveyor STOPPED, Control History에 `INTERLOCK_CRITICAL`·`APPLIED`. 2초 뒤 PdM 칸이 회색 "마지막 판정 · N초 전"과 "라인 정지 중" 문구 |
| M-06 | 재가동 | START → CRITICAL 확인 창 → 확인 → `OPERATOR_START`·`APPLIED`, RUNNING. 새 판정 전에는 "재가동 전 판정" 문구, 약 1~2초 뒤 NORMAL. 확인 창에서 취소하면 명령이 나가지 않는다 |
| M-07 | 품질 | 최근 검사 12개 썸네일, 원본 보기, 불량 표시와 Defect Type, Confidence "—", Grad-CAM "현재 범위에서 제공하지 않음", 판정 출처 pass-through. Defect Rate가 표시된 검사 수·불량 수와 맞다 |
| M-08 | 상관관계 | 시작 직후 "표본 부족", 약 2분 뒤 계수·최대 lag·lag 곡선·구간 차트가 보인다 |
| M-09 | 끊김 표시 | `docker compose stop mosquitto` → MQTT 끊김·Line Status 수신 없음 표시, `start` 뒤 복구. `docker compose stop factory-operations` → "Operations 서버 연결 끊김", `start` 뒤 복구 |
| M-10 | 모양 | 창 폭 1280 px과 1920 px에서 칸이 겹치거나 잘리지 않는다. 어두운 테마에서 글자가 읽힌다. Safari에서도 화면이 뜬다 |

전체 시스템 시연(00 3절)은 integration의 시스템 compose로 한다. 이 목록은 가짜 입력으로 Operations 화면만 확인한다.

## 7. PLAN 반영 규칙

- 사람 task는 M6에 `owner: human`으로 두고 acceptance는 `{type: manual, how: "docs/spec/08-verification.md 6절 M-01~M-10"}` 하나다. 이 task만 manual을 쓴다.
- 사람 task에서 실패한 항목은 계획 작업이 수정 task로 추가하고, 수정 뒤 해당 항목만 다시 확인한다.
- acceptance에는 테스트 파일·테스트 이름을 command로 묶는다(예: `.venv/bin/python -m pytest -q tests/unit/test_interlock.py`).
- PR merge는 조율 agent가 CI 통과와 `finish` 통과 뒤에 한다(`DECISIONS.md` D-01).
