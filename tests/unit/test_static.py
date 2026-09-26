"""Dashboard 정적 파일 (docs/spec/06-dashboard.md 4·5절, 08-verification.md 3.5절).

화면 모양·색·깜빡임·렌더링 시간은 사람이 HUM-1에서 본다(headless 브라우저 없음, D-34).
여기서는 파일 내용(칸 id, polling 상수, 외부 URL 없음, 화면 문구)과 앱의 제공 여부만 본다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factory_operations.web.api import STATIC_DIR, create_app

PANEL_IDS = ("line", "pdm", "vibration", "spectrum", "quality", "correlation", "alarms", "controls")
ASSETS = ("app.js", "plot.js", "style.css")

START_CONFIRM_TEXT = (
    "현재 설비 판정이 CRITICAL입니다. 재가동하면 PdM이 다시 CRITICAL을 내는 즉시 Interlock이 라인을 멈춥니다. "
    "simulator에서 Fault Level을 먼저 낮추었는지 확인하세요."
)


def read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def static_files() -> list[Path]:
    return sorted(p for p in STATIC_DIR.rglob("*") if p.is_file())


def test_static_files_exist():
    names = {p.name for p in static_files()}
    assert {"index.html", *ASSETS} <= names


def test_panel_ids():
    html = read("index.html")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    missing = [i for i in PANEL_IDS if i not in ids]
    assert not missing, missing
    # 칸은 section 요소다(WIREFRAME)
    for i in PANEL_IDS:
        assert re.search(rf'<section\b[^>]*\bid="{i}"', html), i


def test_index_loads_assets():
    html = read("index.html")
    assert '<link rel="stylesheet" href="/static/style.css">' in html
    assert '<script src="/static/plot.js"></script>' in html
    assert '<script src="/static/app.js"></script>' in html
    assert html.index("/static/plot.js") < html.index("/static/app.js")  # app.js가 Plot을 쓴다


def test_poll_interval_constant():
    js = read("app.js")
    assert "const POLL_INTERVAL_MS = 1000;" in js
    assert re.search(r"setInterval\(poll, POLL_INTERVAL_MS\)", js)
    # 스냅숏 요청: 캐시 없음, 3초 AbortController, 진행 중이면 건너뜀
    assert 'fetch("/api/snapshot", { cache: "no-store", signal: ctrl.signal })' in js
    assert "const REQUEST_TIMEOUT_MS = 3000;" in js
    assert "new AbortController()" in js
    assert "if (inFlight) return;" in js


@pytest.mark.parametrize("path", static_files(), ids=lambda p: p.name)
def test_no_external_urls(path: Path):
    text = path.read_text(encoding="utf-8")
    found = re.findall(r"https?://[^\s\"'<>)]*", text, flags=re.IGNORECASE)
    assert not found, (path.name, found)
    # 프로토콜 상대 URL(//host)로 외부 파일을 부르지 않는다
    assert not re.search(r"""(?:src|href)\s*=\s*["']//""", text), path.name
    assert not re.search(r"""url\(\s*["']?//""", text), path.name


def test_static_served():
    client = TestClient(create_app())
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    for i in PANEL_IDS:
        assert f'id="{i}"' in r.text
    types = {"app.js": "javascript", "plot.js": "javascript", "style.css": "text/css"}
    for name in ASSETS:
        r = client.get(f"/static/{name}")
        assert r.status_code == 200, name
        assert types[name] in r.headers["content-type"], (name, r.headers["content-type"])
        assert r.content == (STATIC_DIR / name).read_bytes()


def test_status_texts():
    js = read("app.js")
    html = read("index.html")
    for text in (
        "마지막 판정",  # PdM STALE 제목 "마지막 판정 · N초 전"
        "라인 정지 중 — 정지 중에는 PdM 판정이 없음",
        "재가동 전 판정 — Interlock 판단에서 제외",
        "Operations 서버 연결 끊김",
        "Simulator offline",
        "Line Status 수신 없음",
        "초 전 데이터",
        "PdM 스펙트럼 없음",
        "현재 범위에서 제공하지 않음",
        "pass-through(Simulator 정보 전달)",
        "이미지 없음",
        "표본 부족",
        "마지막 계산",
    ):
        assert text in js, text
    assert "Operations 서버 연결 끊김" in html  # 배너
    # 4절 판정 값과 문구의 연결
    assert 'p.status === "STALE" && line.conveyor === "STOPPED"' in js
    assert "p.before_restart" in js
    assert 'insufficient_samples: "표본 부족"' in js
    # 상관관계 해석 문구(04 2.4절)
    assert "설비 지표 = PdM Anomaly Score, 품질 지표 = 검사 불량 여부(pass-through), 기본 lag 13초(투입 → 캡처)" in html


def test_start_confirm_text():
    js = read("app.js")
    assert START_CONFIRM_TEXT in js
    assert "window.confirm(START_CONFIRM_TEXT)" in js
    assert 'command === "START" && judged && judged.state === "CRITICAL"' in js
    # 응답 오류는 코드로 표시한다
    assert "body.error" in js
    assert 'fetch("/api/conveyor"' in js


def test_debug_timing():
    js = read("app.js")
    assert 'new URLSearchParams(window.location.search).get("debug") === "1"' in js
    assert "performance.now()" in js
    assert "렌더링" in js
    assert 'id="debug-info"' in read("index.html")


def test_color_scheme():
    css = read("style.css")
    assert "@media (prefers-color-scheme: dark)" in css
    root_vars = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    for var in ("--ground", "--panel", "--ink", "--normal", "--caution", "--warning", "--critical", "--stale", "--accent"):
        assert var in root_vars, var
    # 상태 색: RUNNING 초록·STOPPED 빨강, State 4색
    assert ".run { color: var(--normal); }" in css
    assert ".stop { color: var(--critical); }" in css
    for state in ("normal", "caution", "warning", "critical"):
        assert f".b-{state} {{ background: var(--{state}); }}" in css
    # 차트도 CSS 변수로 색을 읽는다
    assert "getPropertyValue(name)" in read("plot.js")


def test_plot_functions():
    js = read("plot.js")
    for fn in ("function drawLines(canvas, opts)", "function drawBands(canvas, opts)", "function drawBars(canvas, opts)"):
        assert fn in js, fn
    assert "global.Plot = { drawLines, drawBands, drawBars };" in js
    assert 'getContext("2d")' in js
