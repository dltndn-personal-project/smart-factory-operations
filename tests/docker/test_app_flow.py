"""흐름 연동 (docs/spec/08-verification.md 3.6절 C-04·C-06, 03-control.md 3.3절).

실제 Mosquitto·TimescaleDB에 연결한 앱(`running_app`)에 harness가 메시지를 보내고 DB 행과
발행 메시지를 본다. PdM 메시지는 `fixtures.payloads.pdm`으로만 만든다(D-39).
Topic이 다르면 도착 순서가 보장되지 않으므로 선행 메시지의 처리를 `wait_snapshot`으로 확인한 뒤 보낸다.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from factory_operations.clock import iso_ms
from fixtures.payloads import pdm

S = timedelta(seconds=1)
ROWS_TIMEOUT_S = 5.0
RESULT_TIMEOUT_S = 3.0


def now_ms() -> datetime:
    t = datetime.now(timezone.utc)
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


def line_status(ts: datetime, conveyor: str = "RUNNING", fault: int = 3, last_command: dict | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "online": True,
        "timestamp": iso_ms(ts),
        "conveyor": conveyor,
        "fault_level": fault,
        "motor_rpm": 1800.0 if conveyor == "RUNNING" else 0.0,
        "sensor_id": "motor01",
        "production_active": conveyor == "RUNNING",
        "products": {"spawned": 2, "created": 2, "expired": 0, "in_flight": 0, "last_product_id": "P-00000002"},
        "last_command": last_command,
    }


def sensor_chunk(ts: datetime, seq: int, n: int = 100) -> dict[str, Any]:
    wave = [round(0.1 * ((i * 7 + seq) % 11 - 5) / 5, 4) for i in range(n)]
    return {
        "schema_version": 1,
        "sensor_id": "motor01",
        "timestamp": iso_ms(ts),
        "seq": seq,
        "sample_rate_hz": 1000,
        "rpm": 1800.0,
        "temperature": 40.5,
        "vibration_x": wave,
        "vibration_y": wave,
        "vibration_z": wave,
    }


def product(pid: str, ts: datetime) -> dict[str, Any]:
    return {"schema_version": 1, "product_id": pid, "timestamp": iso_ms(ts), "image_path": f"products/{pid}.jpg"}


def vision(pid: str, ts: datetime, defect: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "product_id": pid,
        "timestamp": iso_ms(ts),
        "defect": defect,
        "defect_type": "scratch" if defect else None,
        "confidence": None,
        "bbox": None,
        "image_path": f"products/{pid}.jpg",
        "gradcam_path": None,
        "judgement_source": "PASS_THROUGH",
    }


def wait_db(db, check: Callable[[Any], Any], timeout: float) -> Any:
    """`check(conn)`이 참 값을 낼 때까지 0.1초 간격. 시간 초과면 마지막 값으로 AssertionError."""
    deadline = time.monotonic() + timeout
    with db.connect() as conn:
        while True:
            last = check(conn)
            if last:
                return last
            if time.monotonic() >= deadline:
                raise AssertionError(f"DB condition not met within {timeout}s")
            time.sleep(0.1)


def count(conn, table: str, where: str = "TRUE", params: tuple = ()) -> int:
    return conn.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()[0]


def start_running(harness, wait_snapshot, t0: datetime, fault: int = 3) -> None:
    """Line Status(retain, RUNNING)를 보내고 반영(기준 시각)을 확인한다."""
    harness.publish(harness.topics.line_status, line_status(t0, fault=fault), qos=1, retain=True)
    wait_snapshot(
        lambda s: s["line"]["fault_level"] == fault and s["interlock"]["reference_time"] == iso_ms(t0)
    )


# ---------------------------------------------------------------------------


def test_rows_and_joins(running_app, harness, wait_snapshot, clean_db):
    t = harness.topics
    t0 = now_ms()
    start_running(harness, wait_snapshot, t0, fault=3)

    for seq in range(1, 21):
        harness.publish(t.sensor("motor01"), sensor_chunk(t0 + seq * 0.1 * S, seq), qos=0)
    his = [91, 92, 93, 94]
    pdm_ts = [t0 + (1.0 + 0.5 * i) * S for i in range(4)]
    for ts, hi in zip(pdm_ts, his):
        harness.publish(t.pdm_result, pdm.to_bytes(pdm.pdm_result("motor01", ts, "NORMAL", hi, round(1 - hi / 100, 4))))
    # 검사 결합이 PdM 이력을 보도록 PdM 처리를 먼저 확인한다
    wait_snapshot(lambda s: s["pdm"]["timestamp"] == iso_ms(pdm_ts[-1]) and len(s["pdm"]["history"]) == 4)
    # 캡처 시각: 1.7초(→ 1.5초 결과 HI 92), 2.6초(→ 2.5초 결과 HI 94)
    caps = {"P-00000001": (t0 + 1.7 * S, 92, False), "P-00000002": (t0 + 2.6 * S, 94, True)}
    for pid, (ts, _hi, defect) in caps.items():
        harness.publish(t.product_created, product(pid, ts))
        harness.publish(t.vision_result, vision(pid, ts, defect))
    sent = time.monotonic()

    def rows_ready(conn):
        return (
            count(conn, "sensor_chunk") == 20
            and count(conn, "equipment_state") == 4
            and count(conn, "product") == 2
            and count(conn, "inspection") == 2
            and count(conn, "line_status_change") == 1
        )

    wait_db(clean_db, rows_ready, ROWS_TIMEOUT_S)
    assert time.monotonic() - sent <= ROWS_TIMEOUT_S
    with clean_db.connect() as conn:
        assert count(conn, "sensor_chunk", "fault_level = 3") == 20
        seqs = [r[0] for r in conn.execute("SELECT seq FROM sensor_chunk ORDER BY seq").fetchall()]
        assert seqs == list(range(1, 21))
        es = conn.execute('SELECT "timestamp", health_index, state FROM equipment_state ORDER BY "timestamp"').fetchall()
        assert [(r[0], r[1], r[2]) for r in es] == [(ts, hi, "NORMAL") for ts, hi in zip(pdm_ts, his)]
        insp = conn.execute(
            'SELECT product_id, "timestamp", defect, sensor_id, health_index_at_time, pdm_timestamp_at_time '
            "FROM inspection ORDER BY product_id"
        ).fetchall()
        assert [(r[0], r[1], r[2], r[3], r[4]) for r in insp] == [
            (pid, ts, defect, "motor01", hi) for pid, (ts, hi, defect) in caps.items()
        ]
        for r in insp:  # 캡처 시각 이하 가장 최근 PdM 결과
            assert r[5] == max(p for p in pdm_ts if p <= r[1])
        lsc = conn.execute('SELECT online, conveyor, fault_level, "timestamp" FROM line_status_change').fetchall()
        assert lsc == [(True, "RUNNING", 3, t0)]


def test_stop_result_recorded(running_app, harness, wait_snapshot, clean_db):
    t = harness.topics
    t0 = now_ms()
    start_running(harness, wait_snapshot, t0, fault=8)
    crit_ts = t0 + 1 * S
    harness.publish(t.pdm_result, pdm.to_bytes(pdm.pdm_result("motor01", crit_ts, "CRITICAL", 18, 0.82)))
    _, stop = harness.wait_for(t.conveyor, lambda m: m["command"] == "STOP", timeout=2.0)
    assert stop["reason"] == "INTERLOCK_CRITICAL"
    wait_snapshot(lambda s: s["interlock"]["pending_stop"] is not None and s["interlock"]["pending_stop"]["command_id"] == stop["command_id"])

    last_command = {
        "command": "STOP",
        "command_id": stop["command_id"],
        "source": "mqtt",
        "received_at": iso_ms(now_ms()),
        "result": "APPLIED",
        "reason": "INTERLOCK_CRITICAL",
        "error": None,
    }
    harness.publish(t.line_status, line_status(t0 + 1.5 * S, "STOPPED", fault=8, last_command=last_command), retain=True)
    sent = time.monotonic()

    def applied(conn):
        row = conn.execute("SELECT result, origin, trigger_timestamp FROM control WHERE command_id = %s", (stop["command_id"],)).fetchone()
        return row if row and row[0] == "APPLIED" else None

    row = wait_db(clean_db, applied, RESULT_TIMEOUT_S)
    assert time.monotonic() - sent <= RESULT_TIMEOUT_S
    assert row == ("APPLIED", "operations", crit_ts)
    s = wait_snapshot(lambda s: s["interlock"]["pending_stop"] is None and s["interlock"]["line_state"] == "STOPPED")
    assert s["interlock"]["last_trigger_timestamp"] == iso_ms(crit_ts)
    # 같은 PdM 결과로 STOP을 두 번 내지 않았다
    assert len([m for _t, m in harness.received(t.conveyor) if m["command"] == "STOP"]) == 1


def test_operator_start_published(running_app, harness, clean_db):
    r = running_app.post("/api/conveyor", json={"command": "START"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["command"] == "START" and uuid.UUID(body["command_id"]).version == 4
    _, msg = harness.wait_for(harness.topics.conveyor, lambda m: m["command_id"] == body["command_id"], timeout=2.0)
    assert msg == {
        "schema_version": 1,
        "command": "START",
        "command_id": body["command_id"],
        "timestamp": body["timestamp"],
        "reason": "OPERATOR_START",
    }

    def recorded(conn):
        return conn.execute(
            "SELECT command, reason, origin, trigger_timestamp FROM control WHERE command_id = %s", (body["command_id"],)
        ).fetchone()

    assert wait_db(clean_db, recorded, RESULT_TIMEOUT_S) == ("START", "OPERATOR_START", "operations", None)


def test_readyz_and_snapshot_live(running_app, harness, wait_snapshot):
    """조립된 앱의 `/readyz`·`/healthz`와 스냅숏의 연결 표시."""
    assert running_app.get("/readyz").status_code == 200
    h = running_app.get("/healthz").json()
    assert h["mqtt_connected"] is True and h["db_ok"] is True and h["commit"] == "test"
    s = wait_snapshot(lambda s: s["production"] is not None)  # DB 요약이 2초 주기로 들어온다
    assert s["mqtt_connected"] is True and s["db_ok"] is True


def test_operator_stop_does_not_touch_interlock(running_app, harness):
    """운영자 STOP은 Interlock 대기 상태를 만들지 않는다(03 3.3절)."""
    r = running_app.post("/api/conveyor", json={"command": "STOP"})
    assert r.status_code == 202
    harness.wait_for(harness.topics.conveyor, lambda m: m["reason"] == "OPERATOR_STOP", timeout=2.0)
    s = running_app.snapshot()
    assert s["interlock"]["pending_stop"] is None and s["interlock"]["last_trigger_timestamp"] is None
