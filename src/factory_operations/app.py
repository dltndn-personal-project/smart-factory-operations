"""조립과 수명 주기 (docs/spec/01-core.md 7절).

lifespan이 1) 설정·로그·StateStore 2) DB 스레드 3) 도메인 워커 4) MQTT client 순서로 시작하고
반대 순서로 끝낸다. 지금은 1)의 시작 로그만 있고 2)~4)는 OPS-4B·OPS-7A가 채운다.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from .config import Config
from .log import get_logger
from .web.api import create_app

log = get_logger("factory_operations.app")


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


def build_app(cfg: Config, *, commit: str | None = None):
    commit = commit or git_commit()

    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        # 1. 설정·로그 준비(호출 전에 끝남), 시작 로그. StateStore는 OPS-3A 이후.
        log.info("service_started", commit=commit, config=config_summary(cfg))
        # 2. DB 스레드(OPS-4B) 3. 도메인 워커 4. MQTT client(OPS-7A)
        try:
            yield
        finally:
            # 종료는 시작의 반대 순서(MQTT → 워커 → DB)
            log.info("service_stopped", commit=commit)

    return create_app(cfg, lifespan=lifespan, commit=commit)
