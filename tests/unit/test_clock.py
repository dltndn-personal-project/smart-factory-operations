"""시계와 timestamp (docs/spec/01-core.md 5절, 08-verification.md 3.1절)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from factory_operations.clock import TS_PATTERN, SystemClock, iso_ms, parse_ts

TS_RE = re.compile(TS_PATTERN)
UTC = timezone.utc


def test_iso_ms_format():
    s = iso_ms(datetime(2026, 9, 25, 5, 21, 0, 512000, tzinfo=UTC))
    assert s == "2026-09-25T05:21:00.512Z"
    assert TS_RE.match(s)
    # 밀리초가 0이어도 3자리
    assert iso_ms(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2026-01-02T03:04:05.000Z"
    # 다른 시간대는 UTC로 바꾼다
    kst = timezone(timedelta(hours=9))
    assert iso_ms(datetime(2026, 9, 25, 14, 21, 0, 7000, tzinfo=kst)) == "2026-09-25T05:21:00.007Z"


def test_iso_ms_truncates():
    # …59.9999가 다음 초로 올라가지 않는다
    assert iso_ms(datetime(2026, 9, 25, 5, 21, 59, 999900, tzinfo=UTC)) == "2026-09-25T05:21:59.999Z"
    assert iso_ms(datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)) == "2026-12-31T23:59:59.999Z"
    assert iso_ms(datetime(2026, 9, 25, 5, 21, 0, 1999, tzinfo=UTC)) == "2026-09-25T05:21:00.001Z"
    for us in (0, 1, 999, 1000, 499999, 500000, 999999):
        assert TS_RE.match(iso_ms(datetime(2026, 9, 25, 5, 21, 0, us, tzinfo=UTC)))


def test_iso_ms_rejects_naive():
    with pytest.raises(ValueError):
        iso_ms(datetime(2026, 9, 25, 5, 21, 0))


def test_parse_ts_roundtrip():
    dt = parse_ts("2026-09-25T05:21:00.512Z")
    assert dt == datetime(2026, 9, 25, 5, 21, 0, 512000, tzinfo=UTC)
    assert dt.tzinfo is not None
    assert iso_ms(dt) == "2026-09-25T05:21:00.512Z"


def test_parse_ts_rejects_non_ms():
    for bad in (
        "2026-09-25T05:21:13Z",  # 밀리초 없음
        "2026-09-25T05:21:13.4Z",  # 1자리
        "2026-09-25T05:21:13.4567Z",  # 4자리
        "2026-09-25T05:21:13.000+00:00",  # Z 대신 오프셋
        "2026-09-25T05:21:13+00:00",
        "2026-09-25 05:21:13.000Z",  # T 없음
        "2026-09-25T05:21:13.000z",
        "2026-09-25T05:21:13.000Z\n",  # 끝 줄바꿈
        "2026-13-25T05:21:13.000Z",  # 정규식은 맞지만 없는 달
        "",
    ):
        with pytest.raises(ValueError):
            parse_ts(bad)
    with pytest.raises(ValueError):
        parse_ts(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        parse_ts(1727241673000)  # type: ignore[arg-type]


def test_system_clock():
    c = SystemClock()
    w = c.wall()
    assert w.tzinfo is not None and w.utcoffset() == timedelta(0)
    a = c.mono()
    assert c.mono() >= a


def test_fake_clock_advances_both(fake_clock):
    w0, m0 = fake_clock.wall(), fake_clock.mono()
    fake_clock.advance(1.5)
    assert fake_clock.wall() - w0 == timedelta(seconds=1.5)
    assert fake_clock.mono() - m0 == pytest.approx(1.5)
    assert TS_RE.match(iso_ms(fake_clock.wall()))
