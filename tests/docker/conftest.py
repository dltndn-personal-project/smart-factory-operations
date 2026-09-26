"""Docker 연동 테스트 fixture (docs/spec/08-verification.md 2절, docs/plan/05-storage.md 1절).

- 이 폴더의 모든 테스트는 `docker` 마커를 갖는다(`make test`에서 빠지고 `make docker-test`에만 들어간다).
- 호스트 포트는 테스트가 고른 빈 포트로 고정한다(`-p 127.0.0.1:<port>:5432`). Docker 임의 포트는
  `docker restart` 뒤 바뀌어 재연결 테스트가 옛 포트를 보게 된다(DECISIONS D-43).
- 컨테이너 이름은 `factory-operations-test-db-<hex8>`·`factory-operations-test-mqtt-<hex8>`이고,
  지울 때는 id로만 지운다(조율 C-11·C-23).
- 앱 fixture(OPS-7A): `mqtt_broker`, `broker_container_factory`, `app_factory`/`running_app`, `harness`,
  `wait_snapshot`. 앱마다 고유한 Topic 접두사와 client_id를 써서 세션 broker의 retained 메시지가
  다른 테스트에 섞이지 않게 한다.
"""

from __future__ import annotations

import json
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
import paho.mqtt.client as mqtt
import psycopg
import pytest
import uvicorn
from paho.mqtt.enums import CallbackAPIVersion, MQTTProtocolVersion

from factory_operations.app import Services, build_app
from factory_operations.config import load_config
from factory_operations.mqtt.topics import Topics

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "db" / "schema.sql"
DOCKER_DIR = Path(__file__).resolve().parent

TIMESCALE_IMAGE = "timescale/timescaledb:2.30.1-pg17"
MOSQUITTO_IMAGE = "eclipse-mosquitto:2.1.2-alpine"
BROKER_READY_TIMEOUT_S = 10.0
APP_READY_TIMEOUT_S = 15.0
DB_USER = "factory"
DB_PASSWORD = "factory"
DB_NAME = "factory"
DB_READY_TIMEOUT_S = 60.0
SCHEMA_VERSION = 1

# schema_info를 뺀 운영 테이블. clean_db가 비운다.
DATA_TABLES = (
    "sensor_chunk",
    "line_status_change",
    "product",
    "inspection",
    "equipment_state",
    "alarm",
    "control",
)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """이 폴더 아래 테스트에 `docker` 마커를 붙인다(파일마다 `pytestmark`를 잊어도 빠지지 않게)."""
    for item in items:
        if DOCKER_DIR in Path(str(item.path)).resolve().parents:
            item.add_marker(pytest.mark.docker)


def free_port() -> int:
    """127.0.0.1에서 비어 있는 TCP 포트 하나. 고른 뒤 `docker run`까지의 짧은 경쟁만 남는다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def docker(*args: str, check: bool = True, timeout: float = 120.0, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=timeout, **kw)


@dataclass(frozen=True)
class DbContainer:
    """실행 중인 TimescaleDB 테스트 컨테이너."""

    id: str
    name: str
    port: int

    @property
    def url(self) -> str:
        return f"postgresql://{DB_USER}:{DB_PASSWORD}@127.0.0.1:{self.port}/{DB_NAME}"

    def connect(self, **kw) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=True, connect_timeout=5, **kw)

    def psql(self, sql_file: Path) -> subprocess.CompletedProcess:
        """컨테이너 안 psql로 파일을 실행한다(`ON_ERROR_STOP=1`). 종료 코드를 확인하지 않고 돌려준다."""
        with open(sql_file, "rb") as f:
            return subprocess.run(
                ["docker", "exec", "-i", self.id, "psql", "-v", "ON_ERROR_STOP=1", "-U", DB_USER, "-d", DB_NAME],
                stdin=f,
                capture_output=True,
                timeout=60,
            )


def schema_version(url: str) -> int | None:
    """`schema_info`의 factory-operations 버전. 연결·조회가 안 되면 None."""
    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=2) as conn:
            row = conn.execute("SELECT version FROM schema_info WHERE component = 'factory-operations'").fetchone()
            return row[0] if row else None
    except psycopg.Error:
        return None


def wait_schema_ready(db: DbContainer, timeout: float = DB_READY_TIMEOUT_S) -> None:
    """psycopg 연결과 `schema_info` 버전 1 확인이 될 때까지 기다린다. initdb 중 임시 서버는
    TCP를 듣지 않으므로 연결이 되면 initdb(schema.sql 포함)가 끝난 것이다."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if schema_version(db.url) == SCHEMA_VERSION:
            return
        state = docker("inspect", "-f", "{{.State.Running}}", db.id, check=False)
        if state.stdout.strip() != "true":
            break
        time.sleep(0.5)
    logs = docker("logs", "--tail", "50", db.id, check=False)
    raise RuntimeError(
        f"TimescaleDB {db.name} not ready with schema_info version {SCHEMA_VERSION} within {timeout}s\n"
        f"{logs.stdout}{logs.stderr}"
    )


def start_db_container() -> DbContainer:
    """빈 포트를 고정 매핑하고 schema.sql을 initdb로 마운트한 TimescaleDB 컨테이너를 띄운다.
    준비는 기다리지 않는다(`wait_schema_ready`)."""
    name = f"factory-operations-test-db-{secrets.token_hex(4)}"
    port = free_port()
    out = docker(
        "run", "-d", "--rm", "--name", name,
        "-e", f"POSTGRES_USER={DB_USER}",
        "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}",
        "-e", f"POSTGRES_DB={DB_NAME}",
        "-p", f"127.0.0.1:{port}:5432",
        "-v", f"{SCHEMA_SQL}:/docker-entrypoint-initdb.d/100_factory_operations.sql:ro",
        TIMESCALE_IMAGE,
    )  # fmt: skip
    return DbContainer(id=out.stdout.strip(), name=name, port=port)


def remove_container(container_id: str) -> None:
    docker("rm", "-f", container_id, check=False, timeout=60)


def _started_and_ready() -> DbContainer:
    db = start_db_container()
    try:
        wait_schema_ready(db)
    except BaseException:
        remove_container(db.id)
        raise
    return db


@pytest.fixture(scope="session")
def timescale_db() -> Iterator[DbContainer]:
    """세션 공용 TimescaleDB. 재시작 테스트는 이것 대신 `db_container_factory`로 자기 컨테이너를 쓴다."""
    db = _started_and_ready()
    try:
        yield db
    finally:
        remove_container(db.id)


@pytest.fixture
def clean_db(timescale_db: DbContainer) -> DbContainer:
    """운영 테이블을 비운 세션 DB(`schema_info`는 남긴다)."""
    with timescale_db.connect() as conn:
        conn.execute(f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY")
    return timescale_db


@pytest.fixture
def db_container_factory() -> Iterator[Callable[[], DbContainer]]:
    """테스트 전용 TimescaleDB를 띄우는 함수(준비까지 기다림). 테스트가 끝나면 만든 것을 id로 지운다.
    `docker restart`처럼 세션 컨테이너를 흔드는 테스트가 쓴다(DECISIONS D-43)."""
    made: list[str] = []

    def make() -> DbContainer:
        db = _started_and_ready()
        made.append(db.id)
        return db

    try:
        yield make
    finally:
        for cid in made:
            remove_container(cid)


# ---------------------------------------------------------------------------
# Mosquitto (08 2절)


@dataclass(frozen=True)
class BrokerContainer:
    """실행 중인 Mosquitto 테스트 컨테이너(인증 없음)."""

    id: str
    name: str
    port: int

    @property
    def url(self) -> str:
        return f"mqtt://127.0.0.1:{self.port}"


def new_paho(client_id: str) -> mqtt.Client:
    return mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=MQTTProtocolVersion.MQTTv311,
        clean_session=True,
    )


def broker_accepts(port: int) -> bool:
    """MQTT CONNACK까지 받으면 True. Docker 포트 프록시는 컨테이너가 듣기 전에도 TCP를 받으므로
    TCP 연결만으로는 준비를 알 수 없다."""
    c = new_paho(f"fops-probe-{secrets.token_hex(4)}")
    try:
        c.connect("127.0.0.1", port, keepalive=5)
        c.loop_start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if c.is_connected():
                return True
            time.sleep(0.05)
        return False
    except OSError:
        return False
    finally:
        c.disconnect()
        c.loop_stop()


def wait_broker_ready(b: BrokerContainer, timeout: float = BROKER_READY_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if broker_accepts(b.port):
            return
        time.sleep(0.2)
    logs = docker("logs", "--tail", "50", b.id, check=False)
    raise RuntimeError(f"Mosquitto {b.name} not ready within {timeout}s\n{logs.stdout}{logs.stderr}")


def start_broker_container(port: int | None = None) -> BrokerContainer:
    """빈 포트를 고정 매핑한 Mosquitto 컨테이너(D-43). 준비까지 기다린다."""
    name = f"factory-operations-test-mqtt-{secrets.token_hex(4)}"
    port = port or free_port()
    out = docker(
        "run", "-d", "--rm", "--name", name,
        "-p", f"127.0.0.1:{port}:1883",
        MOSQUITTO_IMAGE, "mosquitto", "-c", "/mosquitto-no-auth.conf",
    )  # fmt: skip
    b = BrokerContainer(id=out.stdout.strip(), name=name, port=port)
    try:
        wait_broker_ready(b)
    except BaseException:
        remove_container(b.id)
        raise
    return b


@pytest.fixture(scope="session")
def mqtt_broker() -> Iterator[BrokerContainer]:
    """세션 공용 Mosquitto. 재시작 테스트는 `broker_container_factory`로 자기 컨테이너를 쓴다."""
    b = start_broker_container()
    try:
        yield b
    finally:
        remove_container(b.id)


@pytest.fixture
def broker_container_factory() -> Iterator[Callable[[], BrokerContainer]]:
    """테스트 전용 Mosquitto를 띄우는 함수. 테스트가 끝나면 만든 것을 id로 지운다."""
    made: list[str] = []

    def make() -> BrokerContainer:
        b = start_broker_container()
        made.append(b.id)
        return b

    try:
        yield make
    finally:
        for cid in made:
            remove_container(cid)


# ---------------------------------------------------------------------------
# 앱 (08 2절 running_app)


@dataclass
class RunningApp:
    """스레드에서 도는 uvicorn과 실제 조립(DB 스레드, 워커, paho client)."""

    base_url: str
    prefix: str
    services: Services
    server: uvicorn.Server
    thread: threading.Thread
    http: httpx.Client = field(repr=False)

    @property
    def topics(self) -> Topics:
        return Topics(self.prefix)

    def get(self, path: str, **kw: Any) -> httpx.Response:
        return self.http.get(path, **kw)

    def post(self, path: str, **kw: Any) -> httpx.Response:
        return self.http.post(path, **kw)

    def snapshot(self) -> dict[str, Any]:
        r = self.http.get("/api/snapshot")
        r.raise_for_status()
        return r.json()

    def wait_snapshot(self, pred: Callable[[dict[str, Any]], bool], timeout: float = 5.0) -> dict[str, Any]:
        """`/api/snapshot`을 0.1초 간격으로 불러 `pred`가 참인 스냅숏을 돌려준다. 시간 초과면 AssertionError."""
        deadline = time.monotonic() + timeout
        last: dict[str, Any] | None = None
        while True:
            last = self.snapshot()
            try:
                if pred(last):
                    return last
            except (KeyError, TypeError, IndexError):
                pass
            if time.monotonic() >= deadline:
                raise AssertionError(f"snapshot condition not met within {timeout}s: {json.dumps(last)[:2000]}")
            time.sleep(0.1)

    def stop(self, timeout: float = 15.0) -> None:
        """uvicorn 종료 → lifespan이 01 7절 순서로 멈춘다."""
        self.server.should_exit = True
        self.thread.join(timeout)
        self.http.close()
        if self.thread.is_alive():
            raise RuntimeError("app did not stop")


def start_app(mqtt_url: str, db_url: str, image_root: Path, *, prefix: str | None = None) -> RunningApp:
    """앱을 띄우고 `/readyz` 200까지(최대 15초) 기다린다. broker·DB 주소는 인자다(OPS-7B 재시작 테스트)."""
    prefix = prefix or f"fops{secrets.token_hex(3)}"
    port = free_port()
    cfg = load_config(
        {
            "HTTP_HOST": "127.0.0.1",
            "HTTP_PORT": str(port),
            "MQTT_URL": mqtt_url,
            "DATABASE_URL": db_url,
            "IMAGE_ROOT": str(image_root),
            "TOPIC_PREFIX": prefix,
            "LOG_LEVEL": "INFO",
        }
    )
    cfg = cfg.model_copy(update={"mqtt": cfg.mqtt.model_copy(update={"client_id": f"factory-operations-{prefix}"})})
    app = build_app(cfg, commit="test")
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, access_log=False, lifespan="on")
    )
    thread = threading.Thread(target=server.run, name=f"uvicorn-{port}", daemon=True)
    thread.start()
    ra = RunningApp(
        base_url=f"http://127.0.0.1:{port}",
        prefix=prefix,
        services=app.state.services,
        server=server,
        thread=thread,
        http=httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5.0),
    )
    deadline = time.monotonic() + APP_READY_TIMEOUT_S
    while True:
        try:
            if ra.get("/readyz").status_code == 200:
                return ra
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline or not thread.is_alive():
            try:
                ra.stop()
            finally:
                raise RuntimeError(f"app not ready within {APP_READY_TIMEOUT_S}s")
        time.sleep(0.1)


@pytest.fixture
def app_factory(tmp_image_root: Path) -> Iterator[Callable[..., RunningApp]]:
    """`start_app(mqtt_url, db_url, prefix=None)`. 테스트가 끝나면 띄운 앱을 모두 멈춘다."""
    apps: list[RunningApp] = []

    def make(mqtt_url: str, db_url: str, *, prefix: str | None = None) -> RunningApp:
        ra = start_app(mqtt_url, db_url, tmp_image_root, prefix=prefix)
        apps.append(ra)
        return ra

    try:
        yield make
    finally:
        for ra in apps:
            ra.stop()


@pytest.fixture
def running_app(app_factory, mqtt_broker: BrokerContainer, clean_db: DbContainer) -> RunningApp:
    """세션 broker·비운 세션 DB에 연결된 앱."""
    return app_factory(mqtt_broker.url, clean_db.url)


# ---------------------------------------------------------------------------
# harness (08 2절)


class Harness:
    """테스트용 paho client. 구독은 SUBACK까지, QoS 1 발행은 PUBACK까지 기다린다.
    받은 메시지는 `(time.monotonic(), topic, payload bytes)`로 `messages`에 쌓인다."""

    def __init__(self, port: int, prefix: str):
        self.topics = Topics(prefix)
        self.messages: list[tuple[float, str, bytes]] = []
        self._lock = threading.Lock()
        self._subacks: dict[int, threading.Event] = {}
        self.client = new_paho(f"fops-harness-{secrets.token_hex(4)}")
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.client.connect("127.0.0.1", port, keepalive=30)
        self.client.loop_start()
        deadline = time.monotonic() + 5.0
        while not self.client.is_connected():
            if time.monotonic() >= deadline:
                raise RuntimeError("harness could not connect")
            time.sleep(0.02)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        with self._lock:
            self.messages.append((time.monotonic(), msg.topic, bytes(msg.payload)))

    def _on_subscribe(self, client: Any, userdata: Any, mid: int, reason_codes: Any, properties: Any = None) -> None:
        ev = self._subacks.setdefault(mid, threading.Event())
        ev.set()

    def subscribe(self, topic: str, qos: int = 1, timeout: float = 5.0) -> None:
        result, mid = self.client.subscribe(topic, qos)
        assert result == mqtt.MQTT_ERR_SUCCESS
        ev = self._subacks.setdefault(mid, threading.Event())
        assert ev.wait(timeout), f"no SUBACK for {topic}"

    def publish(self, topic: str, payload: Any, qos: int = 1, retain: bool = False) -> None:
        raw = payload if isinstance(payload, (bytes, bytearray)) else json.dumps(payload, separators=(",", ":")).encode()
        info = self.client.publish(topic, raw, qos=qos, retain=retain)
        assert info.rc == mqtt.MQTT_ERR_SUCCESS, mqtt.error_string(info.rc)
        if qos > 0:
            info.wait_for_publish(timeout=5.0)
            assert info.is_published(), f"no PUBACK for {topic}"

    def received(self, topic: str) -> list[tuple[float, dict[str, Any]]]:
        with self._lock:
            return [(t, json.loads(p)) for t, tp, p in self.messages if tp == topic]

    def wait_for(self, topic: str, pred: Callable[[dict[str, Any]], bool] = lambda m: True, timeout: float = 5.0):
        """조건에 맞는 첫 메시지 `(수신 mono, dict)`. 시간 초과면 AssertionError."""
        deadline = time.monotonic() + timeout
        while True:
            for t, m in self.received(topic):
                if pred(m):
                    return t, m
            if time.monotonic() >= deadline:
                raise AssertionError(f"no matching message on {topic} within {timeout}s")
            time.sleep(0.02)

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()


@pytest.fixture
def harness_factory() -> Iterator[Callable[[int, str], Harness]]:
    made: list[Harness] = []

    def make(port: int, prefix: str) -> Harness:
        h = Harness(port, prefix)
        made.append(h)
        return h

    try:
        yield make
    finally:
        for h in made:
            h.close()


@pytest.fixture
def harness(harness_factory, running_app: RunningApp, mqtt_broker: BrokerContainer) -> Harness:
    """`running_app`과 같은 접두사를 쓰는 harness. Operations 발행 Topic 두 개를 구독해 둔다."""
    h = harness_factory(mqtt_broker.port, running_app.prefix)
    h.subscribe(h.topics.conveyor)
    h.subscribe(h.topics.alarm)
    return h


@pytest.fixture
def wait_snapshot(running_app: RunningApp) -> Callable[..., dict[str, Any]]:
    """`wait_snapshot(pred, timeout=5.0)` (`running_app`에 묶음)."""
    return running_app.wait_snapshot
