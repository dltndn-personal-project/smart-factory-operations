"""입력 Payload 검증과 발행 Payload 생성 (docs/spec/02-mqtt.md 3·4절). 순수 함수만 있다.

`parse_<kind>(topic, raw: bytes) -> 결과 객체 | Rejected(reason)`. 공통 규칙은 3.1절:
`invalid_json` → `unsupported_schema_version` → 표 순서대로 `missing_field:<이름>` /
`invalid_field:<이름>`(첫 실패 하나). 선택 필드는 없거나 틀리면 None이 되고 그 이름이 `nulled`에 남는다.

PdM Result·PdM Spectrum 형식(Shared `cb6dc3c` 확정본)에 기대는 제품 코드는 `parse_pdm_result`, `parse_pdm_spectrum` 두 함수뿐이다
(DECISIONS D-39). 다른 모듈은 PdM Payload의 JSON 키를 직접 읽지 않는다.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import numpy as np

from ..clock import iso_ms, parse_ts
from . import topics as _topics

# ---------------------------------------------------------------------------
# 결과 객체


@dataclass(frozen=True)
class Rejected:
    reason: str


@dataclass(frozen=True, eq=False)
class SensorChunk:
    sensor_id: str
    timestamp: datetime
    seq: int
    sample_rate_hz: int
    rpm: float
    temperature: float
    x: np.ndarray  # float32, 만든 뒤 바꾸지 않는다
    y: np.ndarray
    z: np.ndarray


@dataclass(frozen=True)
class LineOffline:
    pass


@dataclass(frozen=True)
class Products:
    spawned: int
    created: int
    expired: int
    in_flight: int
    last_product_id: str | None


@dataclass(frozen=True)
class LastCommand:
    result: str  # APPLIED | NO_CHANGE | REJECTED
    command_id: str | None
    command: str | None
    source: str | None
    reason: str | None
    error: str | None
    received_at: datetime | None


@dataclass(frozen=True)
class LineStatus:
    timestamp: datetime
    conveyor: str  # RUNNING | STOPPED
    fault_level: int
    motor_rpm: float
    sensor_id: str
    production_active: bool
    products: Products | None
    last_command: LastCommand | None
    nulled: tuple[str, ...] = ()  # 형식이 틀려 None이 된 선택 필드(DEBUG 로그용)


@dataclass(frozen=True)
class ProductCreated:
    product_id: str
    timestamp: datetime
    image_path: str


@dataclass(frozen=True)
class VisionResult:
    product_id: str
    timestamp: datetime
    defect: bool
    image_path: str
    defect_type: str | None
    confidence: float | None
    bbox: tuple[int, int, int, int] | None
    gradcam_path: str | None
    judgement_source: str | None
    nulled: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdmResult:
    sensor_id: str
    timestamp: datetime  # 분석 윈도우의 끝(Simulator 시계)
    anomaly_score: float
    health_index: int
    state: str  # NORMAL | CAUTION | WARNING | CRITICAL
    window_start: datetime | None
    model_version: str | None
    nulled: tuple[str, ...] = ()


@dataclass(frozen=True, eq=False)
class SpectrumSeries:
    name: str
    values: np.ndarray  # float32


@dataclass(frozen=True)
class SpectrumPanel:
    title: str
    x_start: float
    x_step: float
    x_unit: str  # "Hz" | "bin"
    series: tuple[SpectrumSeries, ...]


@dataclass(frozen=True)
class SpectrumPanels:
    sensor_id: str
    timestamp: datetime  # PdM Result와 같은 윈도우 끝
    window_start: datetime
    panels: tuple[SpectrumPanel, ...]  # (원 스펙트럼, 포락선 스펙트럼)
    rpm: float
    rot_hz: float  # 화면 표시선용으로 담기만 한다
    bpfo_hz: float
    bpfi_hz: float


# ---------------------------------------------------------------------------
# 공통 규칙 (3.1절)

SENSOR_ID_RE = re.compile(r"[a-z][a-z0-9_]{0,31}", re.ASCII)
PRODUCT_ID_RE = re.compile(r"P-[0-9]{8}", re.ASCII)
DEFECT_TYPE_RE = re.compile(r"[a-z][a-z_]{0,31}", re.ASCII)
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
REL_PATH_MAX = 200

LINE_STATES = ("RUNNING", "STOPPED")
COMMAND_RESULTS = ("APPLIED", "NO_CHANGE", "REJECTED")
COMMANDS = ("START", "STOP")
PDM_STATES = ("NORMAL", "CAUTION", "WARNING", "CRITICAL")

SPECTRUM_MAX_BYTES = 256 * 1024
SPECTRUM_ARRAYS = ("spectrum_x", "spectrum_y", "spectrum_z", "envelope_x", "envelope_y", "envelope_z")
SPECTRUM_MAX_HZ = 500
SPECTRUM_TITLE = "스펙트럼"
ENVELOPE_TITLE = "포락선 스펙트럼"
VIBRATION_MAX = 10000


class _Reject(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _reject_constant(name: str) -> Any:
    # json 모듈은 NaN·Infinity를 받지만 JSON이 아니다
    raise ValueError(f"non-JSON constant {name}")


def _load_object(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray, memoryview)) else raw
        obj = json.loads(text, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        raise _Reject("invalid_json") from None
    if not isinstance(obj, dict):
        raise _Reject("invalid_json")
    sv = obj.get("schema_version")
    if type(sv) is not int or sv != 1:
        raise _Reject("unsupported_schema_version")
    return obj


def is_number(v: Any) -> bool:
    """int 또는 float(bool 제외), 유한값."""
    t = type(v)
    if t is int:
        return True
    return t is float and math.isfinite(v)


def as_int(v: Any) -> int | None:
    """int(bool 제외) 또는 `is_integer()`인 float이면 int, 아니면 None."""
    t = type(v)
    if t is int:
        return v
    if t is float and math.isfinite(v) and v.is_integer():
        return int(v)
    return None


def is_ts(v: Any) -> bool:
    try:
        parse_ts(v)
        return True
    except ValueError:
        return False


def rel_path(v: Any, directory: str) -> str | None:
    """이미지 경로 형식 `rel_path(dir)` (3.1절 6번). 맞으면 그 문자열, 아니면 None."""
    if not isinstance(v, str) or not v or len(v) > REL_PATH_MAX:
        return None
    if not v.startswith(directory + "/") or v.startswith("/") or "\\" in v or "\x00" in v:
        return None
    for part in v.split("/"):
        if not part or part.startswith(".") or part == "..":
            return None
    if not v.endswith(IMAGE_EXTENSIONS):
        return None
    return v


class _Fields:
    """필드 검사 도우미. 필수 필드 실패는 `_Reject`, 선택 필드 실패는 None과 `nulled` 기록."""

    def __init__(self, obj: dict[str, Any]):
        self.obj = obj
        self.nulled: list[str] = []

    def req(self, name: str, check: Callable[[Any], Any]) -> Any:
        if name not in self.obj:
            raise _Reject(f"missing_field:{name}")
        out = check(self.obj[name])
        if out is _BAD:
            raise _Reject(f"invalid_field:{name}")
        return out

    def opt(self, name: str, check: Callable[[Any], Any]) -> Any:
        if name not in self.obj or self.obj[name] is None:
            return None
        out = check(self.obj[name])
        if out is _BAD:
            self.nulled.append(name)
            return None
        return out


_BAD = object()


def _c_ts(v: Any) -> Any:
    try:
        return parse_ts(v)
    except ValueError:
        return _BAD


def _c_sensor_id(v: Any) -> Any:
    return v if isinstance(v, str) and SENSOR_ID_RE.fullmatch(v) else _BAD


def _c_product_id(v: Any) -> Any:
    return v if isinstance(v, str) and PRODUCT_ID_RE.fullmatch(v) else _BAD


def _c_bool(v: Any) -> Any:
    return v if type(v) is bool else _BAD


def _c_number(lo: float | None = None, hi: float | None = None) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        if not is_number(v):
            return _BAD
        if (lo is not None and v < lo) or (hi is not None and v > hi):
            return _BAD
        return float(v)

    return check


def _c_int(lo: int | None = None, hi: int | None = None, gt: int | None = None) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        i = as_int(v)
        if i is None:
            return _BAD
        if (lo is not None and i < lo) or (hi is not None and i > hi) or (gt is not None and i <= gt):
            return _BAD
        return i

    return check


def _c_enum(values: tuple[str, ...]) -> Callable[[Any], Any]:
    return lambda v: v if isinstance(v, str) and v in values else _BAD


def _c_str(lo: int, hi: int) -> Callable[[Any], Any]:
    return lambda v: v if isinstance(v, str) and lo <= len(v) <= hi else _BAD


def _c_any_str(v: Any) -> Any:
    return v if isinstance(v, str) else _BAD


def _c_rel_path(directory: str) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        p = rel_path(v, directory)
        return _BAD if p is None else p

    return check


def _number_array(v: Any, lo: int, hi: int) -> np.ndarray | None:
    """`number` 배열이면 float32 배열, 아니면 None. 원소 검사는 C 수준 연산으로 한다."""
    if not isinstance(v, list) or not lo <= len(v) <= hi:
        return None
    if not set(map(type, v)) <= {int, float}:  # bool·문자열·null·중첩 배열 제외
        return None
    try:
        arr = np.asarray(v, dtype=np.float64)
    except (ValueError, OverflowError):
        return None
    if not np.isfinite(arr).all():
        return None
    out = arr.astype(np.float32)
    if not np.isfinite(out).all():  # float32 범위를 넘는 값
        return None
    out.setflags(write=False)
    return out


def _c_vibration(v: Any) -> Any:
    arr = _number_array(v, 1, VIBRATION_MAX)
    return _BAD if arr is None else arr


def _parse(fn: Callable[[dict[str, Any]], Any], raw: bytes) -> Any:
    try:
        return fn(_load_object(raw))
    except _Reject as r:
        return Rejected(r.reason)


# ---------------------------------------------------------------------------
# 파서 6종


def parse_sensor_vibration(topic: str, raw: bytes) -> SensorChunk | Rejected:
    """3.2절. `sensor_id`는 Topic의 `+` 자리 값과 같아야 한다."""
    parts = topic.split("/")
    topic_sensor = parts[-2] if len(parts) >= 3 and parts[-1] == "vibration" else None

    def build(obj: dict[str, Any]) -> SensorChunk:
        f = _Fields(obj)
        sensor_id = f.req("sensor_id", _c_sensor_id)
        if sensor_id != topic_sensor:
            raise _Reject("topic_mismatch")
        timestamp = f.req("timestamp", _c_ts)
        seq = f.req("seq", _c_int(lo=0))
        sample_rate_hz = f.req("sample_rate_hz", _c_int(gt=0))
        rpm = f.req("rpm", _c_number(lo=0))
        temperature = f.req("temperature", _c_number())
        axes = []
        for name in ("vibration_x", "vibration_y", "vibration_z"):
            arr = f.req(name, _c_vibration)
            if axes and len(arr) != len(axes[0]):
                raise _Reject(f"invalid_field:{name}")
            axes.append(arr)
        return SensorChunk(sensor_id, timestamp, seq, sample_rate_hz, rpm, temperature, *axes)

    return _parse(build, raw)


def _c_products(v: Any) -> Any:
    if not isinstance(v, dict):
        return _BAD
    counts = [as_int(v.get(k)) for k in ("spawned", "created", "expired", "in_flight")]
    if any(c is None for c in counts):
        return _BAD
    last = v.get("last_product_id")
    if last is not None and _c_product_id(last) is _BAD:
        return _BAD
    return Products(*counts, last)  # type: ignore[arg-type]


def _c_last_command(v: Any) -> Any:
    if not isinstance(v, dict) or _c_enum(COMMAND_RESULTS)(v.get("result")) is _BAD:
        return _BAD
    f = _Fields(v)
    return LastCommand(
        result=v["result"],
        command_id=f.opt("command_id", _c_str(1, 64)),
        command=f.opt("command", _c_enum(COMMANDS)),
        source=f.opt("source", _c_any_str),
        reason=f.opt("reason", _c_any_str),
        error=f.opt("error", _c_any_str),
        received_at=f.opt("received_at", _c_ts),
    )


def parse_line_status(topic: str, raw: bytes) -> LineStatus | LineOffline | Rejected:
    """3.3절. `online: false`면 다른 필드를 보지 않는다."""

    def build(obj: dict[str, Any]) -> LineStatus | LineOffline:
        f = _Fields(obj)
        online = f.req("online", _c_bool)
        if online is False:
            return LineOffline()
        timestamp = f.req("timestamp", _c_ts)
        conveyor = f.req("conveyor", _c_enum(LINE_STATES))
        fault_level = f.req("fault_level", _c_int(lo=0, hi=10))
        motor_rpm = f.req("motor_rpm", _c_number())
        sensor_id = f.req("sensor_id", _c_sensor_id)
        production_active = f.req("production_active", _c_bool)
        products = f.opt("products", _c_products)
        last_command = f.opt("last_command", _c_last_command)
        return LineStatus(
            timestamp,
            conveyor,
            fault_level,
            motor_rpm,
            sensor_id,
            production_active,
            products,
            last_command,
            tuple(f.nulled),
        )

    return _parse(build, raw)


def parse_product_created(topic: str, raw: bytes) -> ProductCreated | Rejected:
    """3.4절."""

    def build(obj: dict[str, Any]) -> ProductCreated:
        f = _Fields(obj)
        return ProductCreated(
            f.req("product_id", _c_product_id),
            f.req("timestamp", _c_ts),
            f.req("image_path", _c_rel_path("products")),
        )

    return _parse(build, raw)


def _c_bbox(v: Any) -> Any:
    if not isinstance(v, list) or len(v) != 4:
        return _BAD
    ints = [as_int(x) for x in v]
    return _BAD if any(i is None for i in ints) else tuple(ints)


def parse_vision_result(topic: str, raw: bytes) -> VisionResult | Rejected:
    """3.5절. `defect_type`·`confidence`·`bbox`·`gradcam_path`는 키가 없어도 None으로 받는다."""

    def build(obj: dict[str, Any]) -> VisionResult:
        f = _Fields(obj)
        product_id = f.req("product_id", _c_product_id)
        timestamp = f.req("timestamp", _c_ts)
        defect = f.req("defect", _c_bool)
        image_path = f.req("image_path", _c_rel_path("products"))
        return VisionResult(
            product_id,
            timestamp,
            defect,
            image_path,
            defect_type=f.opt("defect_type", lambda v: v if isinstance(v, str) and DEFECT_TYPE_RE.fullmatch(v) else _BAD),
            confidence=f.opt("confidence", _c_number(0.0, 1.0)),
            bbox=f.opt("bbox", _c_bbox),
            gradcam_path=f.opt("gradcam_path", _c_rel_path("gradcam")),
            judgement_source=f.opt("judgement_source", _c_str(1, 32)),
            nulled=tuple(f.nulled),
        )

    return _parse(build, raw)


def parse_pdm_result(topic: str, raw: bytes) -> PdmResult | Rejected:
    """3.6절 (Shared `cb6dc3c` 확정본)."""

    def build(obj: dict[str, Any]) -> PdmResult:
        f = _Fields(obj)
        sensor_id = f.req("sensor_id", _c_sensor_id)
        timestamp = f.req("timestamp", _c_ts)
        window_start = f.req("window_start", _c_ts)
        anomaly_score = f.req("anomaly_score", _c_number(0.0, 1.0))
        health_index = f.req("health_index", _c_int(lo=0, hi=100))
        state = f.req("state", _c_enum(PDM_STATES))
        model_version = f.opt("model_version", _c_str(1, 64))
        return PdmResult(sensor_id, timestamp, anomaly_score, health_index, state, window_start, model_version, tuple(f.nulled))

    return _parse(build, raw)


def _c_positive(v: Any) -> Any:
    return float(v) if is_number(v) and v > 0 else _BAD


def _spectrum_length(step: float) -> int:
    """배열 길이 규칙 `floor(500 / freq_step_hz) + 1` (부동소수 오차 1e-9 허용)."""
    return math.floor(SPECTRUM_MAX_HZ / step + 1e-9) + 1


def _c_spectrum_array(n: int) -> Callable[[Any], Any]:
    def check(v: Any) -> Any:
        arr = _number_array(v, n, n)  # 길이 n, 유한한 수
        if arr is None or (arr < 0).any():  # 0 이상
            return _BAD
        return arr

    return check


def parse_pdm_spectrum(topic: str, raw: bytes) -> SpectrumPanels | Rejected:
    """3.7절 (Shared `cb6dc3c` 확정본, 표시 전용). 모든 필드가 필수다."""
    if len(raw) > SPECTRUM_MAX_BYTES:
        return Rejected("too_large")

    def build(obj: dict[str, Any]) -> SpectrumPanels:
        f = _Fields(obj)
        sensor_id = f.req("sensor_id", _c_sensor_id)
        timestamp = f.req("timestamp", _c_ts)
        window_start = f.req("window_start", _c_ts)
        rpm = f.req("rpm", _c_number())
        step = f.req("freq_step_hz", _c_positive)
        rot_hz = f.req("rot_hz", _c_number())
        bpfo_hz = f.req("bpfo_hz", _c_number())
        bpfi_hz = f.req("bpfi_hz", _c_number())
        check = _c_spectrum_array(_spectrum_length(step))
        arrays = {name: f.req(name, check) for name in SPECTRUM_ARRAYS}
        panels = tuple(
            SpectrumPanel(
                title,
                0.0,
                step,
                "Hz",
                tuple(SpectrumSeries(name, arrays[name]) for name in SPECTRUM_ARRAYS if name.startswith(prefix)),
            )
            for title, prefix in ((SPECTRUM_TITLE, "spectrum_"), (ENVELOPE_TITLE, "envelope_"))
        )
        return SpectrumPanels(sensor_id, timestamp, window_start, panels, rpm, rot_hz, bpfo_hz, bpfi_hz)

    return _parse(build, raw)


PARSERS: dict[str, Callable[[str, bytes], Any]] = {
    _topics.SENSOR_VIBRATION: parse_sensor_vibration,
    _topics.PRODUCT_CREATED: parse_product_created,
    _topics.LINE_STATUS: parse_line_status,
    _topics.VISION_RESULT: parse_vision_result,
    _topics.PDM_RESULT: parse_pdm_result,
    _topics.PDM_SPECTRUM: parse_pdm_spectrum,
}


def parse(kind: str, topic: str, raw: bytes) -> Any:
    """입력 종류(`topics.TopicMatch.kind`)에 맞는 파서를 부른다."""
    return PARSERS[kind](topic, raw)


# ---------------------------------------------------------------------------
# 발행 (4.1절)

CONVEYOR_REASONS = ("INTERLOCK_CRITICAL", "OPERATOR_START", "OPERATOR_STOP")
ALARM_SEVERITIES = ("WARNING", "CRITICAL")


def new_command_id() -> str:
    """UUID4 문자열(소문자, 36자)."""
    return str(uuid.uuid4())


def build_conveyor(command: str, command_id: str, reason: str, now: datetime) -> dict[str, Any]:
    """Conveyor Control (Shared INTERFACES, AGREEMENTS.md A-03). `now`는 발행 직전 `clock.wall()`."""
    if command not in COMMANDS:
        raise ValueError(f"invalid command {command!r}")
    if not isinstance(command_id, str) or not 1 <= len(command_id) <= 64:
        raise ValueError("command_id must be 1..64 chars")
    return {
        "schema_version": 1,
        "command": command,
        "command_id": command_id,
        "timestamp": iso_ms(now),
        "reason": reason,
    }


@dataclass(frozen=True)
class Alarm:
    """Alarm 값 객체(03 4절). 필드 이름은 A-02 Alarm Event와 같다. OPS-3B가 만든다."""

    alarm_id: str
    timestamp: datetime  # 원인 PdM Result의 timestamp
    raised_at: datetime  # Operations 판정 시각
    sensor_id: str
    severity: str  # WARNING | CRITICAL
    previous_state: str | None
    health_index: int
    anomaly_score: float


def build_alarm(alarm: Alarm) -> dict[str, Any]:
    """Alarm Event (AGREEMENTS.md A-02)."""
    if alarm.severity not in ALARM_SEVERITIES:
        raise ValueError(f"invalid severity {alarm.severity!r}")
    if alarm.previous_state is not None and alarm.previous_state not in PDM_STATES:
        raise ValueError(f"invalid previous_state {alarm.previous_state!r}")
    return {
        "schema_version": 1,
        "alarm_id": alarm.alarm_id,
        "timestamp": iso_ms(alarm.timestamp),
        "raised_at": iso_ms(alarm.raised_at),
        "sensor_id": alarm.sensor_id,
        "severity": alarm.severity,
        "previous_state": alarm.previous_state,
        "health_index": alarm.health_index,
        "anomaly_score": alarm.anomaly_score,
    }


def serialize(payload: dict[str, Any]) -> bytes:
    """발행 직렬화 (4.1절)."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
