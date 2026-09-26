"""Payload 검증과 생성 (docs/spec/02-mqtt.md 3·4절, 08-verification.md 3.2절)."""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import datetime, timezone

import numpy as np
import pytest

from factory_operations.clock import TS_PATTERN, parse_ts
from factory_operations.mqtt import payloads as P
from factory_operations.mqtt import topics as T
from fixtures.payloads import pdm

SENSOR_TOPIC = "factory/sensor/motor01/vibration"
UTC = timezone.utc


def enc(obj) -> bytes:
    return json.dumps(obj).encode()


def without(obj: dict, key: str) -> dict:
    o = copy.deepcopy(obj)
    del o[key]
    return o


def with_(obj: dict, **kv) -> dict:
    o = copy.deepcopy(obj)
    o.update(kv)
    return o


@pytest.fixture
def ex(payload_examples):
    return copy.deepcopy(payload_examples)


def online_line(ex) -> dict:
    return ex["shared_line_status"]


# 입력 종류 → (파서, fixture 이름, Topic, 필수 필드와 틀린 값 후보)
REQUIRED = {
    "sensor": (
        P.parse_sensor_vibration,
        "shared_sensor_vibration",
        SENSOR_TOPIC,
        {
            "sensor_id": ["Motor01", "", 1, None],
            "timestamp": ["2026-09-25T05:20:13Z", 0, None],
            "seq": [-1, 1.5, "1", True, None],
            "sample_rate_hz": [0, -10, 10000.5, "10000", None],
            "rpm": [-0.1, "1800", True, None],
            "temperature": ["37", None, [1.0]],
            "vibration_x": [[], [0.1, "x"], [True, 0.1], "0.1", None, [0.1] * 10001],
            "vibration_y": [[0.1, None], {}, None],
            "vibration_z": [[[0.1]], None],
        },
    ),
    "line": (
        P.parse_line_status,
        "shared_line_status",
        "factory/line/status",
        {
            "online": ["true", 1, None],
            "timestamp": ["2026-09-25T05:21:00.02Z", None],
            "conveyor": ["running", "PAUSED", None],
            "fault_level": [11, -1, 3.5, "3", True, None],
            "motor_rpm": ["0", None, True],
            "sensor_id": ["9motor", "motor-01", None],
            "production_active": [0, "false", None],
        },
    ),
    "product": (
        P.parse_product_created,
        "shared_product_created",
        "factory/product/created",
        {
            "product_id": ["P-113", "p-00000113", 113, None],
            "timestamp": ["2026-09-25T05:20:13.425", None],
            "image_path": ["/data/products/P-00000113.jpg", "gradcam/P-00000113.jpg", None],
        },
    ),
    "vision": (
        P.parse_vision_result,
        "shared_vision_result",
        "factory/vision/result",
        {
            "product_id": ["P-0000011", None],
            "timestamp": ["2026-09-25T05:20:13.425+00:00", None],
            "defect": ["true", 1, None],
            "image_path": ["products/../x.jpg", None],
        },
    ),
    "pdm": (
        P.parse_pdm_result,
        "pdm_result_draft",
        "factory/pdm/result",
        {
            "sensor_id": ["MOTOR01", None],
            "timestamp": ["2026-09-25T05:20:14.4Z", None],
            "anomaly_score": ["0.82", True, None],
            "health_index": [101, -1, 18.5, "18", None],
            "state": ["critical", "ALARM", None],
        },
    ),
}


def test_shared_examples_accepted(ex, payload_examples):
    s = P.parse_sensor_vibration(SENSOR_TOPIC, enc(ex["shared_sensor_vibration"]))
    src = payload_examples["shared_sensor_vibration"]
    assert isinstance(s, P.SensorChunk)
    assert (s.sensor_id, s.seq, s.sample_rate_hz, s.rpm, s.temperature) == (
        src["sensor_id"],
        src["seq"],
        src["sample_rate_hz"],
        src["rpm"],
        src["temperature"],
    )
    assert s.timestamp == parse_ts(src["timestamp"])
    for axis in "xyz":
        arr = getattr(s, axis)
        assert arr.dtype == np.float32 and arr.shape == (1000,)
        np.testing.assert_allclose(arr, np.asarray(src["vibration_" + axis], dtype=np.float32))
        assert not arr.flags.writeable

    src = payload_examples["shared_line_status"]
    ls = P.parse_line_status("factory/line/status", enc(src))
    assert isinstance(ls, P.LineStatus)
    assert (ls.conveyor, ls.fault_level, ls.motor_rpm, ls.sensor_id, ls.production_active) == (
        "STOPPED",
        8,
        0.0,
        "motor01",
        False,
    )
    assert ls.timestamp == parse_ts(src["timestamp"])
    assert ls.products == P.Products(120, 113, 0, 7, "P-00000113")
    lc = src["last_command"]
    assert ls.last_command == P.LastCommand(
        result=lc["result"],
        command_id=lc["command_id"],
        command=lc["command"],
        source=lc["source"],
        reason=lc["reason"],
        error=lc["error"],
        received_at=parse_ts(lc["received_at"]),
    )
    assert ls.nulled == ()

    src = payload_examples["shared_product_created"]
    pc = P.parse_product_created("factory/product/created", enc(src))
    assert pc == P.ProductCreated(src["product_id"], parse_ts(src["timestamp"]), src["image_path"])

    src = payload_examples["shared_vision_result"]
    vr = P.parse_vision_result("factory/vision/result", enc(src))
    assert vr == P.VisionResult(
        src["product_id"],
        parse_ts(src["timestamp"]),
        True,
        src["image_path"],
        defect_type="scratch",
        confidence=None,
        bbox=None,
        gradcam_path=None,
        judgement_source="PASS_THROUGH",
    )

    # Conveyor Control 예시는 발행 형식의 기준이다(test_build_conveyor_shape)
    cc = payload_examples["shared_conveyor_control"]
    assert set(cc) == {"schema_version", "command", "command_id", "timestamp", "reason"}


def test_pdm_draft_example_accepted(payload_examples):
    src = payload_examples["pdm_result_draft"]
    r = P.parse_pdm_result("factory/pdm/result", enc(src))
    assert r == P.PdmResult(
        sensor_id=src["sensor_id"],
        timestamp=parse_ts(src["timestamp"]),
        anomaly_score=src["anomaly_score"],
        health_index=src["health_index"],
        state=src["state"],
        window_start=parse_ts(src["window_start"]),
        model_version=src["model_version"],
    )


def test_missing_field_reasons(ex):
    for kind, (parse, name, topic, fields) in REQUIRED.items():
        for field in fields:
            r = parse(topic, enc(without(ex[name], field)))
            assert r == P.Rejected(f"missing_field:{field}"), (kind, field, r)
    # 스펙트럼 필수 필드
    base = ex["pdm_spectrum_basic"]
    for field in ("sensor_id", "timestamp"):
        assert P.parse_pdm_spectrum("factory/pdm/spectrum", enc(without(base, field))) == P.Rejected(
            f"missing_field:{field}"
        )
    # 첫 실패 하나만 사유가 된다(표 순서)
    both = without(without(ex["shared_product_created"], "timestamp"), "image_path")
    assert P.parse_product_created("t", enc(both)) == P.Rejected("missing_field:timestamp")


def test_invalid_field_reasons(ex):
    for kind, (parse, name, topic, fields) in REQUIRED.items():
        for field, bads in fields.items():
            for bad in bads:
                r = parse(topic, enc(with_(ex[name], **{field: bad})))
                assert r == P.Rejected(f"invalid_field:{field}"), (kind, field, bad, r)
    # 세 축 길이가 다르면 틀린 쪽 이름
    s = with_(ex["shared_sensor_vibration"], vibration_z=[0.1] * 999)
    assert P.parse_sensor_vibration(SENSOR_TOPIC, enc(s)) == P.Rejected("invalid_field:vibration_z")
    # JSON 밖의 큰 수(1e400 → inf)도 유한값이 아니다
    raw = enc(ex["shared_sensor_vibration"]).replace(b'"rpm": 1800.0', b'"rpm": 1e400')
    assert P.parse_sensor_vibration(SENSOR_TOPIC, raw) == P.Rejected("invalid_field:rpm")
    raw = enc(ex["shared_sensor_vibration"]).replace(b'"vibration_y": [', b'"vibration_y": [1e400, ')
    assert P.parse_sensor_vibration(SENSOR_TOPIC, raw) == P.Rejected("invalid_field:vibration_y")
    # 스펙트럼 필수 필드 형식
    base = ex["pdm_spectrum_basic"]
    assert P.parse_pdm_spectrum("t", enc(with_(base, sensor_id="Motor"))) == P.Rejected("invalid_field:sensor_id")
    assert P.parse_pdm_spectrum("t", enc(with_(base, timestamp="x"))) == P.Rejected("invalid_field:timestamp")


def test_int_accepts_integral_float(ex):
    s = with_(ex["shared_sensor_vibration"], seq=1234.0, sample_rate_hz=10000.0)
    r = P.parse_sensor_vibration(SENSOR_TOPIC, enc(s))
    assert (r.seq, r.sample_rate_hz) == (1234, 10000) and type(r.seq) is int
    ls = P.parse_line_status("t", enc(with_(ex["shared_line_status"], fault_level=8.0)))
    assert ls.fault_level == 8 and type(ls.fault_level) is int


def test_topic_mismatch(ex):
    s = ex["shared_sensor_vibration"]
    assert P.parse_sensor_vibration("factory/sensor/motor02/vibration", enc(s)) == P.Rejected("topic_mismatch")
    assert P.parse_sensor_vibration("plant/a/sensor/motor01/vibration", enc(s)).sensor_id == "motor01"
    # 형식이 틀린 sensor_id는 topic 비교 전에 invalid_field
    assert P.parse_sensor_vibration(SENSOR_TOPIC, enc(with_(s, sensor_id="M1"))) == P.Rejected(
        "invalid_field:sensor_id"
    )


def test_unsupported_schema_version(ex):
    cases = [
        ("shared_sensor_vibration", P.parse_sensor_vibration, SENSOR_TOPIC),
        ("shared_line_status", P.parse_line_status, "t"),
        ("shared_product_created", P.parse_product_created, "t"),
        ("shared_vision_result", P.parse_vision_result, "t"),
        ("pdm_result_draft", P.parse_pdm_result, "t"),
        ("pdm_spectrum_basic", P.parse_pdm_spectrum, "t"),
    ]
    for name, parse, topic in cases:
        for bad in (2, 0, "1", 1.0, True, None):
            assert parse(topic, enc(with_(ex[name], schema_version=bad))) == P.Rejected(
                "unsupported_schema_version"
            ), (name, bad)
        assert parse(topic, enc(without(ex[name], "schema_version"))) == P.Rejected("unsupported_schema_version")
    # offline 메시지도 schema_version을 먼저 본다
    assert P.parse_line_status("t", enc({"schema_version": True, "online": False})) == P.Rejected(
        "unsupported_schema_version"
    )


def test_invalid_json():
    for parse in P.PARSERS.values():
        for raw in (b"", b"{", b"[1,2]", b'"text"', b"null", b"\xff\xfe{}", b'{"schema_version": NaN}', b"12"):
            assert parse(SENSOR_TOPIC, raw) == P.Rejected("invalid_json"), (parse.__name__, raw)


def test_optional_fields_become_null(ex):
    v = ex["shared_vision_result"]
    bad = with_(
        v,
        defect_type="Scratch!",
        confidence=1.5,
        bbox=[1, 2, 3],
        gradcam_path="products/a.jpg",
        judgement_source="",
    )
    r = P.parse_vision_result("t", enc(bad))
    assert isinstance(r, P.VisionResult)
    assert (r.defect_type, r.confidence, r.bbox, r.gradcam_path, r.judgement_source) == (None,) * 5
    assert set(r.nulled) == {"defect_type", "confidence", "bbox", "gradcam_path", "judgement_source"}
    good = with_(v, confidence=0.93, bbox=[250, 301.0, 330, 352], gradcam_path="gradcam/P-00000113.png")
    r = P.parse_vision_result("t", enc(good))
    assert (r.confidence, r.bbox, r.gradcam_path) == (0.93, (250, 301, 330, 352), "gradcam/P-00000113.png")
    assert r.nulled == ()

    d = ex["pdm_result_draft"]
    r = P.parse_pdm_result("t", enc(with_(d, window_start="yesterday", model_version="")))
    assert isinstance(r, P.PdmResult)
    assert (r.window_start, r.model_version) == (None, None)
    r = P.parse_pdm_result("t", enc(without(without(d, "window_start"), "model_version")))
    assert isinstance(r, P.PdmResult) and r.window_start is None and r.model_version is None
    # 범위는 검사하지 않는다(A-05 가정)
    assert P.parse_pdm_result("t", enc(with_(d, anomaly_score=3.2))).anomaly_score == 3.2

    ls = ex["shared_line_status"]
    r = P.parse_line_status("t", enc(with_(ls, products={"spawned": 1})))
    assert isinstance(r, P.LineStatus) and r.products is None and r.nulled == ("products",)
    r = P.parse_line_status("t", enc(with_(ls, products=None, last_command=None)))
    assert r.products is None and r.last_command is None and r.nulled == ()
    r = P.parse_line_status("t", enc(without(without(ls, "products"), "last_command")))
    assert isinstance(r, P.LineStatus)
    # 표에 없는 필드는 무시한다
    assert isinstance(P.parse_line_status("t", enc(with_(ls, extra_field=[1, 2]))), P.LineStatus)


def test_line_offline_only():
    r = P.parse_line_status("factory/line/status", b'{"schema_version":1,"online":false}')
    assert r == P.LineOffline()
    # 다른 필드가 틀려도 offline이면 보지 않는다
    r = P.parse_line_status("t", enc({"schema_version": 1, "online": False, "conveyor": "??"}))
    assert r == P.LineOffline()
    assert P.parse_line_status("t", enc({"schema_version": 1})) == P.Rejected("missing_field:online")
    assert P.parse_line_status("t", enc({"schema_version": 1, "online": None})) == P.Rejected("invalid_field:online")


def test_bad_last_command_nulls_only_it(ex):
    ls = ex["shared_line_status"]
    for bad_result in ("DONE", None, 1):
        lc = with_(ls["last_command"], result=bad_result)
        r = P.parse_line_status("t", enc(with_(ls, last_command=lc)))
        assert isinstance(r, P.LineStatus)
        assert r.last_command is None
        assert r.nulled == ("last_command",)
        assert r.products == P.Products(120, 113, 0, 7, "P-00000113")
        assert (r.conveyor, r.fault_level) == ("STOPPED", 8)
    for bad in ("STOP", [1], 5):
        r = P.parse_line_status("t", enc(with_(ls, last_command=bad)))
        assert r.last_command is None and r.conveyor == "STOPPED"
    # result가 맞으면 틀린 하위 값만 null
    lc = with_(ls["last_command"], command="HALT", command_id="x" * 65, received_at="now", error=5)
    r = P.parse_line_status("t", enc(with_(ls, last_command=lc)))
    assert r.last_command == P.LastCommand(
        result="APPLIED",
        command_id=None,
        command=None,
        source="mqtt",
        reason="INTERLOCK_CRITICAL",
        error=None,
        received_at=None,
    )
    # 거부된 명령: 알 수 없는 필드가 null
    rejected = {
        "command": None,
        "command_id": None,
        "source": "mqtt",
        "received_at": "2026-09-25T05:21:00.015Z",
        "result": "REJECTED",
        "reason": None,
        "error": "retained_ignored",
    }
    r = P.parse_line_status("t", enc(with_(ls, last_command=rejected)))
    assert r.last_command.result == "REJECTED" and r.last_command.error == "retained_ignored"


def test_vision_missing_optional_keys(ex):
    v = ex["shared_vision_result"]
    for key in ("confidence", "bbox", "gradcam_path", "defect_type", "judgement_source"):
        v = without(v, key)
    r = P.parse_vision_result("factory/vision/result", enc(v))
    assert isinstance(r, P.VisionResult)
    assert (r.confidence, r.bbox, r.gradcam_path, r.defect_type, r.judgement_source) == (None,) * 5
    assert r.nulled == ()
    # defect false인데 defect_type이 있으면 그대로
    r = P.parse_vision_result("t", enc(with_(ex["shared_vision_result"], defect=False)))
    assert r.defect is False and r.defect_type == "scratch"


def _series(panel):
    return [(s.name, len(s.values), s.values.dtype) for s in panel.series]


def test_spectrum_single_panel(ex):
    r = P.parse_pdm_spectrum("factory/pdm/spectrum", enc(ex["pdm_spectrum_basic"]))
    assert isinstance(r, P.SpectrumPanels)
    assert r.sensor_id == "motor01"
    assert r.timestamp == parse_ts("2026-09-25T05:20:14.400Z")
    assert r.window_start == parse_ts("2026-09-25T05:20:13.400Z")
    (panel,) = r.panels
    assert (panel.title, panel.x_start, panel.x_step, panel.x_unit) == ("스펙트럼", 0.0, 1.0, "Hz")
    assert _series(panel) == [(f"spectrum_{a}", 501, np.float32) for a in "xyz"]
    np.testing.assert_allclose(panel.series[0].values, np.asarray(ex["pdm_spectrum_basic"]["spectrum_x"], np.float32))
    # 시작 주파수
    r = P.parse_pdm_spectrum("t", enc(with_(ex["pdm_spectrum_basic"], freq_start_hz=5.0, freq_step_hz=0.5)))
    assert (r.panels[0].x_start, r.panels[0].x_step) == (5.0, 0.5)


def test_spectrum_envelope_panel(ex):
    r = P.parse_pdm_spectrum("t", enc(ex["pdm_spectrum_envelope"]))
    assert [p.title for p in r.panels] == ["스펙트럼", "포락선 스펙트럼"]
    spec, env = r.panels
    assert _series(spec) == [(f"spectrum_{a}", 501, np.float32) for a in "xyz"]
    assert _series(env) == [("envelope_y", 501, np.float32)]
    assert (env.x_start, env.x_step, env.x_unit) == (0.0, 1.0, "Hz")
    # 포락선 간격 필드가 있으면 그것
    r = P.parse_pdm_spectrum("t", enc(with_(ex["pdm_spectrum_envelope"], envelope_freq_step_hz=0.25)))
    assert (r.panels[0].x_step, r.panels[1].x_step) == (1.0, 0.25)
    # 포락선만 있어도 받는다
    only_env = {k: v for k, v in ex["pdm_spectrum_envelope"].items() if not k.startswith("spectrum_")}
    r = P.parse_pdm_spectrum("t", enc(only_env))
    assert [p.title for p in r.panels] == ["포락선 스펙트럼"]


def test_spectrum_bins_without_step(ex):
    r = P.parse_pdm_spectrum("t", enc(ex["pdm_spectrum_nostep"]))
    (panel,) = r.panels
    assert (panel.x_start, panel.x_step, panel.x_unit) == (0.0, 1.0, "bin")
    assert len(panel.series) == 3
    # 간격이 양수가 아니면 모르는 것으로 본다
    r = P.parse_pdm_spectrum("t", enc(with_(ex["pdm_spectrum_basic"], freq_step_hz=0)))
    assert r.panels[0].x_unit == "bin"


def test_spectrum_no_series(ex):
    base = {k: v for k, v in ex["pdm_spectrum_basic"].items() if not k.startswith("spectrum_")}
    assert P.parse_pdm_spectrum("t", enc(base)) == P.Rejected("no_series")
    # 길이 2~4096 밖, 숫자가 아닌 원소가 섞인 배열은 계열이 아니다
    odd = with_(base, spectrum_x=[0.1], spectrum_y=[0.1] * 4097, spectrum_z=[0.1, "a"], other=[True, False])
    assert P.parse_pdm_spectrum("t", enc(odd)) == P.Rejected("no_series")


def test_spectrum_too_large(ex):
    big = with_(ex["pdm_spectrum_basic"], padding="x" * (300 * 1024))
    raw = enc(big)
    assert len(raw) > 256 * 1024
    assert P.parse_pdm_spectrum("t", raw) == P.Rejected("too_large")
    # 크기 검사가 JSON보다 먼저다
    assert P.parse_pdm_spectrum("t", b"{" * (300 * 1024)) == P.Rejected("too_large")


def test_build_conveyor_shape(payload_examples):
    now = datetime(2026, 9, 25, 5, 21, 0, 12999, tzinfo=UTC)
    cid = P.new_command_id()
    msg = P.build_conveyor("STOP", cid, "INTERLOCK_CRITICAL", now)
    shared = payload_examples["shared_conveyor_control"]
    assert list(msg) == list(shared)
    assert msg == {**shared, "command_id": cid}
    assert re.match(TS_PATTERN, msg["timestamp"])
    assert len(cid) == 36 and uuid.UUID(cid).version == 4 and cid == cid.lower()
    assert P.new_command_id() != cid
    for reason in ("OPERATOR_START", "OPERATOR_STOP"):
        m = P.build_conveyor("START", P.new_command_id(), reason, now)
        assert m["command"] == "START" and m["reason"] == reason
    with pytest.raises(ValueError):
        P.build_conveyor("PAUSE", cid, "x", now)
    raw = P.serialize(msg)
    assert b" " not in raw and json.loads(raw) == msg


A02_EXAMPLE = {
    "schema_version": 1,
    "alarm_id": "3b0f6a52-8f0e-4c55-9d7e-2f1c9a4b7e10",
    "timestamp": "2026-09-25T05:20:14.400Z",
    "raised_at": "2026-09-25T05:20:14.412Z",
    "sensor_id": "motor01",
    "severity": "CRITICAL",
    "previous_state": "WARNING",
    "health_index": 18,
    "anomaly_score": 0.82,
}


def test_build_alarm_shape():
    alarm = P.Alarm(
        alarm_id="3b0f6a52-8f0e-4c55-9d7e-2f1c9a4b7e10",
        timestamp=parse_ts("2026-09-25T05:20:14.400Z"),
        raised_at=datetime(2026, 9, 25, 5, 20, 14, 412700, tzinfo=UTC),
        sensor_id="motor01",
        severity="CRITICAL",
        previous_state="WARNING",
        health_index=18,
        anomaly_score=0.82,
    )
    msg = P.build_alarm(alarm)
    assert list(msg) == list(A02_EXAMPLE)
    assert msg == A02_EXAMPLE
    assert re.match(TS_PATTERN, msg["timestamp"]) and re.match(TS_PATTERN, msg["raised_at"])
    first = P.build_alarm(
        P.Alarm(str(uuid.uuid4()), alarm.timestamp, alarm.raised_at, "motor01", "WARNING", None, 55, 0.4)
    )
    assert first["previous_state"] is None and uuid.UUID(first["alarm_id"]).version == 4
    with pytest.raises(ValueError):
        P.build_alarm(P.Alarm("a", alarm.timestamp, alarm.raised_at, "motor01", "CAUTION", None, 70, 0.3))


def test_rel_path_rejects():
    for bad in (
        "products/../x.jpg",
        "/data/products/a.jpg",
        "products/.P-1.jpg.tmp",
        "products/a.gif",
        "products//a.jpg",
        "products/",
        "products",
        "products/a",
        "products/sub/.hidden/a.jpg",
        "products\\a.jpg",
        "products/" + "a" * 200 + ".jpg",
        None,
        5,
    ):
        assert P.rel_path(bad, "products") is None, bad
    # gradcam 경로는 products 자리에 올 수 없다
    assert P.rel_path("gradcam/a.jpg", "products") is None
    for good in ("products/P-00000001.jpg", "products/a.jpeg", "products/sub/a.png"):
        assert P.rel_path(good, "products") == good
    assert P.rel_path("gradcam/P-00000001.png", "gradcam") == "gradcam/P-00000001.png"
    pc = {"schema_version": 1, "product_id": "P-00000001", "timestamp": "2026-09-25T05:20:13.425Z"}
    for bad in ("products/../x.jpg", "/data/products/a.jpg", "products/.P-1.jpg.tmp", "gradcam/a.jpg", "products/a.gif"):
        assert P.parse_product_created("t", enc({**pc, "image_path": bad})) == P.Rejected("invalid_field:image_path")


def test_parse_dispatch(ex):
    assert set(P.PARSERS) == set(T.INPUT_KINDS)
    assert isinstance(P.parse(T.PRODUCT_CREATED, "t", enc(ex["shared_product_created"])), P.ProductCreated)


def test_pdm_helpers_match_fixtures(payload_examples):
    ts = datetime(2026, 9, 25, 6, 0, 1, 500000, tzinfo=UTC)
    msg = pdm.pdm_result("motor01", ts, "WARNING", 45, 0.55)
    assert set(msg) == set(payload_examples["pdm_result_draft"])
    r = P.parse_pdm_result("factory/pdm/result", pdm.to_bytes(msg))
    assert isinstance(r, P.PdmResult)
    assert (r.sensor_id, r.timestamp, r.state, r.health_index, r.anomaly_score) == ("motor01", ts, "WARNING", 45, 0.55)
    assert r.window_start == parse_ts("2026-09-25T06:00:00.500Z")
    # 문자열 timestamp, 값 바꾸기, 키 빼기
    msg = pdm.pdm_result("motor02", "2026-09-25T06:00:02.000Z", "NORMAL", 97, 0.03, model_version="m2")
    r = P.parse_pdm_result("t", pdm.to_bytes(msg))
    assert r.model_version == "m2" and r.sensor_id == "motor02"
    msg = pdm.pdm_result("motor01", ts, "NORMAL", 97, 0.03, window_start=pdm.DROP)
    assert "window_start" not in msg

    spec = pdm.pdm_spectrum("motor01", ts)
    assert set(spec) == set(payload_examples["pdm_spectrum_envelope"])
    r = P.parse_pdm_spectrum("factory/pdm/spectrum", pdm.to_bytes(spec))
    assert isinstance(r, P.SpectrumPanels) and r.timestamp == ts
    assert [p.title for p in r.panels] == ["스펙트럼", "포락선 스펙트럼"]
