"""Alarm 규칙 `AlarmManager` (docs/spec/03-control.md 4절, DECISIONS D-21).

센서별 이전 상태 `prev`를 기억하고 심각도가 올라 `WARNING`·`CRITICAL`이 될 때 Alarm 값 객체를 만든다.
DB 작업·발행·로그는 워커가 한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from ..mqtt.payloads import Alarm, PdmResult

SEVERITY = {"NORMAL": 0, "CAUTION": 1, "WARNING": 2, "CRITICAL": 3}
ALARM_STATES = ("WARNING", "CRITICAL")


class AlarmManager:
    def __init__(self) -> None:
        self._prev: dict[str, str | None] = {}

    def prev(self, sensor_id: str) -> str | None:
        return self._prev.get(sensor_id)

    def evaluate(self, r: PdmResult, now: datetime) -> Alarm | None:
        """Alarm 대상 PdM Result 하나. 올라가면 Alarm, 아니면 None. 어느 쪽이든 `prev = r.state`."""
        prev = self._prev.get(r.sensor_id)
        alarm = None
        if r.state in ALARM_STATES and SEVERITY[r.state] > (SEVERITY[prev] if prev is not None else -1):
            alarm = Alarm(
                alarm_id=str(uuid.uuid4()),
                timestamp=r.timestamp,
                raised_at=now,
                sensor_id=r.sensor_id,
                severity=r.state,
                previous_state=prev,
                health_index=r.health_index,
                anomaly_score=r.anomaly_score,
            )
        self._prev[r.sensor_id] = r.state
        return alarm

    def reset(self, sensor_id: str) -> None:
        """재가동 이벤트(03 1.2절): 라인 센서의 prev를 비운다."""
        self._prev.pop(sensor_id, None)
