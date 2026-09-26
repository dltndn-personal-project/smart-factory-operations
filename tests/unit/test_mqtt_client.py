"""paho client 감싸개 `MqttClient` (docs/spec/02-mqtt.md 1·4.2절, 01-core.md 2절).

paho client 객체를 가짜(`FakePaho`)로 바꿔 끼워 broker 없이 본다.
"""

from __future__ import annotations

import queue
from dataclasses import dataclass
from types import SimpleNamespace

import paho.mqtt.client as mqtt
import pytest

from factory_operations.config import load_config
from factory_operations.domain.state import StateStore
from factory_operations.domain.worker import Inbound
from factory_operations.mqtt.client import MqttClient


@dataclass
class FakeInfo:
    rc: int


class FakePaho:
    """paho `Client` 가짜. 호출을 기록하고 `publish_rc`로 반환 코드를 정한다."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.published: list[tuple] = []
        self.subscribed: list = []
        self.publish_rc = mqtt.MQTT_ERR_SUCCESS
        self.on_connect = self.on_subscribe = self.on_disconnect = self.on_message = None

    def reconnect_delay_set(self, lo, hi):
        self.calls.append(("reconnect_delay_set", lo, hi))

    def max_queued_messages_set(self, n):
        self.calls.append(("max_queued_messages_set", n))

    def connect_async(self, host, port, keepalive):
        self.calls.append(("connect_async", host, port, keepalive))

    def loop_start(self):
        self.calls.append(("loop_start",))

    def loop_stop(self):
        self.calls.append(("loop_stop",))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def subscribe(self, topics):
        self.subscribed.append(topics)
        return mqtt.MQTT_ERR_SUCCESS, 7

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return FakeInfo(self.publish_rc)


OK = SimpleNamespace(is_failure=False)
FAIL = SimpleNamespace(is_failure=True)


def msg(topic: str, payload: bytes, retain: bool = False):
    return SimpleNamespace(topic=topic, payload=payload, retain=retain)


@pytest.fixture
def cfg():
    return load_config({"MQTT_URL": "mqtt://broker.example:1884"})


@pytest.fixture
def fake_paho():
    return FakePaho()


def make(cfg, fake_paho, fake_clock, maxsize=10):
    state = StateStore.from_config(cfg)
    q: queue.Queue = queue.Queue(maxsize=maxsize)
    c = MqttClient(cfg, state, q, fake_clock, client_factory=lambda _cfg: fake_paho)
    return c, state, q


def test_start_order(cfg, fake_paho, fake_clock):
    c, _state, _q = make(cfg, fake_paho, fake_clock)
    c.start()
    assert fake_paho.calls == [
        ("reconnect_delay_set", 1, 10),
        ("max_queued_messages_set", 100),
        ("connect_async", "broker.example", 1884, 30),
        ("loop_start",),
    ]
    c.stop()
    assert fake_paho.calls[-2:] == [("disconnect",), ("loop_stop",)]


def test_connect_subscribes_once_and_connected_after_suback(cfg, fake_paho, fake_clock):
    c, state, _q = make(cfg, fake_paho, fake_clock)
    c._on_connect(fake_paho, None, None, OK, None)
    assert len(fake_paho.subscribed) == 1  # 한 번의 subscribe([...])
    assert sorted(fake_paho.subscribed[0]) == sorted(
        [
            ("factory/sensor/+/vibration", 0),
            ("factory/product/created", 1),
            ("factory/line/status", 1),
            ("factory/vision/result", 1),
            ("factory/pdm/result", 1),
            ("factory/pdm/spectrum", 0),
        ]
    )
    assert state.mqtt_connected is False  # SUBACK 전
    c._on_subscribe(fake_paho, None, 7, [OK] * 6, None)
    assert state.mqtt_connected is True
    c._on_disconnect(fake_paho, None, None, OK, None)
    assert state.mqtt_connected is False


def test_connect_failure_does_not_subscribe(cfg, fake_paho, fake_clock):
    c, state, _q = make(cfg, fake_paho, fake_clock)
    c._on_connect(fake_paho, None, None, FAIL, None)
    assert fake_paho.subscribed == [] and state.mqtt_connected is False


def test_publish_skipped_when_disconnected(cfg, fake_paho, fake_clock):
    c, state, _q = make(cfg, fake_paho, fake_clock)
    assert c.publish("factory/control/conveyor", b"{}", 1, False) is False
    assert fake_paho.published == []  # paho를 부르지 않는다(D-20)
    state.mqtt_connected = True
    assert c.publish("factory/control/conveyor", b"{}", 1, False) is True
    assert fake_paho.published == [("factory/control/conveyor", b"{}", 1, False)]
    # paho 반환 코드가 성공이 아니면 False
    fake_paho.publish_rc = mqtt.MQTT_ERR_QUEUE_SIZE
    assert c.publish("factory/alarm/event", b"{}", 1, False) is False
    state.mqtt_connected = False
    n = len(fake_paho.published)
    assert c.publish("factory/alarm/event", b"{}") is False and len(fake_paho.published) == n


def test_on_message_only_enqueues(cfg, fake_paho, fake_clock):
    c, _state, q = make(cfg, fake_paho, fake_clock)
    raw = b"{not json at all"
    c._on_message(fake_paho, None, msg("factory/pdm/result", raw, retain=True))
    item = q.get_nowait()
    assert isinstance(item, Inbound)
    assert (item.topic, item.payload, item.retain) == ("factory/pdm/result", raw, True)
    assert (item.recv_wall, item.recv_mono) == (fake_clock.wall(), fake_clock.mono())
    assert q.empty()


def test_inbound_overflow_counted(cfg, fake_paho, fake_clock):
    c, state, q = make(cfg, fake_paho, fake_clock, maxsize=2)
    for _ in range(5):
        c._on_message(fake_paho, None, msg("factory/line/status", b"{}"))
    assert q.qsize() == 2
    assert state.snapshot_view().counters == {("inbound_queue_overflow", "factory/line/status"): 3}
