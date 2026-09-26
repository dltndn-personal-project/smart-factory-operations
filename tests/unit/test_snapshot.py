"""`/api/snapshot` 만들기 `build_snapshot` (docs/spec/06-dashboard.md 3·4절, 08-verification.md 3.5절).

StateStore에 파싱한 메시지·LineTracker 뷰·Interlock 뷰·DB 요약(psycopg 원형 값)을 직접 넣고
가짜 시계로 판정 경계를 본다. PdM 메시지는 `fixtures.payloads.pdm`으로만 만든다(D-39).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta

import numpy as np
import pytest

from factory_operations.clock import TS_PATTERN, iso_ms
from factory_operations.config import load_config
from factory_operations.domain.interlock import Interlock
from factory_operations.domain.line import LineTracker
from factory_operations.domain.state import StateStore
from factory_operations.mqtt import payloads as P
from factory_operations.web.snapshot import build_snapshot, minmax_buckets
from fixtures.payloads import pdm

S = timedelta(seconds=1)
TS_RE = re.compile(TS_PATTERN)
TIME_KEYS = {
    "generated_at",
    "timestamp",
    "received_at",
    "window_start",
    "reference_time",
    "last_trigger_timestamp",
    "summary_at",
    "raised_at",
    "issued_at",
    "trigger_timestamp",
    "result_received_at",
    "recorded_at",
    "computed_at",
    "start",
}


class W:
    """스냅숏 시나리오 도구: StateStore·LineTracker·Interlock을 가짜 시계로 채운다."""

    def __init__(self, clock, cfg=None):
        self.cfg = cfg or load_config({})
        self.clock = clock
        self.state = StateStore.from_config(self.cfg)
        self.line = LineTracker(self.cfg.line.sensor_id)
        self.interlock = Interlock(self.cfg.interlock.pending_timeout_s)
        self.t0 = clock.wall()
        self.state.set_line(self.line.view())
        self.state.set_interlock(self.interlock.view())

    def ts(self, at: float) -> datetime:
        return self.t0 + timedelta(seconds=at)

    def ls(self, conveyor="RUNNING", at=0.0, fault=0, last_command=None):
        msg = {
            "schema_version": 1,
            "online": True,
            "timestamp": iso_ms(self.ts(at)),
            "conveyor": conveyor,
            "fault_level": fault,
            "motor_rpm": 1800.0 if conveyor == "RUNNING" else 0.0,
            "sensor_id": "motor01",
            "production_active": conveyor == "RUNNING",
            "products": {"spawned": 9, "created": 8, "expired": 0, "in_flight": 1, "last_product_id": "P-00000008"},
            "last_command": last_command,
        }
        parsed = P.parse_line_status("factory/line/status", json.dumps(msg).encode())
        assert not isinstance(parsed, P.Rejected), parsed
        upd = self.line.update(parsed, self.clock.wall(), self.clock.mono())
        if upd.reference_changed:
            self.interlock.on_reference_changed(self.line.reference_time)
        self.state.set_line(self.line.view())
        self.state.set_interlock(self.interlock.view())

    def off(self):
        self.line.update(P.LineOffline(), self.clock.wall(), self.clock.mono())
        self.state.set_line(self.line.view())

    def pdm(self, state="NORMAL", at=0.0, hi=95, score=0.05):
        raw = pdm.to_bytes(pdm.pdm_result("motor01", self.ts(at), state, hi, score))
        r = P.parse_pdm_result("factory/pdm/result", raw)
        assert not isinstance(r, P.Rejected), r
        self.state.add_pdm(r, self.clock.wall(), self.clock.mono())
        self.interlock.observe(r)
        self.state.set_interlock(self.interlock.view())
        return r

    def spectrum(self, at=0.0):
        raw = pdm.to_bytes(pdm.pdm_spectrum("motor01", self.ts(at)))
        sp = P.parse_pdm_spectrum("factory/pdm/spectrum", raw)
        assert not isinstance(sp, P.Rejected), sp
        self.state.set_spectrum(sp, self.clock.wall(), self.clock.mono())

    def chunk(self, seq, x, y=None, z=None, at=0.0, rate=10000):
        arr = lambda v: np.asarray(v, dtype=np.float32)  # noqa: E731
        y = x if y is None else y
        z = x if z is None else z
        c = P.SensorChunk("motor01", self.ts(at), seq, rate, 1800.0, 41.23, arr(x), arr(y), arr(z))
        self.state.add_vibration(c, self.clock.wall(), self.clock.mono())

    def snap(self) -> dict:
        return build_snapshot(self.state.snapshot_view(), self.clock.wall(), self.clock.mono(), self.cfg)


@pytest.fixture
def w(fake_clock):
    return W(fake_clock)


def summary_rows(clock, n_insp=30, n_alarm=30, n_ctrl=30):
    """05 5절 요약 dict(psycopg 원형: aware datetime, UUID, int 목록)."""
    t = clock.wall()
    inspections = [
        {
            "product_id": f"P-{i:08d}",
            "timestamp": t - i * S,
            "defect": i % 3 == 0,
            "defect_type": "scratch" if i % 3 == 0 else None,
            "confidence": 0.8999999761581421,
            "bbox": [1, 2, 3, 4] if i % 2 else None,
            "image_path": f"products/P-{i:08d}.jpg",
            "gradcam_path": None,
            "judgement_source": "PASS_THROUGH",
            "health_index_at_time": 22,
        }
        for i in range(1, n_insp + 1)
    ]
    alarms = [
        {
            "alarm_id": uuid.uuid4(),
            "timestamp": t - i * S,
            "raised_at": t - i * S,
            "sensor_id": "motor01",
            "severity": "CRITICAL",
            "previous_state": "WARNING",
            "health_index": 18,
            "anomaly_score": 0.82,
        }
        for i in range(n_alarm)
    ]
    controls = [
        {
            "command_id": str(uuid.uuid4()),
            "command": "STOP",
            "reason": "INTERLOCK_CRITICAL",
            "origin": "operations",
            "source": None,
            "issued_at": t - i * S,
            "trigger_timestamp": t - i * S,
            "result": "APPLIED" if i else None,
            "result_received_at": t - i * S if i else None,
            "error": None,
            "recorded_at": t - i * S,
        }
        for i in range(n_ctrl)
    ]
    return {
        "produced": 113,
        "inspected": 111,
        "defects": 14,
        "inspections": inspections,
        "alarms": alarms,
        "controls": controls,
        "summary_at": t,
    }


def correlation_result(clock, n_curve=31, n_bins=20):
    point = {"lag_s": 13, "n": 131, "pearson": 0.4123, "spearman": 0.3981, "reason": None}
    return {
        "computed_at": iso_ms(clock.wall()),
        "n_inspections": 150,
        "default_lag_s": 13,
        "at_default": dict(point),
        "best": dict(point),
        "curve": [dict(point, lag_s=i) for i in range(n_curve)],
        "bins": [
            {"start": iso_ms(clock.wall() - (n_bins - i) * 30 * S), "n_inspected": 15, "defect_rate": 0.0667, "mean_anomaly": 0.213}
            for i in range(n_bins)
        ],
    }


def iter_times(obj, path=""):
    """시각 필드(`TIME_KEYS`) 값을 경로와 함께 모두 꺼낸다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in TIME_KEYS:
                yield f"{path}.{k}", v
            yield from iter_times(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_times(v, f"{path}[{i}]")


# ---------------------------------------------------------------------------


def test_empty_snapshot(w):
    s = w.snap()
    assert s["schema_version"] == 1
    for k in ("line", "pdm", "spectrum", "vibration"):
        assert s[k] == {"status": "NONE"}
    assert s["interlock"] == {
        "line_state": "UNKNOWN",
        "reference_time": None,
        "judged": None,
        "pending_stop": None,
        "last_trigger_timestamp": None,
    }
    assert (s["production"], s["inspections"], s["alarms"], s["controls"], s["correlation"]) == (None, [], [], [], None)
    assert s["counters"] == {"rejected": {}, "queue_overflow": 0}
    json.dumps(s, allow_nan=False)


def test_pdm_live_stale_boundary(w):
    w.ls("RUNNING", at=0)
    w.pdm("CRITICAL", at=1, hi=18, score=0.82)
    w.clock.advance(2.0)
    s = w.snap()["pdm"]
    assert (s["status"], s["age_s"]) == ("LIVE", 2.0)
    assert (s["state"], s["health_index"], s["anomaly_score"]) == ("CRITICAL", 18, 0.82)
    assert s["timestamp"] == iso_ms(w.ts(1)) and s["window_start"] == iso_ms(w.ts(0))
    w.clock.advance(0.1)
    s = w.snap()["pdm"]
    assert (s["status"], s["age_s"]) == ("STALE", 2.1)
    # 새 결과를 받으면 다시 LIVE
    w.pdm("CRITICAL", at=3.5, hi=18, score=0.82)
    assert w.snap()["pdm"]["status"] == "LIVE"


def test_pdm_other_sensor_ignored(w):
    w.ls("RUNNING", at=0)
    raw = pdm.to_bytes(pdm.pdm_result("motor02", w.ts(1), "NORMAL", 95, 0.05))
    r = P.parse_pdm_result("factory/pdm/result", raw)
    w.state.add_pdm(r, w.clock.wall(), w.clock.mono())
    assert w.snap()["pdm"] == {"status": "NONE"}


def test_pdm_history(w):
    w.ls("RUNNING", at=0)
    for i in range(300):  # 150초 분량, 0.5초 hop
        w.pdm("NORMAL", at=i * 0.5, hi=90 + i % 5, score=0.1)
    h = w.snap()["pdm"]["history"]
    assert 1 <= len(h) <= 240
    ts = [x["timestamp"] for x in h]
    assert ts == sorted(ts)  # 오래된 것부터
    assert ts[-1] == iso_ms(w.ts(299 * 0.5))
    assert (w.ts(299 * 0.5) - w.ts(0)) > timedelta(seconds=120)  # 120초 밖은 빠졌다
    assert set(h[0]) == {"timestamp", "anomaly_score", "health_index", "state"}


def test_before_restart(w):
    w.ls("RUNNING", at=0)
    w.pdm("CRITICAL", at=5, hi=18, score=0.82)
    assert w.snap()["pdm"]["before_restart"] is False
    # 정지 → 재가동: reference_time = 10초. 5초 결과는 재가동 전 판정
    w.ls("STOPPED", at=8)
    w.ls("RUNNING", at=10)
    s = w.snap()
    assert s["interlock"]["reference_time"] == iso_ms(w.ts(10))
    assert s["pdm"]["before_restart"] is True
    assert s["interlock"]["judged"] is None  # Interlock 판단에서 빠졌다
    # 기준 시각과 같은 timestamp도 재가동 전(timestamp ≤ reference_time)
    w.pdm("NORMAL", at=10)
    assert w.snap()["pdm"]["before_restart"] is True
    w.pdm("CRITICAL", at=10.5, hi=18, score=0.82)
    s = w.snap()
    assert s["pdm"]["before_restart"] is False
    assert s["interlock"]["judged"] == {"timestamp": iso_ms(w.ts(10.5)), "state": "CRITICAL"}


def test_line_status_states(w):
    assert w.snap()["line"] == {"status": "NONE"}
    lc = {
        "command": "STOP",
        "command_id": "9f1c2e7a-4b1d-4e0a-9a51-0f3b2c7d8e11",
        "source": "mqtt",
        "received_at": iso_ms(w.ts(0)),
        "result": "APPLIED",
        "reason": "INTERLOCK_CRITICAL",
        "error": None,
    }
    w.ls("RUNNING", at=0, fault=8, last_command=lc)
    s = w.snap()["line"]
    assert s["status"] == "LIVE"
    assert (s["conveyor"], s["fault_level"], s["motor_rpm"], s["production_active"], s["sensor_id"]) == (
        "RUNNING",
        8,
        1800.0,
        True,
        "motor01",
    )
    assert s["products"] == {"spawned": 9, "created": 8, "expired": 0, "in_flight": 1, "last_product_id": "P-00000008"}
    assert s["last_command"] == lc
    assert s["timestamp"] == iso_ms(w.ts(0)) and s["received_at"] == iso_ms(w.clock.wall())
    w.clock.advance(3.0)
    assert w.snap()["line"]["status"] == "LIVE"  # 3.0 ≤ line_stale_s
    w.clock.advance(0.1)
    s = w.snap()["line"]
    assert (s["status"], s["age_s"], s["conveyor"]) == ("STALE", 3.1, "RUNNING")  # 마지막 conveyor 유지
    w.off()
    s = w.snap()
    assert s["line"]["status"] == "OFFLINE"
    assert s["line"]["conveyor"] == "RUNNING" and s["line"]["fault_level"] == 8  # 마지막 online 값
    assert s["interlock"]["line_state"] == "UNKNOWN"
    w.clock.advance(10)
    assert w.snap()["line"]["status"] == "OFFLINE"  # 오래되어도 OFFLINE
    w.ls("STOPPED", at=20)
    s = w.snap()["line"]
    assert (s["status"], s["conveyor"], s["age_s"]) == ("LIVE", "STOPPED", 0.0)


def test_line_offline_without_online(w):
    w.off()
    s = w.snap()["line"]
    assert s["status"] == "OFFLINE"
    assert s["conveyor"] is None and s["timestamp"] is None and s["age_s"] is None


def test_vibration_minmax_buckets(w):
    # chunk 10개 × 1000샘플, seq 순서가 뒤섞여 들어와도 seq 순으로 잇는다
    base = np.arange(10000, dtype=np.float64) / 10000.0  # 0.0000 ~ 0.9999
    order = [3, 0, 1, 2, 4, 5, 6, 7, 9, 8]
    for seq in order:
        part = base[seq * 1000 : (seq + 1) * 1000]
        w.chunk(100 + seq, part, -part, part * 2, at=seq * 0.1)
    s = w.snap()["vibration"]
    assert s["status"] == "LIVE"
    assert (s["window_s"], s["sample_rate_hz"], s["rpm"], s["temperature"]) == (1.0, 10000, 1800.0, 41.23)
    assert s["timestamp"] == iso_ms(w.ts(0.9))  # seq가 가장 큰 chunk
    assert len(s["x"]["min"]) == len(s["x"]["max"]) == 500
    # 구간 i = 샘플 [20i, 20i+20)
    assert s["x"]["min"][:3] == [0.0, 0.002, 0.004]
    assert s["x"]["max"][:3] == [0.0019, 0.0039, 0.0059]
    assert s["x"]["max"][-1] == 0.9999
    assert s["y"]["min"][0] == -0.0019 and s["y"]["max"][0] == 0.0
    assert s["z"]["max"][-1] == 1.9998
    # 임펄스 하나는 띠에 남는다(D-31)
    spike = np.zeros(1000)
    spike[517] = 3.25
    w.state.add_vibration(
        P.SensorChunk("motor01", w.ts(1.0), 200, 10000, 1800.0, 41.0, *(np.asarray(spike, np.float32),) * 3),
        w.clock.wall(),
        w.clock.mono(),
        reset=True,
    )
    s = w.snap()["vibration"]
    assert max(s["x"]["max"]) == 3.25 and len(s["x"]["max"]) == 500
    # 1초 넘게 새 chunk가 없으면 STALE
    w.clock.advance(1.0)
    assert w.snap()["vibration"]["status"] == "LIVE"
    w.clock.advance(0.1)
    assert w.snap()["vibration"]["status"] == "STALE"


def test_vibration_fewer_samples_than_buckets(w):
    w.chunk(1, [0.5, -0.25, 0.125])
    w.chunk(2, [1.0, 2.0])
    s = w.snap()["vibration"]
    assert s["x"] == {"min": [0.5, -0.25, 0.125, 1.0, 2.0], "max": [0.5, -0.25, 0.125, 1.0, 2.0]}
    assert s["window_s"] == 5 / 10000
    # 나누어떨어지지 않는 경우: 구간 길이 차이 1 이하, 모든 샘플을 덮는다
    lo, hi = minmax_buckets(np.arange(7, dtype=np.float32), 3)
    assert (lo, hi) == ([0.0, 2.0, 4.0], [1.0, 3.0, 6.0])
    assert minmax_buckets(np.array([], dtype=np.float32), 500) == ([], [])


def test_spectrum(w):
    w.spectrum(at=1)
    s = w.snap()["spectrum"]
    assert s["status"] == "LIVE" and s["timestamp"] == iso_ms(w.ts(1))
    assert [p["title"] for p in s["panels"]] == ["스펙트럼", "포락선 스펙트럼"]
    p0 = s["panels"][0]
    assert (p0["x_start"], p0["x_unit"]) == (0.0, "Hz")
    assert [x["name"] for x in p0["series"]] == ["spectrum_x", "spectrum_y", "spectrum_z"]
    for panel in s["panels"]:
        for series in panel["series"]:
            assert all(v == round(v, 4) for v in series["values"])
    w.clock.advance(3.1)
    assert w.snap()["spectrum"]["status"] == "STALE"


def test_interlock_pending(w):
    w.ls("RUNNING", at=0)
    r = w.pdm("CRITICAL", at=1, hi=18, score=0.82)
    w.interlock.issued("cmd-1", w.clock.mono())
    w.state.set_interlock(w.interlock.view())
    w.clock.advance(0.4)
    il = w.snap()["interlock"]
    assert il["line_state"] == "RUNNING"
    assert il["pending_stop"] == {"command_id": "cmd-1", "age_s": 0.4}
    assert il["last_trigger_timestamp"] == iso_ms(r.timestamp)


def test_list_limits(w):
    w.state.set_db_ok(True)
    w.state.set_summary(summary_rows(w.clock, 30, 30, 30), w.clock.wall(), w.clock.mono())
    s = w.snap()
    d = w.cfg.dashboard
    assert (len(s["inspections"]), len(s["alarms"]), len(s["controls"])) == (
        d.recent_inspections,
        d.recent_alarms,
        d.recent_controls,
    ) == (12, 20, 20)
    assert s["production"] == {
        "summary_at": iso_ms(w.clock.wall()),
        "produced": 113,
        "inspected": 111,
        "defects": 14,
        "defect_rate": 0.1261,
    }
    first = s["inspections"][0]
    assert first["product_id"] == "P-00000001"  # 최신이 먼저(요약 순서 유지)
    assert first["confidence"] == 0.9 and first["bbox"] == [1, 2, 3, 4]
    assert isinstance(s["alarms"][0]["alarm_id"], str) and uuid.UUID(s["alarms"][0]["alarm_id"])
    assert s["controls"][0]["result"] is None
    # 검사 0건이면 불량률 null
    w.state.set_summary(dict(summary_rows(w.clock, 0, 0, 0), inspected=0, defects=0), w.clock.wall(), w.clock.mono())
    assert w.snap()["production"]["defect_rate"] is None
    # DB가 끊기면 production null, 목록 빈 배열
    w.state.set_db_ok(False)
    s = w.snap()
    assert (s["production"], s["inspections"], s["alarms"], s["controls"]) == (None, [], [], [])


def test_correlation_stale(w):
    w.state.set_db_ok(True)
    w.state.set_correlation(correlation_result(w.clock))
    c = w.snap()["correlation"]
    assert c["stale"] is False and c["default_lag_s"] == 13 and len(c["curve"]) == 31
    w.clock.advance(30.0)  # 3 × period_s까지는 최신
    assert w.snap()["correlation"]["stale"] is False
    w.clock.advance(0.1)
    assert w.snap()["correlation"]["stale"] is True
    # 새 결과가 오면 다시 최신, DB가 끊기면 바로 stale
    w.state.set_correlation(correlation_result(w.clock))
    assert w.snap()["correlation"]["stale"] is False
    w.state.set_db_ok(False)
    assert w.snap()["correlation"]["stale"] is True


def test_counters(w):
    w.state.incr(("rejected", "factory/pdm/result", "invalid_field:state"), 2)
    w.state.incr(("db_queue_overflow", "vision_result"))
    w.state.incr(("db_queue_overflow", "sensor_chunk"), 3)
    assert w.snap()["counters"] == {"rejected": {"factory/pdm/result:invalid_field:state": 2}, "queue_overflow": 4}


def fill_full(w):
    """가장 큰 스냅숏: 모든 절이 차 있다."""
    lc = {
        "command": "STOP",
        "command_id": str(uuid.uuid4()),
        "source": "mqtt",
        "received_at": iso_ms(w.ts(0)),
        "result": "APPLIED",
        "reason": "INTERLOCK_CRITICAL",
        "error": None,
    }
    w.ls("STOPPED", at=0)
    w.ls("RUNNING", at=1, fault=8, last_command=lc)
    rng = np.random.default_rng(0)
    for i in range(240):
        w.pdm("CRITICAL", at=2 + i * 0.5, hi=18, score=0.8234)
    w.interlock.issued("cmd-1", w.clock.mono())
    w.state.set_interlock(w.interlock.view())
    w.spectrum(at=120)
    for seq in range(10):
        w.chunk(seq, rng.normal(0, 0.3, 1000), rng.normal(0, 0.3, 1000), rng.normal(0, 0.3, 1000), at=119 + seq * 0.1)
    w.state.set_db_ok(True)
    w.state.mqtt_connected = True
    w.state.set_summary(summary_rows(w.clock), w.clock.wall(), w.clock.mono())
    w.state.set_correlation(correlation_result(w.clock, n_curve=31, n_bins=20))
    for reason in ("invalid_json", "missing_field:timestamp", "invalid_field:state"):
        w.state.incr(("rejected", "factory/pdm/result", reason))


def test_all_times_match_regex(w):
    fill_full(w)
    s = w.snap()
    found = list(iter_times(s))
    keys = {p.rsplit(".", 1)[-1] for p, _ in found}
    assert TIME_KEYS <= keys  # 모든 종류의 시각 필드가 실제로 나왔다
    for path, v in found:
        assert v is None or (isinstance(v, str) and TS_RE.fullmatch(v)), (path, v)
    assert sum(v is not None for _, v in found) > 100


def test_full_snapshot_size(w):
    fill_full(w)
    s = w.snap()
    assert all(s[k]["status"] != "NONE" for k in ("line", "pdm", "spectrum", "vibration"))
    assert len(s["pdm"]["history"]) == 240
    raw = json.dumps(s, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    assert len(raw) <= 150 * 1024, len(raw)
