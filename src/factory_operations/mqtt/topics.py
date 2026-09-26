"""Topic 이름 (docs/spec/02-mqtt.md 2절, AGREEMENTS.md A-01).

접두사 `p`(설정 `mqtt.topic_prefix`)로 Topic을 만든다. QoS·retain은 코드 상수다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 입력 종류 이름
SENSOR_VIBRATION = "sensor_vibration"
PRODUCT_CREATED = "product_created"
LINE_STATUS = "line_status"
VISION_RESULT = "vision_result"
PDM_RESULT = "pdm_result"
PDM_SPECTRUM = "pdm_spectrum"

INPUT_KINDS = (SENSOR_VIBRATION, PRODUCT_CREATED, LINE_STATUS, VISION_RESULT, PDM_RESULT, PDM_SPECTRUM)

# 구독 QoS
SUBSCRIBE_QOS = {
    SENSOR_VIBRATION: 0,
    PRODUCT_CREATED: 1,
    LINE_STATUS: 1,
    VISION_RESULT: 1,
    PDM_RESULT: 1,
    PDM_SPECTRUM: 0,
}

# 발행 QoS·retain
CONVEYOR_QOS, CONVEYOR_RETAIN = 1, False
ALARM_QOS, ALARM_RETAIN = 1, False

# 접두사 뒤의 고정 경로
_FIXED = {
    "product/created": PRODUCT_CREATED,
    "line/status": LINE_STATUS,
    "vision/result": VISION_RESULT,
    "pdm/result": PDM_RESULT,
    "pdm/spectrum": PDM_SPECTRUM,
}


@dataclass(frozen=True)
class TopicMatch:
    kind: str
    sensor_id: str | None = None  # Sensor Vibration Topic의 `+` 자리 값


class Topics:
    def __init__(self, prefix: str = "factory"):
        if not prefix or prefix.endswith("/") or "+" in prefix or "#" in prefix:
            raise ValueError(f"invalid topic prefix: {prefix!r}")
        self.prefix = prefix
        p = prefix
        self.sensor_vibration = f"{p}/sensor/+/vibration"
        self.product_created = f"{p}/product/created"
        self.line_status = f"{p}/line/status"
        self.vision_result = f"{p}/vision/result"
        self.pdm_result = f"{p}/pdm/result"
        self.pdm_spectrum = f"{p}/pdm/spectrum"
        self.conveyor = f"{p}/control/conveyor"
        self.alarm = f"{p}/alarm/event"

    def sensor(self, sensor_id: str) -> str:
        return f"{self.prefix}/sensor/{sensor_id}/vibration"

    def subscriptions(self) -> list[tuple[str, int]]:
        """한 번의 `subscribe([...])`에 넘길 (topic, qos) 목록 (02 1절)."""
        return [(getattr(self, kind), SUBSCRIBE_QOS[kind]) for kind in INPUT_KINDS]

    def kind_of(self, topic: str) -> TopicMatch | None:
        """수신 Topic의 입력 종류. 구독하지 않는 Topic이면 None."""
        head = self.prefix + "/"
        if not topic.startswith(head):
            return None
        rest = topic[len(head):]
        kind = _FIXED.get(rest)
        if kind is not None:
            return TopicMatch(kind)
        parts = rest.split("/")
        if len(parts) == 3 and parts[0] == "sensor" and parts[2] == "vibration" and parts[1]:
            return TopicMatch(SENSOR_VIBRATION, parts[1])
        return None
