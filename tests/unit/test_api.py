"""HTTP API (docs/spec/06-dashboard.md 2절, 08-verification.md 3.5절).

FastAPI `TestClient`, StateStore(값을 직접 넣음), inbound 큐를 읽어 future에 답하는 가짜 워커로 본다.
"""

from __future__ import annotations

import queue
import re
import threading
from typing import Any

import pytest
from fastapi.testclient import TestClient

from factory_operations.clock import TS_PATTERN
from factory_operations.config import load_config
from factory_operations.domain.state import StateStore
from factory_operations.domain.worker import OperatorCommand, OperatorCommandError
from factory_operations.web.api import create_app

JPEG_MAGIC = b"\xff\xd8\xff"


class FakeWorker:
    """inbound 큐를 읽어 `mode`대로 답한다: ok | mqtt_disconnected | invalid_command | silent."""

    def __init__(self, q: queue.Queue):
        self.q = q
        self.mode = "ok"
        self.received: list[OperatorCommand] = []
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self.q.get(timeout=0.05)
            except queue.Empty:
                continue
            self.received.append(item)
            if self.mode == "silent":
                continue
            if self.mode == "ok":
                item.future.set_result(
                    {
                        "command_id": "11111111-2222-4333-8444-555555555555",
                        "command": item.command,
                        "timestamp": "2026-09-25T05:21:00.512Z",
                        "judged_state": "CRITICAL",
                    }
                )
            else:
                item.future.set_exception(OperatorCommandError(self.mode))

    def stop(self) -> None:
        self._stop.set()
        self._t.join(timeout=1)


@pytest.fixture
def cfg(tmp_image_root):
    return load_config({"IMAGE_ROOT": str(tmp_image_root)})


@pytest.fixture
def state(cfg):
    return StateStore.from_config(cfg)


@pytest.fixture
def inbound():
    return queue.Queue(maxsize=10)


@pytest.fixture
def worker(inbound):
    w = FakeWorker(inbound)
    yield w
    w.stop()


@pytest.fixture
def client(cfg, state, inbound, fake_clock, worker):
    app = create_app(cfg, state, inbound, fake_clock, commit="abc1234", command_timeout_s=0.3)
    with TestClient(app) as c:
        yield c


def test_healthz(client, state):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "commit": "abc1234", "mqtt_connected": False, "db_ok": False}
    state.mqtt_connected = True
    state.set_db_ok(True)
    assert client.get("/healthz").json() == {"status": "ok", "commit": "abc1234", "mqtt_connected": True, "db_ok": True}


def test_readyz(client, state):
    r = client.get("/readyz")
    assert r.status_code == 503 and r.json()["mqtt_connected"] is False
    state.mqtt_connected = True
    assert client.get("/readyz").status_code == 503  # DB 아직
    state.set_db_ok(True)
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json() == client.get("/healthz").json()
    state.mqtt_connected = False  # 끊기면 다시 503
    assert client.get("/readyz").status_code == 503


def test_snapshot_no_store(client, state, fake_clock):
    r = client.get("/api/snapshot")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["schema_version"] == 1
    assert re.fullmatch(TS_PATTERN, body["generated_at"])
    assert body["line"] == {"status": "NONE"} and body["correlation"] is None
    state.mqtt_connected = True
    assert client.get("/api/snapshot").json()["mqtt_connected"] is True


def test_images_status_codes(client, tmp_image_root):
    r = client.get("/api/images/products/P-00000001.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content.startswith(JPEG_MAGIC)
    assert r.content == (tmp_image_root / "products" / "P-00000001.jpg").read_bytes()
    # png는 확장자로
    (tmp_image_root / "gradcam" / "P-00000001.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    r = client.get("/api/images/gradcam/P-00000001.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    # 형식이 틀리면 400
    for bad in (
        "other/P-00000001.jpg",
        "products/P-00000001.gif",
        "products/.hidden.jpg",
        "products/%2e%2e/secret.jpg",
        "products//P-00000001.jpg",
        "products/a%5Cb.jpg",
        "products",
    ):
        r = client.get(f"/api/images/{bad}")
        assert r.status_code == 400, bad
        assert r.json()["error"] == "invalid_path"
        assert set(r.json()) == {"error", "detail"}
    # 형식은 맞지만 파일이 없으면 404
    r = client.get("/api/images/products/P-00000099.jpg")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    r = client.get("/api/images/gradcam/P-00000001.jpg")
    assert r.status_code == 404


def test_images_symlink_outside_root(client, tmp_image_root, tmp_path):
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"\xff\xd8\xffsecret")
    (tmp_image_root / "products" / "P-00000002.jpg").symlink_to(outside)
    assert client.get("/api/images/products/P-00000002.jpg").status_code == 404


def test_conveyor_status_codes(client, worker):
    # 202: 워커 결과를 그대로
    r = client.post("/api/conveyor", json={"command": "STOP"})
    assert r.status_code == 202
    assert r.json() == {
        "command_id": "11111111-2222-4333-8444-555555555555",
        "command": "STOP",
        "timestamp": "2026-09-25T05:21:00.512Z",
        "judged_state": "CRITICAL",
    }
    assert [c.command for c in worker.received] == ["STOP"]
    assert client.post("/api/conveyor", json={"command": "START"}).status_code == 202
    # 422: 본문이 틀리면 큐에 넣지 않는다
    n = len(worker.received)
    for body in ({"command": "stop"}, {"command": "RESTART"}, {}, ["START"], {"cmd": "START"}, {"command": None}):
        r = client.post("/api/conveyor", json=body)
        assert r.status_code == 422, body
        assert r.json()["error"] == "invalid_command" and set(r.json()) == {"error", "detail"}
    r = client.post("/api/conveyor", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_command"
    assert len(worker.received) == n
    # 워커가 invalid_command로 답해도 422
    worker.mode = "invalid_command"
    r = client.post("/api/conveyor", json={"command": "START"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_command"
    # 503: MQTT 끊김
    worker.mode = "mqtt_disconnected"
    r = client.post("/api/conveyor", json={"command": "STOP"})
    assert r.status_code == 503
    assert r.json()["error"] == "mqtt_disconnected" and set(r.json()) == {"error", "detail"}
    # 504: 워커가 제한 시간 안에 답하지 않음. future는 취소되어 늦은 답은 버려진다
    worker.mode = "silent"
    r = client.post("/api/conveyor", json={"command": "STOP"})
    assert r.status_code == 504 and r.json()["error"] == "timeout"
    assert worker.received[-1].future.cancelled()


def test_conveyor_queue_full(cfg, state, fake_clock):
    q: queue.Queue[Any] = queue.Queue(maxsize=1)
    q.put_nowait("busy")  # 아무도 읽지 않는 가득 찬 큐
    app = create_app(cfg, state, q, fake_clock, command_timeout_s=0.2)
    with TestClient(app) as c:
        r = c.post("/api/conveyor", json={"command": "STOP"})
    assert r.status_code == 504 and r.json()["error"] == "timeout"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<html" in r.text
    r = client.get("/static/index.html")
    assert r.status_code == 200
    assert client.get("/static/nope.js").status_code == 404


def test_standalone_defaults():
    """조립 전 단독 실행(state·큐·시계 없음)에도 모든 endpoint가 답한다."""
    with TestClient(create_app(command_timeout_s=0.1)) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 503
        assert c.get("/api/snapshot").json()["line"] == {"status": "NONE"}
        assert c.post("/api/conveyor", json={"command": "STOP"}).status_code == 504
