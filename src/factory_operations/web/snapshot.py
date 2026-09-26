"""`/api/snapshot` 만들기 (docs/spec/06-dashboard.md 3·4절).

순수 함수 `build_snapshot(view, now_wall, now_mono, cfg) -> dict`. 입력은 StateStore의
`snapshot_view()` 결과(`domain.state.SnapshotView`)이고, 락 밖에서 JSON으로 바꿀 수 있는 값만 만든다.
FastAPI·psycopg·paho를 import하지 않는다(01 1절).

- 시각 필드는 모두 `iso_ms` 문자열이다. `age_s`는 Operations `mono()` 기준 수신 뒤 지난 초(소수 1자리).
- stale 판정(4절)은 `age_s` 값(소수 1자리)과 설정 임계값을 비교한다. 화면에 보이는 값과 판정이 어긋나지 않는다.
- DB 요약 값은 psycopg 원형(aware datetime, `uuid.UUID`, int 목록)이라 여기서 JSON 값으로 바꾼다.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Hashable, Mapping, Sequence

import numpy as np

from ..clock import iso_ms, parse_ts

SCHEMA_VERSION = 1
PDM_HISTORY_MAX = 240  # 120초 × 0.5초 hop
DECIMALS = 4  # 진동·스펙트럼·불량률 소수 자리
CORRELATION_STALE_PERIODS = 3  # computed_at 뒤 3 × correlation.period_s

NONE = {"status": "NONE"}


# ---------------------------------------------------------------------------
# 공통


def _age(now_mono: float, mono: float) -> float:
    return round(max(0.0, now_mono - mono), 1)


def _ts(dt: datetime | None) -> str | None:
    return iso_ms(dt) if dt is not None else None


def _round(v: float | None, n: int = DECIMALS) -> float | None:
    if v is None:
        return None
    return round(float(v), n)


def jsonable(v: Any) -> Any:
    """DB 행 값·결과 dict를 JSON 값으로 바꾼다(datetime → iso_ms, UUID → 문자열, 튜플 → 목록)."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, datetime):
        return iso_ms(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, np.generic):
        return jsonable(v.item())
    if isinstance(v, np.ndarray):
        return [jsonable(x) for x in v.tolist()]
    if isinstance(v, Mapping):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return str(v)


# ---------------------------------------------------------------------------
# 절마다


def line_section(line: Any, now_mono: float, cfg: Any) -> dict[str, Any]:
    """`line` (3절 표, 4절). `line`은 `domain.line.LineView` 또는 None."""
    if line is None or line.last_mono is None:
        return dict(NONE)
    ls = line.latest
    if line.online is False:
        status = "OFFLINE"
    else:
        age = _age(now_mono, line.latest_mono)
        status = "STALE" if age > cfg.dashboard.line_stale_s else "LIVE"
    out: dict[str, Any] = {
        "status": status,
        "timestamp": _ts(ls.timestamp) if ls else None,
        "received_at": _ts(line.latest_wall),
        "age_s": _age(now_mono, line.latest_mono) if line.latest_mono is not None else None,
        "conveyor": ls.conveyor if ls else None,
        "fault_level": ls.fault_level if ls else None,
        "motor_rpm": ls.motor_rpm if ls else None,
        "production_active": ls.production_active if ls else None,
        "sensor_id": ls.sensor_id if ls else None,
        "products": None,
        "last_command": None,
    }
    if ls is not None and ls.products is not None:
        p = ls.products
        out["products"] = {
            "spawned": p.spawned,
            "created": p.created,
            "expired": p.expired,
            "in_flight": p.in_flight,
            "last_product_id": p.last_product_id,
        }
    if ls is not None and ls.last_command is not None:
        c = ls.last_command
        out["last_command"] = {
            "command": c.command,
            "command_id": c.command_id,
            "source": c.source,
            "received_at": _ts(c.received_at),
            "result": c.result,
            "reason": c.reason,
            "error": c.error,
        }
    return out


def line_sensor_id(line: Any, cfg: Any) -> str:
    return line.line_sensor_id if line is not None else cfg.line.sensor_id


def pdm_section(view: Any, now_mono: float, cfg: Any) -> dict[str, Any]:
    """`pdm`: 라인 센서의 마지막 PdM Result와 최근 이력."""
    sensor = line_sensor_id(view.line, cfg)
    rec = view.pdm_latest.get(sensor)
    if rec is None:
        return dict(NONE)
    r = rec.value
    age = _age(now_mono, rec.mono)
    ref = view.line.reference_time if view.line is not None else None
    history = view.pdm_history.get(sensor, ())[-PDM_HISTORY_MAX:]
    return {
        "status": "LIVE" if age <= cfg.pdm.stale_s else "STALE",
        "sensor_id": r.sensor_id,
        "timestamp": _ts(r.timestamp),
        "window_start": _ts(r.window_start),
        "received_at": _ts(rec.wall),
        "age_s": age,
        "anomaly_score": r.anomaly_score,
        "health_index": r.health_index,
        "state": r.state,
        "model_version": r.model_version,
        "before_restart": ref is not None and r.timestamp <= ref,
        "history": [
            {"timestamp": _ts(h.timestamp), "anomaly_score": h.anomaly_score, "health_index": h.health_index, "state": h.state}
            for h in history
        ],
    }


def _values(arr: np.ndarray) -> list[float]:
    return np.round(np.asarray(arr, dtype=np.float64), DECIMALS).tolist()


def spectrum_section(rec: Any, now_mono: float, cfg: Any) -> dict[str, Any]:
    """`spectrum`: 02 3.7절 `SpectrumPanels`, 값은 소수 4자리."""
    if rec is None:
        return dict(NONE)
    sp = rec.value
    age = _age(now_mono, rec.mono)
    return {
        "status": "LIVE" if age <= cfg.dashboard.spectrum_stale_s else "STALE",
        "timestamp": _ts(sp.timestamp),
        "received_at": _ts(rec.wall),
        "age_s": age,
        "panels": [
            {
                "title": p.title,
                "x_start": p.x_start,
                "x_step": p.x_step,
                "x_unit": p.x_unit,
                "series": [{"name": s.name, "values": _values(s.values)} for s in p.series],
            }
            for p in sp.panels
        ],
    }


def minmax_buckets(samples: np.ndarray, buckets: int) -> tuple[list[float], list[float]]:
    """`samples`를 `buckets`개 구간으로 같게 나눈 구간별 최솟값·최댓값(소수 4자리).
    샘플이 구간 수보다 적으면 구간 수 = 샘플 수. 나누어떨어지지 않으면 구간 길이 차이는 1 이하다."""
    n = len(samples)
    if n == 0:
        return [], []
    b = max(1, min(int(buckets), n))
    starts = (np.arange(b, dtype=np.int64) * n) // b
    a = np.asarray(samples, dtype=np.float64)
    return (
        np.round(np.minimum.reduceat(a, starts), DECIMALS).tolist(),
        np.round(np.maximum.reduceat(a, starts), DECIMALS).tolist(),
    )


def vibration_section(ring: Sequence[Any], now_mono: float, cfg: Any) -> dict[str, Any]:
    """`vibration`: 링 버퍼 chunk를 `seq` 순으로 이어 축별 min/max 띠로 솎는다(D-31)."""
    if not ring:
        return dict(NONE)
    ordered = sorted(ring, key=lambda rec: rec.value.seq)
    last = ordered[-1].value  # 가장 뒤 seq: timestamp·rpm·temperature
    newest = max(ring, key=lambda rec: rec.mono)  # 가장 최근 수신: age_s
    age = _age(now_mono, newest.mono)
    buckets = cfg.dashboard.vibration_buckets
    out: dict[str, Any] = {
        "status": "STALE" if age > cfg.dashboard.vibration_stale_s else "LIVE",
        "sensor_id": last.sensor_id,
        "timestamp": _ts(last.timestamp),
        "received_at": _ts(newest.wall),
        "age_s": age,
        "rpm": last.rpm,
        "temperature": last.temperature,
        "window_s": None,
        "sample_rate_hz": last.sample_rate_hz,
    }
    n = 0
    for axis in ("x", "y", "z"):
        samples = np.concatenate([getattr(rec.value, axis) for rec in ordered])
        n = len(samples)
        lo, hi = minmax_buckets(samples, buckets)
        out[axis] = {"min": lo, "max": hi}
    out["window_s"] = round(n / last.sample_rate_hz, 6)
    return out


def interlock_section(view: Any, now_mono: float) -> dict[str, Any]:
    """`interlock` (03 3.1절 상태)."""
    line = view.line
    il = view.interlock
    judged = getattr(il, "judged", None)
    pending = getattr(il, "pending", None)
    return {
        "line_state": line.line_state if line is not None else "UNKNOWN",
        "reference_time": _ts(line.reference_time) if line is not None else None,
        "judged": {"timestamp": _ts(judged.timestamp), "state": judged.state} if judged is not None else None,
        "pending_stop": (
            {"command_id": pending.command_id, "age_s": _age(now_mono, pending.issued_mono)} if pending is not None else None
        ),
        "last_trigger_timestamp": _ts(getattr(il, "last_trigger_ts", None)),
    }


INSPECTION_KEYS = (
    "product_id",
    "timestamp",
    "defect",
    "defect_type",
    "confidence",
    "bbox",
    "image_path",
    "gradcam_path",
    "judgement_source",
    "health_index_at_time",
)
ALARM_KEYS = ("alarm_id", "timestamp", "raised_at", "sensor_id", "severity", "previous_state", "health_index", "anomaly_score")
CONTROL_KEYS = (
    "command_id",
    "command",
    "reason",
    "origin",
    "source",
    "issued_at",
    "trigger_timestamp",
    "result",
    "result_received_at",
    "error",
    "recorded_at",
)


def _rows(rows: Sequence[Mapping[str, Any]] | None, keys: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
    return [{k: jsonable(r.get(k)) for k in keys} for r in list(rows or ())[:limit]]


def summary_sections(summary: Any, db_ok: bool, cfg: Any) -> dict[str, Any]:
    """`production`, `inspections`, `alarms`, `controls` (05 5절 요약). 없거나 DB가 끊겼으면 null과 빈 목록."""
    if summary is None or not db_ok:
        return {"production": None, "inspections": [], "alarms": [], "controls": []}
    s = summary.value
    inspected = int(s.get("inspected") or 0)
    defects = int(s.get("defects") or 0)
    dash = cfg.dashboard
    inspections = _rows(s.get("inspections"), INSPECTION_KEYS, dash.recent_inspections)
    for row in inspections:
        if isinstance(row["confidence"], float):  # real 열: 0.9 → 0.8999999761…
            row["confidence"] = _round(row["confidence"])
    return {
        "production": {
            "summary_at": jsonable(s.get("summary_at") or summary.wall),
            "produced": int(s.get("produced") or 0),
            "inspected": inspected,
            "defects": defects,
            "defect_rate": round(defects / inspected, DECIMALS) if inspected else None,
        },
        "inspections": inspections,
        "alarms": _rows(s.get("alarms"), ALARM_KEYS, dash.recent_alarms),
        "controls": _rows(s.get("controls"), CONTROL_KEYS, dash.recent_controls),
    }


def correlation_section(result: Any, db_ok: bool, now_wall: datetime, cfg: Any) -> dict[str, Any] | None:
    """`correlation` (04 2.3절 결과). `stale`은 항상 붙인다(true: DB 끊김 또는 3 주기 넘게 지남)."""
    if result is None:
        return None
    out = jsonable(result)
    stale = not db_ok
    try:
        computed = parse_ts(out.get("computed_at"))
        if now_wall - computed > timedelta(seconds=CORRELATION_STALE_PERIODS * cfg.correlation.period_s):
            stale = True
    except ValueError:
        stale = True
    out["stale"] = stale
    return out


def counters_section(counters: Mapping[Hashable, int]) -> dict[str, Any]:
    """StateStore 카운터: `("rejected", topic, reason)` → `rejected["topic:reason"]`,
    `…queue_overflow` 계열 합계 → `queue_overflow`."""
    rejected: dict[str, int] = {}
    overflow = 0
    for key, n in counters.items():
        head = key[0] if isinstance(key, tuple) and key else key
        if head == "rejected" and isinstance(key, tuple):
            rejected[":".join(str(k) for k in key[1:])] = n
        elif isinstance(head, str) and head.endswith("queue_overflow"):
            overflow += n
    return {"rejected": rejected, "queue_overflow": overflow}


# ---------------------------------------------------------------------------


def build_snapshot(view: Any, now_wall: datetime, now_mono: float, cfg: Any) -> dict[str, Any]:
    """06 3절 JSON. `view`는 `StateStore.snapshot_view()` 결과."""
    snap: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": iso_ms(now_wall),
        "mqtt_connected": bool(view.mqtt_connected),
        "db_ok": bool(view.db_ok),
        "line": line_section(view.line, now_mono, cfg),
        "pdm": pdm_section(view, now_mono, cfg),
        "spectrum": spectrum_section(view.spectrum_latest, now_mono, cfg),
        "vibration": vibration_section(view.vibration_ring, now_mono, cfg),
        "interlock": interlock_section(view, now_mono),
    }
    snap.update(summary_sections(view.summary, view.db_ok, cfg))
    snap["correlation"] = correlation_section(view.correlation, view.db_ok, now_wall, cfg)
    snap["counters"] = counters_section(view.counters)
    return snap
