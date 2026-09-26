"""DB 스레드 연동 (docs/spec/08-verification.md 3.6절, 05-storage.md 2·3·5절)."""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable

import numpy as np
import pytest

from factory_operations.config import load_config
from factory_operations.store.db import DbWriter
from factory_operations.store.jobs import (
    AlarmJob,
    ControlIssuedJob,
    ControlObservedJob,
    ControlResultJob,
    EquipmentJob,
    InspectionJob,
    LineChangeJob,
    ProductJob,
    SensorJob,
)

if TYPE_CHECKING:
    from .conftest import DbContainer

pytestmark = pytest.mark.docker

T0 = datetime(2026, 9, 25, 5, 21, 0, tzinfo=timezone.utc)


def ts(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


# --- 도구 --------------------------------------------------------------------


def make_cfg(url: str, **sections: dict[str, Any]):
    """기본 설정 + `DATABASE_URL`. `sections`는 절 이름 → 바꿀 키(검증 없이 model_copy)."""
    cfg = load_config({"DATABASE_URL": url})
    updates = {name: getattr(cfg, name).model_copy(update=vals) for name, vals in sections.items()}
    return cfg.model_copy(update=updates)


class Recorder:
    """콜백 기록. 다른 스레드에서 불린다."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.db_ok: list[tuple[float, bool]] = []
        self.summaries: list[dict] = []
        self.correlations: list[dict] = []
        self.corr_calls: list[tuple[list, list, Any]] = []

    def on_db_ok(self, ok: bool) -> None:
        with self.lock:
            self.db_ok.append((time.monotonic(), ok))

    def on_summary(self, s: dict) -> None:
        with self.lock:
            self.summaries.append(s)

    def on_correlation(self, r: dict) -> None:
        with self.lock:
            self.correlations.append(r)

    def compute(self, inspections: list, scores: list, cfg: Any) -> dict:
        with self.lock:
            self.corr_calls.append((list(inspections), list(scores), cfg))
        return {"n_inspections": len(inspections), "n_scores": len(scores)}


def wait_for(pred: Callable[[], Any], timeout: float, interval: float = 0.05) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(interval)
    return pred()


def start_writer(cfg, rec: Recorder | None = None, *, correlation: bool = False) -> tuple[DbWriter, queue.Queue, Recorder]:
    rec = rec or Recorder()
    q: queue.Queue = queue.Queue(maxsize=10000)
    w = DbWriter(
        cfg,
        q,
        on_db_ok=rec.on_db_ok,
        on_summary=rec.on_summary,
        on_correlation=rec.on_correlation,
        compute_correlation=rec.compute if correlation else None,
    )
    w.start()
    return w, q, rec


def wait_idle(w: DbWriter, q: queue.Queue, timeout: float = 5.0) -> None:
    """큐가 비고 센서 배치까지 flush될 때까지."""
    assert wait_for(lambda: q.empty() and not w._batch, timeout)
    time.sleep(0.3)  # 마지막으로 꺼낸 작업의 실행이 끝날 시간


def rows(db: "DbContainer", query: str, params: Any = None) -> list[tuple]:
    with db.connect() as conn:
        return conn.execute(query, params).fetchall()


def sensor_job(i: int, sensor_id: str = "motor01", fault_level: int | None = 3) -> SensorJob:
    rng = np.random.default_rng(i)
    vib = [np.round(rng.normal(0, 0.1, 1000), 4) for _ in range(3)]
    return SensorJob(
        sensor_id=sensor_id,
        timestamp=ts(i * 0.1),
        seq=i,
        sample_rate_hz=10000,
        rpm=1780.0,
        temperature=42.5,
        vibration_x=vib[0],
        vibration_y=vib[1],
        vibration_z=vib[2],
        fault_level=fault_level,
        received_at=ts(i * 0.1 + 0.05),
    )


def line_change_job() -> LineChangeJob:
    return LineChangeJob(
        received_at=ts(1.1),
        timestamp=ts(1.0),
        online=True,
        conveyor="RUNNING",
        fault_level=3,
        motor_rpm=1780.0,
        production_active=True,
        sensor_id="motor01",
    )


def product_job(pid: str = "P-00000001", t: float = 10.0) -> ProductJob:
    return ProductJob(product_id=pid, timestamp=ts(t), image_path=f"products/{pid}.jpg", received_at=ts(t + 0.1))


def inspection_job(pid: str = "P-00000001", t: float = 10.0, defect: bool = True, hi: int | None = 55) -> InspectionJob:
    return InspectionJob(
        product_id=pid,
        timestamp=ts(t),
        defect=defect,
        defect_type="scratch" if defect else None,
        confidence=None,
        bbox=(1, 2, 30, 40) if defect else None,
        image_path=f"products/{pid}.jpg",
        gradcam_path=None,
        judgement_source="PASS_THROUGH",
        sensor_id="motor01",
        health_index_at_time=hi,
        anomaly_score_at_time=0.45 if hi is not None else None,
        pdm_timestamp_at_time=ts(t - 0.3) if hi is not None else None,
        received_at=ts(t + 0.2),
    )


def equipment_job(t: float = 5.0, score: float = 0.45, sensor_id: str = "motor01") -> EquipmentJob:
    return EquipmentJob(
        sensor_id=sensor_id,
        timestamp=ts(t),
        window_start=ts(t - 1.0),
        anomaly_score=score,
        health_index=55,
        state="WARNING",
        model_version="pdm-1",
        received_at=ts(t + 0.05),
    )


def alarm_job(alarm_id: str | None = None, t: float = 6.0) -> AlarmJob:
    return AlarmJob(
        alarm_id=alarm_id or str(uuid.uuid4()),
        timestamp=ts(t),
        raised_at=ts(t + 0.01),
        sensor_id="motor01",
        severity="CRITICAL",
        previous_state="WARNING",
        health_index=12,
        anomaly_score=0.91,
    )


def control_issued_job(cid: str = "c-1", t: float = 7.0) -> ControlIssuedJob:
    return ControlIssuedJob(
        command_id=cid,
        command="STOP",
        reason="INTERLOCK_CRITICAL",
        issued_at=ts(t),
        trigger_sensor_id="motor01",
        trigger_timestamp=ts(t - 0.1),
        recorded_at=ts(t + 0.001),
    )


def control_result_job(cid: str = "c-1", result: str = "APPLIED", t: float = 8.0) -> ControlResultJob:
    return ControlResultJob(
        command_id=cid, result=result, result_received_at=ts(t), error=None, observed_at=ts(t + 0.2)
    )


def control_observed_job(cid: str = "c-obs", t: float = 9.0) -> ControlObservedJob:
    return ControlObservedJob(
        command_id=cid,
        command="START",
        reason="operator",
        source="dashboard",
        result="NO_CHANGE",
        result_received_at=ts(t),
        error=None,
        observed_at=ts(t + 0.1),
        recorded_at=ts(t + 0.1),
    )


# --- 2절 쓰기 작업 -----------------------------------------------------------


def test_each_job_writes_row(clean_db: "DbContainer") -> None:
    w, q, rec = start_writer(make_cfg(clean_db.url))
    try:
        assert wait_for(lambda: w.db_ok, 10)
        alarm_id = str(uuid.uuid4())
        s = sensor_job(1)
        for job in (
            s,
            line_change_job(),
            product_job(),
            inspection_job(),
            equipment_job(),
            alarm_job(alarm_id),
            control_issued_job("c-1"),
            control_result_job("c-1"),
            control_observed_job("c-obs"),
        ):
            q.put_nowait(job)
        wait_idle(w, q)
    finally:
        w.stop()

    got = rows(clean_db, 'SELECT sensor_id, "timestamp", seq, sample_rate_hz, rpm, temperature, fault_level, '
               "received_at, vibration_x, array_length(vibration_y, 1), array_length(vibration_z, 1) FROM sensor_chunk")
    assert len(got) == 1
    r = got[0]
    assert r[:8] == ("motor01", s.timestamp, 1, 10000, 1780.0, 42.5, 3, s.received_at)
    assert len(r[8]) == 1000 and r[8][:5] == pytest.approx(s.vibration_x[:5].tolist(), abs=1e-6)
    assert r[9] == r[10] == 1000

    assert rows(clean_db, 'SELECT received_at, "timestamp", online, conveyor, fault_level, motor_rpm, '
                "production_active, sensor_id FROM line_status_change") == [
        (ts(1.1), ts(1.0), True, "RUNNING", 3, 1780.0, True, "motor01")
    ]
    assert rows(clean_db, 'SELECT product_id, "timestamp", image_path, received_at FROM product') == [
        ("P-00000001", ts(10.0), "products/P-00000001.jpg", ts(10.1))
    ]
    assert rows(clean_db, 'SELECT product_id, "timestamp", defect, defect_type, confidence, bbox, image_path, '
                "gradcam_path, judgement_source, sensor_id, health_index_at_time, anomaly_score_at_time, "
                "pdm_timestamp_at_time, received_at FROM inspection") == [
        ("P-00000001", ts(10.0), True, "scratch", None, [1, 2, 30, 40], "products/P-00000001.jpg", None,
         "PASS_THROUGH", "motor01", 55, 0.45, ts(9.7), ts(10.2))
    ]  # fmt: skip
    assert rows(clean_db, "SELECT product_id FROM defect_result") == [("P-00000001",)]
    assert rows(clean_db, 'SELECT sensor_id, "timestamp", window_start, anomaly_score, health_index, state, '
                "model_version, received_at FROM equipment_state") == [
        ("motor01", ts(5.0), ts(4.0), 0.45, 55, "WARNING", "pdm-1", ts(5.05))
    ]
    assert rows(clean_db, 'SELECT alarm_id::text, "timestamp", raised_at, sensor_id, severity, previous_state, '
                "health_index, anomaly_score FROM alarm") == [
        (alarm_id, ts(6.0), ts(6.01), "motor01", "CRITICAL", "WARNING", 12, 0.91)
    ]
    ctl = rows(clean_db, "SELECT command_id, command, reason, origin, source, issued_at, trigger_sensor_id, "
               "trigger_timestamp, result, result_received_at, error, observed_at, recorded_at "
               "FROM control ORDER BY recorded_at")
    assert ctl == [
        ("c-1", "STOP", "INTERLOCK_CRITICAL", "operations", None, ts(7.0), "motor01", ts(6.9), "APPLIED",
         ts(8.0), None, ts(8.2), ts(7.001)),
        ("c-obs", "START", "operator", "observed", "dashboard", None, None, None, "NO_CHANGE", ts(9.0), None,
         ts(9.1), ts(9.1)),
    ]  # fmt: skip
    assert w.counters["db_errors"] == 0
    assert w.counters["jobs_written"] == 8


def test_duplicates_ignored(clean_db: "DbContainer") -> None:
    w, q, rec = start_writer(make_cfg(clean_db.url))
    try:
        assert wait_for(lambda: w.db_ok, 10)
        for job in (
            sensor_job(1),
            sensor_job(1),
            product_job("P-1"),
            product_job("P-1", t=11.0),
            inspection_job("P-1", defect=True),
            inspection_job("P-1", t=12.0, defect=False),  # 같은 제품의 두 번째 결과는 버린다
            equipment_job(5.0, 0.45),
            equipment_job(5.0, 0.99),
            control_issued_job("c-1"),
            control_issued_job("c-1", t=20.0),
            control_observed_job("c-1"),  # 이미 있는 자기 명령 id
            control_observed_job("c-obs"),
            control_observed_job("c-obs", t=30.0),
        ):
            q.put_nowait(job)
        wait_idle(w, q)
    finally:
        w.stop()

    assert rows(clean_db, "SELECT count(*) FROM sensor_chunk") == [(1,)]
    assert rows(clean_db, 'SELECT "timestamp" FROM product') == [(ts(10.0),)]
    assert rows(clean_db, 'SELECT defect, "timestamp" FROM inspection') == [(True, ts(10.0))]
    assert rows(clean_db, "SELECT anomaly_score FROM equipment_state") == [(0.45,)]
    assert rows(clean_db, "SELECT command_id, origin, issued_at, observed_at FROM control ORDER BY command_id") == [
        ("c-1", "operations", ts(7.0), None),
        ("c-obs", "observed", None, ts(9.1)),
    ]
    assert w.counters["db_errors"] == 0


def test_sensor_batches(clean_db: "DbContainer") -> None:
    w, q, rec = start_writer(make_cfg(clean_db.url))
    try:
        assert wait_for(lambda: w.db_ok, 10)
        for i in range(25):
            q.put_nowait(sensor_job(i))
        assert wait_for(lambda: w.counters["sensor_rows_written"] == 25, 5)
    finally:
        w.stop()
    assert rows(clean_db, "SELECT count(*), min(seq), max(seq), count(fault_level) FROM sensor_chunk") == [(25, 0, 24, 25)]
    assert w.counters["sensor_batches"] >= 2


def test_control_result_update_once(clean_db: "DbContainer") -> None:
    w, q, rec = start_writer(make_cfg(clean_db.url))
    try:
        assert wait_for(lambda: w.db_ok, 10)
        q.put_nowait(control_issued_job("c-1"))
        q.put_nowait(control_result_job("c-1", "APPLIED", t=8.0))
        q.put_nowait(control_result_job("c-1", "REJECTED", t=9.0))  # 1초 뒤 같은 결과를 다시 봐도 바꾸지 않는다
        q.put_nowait(control_result_job("c-unknown", "APPLIED"))  # 행 없음: 0행
        wait_idle(w, q)
    finally:
        w.stop()
    assert rows(clean_db, "SELECT command_id, result, result_received_at, observed_at FROM control") == [
        ("c-1", "APPLIED", ts(8.0), ts(8.2))
    ]
    assert w.counters["db_errors"] == 0


# --- 3절 재연결·스키마 확인 --------------------------------------------------


def test_db_restart_recovers(db_container_factory: Callable[[], "DbContainer"]) -> None:
    db = db_container_factory()  # 세션 컨테이너를 흔들지 않도록 자기 컨테이너(D-43)
    cfg = make_cfg(db.url, db={"summary_period_s": 0.5})
    w, q, rec = start_writer(cfg)
    try:
        assert wait_for(lambda: w.db_ok, 10)
        q.put_nowait(product_job("P-before"))
        assert wait_for(lambda: rows(db, "SELECT count(*) FROM product") == [(1,)], 5)

        subprocess.run(["docker", "restart", db.id], check=True, capture_output=True, timeout=60)
        restarted = time.monotonic()

        def recovered() -> bool:
            with rec.lock:
                events = [e for e in rec.db_ok if e[0] >= restarted - 60]
            falses = [i for i, e in enumerate(events) if not e[1]]
            return bool(falses) and any(e[1] for e in events[falses[0] + 1 :])

        assert wait_for(recovered, 15), f"db_ok events: {rec.db_ok}"
        assert time.monotonic() - restarted <= 15
        assert w.db_ok

        q.put_nowait(product_job("P-after", t=20.0))
        assert wait_for(lambda: rows(db, "SELECT product_id FROM product ORDER BY product_id")
                        == [("P-after",), ("P-before",)], 5)  # fmt: skip
    finally:
        w.stop()


def test_schema_missing_not_ok(timescale_db: "DbContainer", caplog: pytest.LogCaptureFixture) -> None:
    with timescale_db.connect() as conn:
        conn.execute("DROP DATABASE IF EXISTS noschema")
        conn.execute("CREATE DATABASE noschema")
    url = timescale_db.url.rsplit("/", 1)[0] + "/noschema"
    caplog.set_level(logging.INFO, logger="factory_operations.db")
    w, q, rec = start_writer(make_cfg(url, db={"reconnect_interval_s": 0.5}))
    try:
        assert wait_for(lambda: w.counters["connect_attempts"] >= 2, 10)
        q.put_nowait(product_job())
        assert wait_for(lambda: w.counters["dropped_disconnected"] >= 1, 5)
        assert not w.db_ok
        assert rec.db_ok == []  # 한 번도 true가 되지 않았다
        assert rec.summaries == []
        events = [getattr(r, "fops_event", None) for r in caplog.records]
        assert "db_schema_missing" in events
        assert "db_connected" not in events
    finally:
        w.stop()
        with timescale_db.connect() as conn:
            conn.execute("DROP DATABASE IF EXISTS noschema WITH (FORCE)")


# --- 5절 요약·상관분석 -------------------------------------------------------


def test_summary_callback(clean_db: "DbContainer") -> None:
    cfg = make_cfg(clean_db.url, db={"summary_period_s": 0.5}, dashboard={"recent_inspections": 2, "recent_alarms": 1})
    w, q, rec = start_writer(cfg)
    try:
        assert wait_for(lambda: w.db_ok, 10)
        a_old, a_new = str(uuid.uuid4()), str(uuid.uuid4())
        for job in (
            product_job("P-1", 10.0),
            product_job("P-2", 12.0),
            product_job("P-3", 14.0),
            product_job("P-4", 16.0),
            inspection_job("P-1", 10.0, defect=True),
            inspection_job("P-2", 12.0, defect=False),
            inspection_job("P-3", 14.0, defect=True, hi=None),
            alarm_job(a_old, t=6.0),
            alarm_job(a_new, t=8.0),
            control_issued_job("c-1", t=7.0),
            control_observed_job("c-obs", t=9.0),
        ):
            q.put_nowait(job)
        wait_idle(w, q)
        n = len(rec.summaries)
        assert wait_for(lambda: len(rec.summaries) > n, 3)
        s = rec.summaries[-1]
    finally:
        w.stop()

    assert set(s) == {"produced", "inspected", "defects", "inspections", "alarms", "controls", "summary_at"}
    assert (s["produced"], s["inspected"], s["defects"]) == (4, 3, 2)
    assert isinstance(s["summary_at"], datetime) and s["summary_at"].tzinfo is not None
    assert [r["product_id"] for r in s["inspections"]] == ["P-3", "P-2"]  # 최신 먼저, n_inspections
    assert list(s["inspections"][0]) == [
        "product_id", "timestamp", "defect", "defect_type", "confidence", "bbox", "image_path",
        "gradcam_path", "judgement_source", "health_index_at_time",
    ]  # fmt: skip
    assert s["inspections"][0]["health_index_at_time"] is None and s["inspections"][0]["bbox"] == [1, 2, 30, 40]
    assert len(s["alarms"]) == 1 and str(s["alarms"][0]["alarm_id"]) == a_new
    assert list(s["alarms"][0]) == [
        "alarm_id", "timestamp", "raised_at", "sensor_id", "severity", "previous_state", "health_index", "anomaly_score",
    ]  # fmt: skip
    assert [r["command_id"] for r in s["controls"]] == ["c-obs", "c-1"]
    assert list(s["controls"][0]) == [
        "command_id", "command", "reason", "origin", "source", "issued_at", "trigger_timestamp",
        "result", "result_received_at", "error", "recorded_at",
    ]  # fmt: skip
    assert s["controls"][1]["origin"] == "operations"


def test_correlation_hook_receives_rows(clean_db: "DbContainer") -> None:
    # 검사: 0, 30, 45, 50초(최대 50). 설비(motor01): 0, 4, 10, 40, 50초. 다른 센서 한 행.
    with clean_db.connect() as conn:
        for t, d in ((0, False), (30, True), (45, False), (50, True)):
            conn.execute(
                "INSERT INTO inspection (product_id, \"timestamp\", defect, image_path, sensor_id, received_at) "
                "VALUES (%s, %s, %s, 'products/x.jpg', 'motor01', %s)",
                (f"P-{t}", ts(t), d, ts(t)),
            )
        for t, sid in ((0, "motor01"), (4, "motor01"), (10, "motor01"), (40, "motor01"), (50, "motor01"), (45, "motor02")):
            conn.execute(
                "INSERT INTO equipment_state (sensor_id, \"timestamp\", anomaly_score, health_index, state, received_at) "
                "VALUES (%s, %s, %s, 50, 'WARNING', %s)",
                (sid, ts(t), t / 100, ts(t)),
            )

    # window 없음: 전체 행, 라인 센서만
    w, q, rec = start_writer(make_cfg(clean_db.url, correlation={"period_s": 0.5}), correlation=True)
    try:
        assert wait_for(lambda: rec.correlations, 10)
    finally:
        w.stop()
    insp, scores, cfg = rec.corr_calls[0]
    assert [(r[0], r[1]) for r in insp] == [(ts(0), False), (ts(30), True), (ts(45), False), (ts(50), True)]
    assert [(r[0], r[1]) for r in scores] == [(ts(t), t / 100) for t in (0, 4, 10, 40, 50)]
    assert cfg is w.cfg
    assert rec.correlations[0] == {"n_inspections": 4, "n_scores": 5}

    # window_s 20: 검사 하한 50 - 20 = 30초, 설비 하한 50 - (20 + lag_max 10 + max_gap 5) = 15초
    cfg2 = make_cfg(
        clean_db.url,
        correlation={"period_s": 0.5, "window_s": 20.0, "lag_max_s": 10.0, "default_lag_s": 5.0},
        join={"max_gap_s": 5.0},
    )
    w, q, rec = start_writer(cfg2, correlation=True)
    try:
        assert wait_for(lambda: rec.correlations, 10)
    finally:
        w.stop()
    insp, scores, _ = rec.corr_calls[0]
    assert [r[0] for r in insp] == [ts(30), ts(45), ts(50)]
    assert [r[0] for r in scores] == [ts(40), ts(50)]
