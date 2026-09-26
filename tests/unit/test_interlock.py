"""Interlock 시나리오 S-01~S-12 (docs/spec/03-control.md 6절, 3.2·3.3절)."""

from __future__ import annotations

import pytest

from factory_operations.domain.worker import OperatorCommandError
from test_worker import H


@pytest.fixture
def h(fake_clock, fake_publisher, fake_db_sink):
    return H(fake_clock, fake_publisher, fake_db_sink)


def s01(h: H) -> dict:
    h.ls("RUNNING", at=0)
    h.advance(1)
    h.pdm("CRITICAL", at=1)
    assert len(h.stops) == 1
    return h.stops[0]


def test_s01(h):
    stop = s01(h)
    assert stop["reason"] == "INTERLOCK_CRITICAL" and stop["command"] == "STOP"
    (job,) = h.jobs("control_issued")
    assert (job.command_id, job.command, job.reason) == (stop["command_id"], "STOP", "INTERLOCK_CRITICAL")
    assert (job.trigger_sensor_id, job.trigger_timestamp) == ("motor01", h.ts(1))
    assert job.issued_at.isoformat().startswith(stop["timestamp"][:19])
    assert h.pending.command_id == stop["command_id"]
    assert h.state.snapshot_view().interlock.pending.command_id == stop["command_id"]


def test_s02(h):
    s01(h)
    h.advance(0.5)
    h.pdm("CRITICAL", at=1.5)
    h.advance(0.5)
    h.pdm("CRITICAL", at=2)
    assert len(h.stops) == 1
    assert len(h.jobs("control_issued")) == 1


def test_s03(h):
    stop = s01(h)
    h.advance(0.2)
    h.result(stop["command_id"], "APPLIED", conveyor="STOPPED")
    assert h.pending is None
    assert len(h.jobs("control_result")) == 1
    h.pdm("CRITICAL", at=1.5)
    assert len(h.stops) == 1  # STOPPED


def test_s04(h):
    s01(h)
    h.advance(4.9)
    h.pdm("CRITICAL", at=6)
    assert len(h.stops) == 1  # 아직 대기 중
    h.advance(0.2)
    h.tick()  # 시간 초과 → 바로 평가
    assert len(h.stops) == 2
    job = h.jobs("control_issued")[-1]
    assert job.trigger_timestamp == h.ts(6)
    assert h.pending.command_id == h.stops[1]["command_id"]
    h.pdm("CRITICAL", at=6.5)
    assert len(h.stops) == 2  # 새 대기 중


def test_s05(h):
    s01(h)
    h.advance(6)
    for _ in range(5):
        h.tick()
        h.advance(0.1)
    assert len(h.stops) == 1  # 같은 PdM 결과로 두 번 내지 않는다
    assert h.pending is None


def test_s06(h, fake_clock, fake_publisher, fake_db_sink):
    # Line Status 없음
    h.pdm("CRITICAL", at=0)
    assert len(h.stops) == 1
    # LS offline 뒤
    from conftest import FakeDbSink, FakePublisher

    h2 = H(fake_clock, FakePublisher(), FakeDbSink())
    h2.off()
    h2.pdm("CRITICAL", at=1)
    assert len(h2.stops) == 1
    assert h2.jobs("control_issued")[0].trigger_timestamp == h2.ts(1)


def _stop_then_restart(h: H, via_offline: bool) -> None:
    stop = s01(h)
    h.result(stop["command_id"], "APPLIED", conveyor="STOPPED", at=1.2)
    if via_offline:
        h.off()
    h.advance(28)
    h.ls("RUNNING", at=30)  # 운영자 START 뒤 재가동
    assert len(h.stops) == 1  # 옛 CRITICAL(t0+1)은 기준 시각 이전이라 판정 대상이 아니다
    assert h.p.interlock.judged is None
    h.advance(1.1)
    h.pdm("CRITICAL", at=31.1)
    assert len(h.stops) == 2
    assert h.jobs("control_issued")[-1].trigger_timestamp == h.ts(31.1)


def test_s07(h):
    _stop_then_restart(h, via_offline=False)


def test_s08(h):
    _stop_then_restart(h, via_offline=True)


def test_s09(h):
    stop = s01(h)
    h.result(stop["command_id"], "REJECTED", conveyor="RUNNING", at=1.2, error="invalid")
    assert h.pending is not None
    h.pdm("CRITICAL", at=2)
    assert len(h.stops) == 1  # 대기 유지
    h.advance(5)
    h.tick()
    assert len(h.stops) == 2
    assert h.jobs("control_issued")[-1].trigger_timestamp == h.ts(2)


def test_s10(h):
    h.ls("RUNNING", at=0)
    h.pub.connected = False
    h.pdm("CRITICAL", at=1)
    assert h.stops == [] and h.jobs("control_issued") == []
    assert h.pending is None and h.p.interlock.last_trigger_ts is None
    h.pub.connected = True
    h.pdm("CRITICAL", at=1.5)
    assert len(h.stops) == 1
    assert h.jobs("control_issued")[0].trigger_timestamp == h.ts(1.5)


def test_s11(h):
    h.ls("RUNNING", at=0)
    for i, state in enumerate(("WARNING", "CAUTION", "NORMAL")):
        h.pdm(state, at=1 + i * 0.5)
    h.pdm("CRITICAL", at=3, sensor="motor02")
    h.tick()
    assert h.stops == []
    assert h.jobs("control_issued") == []


def test_s12(h):
    s01(h)
    before = h.p.interlock.view()
    f = h.operator("START")
    r = f.result(0)
    assert r["command"] == "START" and r["judged_state"] == "CRITICAL"
    assert set(r) == {"command_id", "command", "timestamp", "judged_state"}
    job = h.jobs("control_issued")[-1]
    assert (job.command, job.reason, job.trigger_sensor_id, job.trigger_timestamp) == ("START", "OPERATOR_START", None, None)
    assert h.published("factory/control/conveyor")[-1]["reason"] == "OPERATOR_START"
    assert h.p.interlock.view() == before
    # 끊김
    h.pub.connected = False
    n_jobs = len(h.db.jobs)
    f = h.operator("START")
    with pytest.raises(OperatorCommandError) as ei:
        f.result(0)
    assert ei.value.code == "mqtt_disconnected"
    assert len(h.db.jobs) == n_jobs
    assert h.p.interlock.view() == before
