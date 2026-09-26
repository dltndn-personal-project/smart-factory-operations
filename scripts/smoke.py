"""컨테이너 smoke (docs/spec/08-verification.md 3.7절, 조율 C-09).

이 저장소 Dockerfile로 이미지를 만들고 Mosquitto·TimescaleDB·Image Storage(읽기 전용 볼륨)와 함께 띄워
컨테이너 안의 앱이 입력을 받고 Alarm·STOP을 발행하며 DB에 기록하는지 본다.

`make smoke` = `.venv/bin/python scripts/smoke.py`. 성공이면 종료 코드 0, 실패면 Operations 컨테이너 로그
마지막 100줄을 출력하고 종료 코드 1. 성공·실패와 무관하게 만든 컨테이너·network·volume을 id·이름으로 지운다.

- 이미지: `factory-operations:smoke-<commit 12자리>`(D-45). 다음 검사(A4)가 쓰므로 지우지 않는다.
- 이름: network `fops-smoke-<hex8>`, volume `fops-smoke-img-<hex8>`, 컨테이너 `factory-operations-fops-smoke-<hex8>-<역할>`.
- 호스트 포트: 모두 `-p 127.0.0.1::<port>`(Docker 임의 포트, 재시작 없음).
- PdM 메시지: `tests/fixtures/payloads/pdm.py`를 파일 경로로 불러온다(D-39).
"""

from __future__ import annotations

import importlib.util
import json
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion

REPO = Path(__file__).resolve().parents[1]
SEED_DIR = REPO / "tests" / "fixtures" / "images"
SCHEMA_SQL = REPO / "db" / "schema.sql"
PDM_HELPER = REPO / "tests" / "fixtures" / "payloads" / "pdm.py"

MOSQUITTO_IMAGE = "eclipse-mosquitto:2.1.2-alpine"
TIMESCALE_IMAGE = "timescale/timescaledb:2.30.1-pg17"
DB_USER = DB_PASSWORD = DB_NAME = "factory"

DB_READY_TIMEOUT_S = 60.0
READYZ_TIMEOUT_S = 30.0
READYZ_INTERVAL_S = 0.5
INTERLOCK_TIMEOUT_S = 2.0
SNAPSHOT_TIMEOUT_S = 5.0
DB_ROWS_TIMEOUT_S = 5.0

# Topic(기본 접두사 factory, Shared INTERFACES)
T_LINE = "factory/line/status"
T_PDM = "factory/pdm/result"
T_PRODUCT = "factory/product/created"
T_VISION = "factory/vision/result"
T_CONVEYOR = "factory/control/conveyor"
T_ALARM = "factory/alarm/event"

ALARM_KEYS = {
    "schema_version",
    "alarm_id",
    "timestamp",
    "raised_at",
    "sensor_id",
    "severity",
    "previous_state",
    "health_index",
    "anomaly_score",
}  # A-02
STOP_KEYS = {"schema_version", "command", "command_id", "timestamp", "reason"}  # A-03 (Shared Conveyor Control)

# 같은 seed 방식(07 4절 image-seed): 예시 8장을 P-00000001~300 이름으로 복사
SEED_SCRIPT = (
    "mkdir -p /data/products /data/gradcam; i=1; while [ $i -le 300 ]; do k=$(( (i - 1) % 8 + 1 )); "
    "cp /seed/P-0000000$k.jpg $(printf /data/products/P-%08d.jpg $i); i=$((i + 1)); done"
)


class SmokeFailure(Exception):
    pass


def log(msg: str) -> None:
    print(f"[smoke {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(*args: str, check: bool = True, timeout: float = 120.0, capture: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(list(args), capture_output=capture, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise SmokeFailure(f"command failed ({p.returncode}): {' '.join(args)}\n{p.stdout or ''}{p.stderr or ''}")
    return p


def docker(*args: str, **kw: Any) -> subprocess.CompletedProcess:
    return run("docker", *args, **kw)


def git(*args: str) -> str:
    return run("git", "-C", str(REPO), *args).stdout.strip()


def iso_ms(dt: datetime) -> str:
    u = dt.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (u.microsecond // 1000)


def now_ms() -> datetime:
    t = datetime.now(timezone.utc)
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


def load_pdm_helper() -> Any:
    spec = importlib.util.spec_from_file_location("fops_smoke_pdm", PDM_HELPER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def host_port(container_id: str, port: int) -> int:
    """`docker port <id> <port>/tcp`의 127.0.0.1 호스트 포트."""
    out = docker("port", container_id, f"{port}/tcp").stdout.split()
    for line in out:
        host, _, p = line.rpartition(":")
        if host in ("127.0.0.1", "0.0.0.0") and p.isdigit():
            return int(p)
    raise SmokeFailure(f"no host port for {container_id[:12]} {port}: {out}")


def http_get(url: str, timeout: float = 2.0) -> tuple[int, dict[str, str], bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def wait_until(pred: Callable[[], Any], timeout: float, interval: float, what: str) -> Any:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while True:
        try:
            v = pred()
            if v:
                return v
        except Exception as e:  # noqa: BLE001 - 연결 거부 등은 다시 시도
            last_err = e
        if time.monotonic() >= deadline:
            raise SmokeFailure(f"timeout ({timeout:g}s): {what}" + (f" (last error: {last_err})" if last_err else ""))
        time.sleep(interval)


# ---------------------------------------------------------------------------
# harness


class Harness:
    """paho client. 구독은 SUBACK까지, QoS 1 발행은 PUBACK까지 기다린다. 수신은 (mono, topic, dict)."""

    def __init__(self, port: int):
        self.messages: list[tuple[float, str, dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._subacks: dict[int, threading.Event] = {}
        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"fops-smoke-harness-{secrets.token_hex(4)}",
            protocol=MQTTProtocolVersion.MQTTv311,
            clean_session=True,
        )
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.client.connect("127.0.0.1", port, keepalive=30)
        self.client.loop_start()
        wait_until(self.client.is_connected, 10.0, 0.05, "harness MQTT connect")

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload = json.loads(msg.payload)
        except ValueError:
            payload = {"_raw": bytes(msg.payload).decode(errors="replace")}
        with self._lock:
            self.messages.append((time.monotonic(), msg.topic, payload))

    def _on_subscribe(self, client: Any, userdata: Any, mid: int, reason_codes: Any, properties: Any = None) -> None:
        self._subacks.setdefault(mid, threading.Event()).set()

    def subscribe(self, topic: str) -> None:
        rc, mid = self.client.subscribe(topic, 1)
        if rc != mqtt.MQTT_ERR_SUCCESS or not self._subacks.setdefault(mid, threading.Event()).wait(5.0):
            raise SmokeFailure(f"subscribe failed: {topic}")

    def publish(self, topic: str, payload: dict[str, Any] | bytes, retain: bool = False) -> None:
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()
        info = self.client.publish(topic, raw, qos=1, retain=retain)
        info.wait_for_publish(timeout=5.0)
        if not info.is_published():
            raise SmokeFailure(f"no PUBACK for {topic}")

    def first(self, topic: str, pred: Callable[[dict[str, Any]], bool] = lambda m: True):
        with self._lock:
            for t, tp, m in self.messages:
                if tp == topic and pred(m):
                    return t, m
        return None

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()


# ---------------------------------------------------------------------------
# 메시지 (Shared INTERFACES)


def line_status(ts: datetime, conveyor: str, fault: int, last_command: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "online": True,
        "timestamp": iso_ms(ts),
        "conveyor": conveyor,
        "fault_level": fault,
        "motor_rpm": 1800.0 if conveyor == "RUNNING" else 0.0,
        "sensor_id": "motor01",
        "production_active": conveyor == "RUNNING",
        "products": {"spawned": 1, "created": 1, "expired": 0, "in_flight": 0, "last_product_id": "P-00000001"},
        "last_command": last_command,
    }


# ---------------------------------------------------------------------------


class Smoke:
    def __init__(self) -> None:
        self.suffix = secrets.token_hex(4)
        self.commit = git("rev-parse", "HEAD")
        self.image = f"factory-operations:smoke-{git('rev-parse', '--short=12', 'HEAD')}"
        self.network = f"fops-smoke-{self.suffix}"
        self.volume = f"fops-smoke-img-{self.suffix}"
        self.containers: list[str] = []  # 만든 순서
        self.app_id: str | None = None
        self.db_id: str | None = None
        self.networks: list[str] = []
        self.volumes: list[str] = []

    def name(self, role: str) -> str:
        return f"factory-operations-fops-smoke-{self.suffix}-{role}"

    # 1
    def build(self) -> None:
        log(f"build {self.image} (GIT_COMMIT={self.commit})")
        t0 = time.monotonic()
        p = docker("build", "-t", self.image, "--build-arg", f"GIT_COMMIT={self.commit}", str(REPO), check=False, timeout=1200)
        if p.returncode != 0:
            raise SmokeFailure(f"docker build failed\n{p.stdout[-3000:]}{p.stderr[-3000:]}")
        log(f"build time {time.monotonic() - t0:.1f}s")

    # 2
    def seed(self) -> None:
        docker("network", "create", self.network)
        self.networks.append(self.network)
        docker("volume", "create", self.volume)
        self.volumes.append(self.volume)
        name = self.name("seed")
        p = docker(
            "run", "--name", name,
            "-v", f"{self.volume}:/data",
            "-v", f"{SEED_DIR}:/seed:ro",
            MOSQUITTO_IMAGE, "sh", "-c", SEED_SCRIPT,
            check=False, timeout=120,
        )  # fmt: skip
        cid = docker("ps", "-aq", "--no-trunc", "--filter", f"name=^/{name}$").stdout.strip()
        if cid:
            self.containers.append(cid)
        if p.returncode != 0:
            raise SmokeFailure(f"image seed failed\n{p.stdout}{p.stderr}")
        log(f"network {self.network}, volume {self.volume} seeded")

    # 3
    def infra(self) -> None:
        mq = docker(
            "run", "-d", "--name", self.name("mqtt"),
            "--network", self.network, "--network-alias", "mosquitto",
            "-p", "127.0.0.1::1883",
            MOSQUITTO_IMAGE, "mosquitto", "-c", "/mosquitto-no-auth.conf",
        ).stdout.strip()  # fmt: skip
        self.containers.append(mq)
        self.mqtt_port = host_port(mq, 1883)
        db = docker(
            "run", "-d", "--name", self.name("db"),
            "--network", self.network, "--network-alias", "db",
            "-e", f"POSTGRES_USER={DB_USER}", "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}", "-e", f"POSTGRES_DB={DB_NAME}",
            "-v", f"{SCHEMA_SQL}:/docker-entrypoint-initdb.d/100_factory_operations.sql:ro",
            TIMESCALE_IMAGE,
        ).stdout.strip()  # fmt: skip
        self.containers.append(db)
        self.db_id = db
        t0 = time.monotonic()
        wait_until(
            lambda: docker("exec", db, "pg_isready", "-h", "127.0.0.1", "-U", DB_USER, "-d", DB_NAME, check=False).returncode == 0,
            DB_READY_TIMEOUT_S,
            0.5,
            "pg_isready",
        )
        log(f"mosquitto 127.0.0.1:{self.mqtt_port}, db ready in {time.monotonic() - t0:.1f}s")

    # 4
    def app(self) -> None:
        cid = docker(
            "run", "-d", "--name", self.name("app"),
            "--network", self.network,
            "-e", "MQTT_URL=mqtt://mosquitto:1883",
            "-e", f"DATABASE_URL=postgresql://{DB_USER}:{DB_PASSWORD}@db:5432/{DB_NAME}",
            "-v", f"{self.volume}:/data:ro",
            "-p", "127.0.0.1::8080",
            self.image,
        ).stdout.strip()  # fmt: skip
        started = time.monotonic()  # docker run이 끝난 시각
        self.containers.append(cid)
        self.app_id = cid
        self.base = f"http://127.0.0.1:{host_port(cid, 8080)}"
        wait_until(lambda: http_get(self.base + "/readyz", timeout=1.0)[0] == 200, READYZ_TIMEOUT_S, READYZ_INTERVAL_S, "/readyz 200")
        elapsed = time.monotonic() - started
        if elapsed > READYZ_TIMEOUT_S:
            raise SmokeFailure(f"/readyz took {elapsed:.1f}s > {READYZ_TIMEOUT_S:g}s")
        status, _, body = http_get(self.base + "/healthz")
        health = json.loads(body)
        if status != 200 or health.get("commit") != self.commit:
            raise SmokeFailure(f"/healthz {status} commit {health.get('commit')!r} != {self.commit!r}")
        log(f"app {self.base}: /readyz 200 after {elapsed:.1f}s, /healthz commit ok")

    def snapshot(self) -> dict[str, Any]:
        status, _, body = http_get(self.base + "/api/snapshot")
        if status != 200:
            raise SmokeFailure(f"/api/snapshot {status}")
        return json.loads(body)

    def psql(self, sql: str) -> str:
        return docker("exec", self.db_id, "psql", "-U", DB_USER, "-d", DB_NAME, "-tAc", sql).stdout.strip()

    # 5, 6
    def flow(self) -> None:
        pdm = load_pdm_helper()
        h = Harness(self.mqtt_port)
        try:
            h.subscribe(T_CONVEYOR)
            h.subscribe(T_ALARM)
            t0 = now_ms()
            h.publish(T_LINE, line_status(t0, "RUNNING", 9), retain=True)
            wait_until(
                lambda: (s := self.snapshot())["line"].get("fault_level") == 9 and s["interlock"]["reference_time"] == iso_ms(t0),
                SNAPSHOT_TIMEOUT_S,
                0.1,
                "Line Status RUNNING fault_level 9 in snapshot",
            )

            pdm_ts = t0 + timedelta(seconds=1)
            h.publish(T_PDM, pdm.to_bytes(pdm.pdm_result("motor01", pdm_ts, "CRITICAL", 12, 0.88)))
            sent = time.monotonic()

            def both():
                a = h.first(T_ALARM, lambda m: m.get("severity") == "CRITICAL")
                c = h.first(T_CONVEYOR, lambda m: m.get("command") == "STOP")
                return (a, c) if a and c else None

            (ta, alarm), (tc, stop) = wait_until(both, INTERLOCK_TIMEOUT_S, 0.02, "Alarm Event and STOP after CRITICAL")
            if set(alarm) != ALARM_KEYS or alarm["timestamp"] != iso_ms(pdm_ts) or alarm["sensor_id"] != "motor01":
                raise SmokeFailure(f"Alarm Event fields: {alarm}")
            if set(stop) != STOP_KEYS or stop["reason"] != "INTERLOCK_CRITICAL" or stop["schema_version"] != 1:
                raise SmokeFailure(f"STOP fields: {stop}")
            log(f"CRITICAL -> Alarm {ta - sent:.3f}s, STOP {tc - sent:.3f}s")

            t1 = now_ms()
            result = {
                "command": "STOP",
                "command_id": stop["command_id"],
                "source": "mqtt",
                "received_at": iso_ms(t1),
                "result": "APPLIED",
                "reason": "INTERLOCK_CRITICAL",
                "error": None,
            }
            h.publish(T_LINE, line_status(t1, "STOPPED", 9, result), retain=True)
            wait_until(
                lambda: (s := self.snapshot())["line"].get("conveyor") == "STOPPED" and s["interlock"]["pending_stop"] is None,
                SNAPSHOT_TIMEOUT_S,
                0.1,
                "Line Status STOPPED/APPLIED in snapshot",
            )

            pid = "P-00000001"
            cap = now_ms()
            h.publish(T_PRODUCT, {"schema_version": 1, "product_id": pid, "timestamp": iso_ms(cap), "image_path": f"products/{pid}.jpg"})
            h.publish(
                T_VISION,
                {
                    "schema_version": 1,
                    "product_id": pid,
                    "timestamp": iso_ms(cap),
                    "defect": True,
                    "defect_type": "scratch",
                    "confidence": None,
                    "bbox": None,
                    "image_path": f"products/{pid}.jpg",
                    "gradcam_path": None,
                    "judgement_source": "PASS_THROUGH",
                },
            )
            wait_until(
                lambda: any(r.get("product_id") == pid for r in self.snapshot()["inspections"]),
                SNAPSHOT_TIMEOUT_S,
                0.2,
                f"{pid} in snapshot inspections",
            )
            status, headers, body = http_get(f"{self.base}/api/images/products/{pid}.jpg")
            ctype = {k.lower(): v for k, v in headers.items()}.get("content-type", "")
            if status != 200 or not ctype.startswith("image/jpeg") or not body.startswith(b"\xff\xd8\xff"):
                raise SmokeFailure(f"/api/images/products/{pid}.jpg -> {status} {ctype}")
            log(f"{pid} in snapshot, image 200 {ctype} {len(body)} bytes")

            cmd_id = stop["command_id"]
            wait_until(
                lambda: self.psql(f"SELECT result FROM control WHERE command_id = '{cmd_id}'") == "APPLIED"
                and self.psql(f"SELECT count(*) FROM alarm WHERE alarm_id = '{alarm['alarm_id']}'") == "1"
                and self.psql(f"SELECT count(*) FROM inspection WHERE product_id = '{pid}'") == "1",
                DB_ROWS_TIMEOUT_S,
                0.3,
                "DB rows: control APPLIED, alarm 1, inspection 1",
            )
            log("DB: control.result = APPLIED, alarm 1 row, inspection 1 row")
        finally:
            h.close()

    # 7
    def cleanup(self) -> None:
        for cid in reversed(self.containers):
            docker("rm", "-f", "-v", cid, check=False, timeout=60)
        for v in self.volumes:
            docker("volume", "rm", "-f", v, check=False, timeout=60)
        for n in self.networks:
            docker("network", "rm", n, check=False, timeout=60)

    def app_logs(self) -> str:
        if not self.app_id:
            return "(Operations container not started)"
        p = docker("logs", "--tail", "100", self.app_id, check=False, timeout=30)
        return (p.stdout or "") + (p.stderr or "")


def main() -> int:
    s = Smoke()
    ok = False
    try:
        s.build()
        s.seed()
        s.infra()
        s.app()
        s.flow()
        ok = True
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 로그를 남기고 정리한다
        log(f"FAIL: {type(e).__name__}: {e}")
        print("---- Operations container log (last 100 lines) ----", flush=True)
        print(s.app_logs(), flush=True)
    finally:
        s.cleanup()
    log("smoke passed" if ok else "smoke failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
