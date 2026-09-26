"""조립과 수명 주기 (docs/spec/01-core.md 2·7절).

`build_services(cfg)`가 StateStore·큐·DB 스레드·워커·MQTT client를 만들고(시작하지 않음),
`build_app(cfg)`가 그것을 HTTP 앱(`web.api.create_app`)과 lifespan으로 묶는다.
lifespan은 1) 시작 로그 2) DB 스레드 3) 도메인 워커 4) MQTT client 순서로 시작하고
반대 순서로 끝낸다(MQTT → 워커 join 2초 → DB 스레드 join 5초). 제한 시간을 넘기면 로그만 남긴다.
"""

from __future__ import annotations

import functools
import os
import queue
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from .clock import Clock, SystemClock
from .config import Config
from .domain import correlation
from .domain.state import StateStore
from .domain.worker import Processor, Worker
from .log import get_logger
from .mqtt.client import MqttClient
from .store.db import DbWriter
from .web.api import create_app

log = get_logger("factory_operations.app")

INBOUND_MAXSIZE = 2000  # 01 2절
DB_QUEUE_MAXSIZE = 10000
WORKER_STOP_TIMEOUT_S = 2.0  # 01 7절
DB_STOP_TIMEOUT_S = 5.0


def git_commit(env: Any = None) -> str:
    env = os.environ if env is None else env
    return env.get("GIT_COMMIT") or "unknown"


def mask_url_password(url: str) -> str:
    """로그에 비밀번호를 남기지 않는다."""
    u = urlsplit(url)
    if u.password is None:
        return url
    netloc = f"{u.username}:***@{u.hostname}" + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment))


def config_summary(cfg: Config) -> dict[str, Any]:
    return {
        "http": f"{cfg.http.host}:{cfg.http.port}",
        "mqtt_url": cfg.mqtt.url,
        "topic_prefix": cfg.mqtt.topic_prefix,
        "db_url": mask_url_password(cfg.db.url),
        "image_root": str(cfg.paths.image_root_path),
        "log_level": cfg.logging.level,
    }


@dataclass
class Services:
    """한 프로세스의 구성 요소(01 2절 스레드 표)."""

    cfg: Config
    clock: Clock
    state: StateStore
    inbound: "queue.Queue[Any]"
    db_queue: "queue.Queue[Any]"
    db: DbWriter
    mqtt: MqttClient
    processor: Processor
    worker: Worker

    def start(self) -> None:
        """2) DB 스레드 3) 워커 4) MQTT. Broker·DB가 없어도 기동은 계속한다."""
        self.db.start()
        self.worker.start()
        self.mqtt.start()

    def stop(self) -> bool:
        """MQTT → 워커 → DB 순서. 모두 제한 시간 안에 끝났으면 True."""
        self.mqtt.stop()
        ok_worker = self.worker.stop(WORKER_STOP_TIMEOUT_S)
        ok_db = self.db.stop(DB_STOP_TIMEOUT_S)
        return ok_worker and ok_db


def build_services(cfg: Config, *, clock: Clock | None = None) -> Services:
    clock = clock or SystemClock()
    state = StateStore.from_config(cfg)
    inbound: queue.Queue[Any] = queue.Queue(maxsize=INBOUND_MAXSIZE)
    db_queue: queue.Queue[Any] = queue.Queue(maxsize=DB_QUEUE_MAXSIZE)

    def on_summary(summary: dict) -> None:
        state.set_summary(summary, clock.wall(), clock.mono())

    db = DbWriter(
        cfg,
        db_queue,
        clock=clock,
        on_db_ok=state.set_db_ok,
        on_summary=on_summary,
        on_correlation=state.set_correlation,
        compute_correlation=functools.partial(correlation.compute, clock=clock),
    )
    mqtt = MqttClient(cfg, state, inbound, clock)
    processor = Processor(cfg, state, mqtt, db_queue, clock, topics=mqtt.topics)
    worker = Worker(processor, inbound)
    return Services(cfg, clock, state, inbound, db_queue, db, mqtt, processor, worker)


def build_app(cfg: Config, *, commit: str | None = None, services: Services | None = None):
    commit = commit or git_commit()
    svc = services or build_services(cfg)

    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        # 1. 설정·로그·StateStore(build_services에서 끝남), 시작 로그
        log.info("service_started", commit=commit, config=config_summary(cfg))
        # 2. DB 스레드 3. 도메인 워커 4. MQTT client
        svc.start()
        try:
            yield  # 5. HTTP 응답
        finally:
            # 종료는 시작의 반대 순서(MQTT → 워커 → DB)
            clean = svc.stop()
            log.info("service_stopped", commit=commit, clean=clean)

    app = create_app(cfg, svc.state, svc.inbound, svc.clock, lifespan, commit=commit)
    app.state.services = svc
    return app
