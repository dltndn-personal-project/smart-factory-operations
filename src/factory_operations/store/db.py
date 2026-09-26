"""DB 스레드 (docs/spec/05-storage.md 3·5절, 01-core.md 2·7절, DECISIONS D-11·D-14·D-15).

DB 큐의 쓰기 작업(`store/jobs.py`)을 실행하고, 센서 chunk를 배치로 쓰고, 요약·상관분석 조회를
주기적으로 돌린다. 도메인 모듈을 import하지 않는다. 결과는 생성자로 받은 콜백으로 낸다
(`on_db_ok(bool)`, `on_summary(dict)`, `on_correlation(dict)`). 상관분석 계산 함수
`compute_correlation(inspections, scores, cfg) -> dict`도 주입받고, 없으면 조회·계산을 건너뛴다
(docs/plan/05-storage.md 1절, D-37). psycopg를 import하는 모듈은 이 파일 하나다.
"""

from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import fields
from typing import Any, Callable

import psycopg
from psycopg.rows import dict_row

from ..clock import Clock, SystemClock
from ..log import EventLogger
from . import sql

BATCH_MAX_ROWS = 20
GET_TIMEOUT_S = 0.2
CONNECT_TIMEOUT_S = 5
STATEMENT_TIMEOUT_MS = 5000

ComputeCorrelation = Callable[[list[tuple[Any, ...]], list[tuple[Any, ...]], Any], dict]


def job_params(job: Any) -> dict[str, Any]:
    """작업 dataclass → SQL 파라미터 dict. 진동 배열은 float 목록, `bbox`는 목록, `alarm_id`는 UUID."""
    params = {f.name: getattr(job, f.name) for f in fields(job)}
    for key in ("vibration_x", "vibration_y", "vibration_z"):
        v = params.get(key)
        if v is not None and hasattr(v, "tolist"):
            params[key] = v.tolist()
    if params.get("bbox") is not None:
        params["bbox"] = list(params["bbox"])
    if job.kind == "alarm":
        params["alarm_id"] = uuid.UUID(str(params["alarm_id"]))
    return params


class DbWriter:
    """DB 스레드 하나와 연결 하나.

    `cfg`는 `config.Config`(또는 같은 속성을 가진 객체)로 `db`, `correlation`, `join`, `line`,
    `dashboard` 절을 읽는다. `counters`는 관찰용 누계(다른 스레드에서 읽기만 한다).
    """

    def __init__(
        self,
        cfg: Any,
        db_queue: "queue.Queue[Any]",
        *,
        clock: Clock | None = None,
        on_db_ok: Callable[[bool], None] | None = None,
        on_summary: Callable[[dict], None] | None = None,
        on_correlation: Callable[[dict], None] | None = None,
        compute_correlation: ComputeCorrelation | None = None,
        logger: EventLogger | None = None,
    ) -> None:
        self.cfg = cfg
        self.queue = db_queue
        self.clock = clock or SystemClock()
        self.on_db_ok = on_db_ok
        self.on_summary = on_summary
        self.on_correlation = on_correlation
        self.compute_correlation = compute_correlation
        self.log = logger or EventLogger("factory_operations.db", clock=self.clock)

        self.counters: dict[str, int] = {
            "jobs_written": 0,
            "sensor_rows_written": 0,
            "sensor_batches": 0,
            "dropped_disconnected": 0,
            "db_errors": 0,
            "connect_attempts": 0,
            "summaries": 0,
            "correlations": 0,
        }
        self._conn: psycopg.Connection | None = None
        self._db_ok = False
        self._last_connect_mono: float | None = None
        self._batch: list[dict[str, Any]] = []
        self._last_flush_mono = self.clock.mono()
        self._next_summary_mono = self.clock.mono()
        self._next_correlation_mono = self.clock.mono()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- 수명 주기 (01 7절) --------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="db", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> bool:
        """종료 표시 후 join. 스레드가 남은 센서 배치를 쓰고 연결을 닫는다. 제한 시간 안에 끝나면 True."""
        self._stop.set()
        if self._thread is None:
            return True
        self._thread.join(timeout)
        alive = self._thread.is_alive()
        if alive:
            self.log.warning("db_stop_timeout", timeout_s=timeout)
        return not alive

    @property
    def db_ok(self) -> bool:
        return self._db_ok

    def run(self) -> None:
        try:
            while not self._stop.is_set():
                self._ensure_connected()
                try:
                    job = self.queue.get(timeout=GET_TIMEOUT_S)
                except queue.Empty:
                    job = None
                if job is not None:
                    self._handle(job)
                if self._batch and (
                    len(self._batch) >= BATCH_MAX_ROWS
                    or self.clock.mono() - self._last_flush_mono >= self.cfg.db.batch_period_s
                ):
                    self._flush_batch()
                self._periodic()
            if self._batch:
                self._flush_batch()
        finally:
            self._close()

    # --- 연결 (05 3절) -------------------------------------------------------

    def _set_db_ok(self, ok: bool) -> None:
        if ok == self._db_ok:
            return
        self._db_ok = ok
        if self.on_db_ok is not None:
            try:
                self.on_db_ok(ok)
            except Exception as e:  # 콜백 오류가 DB 스레드를 멈추지 않게
                self.log.error("db_callback_error", reason="on_db_ok", error=repr(e))

    def _close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        self._set_db_ok(False)

    def _disconnect(self, where: str, err: BaseException) -> None:
        self.log.warning("db_disconnected", reason=where, error=str(err).strip())
        self._close()

    def _ensure_connected(self) -> bool:
        if self._conn is not None:
            return True
        now = self.clock.mono()
        if self._last_connect_mono is not None and now - self._last_connect_mono < self.cfg.db.reconnect_interval_s:
            return False
        self._last_connect_mono = now
        self.counters["connect_attempts"] += 1
        try:
            conn = psycopg.connect(
                self.cfg.db.url,
                autocommit=True,
                connect_timeout=CONNECT_TIMEOUT_S,
                options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            )
        except psycopg.Error as e:
            self.log.warning("db_connect_failed", reason="connect", error=str(e).strip())
            return False
        try:
            row = conn.execute(sql.SELECT_SCHEMA_VERSION).fetchone()
            version = row[0] if row else None
        except psycopg.Error as e:
            version = None
            detail = str(e).strip()
        else:
            detail = f"version={version}"
        if version != sql.SCHEMA_VERSION:
            self.log.error("db_schema_missing", reason="schema_info", detail=detail, expected=sql.SCHEMA_VERSION)
            try:
                conn.close()
            except Exception:
                pass
            return False
        self._conn = conn
        self.log.info("db_connected")
        self._set_db_ok(True)
        return True

    def _on_error(self, where: str, err: psycopg.Error) -> None:
        """OperationalError이거나 연결이 깨졌으면 재연결 경로, 아니면 db_error 로그 후 버린다."""
        conn = self._conn
        if isinstance(err, psycopg.OperationalError) or conn is None or conn.broken or conn.closed:
            self._disconnect(where, err)
        else:
            self.counters["db_errors"] += 1
            self.log.warning("db_error", reason=where, error=str(err).strip())

    # --- 작업 (05 2절) -------------------------------------------------------

    def _drop(self, n: int, kind: str) -> None:
        self.counters["dropped_disconnected"] += n
        self.log.warning("db_job_dropped", reason="disconnected", kind=kind, count=n)

    def _handle(self, job: Any) -> None:
        kind = getattr(job, "kind", None)
        if kind not in sql.JOB_SQL:
            self.counters["db_errors"] += 1
            self.log.warning("db_error", reason="unknown_job", job_type=type(job).__name__)
            return
        if self._conn is None:
            self._drop(1, kind)
            return
        try:
            params = job_params(job)
        except Exception as e:
            self.counters["db_errors"] += 1
            self.log.warning("db_error", reason=kind, error=repr(e))
            return
        if kind == "sensor":
            self._batch.append(params)
            return
        try:
            self._conn.execute(sql.JOB_SQL[kind], params)
        except psycopg.Error as e:
            self._on_error(kind, e)
            return
        self.counters["jobs_written"] += 1

    def _flush_batch(self) -> None:
        batch, self._batch = self._batch, []
        self._last_flush_mono = self.clock.mono()
        if not batch:
            return
        if self._conn is None:
            self._drop(len(batch), "sensor")
            return
        try:
            with self._conn.transaction():
                with self._conn.cursor() as cur:
                    cur.executemany(sql.INSERT_SENSOR, batch)
        except psycopg.Error as e:
            self._on_error("sensor", e)
            return
        self.counters["sensor_batches"] += 1
        self.counters["sensor_rows_written"] += len(batch)

    # --- 주기 작업 (05 5절) --------------------------------------------------

    def _periodic(self) -> None:
        now = self.clock.mono()
        if now >= self._next_summary_mono:
            self._next_summary_mono = now + self.cfg.db.summary_period_s
            if self._db_ok and self._conn is not None:
                self._run_summary()
        if self.compute_correlation is not None and now >= self._next_correlation_mono:
            self._next_correlation_mono = now + self.cfg.correlation.period_s
            if self._db_ok and self._conn is not None:
                self._run_correlation()

    def query_summary(self) -> dict[str, Any]:
        """05 5절 네 조회(한 트랜잭션 없이 문장 네 개). 행 dict의 키는 SELECT 열 이름이다."""
        assert self._conn is not None
        dash = self.cfg.dashboard
        with self._conn.cursor(row_factory=dict_row) as cur:
            counts = cur.execute(sql.SUMMARY_COUNTS).fetchone() or {}
            inspections = cur.execute(sql.SUMMARY_INSPECTIONS, {"n_inspections": dash.recent_inspections}).fetchall()
            alarms = cur.execute(sql.SUMMARY_ALARMS, {"n_alarms": dash.recent_alarms}).fetchall()
            controls = cur.execute(sql.SUMMARY_CONTROLS, {"n_controls": dash.recent_controls}).fetchall()
        return {
            "produced": counts.get("produced", 0),
            "inspected": counts.get("inspected", 0),
            "defects": counts.get("defects", 0),
            "inspections": inspections,
            "alarms": alarms,
            "controls": controls,
            "summary_at": self.clock.wall(),
        }

    def query_correlation_rows(self) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        """상관분석 두 조회. `(timestamp, defect)` 목록과 라인 센서의 `(timestamp, anomaly_score)` 목록."""
        assert self._conn is not None
        c = self.cfg.correlation
        windowed = c.window_s is not None
        p_insp: dict[str, Any] = {}
        p_score: dict[str, Any] = {"sensor_id": self.cfg.line.sensor_id}
        if windowed:
            p_insp["w"] = float(c.window_s)
            p_score["w"] = float(c.window_s) + float(c.lag_max_s) + float(self.cfg.join.max_gap_s)
        inspections = self._conn.execute(sql.correlation_inspections_sql(windowed), p_insp).fetchall()
        scores = self._conn.execute(sql.correlation_scores_sql(windowed), p_score).fetchall()
        return inspections, scores

    def _run_summary(self) -> None:
        try:
            summary = self.query_summary()
        except psycopg.Error as e:
            self._on_error("summary", e)
            return
        self.counters["summaries"] += 1
        if self.on_summary is not None:
            try:
                self.on_summary(summary)
            except Exception as e:
                self.log.error("db_callback_error", reason="on_summary", error=repr(e))

    def _run_correlation(self) -> None:
        try:
            inspections, scores = self.query_correlation_rows()
        except psycopg.Error as e:
            self._on_error("correlation", e)
            return
        try:
            result = self.compute_correlation(inspections, scores, self.cfg)  # type: ignore[misc]
        except Exception as e:  # 계산 예외는 로그로 남기고 이전 결과를 유지한다 (04 2.3절)
            self.log.error("correlation_error", reason="compute", error=repr(e))
            return
        self.counters["correlations"] += 1
        if self.on_correlation is not None:
            try:
                self.on_correlation(result)
            except Exception as e:
                self.log.error("db_callback_error", reason="on_correlation", error=repr(e))
