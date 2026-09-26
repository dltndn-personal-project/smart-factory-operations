"""가짜 입력 자체 검사 (docs/spec/07-runtime.md 5절, DECISIONS D-44).

`scripts/fake_feed.py`를 파일 경로로 불러 `Feed`에 시각을 직접 흘리고, 만든 메시지를 OPS-2 파서에 넣는다.
MQTT·Docker 없이 돈다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from factory_operations.mqtt import payloads as P
from factory_operations.mqtt.topics import INPUT_KINDS, Topics

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "fake_feed.py"
PAYLOADS = REPO / "tests" / "fixtures" / "payloads"
T0 = datetime(2026, 9, 25, 5, 20, 0, tzinfo=timezone.utc)
TICK = timedelta(seconds=0.1)


def load_fake_feed():
    spec = importlib.util.spec_from_file_location("fake_feed", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("fake_feed", mod)
    spec.loader.exec_module(mod)
    return mod


ff = load_fake_feed()


class Runner:
    """Feed를 0.1초씩 흘리며 메시지를 모은다."""

    def __init__(self, **kw):
        self.feed = ff.Feed(**kw)
        self.now = T0
        self.messages: list[tuple[datetime, str, dict, int, bool]] = []

    def run(self, seconds: float) -> list:
        start = len(self.messages)
        for _ in range(round(seconds / 0.1)):
            for topic, payload, qos, retain in self.feed.step(self.now):
                self.messages.append((self.now, topic, payload, qos, retain))
            self.now += TICK
        return self.messages[start:]

    def command(self, payload, retained: bool = False) -> dict:
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        out = self.feed.on_command(raw, retained, self.now)
        assert len(out) == 1
        topic, msg, qos, retain = out[0]
        assert topic == self.feed.topics.line and retain is True and qos == 1
        self.messages.append((self.now, topic, msg, qos, retain))
        return msg

    def of(self, topic: str, msgs=None) -> list[dict]:
        return [m[2] for m in (self.messages if msgs is None else msgs) if m[1] == topic]


def conveyor(command: str, command_id: str = "11111111-2222-4333-8444-555555555555") -> dict:
    return {
        "schema_version": 1,
        "command": command,
        "command_id": command_id,
        "timestamp": "2026-09-25T05:21:00.012Z",
        "reason": f"OPERATOR_{command}",
    }


def parse(topics: Topics, topic: str, payload: dict):
    match = topics.kind_of(topic)
    assert match is not None, topic
    return match.kind, P.parse(match.kind, topic, json.dumps(payload).encode())


# ---------------------------------------------------------------------------


def test_messages_parse():
    r = Runner()
    r.run(12.0)
    r.command(conveyor("STOP"))
    r.run(2.0)
    r.command(conveyor("START"))
    r.run(3.0)
    topics = Topics("factory")
    kinds = Counter()
    for _, topic, payload, _, _ in r.messages:
        kind, parsed = parse(topics, topic, payload)
        assert not isinstance(parsed, P.Rejected), (topic, parsed, str(payload)[:300])
        kinds[kind] += 1
    assert set(kinds) == set(INPUT_KINDS), kinds
    # 여섯 Topic 모두, 센서는 0.1초마다
    assert kinds["sensor_vibration"] == 170
    assert kinds["pdm_result"] >= 20 and kinds["pdm_spectrum"] >= 10
    assert kinds["product_created"] == kinds["vision_result"] >= 5


def test_message_shapes():
    r = Runner()
    r.run(3.0)
    chunk = r.of(r.feed.topics.sensor)[-1]
    assert chunk["sample_rate_hz"] == 10000
    assert len(chunk["vibration_x"]) == len(chunk["vibration_y"]) == len(chunk["vibration_z"]) == 1000
    seqs = [c["seq"] for c in r.of(r.feed.topics.sensor)]
    assert seqs == list(range(len(seqs)))
    sp = r.of(r.feed.topics.spectrum)[-1]
    for k in ("spectrum_x", "spectrum_y", "spectrum_z", "envelope_x", "envelope_y", "envelope_z"):
        assert len(sp[k]) == 501 and min(sp[k]) >= 0
    # PdM timestamp = 마지막 chunk 끝, window_start = 1초 전
    res = r.of(r.feed.topics.pdm)[-1]
    ts = P.parse_pdm_result("factory/pdm/result", json.dumps(res).encode())
    assert ts.timestamp - ts.window_start == timedelta(seconds=1)
    assert res["timestamp"] in {c["timestamp"] for c in r.of(r.feed.topics.sensor)}
    # QoS·retain: Line Status만 retain
    for _, topic, _, qos, retain in r.messages:
        assert retain == (topic == r.feed.topics.line)
        assert qos == (0 if topic in (r.feed.topics.sensor, r.feed.topics.spectrum) else 1)


def test_pdm_keys_match_fixture():
    r = Runner()
    r.run(2.0)
    result_keys = set(json.loads((PAYLOADS / "shared_pdm_result.json").read_text()))
    spectrum_keys = set(json.loads((PAYLOADS / "shared_pdm_spectrum.json").read_text()))
    results = r.of(r.feed.topics.pdm)
    spectra = r.of(r.feed.topics.spectrum)
    assert results and spectra
    for m in results:
        assert set(m) == result_keys, set(m) ^ result_keys
    for m in spectra:
        assert set(m) == spectrum_keys, set(m) ^ spectrum_keys


def test_scenario_levels():
    level = ff.scenario_level
    for s, want in ((0, 0), (39.9, 0), (40, 3), (69.9, 3), (70, 6), (159.9, 6), (160, 9), (600, 9)):
        assert level(s) == want, (s, level(s))
    # Feed에서: Line Status fault_level이 시나리오 시각에 바뀐다(배속 10 → 4·7·16초)
    r = Runner(speed=10.0)
    r.run(20.0)
    changes = []
    last = None
    for at, topic, payload, _, _ in r.messages:
        if topic == r.feed.topics.line and payload["fault_level"] != last:
            last = payload["fault_level"]
            changes.append((round((at - T0).total_seconds(), 1), last))
    assert [lv for _, lv in changes] == [0, 3, 6, 9]
    assert [t for t, _ in changes][1:] == [4.0, 7.0, 16.0]
    # HI·State는 목표식과 Shared 4.2 구간(±2 잡음)
    assert ff.target_hi(0) == 100 and ff.target_hi(9) == 13
    assert [ff.state_of(h) for h in (80, 79, 60, 59, 40, 39)] == ["NORMAL", "CAUTION", "CAUTION", "WARNING", "WARNING", "CRITICAL"]
    last_hi = [m["health_index"] for m in r.of(r.feed.topics.pdm)][-5:]
    assert all(abs(h - 13) <= 2 for h in last_hi)
    assert {m["state"] for m in r.of(r.feed.topics.pdm)[-5:]} == {"CRITICAL"}


def test_image_path_matches_product_id():
    r = Runner(start_id=7)
    r.run(21.0)
    created = r.of(r.feed.topics.product)
    visions = r.of(r.feed.topics.vision)
    assert [m["product_id"] for m in created] == [f"P-{i:08d}" for i in range(7, 7 + len(created))]
    assert len(created) == 11  # 0초부터 2초마다(0, 2, …, 20초)
    for m in created:
        assert m["image_path"] == f"products/{m['product_id']}.jpg"
    by_id = {m["product_id"]: m for m in created}
    for v in visions:
        assert v["image_path"] == by_id[v["product_id"]]["image_path"]
        assert v["timestamp"] == by_id[v["product_id"]]["timestamp"]
        assert v["judgement_source"] == "PASS_THROUGH" and v["confidence"] is None and v["gradcam_path"] is None
        assert (v["defect_type"] is None) == (v["defect"] is False)
    # Vision은 Product Created 0.2초 뒤
    times = {(m[1], m[2]["product_id"]): m[0] for m in r.messages if m[1] in (r.feed.topics.product, r.feed.topics.vision)}
    for pid in by_id:
        if (r.feed.topics.vision, pid) in times:
            assert times[(r.feed.topics.vision, pid)] - times[(r.feed.topics.product, pid)] == timedelta(seconds=0.2)


def test_control_updates_last_command():
    r = Runner(speed=10.0)
    r.run(17.0)  # Fault Level 9
    assert r.feed.fault_level == 9

    ls = r.command(conveyor("STOP", "a" * 8))
    assert ls["conveyor"] == "STOPPED" and ls["motor_rpm"] == 0.0 and ls["production_active"] is False
    lc = ls["last_command"]
    assert lc["command"] == "STOP" and lc["command_id"] == "a" * 8 and lc["result"] == "APPLIED"
    assert lc["source"] == "mqtt" and lc["error"] is None and lc["reason"] == "OPERATOR_STOP"
    stopped = r.run(3.0)
    assert not r.of(r.feed.topics.pdm, stopped) and not r.of(r.feed.topics.spectrum, stopped)
    assert not r.of(r.feed.topics.product, stopped)
    assert all(c["rpm"] == 0.0 for c in r.of(r.feed.topics.sensor, stopped))
    # 1초마다 Line Status가 같은 last_command를 싣는다
    assert all(m["last_command"]["command_id"] == "a" * 8 for m in r.of(r.feed.topics.line, stopped))

    assert r.command(conveyor("STOP", "b" * 8))["last_command"]["result"] == "NO_CHANGE"

    rej = r.command(conveyor("START", "c" * 8), retained=True)["last_command"]
    assert rej["result"] == "REJECTED" and rej["error"] == "retained_ignored" and rej["command_id"] is None
    assert r.feed.running is False

    bad = r.command(b"not json")["last_command"]
    assert bad["result"] == "REJECTED" and bad["error"] == "invalid_json"

    ls = r.command(conveyor("START", "d" * 8))
    assert ls["conveyor"] == "RUNNING" and ls["fault_level"] == 0
    assert ls["last_command"]["result"] == "APPLIED" and ls["last_command"]["command_id"] == "d" * 8
    restart_ts = ls["timestamp"]
    after = r.run(2.0)
    # 재가동 뒤 첫 PdM 결과는 1초 윈도우가 찬 뒤, 기준 시각보다 뒤
    first = r.of(r.feed.topics.pdm, after)[0]
    assert first["window_start"] >= restart_ts and first["timestamp"] > restart_ts
    assert first["state"] == "NORMAL"
    assert r.command(conveyor("START", "e" * 8))["last_command"]["result"] == "NO_CHANGE"
    # 모든 Line Status가 파서로 받아지고 last_command가 해석된다
    for m in r.of(r.feed.topics.line):
        parsed = P.parse_line_status("factory/line/status", json.dumps(m).encode())
        assert not isinstance(parsed, P.Rejected), parsed


def test_offline_message():
    feed = ff.Feed()
    topic, payload, qos, retain = feed.offline(T0)
    assert topic == "factory/line/status" and retain is True and qos == 1
    assert isinstance(P.parse_line_status(topic, json.dumps(payload).encode()), P.LineOffline)


@pytest.mark.parametrize("argv", [["--speed", "0"], ["--start-id", "0"]])
def test_bad_args(argv):
    with pytest.raises(SystemExit):
        ff.parse_args(argv)
