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
        "shared_pdm_result",
        "factory/pdm/result",
        {
            "sensor_id": ["MOTOR01", None],
            "timestamp": ["2026-09-25T05:20:14.4Z", None],
            "window_start": ["2026-09-25T05:20:13Z", None],
            "anomaly_score": ["0.82", True, None, -0.01, 1.0001],
            "health_index": [101, -1, 18.5, "18", None],
            "state": ["critical", "ALARM", None],
        },
    ),
    "spectrum": (
        P.parse_pdm_spectrum,
        "shared_pdm_spectrum",
        "factory/pdm/spectrum",
        {
            "sensor_id": ["Motor01", None],
            "timestamp": ["x", None],
            "window_start": ["2026-09-25T05:20:13.4Z", None],
            "rpm": ["1800", True, None],
            "freq_step_hz": [0, -1.0, "1.0", None],
            "rot_hz": ["30", None],
            "bpfo_hz": [None, [107.5]],
            "bpfi_hz": [None, False],
            "spectrum_x": [[0.1] * 500, [0.1] * 502, None, "0.1"],
            "spectrum_y": [[-0.1] + [0.1] * 500, [0.1] * 500 + ["a"]],
            "spectrum_z": [[0.1] * 500 + [True], {}],
            "envelope_x": [[0.1] * 250, None],
            "envelope_y": [[0.0] * 500 + [None]],
            "envelope_z": [[-0.0001] * 501],
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
        ("shared_pdm_result", P.parse_pdm_result, "t"),
        ("shared_pdm_spectrum", P.parse_pdm_spectrum, "t"),
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

    d = ex["shared_pdm_result"]
    r = P.parse_pdm_result("t", enc(with_(d, model_version="")))
    assert isinstance(r, P.PdmResult) and r.model_version is None and r.nulled == ("model_version",)
    r = P.parse_pdm_result("t", enc(without(d, "model_version")))
    assert isinstance(r, P.PdmResult) and r.model_version is None and r.nulled == ()

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
    # 확정본(cb6dc3c)에서는 원 스펙트럼 패널 하나에 spectrum_x/y/z 세 계열, 간격 freq_step_hz
    src = ex["shared_pdm_spectrum"]
    r = P.parse_pdm_spectrum("factory/pdm/spectrum", enc(src))
    assert isinstance(r, P.SpectrumPanels)
    panel = r.panels[0]
    assert (panel.title, panel.x_start, panel.x_step, panel.x_unit) == ("스펙트럼", 0.0, 1.0, "Hz")
    assert _series(panel) == [(f"spectrum_{a}", 501, np.float32) for a in "xyz"]
    np.testing.assert_allclose(panel.series[0].values, np.asarray(src["spectrum_x"], np.float32))
    # 간격 0.5 Hz면 길이 1001
    half = with_(src, freq_step_hz=0.5, **{k: [0.0] * 1001 for k in P.SPECTRUM_ARRAYS})
    r = P.parse_pdm_spectrum("t", enc(half))
    assert (r.panels[0].x_step, len(r.panels[0].series[0].values)) == (0.5, 1001)


def test_spectrum_envelope_panel(ex):
    r = P.parse_pdm_spectrum("t", enc(ex["shared_pdm_spectrum"]))
    assert [p.title for p in r.panels] == ["스펙트럼", "포락선 스펙트럼"]
    spec, env = r.panels
    assert _series(spec) == [(f"spectrum_{a}", 501, np.float32) for a in "xyz"]
    assert _series(env) == [(f"envelope_{a}", 501, np.float32) for a in "xyz"]
    assert (env.x_start, env.x_step, env.x_unit) == (0.0, 1.0, "Hz")


def test_spectrum_bins_without_step(ex):
    # 확정본에서 freq_step_hz는 필수다(D-46: 느슨한 해석의 bin 축 대신 거부)
    r = P.parse_pdm_spectrum("t", enc(without(ex["shared_pdm_spectrum"], "freq_step_hz")))
    assert r == P.Rejected("missing_field:freq_step_hz")


def test_spectrum_no_series(ex):
    # 배열이 하나도 없으면 첫 배열 필드가 사유가 된다(D-46: no_series 대신 거부)
    base = {k: v for k, v in ex["shared_pdm_spectrum"].items() if k not in P.SPECTRUM_ARRAYS}
    assert P.parse_pdm_spectrum("t", enc(base)) == P.Rejected("missing_field:spectrum_x")


def test_spectrum_too_large(ex):
    big = with_(ex["shared_pdm_spectrum"], padding="x" * (300 * 1024))
    raw = enc(big)
    assert len(raw) > 256 * 1024
    assert P.parse_pdm_spectrum("t", raw) == P.Rejected("too_large")
    # 크기 검사가 JSON보다 먼저다
    assert P.parse_pdm_spectrum("t", b"{" * (300 * 1024)) == P.Rejected("too_large")


def test_shared_pdm_result_example(payload_examples):
    src = payload_examples["shared_pdm_result"]
    r = P.parse_pdm_result("factory/pdm/result", enc(src))
    assert r == P.PdmResult(
        sensor_id="motor01",
        timestamp=parse_ts("2026-09-25T05:20:14.400Z"),
        anomaly_score=0.7518,
        health_index=24,
        state="CRITICAL",
        window_start=parse_ts("2026-09-25T05:20:13.400Z"),
        model_version="v1",
    )


def test_shared_pdm_result_reject_example():
    # Shared cb6dc3c INTERFACES PdM Result "거부해야 할 예"
    raw = b'{"schema_version":1,"sensor_id":"motor01","timestamp":"2026-09-25T05:20:14Z","anomaly_score":0.1,"health_index":85,"state":"normal"}'
    assert isinstance(P.parse_pdm_result("factory/pdm/result", raw), P.Rejected)
    obj = json.loads(raw)
    # 이유 하나씩: 밀리초 없는 timestamp, window_start 없음, 소문자 state
    good = {**obj, "timestamp": "2026-09-25T05:20:14.000Z", "window_start": "2026-09-25T05:20:13.000Z", "state": "NORMAL"}
    assert isinstance(P.parse_pdm_result("t", enc(good)), P.PdmResult)
    assert P.parse_pdm_result("t", enc({**good, "timestamp": "2026-09-25T05:20:14Z"})) == P.Rejected(
        "invalid_field:timestamp"
    )
    assert P.parse_pdm_result("t", enc(without(good, "window_start"))) == P.Rejected("missing_field:window_start")
    assert P.parse_pdm_result("t", enc({**good, "state": "normal"})) == P.Rejected("invalid_field:state")


def test_shared_pdm_spectrum_example(payload_examples):
    src = payload_examples["shared_pdm_spectrum"]
    r = P.parse_pdm_spectrum("factory/pdm/spectrum", enc(src))
    assert isinstance(r, P.SpectrumPanels)
    assert (r.sensor_id, r.timestamp, r.window_start) == (
        "motor01",
        parse_ts("2026-09-25T05:20:14.400Z"),
        parse_ts("2026-09-25T05:20:13.400Z"),
    )
    assert (r.rpm, r.rot_hz, r.bpfo_hz, r.bpfi_hz) == (1800.0, 30.0, 107.54, 162.46)
    for panel in r.panels:
        for series in panel.series:
            np.testing.assert_allclose(series.values, np.asarray(src[series.name], np.float32))
            assert not series.values.flags.writeable
    # Shared "거부해야 할 예": envelope_z 없음, spectrum_x 길이 500, freq_step_hz 0
    assert P.parse_pdm_spectrum("t", enc(without(src, "envelope_z"))) == P.Rejected("missing_field:envelope_z")
    assert P.parse_pdm_spectrum("t", enc(with_(src, spectrum_x=src["spectrum_x"][:500]))) == P.Rejected(
        "invalid_field:spectrum_x"
    )
    assert P.parse_pdm_spectrum("t", enc(with_(src, freq_step_hz=0))) == P.Rejected("invalid_field:freq_step_hz")


def test_pdm_result_window_start_required(ex):
    d = ex["shared_pdm_result"]
    assert P.parse_pdm_result("t", enc(without(d, "window_start"))) == P.Rejected("missing_field:window_start")
    assert P.parse_pdm_result("t", enc(with_(d, window_start=None))) == P.Rejected("invalid_field:window_start")
    assert P.parse_pdm_result("t", enc(with_(d, window_start="yesterday"))) == P.Rejected(
        "invalid_field:window_start"
    )


def test_pdm_result_anomaly_score_range(ex):
    d = ex["shared_pdm_result"]
    for ok in (0, 0.0, 0.5, 1, 1.0):
        assert P.parse_pdm_result("t", enc(with_(d, anomaly_score=ok))).anomaly_score == ok
    for bad in (-0.0001, 1.0001, 3.2, -1):
        assert P.parse_pdm_result("t", enc(with_(d, anomaly_score=bad))) == P.Rejected("invalid_field:anomaly_score")


SPECTRUM_FIELDS = (
    "sensor_id",
    "timestamp",
    "window_start",
    "rpm",
    "freq_step_hz",
    "rot_hz",
    "bpfo_hz",
    "bpfi_hz",
    "spectrum_x",
    "spectrum_y",
    "spectrum_z",
    "envelope_x",
    "envelope_y",
    "envelope_z",
)


def test_spectrum_requires_all_fields(ex):
    src = ex["shared_pdm_spectrum"]
    assert set(SPECTRUM_FIELDS) | {"schema_version"} == set(src)
    for field in SPECTRUM_FIELDS:
        assert P.parse_pdm_spectrum("t", enc(without(src, field))) == P.Rejected(f"missing_field:{field}"), field
    # 모르는 필드는 무시한다
    assert isinstance(P.parse_pdm_spectrum("t", enc(with_(src, extra=[1.0, 2.0]))), P.SpectrumPanels)


def test_spectrum_length_rule(ex):
    src = ex["shared_pdm_spectrum"]
    # 여섯 개 길이가 같고 floor(500 / freq_step_hz) + 1
    for step, n in ((1.0, 501), (2.0, 251), (0.5, 1001), (3.0, 167), (0.3, 1667)):
        msg = with_(src, freq_step_hz=step, **{k: [0.0] * n for k in P.SPECTRUM_ARRAYS})
        r = P.parse_pdm_spectrum("t", enc(msg))
        assert isinstance(r, P.SpectrumPanels), (step, r)
        assert all(len(s.values) == n for p in r.panels for s in p.series)
    # 간격과 길이가 맞지 않음
    msg = with_(src, freq_step_hz=2.0)
    assert P.parse_pdm_spectrum("t", enc(msg)) == P.Rejected("invalid_field:spectrum_x")
    # 하나만 길이가 다름
    for name in P.SPECTRUM_ARRAYS:
        msg = with_(src, **{name: src[name] + [0.0]})
        assert P.parse_pdm_spectrum("t", enc(msg)) == P.Rejected(f"invalid_field:{name}"), name


def test_spectrum_values_finite_nonnegative(ex):
    src = ex["shared_pdm_spectrum"]
    for name in P.SPECTRUM_ARRAYS:
        neg = list(src[name])
        neg[100] = -0.0001
        assert P.parse_pdm_spectrum("t", enc(with_(src, **{name: neg}))) == P.Rejected(f"invalid_field:{name}")
        # 길이는 맞고 원소 하나가 inf(JSON 1e400)
        marked = list(src[name])
        marked[7] = 123456.789
        raw = enc(with_(src, **{name: marked})).replace(b"123456.789", b"1e400")
        assert len(json.loads(raw)[name]) == 501
        assert P.parse_pdm_spectrum("t", raw) == P.Rejected(f"invalid_field:{name}")
    for bad in (0, -1.0, "1.0", True):
        assert P.parse_pdm_spectrum("t", enc(with_(src, freq_step_hz=bad))) == P.Rejected("invalid_field:freq_step_hz")
    # 0은 허용
    zeros = with_(src, **{k: [0.0] * 501 for k in P.SPECTRUM_ARRAYS})
    assert isinstance(P.parse_pdm_spectrum("t", enc(zeros)), P.SpectrumPanels)


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


def test_build_alarm_matches_shared_example(payload_examples):
    shared = payload_examples["shared_alarm_event"]
    alarm = P.Alarm(
        alarm_id=shared["alarm_id"],
        timestamp=parse_ts(shared["timestamp"]),
        raised_at=parse_ts(shared["raised_at"]),
        sensor_id=shared["sensor_id"],
        severity=shared["severity"],
        previous_state=shared["previous_state"],
        health_index=shared["health_index"],
        anomaly_score=shared["anomaly_score"],
    )
    msg = P.build_alarm(alarm)
    assert set(msg) == set(shared)
    assert list(msg) == list(shared)
    assert msg == shared


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
    assert set(msg) == set(payload_examples["shared_pdm_result"])
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
    assert set(spec) == set(payload_examples["shared_pdm_spectrum"])
    r = P.parse_pdm_spectrum("factory/pdm/spectrum", pdm.to_bytes(spec))
    assert isinstance(r, P.SpectrumPanels) and r.timestamp == ts
    assert [p.title for p in r.panels] == ["스펙트럼", "포락선 스펙트럼"]
