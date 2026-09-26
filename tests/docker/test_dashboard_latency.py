"""Dashboard 데이터 5초 이내 갱신 (docs/spec/08-verification.md 4.1절, C-08, AGREEMENTS.md A-10, D-34).

측정 도구(별도 harness)가 같은 broker의 `<prefix>/#`를 구독해 이벤트 E를 받은 시각 `t_rx`를 자기
`monotonic`으로 적고, `/api/snapshot`을 0.2초 간격으로 불러 반영 조건이 처음 참이 된 응답 시각을
`t_seen`으로 둔다. `D = t_seen − t_rx + P + r_max + R`(P = 1.0, R = 0.2, `r_max` = 측정 중 스냅숏
응답 시간 최댓값). 판정: 모든 표본 `max D ≤ 5.0`초, `r_max ≤ 0.5`초.

부하(60초): Line Status 변경 5초마다(12개), 센서 0.1초마다, PdM Result 0.5초마다, 스펙트럼 1초마다,
Product·Vision 2초마다(30개), `CRITICAL` 1회(Alarm·STOP)와 명령 결과 1회.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import numpy as np

from factory_operations.clock import iso_ms
from fixtures.payloads import pdm

from .test_app_flow import S, line_status, now_ms, product, vision

LOAD_S = 60.0
POLL_S = 0.2
P = 1.0  # 브라우저 polling 간격
R = 0.2  # 렌더링 예산(사람 확인 M-02)
D_LIMIT_S = 5.0
R_LIMIT_S = 0.5
DRAIN_S = 10.0  # 부하가 끝난 뒤 남은 표본의 반영을 기다리는 최대 시간
CRITICAL_AT = 30.0
RESULT_AT = 31.0

KINDS = ("line_status", "pdm_result", "pdm_spectrum", "sensor_vibration", "vision_result", "alarm_event", "command_result")


@dataclass
class Event:
    kind: str
    key: str
    t_rx: float
    cond: Callable[[dict[str, Any]], bool]
    t_seen: float | None = None


def _ts_ge(section: dict[str, Any], ts: str) -> bool:
    v = section.get("timestamp")
    return v is not None and v >= ts  # iso_ms 문자열은 사전 순서 = 시간 순서


class Meter:
    """측정 도구. 수신 메시지를 이벤트로 바꾸고 0.2초마다 스냅숏으로 반영을 본다."""

    def __init__(self, app, meter_harness):
        self.app = app
        self.h = meter_harness
        self.topics = meter_harness.topics
        self.events: list[Event] = []
        self.cursor = 0
        self.n_vision = 0
        self.r_max = 0.0
        self.n_polls = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="meter", daemon=True)

    def start(self) -> None:
        with self.h._lock:
            self.cursor = len(self.h.messages)  # 시작 전 메시지(retained 포함)는 표본이 아니다
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(5)

    def pending(self) -> list[Event]:
        return [e for e in self.events if e.t_seen is None]

    def _ingest(self) -> None:
        with self.h._lock:
            new = self.h.messages[self.cursor :]
            self.cursor += len(new)
        t = self.topics
        for t_rx, topic, raw in new:
            m = json.loads(raw)
            kind = t.kind_of(topic)
            if topic == t.alarm:
                aid = m["alarm_id"]
                self.events.append(Event("alarm_event", aid, t_rx, lambda s, aid=aid: any(a["alarm_id"] == aid for a in s["alarms"])))
            elif kind is None:
                continue  # Conveyor Control
            elif kind.kind == "line_status":
                if not m.get("online"):
                    continue
                lc = m.get("last_command")
                if lc is not None:
                    cid = lc["command_id"]
                    self.events.append(
                        Event(
                            "command_result",
                            cid,
                            t_rx,
                            lambda s, cid=cid: any(c["command_id"] == cid and c["result"] is not None for c in s["controls"]),
                        )
                    )
                else:
                    ts = m["timestamp"]
                    self.events.append(Event("line_status", ts, t_rx, lambda s, ts=ts: _ts_ge(s["line"], ts)))
            elif kind.kind == "pdm_result":
                ts = m["timestamp"]
                self.events.append(Event("pdm_result", ts, t_rx, lambda s, ts=ts: _ts_ge(s["pdm"], ts)))
            elif kind.kind == "pdm_spectrum":
                ts = m["timestamp"]
                self.events.append(Event("pdm_spectrum", ts, t_rx, lambda s, ts=ts: _ts_ge(s["spectrum"], ts)))
            elif kind.kind == "sensor_vibration":
                ts = m["timestamp"]
                self.events.append(Event("sensor_vibration", ts, t_rx, lambda s, ts=ts: _ts_ge(s["vibration"], ts)))
            elif kind.kind == "vision_result":
                self.n_vision += 1
                pid, k = m["product_id"], self.n_vision
                # inspections에 product_id가 있고 inspected가 E 이전 값(k − 1, 빈 DB)보다 큼
                self.events.append(
                    Event(
                        "vision_result",
                        pid,
                        t_rx,
                        lambda s, pid=pid, k=k: s["production"] is not None
                        and s["production"]["inspected"] >= k
                        and any(i["product_id"] == pid for i in s["inspections"]),
                    )
                )

    def _run(self) -> None:
        next_t = time.monotonic()
        while not self._stop.is_set():
            t_req = time.monotonic()
            r = self.app.http.get("/api/snapshot")
            t_resp = time.monotonic()
            r.raise_for_status()
            snap = r.json()
            self.r_max = max(self.r_max, t_resp - t_req)
            self.n_polls += 1
            self._ingest()
            for e in self.pending():
                if e.t_rx <= t_resp and e.cond(snap):
                    e.t_seen = t_resp
            next_t += POLL_S
            delay = next_t - time.monotonic()
            if delay > 0:
                self._stop.wait(delay)
            else:
                next_t = time.monotonic()


class Feeder:
    """60초 부하 일정(08 4.1절)."""

    def __init__(self, harness, t_sim0: datetime):
        self.h = harness
        self.t = harness.topics
        self.t_sim0 = t_sim0
        rng = np.random.default_rng(1)
        axes = [json.dumps(np.round(rng.normal(0, 0.2, 1000), 4).tolist()) for _ in range(3)]
        self._axes = axes
        self.seq = 0
        self.fault = 0
        self.stop_id: str | None = None

    def ts(self, off: float) -> datetime:
        return self.t_sim0 + off * S

    def sensor(self, off: float) -> None:
        self.seq += 1
        x, y, z = self._axes
        raw = (
            '{"schema_version":1,"sensor_id":"motor01","timestamp":"%s","seq":%d,"sample_rate_hz":10000,'
            '"rpm":1800.0,"temperature":41.2,"vibration_x":%s,"vibration_y":%s,"vibration_z":%s}'
            % (iso_ms(self.ts(off)), self.seq, x, y, z)
        ).encode()
        self.h.publish(self.t.sensor("motor01"), raw, qos=0)

    def pdm_result(self, off: float) -> None:
        if abs(off - CRITICAL_AT) < 1e-9:
            msg = pdm.pdm_result("motor01", self.ts(off), "CRITICAL", 18, 0.82)
        else:
            msg = pdm.pdm_result("motor01", self.ts(off), "NORMAL", 92, 0.08)
        self.h.publish(self.t.pdm_result, pdm.to_bytes(msg))

    def spectrum(self, off: float) -> None:
        self.h.publish(self.t.pdm_spectrum, pdm.to_bytes(pdm.pdm_spectrum("motor01", self.ts(off))), qos=0)

    def product_vision(self, off: float, n: int) -> None:
        pid = f"P-{n:08d}"
        self.h.publish(self.t.product_created, product(pid, self.ts(off)))
        self.h.publish(self.t.vision_result, vision(pid, self.ts(off), defect=n % 4 == 0))

    def line_change(self, off: float, k: int) -> None:
        self.fault = k % 9 + 1  # 1..9, 매번 바뀐다
        self.h.publish(self.t.line_status, line_status(self.ts(off), "RUNNING", fault=self.fault), retain=True)

    def command_result(self, off: float) -> None:
        """CRITICAL로 나간 STOP에 APPLIED·STOPPED로 답한다(명령 결과 1회)."""
        _t, stop = self.h.wait_for(self.t.conveyor, lambda m: m["command"] == "STOP", timeout=2.0)
        self.stop_id = stop["command_id"]
        lc = {
            "command": "STOP",
            "command_id": stop["command_id"],
            "source": "mqtt",
            "received_at": iso_ms(self.ts(off)),
            "result": "APPLIED",
            "reason": "INTERLOCK_CRITICAL",
            "error": None,
        }
        self.h.publish(self.t.line_status, line_status(self.ts(off), "STOPPED", fault=self.fault, last_command=lc), retain=True)

    def schedule(self) -> list[tuple[float, Callable[[], None]]]:
        items: list[tuple[float, Callable[[], None]]] = []
        for i in range(int(LOAD_S / 0.1)):
            off = round(i * 0.1, 1)
            items.append((off, lambda off=off: self.sensor(off)))
        for i in range(int(LOAD_S / 0.5)):
            off = 0.05 + i * 0.5 if abs(i * 0.5 - CRITICAL_AT) > 1e-9 else CRITICAL_AT
            items.append((off, lambda off=off: self.pdm_result(off)))
        for i in range(int(LOAD_S)):
            off = 0.5 + i
            items.append((off, lambda off=off: self.spectrum(off)))
        for n in range(1, 31):
            off = 1.0 + (n - 1) * 2.0
            items.append((off, lambda off=off, n=n: self.product_vision(off, n)))
        for k in range(12):
            off = 2.5 + 5.0 * k
            items.append((off, lambda off=off, k=k: self.line_change(off, k)))
        items.append((RESULT_AT, lambda: self.command_result(RESULT_AT)))
        items.sort(key=lambda it: it[0])
        return items

    def run(self) -> None:
        start = time.monotonic()
        for off, fn in self.schedule():
            delay = start + off - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            fn()


def summarize(values: list[float]) -> str:
    a = np.asarray(values)
    return f"n={len(a):4d} p50={np.percentile(a, 50):.3f} p95={np.percentile(a, 95):.3f} max={a.max():.3f}"


def test_dashboard_update_within_5s(running_app, harness, harness_factory, mqtt_broker, wait_snapshot):
    t = harness.topics
    meter_h = harness_factory(mqtt_broker.port, running_app.prefix)
    meter_h.subscribe(f"{running_app.prefix}/#", qos=1)

    t_sim0 = now_ms()
    # 준비: 라인 가동(fault 0)과 기준 시각
    setup_ts = iso_ms(t_sim0 - 1 * S)
    harness.publish(t.line_status, line_status(t_sim0 - 1 * S, "RUNNING", fault=0), retain=True)
    wait_snapshot(lambda s: s["line"]["fault_level"] == 0 and s["interlock"]["reference_time"] == setup_ts)
    # 준비 메시지가 측정 도구에도 도착한 뒤에 시작한다(표본에서 빼기 위해)
    meter_h.wait_for(t.line_status, lambda m: m.get("timestamp") == setup_ts, timeout=5.0)

    meter = Meter(running_app, meter_h)
    meter.start()
    feeder = Feeder(harness, t_sim0)
    try:
        feeder.run()
        deadline = time.monotonic() + DRAIN_S
        while time.monotonic() < deadline:
            time.sleep(POLL_S)
            with meter_h._lock:
                caught_up = meter.cursor >= len(meter_h.messages)
            if caught_up and not meter.pending():
                break
    finally:
        meter.stop()

    events = meter.events
    by_kind: dict[str, list[float]] = {k: [] for k in KINDS}
    unseen = [e for e in events if e.t_seen is None]
    for e in events:
        if e.t_seen is not None:
            by_kind[e.kind].append(e.t_seen - e.t_rx + P + meter.r_max + R)

    print()
    print(f"dashboard latency: polls={meter.n_polls} r_max={meter.r_max:.3f}s (P={P}, R={R})")
    for k in KINDS:
        if by_kind[k]:
            print(f"  {k:16s} {summarize(by_kind[k])}")
    all_d = [d for v in by_kind.values() for d in v]
    print(f"  {'all':16s} {summarize(all_d)}")

    assert not unseen, f"{len(unseen)} events never reflected: {[(e.kind, e.key) for e in unseen[:10]]}"
    counts = {k: len(v) for k, v in by_kind.items()}
    assert counts["line_status"] == 12 and counts["vision_result"] == 30, counts
    assert counts["sensor_vibration"] == 600 and counts["pdm_result"] == 120 and counts["pdm_spectrum"] == 60, counts
    assert counts["alarm_event"] == 1 and counts["command_result"] == 1, counts
    assert meter.r_max <= R_LIMIT_S, meter.r_max
    assert max(all_d) <= D_LIMIT_S, max(all_d)
