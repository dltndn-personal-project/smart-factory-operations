"""시계와 timestamp (docs/spec/01-core.md 5절).

`Clock`은 벽시계(`wall`, UTC aware)와 단조 시계(`mono`, 초)를 준다. 판단 로직은 시계를
주입받아 테스트에서 가짜 시계(`tests/conftest.py` `FakeClock`)로 바꾼다.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Protocol

# Shared CONVENTIONS timestamp 정규식
TS_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", re.ASCII)


class Clock(Protocol):
    def wall(self) -> datetime:
        """현재 UTC 시각(aware)."""
        ...

    def mono(self) -> float:
        """단조 시계(초). 경과 시간 비교에만 쓴다."""
        ...


class SystemClock:
    def wall(self) -> datetime:
        return datetime.now(timezone.utc)

    def mono(self) -> float:
        return time.monotonic()


def iso_ms(dt: datetime) -> str:
    """UTC, 밀리초 3자리(밀리초 미만 버림), `Z` 접미사 문자열.

    반올림하지 않으므로 `…59.9999`가 다음 초로 올라가지 않는다. naive datetime은 받지 않는다.
    """
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("iso_ms requires an aware datetime")
    u = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        u.year,
        u.month,
        u.day,
        u.hour,
        u.minute,
        u.second,
        u.microsecond // 1000,
    )


def parse_ts(s: str) -> datetime:
    """CONVENTIONS 정규식에 맞는 문자열만 UTC aware datetime으로 바꾼다. 아니면 `ValueError`."""
    if not isinstance(s, str) or _TS_RE.fullmatch(s) is None:
        raise ValueError(f"timestamp must match {TS_PATTERN}: {s!r}")
    try:
        return datetime.strptime(s[:-1], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(f"invalid timestamp {s!r}: {e}") from None
