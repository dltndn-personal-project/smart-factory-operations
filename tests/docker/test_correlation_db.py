"""DB 주기 상관분석 (docs/spec/04-analysis.md 2절, 05-storage.md 3·5절, docs/plan/04-analysis.md A5).

실제 DB에 합성 검사·설비 행을 넣고 DB 스레드에 `correlation.compute`를 주입해 주기 결과를 받는다.
`store/`는 고치지 않는다(docs/plan/05-storage.md 1절).
"""

from __future__ import annotations

import functools
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import numpy as np
import pytest

from factory_operations.domain.correlation import compute
from factory_operations.store.db import DbWriter

from .test_db_writer import make_cfg, wait_for

if TYPE_CHECKING:
    from .conftest import DbContainer

pytestmark = pytest.mark.docker

T0 = datetime(2026, 9, 25, 5, 20, 0, tzinfo=timezone.utc)


def ts(s: float) -> datetime:
    return T0 + timedelta(seconds=s)


def synthetic(seed: int = 0, duration_s: float = 600.0, lag_s: float = 13.0):
    """`tests/unit/test_correlation.py`의 `synthetic`과 같은 규칙(08 3.4절, DECISIONS D-49)."""
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


class FixedClock:
    def __init__(self, wall: datetime):
        self._wall = wall

    def wall(self) -> datetime:
        return self._wall

    def mono(self) -> float:
        return time.monotonic()


def test_periodic_correlation_from_db(clean_db: "DbContainer") -> None:
    inspections, scores = synthetic()
    with clean_db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                'INSERT INTO inspection (product_id, "timestamp", defect, image_path, sensor_id, received_at) '
                "VALUES (%s, %s, %s, %s, 'motor01', %s)",
                [(f"P-{i:08d}", t, d, f"products/P-{i:08d}.jpg", t) for i, (t, d) in enumerate(inspections)],
            )
            cur.executemany(
                'INSERT INTO equipment_state (sensor_id, "timestamp", window_start, anomaly_score, health_index, '
                "state, received_at) VALUES ('motor01', %s, %s, %s, 50, 'WARNING', %s)",
                [(t, t - timedelta(seconds=1), x, t) for t, x in scores],
            )
            # 라인 센서가 아닌 센서의 결과는 쓰지 않는다
            cur.execute(
                'INSERT INTO equipment_state (sensor_id, "timestamp", anomaly_score, health_index, state, received_at) '
                "VALUES ('motor02', %s, 0.99, 1, 'CRITICAL', %s)",
                (ts(100.1), ts(100.1)),
            )

    computed_at = datetime(2026, 9, 25, 5, 31, 0, 120000, tzinfo=timezone.utc)
    results: list[dict] = []
    lock = threading.Lock()

    def on_correlation(r: dict) -> None:
        with lock:
            results.append(r)

    cfg = make_cfg(clean_db.url, correlation={"period_s": 1.0})
    w = DbWriter(
        cfg,
        queue.Queue(),
        on_correlation=on_correlation,
        compute_correlation=functools.partial(compute, clock=FixedClock(computed_at)),
    )
    w.start()
    try:
        assert wait_for(lambda: len(results) >= 2, 15), "두 번 이상의 주기 결과가 콜백으로 와야 한다"
    finally:
        w.stop()

    r = results[-1]
    assert r["computed_at"] == "2026-09-25T05:31:00.120Z"
    assert r["n_inspections"] == len(inspections)
    assert 12 <= r["best"]["lag_s"] <= 14, r["best"]
    assert r["at_default"]["pearson"] > 0.3
    # DB를 거친 결과가 메모리의 같은 데이터로 직접 계산한 결과와 같다
    direct = compute(inspections, scores, cfg, clock=FixedClock(computed_at))
    assert r == direct
