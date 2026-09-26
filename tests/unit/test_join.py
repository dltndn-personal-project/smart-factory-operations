"""시간 결합 (docs/spec/04-analysis.md 1절, 08-verification.md 3.4절)."""

from __future__ import annotations

from datetime import timedelta

from factory_operations.domain.join import HealthAtTime, fault_level_at, health_index_at_time
from factory_operations.domain.line import FaultChange
from factory_operations.mqtt.payloads import PdmResult

S = timedelta(seconds=1)
MS = timedelta(milliseconds=1)


def pdm(ts, hi, score, sensor="motor01"):
    return PdmResult(sensor, ts, score, hi, "NORMAL", ts - S, "v1")


def test_fault_level_at_inclusive(fake_clock):
    t0 = fake_clock.wall()
    changes = [FaultChange(t0, 0), FaultChange(t0 + 40 * S, 3), FaultChange(t0 + 70 * S, 6)]
    assert fault_level_at(changes, t0) == 0
    assert fault_level_at(changes, t0 + 40 * S - MS) == 0
    assert fault_level_at(changes, t0 + 40 * S) == 3  # 같은 timestamp면 그 값(≤)
    assert fault_level_at(changes, t0 + 69 * S) == 3
    assert fault_level_at(changes, t0 + 70 * S) == 6
    assert fault_level_at(changes, t0 + 1000 * S) == 6


def test_fault_level_before_first_is_null(fake_clock):
    t0 = fake_clock.wall()
    assert fault_level_at([FaultChange(t0, 2)], t0 - MS) is None
    assert fault_level_at([], t0) is None


def test_health_index_gap_boundary(fake_clock):
    t0 = fake_clock.wall()
    hist = [pdm(t0, 90, 0.1), pdm(t0 + 0.5 * S, 88, 0.12)]
    last = t0 + 0.5 * S
    # 차가 정확히 max_gap_s(5.0초)면 붙는다
    assert health_index_at_time(last + 5 * S, hist, 5.0, "motor01") == HealthAtTime("motor01", 88, 0.12, last)
    # 1 ms 넘으면 null
    assert health_index_at_time(last + 5 * S + MS, hist, 5.0, "motor01") == HealthAtTime("motor01", None, None, None)
    # 같은 시각이면 그 결과
    assert health_index_at_time(t0, hist, 5.0, "motor01").health_index == 90
    # 사이면 캡처 시각 이하 가장 최근
    assert health_index_at_time(t0 + 0.4 * S, hist, 5.0, "motor01").health_index == 90


def test_future_pdm_not_used(fake_clock):
    t0 = fake_clock.wall()
    hist = [pdm(t0, 90, 0.1), pdm(t0 + 2 * S, 20, 0.8)]
    r = health_index_at_time(t0 + 1 * S, hist, 5.0, "motor01")
    assert (r.health_index, r.pdm_timestamp) == (90, t0)
    # 모든 결과가 미래면 null
    r = health_index_at_time(t0 - MS, hist, 5.0, "motor01")
    assert (r.health_index, r.anomaly_score, r.pdm_timestamp) == (None, None, None)


def test_no_pdm_keeps_line_sensor(fake_clock):
    r = health_index_at_time(fake_clock.wall(), [], 5.0, "motor07")
    assert r == HealthAtTime("motor07", None, None, None)
