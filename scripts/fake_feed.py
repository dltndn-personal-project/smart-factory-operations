"""가짜 입력: Simulator·PdM·Vision 흉내 (docs/spec/07-runtime.md 5절, DECISIONS D-35·D-44).

다른 Component 없이 Operations 화면과 Interlock 흐름을 보기 위한 개발·사람 확인용 도구다.
다른 테스트는 이 스크립트에 의존하지 않는다. `tests/unit/test_fake_feed.py`가 메시지를 파서에 넣어 본다.

    .venv/bin/python scripts/fake_feed.py [--mqtt mqtt://127.0.0.1:1883] [--prefix factory] [--seed 1]
                                          [--speed 1.0] [--start-id 1]

- 메시지를 만드는 `Feed`(시각을 인자로 받는 상태 기계)와 발행 루프(`run`)를 나눴다.
  `Feed.step(now)`은 0.1초마다, `Feed.on_command(raw, retained, now)`는 Conveyor Control을 받을 때 부른다.
  둘 다 `(topic, payload dict, qos, retain)` 목록을 돌려준다.
- Fault Level 시나리오(초, `--speed`로 배속): 0~40 → 0, 40~70 → 3, 70~160 → 6, 160~ → 9.
  `START`를 받으면 Fault Level 0으로 처음부터 다시 한다.
- Ctrl-C(SIGINT)·SIGTERM이면 Line Status `online: false`를 retain으로 발행하고 끝낸다(연결이 끊기면 같은 내용의 will).
- 형식: Shared INTERFACES(`cb6dc3c`). PdM Result·Spectrum 키 집합은 `tests/fixtures/payloads/shared_pdm_*.json`과 같다.
"""

from __future__ import annotations

import argparse
import json
import math
import queue
import random
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

SENSOR_ID = "motor01"
TICK_S = 0.1  # 센서 chunk 간격
SAMPLE_RATE_HZ = 10000
CHUNK_SAMPLES = 1000  # 0.1초
RPM = 1800.0
ROT_HZ = RPM / 60.0  # 30 Hz
BPFO_HZ = 107.54
BPFI_HZ = 162.46
FREQ_STEP_HZ = 1.0
SPECTRUM_LEN = int(500 / FREQ_STEP_HZ) + 1  # 501
PDM_WINDOW_S = 1.0
PDM_EVERY_TICKS = 5  # 0.5초
SPECTRUM_EVERY_TICKS = 10  # 1초
LINE_EVERY_TICKS = 10  # 1초
PRODUCT_EVERY_TICKS = 20  # 2초
VISION_DELAY_TICKS = 2  # 0.2초
INSPECT_LAG_S = 13.0  # 투입 → 캡처(불량 확률은 13초 전 Fault Level)
DEFECT_TYPES = ("scratch", "dent", "contamination")
MODEL_VERSION = "fake-feed"
SCENARIO = ((0.0, 0), (40.0, 3), (70.0, 6), (160.0, 9))  # (시작 초, Fault Level)

QOS = {"line": 1, "sensor": 0, "product": 1, "vision": 1, "pdm": 1, "spectrum": 0}

Message = tuple[str, dict[str, Any], int, bool]


def iso_ms(dt: datetime) -> str:
    u = dt.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (u.microsecond // 1000)


def scenario_level(scenario_s: float) -> int:
    """시나리오 시각(초)의 Fault Level."""
    level = SCENARIO[0][1]
    for start, lv in SCENARIO:
        if scenario_s >= start:
            level = lv
    return level


def target_hi(fault_level: int) -> int:
    """PdM HI 목표식 `100·(1−(f/10)^1.3)` (조율 C-19)."""
    return round(100 * (1 - (fault_level / 10) ** 1.3))


def state_of(hi: int) -> str:
    """Shared ARCHITECTURE 4.2 HI → Equipment State (80 / 60 / 40)."""
    if hi >= 80:
        return "NORMAL"
    if hi >= 60:
        return "CAUTION"
    if hi >= 40:
        return "WARNING"
    return "CRITICAL"


def defect_probability(fault_level: int) -> float:
    return 0.02 + 0.4 * (fault_level / 10) ** 1.3


class Topics:
    def __init__(self, prefix: str = "factory", sensor_id: str = SENSOR_ID):
        self.line = f"{prefix}/line/status"
        self.sensor = f"{prefix}/sensor/{sensor_id}/vibration"
        self.product = f"{prefix}/product/created"
        self.vision = f"{prefix}/vision/result"
        self.pdm = f"{prefix}/pdm/result"
        self.spectrum = f"{prefix}/pdm/spectrum"
        self.conveyor = f"{prefix}/control/conveyor"


class Feed:
    """Simulator·PdM·Vision 흉내 상태 기계. 시각은 호출자가 준다(테스트가 시간을 흘린다)."""

    def __init__(self, prefix: str = "factory", seed: int = 1, speed: float = 1.0, start_id: int = 1):
        self.topics = Topics(prefix)
        self.rng = random.Random(seed)
        self.speed = speed
        self.tick = 0
        self.elapsed = 0.0  # 실제 경과(초)
        self.running = True
        self.scenario_s = 0.0
        self.fault_level = scenario_level(0.0)
        self.run_started_at = 0.0  # 마지막 가동 시작의 elapsed. PdM은 그 뒤 1초 윈도우가 차야 낸다
        self.seq = 0
        self.next_id = start_id
        self.created = 0
        self.last_product_id: str | None = None
        self.last_command: dict[str, Any] | None = None
        self.last_chunk_ts: datetime | None = None
        self.fault_history: list[tuple[float, int]] = [(0.0, self.fault_level)]  # (elapsed, level)
        self.pending_vision: list[tuple[int, dict[str, Any]]] = []  # (보낼 tick, payload)
        self.started = False

    # ------------------------------------------------------------------
    # 메시지

    def line_status(self, now: datetime) -> Message:
        running = self.running
        payload = {
            "schema_version": 1,
            "online": True,
            "timestamp": iso_ms(now),
            "conveyor": "RUNNING" if running else "STOPPED",
            "fault_level": self.fault_level,
            "motor_rpm": RPM if running else 0.0,
            "sensor_id": SENSOR_ID,
            "production_active": running,
            "products": {
                "spawned": self.created,
                "created": self.created,
                "expired": 0,
                "in_flight": 0,
                "last_product_id": self.last_product_id,
            },
            "last_command": self.last_command,
        }
        return (self.topics.line, payload, QOS["line"], True)

    def offline(self, now: datetime) -> Message:
        return (self.topics.line, {"schema_version": 1, "online": False, "timestamp": iso_ms(now)}, QOS["line"], True)

    def _axis(self, amp: float, noise: float, phase: float) -> list[float]:
        g = self.rng.gauss
        w = 2 * math.pi * ROT_HZ / SAMPLE_RATE_HZ
        start = self.seq * CHUNK_SAMPLES
        return [round(amp * math.sin(w * (start + i) + phase) + g(0.0, noise), 4) for i in range(CHUNK_SAMPLES)]

    def sensor_chunk(self, now: datetime) -> Message:
        f = self.fault_level
        if self.running:
            amp, noise = 0.2 + 0.05 * f, 0.02 + 0.03 * f
        else:
            amp, noise = 0.0, 0.005
        payload = {
            "schema_version": 1,
            "sensor_id": SENSOR_ID,
            "timestamp": iso_ms(now),
            "seq": self.seq,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "rpm": RPM if self.running else 0.0,
            "temperature": round(38.0 + 0.4 * f + self.rng.uniform(-0.1, 0.1), 2),
            "vibration_x": self._axis(amp, noise, 0.0),
            "vibration_y": self._axis(amp * 0.8, noise, math.pi / 3),
            "vibration_z": self._axis(amp * 0.5, noise * 0.7, math.pi / 2),
        }
        self.seq += 1
        self.last_chunk_ts = now
        return (self.topics.sensor, payload, QOS["sensor"], False)

    def pdm_result(self, ts: datetime) -> Message:
        hi = max(0, min(100, target_hi(self.fault_level) + self.rng.randint(-2, 2)))
        payload = {
            "schema_version": 1,
            "sensor_id": SENSOR_ID,
            "timestamp": iso_ms(ts),
            "window_start": iso_ms(ts - timedelta(seconds=PDM_WINDOW_S)),
            "anomaly_score": round(1 - hi / 100, 4),
            "health_index": hi,
            "state": state_of(hi),
            "model_version": MODEL_VERSION,
        }
        return (self.topics.pdm, payload, QOS["pdm"], False)

    def _peaks(self, peaks: list[tuple[float, float]], floor: float) -> list[float]:
        out = [floor * (1.0 + 0.5 * self.rng.random()) for _ in range(SPECTRUM_LEN)]
        for hz, height in peaks:
            lo = int(math.floor(hz / FREQ_STEP_HZ))
            frac = hz / FREQ_STEP_HZ - lo
            for i, share in ((lo, 1 - frac), (lo + 1, frac)):
                if 0 <= i < SPECTRUM_LEN:
                    out[i] += height * share
        return [round(v, 6) for v in out]

    def pdm_spectrum(self, ts: datetime) -> Message:
        k = (self.fault_level / 10) ** 1.3
        base = [(ROT_HZ, 0.05), (2 * ROT_HZ, 0.02), (3 * ROT_HZ, 0.01), (BPFO_HZ, 0.002 + 0.03 * k)]
        env = [(BPFO_HZ * n, (0.001 + 0.02 * k) / n) for n in (1, 2, 3, 4)]
        payload: dict[str, Any] = {
            "schema_version": 1,
            "sensor_id": SENSOR_ID,
            "timestamp": iso_ms(ts),
            "window_start": iso_ms(ts - timedelta(seconds=PDM_WINDOW_S)),
            "rpm": RPM,
            "freq_step_hz": FREQ_STEP_HZ,
            "rot_hz": ROT_HZ,
            "bpfo_hz": BPFO_HZ,
            "bpfi_hz": BPFI_HZ,
        }
        for axis, gain in (("x", 1.0), ("y", 0.8), ("z", 0.5)):
            payload[f"spectrum_{axis}"] = self._peaks([(hz, h * gain) for hz, h in base], 0.0004 * gain)
        for axis, gain in (("x", 1.0), ("y", 0.8), ("z", 0.5)):
            payload[f"envelope_{axis}"] = self._peaks([(hz, h * gain) for hz, h in env], 0.0002 * gain)
        return (self.topics.spectrum, payload, QOS["spectrum"], False)

    def fault_at(self, elapsed: float) -> int:
        level = self.fault_history[0][1]
        for t, lv in self.fault_history:
            if t <= elapsed:
                level = lv
        return level

    def product(self, now: datetime) -> list[Message]:
        pid = f"P-{self.next_id:08d}"
        self.next_id += 1
        self.created += 1
        self.last_product_id = pid
        image_path = f"products/{pid}.jpg"
        created = {"schema_version": 1, "product_id": pid, "timestamp": iso_ms(now), "image_path": image_path}
        f = self.fault_at(self.elapsed - INSPECT_LAG_S)
        defect = self.rng.random() < defect_probability(f)
        vision = {
            "schema_version": 1,
            "product_id": pid,
            "timestamp": iso_ms(now),
            "defect": defect,
            "defect_type": self.rng.choice(DEFECT_TYPES) if defect else None,
            "confidence": None,
            "bbox": None,
            "image_path": image_path,
            "gradcam_path": None,
            "judgement_source": "PASS_THROUGH",
        }
        self.pending_vision.append((self.tick + VISION_DELAY_TICKS, vision))
        return [(self.topics.product, created, QOS["product"], False)]

    # ------------------------------------------------------------------
    # 진행

    def _set_fault(self, level: int) -> bool:
        if level == self.fault_level:
            return False
        self.fault_level = level
        self.fault_history.append((self.elapsed, level))
        return True

    def step(self, now: datetime) -> list[Message]:
        """0.1초 진행. 첫 호출은 Line Status로 시작한다."""
        out: list[Message] = []
        if not self.started:
            self.started = True
            out.append(self.line_status(now))
        else:
            self.tick += 1
            self.elapsed += TICK_S
            if self.running:
                self.scenario_s += TICK_S * self.speed
                if self._set_fault(scenario_level(self.scenario_s)):
                    out.append(self.line_status(now))  # 변화 즉시
        out.append(self.sensor_chunk(now))
        if self.running and self.elapsed - self.run_started_at >= PDM_WINDOW_S - 1e-9:
            if self.tick % PDM_EVERY_TICKS == 0:
                out.append(self.pdm_result(now))
            if self.tick % SPECTRUM_EVERY_TICKS == 0:
                out.append(self.pdm_spectrum(now))
        if self.running and self.tick % PRODUCT_EVERY_TICKS == 0:
            out.extend(self.product(now))
        due = [v for t, v in self.pending_vision if t <= self.tick]
        self.pending_vision = [(t, v) for t, v in self.pending_vision if t > self.tick]
        out.extend((self.topics.vision, v, QOS["vision"], False) for v in due)
        if self.tick % LINE_EVERY_TICKS == 0 and self.tick > 0:
            out.append(self.line_status(now))
        return out

    def on_command(self, raw: bytes, retained: bool, now: datetime) -> list[Message]:
        """Conveyor Control 적용 → `last_command`를 실은 Line Status를 즉시 돌려준다(SIM A-11·A-12 흉내)."""
        result: dict[str, Any] = {
            "command": None,
            "command_id": None,
            "source": "mqtt",
            "received_at": iso_ms(now),
            "result": "REJECTED",
            "reason": None,
            "error": None,
        }
        try:
            msg = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            msg = None
        if not isinstance(msg, dict):
            result["error"] = "invalid_json"
        else:
            command = msg.get("command")
            command_id = msg.get("command_id")
            reason = msg.get("reason")
            result["command"] = command if command in ("START", "STOP") else None
            result["reason"] = reason if isinstance(reason, str) else None
            if retained:
                result["error"] = "retained_ignored"  # command_id는 null(Operations 03 3.4절)
            elif msg.get("schema_version") != 1:
                result["error"] = "invalid_field:schema_version"
            elif command not in ("START", "STOP"):
                result["error"] = "invalid_field:command"
            elif not isinstance(command_id, str) or not command_id:
                result["error"] = "missing_field:command_id"
            else:
                result["command_id"] = command_id
                if command == "STOP":
                    result["result"] = "APPLIED" if self.running else "NO_CHANGE"
                    self.running = False
                elif self.running:
                    result["result"] = "NO_CHANGE"
                else:
                    result["result"] = "APPLIED"
                    self.running = True
                    self.run_started_at = self.elapsed
                    self.scenario_s = 0.0
                    self._set_fault(scenario_level(0.0))
        self.last_command = result
        return [self.line_status(now)]


# ---------------------------------------------------------------------------
# 발행 루프


def run(args: argparse.Namespace) -> int:
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion

    url = urlparse(args.mqtt)
    host, port = url.hostname or "127.0.0.1", url.port or 1883
    feed = Feed(prefix=args.prefix, seed=args.seed, speed=args.speed, start_id=args.start_id)
    commands: queue.Queue = queue.Queue()
    stop = threading.Event()

    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=f"fake-feed-{random.getrandbits(32):08x}",
        protocol=MQTTProtocolVersion.MQTTv311,
        clean_session=True,
    )
    will_topic, will_payload, _, _ = feed.offline(datetime.now(timezone.utc))
    client.will_set(will_topic, json.dumps(will_payload), qos=1, retain=True)

    def on_connect(c: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        if not reason_code.is_failure:
            c.subscribe(feed.topics.conveyor, qos=1)
            print(f"fake_feed: connected to {host}:{port}", flush=True)

    def on_message(c: Any, userdata: Any, msg: Any) -> None:
        commands.put((bytes(msg.payload), bool(msg.retain)))

    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=5)

    def handle_signal(signum: int, frame: Any) -> None:
        stop.set()

    # 백그라운드 실행에서 SIGINT가 무시(SIG_IGN)로 물려받아져도 끝낼 수 있게 직접 둔다
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    client.connect_async(host, port, keepalive=30)
    client.loop_start()

    def publish(messages: list[Message]) -> None:
        for topic, payload, qos, retain in messages:
            client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=qos, retain=retain)

    next_t = time.monotonic()
    last_level = None
    try:
        while not stop.is_set():
            now = datetime.now(timezone.utc)
            while True:
                try:
                    raw, retained = commands.get_nowait()
                except queue.Empty:
                    break
                publish(feed.on_command(raw, retained, now))
                lc = feed.last_command or {}
                print(f"fake_feed: command {lc.get('command')} -> {lc.get('result')} {lc.get('error') or ''}", flush=True)
            publish(feed.step(now))
            if feed.fault_level != last_level:
                last_level = feed.fault_level
                print(f"fake_feed: fault_level {last_level} ({'RUNNING' if feed.running else 'STOPPED'})", flush=True)
            next_t += TICK_S
            delay = next_t - time.monotonic()
            if delay > 0:
                stop.wait(delay)
            else:
                next_t = time.monotonic()  # 밀리면 따라잡지 않고 다시 맞춘다
    finally:
        topic, payload, qos, retain = feed.offline(datetime.now(timezone.utc))
        info = client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        try:
            info.wait_for_publish(timeout=2.0)
        except (RuntimeError, ValueError):
            pass
        client.disconnect()
        client.loop_stop()
        print("fake_feed: stopped (Line Status offline)", flush=True)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="fake_feed.py", description="Simulator·PdM·Vision 흉내 입력(개발·사람 확인용)")
    p.add_argument("--mqtt", default="mqtt://127.0.0.1:1883", help="broker URL (기본 mqtt://127.0.0.1:1883)")
    p.add_argument("--prefix", default="factory", help="Topic 접두사 (기본 factory)")
    p.add_argument("--seed", type=int, default=1, help="난수 seed (기본 1)")
    p.add_argument("--speed", type=float, default=1.0, help="Fault Level 시나리오 배속 (기본 1.0)")
    p.add_argument("--start-id", type=int, default=1, help="첫 product_id 번호 (기본 1)")
    args = p.parse_args(argv)
    if args.speed <= 0:
        p.error("--speed must be > 0")
    if args.start_id < 1:
        p.error("--start-id must be >= 1")
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args()))
