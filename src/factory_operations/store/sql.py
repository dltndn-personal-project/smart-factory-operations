"""DB 스레드가 실행하는 SQL 문자열 (docs/spec/05-storage.md 2·5절, DECISIONS D-11).

파라미터는 psycopg 이름 자리표시자(`%(name)s`)이고 이름은 `store/jobs.py` 필드 이름과 같다.
이 모듈은 psycopg를 import하지 않는다(01 1절: psycopg는 `store/db.py`만).
"""

from __future__ import annotations

# --- 2절 쓰기 작업 -----------------------------------------------------------

INSERT_SENSOR = """
INSERT INTO sensor_chunk (sensor_id, "timestamp", seq, sample_rate_hz, rpm, temperature,
                          vibration_x, vibration_y, vibration_z, fault_level, received_at)
VALUES (%(sensor_id)s, %(timestamp)s, %(seq)s, %(sample_rate_hz)s, %(rpm)s, %(temperature)s,
        %(vibration_x)s, %(vibration_y)s, %(vibration_z)s, %(fault_level)s, %(received_at)s)
ON CONFLICT (sensor_id, "timestamp") DO NOTHING
"""

INSERT_LINE_CHANGE = """
INSERT INTO line_status_change (received_at, "timestamp", online, conveyor, fault_level,
                                motor_rpm, production_active, sensor_id)
VALUES (%(received_at)s, %(timestamp)s, %(online)s, %(conveyor)s, %(fault_level)s,
        %(motor_rpm)s, %(production_active)s, %(sensor_id)s)
"""

INSERT_PRODUCT = """
INSERT INTO product (product_id, "timestamp", image_path, received_at)
VALUES (%(product_id)s, %(timestamp)s, %(image_path)s, %(received_at)s)
ON CONFLICT (product_id) DO NOTHING
"""

INSERT_INSPECTION = """
INSERT INTO inspection (product_id, "timestamp", defect, defect_type, confidence, bbox, image_path,
                        gradcam_path, judgement_source, sensor_id, health_index_at_time,
                        anomaly_score_at_time, pdm_timestamp_at_time, received_at)
VALUES (%(product_id)s, %(timestamp)s, %(defect)s, %(defect_type)s, %(confidence)s, %(bbox)s, %(image_path)s,
        %(gradcam_path)s, %(judgement_source)s, %(sensor_id)s, %(health_index_at_time)s,
        %(anomaly_score_at_time)s, %(pdm_timestamp_at_time)s, %(received_at)s)
ON CONFLICT (product_id) DO NOTHING
"""

INSERT_EQUIPMENT = """
INSERT INTO equipment_state (sensor_id, "timestamp", window_start, anomaly_score, health_index, state,
                             model_version, received_at)
VALUES (%(sensor_id)s, %(timestamp)s, %(window_start)s, %(anomaly_score)s, %(health_index)s, %(state)s,
        %(model_version)s, %(received_at)s)
ON CONFLICT (sensor_id, "timestamp") DO NOTHING
"""

INSERT_ALARM = """
INSERT INTO alarm (alarm_id, "timestamp", raised_at, sensor_id, severity, previous_state, health_index,
                   anomaly_score)
VALUES (%(alarm_id)s, %(timestamp)s, %(raised_at)s, %(sensor_id)s, %(severity)s, %(previous_state)s,
        %(health_index)s, %(anomaly_score)s)
"""

INSERT_CONTROL_ISSUED = """
INSERT INTO control (command_id, command, reason, issued_at, trigger_sensor_id, trigger_timestamp,
                     recorded_at, origin)
VALUES (%(command_id)s, %(command)s, %(reason)s, %(issued_at)s, %(trigger_sensor_id)s, %(trigger_timestamp)s,
        %(recorded_at)s, 'operations')
ON CONFLICT (command_id) DO NOTHING
"""

UPDATE_CONTROL_RESULT = """
UPDATE control SET result = %(result)s, result_received_at = %(result_received_at)s, error = %(error)s,
                   observed_at = %(observed_at)s
WHERE command_id = %(command_id)s AND result IS NULL
"""

INSERT_CONTROL_OBSERVED = """
INSERT INTO control (command_id, command, reason, source, result, result_received_at, error, observed_at,
                     recorded_at, origin)
VALUES (%(command_id)s, %(command)s, %(reason)s, %(source)s, %(result)s, %(result_received_at)s, %(error)s,
        %(observed_at)s, %(recorded_at)s, 'observed')
ON CONFLICT (command_id) DO NOTHING
"""

# 작업 kind → SQL. `sensor`는 배치(executemany)로, 나머지는 문장 하나로 실행한다.
JOB_SQL: dict[str, str] = {
    "sensor": INSERT_SENSOR,
    "line_change": INSERT_LINE_CHANGE,
    "product": INSERT_PRODUCT,
    "inspection": INSERT_INSPECTION,
    "equipment": INSERT_EQUIPMENT,
    "alarm": INSERT_ALARM,
    "control_issued": INSERT_CONTROL_ISSUED,
    "control_result": UPDATE_CONTROL_RESULT,
    "control_observed": INSERT_CONTROL_OBSERVED,
}

# --- 3절 스키마 확인 ---------------------------------------------------------

SCHEMA_VERSION = 1
SELECT_SCHEMA_VERSION = "SELECT version FROM schema_info WHERE component = 'factory-operations'"

# --- 5절 요약 ----------------------------------------------------------------

SUMMARY_COUNTS = """
SELECT (SELECT count(*) FROM product) AS produced,
       count(*) AS inspected,
       count(*) FILTER (WHERE defect) AS defects
FROM inspection
"""

SUMMARY_INSPECTIONS = """
SELECT product_id, "timestamp", defect, defect_type, confidence, bbox, image_path,
       gradcam_path, judgement_source, health_index_at_time
FROM inspection ORDER BY "timestamp" DESC, id DESC LIMIT %(n_inspections)s
"""

SUMMARY_ALARMS = """
SELECT alarm_id, "timestamp", raised_at, sensor_id, severity, previous_state, health_index, anomaly_score
FROM alarm ORDER BY raised_at DESC LIMIT %(n_alarms)s
"""

SUMMARY_CONTROLS = """
SELECT command_id, command, reason, origin, source, issued_at, trigger_timestamp,
       result, result_received_at, error, recorded_at
FROM control ORDER BY recorded_at DESC LIMIT %(n_controls)s
"""

# --- 5절 상관분석 ------------------------------------------------------------

_WINDOW_LOWER = """(SELECT max("timestamp") FROM inspection) - make_interval(secs => %(w)s)"""


def correlation_inspections_sql(windowed: bool) -> str:
    """검사 조회. `windowed`면 파라미터 `w` = `correlation.window_s`."""
    where = f'WHERE "timestamp" >= {_WINDOW_LOWER} ' if windowed else ""
    return f'SELECT "timestamp", defect FROM inspection {where}ORDER BY "timestamp"'


def correlation_scores_sql(windowed: bool) -> str:
    """설비 점수 조회(파라미터 `sensor_id`). `windowed`면 파라미터 `w` =
    `correlation.window_s + correlation.lag_max_s + join.max_gap_s`(검사 하한에서 더 뺀 값)."""
    extra = f'AND "timestamp" >= {_WINDOW_LOWER} ' if windowed else ""
    return (
        'SELECT "timestamp", anomaly_score FROM equipment_state '
        f'WHERE sensor_id = %(sensor_id)s {extra}ORDER BY "timestamp"'
    )
