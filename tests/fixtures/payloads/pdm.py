"""테스트·smoke용 PdM 메시지 생성 함수 (spec D-39).

PdM 형식(필드 구성)은 이 폴더의 PdM fixture JSON이 원본이다. 함수는 fixture를 템플릿으로 읽어
값만 바꾸므로 Shared 확정본이 바뀌면 fixture만 바꾸면 된다(OPS-10).

- 테스트: `from fixtures.payloads import pdm` (pytest가 `tests/`를 sys.path에 넣는다)
- `scripts/smoke.py`: 파일 경로로 불러온다(`importlib.util.spec_from_file_location`)

`timestamp`는 CONVENTIONS 문자열이나 aware datetime을 받는다. 템플릿에 `window_start`가 있고
바꿀 값에 없으면 `timestamp` 1초 전으로 맞춘다(10 chunk 윈도우). 키를 빼려면 값에 `DROP`을 준다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULT_TEMPLATE = HERE / "pdm_result_draft.json"
SPECTRUM_TEMPLATE = HERE / "pdm_spectrum_envelope.json"
WINDOW_S = 1.0

DROP = object()  # 바꿀 값에 주면 그 키를 뺀다


def _iso_ms(dt: datetime) -> str:
    u = dt.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (u.microsecond // 1000)


def _as_datetime(ts: str | datetime) -> datetime:
    if isinstance(ts, datetime):
        return ts
    return datetime.strptime(ts[:-1], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)


def _fill(template: Path, values: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    msg = json.loads(template.read_text(encoding="utf-8"))
    for key, value in values.items():
        if key not in msg:
            raise KeyError(f"{template.name} has no field {key!r}")
        msg[key] = value
    ts = _as_datetime(values["timestamp"])
    msg["timestamp"] = _iso_ms(ts)
    if "window_start" in msg and "window_start" not in overrides:
        msg["window_start"] = _iso_ms(ts - timedelta(seconds=WINDOW_S))
    for key, value in overrides.items():
        if value is DROP:
            msg.pop(key, None)
        else:
            msg[key] = _iso_ms(value) if isinstance(value, datetime) else value
    return msg


def pdm_result(
    sensor_id: str,
    timestamp: str | datetime,
    state: str,
    health_index: int,
    anomaly_score: float,
    **overrides: Any,
) -> dict[str, Any]:
    """PdM Result 한 건(dict). 템플릿: `pdm_result_draft.json`."""
    values = {
        "sensor_id": sensor_id,
        "timestamp": timestamp,
        "state": state,
        "health_index": health_index,
        "anomaly_score": anomaly_score,
    }
    return _fill(RESULT_TEMPLATE, values, overrides)


def pdm_spectrum(sensor_id: str, timestamp: str | datetime, **overrides: Any) -> dict[str, Any]:
    """PdM Spectrum 한 건(dict). 템플릿: `pdm_spectrum_envelope.json`(배열 값은 템플릿 그대로)."""
    return _fill(SPECTRUM_TEMPLATE, {"sensor_id": sensor_id, "timestamp": timestamp}, overrides)


def to_bytes(msg: dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":"), ensure_ascii=False).encode()
