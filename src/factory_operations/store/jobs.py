"""DB 쓰기 작업 (docs/spec/05-storage.md 2절). 순수 dataclass.

워커가 만들어 DB 큐에 넣고 DB 스레드(OPS-4B)가 소비한다. `kind`는 05 2절 표의 작업 이름이다.
timestamp는 모두 UTC datetime이다. `received_at`·`recorded_at`·`observed_at`·`raised_at`·`issued_at`은
Operations 시각, 나머지는 Payload 값이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Union

import numpy as np


@dataclass(frozen=True, eq=False)
class SensorJob:
    kind: ClassVar[str] = "sensor"
    sensor_id: str
    timestamp: datetime
    seq: int
    sample_rate_hz: int
    rpm: float
    temperature: float
    vibration_x: np.ndarray
    vibration_y: np.ndarray
    vibration_z: np.ndarray
    fault_level: int | None
    received_at: datetime


@dataclass(frozen=True)
class LineChangeJob:
    kind: ClassVar[str] = "line_change"
    received_at: datetime
    timestamp: datetime | None  # offline 행은 None
    online: bool
    conveyor: str | None
    fault_level: int | None
    motor_rpm: float | None
    production_active: bool | None
    sensor_id: str | None


@dataclass(frozen=True)
class ProductJob:
    kind: ClassVar[str] = "product"
    product_id: str
    timestamp: datetime
    image_path: str
    received_at: datetime


@dataclass(frozen=True)
class InspectionJob:
    kind: ClassVar[str] = "inspection"
    product_id: str
    timestamp: datetime
    defect: bool
    defect_type: str | None
    confidence: float | None
    bbox: tuple[int, int, int, int] | None
    image_path: str
    gradcam_path: str | None
    judgement_source: str | None
    sensor_id: str
    health_index_at_time: int | None
    anomaly_score_at_time: float | None
    pdm_timestamp_at_time: datetime | None
    received_at: datetime


@dataclass(frozen=True)
class EquipmentJob:
    kind: ClassVar[str] = "equipment"
    sensor_id: str
    timestamp: datetime
    window_start: datetime | None
    anomaly_score: float
    health_index: int
    state: str
    model_version: str | None
    received_at: datetime


@dataclass(frozen=True)
class AlarmJob:
    kind: ClassVar[str] = "alarm"
    alarm_id: str
    timestamp: datetime
    raised_at: datetime
    sensor_id: str
    severity: str
    previous_state: str | None
    health_index: int
    anomaly_score: float


@dataclass(frozen=True)
class ControlIssuedJob:
    """Operations가 발행한 명령(origin `operations`)."""

    kind: ClassVar[str] = "control_issued"
    command_id: str
    command: str
    reason: str
    issued_at: datetime  # 발행 Payload의 timestamp
    trigger_sensor_id: str | None  # Interlock STOP만
    trigger_timestamp: datetime | None
    recorded_at: datetime


@dataclass(frozen=True)
class ControlResultJob:
    kind: ClassVar[str] = "control_result"
    command_id: str
    result: str
    result_received_at: datetime | None  # last_command.received_at (Simulator 시계)
    error: str | None
    observed_at: datetime


@dataclass(frozen=True)
class ControlObservedJob:
    """모르는 command_id의 결과(origin `observed`)."""

    kind: ClassVar[str] = "control_observed"
    command_id: str
    command: str | None
    reason: str | None
    source: str | None
    result: str
    result_received_at: datetime | None
    error: str | None
    observed_at: datetime
    recorded_at: datetime


Job = Union[
    SensorJob,
    LineChangeJob,
    ProductJob,
    InspectionJob,
    EquipmentJob,
    AlarmJob,
    ControlIssuedJob,
    ControlResultJob,
    ControlObservedJob,
]

JOB_KINDS = (
    "sensor",
    "line_change",
    "product",
    "inspection",
    "equipment",
    "alarm",
    "control_issued",
    "control_result",
    "control_observed",
)
