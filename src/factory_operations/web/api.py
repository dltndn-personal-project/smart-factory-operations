"""FastAPI 앱 (docs/spec/06-dashboard.md 1·2절). FastAPI는 이 모듈만 import한다(01 1절).

`create_app(cfg, state, inbound_queue, clock, lifespan, *, commit)`: StateStore와 inbound 큐를 받는다.
HTTP 요청 처리 중에는 DB를 조회하지 않는다. 스냅숏은 StateStore에서만 만든다(`snapshot.py`).
실제 워커·MQTT·DB와의 조립은 `app.py`(OPS-7A)가 한다.
"""

from __future__ import annotations

import json
import os
import queue
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from ..clock import SystemClock
from ..config import load_config
from ..domain.state import StateStore
from ..domain.worker import OperatorCommand, OperatorCommandError
from . import images
from .snapshot import build_snapshot

STATIC_DIR = Path(__file__).resolve().parent / "static"
COMMAND_TIMEOUT_S = 2.0  # 워커 응답 대기(03 3.3절)
COMMANDS = ("START", "STOP")
NO_STORE = {"Cache-Control": "no-store"}

# 운영자 명령 실패 코드 → HTTP 상태
COMMAND_ERROR_STATUS = {"invalid_command": 422, "mqtt_disconnected": 503, "timeout": 504}
COMMAND_ERROR_DETAIL = {
    "invalid_command": 'body must be {"command": "START"} or {"command": "STOP"}',
    "mqtt_disconnected": "MQTT broker is not connected",
}


def error_response(status: int, code: str, detail: str, headers: dict[str, str] | None = None) -> JSONResponse:
    """오류 본문 `{"error","detail"}` (06 2절)."""
    return JSONResponse({"error": code, "detail": detail}, status_code=status, headers=headers)


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def create_app(
    cfg: Any = None,
    state: StateStore | None = None,
    inbound_queue: Any = None,
    clock: Any = None,
    lifespan: Any = None,
    *,
    commit: str | None = None,
    command_timeout_s: float = COMMAND_TIMEOUT_S,
) -> FastAPI:
    """`state`·`inbound_queue`·`clock`이 없으면 빈 StateStore, 아무도 읽지 않는 큐, 시스템 시계를 쓴다
    (조립 전 단독 실행용: 스냅숏은 NONE, `/api/conveyor`는 504)."""
    commit = commit or os.environ.get("GIT_COMMIT") or "unknown"
    cfg = cfg if cfg is not None else load_config({})
    state = state if state is not None else StateStore.from_config(cfg)
    inbound = inbound_queue if inbound_queue is not None else queue.Queue(maxsize=1)
    clock = clock if clock is not None else SystemClock()
    image_root = cfg.paths.image_root_path

    app = FastAPI(
        title="factory-operations",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def health_body() -> dict[str, Any]:
        return {
            "status": "ok",
            "commit": commit,
            "mqtt_connected": bool(state.mqtt_connected),
            "db_ok": bool(state.db_ok),
        }

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        # 프로세스와 HTTP가 살아 있으면 항상 200
        return health_body()

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        body = health_body()
        ready = body["mqtt_connected"] and body["db_ok"]
        return JSONResponse(body, status_code=200 if ready else 503)

    @app.get("/api/snapshot")
    def snapshot() -> Response:
        view = state.snapshot_view()  # 락 안에서는 참조·얕은 복사만
        snap = build_snapshot(view, clock.wall(), clock.mono(), cfg)
        return Response(_json_bytes(snap), media_type="application/json", headers=NO_STORE)

    @app.get("/api/images/{path:path}")
    def image(path: str) -> Response:
        try:
            f = images.resolve(image_root, path)
        except images.BadImagePath:
            return error_response(400, "invalid_path", "path must be products/… or gradcam/… with .jpg/.jpeg/.png")
        except images.ImageNotFound:
            return error_response(404, "not_found", f"no image at {path}")
        return FileResponse(f.path, media_type=f.content_type)

    def run_command(command: str) -> tuple[int, dict[str, Any]]:
        """워커 큐에 넣고 최대 `command_timeout_s` 기다린다(스레드 풀에서 실행)."""
        deadline = time.monotonic() + command_timeout_s
        future: Future = Future()
        try:
            inbound.put(OperatorCommand(command, future), timeout=command_timeout_s)
        except queue.Full:
            return COMMAND_ERROR_STATUS["timeout"], {"error": "timeout", "detail": "inbound queue is full"}
        try:
            result = future.result(timeout=max(0.0, deadline - time.monotonic()))
        except FutureTimeout:
            future.cancel()  # 늦게 온 워커 결과는 버려진다(worker._complete)
            detail = f"worker did not answer within {command_timeout_s:g} s"
            return COMMAND_ERROR_STATUS["timeout"], {"error": "timeout", "detail": detail}
        except OperatorCommandError as e:
            status = COMMAND_ERROR_STATUS.get(e.code, 500)
            return status, {"error": e.code, "detail": COMMAND_ERROR_DETAIL.get(e.code, e.code)}
        return 202, result

    @app.post("/api/conveyor")
    async def conveyor(request: Request) -> JSONResponse:
        try:
            body = json.loads(await request.body())
        except (ValueError, UnicodeDecodeError):
            body = None
        command = body.get("command") if isinstance(body, dict) else None
        if not isinstance(command, str) or command not in COMMANDS:
            return error_response(422, "invalid_command", COMMAND_ERROR_DETAIL["invalid_command"])
        status, payload = await run_in_threadpool(run_command, command)
        return JSONResponse(payload, status_code=status)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html", headers=NO_STORE)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
