"""Topic (docs/spec/02-mqtt.md 2절)."""

from __future__ import annotations

import pytest

from factory_operations.mqtt import topics as t
from factory_operations.mqtt.topics import Topics, TopicMatch


def test_topics_with_prefix():
    d = Topics()
    assert d.sensor_vibration == "factory/sensor/+/vibration"
    assert d.product_created == "factory/product/created"
    assert d.line_status == "factory/line/status"
    assert d.vision_result == "factory/vision/result"
    assert d.pdm_result == "factory/pdm/result"
    assert d.pdm_spectrum == "factory/pdm/spectrum"
    assert d.conveyor == "factory/control/conveyor"
    assert d.alarm == "factory/alarm/event"
    assert d.sensor("motor01") == "factory/sensor/motor01/vibration"
    assert dict(d.subscriptions()) == {
        "factory/sensor/+/vibration": 0,
        "factory/product/created": 1,
        "factory/line/status": 1,
        "factory/vision/result": 1,
        "factory/pdm/result": 1,
        "factory/pdm/spectrum": 0,
    }
    p = Topics("plant/a")
    assert p.line_status == "plant/a/line/status"
    assert p.conveyor == "plant/a/control/conveyor"
    assert p.alarm == "plant/a/alarm/event"
    assert all(topic.startswith("plant/a/") for topic, _ in p.subscriptions())
    assert (t.CONVEYOR_QOS, t.CONVEYOR_RETAIN, t.ALARM_QOS, t.ALARM_RETAIN) == (1, False, 1, False)
    for bad in ("", "factory/", "fac+tory", "#"):
        with pytest.raises(ValueError):
            Topics(bad)


def test_kind_of_topic():
    d = Topics()
    assert d.kind_of("factory/sensor/motor01/vibration") == TopicMatch(t.SENSOR_VIBRATION, "motor01")
    assert d.kind_of("factory/product/created") == TopicMatch(t.PRODUCT_CREATED)
    assert d.kind_of("factory/line/status") == TopicMatch(t.LINE_STATUS)
    assert d.kind_of("factory/vision/result") == TopicMatch(t.VISION_RESULT)
    assert d.kind_of("factory/pdm/result") == TopicMatch(t.PDM_RESULT)
    assert d.kind_of("factory/pdm/spectrum") == TopicMatch(t.PDM_SPECTRUM)
    # 구독하지 않는 Topic
    for other in (
        "factory/control/conveyor",
        "factory/alarm/event",
        "factory/sensor//vibration",
        "factory/sensor/motor01/temperature",
        "factory/sensor/a/b/vibration",
        "other/line/status",
        "factoryx/line/status",
        "factory/line/status/extra",
    ):
        assert d.kind_of(other) is None, other
    p = Topics("plant/a")
    assert p.kind_of("plant/a/sensor/m2/vibration") == TopicMatch(t.SENSOR_VIBRATION, "m2")
    assert p.kind_of("factory/line/status") is None
