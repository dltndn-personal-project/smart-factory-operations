"""예시 이미지 `P-00000001.jpg`~`P-00000008.jpg`를 만든다 (docs/spec/07-runtime.md 5절).

640 × 640 JPEG. 1~4번은 회색(#808080) 바탕, 5~8번은 회색 바탕에 짙은 사선(긁힘 모양).
표준 라이브러리 `zlib`·`struct`로 PNG를 쓰고 macOS `sips`로 JPEG(품질 90)로 바꾼다.
결과 파일은 commit한다(테스트·smoke·compose `image-seed`가 쓴다). 다시 만들 때만 실행한다:

    python3 tests/fixtures/images/make_images.py
"""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIZE = 640
GRAY = 0x80
DARK = 0x30
COUNT = 8
PLAIN = 4  # 앞 네 장은 무늬 없음


def png_bytes(rows: list[bytes], width: int, height: int) -> bytes:
    """8비트 회색조 PNG. `rows`는 줄마다 `width` 바이트."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # bit depth 8, color type 0(회색조)
    raw = b"".join(b"\x00" + r for r in rows)  # 필터 없음
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def image_rows(index: int) -> list[bytes]:
    """`index`(1부터). PLAIN보다 크면 사선 하나(번호마다 위치·두께가 조금 다름)를 긋는다."""
    rows = []
    scratch = index > PLAIN
    offset = (index - PLAIN) * 60 - 150  # 사선이 지나는 위치
    half = 2 + (index - PLAIN)  # 선 두께의 절반(px)
    for y in range(SIZE):
        row = bytearray([GRAY]) * SIZE
        if scratch:
            # x - y ≈ offset인 띠(좌상 → 우하 사선)
            lo = max(0, y + offset - half)
            hi = min(SIZE, y + offset + half + 1)
            if lo < hi:
                row[lo:hi] = bytes([DARK]) * (hi - lo)
        rows.append(bytes(row))
    return rows


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(1, COUNT + 1):
            png = Path(tmp) / f"P-{i:08d}.png"
            png.write_bytes(png_bytes(image_rows(i), SIZE, SIZE))
            out = HERE / f"P-{i:08d}.jpg"
            subprocess.run(
                ["sips", "-s", "format", "jpeg", "-s", "formatOptions", "90", str(png), "--out", str(out)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            print(out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
