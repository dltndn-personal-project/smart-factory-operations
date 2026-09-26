"""StateStore (docs/spec/01-core.md 3절)."""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import numpy as np

from factory_operations.domain.state import PdmHistory, StateStore
from factory_operations.mqtt.payloads import PdmResult, SensorChunk


def pdm(ts, state="NORMAL", hi=95, score=0.05, sensor="motor01"):
    return PdmResult(sensor, ts, score, hi, state, ts - timedelta(seconds=1), "v1")


def chunk(ts, seq):
    a = np.zeros(10, dtype=np.float32)
    return SensorChunk("motor01", ts, seq, 10000, 1800.0, 40.0, a, a, a)


def test_snapshot_view_copies(fake_clock):
    st = StateStore(history_s=120, vibration_window_chunks=3)
    t0 = fake_clock.wall()
    st.add_pdm(pdm(t0), fake_clock.wall(), fake_clock.mono())
    st.add_vibration(chunk(t0, 1), fake_clock.wall(), fake_clock.mono())
    st.incr(("rejected", "factory/line/status", "invalid_json"))
    st.set_line("line-view-1")
    v1 = st.snapshot_view()

    # 뒤에 바꿔도 앞서 꺼낸 뷰의 컨테이너는 바뀌지 않는다(얕은 복사)
    st.add_pdm(pdm(t0 + timedelta(seconds=0.5), "CRITICAL", 20, 0.8), fake_clock.wall(), fake_clock.mono())
    st.add_pdm(pdm(t0, sensor="motor02"), fake_clock.wall(), fake_clock.mono())
    st.add_vibration(chunk(t0, 2), fake_clock.wall(), fake_clock.mono())
    st.incr(("rejected", "factory/line/status", "invalid_json"))
    st.set_line("line-view-2")
    st.mqtt_connected = True
    st.set_db_ok(True)
    assert len(v1.pdm_history["motor01"]) == 1
    assert set(v1.pdm_latest) == {"motor01"} and v1.pdm_latest["motor01"].value.state == "NORMAL"
    assert len(v1.vibration_ring) == 1
    assert v1.counters == {("rejected", "factory/line/status", "invalid_json"): 1}
    assert v1.line == "line-view-1"
    assert (v1.mqtt_connected, v1.db_ok) == (False, False)

    v2 = st.snapshot_view()
    assert len(v2.pdm_history["motor01"]) == 2 and v2.pdm_latest["motor01"].value.state == "CRITICAL"
    assert set(v2.pdm_history) == {"motor01", "motor02"}
    assert [r.value.seq for r in v2.vibration_ring] == [1, 2]
    assert v2.counters[("rejected", "factory/line/status", "invalid_json")] == 2
    assert (v2.line, v2.mqtt_connected, v2.db_ok) == ("line-view-2", True, True)
    # 원소는 같은 객체(복사하지 않음)
    assert v2.pdm_history["motor01"][0] is v1.pdm_history["motor01"][0]
    assert isinstance(v2.pdm_history["motor01"], tuple) and isinstance(v2.vibration_ring, tuple)

    # 락 안에서 꺼낸다: 락을 쥐고 있으면 snapshot_view가 기다린다
    done = threading.Event()
    st._lock.acquire()
    try:
        t = threading.Thread(target=lambda: (st.snapshot_view(), done.set()))
        t.start()
        time.sleep(0.05)
        assert not done.is_set()
    finally:
        st._lock.release()
    t.join(2)
    assert done.is_set()


def test_pdm_history_trims_120s(fake_clock):
    st = StateStore(history_s=120)
    t0 = fake_clock.wall()
    for i in range(401):  # 0.5초 간격 200초
        st.add_pdm(pdm(t0 + timedelta(seconds=0.5 * i)), fake_clock.wall(), fake_clock.mono())
    hist = st.pdm_history("motor01")
    newest = t0 + timedelta(seconds=200)
    assert hist[-1].timestamp == newest
    assert hist[0].timestamp == newest - timedelta(seconds=120)
    assert len(hist) == 241
    assert all(a.timestamp < b.timestamp for a, b in zip(hist, hist[1:]))
    assert st.snapshot_view().pdm_history["motor01"] == hist
    assert st.pdm_history("nosensor") == ()


def test_pdm_history_orders_and_dedupes(fake_clock):
    h = PdmHistory(120)
    t0 = fake_clock.wall()
    for s in (1.0, 0.5, 2.0, 1.5):
        h.add(pdm(t0 + timedelta(seconds=s)))
    h.add(pdm(t0 + timedelta(seconds=1.0), "WARNING", 50, 0.5))  # 같은 timestamp 다시 옴
    items = h.items()
    assert [(r.timestamp - t0).total_seconds() for r in items] == [0.5, 1.0, 1.5, 2.0]
    assert items[1].state == "WARNING"
    # 늦게 온 오래된 결과는 창 밖이면 바로 빠진다
    h.add(pdm(t0 - timedelta(seconds=500)))
    assert len(h) == 4


def test_vibration_ring_maxlen_and_reset(fake_clock):
    st = StateStore(vibration_window_chunks=3)
    t0 = fake_clock.wall()
    for seq in range(5):
        st.add_vibration(chunk(t0, seq), fake_clock.wall(), fake_clock.mono())
    assert [r.value.seq for r in st.snapshot_view().vibration_ring] == [2, 3, 4]
    assert st.last_vibration().value.seq == 4
    st.add_vibration(chunk(t0, 10), fake_clock.wall(), fake_clock.mono(), reset=True)
    assert [r.value.seq for r in st.snapshot_view().vibration_ring] == [10]


def test_other_slots(fake_clock):
    st = StateStore()
    assert st.last_vibration() is None
    st.set_spectrum("panels", fake_clock.wall(), fake_clock.mono())
    st.set_interlock("il")
    st.set_summary({"n": 1}, fake_clock.wall(), fake_clock.mono())
    st.set_correlation({"status": "ok"})
    v = st.snapshot_view()
    assert v.spectrum_latest.value == "panels" and v.spectrum_latest.mono == fake_clock.mono()
    assert (v.interlock, v.summary.value, v.correlation) == ("il", {"n": 1}, {"status": "ok"})


def test_from_config():
    from factory_operations.config import load_config

    st = StateStore.from_config(load_config({}))
    assert (st.history_s, st.vibration_window_chunks) == (120, 10)
