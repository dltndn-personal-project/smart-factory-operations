"""설비-품질 상관분석 (docs/spec/04-analysis.md 2절, DECISIONS D-13·D-30). 순수 함수.

DB 스레드(`store/db.py`)가 `correlation.period_s`마다 두 조회 결과로 `compute`를 부른다.
- `inspections`: `(timestamp, defect)` 목록, `timestamp` 순(검사 캡처 시각).
- `scores`: 라인 센서의 `(timestamp, anomaly_score)` 목록, `timestamp` 순(PdM 윈도우 끝).
- `cfg`: `correlation`·`join` 절을 가진 설정(`config.Config`).
예외는 호출자가 로그로 남기고 이전 결과를 유지한다(2.3절).

시각은 정수 마이크로초로 바꿔 비교한다(`max_gap_s` 경계에서 부동소수 오차가 없게).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import numpy as np
from scipy import stats

from ..clock import Clock, SystemClock, iso_ms

MAX_BINS = 20
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

REASON_INSUFFICIENT = "insufficient_samples"
REASON_SINGLE_CLASS = "single_class"
REASON_CONSTANT = "constant_score"


def _us(dt: datetime) -> int:
    d = dt - _EPOCH
    return (d.days * 86400 + d.seconds) * 1_000_000 + d.microseconds


def _secs_us(s: float) -> int:
    return int(round(float(s) * 1_000_000))


def _num(v: float) -> int | float:
    """정수 값이면 int(예: `lag_s` 13), 아니면 float."""
    f = float(v)
    return int(f) if f.is_integer() else f


def _r4(v: float | None) -> float | None:
    if v is None:
        return None
    f = float(v)
    return round(f, 4) if math.isfinite(f) else None


def _lags(c: Any) -> list[float]:
    n = int(math.floor((float(c.lag_max_s) - float(c.lag_min_s)) / float(c.lag_step_s) + 1e-9)) + 1
    return [float(c.lag_min_s) + i * float(c.lag_step_s) for i in range(n)]


def _pairs(t: np.ndarray, s: np.ndarray, lag_s: float, max_gap_us: int) -> tuple[np.ndarray, np.ndarray]:
    """lag `L`의 as-of 결합: 목표 시각 `u = t − L` 이하 가장 최근 설비 결과 `k`가 `max_gap_s` 안인 표본.
    반환: 검사 인덱스, 설비 인덱스."""
    u = t - _secs_us(lag_s)
    k = np.searchsorted(s, u, side="right") - 1
    ok = k >= 0
    ok[ok] = (u[ok] - s[k[ok]]) <= max_gap_us
    idx = np.nonzero(ok)[0]
    return idx, k[idx]


def _at_lag(t: np.ndarray, y: np.ndarray, s: np.ndarray, x: np.ndarray, lag_s: float, cfg: Any) -> dict[str, Any]:
    idx, k = _pairs(t, s, lag_s, _secs_us(cfg.join.max_gap_s))
    xs, ys = x[k], y[idx]
    n = int(len(idx))
    out: dict[str, Any] = {"lag_s": _num(lag_s), "n": n, "pearson": None, "spearman": None, "reason": None}
    if n < cfg.correlation.min_samples:
        out["reason"] = REASON_INSUFFICIENT
    elif np.all(ys == ys[0]):
        out["reason"] = REASON_SINGLE_CLASS
    elif np.all(xs == xs[0]):  # 분산 0
        out["reason"] = REASON_CONSTANT
    else:
        out["pearson"] = _r4(stats.pearsonr(xs, ys).statistic)
        out["spearman"] = _r4(stats.spearmanr(xs, ys).statistic)
    return out


def _bins(t: np.ndarray, y: np.ndarray, s: np.ndarray, x: np.ndarray, cfg: Any) -> list[dict[str, Any]]:
    """기본 lag의 표본을 캡처 시각 기준 `bin_s` 구간으로 나눈다. 첫 검사 시각부터 `bin_s`씩, 최근 20구간."""
    if len(t) == 0:
        return []
    bin_us = _secs_us(cfg.correlation.bin_s)
    b = (t - t[0]) // bin_us
    n_bins = int(b[-1]) + 1
    idx, k = _pairs(t, s, float(cfg.correlation.default_lag_s), _secs_us(cfg.join.max_gap_s))
    valid_x = np.full(len(t), np.nan)
    valid_x[idx] = x[k]
    t0 = _EPOCH + timedelta(microseconds=int(t[0]))
    out = []
    for i in range(max(0, n_bins - MAX_BINS), n_bins):
        m = b == i
        n_insp = int(m.sum())
        vx = valid_x[m]
        vx = vx[~np.isnan(vx)]
        out.append(
            {
                "start": iso_ms(t0 + timedelta(microseconds=i * bin_us)),
                "n_inspected": n_insp,
                "defect_rate": _r4(y[m].sum() / n_insp) if n_insp else None,
                "mean_anomaly": _r4(vx.mean()) if len(vx) else None,
            }
        )
    return out


def compute(
    inspections: Sequence[Sequence[Any]],
    scores: Sequence[Sequence[Any]],
    cfg: Any,
    clock: Clock | None = None,
) -> dict[str, Any]:
    """04 2.2절 1~5번과 2.3절 결과 형식. `computed_at`은 `clock.wall()`(기본 시스템 시계)."""
    clock = clock or SystemClock()
    c = cfg.correlation
    t = np.array([_us(r[0]) for r in inspections], dtype=np.int64)
    y = np.array([1.0 if r[1] else 0.0 for r in inspections], dtype=np.float64)
    s = np.array([_us(r[0]) for r in scores], dtype=np.int64)
    x = np.array([float(r[1]) for r in scores], dtype=np.float64)
    # 조회가 timestamp 순이지만 순서를 가정하지 않는다(안정 정렬)
    if len(t) > 1 and np.any(np.diff(t) < 0):
        o = np.argsort(t, kind="stable")
        t, y = t[o], y[o]
    if len(s) > 1 and np.any(np.diff(s) < 0):
        o = np.argsort(s, kind="stable")
        s, x = s[o], x[o]

    curve = [_at_lag(t, y, s, x, lag, cfg) for lag in _lags(c)]
    best = None
    for r in curve:  # lag 오름차순: 같으면 먼저 온(작은) lag를 유지
        if r["pearson"] is not None and (best is None or abs(r["pearson"]) > abs(best["pearson"])):
            best = r
    return {
        "computed_at": iso_ms(clock.wall()),
        "n_inspections": int(len(t)),
        "default_lag_s": _num(c.default_lag_s),
        "at_default": _at_lag(t, y, s, x, float(c.default_lag_s), cfg),
        "best": dict(best) if best is not None else None,
        "curve": curve,
        "bins": _bins(t, y, s, x, cfg),
    }
