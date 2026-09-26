"""LineTracker (docs/spec/03-control.md 1절, 08-verification.md 3.3절)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from factory_operations.domain.line import RUNNING, STOPPED, UNKNOWN, FaultChange, LineTracker, LineUpdate
from factory_operations.mqtt.payloads import LineOffline, LineStatus

S = timedelta(seconds=1)


class Feed:
    """가짜 시계로 Line Status를 보낸다. timestamp는 가짜 시계의 벽시계 값(Simulator 시계 대신)."""

    def __init__(self, clock, tracker=None):
        self.clock = clock
        self.t = tracker or LineTracker("motor01")

    def ls(self, conveyor=RUNNING, fault=0, production=True, sensor="motor01", advance=1.0) -> LineUpdate:
        self.clock.advance(advance)
        msg = LineStatus(self.clock.wall(), conveyor, fault, 1800.0 if conveyor == RUNNING else 0.0, sensor, production, None, None)
        return self.t.update(msg, self.clock.wall(), self.clock.mono())

    def off(self, advance=1.0) -> LineUpdate:
        self.clock.advance(advance)
        return self.t.update(LineOffline(), self.clock.wall(), self.clock.mono())


@pytest.fixture
def feed(fake_clock):
    return Feed(fake_clock)


def test_initial_state():
    t = LineTracker("motor09")
    assert (t.line_state, t.online, t.latest, t.reference_time, t.last_conveyor) == (UNKNOWN, None, None, None, None)
    assert t.line_sensor_id == "motor09"
    assert t.fault_changes == ()


def test_first_running_sets_reference(feed):
    u = feed.ls(RUNNING, 3)
    ts = feed.clock.wall()
    assert feed.t.reference_time == ts
    assert u == LineUpdate(record_change=True, restart=False, reference_changed=True, fault_changed=True)
    assert (feed.t.line_state, feed.t.online, feed.t.last_conveyor) == (RUNNING, True, RUNNING)
    # 가동 중 1초 주기는 기준 시각을 바꾸지 않는다
    feed.ls(RUNNING, 3)
    assert feed.t.reference_time == ts
    # 기동 뒤 첫 수신이 STOPPED면 기준 시각이 없다
    other = Feed(feed.clock)
    u = other.ls(STOPPED, 0)
    assert other.t.reference_time is None and not u.reference_changed and u.record_change


def test_stopped_to_running_new_reference(feed):
    feed.ls(RUNNING, 0)
    first = feed.t.reference_time
    feed.ls(STOPPED, 9)
    assert feed.t.reference_time == first  # 정지는 기준 시각을 바꾸지 않는다
    u = feed.ls(RUNNING, 0)
    assert feed.t.reference_time == feed.clock.wall() != first
    assert u.reference_changed and u.restart


def test_offline_to_running_new_reference(feed):
    feed.ls(RUNNING, 2)
    first = feed.t.reference_time
    u = feed.off()
    assert (feed.t.line_state, feed.t.online) == (UNKNOWN, False)
    assert feed.t.latest is not None and feed.t.latest.fault_level == 2  # 마지막 값은 지우지 않는다
    assert feed.t.last_conveyor == RUNNING
    assert u == LineUpdate(record_change=True, restart=False, reference_changed=False, fault_changed=False)
    assert feed.t.reference_time == first
    u = feed.ls(RUNNING, 2)
    assert feed.t.reference_time == feed.clock.wall() != first
    assert u.reference_changed and not u.restart  # 가동 중 끊김 후 복귀는 재가동 이벤트가 아니다


def test_periodic_status_is_not_change(feed):
    assert feed.ls(RUNNING, 3).record_change
    for _ in range(10):
        u = feed.ls(RUNNING, 3)
        assert u == LineUpdate(record_change=False, restart=False, reference_changed=False, fault_changed=False)
    # 네 값 중 하나라도 바뀌면 기록
    assert feed.ls(RUNNING, 3, production=False).record_change
    assert not feed.ls(RUNNING, 3, production=False).record_change
    assert feed.ls(RUNNING, 4, production=False).record_change
    assert feed.ls(STOPPED, 4, production=False).record_change
    # offline은 이전 online이 false가 아니었을 때만 한 번
    assert feed.off().record_change
    assert not feed.off().record_change
    assert feed.ls(STOPPED, 4, production=False).record_change  # online 복귀는 변화
    # 처음 받은 것이 offline이어도 기록
    other = Feed(feed.clock)
    assert other.off().record_change
    assert not other.off().record_change


def test_fault_changes_only_on_change(feed):
    feed.ls(RUNNING, 0)
    t_a = feed.clock.wall()
    for _ in range(5):
        assert not feed.ls(RUNNING, 0).fault_changed
    assert feed.ls(RUNNING, 3).fault_changed
    t_b = feed.clock.wall()
    assert not feed.ls(RUNNING, 3).fault_changed
    assert not feed.ls(STOPPED, 3).fault_changed  # conveyor만 바뀜
    feed.off()
    assert not feed.ls(STOPPED, 3).fault_changed
    assert feed.t.fault_changes == (FaultChange(t_a, 0), FaultChange(t_b, 3))
    assert feed.t.fault_level_at(t_b - timedelta(milliseconds=1)) == 0
    assert feed.t.fault_level_at(t_b) == 3


def test_fault_level_kept_after_700s(feed):
    feed.ls(RUNNING, 6)
    start = feed.clock.wall()
    for _ in range(700):  # 700초 동안 1초마다 같은 값
        feed.ls(RUNNING, 6)
    now = feed.clock.wall()
    assert now - start == timedelta(seconds=700)
    assert feed.t.fault_level_at(now) == 6
    assert feed.t.fault_changes == (FaultChange(start, 6),)


def test_fault_changes_pruned_to_600s_plus_one(feed):
    # 10초마다 값을 바꿔 900초
    levels = []
    for i in range(90):
        feed.ls(RUNNING, i % 2, advance=10.0)
        levels.append((feed.clock.wall(), i % 2))
    now = feed.clock.wall()
    kept = feed.t.fault_changes
    cutoff = now - timedelta(seconds=600)
    older = [c for c in kept if c.timestamp < cutoff]
    assert len(older) == 1  # 600초보다 오래된 것은 가장 최근 하나만
    assert all(c.timestamp >= cutoff for c in kept[1:])
    assert feed.t.fault_level_at(cutoff - timedelta(milliseconds=1)) == older[0].fault_level
    assert feed.t.fault_level_at(now) == levels[-1][1]


def test_restart_event_rules(feed):
    # 기동 직후 첫 동기화(RUNNING)는 재가동 이벤트가 아니다
    assert not feed.ls(RUNNING, 0).restart
    # RUNNING → offline → RUNNING: 아님
    feed.off()
    assert not feed.ls(RUNNING, 0).restart
    # RUNNING → STOPPED → RUNNING: 재가동
    assert not feed.ls(STOPPED, 9).restart
    assert not feed.ls(STOPPED, 9).restart
    assert feed.ls(RUNNING, 0).restart
    assert not feed.ls(RUNNING, 0).restart
    # STOPPED → offline → RUNNING(정지 상태에서 simulator 재기동): 재가동
    feed.ls(STOPPED, 9)
    feed.off()
    feed.off()
    assert feed.ls(RUNNING, 0).restart
    # 기동 뒤 첫 수신이 STOPPED, 다음 RUNNING: 재가동
    other = Feed(feed.clock)
    assert not other.ls(STOPPED, 0).restart
    assert other.ls(RUNNING, 0).restart


def test_line_sensor_id_and_view(fake_clock):
    f = Feed(fake_clock, LineTracker("motor01"))
    assert f.t.line_sensor_id == "motor01"
    f.ls(RUNNING, 1, sensor="motor05")
    assert f.t.line_sensor_id == "motor05"
    f.off()
    assert f.t.line_sensor_id == "motor05"  # latest를 지우지 않으므로 유지
    v = f.t.view()
    assert (v.line_state, v.online, v.line_sensor_id, v.last_conveyor) == (UNKNOWN, False, "motor05", RUNNING)
    assert v.latest.sensor_id == "motor05" and v.latest_mono < v.last_mono
    assert v.fault_changes == f.t.fault_changes
    with pytest.raises(Exception):
        v.line_state = RUNNING  # 바뀌지 않는 뷰
