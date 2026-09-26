"""Docker 연동 테스트 fixture (docs/spec/08-verification.md 2절, docs/plan/05-storage.md 1절).

- 이 폴더의 모든 테스트는 `docker` 마커를 갖는다(`make test`에서 빠지고 `make docker-test`에만 들어간다).
- 호스트 포트는 테스트가 고른 빈 포트로 고정한다(`-p 127.0.0.1:<port>:5432`). Docker 임의 포트는
  `docker restart` 뒤 바뀌어 재연결 테스트가 옛 포트를 보게 된다(DECISIONS D-43).
- 컨테이너 이름은 `factory-operations-test-db-<hex8>`이고, 지울 때는 id로만 지운다(조율 C-11·C-23).
- OPS-7A가 broker·앱 fixture를 이 파일에 더한다.
"""

from __future__ import annotations

import secrets
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = REPO_ROOT / "db" / "schema.sql"
DOCKER_DIR = Path(__file__).resolve().parent

TIMESCALE_IMAGE = "timescale/timescaledb:2.30.1-pg17"
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
