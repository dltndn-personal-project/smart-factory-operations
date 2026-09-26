"""Alarm 시나리오 L-01~L-11 (docs/spec/03-control.md 6절, 4절)."""

from __future__ import annotations

import uuid

import pytest

from test_worker import H


@pytest.fixture
def h(fake_clock, fake_publisher, fake_db_sink):
    return H(fake_clock, fake_publisher, fake_db_sink)


def alarms(h: H) -> list[tuple]:
    """DB 작업과 발행한 Alarm Event가 같은지 확인하고 (severity, previous_state) 목록을 준다."""
    jobs = h.jobs("alarm")
    events = h.alarm_events
    assert [j.alarm_id for j in jobs] == [e["alarm_id"] for e in events]
    for j, e in zip(jobs, events):
        assert uuid.UUID(j.alarm_id).version == 4
        assert (e["severity"], e["previous_state"], e["sensor_id"], e["health_index"]) == (
            j.severity,
            j.previous_state,
            j.sensor_id,
            j.health_index,
        )
    return [(j.severity, j.previous_state) for j in jobs]


def seq(h: H, states, start=1.0, sensor="motor01"):
    for i, s in enumerate(states):
        h.pdm(s, at=start + 0.5 * i, sensor=sensor)


def test_l01(h):
    h.ls("RUNNING", at=0)
    seq(h, ["NORMAL", "CAUTION", "WARNING", "CRITICAL"])
    assert alarms(h) == [("WARNING", "CAUTION"), ("CRITICAL", "WARNING")]
    j = h.jobs("alarm")[1]
    assert (j.timestamp, j.raised_at, j.health_index) == (h.ts(2.5), h.clock.wall(), 20)


def test_l02(h):
    h.ls("RUNNING", at=0)
    seq(h, ["WARNING"])
    assert alarms(h) == [("WARNING", None)]


def test_l03(h):
    h.ls("RUNNING", at=0)
    seq(h, ["CRITICAL", "CRITICAL", "WARNING", "CRITICAL"])
    assert alarms(h) == [("CRITICAL", None), ("CRITICAL", "WARNING")]


def test_l04(h):
    h.ls("RUNNING", at=0)
    seq(h, ["WARNING", "CAUTION", "WARNING"])
    assert alarms(h) == [("WARNING", None), ("WARNING", "CAUTION")]


def test_l05(h):
    h.ls("RUNNING", at=0)
    seq(h, ["CRITICAL"], start=1)
    h.ls("STOPPED", at=1.5)
    h.ls("RUNNING", at=10)  # 재가동 이벤트
    seq(h, ["WARNING"], start=11)
    assert alarms(h) == [("CRITICAL", None), ("WARNING", None)]


def test_l06(h):
    h.ls("RUNNING", at=10)
    h.pdm("CRITICAL", at=9.5)  # 재가동 기준 시각 이전
    h.pdm("CRITICAL", at=10.0)  # 같은 시각도 이전으로 본다(> 비교)
    assert alarms(h) == []
    assert [e.timestamp for e in h.jobs("equipment")] == [h.ts(9.5), h.ts(10.0)]
    assert h.stops == []


def test_l07(h):
    h.ls("RUNNING", at=0)
    h.pdm("CRITICAL", at=1)
    topics = [t for t, *_ in h.pub.sent]
    assert topics == ["factory/alarm/event", "factory/control/conveyor"]
    assert alarms(h) == [("CRITICAL", None)]
    # DB 작업도 alarm → control_issued 순서
    kinds = [j.kind for j in h.db.jobs if j.kind in ("alarm", "control_issued")]
    assert kinds == ["alarm", "control_issued"]


def test_l08(h):
    h.pdm("WARNING", at=0)
    h.ls("RUNNING", at=0.2)  # 첫 동기화: 재가동 이벤트 아님
    h.pdm("WARNING", at=0.5)
    assert alarms(h) == [("WARNING", None)]


def test_l09(h):
    h.ls("RUNNING", at=0)
    h.pdm("WARNING", at=1)
    h.off()
    h.ls("RUNNING", at=3)  # RUNNING → offline → RUNNING: 재가동 이벤트 아님
    h.pdm("WARNING", at=4)
    assert alarms(h) == [("WARNING", None)]


def test_l10(h):
    h.ls("RUNNING", at=0)
    h.pdm("CRITICAL", at=1)
    h.ls("STOPPED", at=1.5)
    h.off()
    h.ls("RUNNING", at=30)  # 정지 상태에서 simulator 재기동 → 재가동 이벤트
    h.pdm("WARNING", at=31.1)
    assert alarms(h) == [("CRITICAL", None), ("WARNING", None)]


def test_l11(h):
    h.ls("RUNNING", at=0, sensor="motor01")
    h.pdm("WARNING", at=1, sensor="motor01")
    h.pdm("WARNING", at=1, sensor="motor02")
    assert sorted(j.sensor_id for j in h.jobs("alarm")) == ["motor01", "motor02"]
    assert alarms(h) == [("WARNING", None), ("WARNING", None)]
    assert h.stops == []


def test_alarm_publish_failure_keeps_db(h):
    h.ls("RUNNING", at=0)
    h.pub.connected = False
    h.pdm("WARNING", at=1)
    assert len(h.jobs("alarm")) == 1 and h.alarm_events == []
