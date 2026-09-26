"""공용 fixture (docs/spec/08-verification.md 2절, docs/plan/01-core.md 1절).

뒤 task는 이 파일을 고치지 않는다. 필요한 fixture는 자기 테스트 파일이나
`tests/docker/conftest.py`에 둔다.
"""

from __future__ import annotations

import json
import queue
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

TESTS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = TESTS_DIR / "fixtures"
PAYLOADS_DIR = FIXTURES_DIR / "payloads"
IMAGES_DIR = FIXTURES_DIR / "images"

FAKE_WALL_START = datetime(2026, 9, 25, 5, 21, 0, tzinfo=timezone.utc)
FAKE_MONO_START = 1000.0


class FakeClock:
    """`Clock` 가짜. `advance(s)`가 벽시계와 단조 시계를 함께 진행한다."""

    def __init__(self, wall: datetime = FAKE_WALL_START, mono: float = FAKE_MONO_START):
        self._wall = wall
        self._mono = mono

    def wall(self) -> datetime:
        return self._wall

    def mono(self) -> float:
        return self._mono

    def advance(self, s: float) -> None:
        self._wall = self._wall + timedelta(seconds=s)
        self._mono = self._mono + s


class FakePublisher:
    """발행기 가짜. `publish` 호출을 모두 `(topic, payload, qos, retain)`으로 `calls`에 기록하고,
    `connected`가 결과(True/False)를 정한다. `sent`는 연결된 동안의 호출만이다."""

    def __init__(self, connected: bool = True):
        self.connected = connected
        self.calls: list[tuple[str, Any, int, bool]] = []
        self.results: list[bool] = []

    def publish(self, topic: str, payload: Any, qos: int = 0, retain: bool = False) -> bool:
        self.calls.append((topic, payload, qos, retain))
        self.results.append(self.connected)
        return self.connected

    @property
    def sent(self) -> list[tuple[str, Any, int, bool]]:
        return [c for c, ok in zip(self.calls, self.results) if ok]


class FakeDbSink:
    """DB 큐 가짜. 작업 타입을 모르고 `put_nowait(job)`을 `jobs`에 쌓는다.
    `full = True`면 `queue.Full`을 던진다(큐 초과 경로)."""

    def __init__(self) -> None:
        self.jobs: list[Any] = []
        self.full = False

    def put_nowait(self, job: Any) -> None:
        if self.full:
            raise queue.Full
        self.jobs.append(job)


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def fake_db_sink() -> FakeDbSink:
    return FakeDbSink()


@pytest.fixture
def tmp_image_root(tmp_path: Path) -> Path:
    """`products/P-00000001.jpg` 복사본을 둔 Image Storage 루트.
    원본 `tests/fixtures/images/P-00000001.jpg`는 OPS-6이 만든다."""
    root = tmp_path / "image-root"
    (root / "products").mkdir(parents=True)
    (root / "gradcam").mkdir()
    shutil.copyfile(IMAGES_DIR / "P-00000001.jpg", root / "products" / "P-00000001.jpg")
    return root


@pytest.fixture(scope="session")
def payload_examples() -> dict[str, Any]:
    """`tests/fixtures/payloads/*.json`을 파일 이름(확장자 제외) → JSON 값으로 준다.
    파일과 출처(`SOURCES.md`)는 OPS-2가 만든다."""
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(PAYLOADS_DIR.glob("*.json"))}
