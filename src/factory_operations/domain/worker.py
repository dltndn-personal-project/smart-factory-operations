"""도메인 워커의 처리 함수 `Processor` (docs/spec/03-control.md 2~4절, 01-core.md 2절).

스레드·큐 없이 직접 부를 수 있다(시나리오 테스트가 이것을 부른다). 워커 스레드 루프(큐에서 꺼내기,
0.1초 `tick`, 종료)는 `Worker`다(01 2절).

- 입력: `Inbound`(paho가 넣은 원시 메시지) 또는 `OperatorCommand`(HTTP).
- 출력: `publisher.publish(topic, payload: bytes, qos, retain) -> bool`, `db_sink.put_nowait(job)`,
  StateStore 쓰기, 로그.
"""

from __future__ import annotations

import queue
import threading
from collections import OrderedDict
from concurrent.futures import Future, InvalidStateError
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from ..clock import Clock, iso_ms
from ..log import EventLogger
from ..mqtt import payloads as P
from ..mqtt import topics as T
from ..store import jobs as J
from .alarm import AlarmManager
from .interlock import Interlock
from .join import health_index_at_time
from .line import LineTracker
from .state import StateStore

ISSUED_MAX = 100  # 최근 발행한 명령 수(03 3.4절)
SEEN_MAX = 200  # 결과를 처리한 command_id 수
PAYLOAD_LOG_BYTES = 200

REASON_INTERLOCK = "INTERLOCK_CRITICAL"
OPERATOR_REASONS = {"START": "OPERATOR_START", "STOP": "OPERATOR_STOP"}


@dataclass(frozen=True)
class Inbound:
    """paho `on_message`가 inbound 큐에 넣는 항목(01 2절). 파싱은 워커에서 한다."""

    topic: str
    payload: bytes
    retain: bool
    recv_wall: datetime
    recv_mono: float


@dataclass(frozen=True)
class OperatorCommand:
    """`POST /api/conveyor`가 inbound 큐에 넣는 항목(03 3.3절). 워커가 `future`에 결과를 넣는다."""

    command: str  # START | STOP
    future: Future


class OperatorCommandError(Exception):
    """운영자 명령 실패. `code`: `mqtt_disconnected` | `invalid_command`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Publisher(Protocol):
    def publish(self, topic: str, payload: bytes, qos: int = 1, retain: bool = False) -> bool: ...


class DbSink(Protocol):
    def put_nowait(self, job: Any) -> None: ...


class _Bounded(OrderedDict):
    """오래된 것부터 버리는 크기 제한 사전."""

    def __init__(self, maxlen: int):
        super().__init__()
        self.maxlen = maxlen

    def add(self, key: str, value: Any = True) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.maxlen:
            self.popitem(last=False)


class Processor:
    def __init__(
        self,
        cfg: Any,
        state: StateStore,
        publisher: Publisher,
        db_sink: DbSink,
        clock: Clock,
        topics: T.Topics | None = None,
        log: EventLogger | None = None,
    ):
        self.state = state
        self.publisher = publisher
        self.db_sink = db_sink
        self.clock = clock
        self.topics = topics or T.Topics(cfg.mqtt.topic_prefix)
        self.log = log or EventLogger("factory_operations.worker", clock=clock)
        self.max_gap_s = cfg.join.max_gap_s
        self.line = LineTracker(cfg.line.sensor_id)
        self.interlock = Interlock(cfg.interlock.pending_timeout_s)
        self.alarms = AlarmManager()
        self.issued: _Bounded = _Bounded(ISSUED_MAX)
        self.seen: _Bounded = _Bounded(SEEN_MAX)
        self.state.set_line(self.line.view())
        self.state.set_interlock(self.interlock.view())

    # ------------------------------------------------------------------
    # 진입점

    def handle(self, item: Inbound | OperatorCommand) -> None:
        if isinstance(item, OperatorCommand):
            self.handle_operator(item)
        else:
            self.handle_inbound(item)

    def handle_inbound(self, inb: Inbound) -> None:
        match = self.topics.kind_of(inb.topic)
        if match is None:
            self._drop(inb, "unknown_topic")
            return
        parsed = P.parse(match.kind, inb.topic, inb.payload)
        if isinstance(parsed, P.Rejected):
            self._drop(inb, parsed.reason)
            return
        nulled = getattr(parsed, "nulled", ())
        if nulled:
            self.log.debug("optional_fields_nulled", topic=inb.topic, fields=list(nulled))
        wall, mono = inb.recv_wall, inb.recv_mono
        if match.kind == T.SENSOR_VIBRATION:
            self._on_sensor(parsed, wall, mono)
        elif match.kind == T.LINE_STATUS:
            self._on_line(parsed, wall, mono)
        elif match.kind == T.PRODUCT_CREATED:
            self._put(J.ProductJob(parsed.product_id, parsed.timestamp, parsed.image_path, wall))
        elif match.kind == T.VISION_RESULT:
            self._on_vision(parsed, wall)
        elif match.kind == T.PDM_RESULT:
            self._on_pdm(parsed, wall, mono)
        elif match.kind == T.PDM_SPECTRUM:
            if parsed.sensor_id == self.line.line_sensor_id:
                self.state.set_spectrum(parsed, wall, mono)

    def tick(self) -> None:
        """0.1초마다: 대기 중 STOP 시간 초과. 끝났으면 바로 평가한다(3.2절)."""
        if self._expire():
            self._try_stop()
        self._publish_interlock_view()

    # ------------------------------------------------------------------
    # 메시지별 처리 (2절 표)

    def _on_sensor(self, c: P.SensorChunk, wall: datetime, mono: float) -> None:
        self._put(
            J.SensorJob(
                c.sensor_id,
                c.timestamp,
                c.seq,
                c.sample_rate_hz,
                c.rpm,
                c.temperature,
                c.x,
                c.y,
                c.z,
                self.line.fault_level_at(c.timestamp),
                wall,
            )
        )
        if c.sensor_id != self.line.line_sensor_id:
            return
        last = self.state.last_vibration()
        reset = False
        if last is not None:
            prev: P.SensorChunk = last.value
            reset = (
                prev.sensor_id != c.sensor_id
                or prev.sample_rate_hz != c.sample_rate_hz
                or len(prev.x) != len(c.x)
                or c.seq != prev.seq + 1
            )
        self.state.add_vibration(c, wall, mono, reset=reset)

    def _on_line(self, msg: P.LineStatus | P.LineOffline, wall: datetime, mono: float) -> None:
        upd = self.line.update(msg, wall, mono)
        self.state.set_line(self.line.view())
        if upd.record_change:
            if isinstance(msg, P.LineOffline):
                self._put(J.LineChangeJob(wall, None, False, None, None, None, None, None))
            else:
                self._put(
                    J.LineChangeJob(
                        wall,
                        msg.timestamp,
                        True,
                        msg.conveyor,
                        msg.fault_level,
                        msg.motor_rpm,
                        msg.production_active,
                        msg.sensor_id,
                    )
                )
        if upd.restart:
            self.alarms.reset(self.line.line_sensor_id)
        if upd.reference_changed:
            self.interlock.on_reference_changed(self.line.reference_time)
        if isinstance(msg, P.LineStatus):
            self._check_command_result(msg.last_command)
        self._evaluate()

    def _on_vision(self, v: P.VisionResult, wall: datetime) -> None:
        sensor = self.line.line_sensor_id
        h = health_index_at_time(v.timestamp, self.state.pdm_history(sensor), self.max_gap_s, sensor)
        self._put(
            J.InspectionJob(
                v.product_id,
                v.timestamp,
                v.defect,
                v.defect_type,
                v.confidence,
                v.bbox,
                v.image_path,
                v.gradcam_path,
                v.judgement_source,
                h.sensor_id,
                h.health_index,
                h.anomaly_score,
                h.pdm_timestamp,
                wall,
            )
        )

    def _on_pdm(self, r: P.PdmResult, wall: datetime, mono: float) -> None:
        self.state.add_pdm(r, wall, mono)
        self._put(
            J.EquipmentJob(r.sensor_id, r.timestamp, r.window_start, r.anomaly_score, r.health_index, r.state, r.model_version, wall)
        )
        is_line = r.sensor_id == self.line.line_sensor_id
        ref = self.line.reference_time
        judged_target = is_line and (ref is None or r.timestamp > ref)
        if judged_target or not is_line:  # Alarm 대상
            self._on_alarm(self.alarms.evaluate(r, self.clock.wall()))
        if judged_target:
            self.interlock.observe(r)
            self._evaluate()
        else:
            self._publish_interlock_view()

    # ------------------------------------------------------------------
    # Alarm (4절)

    def _on_alarm(self, alarm: P.Alarm | None) -> None:
        if alarm is None:
            return
        self._put(
            J.AlarmJob(
                alarm.alarm_id,
                alarm.timestamp,
                alarm.raised_at,
                alarm.sensor_id,
                alarm.severity,
                alarm.previous_state,
                alarm.health_index,
                alarm.anomaly_score,
            )
        )
        ok = self.publisher.publish(self.topics.alarm, P.serialize(P.build_alarm(alarm)), T.ALARM_QOS, T.ALARM_RETAIN)
        if not ok:
            self.log.warning("alarm_publish_skipped", alarm_id=alarm.alarm_id, reason="mqtt_disconnected", throttle=False)
        self.log.info(
            "alarm_raised",
            alarm_id=alarm.alarm_id,
            sensor_id=alarm.sensor_id,
            severity=alarm.severity,
            previous_state=alarm.previous_state,
            published=ok,
        )

    # ------------------------------------------------------------------
    # Interlock (3.2절)

    def _expire(self) -> bool:
        p = self.interlock.expire(self.clock.mono())
        if p is not None:
            self.log.warning("interlock_pending_timeout", command_id=p.command_id, throttle=False)
            return True
        return False

    def _evaluate(self) -> None:
        self._expire()
        self._try_stop()
        self._publish_interlock_view()

    def _try_stop(self) -> None:
        if not self.interlock.should_stop(self.line.line_state):
            return
        command_id = P.new_command_id()
        now = self.clock.wall()
        payload = P.build_conveyor("STOP", command_id, REASON_INTERLOCK, now)
        if not self.publisher.publish(self.topics.conveyor, P.serialize(payload), T.CONVEYOR_QOS, T.CONVEYOR_RETAIN):
            self.log.warning("interlock_publish_skipped", reason="mqtt_disconnected")
            return
        trigger = self.interlock.issued(command_id, self.clock.mono())
        self.issued.add(command_id, "STOP")
        self._put(
            J.ControlIssuedJob(command_id, "STOP", REASON_INTERLOCK, now, trigger.sensor_id, trigger.timestamp, self.clock.wall())
        )
        self.log.info(
            "command_published",
            command_id=command_id,
            command="STOP",
            reason_code=REASON_INTERLOCK,
            trigger_timestamp=iso_ms(trigger.timestamp),
        )

    def _publish_interlock_view(self) -> None:
        self.state.set_interlock(self.interlock.view())

    # ------------------------------------------------------------------
    # 운영자 명령 (3.3절)

    def handle_operator(self, cmd: OperatorCommand) -> None:
        if cmd.command not in OPERATOR_REASONS:
            _complete(cmd.future, exc=OperatorCommandError("invalid_command"))
            return
        reason = OPERATOR_REASONS[cmd.command]
        command_id = P.new_command_id()
        now = self.clock.wall()
        payload = P.build_conveyor(cmd.command, command_id, reason, now)
        if not self.publisher.publish(self.topics.conveyor, P.serialize(payload), T.CONVEYOR_QOS, T.CONVEYOR_RETAIN):
            _complete(cmd.future, exc=OperatorCommandError("mqtt_disconnected"))
            return
        self.issued.add(command_id, cmd.command)
        self._put(J.ControlIssuedJob(command_id, cmd.command, reason, now, None, None, self.clock.wall()))
        self.log.info("command_published", command_id=command_id, command=cmd.command, reason_code=reason)
        judged = self.interlock.judged
        _complete(
            cmd.future,
            {
                "command_id": command_id,
                "command": cmd.command,
                "timestamp": payload["timestamp"],
                "judged_state": judged.state if judged is not None else None,
            },
        )

    # ------------------------------------------------------------------
    # 명령 결과 확인 (3.4절)

    def _check_command_result(self, lc: P.LastCommand | None) -> None:
        if lc is None:
            return
        if lc.command_id is None:
            self.log.warning("command_result_without_id", reason=lc.error or lc.result, result=lc.result)
            return
        if lc.command_id in self.seen:
            return
        now = self.clock.wall()
        if lc.command_id in self.issued:
            self._put(J.ControlResultJob(lc.command_id, lc.result, lc.received_at, lc.error, now))
            level = self.log.error if lc.result == "REJECTED" else self.log.info
            level("command_result", command_id=lc.command_id, result=lc.result, error=lc.error, throttle=False)
            self.interlock.on_result(lc.command_id, lc.result)
        else:
            self._put(
                J.ControlObservedJob(
                    lc.command_id, lc.command, lc.reason, lc.source, lc.result, lc.received_at, lc.error, now, now
                )
            )
        self.seen.add(lc.command_id)

    # ------------------------------------------------------------------
    # 공통

    def _put(self, job: Any) -> None:
        try:
            self.db_sink.put_nowait(job)
        except queue.Full:
            self.state.incr(("db_queue_overflow", job.kind))
            self.log.warning("queue_overflow", queue="db", reason=job.kind)

    def _drop(self, inb: Inbound, reason: str) -> None:
        self.state.incr(("rejected", inb.topic, reason))
        self.log.warning(
            "message_rejected",
            topic=inb.topic,
            reason=reason,
            payload=bytes(inb.payload[:PAYLOAD_LOG_BYTES]),
        )


def _complete(f: Future, value: Any = None, exc: BaseException | None = None) -> None:
    """HTTP가 이미 포기(취소)한 future는 건드리지 않는다."""
    if f.done():
        return
    try:
        if exc is not None:
            f.set_exception(exc)
        else:
            f.set_result(value)
    except InvalidStateError:
        pass


# ---------------------------------------------------------------------------
# 워커 스레드 (01 2절)

TICK_S = 0.1


class Worker:
    """도메인 워커 스레드 하나. inbound 큐에서 `get(timeout≤0.1)`로 꺼내 `Processor.handle`에 넘기고,
    꺼낸 것이 없어도 0.1초마다 `Processor.tick`을 부른다. 처리 중 예외는 로그만 남기고 계속한다."""

    def __init__(self, processor: Processor, inbound: "queue.Queue[Any]", *, tick_s: float = TICK_S, log: EventLogger | None = None):
        self.processor = processor
        self.inbound = inbound
        self.tick_s = tick_s
        self.clock = processor.clock
        self.log = log or processor.log
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self.run, name="worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> bool:
        """종료 표시 후 join. 제한 시간 안에 끝나면 True(01 7절)."""
        self._stop.set()
        if self._thread is None:
            return True
        self._thread.join(timeout)
        alive = self._thread.is_alive()
        if alive:
            self.log.warning("worker_stop_timeout", timeout_s=timeout)
        return not alive

    def run(self) -> None:
        next_tick = self.clock.mono() + self.tick_s
        while not self._stop.is_set():
            wait = max(0.0, min(self.tick_s, next_tick - self.clock.mono()))
            try:
                item = self.inbound.get(timeout=wait)
            except queue.Empty:
                item = None
            if item is not None:
                self._safe(self.processor.handle, item)
            now = self.clock.mono()
            if now >= next_tick:
                self._safe(self.processor.tick)
                next_tick = now + self.tick_s

    def _safe(self, fn: Any, *args: Any) -> None:
        try:
            fn(*args)
        except Exception as e:
            self.log.error("worker_error", reason=getattr(fn, "__name__", "call"), error=repr(e))
            if args and isinstance(args[0], OperatorCommand):
                _complete(args[0].future, exc=e)
