"""JSON 로그와 같은 사유 억제 (docs/spec/01-core.md 6절, 08-verification.md 3.1절)."""

from __future__ import annotations

import io
import json
import logging
import re

import pytest

from factory_operations.clock import TS_PATTERN
from factory_operations.log import EventLogger, setup_logging


@pytest.fixture
def log_stream():
    root = logging.getLogger()
    saved = (list(root.handlers), root.level)
    buf = io.StringIO()
    setup_logging("DEBUG", stream=buf)
    yield buf
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved[0]:
        root.addHandler(h)
    root.setLevel(saved[1])


def lines(buf: io.StringIO) -> list[dict]:
    return [json.loads(x) for x in buf.getvalue().splitlines() if x.strip()]


def test_json_line_format(log_stream, fake_clock):
    log = EventLogger("factory_operations.test", clock=fake_clock)
    log.info("mqtt_connected", host="broker", port=1883)
    log.warning("message_rejected", topic="factory/line/status", reason="invalid_json", payload=b"{oops")
    out = lines(log_stream)
    assert len(out) == 2
    first = out[0]
    assert list(first)[:4] == ["ts", "level", "logger", "event"]
    assert re.match(TS_PATTERN, first["ts"])
    assert first["level"] == "INFO"
    assert first["logger"] == "factory_operations.test"
    assert first["event"] == "mqtt_connected"
    assert first["host"] == "broker" and first["port"] == 1883
    assert out[1]["payload"] == "{oops"
    assert "suppressed" not in out[1]


def test_level_filter(log_stream, fake_clock):
    logging.getLogger().setLevel("INFO")
    log = EventLogger("factory_operations.test", clock=fake_clock)
    assert log.debug("correlation_done") is False
    assert log.info("db_connected") is True
    assert [x["event"] for x in lines(log_stream)] == ["db_connected"]


def test_plain_stdlib_record_is_json(log_stream):
    logging.getLogger("uvicorn.error").info("Started server process [%d]", 42)
    (rec,) = lines(log_stream)
    assert rec["event"] == "Started server process [42]"
    assert rec["logger"] == "uvicorn.error"


def test_suppression_window(log_stream, fake_clock):
    log = EventLogger("factory_operations.test", clock=fake_clock)
    written = []
    # 같은 (event, topic, reason) 11번이 10초 안에: 한 줄
    for i in range(11):
        written.append(log.warning("message_rejected", topic="factory/sensor/motor01/vibration", reason="invalid_json"))
        if i < 10:
            fake_clock.advance(0.5)
    assert written == [True] + [False] * 10
    assert len(lines(log_stream)) == 1
    assert "suppressed" not in lines(log_stream)[0]
    # 첫 줄(0초) 뒤 10초가 되면 다음 줄에 suppressed 10
    fake_clock.advance(5.0)
    assert log.warning("message_rejected", topic="factory/sensor/motor01/vibration", reason="invalid_json")
    out = lines(log_stream)
    assert len(out) == 2
    assert out[1]["suppressed"] == 10
    # 억제 뒤 새 창은 0부터 센다
    fake_clock.advance(10.0)
    assert log.warning("message_rejected", topic="factory/sensor/motor01/vibration", reason="invalid_json")
    assert "suppressed" not in lines(log_stream)[2]


def test_suppression_keys_are_independent(log_stream, fake_clock):
    log = EventLogger("factory_operations.test", clock=fake_clock)
    assert log.warning("message_rejected", topic="factory/line/status", reason="invalid_json")
    assert log.warning("message_rejected", topic="factory/line/status", reason="missing_field:conveyor")
    assert log.warning("message_rejected", topic="factory/pdm/result", reason="invalid_json")
    assert log.warning("queue_overflow", topic="factory/line/status", reason="invalid_json")
    assert not log.warning("message_rejected", topic="factory/line/status", reason="invalid_json")
    assert len(lines(log_stream)) == 4


def test_info_events_not_throttled_by_default(log_stream, fake_clock):
    log = EventLogger("factory_operations.test", clock=fake_clock)
    for _ in range(3):
        assert log.info("alarm_raised", severity="CRITICAL")
    assert len(lines(log_stream)) == 3
    # 호출에서 억제를 켤 수 있다
    assert log.info("command_result", throttle=True, reason="x")
    assert not log.info("command_result", throttle=True, reason="x")


def test_suppression_just_before_window(log_stream, fake_clock):
    log = EventLogger("factory_operations.test", clock=fake_clock)
    assert log.warning("db_error", reason="connect")
    fake_clock.advance(9.875)
    assert not log.warning("db_error", reason="connect")
    fake_clock.advance(0.125)
    assert log.warning("db_error", reason="connect")
    assert lines(log_stream)[-1]["suppressed"] == 1
