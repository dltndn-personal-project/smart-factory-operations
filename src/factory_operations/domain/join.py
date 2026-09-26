"""시간 결합 (docs/spec/04-analysis.md 1절). 순수 함수. 모든 비교는 Payload timestamp끼리 한다."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, Sequence

from ..mqtt.payloads import PdmResult


class _Change(Protocol):
    timestamp: datetime
    fault_level: int


def fault_level_at(changes: Sequence[_Change], ts: datetime) -> int | None:
    """변화점 `timestamp ≤ ts`인 가장 최근 것의 `fault_level`. 없으면 None (1.1절).

    `changes`는 `timestamp` 순이다(`LineTracker.fault_changes`).
    """
    i = bisect.bisect_right([c.timestamp for c in changes], ts)
    return changes[i - 1].fault_level if i else None


@dataclass(frozen=True)
class HealthAtTime:
    sensor_id: str  # 결합에 쓴 라인 센서(결과가 없어도)
    health_index: int | None
    anomaly_score: float | None
    pdm_timestamp: datetime | None


def health_index_at_time(
    vision_ts: datetime, history: Sequence[PdmResult], max_gap_s: float, sensor_id: str
) -> HealthAtTime:
    """캡처 시각 이하 가장 최근 PdM 결과가 `max_gap_s` 안이면 그 값, 아니면 셋 다 None (1.2절).

    `history`는 라인 센서의 `timestamp` 순 이력이다. 재가동 기준 시각과 관계없이 모든 결과를 쓴다.
    """
    i = bisect.bisect_right([r.timestamp for r in history], vision_ts)
    if i:
        r = history[i - 1]
        if vision_ts - r.timestamp <= timedelta(seconds=max_gap_s):
            return HealthAtTime(sensor_id, r.health_index, r.anomaly_score, r.timestamp)
    return HealthAtTime(sensor_id, None, None, None)
