"""JSON 한 줄 로그와 같은 사유 억제 (docs/spec/01-core.md 6절).

- `setup_logging(level)`: root logger에 stdout JSON 핸들러를 단다. uvicorn(`log_config=None`)의
  로그도 root로 올라와 같은 형식이 된다.
- `EventLogger`: `event`와 필드를 받아 한 줄을 쓴다. 억제 대상이면 같은 (event, topic, reason)
  조합을 10초에 한 번만 쓰고, 그 사이 억제한 개수를 다음 줄의 `suppressed`에 붙인다.
  억제 대상은 기본으로 WARNING 이상이고 호출에서 `throttle=`로 바꿀 수 있다(DECISIONS D-47).
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from datetime import datetime, timezone
from typing import IO, Any

from .clock import Clock, SystemClock, iso_ms

SUPPRESS_WINDOW_S = 10.0
_FIELDS_ATTR = "fops_fields"
_EVENT_ATTR = "fops_event"


def _json_default(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).decode("utf-8", errors="replace")
    if isinstance(v, datetime):
        return iso_ms(v) if v.tzinfo is not None else v.isoformat()
    return str(v)


class JsonFormatter(logging.Formatter):
    """`{"ts", "level", "logger", "event", ...필드}` 한 줄."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": iso_ms(datetime.fromtimestamp(record.created, timezone.utc)),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, _EVENT_ATTR, None) or record.getMessage(),
        }
        fields = getattr(record, _FIELDS_ATTR, None)
        if fields:
            for k, v in fields.items():
                if k not in ("ts", "level", "logger", "event"):
                    out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=_json_default)


def setup_logging(level: str = "INFO", stream: IO[str] | None = None) -> logging.Handler:
    """root logger를 JSON 한 줄 stdout 핸들러 하나로 설정한다."""
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)
    # uvicorn 로거가 자기 핸들러 없이 root로 올라오게 한다
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    return handler


class EventLogger:
    """이벤트 이름과 필드로 로그를 쓰고 반복되는 사유를 억제한다. 스레드 안전."""

    def __init__(self, name: str, clock: Clock | None = None, window_s: float = SUPPRESS_WINDOW_S):
        self.logger = logging.getLogger(name)
        self._clock = clock or SystemClock()
        self._window_s = window_s
        self._lock = threading.Lock()
        # (event, topic, reason) -> [마지막으로 쓴 mono, 그 뒤 억제한 개수]
        self._seen: dict[tuple[str, Any, Any], list[float | int]] = {}

    def log(self, level: int, event: str, *, throttle: bool | None = None, **fields: Any) -> bool:
        """한 줄을 쓰면 True, 억제했거나 level 미만이면 False."""
        if not self.logger.isEnabledFor(level):
            return False
        if throttle is None:
            throttle = level >= logging.WARNING
        if throttle:
            key = (event, fields.get("topic"), fields.get("reason"))
            now = self._clock.mono()
            with self._lock:
                entry = self._seen.get(key)
                if entry is not None and now - entry[0] < self._window_s:
                    entry[1] += 1
                    return False
                suppressed = entry[1] if entry is not None else 0
                self._seen[key] = [now, 0]
            if suppressed:
                fields["suppressed"] = suppressed
        self.logger.log(level, event, extra={_EVENT_ATTR: event, _FIELDS_ATTR: fields})
        return True

    def debug(self, event: str, **fields: Any) -> bool:
        return self.log(logging.DEBUG, event, **fields)

    def info(self, event: str, **fields: Any) -> bool:
        return self.log(logging.INFO, event, **fields)

    def warning(self, event: str, **fields: Any) -> bool:
        return self.log(logging.WARNING, event, **fields)

    def error(self, event: str, **fields: Any) -> bool:
        return self.log(logging.ERROR, event, **fields)


def get_logger(name: str, clock: Clock | None = None) -> EventLogger:
    return EventLogger(name, clock=clock)
