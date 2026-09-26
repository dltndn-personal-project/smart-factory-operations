"""상관분석 (docs/spec/04-analysis.md 2절, 08-verification.md 3.4절)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from factory_operations.clock import TS_PATTERN
from factory_operations.config import load_config
from factory_operations.domain.correlation import compute

T0 = datetime(2026, 9, 25, 5, 20, 0, tzinfo=timezone.utc)


def ts(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def cfg_with(**corr):
    cfg = load_config({})
    return cfg.model_copy(update={"correlation": cfg.correlation.model_copy(update=corr)}) if corr else cfg


def synthetic(seed: int = 0, duration_s: float = 600.0, lag_s: float = 13.0):
    """08 3.4절: 설비 점수 0.5초 간격 600초, 30초마다 무작위 수준의 계단. 제품 2초 간격,
    불량 확률 = 0.05 + 0.6 × score(t − 13). seed는 0(DECISIONS D-49: 봉우리가 완만해 seed에 따라
    기대를 벗어날 수 있다)."""
    rng = np.random.default_rng(seed)
    levels = rng.uniform(0.0, 1.0, int(duration_s // 30) + 1)

    def score(t: float) -> float:
        return float(levels[int(max(t, 0.0) // 30)])

    scores = [(ts(i * 0.5), score(i * 0.5)) for i in range(int(duration_s / 0.5))]
    inspections = []
    for i in range(int(duration_s / 2)):
        t = i * 2.0 + 0.3
        p = 0.05 + 0.6 * score(t - lag_s)
        inspections.append((ts(t), bool(rng.random() < p)))
    return inspections, scores


def test_known_lag_13(fake_clock):
    inspections, scores = synthetic()
    r = compute(inspections, scores, cfg_with(), clock=fake_clock)
    assert r["best"] is not None
    assert 12 <= r["best"]["lag_s"] <= 14, r["best"]
    assert r["at_default"]["lag_s"] == 13
    assert r["at_default"]["pearson"] > 0.3, r["at_default"]
    assert r["at_default"]["reason"] is None


def _linear_data(n: int, *, defect=None, score=None):
    """검사 1초 간격, 설비 결과 같은 시각. lag 0에서 표본 n개."""
    inspections = [(ts(i), defect(i) if defect else i % 3 == 0) for i in range(n)]
    scores = [(ts(i), score(i) if score else (i % 7) / 7) for i in range(n)]
    return inspections, scores


def test_insufficient_samples(fake_clock):
    cfg = cfg_with(lag_min_s=0, lag_max_s=0, default_lag_s=0)
    r = compute(*_linear_data(19), cfg, clock=fake_clock)
    a = r["at_default"]
    assert (a["n"], a["pearson"], a["spearman"], a["reason"]) == (19, None, None, "insufficient_samples")
    assert r["best"] is None
    r20 = compute(*_linear_data(20), cfg, clock=fake_clock)
    assert r20["at_default"]["reason"] is None and r20["at_default"]["pearson"] is not None


def test_single_class(fake_clock):
    cfg = cfg_with(lag_min_s=0, lag_max_s=2, default_lag_s=0)
    r = compute(*_linear_data(40, defect=lambda i: False), cfg, clock=fake_clock)
    for row in r["curve"] + [r["at_default"]]:
        assert (row["pearson"], row["spearman"], row["reason"]) == (None, None, "single_class")
    assert r["best"] is None


def test_constant_score(fake_clock):
    cfg = cfg_with(lag_min_s=0, lag_max_s=2, default_lag_s=0)
    r = compute(*_linear_data(40, score=lambda i: 0.42), cfg, clock=fake_clock)
    for row in r["curve"] + [r["at_default"]]:
        assert (row["pearson"], row["spearman"], row["reason"]) == (None, None, "constant_score")
    assert r["best"] is None


def test_tie_prefers_smaller_lag(fake_clock):
    # 설비 결과 10초 간격, 검사는 결과 3초 뒤. lag 0~3은 모두 같은 결과(차 3, 2, 1, 0초)에 붙어
    # 표본 쌍이 같고 |Pearson|이 같다. 가장 작은 lag 0이 best.
    rng = np.random.default_rng(3)
    x = rng.uniform(0, 1, 30)
    scores = [(ts(10 * j), float(x[j])) for j in range(30)]
    inspections = [(ts(10 * i + 3), bool(x[i] > np.median(x))) for i in range(30)]
    cfg = cfg_with(lag_min_s=0, lag_max_s=3, default_lag_s=0)
    r = compute(inspections, scores, cfg, clock=fake_clock)
    ps = [row["pearson"] for row in r["curve"]]
    assert ps[0] is not None and len(set(ps)) == 1
    assert r["best"]["lag_s"] == 0
    assert r["best"]["pearson"] == ps[0]

    # 부호만 다르고 크기가 같아도 |Pearson| 기준
    inv = [(t, not d) for t, d in inspections]
    r2 = compute(inv, scores, cfg, clock=fake_clock)
    assert r2["best"]["lag_s"] == 0 and r2["best"]["pearson"] == -ps[0]


def test_max_gap_boundary(fake_clock):
    # 차가 정확히 max_gap_s(5초)이면 표본, 1 ms 넘으면 제외
    cfg = cfg_with(lag_min_s=0, lag_max_s=0, default_lag_s=0, min_samples=3)
    scores = [(ts(0), 0.1), (ts(100), 0.9), (ts(200), 0.5)]
    inspections = [
        (ts(5), False),
        (ts(105), True),
        (ts(205), True),
        (ts(205.001), False),
    ]
    r = compute(inspections, scores, cfg, clock=fake_clock)
    assert r["at_default"]["n"] == 3


def test_bins_match_counts(fake_clock):
    inspections, scores = synthetic(seed=11, duration_s=900.0)
    cfg = cfg_with()
    r = compute(inspections, scores, cfg, clock=fake_clock)
    bins = r["bins"]
    t_first = inspections[0][0]
    last_idx = int((inspections[-1][0] - t_first).total_seconds() // 30)
    assert len(bins) == 20  # 900초 / 30초 = 30구간 중 최근 20
    for j, b in enumerate(bins):
        i = last_idx - 19 + j
        start = t_first + timedelta(seconds=30 * i)
        assert b["start"] == start.strftime("%Y-%m-%dT%H:%M:%S.") + f"{start.microsecond // 1000:03d}Z"
        in_bin = [d for t, d in inspections if start <= t < start + timedelta(seconds=30)]
        assert b["n_inspected"] == len(in_bin)
        assert b["defect_rate"] == round(sum(in_bin) / len(in_bin), 4)
        # 기본 lag 13초 as-of 유효 표본의 점수 평균
        xs = []
        for t, _ in inspections:
            if start <= t < start + timedelta(seconds=30):
                u = t - timedelta(seconds=13)
                prior = [(st, sx) for st, sx in scores if st <= u]
                if prior and (u - prior[-1][0]).total_seconds() <= 5.0:
                    xs.append(prior[-1][1])
        assert b["mean_anomaly"] == (round(float(np.mean(xs)), 4) if xs else None)


def test_bins_empty_interval_and_short_run(fake_clock):
    cfg = cfg_with()
    inspections = [(ts(0), True), (ts(10), False), (ts(70), True)]  # 30~60초 구간은 비어 있다
    r = compute(inspections, [], cfg, clock=fake_clock)
    assert [(b["n_inspected"], b["defect_rate"], b["mean_anomaly"]) for b in r["bins"]] == [
        (2, 0.5, None),
        (0, None, None),
        (1, 1.0, None),
    ]
    assert compute([], [], cfg, clock=fake_clock)["bins"] == []


def test_result_shape(fake_clock):
    inspections, scores = synthetic()
    r = compute(inspections, scores, cfg_with(), clock=fake_clock)
    assert list(r) == ["computed_at", "n_inspections", "default_lag_s", "at_default", "best", "curve", "bins"]
    assert r["computed_at"] == "2026-09-25T05:21:00.000Z"  # 주입한 시계
    assert re.match(TS_PATTERN, r["computed_at"])
    assert r["n_inspections"] == len(inspections)
    assert r["default_lag_s"] == 13 and isinstance(r["default_lag_s"], int)
    assert [row["lag_s"] for row in r["curve"]] == list(range(0, 31))
    for row in r["curve"] + [r["at_default"], r["best"]]:
        assert list(row) == ["lag_s", "n", "pearson", "spearman", "reason"]
        assert isinstance(row["lag_s"], int) and isinstance(row["n"], int)
        for k in ("pearson", "spearman"):
            v = row[k]
            assert v is None or (isinstance(v, float) and v == round(v, 4))
    assert r["at_default"] == r["curve"][13]
    for b in r["bins"]:
        assert list(b) == ["start", "n_inspected", "defect_rate", "mean_anomaly"]
        assert re.match(TS_PATTERN, b["start"])
        for k in ("defect_rate", "mean_anomaly"):
            assert b[k] is None or (isinstance(b[k], float) and b[k] == round(b[k], 4))


def test_matches_scipy_direct(fake_clock):
    # 계수는 scipy 값의 소수 4자리 반올림
    from scipy import stats

    cfg = cfg_with(lag_min_s=0, lag_max_s=0, default_lag_s=0)
    inspections, scores = _linear_data(50)
    r = compute(inspections, scores, cfg, clock=fake_clock)
    x = np.array([s for _, s in scores])
    y = np.array([1.0 if d else 0.0 for _, d in inspections])
    assert r["at_default"]["pearson"] == pytest.approx(round(stats.pearsonr(x, y).statistic, 4), abs=0)
    assert r["at_default"]["spearman"] == pytest.approx(round(stats.spearmanr(x, y).statistic, 4), abs=0)
