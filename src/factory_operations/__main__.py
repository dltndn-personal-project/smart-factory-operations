"""`python -m factory_operations serve` (docs/spec/01-core.md 7절)."""

from __future__ import annotations

import argparse
import sys

from .config import load_or_exit
from .log import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m factory_operations")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="HTTP 서버와 MQTT·DB 처리를 시작한다")
    parser.parse_args(argv)

    cfg = load_or_exit()  # 설정 오류면 stderr에 키 경로를 쓰고 종료 코드 2
    setup_logging(cfg.logging.level)

    import uvicorn

    from .app import build_app

    app = build_app(cfg)
    # access_log=False: 1초 polling마다 로그 줄이 생기지 않게 한다
    uvicorn.run(app, host=cfg.http.host, port=cfg.http.port, log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
