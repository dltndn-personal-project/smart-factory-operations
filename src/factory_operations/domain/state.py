"""StateStore (docs/spec/01-core.md 3절).

`threading.Lock` 하나로 보호한다. 워커와 DB 스레드가 쓰고 HTTP가 읽는다. HTTP는
`snapshot_view()`로 락 안에서 참조·얕은 복사만 꺼내고 JSON 만들기는 락 밖에서 한다.
저장하는 객체(파싱된 메시지, numpy 배열, 라인·Interlock 뷰)는 만든 뒤 바꾸지 않는다.
"""

from __future__ import annotations

import bisect
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Hashable

from ..mqtt.payloads import PdmResult, SensorChunk, SpectrumPanels


@dataclass(frozen=True)
class Received:
    """수신한 값과 Operations 수신 시각(wall: UTC datetime, mono: 초)."""

    value: Any
    wall: datetime
    mono: float


@dataclass(frozen=True)
class SnapshotView:
    """`snapshot_view()` 결과. 컨테이너는 복사본이고 원소는 바뀌지 않는 객체다."""

    line: Any  # domain.line.LineView 또는 None
    pdm_latest: dict[str, Received]  # sensor_id → Received(PdmResult)
    pdm_history: dict[str, tuple[PdmResult, ...]]  # sensor_id → timestamp 순
    spectrum_latest: Received | None  # Received(SpectrumPanels)
    vibration_ring: tuple[Received, ...]  # Received(SensorChunk), 오래된 것부터
    interlock: Any
    mqtt_connected: bool
    db_ok: bool
    summary: Received | None  # Received(요약 결과), wall = 조회 시각
    correlation: Any
    counters: dict[Hashable, int]


class PdmHistory:
    """한 센서의 PdM Result를 `timestamp` 순으로, 가장 최근 `timestamp`에서 `history_s` 안만 보관한다.

    같은 `timestamp`가 다시 오면(QoS 1 중복) 새 값으로 바꾼다. 스레드 안전하지 않다(StateStore 락 안에서 쓴다).
    """

    def __init__(self, history_s: float):
        self._window = timedelta(seconds=history_s)
        self._ts: list[datetime] = []
        self._items: list[PdmResult] = []

    def add(self, r: PdmResult) -> None:
        i = bisect.bisect_left(self._ts, r.timestamp)
        if i < len(self._ts) and self._ts[i] == r.timestamp:
            self._items[i] = r
        else:
            self._ts.insert(i, r.timestamp)
            self._items.insert(i, r)
        cut = bisect.bisect_left(self._ts, self._ts[-1] - self._window)
        if cut:
            del self._ts[:cut]
            del self._items[:cut]

    def items(self) -> tuple[PdmResult, ...]:
        return tuple(self._items)

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class StateStore:
    history_s: float = 120.0
    vibration_window_chunks: int = 10
    # paho 콜백이 단순 대입으로 쓴다(락 없음)
    mqtt_connected: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _line: Any = None
    _pdm_latest: dict[str, Received] = field(default_factory=dict)
    _pdm_history: dict[str, PdmHistory] = field(default_factory=dict)
    _spectrum_latest: Received | None = None
    _vibration_ring: deque = field(default_factory=deque)
    _interlock: Any = None
    _db_ok: bool = False
    _summary: Received | None = None
    _correlation: Any = None
    _counters: dict[Hashable, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._vibration_ring = deque(maxlen=self.vibration_window_chunks)

    @classmethod
    def from_config(cls, cfg: Any) -> "StateStore":
        return cls(history_s=cfg.pdm.history_s, vibration_window_chunks=cfg.dashboard.vibration_window_chunks)

    # --- 워커가 쓰는 값 -------------------------------------------------

    def set_line(self, view: Any) -> None:
        """LineTracker의 바뀌지 않는 뷰(`LineTracker.view()`)를 둔다."""
        with self._lock:
            self._line = view

    def add_pdm(self, r: PdmResult, wall: datetime, mono: float) -> None:
        """`pdm_latest` 교체와 `pdm_history` 추가(01 3절, 03 2절)."""
        with self._lock:
            self._pdm_latest[r.sensor_id] = Received(r, wall, mono)
            hist = self._pdm_history.get(r.sensor_id)
            if hist is None:
                hist = self._pdm_history[r.sensor_id] = PdmHistory(self.history_s)
            hist.add(r)

    def pdm_history(self, sensor_id: str) -> tuple[PdmResult, ...]:
        """결합(04 1.2절)용 이력 복사본."""
        with self._lock:
            hist = self._pdm_history.get(sensor_id)
            return hist.items() if hist is not None else ()

    def set_spectrum(self, panels: SpectrumPanels, wall: datetime, mono: float) -> None:
        with self._lock:
            self._spectrum_latest = Received(panels, wall, mono)

    def add_vibration(self, chunk: SensorChunk, wall: datetime, mono: float, *, reset: bool = False) -> None:
        """라인 센서 chunk를 링 버퍼에 넣는다. `reset`이면 먼저 비운다(03 2절 규칙은 워커가 정한다)."""
        with self._lock:
            if reset:
                self._vibration_ring.clear()
            self._vibration_ring.append(Received(chunk, wall, mono))

    def last_vibration(self) -> Received | None:
        with self._lock:
            return self._vibration_ring[-1] if self._vibration_ring else None

    def set_interlock(self, view: Any) -> None:
        with self._lock:
            self._interlock = view

    # --- DB 스레드가 쓰는 값 --------------------------------------------

    def set_db_ok(self, ok: bool) -> None:
        with self._lock:
            self._db_ok = ok

    def set_summary(self, summary: Any, wall: datetime, mono: float) -> None:
        with self._lock:
            self._summary = Received(summary, wall, mono)

    def set_correlation(self, result: Any) -> None:
        with self._lock:
            self._correlation = result

    # --- 모두 -----------------------------------------------------------

    def incr(self, key: Hashable, n: int = 1) -> None:
        """카운터(버린 메시지 수: 예 `("rejected", topic, reason)`, 큐 초과 수)."""
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + n

    @property
    def db_ok(self) -> bool:
        with self._lock:
            return self._db_ok

    # --- HTTP -----------------------------------------------------------

    def snapshot_view(self) -> SnapshotView:
        """락 안에서 참조와 얕은 복사만 꺼낸다."""
        with self._lock:
            return SnapshotView(
                line=self._line,
                pdm_latest=dict(self._pdm_latest),
                pdm_history={k: h.items() for k, h in self._pdm_history.items()},
                spectrum_latest=self._spectrum_latest,
                vibration_ring=tuple(self._vibration_ring),
                interlock=self._interlock,
                mqtt_connected=self.mqtt_connected,
                db_ok=self._db_ok,
                summary=self._summary,
                correlation=self._correlation,
                counters=dict(self._counters),
            )
