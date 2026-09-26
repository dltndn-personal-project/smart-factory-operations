"""Line Status 추적 `LineTracker` (docs/spec/03-control.md 1절, DECISIONS D-17·D-21).

워커 스레드 하나만 쓴다. `update()`는 DB 작업을 만들지 않고 무엇이 바뀌었는지(`LineUpdate`)를
돌려준다. 워커(OPS-3B)가 그 값으로 `line_status_change` 작업과 Alarm 초기화를 한다.
화면·HTTP에는 `view()`의 바뀌지 않는 `LineView`를 StateStore에 넣어 준다.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..mqtt.payloads import LineOffline, LineStatus
from .join import fault_level_at

UNKNOWN = "UNKNOWN"
RUNNING = "RUNNING"
STOPPED = "STOPPED"

FAULT_RETENTION_S = 600.0


@dataclass(frozen=True)
class FaultChange:
    timestamp: datetime  # Line Status timestamp (Simulator 시계)
    fault_level: int


@dataclass(frozen=True)
class LineUpdate:
    """한 Line Status를 반영한 결과."""

    record_change: bool  # line_status_change 행을 쓸지(1.2절 offline 2번, online 3번)
    restart: bool  # 재가동 이벤트(STOPPED → RUNNING, 사이 offline 허용). Alarm 초기화용
    reference_changed: bool  # reference_time을 새로 잡았는지
    fault_changed: bool  # fault_changes에 변화점을 더했는지


@dataclass(frozen=True)
class LineView:
    line_state: str
    online: bool | None
    latest: LineStatus | None
    latest_wall: datetime | None  # latest 수신 시각
    latest_mono: float | None
    last_wall: datetime | None  # online 여부와 관계없이 마지막 Line Status 수신 시각
    last_mono: float | None
    reference_time: datetime | None
    last_conveyor: str | None
    line_sensor_id: str
    fault_changes: tuple[FaultChange, ...]


class LineTracker:
    def __init__(self, default_sensor_id: str = "motor01", retention_s: float = FAULT_RETENTION_S):
        self.default_sensor_id = default_sensor_id
        self._retention = timedelta(seconds=retention_s)
        self.line_state: str = UNKNOWN
        self.online: bool | None = None
        self.latest: LineStatus | None = None
        self.latest_wall: datetime | None = None
        self.latest_mono: float | None = None
        self.last_wall: datetime | None = None
        self.last_mono: float | None = None
        self.reference_time: datetime | None = None
        self.last_conveyor: str | None = None
        self._fault_ts: list[datetime] = []
        self._fault_changes: list[FaultChange] = []
        # 마지막으로 line_status_change에 기록한 (online, conveyor, fault_level, production_active)
        self._recorded: tuple | None = None

    @property
    def line_sensor_id(self) -> str:
        return self.latest.sensor_id if self.latest is not None else self.default_sensor_id

    @property
    def fault_changes(self) -> tuple[FaultChange, ...]:
        return tuple(self._fault_changes)

    def update(self, msg: LineStatus | LineOffline, wall: datetime, mono: float) -> LineUpdate:
        self.last_wall, self.last_mono = wall, mono
        if isinstance(msg, LineOffline):
            return self._offline()
        return self._online(msg, wall, mono)

    def _offline(self) -> LineUpdate:
        record = self.online is not False
        self.online = False
        self.line_state = UNKNOWN
        if record:
            prev = self._recorded or (None, None, None, None)
            self._recorded = (False,) + tuple(prev[1:])
        return LineUpdate(record_change=record, restart=False, reference_changed=False, fault_changed=False)

    def _online(self, ls: LineStatus, wall: datetime, mono: float) -> LineUpdate:
        new = ls.conveyor
        reference_changed = restart = False
        if new == RUNNING and self.line_state != RUNNING:
            self.reference_time = ls.timestamp
            reference_changed = True
            restart = self.last_conveyor == STOPPED
        self.last_conveyor = new
        self.line_state = new
        self.online = True
        self.latest, self.latest_wall, self.latest_mono = ls, wall, mono

        values = (True, ls.conveyor, ls.fault_level, ls.production_active)
        record = values != self._recorded
        if record:
            self._recorded = values

        fault_changed = not self._fault_changes or self._fault_changes[-1].fault_level != ls.fault_level
        if fault_changed:
            self._add_fault_change(FaultChange(ls.timestamp, ls.fault_level))
        self._prune(ls.timestamp)
        return LineUpdate(record_change=record, restart=restart, reference_changed=reference_changed, fault_changed=fault_changed)

    def _add_fault_change(self, fc: FaultChange) -> None:
        i = bisect.bisect_right(self._fault_ts, fc.timestamp)
        self._fault_ts.insert(i, fc.timestamp)
        self._fault_changes.insert(i, fc)

    def _prune(self, now_ts: datetime) -> None:
        """최근 retention 안의 변화점과, 그보다 오래된 것 중 가장 최근 하나를 남긴다(1.1절)."""
        old = bisect.bisect_left(self._fault_ts, now_ts - self._retention)  # [0, old)가 오래된 것
        drop = old - 1
        if drop > 0:
            del self._fault_ts[:drop]
            del self._fault_changes[:drop]

    def fault_level_at(self, ts: datetime) -> int | None:
        """04 1.1절 결합(`join.fault_level_at`)."""
        return fault_level_at(self._fault_changes, ts)

    def view(self) -> LineView:
        return LineView(
            line_state=self.line_state,
            online=self.online,
            latest=self.latest,
            latest_wall=self.latest_wall,
            latest_mono=self.latest_mono,
            last_wall=self.last_wall,
            last_mono=self.last_mono,
            reference_time=self.reference_time,
            last_conveyor=self.last_conveyor,
            line_sensor_id=self.line_sensor_id,
            fault_changes=self.fault_changes,
        )
