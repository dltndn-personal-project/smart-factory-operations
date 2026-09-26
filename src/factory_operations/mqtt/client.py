"""paho MQTT client (docs/spec/02-mqtt.md 1·4.2·5절, 01-core.md 2절, DECISIONS D-08·D-20).

paho를 import하는 모듈은 이 파일 하나다(01 1절). 콜백은 paho 네트워크 스레드에서 돈다.

- `on_message`: 파싱하지 않고 `Inbound`를 만들어 inbound 큐에 `put_nowait`만 한다. 가득 차면 버리고
  StateStore 카운터 `("inbound_queue_overflow", topic)`을 올리고 `queue_overflow` 로그를 쓴다.
- `mqtt_connected`(StateStore)는 연결 뒤 구독 SUBACK을 받으면 True, 끊기면 False다(D-50).
- `publish()`: `mqtt_connected`가 False이면 paho를 부르지 않고 False(D-20). paho 반환 코드가 성공이
  아니면 ERROR 로그와 False.
"""

from __future__ import annotations

import queue
from typing import Any, Callable

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion

from ..clock import Clock, SystemClock
from ..domain.worker import Inbound
from ..log import EventLogger
from . import topics as T

OVERFLOW_KEY = "inbound_queue_overflow"


def make_paho_client(cfg: Any) -> mqtt.Client:
    """02 1절의 paho client 객체."""
    return mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=cfg.mqtt.client_id,
        protocol=MQTTProtocolVersion.MQTTv311,
        clean_session=True,
    )


class MqttClient:
    """Operations의 MQTT 연결 하나. `Processor`의 `publisher`로 쓴다."""

    def __init__(
        self,
        cfg: Any,
        state: Any,
        inbound_queue: "queue.Queue[Any]",
        clock: Clock | None = None,
        *,
        topics: T.Topics | None = None,
        log: EventLogger | None = None,
        client_factory: Callable[[Any], Any] = make_paho_client,
    ) -> None:
        self.cfg = cfg
        self.state = state
        self.inbound = inbound_queue
        self.clock = clock or SystemClock()
        self.topics = topics or T.Topics(cfg.mqtt.topic_prefix)
        self.log = log or EventLogger("factory_operations.mqtt", clock=self.clock)
        self._stopping = False
        self._sub_mid: int | None = None
        self.client = client_factory(cfg)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    # --- 수명 주기 (01 7절) --------------------------------------------------

    def start(self) -> None:
        m = self.cfg.mqtt
        self.client.reconnect_delay_set(m.reconnect_min_s, m.reconnect_max_s)
        self.client.max_queued_messages_set(m.max_queued)
        self.client.connect_async(m.host, m.port, keepalive=m.keepalive_s)
        self.client.loop_start()
        self.log.info("mqtt_starting", host=m.host, port=m.port, client_id=m.client_id)

    def stop(self) -> None:
        self._stopping = True
        self.state.mqtt_connected = False
        try:
            self.client.disconnect()
        except Exception as e:  # 연결 전이면 paho가 오류를 낼 수 있다
            self.log.info("mqtt_disconnect_error", error=repr(e))
        self.client.loop_stop()

    # --- 콜백 (paho 스레드) ---------------------------------------------------

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        if getattr(reason_code, "is_failure", False):
            self.log.warning("mqtt_connect_failed", reason=str(reason_code))
            return
        result, mid = client.subscribe(self.topics.subscriptions())
        self._sub_mid = mid
        if result != mqtt.MQTT_ERR_SUCCESS:
            self.log.error("mqtt_subscribe_failed", reason=mqtt.error_string(result))
            return
        self.log.info("mqtt_connected", subscriptions=[t for t, _ in self.topics.subscriptions()], throttle=False)

    def _on_subscribe(self, client: Any, userdata: Any, mid: int, reason_codes: Any, properties: Any = None) -> None:
        failed = [str(rc) for rc in (reason_codes or []) if getattr(rc, "is_failure", False)]
        if failed:
            self.log.error("mqtt_subscribe_failed", reason=",".join(failed))
        if mid == self._sub_mid:
            self.state.mqtt_connected = True
            self.log.info("mqtt_subscribed", mid=mid, throttle=False)

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        self.state.mqtt_connected = False
        if self._stopping:
            self.log.info("mqtt_disconnected", reason=str(reason_code), throttle=False)
        else:
            self.log.warning("mqtt_disconnected", reason=str(reason_code))

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """파싱 없이 inbound 큐에 넣기만 한다(01 2절)."""
        item = Inbound(msg.topic, bytes(msg.payload), bool(msg.retain), self.clock.wall(), self.clock.mono())
        try:
            self.inbound.put_nowait(item)
        except queue.Full:
            self.state.incr((OVERFLOW_KEY, msg.topic))
            self.log.warning("queue_overflow", queue="inbound", topic=msg.topic)

    # --- 발행 (02 4.2절) -----------------------------------------------------

    def publish(self, topic: str, payload: bytes, qos: int = 1, retain: bool = False) -> bool:
        if not self.state.mqtt_connected:
            return False
        info = self.client.publish(topic, payload, qos=qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self.log.error("mqtt_publish_failed", topic=topic, reason=mqtt.error_string(info.rc))
            return False
        return True
