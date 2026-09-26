"""`GET /api/images/{path}` 경로 검사와 파일 찾기 (docs/spec/06-dashboard.md 2절).

`path`는 02 3.1절 `rel_path(products)` 또는 `rel_path(gradcam)` 형식이어야 한다. 파일은 읽기만 한다.
FastAPI·psycopg·paho를 import하지 않는다(01 1절). 응답은 `api.py`가 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..mqtt.payloads import rel_path

IMAGE_DIRS = ("products", "gradcam")
CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


@dataclass(frozen=True)
class ImageFile:
    path: Path
    content_type: str


class BadImagePath(ValueError):
    """경로 형식이 틀림 → 400."""


class ImageNotFound(LookupError):
    """파일이 없음 → 404."""


def valid_path(path: str) -> str | None:
    """형식에 맞으면 그 문자열, 아니면 None."""
    for d in IMAGE_DIRS:
        p = rel_path(path, d)
        if p is not None:
            return p
    return None


def content_type(path: str) -> str:
    return CONTENT_TYPES[Path(path).suffix.lower()]


def resolve(image_root: Path, path: str) -> ImageFile:
    """`image_root/path` 파일. 형식이 틀리면 `BadImagePath`, 없으면 `ImageNotFound`.

    형식 검사가 `..`·절대 경로·숨김 파일을 막지만, 기호 링크로 루트 밖을 가리키는 경우도 404로 둔다.
    """
    p = valid_path(path)
    if p is None:
        raise BadImagePath(path)
    root = Path(image_root).resolve()
    target = (root / p).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ImageNotFound(path)
    return ImageFile(target, content_type(p))
