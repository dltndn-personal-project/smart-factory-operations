# 05 저장: DB 스키마, 쓰기, 요약 조회

> 목적: `db/schema.sql`의 내용과 적용 방식, DB 스레드의 쓰기·배치·재연결, Dashboard 요약과 상관분석이 쓰는 조회를 정한다. integration이 쓰는 적용 방식·검증 조회의 약속은 `AGREEMENTS.md` A-08이 원본이다.
> 읽어야 할 때: `db/schema.sql`, `store/`(OPS-4A·4B, OPS-5), 테이블·열을 바꿀 때.

## 1. 구성

- PostgreSQL 17 + TimescaleDB 2.30.1 인스턴스 **하나**, DB 하나(이름은 연결 URL로 받는다), 스키마 `public`. 시계열(Shared 5.2)과 운영 기록(Shared 5.3)을 같은 DB에 둔다(`DECISIONS.md` D-25).
- `sensor_chunk`만 hypertable이다. 나머지는 일반 테이블이다.
- 유지 기간·삭제·압축 없음. 초기화는 integration이 볼륨과 DB를 함께 지워서 한다(Shared INTERFACES ID, SIM A-09).
- Operations는 DB에 기록하는 유일한 Component다(Shared 4.4). 다른 Component에는 DB 연결 정보를 주지 않는다.

## 2. 쓰기 작업

워커가 DB 큐에 넣는 작업과 DB 스레드가 실행하는 SQL. 모든 timestamp는 datetime(UTC)으로 넘긴다. `received_at`·`recorded_at`·`observed_at`은 Operations 시각, 나머지 timestamp는 Payload 값이다.

| 작업 | 원인 | SQL | 중복·충돌 |
|---|---|---|---|
| `sensor` | Sensor Vibration | `INSERT INTO sensor_chunk (...) VALUES (...)` 배치(3절) | `ON CONFLICT (sensor_id, timestamp) DO NOTHING` |
| `line_change` | Line Status 변화(03 1.2절) | `INSERT INTO line_status_change (...)` | 없음(`id` 자동) |
| `product` | Product Created | `INSERT INTO product (...)` | `ON CONFLICT (product_id) DO NOTHING` |
| `inspection` | Vision Result | `INSERT INTO inspection (...)` | `ON CONFLICT (product_id) DO NOTHING` (같은 제품의 두 번째 결과는 버린다) |
| `equipment` | PdM Result | `INSERT INTO equipment_state (...)` | `ON CONFLICT (sensor_id, timestamp) DO NOTHING` |
| `alarm` | Alarm 생성 | `INSERT INTO alarm (...)` | 없음(`alarm_id` 새 UUID) |
| `control_issued` | Operations가 명령 발행 | `INSERT INTO control (..., origin) VALUES (..., 'operations')` | `ON CONFLICT (command_id) DO NOTHING` |
| `control_result` | Line Status로 자기 명령 결과 확인 | `UPDATE control SET result=%s, result_received_at=%s, error=%s, observed_at=%s WHERE command_id=%s AND result IS NULL` | 이미 채워졌으면 0행 |
| `control_observed` | 모르는 `command_id` 관찰 | `INSERT INTO control (..., origin) VALUES (..., 'observed')` | `ON CONFLICT (command_id) DO NOTHING` |

- `control_issued`가 아직 DB에 들어가기 전에 `control_result`가 오는 일은 없다(같은 큐, 순서대로 실행).
- 실패한 작업은 `db_error` 로그를 남기고 버린다. 재시도하지 않는다(Shared 12절).

## 3. DB 스레드

- 연결: `psycopg.connect(db.url, autocommit=True, connect_timeout=5, options="-c statement_timeout=5000")`. 연결 하나를 모든 작업·조회에 쓴다.
- 연결 뒤 **스키마 확인**: `SELECT version FROM schema_info WHERE component = 'factory-operations'`가 `1`이면 `db_ok = true`, `db_connected` INFO. 테이블이 없거나 값이 다르면 `db_ok = false`, `db_schema_missing` ERROR 로그, 연결을 닫고 재연결 규칙으로 다시 확인한다. Operations는 DDL을 직접 실행하지 않는다(`DECISIONS.md` D-26).
- 재연결: 연결이 없거나 작업 중 `psycopg.OperationalError`가 나면 연결을 닫고 `db_ok = false`. 마지막 시도에서 `db.reconnect_interval_s`(2초)가 지난 뒤 다음 작업 때 다시 연결한다. 연결이 없는 동안 꺼낸 작업은 버리고 센다(쌓아 두지 않는다).
- 루프: DB 큐에서 `get(timeout=0.2)`.
  - `sensor` 작업은 메모리 배치에 모은다. 배치가 20행이 되거나 마지막 flush에서 `db.batch_period_s`(1.0초)가 지나면 `with conn.transaction(): cur.executemany(...)`로 한 번에 쓴다. 실패하면 그 배치를 버린다.
  - 나머지 작업은 꺼내는 즉시 실행한다(autocommit, 문장 하나).
  - 매 반복 끝에 주기 작업을 확인한다: 요약(5절) `db.summary_period_s`(2초)마다, 상관분석(04 2절) `correlation.period_s`(10초)마다. `db_ok`가 false이면 건너뛴다.
- 진동 배열은 파이썬 float 목록으로 넘기고 `real[]` 열에 넣는다(`numpy.ndarray.tolist()`, 값은 Payload의 소수 4자리 그대로).
- 적재량: chunk 초당 10행, 행당 약 12 KB(`real` 3 × 1000 × 4 B + 헤더) → 약 120 KB/초, 5분 약 36 MB. 1초 배치 한 번에 약 10행.

구현(`store/db.py`의 `DbWriter`, SQL은 `store/sql.py`):
- 생성자: `DbWriter(cfg, db_queue, clock=, on_db_ok=, on_summary=, on_correlation=, compute_correlation=)`. `start()`, `stop(timeout=5.0)`(남은 배치를 쓰고 연결을 닫는다). 콜백은 DB 스레드에서 불리고, 콜백 예외는 `db_callback_error` 로그만 남긴다. `on_db_ok`는 값이 바뀔 때만 부른다(처음 값 false는 부르지 않는다).
- 재연결 시도는 작업이 없어도 루프 반복마다(최대 0.2초 간격) `reconnect_interval_s`가 지났는지 보고 한다. 트래픽이 없을 때도 `db_ok`(`/readyz`)가 돌아오게 하기 위해서다. 끊김은 작업·요약 조회의 `OperationalError`(또는 깨진 연결)로 알아챈다.
- 요약 dict 값은 psycopg가 준 그대로다(`timestamp`류는 aware datetime, `alarm_id`는 `uuid.UUID`, `bbox`는 int 목록). JSON 변환은 스냅숏(OPS-6)이 한다. 상관분석 입력은 `(timestamp, defect)`·`(timestamp, anomaly_score)` 튜플 목록이고 `cfg`는 생성자에 준 설정이다.
- 관찰용 누계 `counters`: `jobs_written`, `sensor_rows_written`, `sensor_batches`, `dropped_disconnected`, `db_errors`, `connect_attempts`, `summaries`, `correlations`.

## 4. DDL (`db/schema.sql`)

한 파일, 순수 SQL, 반복 실행해도 오류가 없다(`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, `if_not_exists => TRUE`, `CREATE OR REPLACE VIEW`). migration 도구는 쓰지 않는다. 스키마를 바꾸면 `schema_info.version`을 올리고 코드의 기대값도 같은 PR에서 바꾼다(초기화가 매번 빈 DB라 옛 버전 변환은 하지 않는다). 아래가 버전 1의 전체 내용이다(주석은 줄여도 된다).

```sql
-- factory-operations DB schema, version 1 (docs/spec/05-storage.md)
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS schema_info (
    component  text PRIMARY KEY,
    version    integer NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO schema_info (component, version) VALUES ('factory-operations', 1)
    ON CONFLICT (component) DO NOTHING;

-- Shared 5.2 Time-Series: Sensor Vibration chunk 한 행
CREATE TABLE IF NOT EXISTS sensor_chunk (
    sensor_id      text        NOT NULL,
    "timestamp"    timestamptz NOT NULL,   -- 첫 샘플 시각
    seq            bigint      NOT NULL,
    sample_rate_hz integer     NOT NULL,
    rpm            real        NOT NULL,
    temperature    real        NOT NULL,
    vibration_x    real[]      NOT NULL,
    vibration_y    real[]      NOT NULL,
    vibration_z    real[]      NOT NULL,
    fault_level    smallint    NULL,       -- Line Status as-of join, 평가용
    received_at    timestamptz NOT NULL,
    PRIMARY KEY (sensor_id, "timestamp")
);
SELECT create_hypertable('sensor_chunk', by_range('timestamp'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS line_status_change (
    id                bigserial   PRIMARY KEY,
    received_at       timestamptz NOT NULL,
    "timestamp"       timestamptz NULL,     -- offline 행은 null
    online            boolean     NOT NULL,
    conveyor          text        NULL CHECK (conveyor IN ('RUNNING', 'STOPPED')),
    fault_level       smallint    NULL,
    motor_rpm         real        NULL,
    production_active boolean     NULL,
    sensor_id         text        NULL
);
CREATE INDEX IF NOT EXISTS line_status_change_ts_idx ON line_status_change ("timestamp");

CREATE TABLE IF NOT EXISTS product (
    product_id  text        PRIMARY KEY,
    "timestamp" timestamptz NOT NULL,       -- 캡처 시각
    image_path  text        NOT NULL,
    received_at timestamptz NOT NULL
);

-- Shared 5.3 Inspection History
CREATE TABLE IF NOT EXISTS inspection (
    id                    bigserial   PRIMARY KEY,
    product_id            text        NOT NULL UNIQUE,
    "timestamp"           timestamptz NOT NULL,   -- 캡처 시각 (Vision Result 값)
    defect                boolean     NOT NULL,
    defect_type           text        NULL,
    confidence            real        NULL,
    bbox                  integer[]   NULL,
    image_path            text        NOT NULL,
    gradcam_path          text        NULL,
    judgement_source      text        NULL,
    sensor_id             text        NOT NULL,
    health_index_at_time  smallint    NULL,
    anomaly_score_at_time double precision NULL,
    pdm_timestamp_at_time timestamptz NULL,
    received_at           timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS inspection_ts_idx ON inspection ("timestamp");

-- Shared 5.3 Defect Result
CREATE OR REPLACE VIEW defect_result AS
    SELECT id, product_id, "timestamp", defect_type, confidence, bbox,
           image_path, gradcam_path, judgement_source, health_index_at_time
    FROM inspection WHERE defect;

-- Shared 5.3 Equipment State History
CREATE TABLE IF NOT EXISTS equipment_state (
    sensor_id     text             NOT NULL,
    "timestamp"   timestamptz      NOT NULL,  -- 윈도우 끝
    window_start  timestamptz      NULL,
    anomaly_score double precision NOT NULL,
    health_index  smallint         NOT NULL,
    state         text             NOT NULL CHECK (state IN ('NORMAL', 'CAUTION', 'WARNING', 'CRITICAL')),
    model_version text             NULL,
    received_at   timestamptz      NOT NULL,
    PRIMARY KEY (sensor_id, "timestamp")
);

-- Shared 5.3 Alarm History
CREATE TABLE IF NOT EXISTS alarm (
    alarm_id       uuid             PRIMARY KEY,
    "timestamp"    timestamptz      NOT NULL,  -- 원인 PdM Result의 timestamp
    raised_at      timestamptz      NOT NULL,
    sensor_id      text             NOT NULL,
    severity       text             NOT NULL CHECK (severity IN ('WARNING', 'CRITICAL')),
    previous_state text             NULL CHECK (previous_state IN ('NORMAL', 'CAUTION', 'WARNING', 'CRITICAL')),
    health_index   smallint         NOT NULL,
    anomaly_score  double precision NOT NULL
);
CREATE INDEX IF NOT EXISTS alarm_raised_at_idx ON alarm (raised_at);

-- Shared 5.3 Control History
CREATE TABLE IF NOT EXISTS control (
    command_id         text        PRIMARY KEY,
    command            text        NULL CHECK (command IN ('START', 'STOP')),
    reason             text        NULL,
    origin             text        NOT NULL CHECK (origin IN ('operations', 'observed')),
    source             text        NULL,       -- observed: last_command.source
    issued_at          timestamptz NULL,       -- operations: 발행 Payload의 timestamp
    trigger_sensor_id  text        NULL,       -- Interlock STOP만
    trigger_timestamp  timestamptz NULL,       -- Interlock STOP을 낸 PdM Result timestamp
    result             text        NULL CHECK (result IN ('APPLIED', 'NO_CHANGE', 'REJECTED')),
    result_received_at timestamptz NULL,       -- last_command.received_at (Simulator 시계)
    error              text        NULL,
    observed_at        timestamptz NULL,       -- 결과를 본 Operations 시각
    recorded_at        timestamptz NOT NULL    -- 행을 만든 Operations 시각
);
CREATE INDEX IF NOT EXISTS control_recorded_at_idx ON control (recorded_at);
```

- Shared 5.3절 Vision Inspection 최소 필드(`id`, `timestamp`, `product_id`, `image_path`, `defect_type`, `confidence`, `bbox`, `health_index_at_time`)는 `inspection`에 모두 있다.
- `product`·`inspection` 사이에 외래키를 두지 않는다. Topic 사이 도착 순서가 보장되지 않아 Vision Result가 Product Created보다 먼저 올 수 있다.
- 적용 방식(integration): `/docker-entrypoint-initdb.d/100_factory_operations.sql`로 마운트하거나 빈 DB에 `psql -v ON_ERROR_STOP=1 -f db/schema.sql`. 세부는 `AGREEMENTS.md` A-08.

## 5. 조회

DB 스레드만 조회한다(HTTP 요청마다 DB를 조회하지 않는다). 결과를 StateStore `summary`·`correlation`에 넣는다.

요약(`db.summary_period_s`마다), 한 트랜잭션 없이 문장 네 개:

```sql
SELECT (SELECT count(*) FROM product) AS produced,
       count(*) AS inspected,
       count(*) FILTER (WHERE defect) AS defects
FROM inspection;

SELECT product_id, "timestamp", defect, defect_type, confidence, bbox, image_path,
       gradcam_path, judgement_source, health_index_at_time
FROM inspection ORDER BY "timestamp" DESC, id DESC LIMIT %(n_inspections)s;

SELECT alarm_id, "timestamp", raised_at, sensor_id, severity, previous_state, health_index, anomaly_score
FROM alarm ORDER BY raised_at DESC LIMIT %(n_alarms)s;

SELECT command_id, command, reason, origin, source, issued_at, trigger_timestamp,
       result, result_received_at, error, recorded_at
FROM control ORDER BY recorded_at DESC LIMIT %(n_controls)s;
```

- **불량률** = `defects / inspected`(`inspection` 한 소스, `inspected == 0`이면 null). 생산 수 = `produced`(`product` 행 수). Line Status `products.created`는 simulator 누계로 따로 표시만 하고 더하지 않는다.
- 요약 결과에 `summary_at`(Operations 시각)을 붙인다.

상관분석(`correlation.period_s`마다):

```sql
SELECT "timestamp", defect FROM inspection ORDER BY "timestamp";
SELECT "timestamp", anomaly_score FROM equipment_state WHERE sensor_id = %(sensor_id)s ORDER BY "timestamp";
```

`correlation.window_s`가 있으면 첫 조회에 `WHERE "timestamp" >= (SELECT max("timestamp") FROM inspection) - make_interval(secs => %(w)s)`를, 둘째 조회에는 그 하한에서 `lag_max_s + join.max_gap_s`를 더 뺀 조건을 붙인다.

## 6. 설정

| 키 | 기본값 | 의미 |
|---|---|---|
| `db.batch_period_s` | 1.0 | 센서 배치 flush 주기(초) |
| `db.reconnect_interval_s` | 2.0 | 재연결 최소 간격(초) |
| `db.summary_period_s` | 2.0 | 요약 조회 주기(초). Dashboard 갱신 지연 예산(08 4절)에 들어간다. 0.5~2.5 |

`db.url`은 `07-runtime.md` 1절.
