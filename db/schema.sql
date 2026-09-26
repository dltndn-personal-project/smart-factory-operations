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
