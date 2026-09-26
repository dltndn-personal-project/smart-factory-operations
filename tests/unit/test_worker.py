"""워커 처리 함수 `Processor` (docs/spec/03-control.md 2·3.4절, 02 3절).

`H`는 `test_interlock.py`·`test_alarm.py`도 쓰는 시나리오 도구다: 가짜 시계·가짜 발행기·가짜 DB 싱크로
`Processor`를 직접 부른다. PdM 메시지는 `fixtures.payloads.pdm`으로만 만든다(D-39).
"""

from __future__ import annotations

import json
from concurrent.futures import Future
from datetime import datetime, timedelta

import numpy as np
import pytest

from factory_operations.clock import iso_ms
from factory_operations.config import load_config
from factory_operations.domain.state import StateStore
from factory_operations.domain.worker import Inbound, OperatorCommand, OperatorCommandError, Processor
from factory_operations.mqtt.payloads import LastCommand
from fixtures.payloads import pdm

S = timedelta(seconds=1)
HI = {"NORMAL": 95, "CAUTION": 70, "WARNING": 50, "CRITICAL": 20}


class H:
    """시나리오 도구. `t0`는 임의 Simulator 시각(가짜 시계 시작 벽시계). `at`은 t0부터의 초."""

    def __init__(self, clock, publisher, db, cfg=None):
        self.cfg = cfg or load_config({})
        self.clock = clock
        self.pub = publisher
        self.db = db
        self.state = StateStore.from_config(self.cfg)
        self.p = Processor(self.cfg, self.state, publisher, db, clock)
        self.t0 = clock.wall()

    # --- 입력 ---------------------------------------------------------
    def ts(self, at: float) -> datetime:
        return self.t0 + timedelta(seconds=at)

    def send(self, topic: str, obj, retain: bool = False) -> None:
        raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.p.handle(Inbound(topic, raw, retain, self.clock.wall(), self.clock.mono()))

    def ls(self, conveyor="RUNNING", at=None, fault=0, last_command=None, production=True, sensor="motor01"):
        at = (self.clock.wall() - self.t0).total_seconds() if at is None else at
        msg = {
            "schema_version": 1,
            "online": True,
            "timestamp": iso_ms(self.ts(at)),
            "conveyor": conveyor,
            "fault_level": fault,
            "motor_rpm": 1800.0 if conveyor == "RUNNING" else 0.0,
            "sensor_id": sensor,
            "production_active": production and conveyor == "RUNNING",
            "products": {"spawned": 1, "created": 1, "expired": 0, "in_flight": 0, "last_product_id": None},
            "last_command": last_command,
        }
        self.send("factory/line/status", msg, retain=True)

    def off(self):
        self.send("factory/line/status", {"schema_version": 1, "online": False}, retain=True)

    def pdm(self, state: str, at: float, sensor="motor01"):
        hi = HI[state]
        self.send("factory/pdm/result", pdm.pdm_result(sensor, self.ts(at), state, hi, round(1 - hi / 100, 4)))

    def result(self, command_id, result="APPLIED", conveyor="STOPPED", at=None, error=None, command="STOP"):
        lc = {
            "command": command,
            "command_id": command_id,
            "source": "mqtt",
            "received_at": iso_ms(self.clock.wall()),
            "result": result,
            "reason": "INTERLOCK_CRITICAL",
            "error": error,
        }
        self.ls(conveyor, at=at, last_command=lc)

    def operator(self, command: str) -> Future:
        f: Future = Future()
        self.p.handle(OperatorCommand(command, f))
        return f

    def advance(self, s: float) -> None:
        self.clock.advance(s)

    def tick(self) -> None:
        self.p.tick()

    # --- 관찰 ---------------------------------------------------------
    def published(self, topic: str) -> list[dict]:
        return [json.loads(p) for t, p, _q, _r in self.pub.sent if t == topic]

    @property
    def stops(self) -> list[dict]:
        return [m for m in self.published("factory/control/conveyor") if m["command"] == "STOP"]

    @property
    def alarm_events(self) -> list[dict]:
        return self.published("factory/alarm/event")

    def jobs(self, kind: str) -> list:
        return [j for j in self.db.jobs if j.kind == kind]

    @property
    def pending(self):
        return self.p.interlock.pending


@pytest.fixture
def h(fake_clock, fake_publisher, fake_db_sink):
    return H(fake_clock, fake_publisher, fake_db_sink)


# ---------------------------------------------------------------------------
# 명령 결과 확인 (3.4절)


def test_known_command_result_updates(h):
    h.ls("RUNNING", at=0)
    h.pdm("CRITICAL", at=1)
    (stop,) = h.stops
    h.advance(0.3)
    h.result(stop["command_id"], "APPLIED")
    (res,) = h.jobs("control_result")
    assert (res.command_id, res.result, res.error) == (stop["command_id"], "APPLIED", None)
    assert res.observed_at == h.clock.wall()
    assert res.result_received_at == h.clock.wall().replace(microsecond=h.clock.wall().microsecond // 1000 * 1000)
    assert h.pending is None
    assert h.jobs("control_observed") == []
    # REJECTED도 result 작업은 만들지만 대기는 유지한다(3.2절)
    h.ls("RUNNING", at=10)
    h.pdm("CRITICAL", at=11)
    stop2 = h.stops[-1]
    h.result(stop2["command_id"], "REJECTED", conveyor="RUNNING", error="bad")
    assert h.jobs("control_result")[-1].result == "REJECTED"
    assert h.pending is not None and h.pending.command_id == stop2["command_id"]


def test_unknown_command_observed_insert(h):
    h.ls("RUNNING", at=0)
    lc = {
        "command": "STOP",
        "command_id": "local-123",
        "source": "local",
        "received_at": iso_ms(h.clock.wall()),
        "result": "APPLIED",
        "reason": None,
        "error": None,
    }
    h.ls("STOPPED", at=1, last_command=lc)
    (obs,) = h.jobs("control_observed")
    assert (obs.command_id, obs.command, obs.source, obs.result, obs.reason) == ("local-123", "STOP", "local", "APPLIED", None)
    assert obs.observed_at == obs.recorded_at == h.clock.wall()
    assert h.jobs("control_result") == []


def test_same_last_command_once(h):
    h.ls("RUNNING", at=0)
    h.pdm("CRITICAL", at=1)
    cid = h.stops[0]["command_id"]
    for i in range(5):  # Line Status가 1초마다 같은 last_command를 싣고 온다
        h.advance(1)
        h.result(cid, "APPLIED")
    assert len(h.jobs("control_result")) == 1
    for i in range(3):
        h.ls("STOPPED", last_command={"command": "START", "command_id": "loc-1", "source": "local", "received_at": None, "result": "APPLIED", "reason": None, "error": None})
    assert len(h.jobs("control_observed")) == 1


def test_null_command_id_not_recorded(h):
    lc = {"command": None, "command_id": None, "source": "mqtt", "received_at": iso_ms(h.clock.wall()), "result": "REJECTED", "reason": None, "error": "retained_ignored"}
    h.ls("RUNNING", at=0, last_command=lc)
    assert h.jobs("control_result") == [] and h.jobs("control_observed") == []
    assert len(h.jobs("line_change")) == 1


def test_issued_and_seen_are_bounded(h):
    for _ in range(105):
        assert h.operator("STOP").result()["command"] == "STOP"
    assert len(h.p.issued) == 100
    for i in range(210):
        h.p._check_command_result(LastCommand("APPLIED", f"x-{i}", "STOP", "local", None, None, None))
    assert len(h.p.seen) == 200


# ---------------------------------------------------------------------------
# 처리 순서 (2절)


def vibration(ts: datetime, seq: int, n=1000, rate=10000, sensor="motor01", rpm=1800.0):
    rng = np.random.default_rng(seq)
    return {
        "schema_version": 1,
        "sensor_id": sensor,
        "timestamp": iso_ms(ts),
        "seq": seq,
        "sample_rate_hz": rate,
        "rpm": rpm,
        "temperature": 40.0,
        **{f"vibration_{a}": [round(float(v), 4) for v in rng.normal(0, 0.05, n)] for a in "xyz"},
    }


def test_sensor_chunk_joined_and_ringed(h):
    # Line Status 전에 온 chunk는 fault_level null
    h.send("factory/sensor/motor01/vibration", vibration(h.ts(-1), 1))
    h.ls("RUNNING", at=0, fault=3)
    h.ls("RUNNING", at=5, fault=6)
    for seq, at in ((2, 0.0), (3, 4.9), (4, 5.0), (5, 5.1)):
        h.send("factory/sensor/motor01/vibration", vibration(h.ts(at), seq))
    jobs = h.jobs("sensor")
    assert [j.fault_level for j in jobs] == [None, 3, 3, 6, 6]
    j = jobs[1]
    assert (j.sensor_id, j.seq, j.sample_rate_hz, j.rpm, j.temperature) == ("motor01", 2, 10000, 1800.0, 40.0)
    assert j.vibration_x.dtype == np.float32 and len(j.vibration_z) == 1000
    assert j.received_at == h.clock.wall()
    # 라인 센서 chunk만 링에 들어간다
    h.send("factory/sensor/motor02/vibration", vibration(h.ts(5.2), 6, sensor="motor02"))
    assert len(h.jobs("sensor")) == 6
    ring = h.state.snapshot_view().vibration_ring
    assert [r.value.seq for r in ring] == [1, 2, 3, 4, 5]
    # 링 크기(10)를 넘으면 오래된 것부터
    for seq in range(6, 20):
        h.send("factory/sensor/motor01/vibration", vibration(h.ts(5 + seq / 10), seq))
    assert [r.value.seq for r in h.state.snapshot_view().vibration_ring] == list(range(10, 20))


def test_ring_resets_on_format_or_seq_gap(h):
    h.ls("RUNNING", at=0)
    for seq in (1, 2, 3):
        h.send("factory/sensor/motor01/vibration", vibration(h.ts(seq / 10), seq))
    ring = lambda: [r.value.seq for r in h.state.snapshot_view().vibration_ring]  # noqa: E731
    assert ring() == [1, 2, 3]
    h.send("factory/sensor/motor01/vibration", vibration(h.ts(0.5), 5))  # seq 건너뜀
    assert ring() == [5]
    h.send("factory/sensor/motor01/vibration", vibration(h.ts(0.6), 6, n=500))  # 배열 길이 바뀜
    assert ring() == [6]
    h.send("factory/sensor/motor01/vibration", vibration(h.ts(0.7), 7, n=500, rate=5000))  # 샘플링 바뀜
    assert ring() == [7]
    h.send("factory/sensor/motor01/vibration", vibration(h.ts(0.8), 8, n=500, rate=5000))
    assert ring() == [7, 8]
    h.send("factory/sensor/motor01/vibration", vibration(h.ts(0.9), 0, n=500, rate=5000))  # 재기동(seq 감소)
    assert ring() == [0]
    assert len(h.jobs("sensor")) == 8  # DB 기록은 모두


def test_vision_joined_health_index(h):
    h.ls("RUNNING", at=0)
    h.pdm("NORMAL", at=10.0)
    h.pdm("CAUTION", at=10.5)
    h.pdm("NORMAL", at=10.0, sensor="motor02")
    product = {"schema_version": 1, "product_id": "P-00000001", "timestamp": iso_ms(h.ts(10.7)), "image_path": "products/P-00000001.jpg"}
    h.send("factory/product/created", product)
    (pj,) = h.jobs("product")
    assert (pj.product_id, pj.timestamp, pj.image_path) == ("P-00000001", h.ts(10.7), "products/P-00000001.jpg")
    vision = {
        "schema_version": 1,
        "product_id": "P-00000001",
        "timestamp": iso_ms(h.ts(10.7)),
        "defect": True,
        "defect_type": "scratch",
        "confidence": None,
        "bbox": None,
        "image_path": "products/P-00000001.jpg",
        "gradcam_path": None,
        "judgement_source": "PASS_THROUGH",
    }
    h.send("factory/vision/result", vision)
    (ij,) = h.jobs("inspection")
    assert (ij.sensor_id, ij.health_index_at_time, ij.anomaly_score_at_time, ij.pdm_timestamp_at_time) == (
        "motor01",
        HI["CAUTION"],
        0.3,
        h.ts(10.5),
    )
    assert (ij.defect, ij.defect_type, ij.judgement_source) == (True, "scratch", "PASS_THROUGH")
    # 결과가 max_gap_s(5초)보다 오래되면 null, sensor_id는 라인 센서
    h.send("factory/vision/result", {**vision, "product_id": "P-00000002", "timestamp": iso_ms(h.ts(15.6))})
    j2 = h.jobs("inspection")[-1]
    assert (j2.sensor_id, j2.health_index_at_time, j2.pdm_timestamp_at_time) == ("motor01", None, None)


def test_spectrum_only_line_sensor(h):
    h.ls("RUNNING", at=0, sensor="motor01")
    h.send("factory/pdm/spectrum", pdm.pdm_spectrum("motor02", h.ts(1)))
    assert h.state.snapshot_view().spectrum_latest is None
    h.send("factory/pdm/spectrum", pdm.pdm_spectrum("motor01", h.ts(1)))
    sp = h.state.snapshot_view().spectrum_latest
    assert sp.value.sensor_id == "motor01" and sp.value.timestamp == h.ts(1)
    h.send("factory/pdm/spectrum", pdm.pdm_spectrum("motor01", h.ts(2)))
    assert h.state.snapshot_view().spectrum_latest.value.timestamp == h.ts(2)
    assert h.db.jobs == [j for j in h.db.jobs if j.kind == "line_change"]  # 스펙트럼은 DB에 쓰지 않는다


def test_line_change_job_only_on_change(h):
    h.ls("RUNNING", at=0, fault=3)
    for at in range(1, 6):
        h.ls("RUNNING", at=at, fault=3)
    assert len(h.jobs("line_change")) == 1
    h.ls("RUNNING", at=6, fault=4)
    h.off()
    h.off()
    h.ls("STOPPED", at=8, fault=4)
    jobs = h.jobs("line_change")
    assert len(jobs) == 4
    first, second, off, back = jobs
    assert (first.online, first.conveyor, first.fault_level, first.timestamp, first.sensor_id) == (True, "RUNNING", 3, h.ts(0), "motor01")
    assert second.fault_level == 4
    assert (off.online, off.timestamp, off.conveyor, off.fault_level) == (False, None, None, None)
    assert (back.online, back.conveyor) == (True, "STOPPED")
    assert all(j.received_at == h.clock.wall() for j in jobs)
    # 화면용 라인 뷰가 StateStore에 있다
    assert h.state.snapshot_view().line.line_state == "STOPPED"


def test_rejected_message_counted(h):
    h.send("factory/line/status", b"{not json")
    h.send("factory/pdm/result", {"schema_version": 1, "sensor_id": "motor01"})
    h.send("factory/sensor/motor02/vibration", vibration(h.ts(0), 1, sensor="motor01"))
    h.send("factory/unknown/topic", {"schema_version": 1})
    h.send("factory/line/status", b"{not json")
    assert h.db.jobs == []
    assert h.pub.calls == []
    c = h.state.snapshot_view().counters
    assert c[("rejected", "factory/line/status", "invalid_json")] == 2
    assert c[("rejected", "factory/pdm/result", "missing_field:timestamp")] == 1
    assert c[("rejected", "factory/sensor/motor02/vibration", "topic_mismatch")] == 1
    assert c[("rejected", "factory/unknown/topic", "unknown_topic")] == 1
    v = h.state.snapshot_view()
    assert v.line.online is None and v.pdm_latest == {}


def test_pdm_recorded_and_state(h):
    h.ls("RUNNING", at=0)
    h.pdm("CAUTION", at=1)
    (e,) = h.jobs("equipment")
    assert (e.sensor_id, e.timestamp, e.window_start, e.health_index, e.state, e.model_version) == (
        "motor01",
        h.ts(1),
        h.ts(0),
        70,
        "CAUTION",
        "v1",
    )
    v = h.state.snapshot_view()
    assert v.pdm_latest["motor01"].value.state == "CAUTION"
    assert [r.timestamp for r in v.pdm_history["motor01"]] == [h.ts(1)]
    assert v.interlock.judged.state == "CAUTION"


def test_db_queue_full_counted(h):
    h.db.full = True
    h.ls("RUNNING", at=0)
    assert h.state.snapshot_view().counters[("db_queue_overflow", "line_change")] == 1


def test_operator_command_results(h):
    f = h.operator("STOP")
    r = f.result(0)
    assert r["command"] == "STOP" and r["judged_state"] is None
    (msg,) = h.published("factory/control/conveyor")
    assert msg["reason"] == "OPERATOR_STOP" and msg["command_id"] == r["command_id"] and msg["timestamp"] == r["timestamp"]
    (job,) = h.jobs("control_issued")
    assert (job.command, job.reason, job.trigger_sensor_id, job.trigger_timestamp) == ("STOP", "OPERATOR_STOP", None, None)
    bad = h.operator("PAUSE")
    with pytest.raises(OperatorCommandError) as ei:
        bad.result(0)
    assert ei.value.code == "invalid_command"
    # 이미 취소된 future는 건드리지 않는다
    f = Future()
    f.cancel()
    h.p.handle(OperatorCommand("START", f))
    assert f.cancelled()
