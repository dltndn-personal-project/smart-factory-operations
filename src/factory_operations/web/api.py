"""FastAPI 앱 (docs/spec/06-dashboard.md 2절). FastAPI는 이 모듈만 import한다(01 1절).

지금은 `/healthz`만 있다. `/readyz`, `/api/*`, 정적 파일과 StateStore·inbound 큐 사용은 OPS-6이
더한다(`docs/plan/06-dashboard.md` 1절의 `create_app(cfg, state, inbound_queue, clock, lifespan)`).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI


def create_app(
    cfg: Any = None,
    state: Any = None,
    inbound_queue: Any = None,
    clock: Any = None,
    lifespan: Any = None,
    *,
    commit: str | None = None,
) -> FastAPI:
    commit = commit or os.environ.get("GIT_COMMIT") or "unknown"
    app = FastAPI(
        title="factory-operations",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def health_body() -> dict[str, Any]:
        # StateStore가 생기기 전(state None)에는 둘 다 false
        mqtt_connected = bool(getattr(state, "mqtt_connected", False))
        db_ok = bool(getattr(state, "db_ok", False))
        return {"status": "ok", "commit": commit, "mqtt_connected": mqtt_connected, "db_ok": db_ok}

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        # 프로세스와 HTTP가 살아 있으면 항상 200
        return health_body()

    return app
