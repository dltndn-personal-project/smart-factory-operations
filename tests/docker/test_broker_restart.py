"""broker 재시작 뒤 복구 (docs/spec/02-mqtt.md 5절, 08-verification.md 3.6절, DECISIONS D-43).

세션 broker를 흔들지 않도록 자기 Mosquitto 컨테이너(빈 포트 고정)를 띄워 앱을 연결하고
`docker restart`한다. 고정 포트라 재시작 뒤에도 같은 주소로 다시 연결된다.
"""

from __future__ import annotations

import time

from fixtures.payloads import pdm

from .conftest import docker
from .test_app_flow import now_ms, wait_db

RECOVER_S = 15.0


def wait_status(app, code: int, timeout: float) -> float:
    """`/readyz`가 `code`가 될 때까지. 걸린 시간(초)."""
    t0 = time.monotonic()
    while True:
        try:
            if app.get("/readyz", timeout=1.0).status_code == code:
                return time.monotonic() - t0
        except Exception:
            pass
        if time.monotonic() - t0 >= timeout:
            raise AssertionError(f"/readyz did not become {code} within {timeout}s")
        time.sleep(0.1)


def test_broker_restart_recovers(broker_container_factory, app_factory, harness_factory, clean_db):
    broker = broker_container_factory()
    app = app_factory(broker.url, clean_db.url)
    assert app.get("/readyz").status_code == 200

    t_restart = time.monotonic()
    docker("restart", broker.id, timeout=60)
    # 끊김이 보인다(재시작 중 또는 직후)
    wait_status(app, 503, RECOVER_S)
    # 재시작 명령부터 15초 안에 다시 준비
    wait_status(app, 200, RECOVER_S)
    recovered = time.monotonic() - t_restart
    print(f"broker restart: /readyz 200 again after {recovered:.2f}s")
    assert recovered <= RECOVER_S

    # 재연결 뒤 보낸 PdM Result가 기록된다(구독이 다시 걸렸다)
    h = harness_factory(broker.port, app.prefix)
    ts = now_ms()
    h.publish(h.topics.pdm_result, pdm.to_bytes(pdm.pdm_result("motor01", ts, "NORMAL", 93, 0.07)))

    def recorded(conn):
        return conn.execute('SELECT health_index FROM equipment_state WHERE "timestamp" = %s', (ts,)).fetchone()

    assert wait_db(clean_db, recorded, 5.0) == (93,)
