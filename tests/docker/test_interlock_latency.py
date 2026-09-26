"""Interlock 지연 (docs/spec/08-verification.md 4.2절, C-05, AGREEMENTS.md A-11).

5회 반복. 매회 Line Status `STOPPED` → `RUNNING`(새 timestamp = 재가동 기준 시각)을 보내고 스냅숏으로
기준 시각을 확인한 뒤, 그보다 나중 `timestamp`의 PdM `CRITICAL`을 발행한다. 발행 직전 `monotonic`부터
harness가 STOP을 받은 시각까지가 1.0초 이하여야 한다. 측정은 broker 왕복을 포함한다.
"""

from __future__ import annotations

import time

from factory_operations.clock import iso_ms
from fixtures.payloads import pdm

from .test_app_flow import S, line_status, now_ms

ROUNDS = 5
LIMIT_S = 1.0


def test_critical_to_stop_within_1s(running_app, harness, wait_snapshot):
    t = harness.topics
    latencies: list[float] = []
    seen_stops: set[str] = set()
    for i in range(ROUNDS):
        t0 = now_ms()
        # 정지 → 재가동(새 기준 시각). 같은 Topic이라 순서가 지켜진다
        harness.publish(t.line_status, line_status(t0, "STOPPED", fault=8), retain=True)
        t_run = t0 + 0.1 * S
        harness.publish(t.line_status, line_status(t_run, "RUNNING", fault=8), retain=True)
        wait_snapshot(
            lambda s: s["interlock"]["reference_time"] == iso_ms(t_run) and s["interlock"]["line_state"] == "RUNNING"
        )
        crit_ts = t_run + 0.5 * S
        payload = pdm.to_bytes(pdm.pdm_result("motor01", crit_ts, "CRITICAL", 18, 0.82))
        t_pub = time.monotonic()
        harness.publish(t.pdm_result, payload)
        t_rx, stop = harness.wait_for(
            t.conveyor,
            lambda m: m["command"] == "STOP" and m["command_id"] not in seen_stops,
            timeout=5.0,
        )
        latency = t_rx - t_pub
        latencies.append(latency)
        seen_stops.add(stop["command_id"])
        assert stop["reason"] == "INTERLOCK_CRITICAL"
        # 같은 회차의 Alarm Event(수신 순서는 보지 않는다)
        harness.wait_for(
            t.alarm, lambda m: m["timestamp"] == iso_ms(crit_ts) and m["severity"] == "CRITICAL", timeout=3.0
        )
        # APPLIED·STOPPED로 응답하고 대기 해제를 확인한 뒤 다음 회차
        last_command = {
            "command": "STOP",
            "command_id": stop["command_id"],
            "source": "mqtt",
            "received_at": iso_ms(now_ms()),
            "result": "APPLIED",
            "reason": "INTERLOCK_CRITICAL",
            "error": None,
        }
        harness.publish(t.line_status, line_status(crit_ts + 0.1 * S, "STOPPED", fault=8, last_command=last_command), retain=True)
        wait_snapshot(lambda s: s["interlock"]["pending_stop"] is None and s["interlock"]["line_state"] == "STOPPED")
        print(f"round {i + 1}: CRITICAL publish -> STOP received {latency * 1000:.1f} ms")

    print(f"interlock latency ms: max {max(latencies) * 1000:.1f}, all {[round(x * 1000, 1) for x in latencies]}")
    assert len(latencies) == ROUNDS
    assert max(latencies) <= LIMIT_S, latencies
    # 회차마다 STOP은 하나씩만
    stops = [m for _t, m in harness.received(t.conveyor) if m["command"] == "STOP"]
    assert len(stops) == ROUNDS
