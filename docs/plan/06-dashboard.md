# 06 Dashboard 계획 (M3, M4)

> 목적: OPS-6(스냅숏과 HTTP API)과 OPS-8(화면)의 PLAN 정의와 단계 개요.
> 읽어야 할 때: 두 task를 실행하거나 등록할 때. 같이 읽을 spec: `docs/spec/06-dashboard.md`, `docs/WIREFRAME.html`.

## 1. 경계

- OPS-6은 `web/`의 파이썬 쪽 전부다: `snapshot.py`(순수 함수 `build_snapshot`), `images.py`(경로 검사·파일 응답), `api.py`(모든 endpoint, 정적 파일 제공). `create_app(cfg, state, inbound_queue, clock, lifespan=None)`처럼 StateStore와 inbound 큐를 받는다. 실제 워커·MQTT·DB와의 조립은 OPS-7A다.
- `POST /api/conveyor`는 `OperatorCommand(command, future)`(OPS-3B)를 inbound 큐에 넣고 2초 기다린다. OPS-6 테스트는 큐를 읽어 future에 답하는 가짜 워커로 한다.
- 정적 파일: OPS-6은 `GET /`와 `/static/{file}` 경로를 만들고 자리표시 `index.html` 하나를 둔다. OPS-8이 `static/` 전체를 채운다.
- 예시 이미지 fixture(`tests/fixtures/images/`)는 `/api/images` 테스트가 처음 쓰므로 OPS-6이 만든다(spec 00 6절은 OPS-9에 두었다. D-37). OPS-9A·9B(smoke, compose `image-seed`)가 같은 파일을 쓴다.

## 2. task

### OPS-6 스냅숏과 HTTP API

```yaml
  - id: OPS-6
    milestone: M3
    type: feature
    title: 스냅숏, HTTP API, 이미지 응답, 예시 이미지 fixture
    why: 화면과 갱신 지연 측정·integration 관찰이 /api/snapshot 하나를 보고, 흐름 연동 테스트가 /readyz와 스냅숏으로 처리 완료를 확인한다 (spec 06 1~4절, A-09·A-10, D-15·D-23·D-33)
    depends_on: [OPS-4B]
    scope: [src/factory_operations/web/__init__.py, src/factory_operations/web/api.py, src/factory_operations/web/snapshot.py, src/factory_operations/web/images.py, src/factory_operations/web/static/index.html, tests/unit/test_snapshot.py, tests/unit/test_api.py, tests/fixtures/images/**, docs/spec/06-dashboard.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: 스냅숏이 pdm age_s 2.0 LIVE·2.1 STALE, before_restart, line NONE·OFFLINE·STALE·LIVE, 진동 구간 min/max(샘플 수 < 구간 수 포함), 목록 길이 상한, 상관분석 stale, 모든 시각 필드의 정규식을 만족하고 가득 찬 스냅숏이 150 KB 이하다 (06 3·4절, 08 3.5절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_snapshot.py tests/unit/test_snapshot.py::test_pdm_live_stale_boundary tests/unit/test_snapshot.py::test_before_restart tests/unit/test_snapshot.py::test_line_status_states tests/unit/test_snapshot.py::test_vibration_minmax_buckets tests/unit/test_snapshot.py::test_vibration_fewer_samples_than_buckets tests/unit/test_snapshot.py::test_list_limits tests/unit/test_snapshot.py::test_correlation_stale tests/unit/test_snapshot.py::test_all_times_match_regex tests/unit/test_snapshot.py::test_full_snapshot_size"}
      - id: A3
        text: /healthz 200, /readyz 503·200, /api/snapshot Cache-Control no-store, /api/images 200(image/jpeg)·400·404, /api/conveyor 202·422·503·504, GET / 200이 spec 06 2절대로다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_api.py tests/unit/test_api.py::test_healthz tests/unit/test_api.py::test_readyz tests/unit/test_api.py::test_snapshot_no_store tests/unit/test_api.py::test_images_status_codes tests/unit/test_api.py::test_conveyor_status_codes tests/unit/test_api.py::test_index_served"}
      - id: A4
        text: 예시 이미지 P-00000001~8.jpg가 640 px JPEG이고 만드는 스크립트가 있다 (07 5절)
        check: {type: command, run: "test -f tests/fixtures/images/make_images.py || exit 1; for i in 1 2 3 4 5 6 7 8; do f=tests/fixtures/images/P-0000000$i.jpg; out=$(sips -g format -g pixelWidth -g pixelHeight \"$f\" 2>/dev/null) || { echo \"missing $f\"; exit 1; }; echo \"$out\" | grep -q 'format: jpeg' && echo \"$out\" | grep -q 'pixelWidth: 640' && echo \"$out\" | grep -q 'pixelHeight: 640' || { echo \"bad $f\"; exit 1; }; done"}
      - id: A5
        text: snapshot.py와 images.py가 FastAPI·psycopg·paho를 import하지 않는다 (01 1절)
        check: {type: command, run: "! grep -nE '^[[:space:]]*(import|from)[[:space:]]+(fastapi|starlette|psycopg|paho)' src/factory_operations/web/snapshot.py src/factory_operations/web/images.py"}
    size: M
```

단계 개요:
1. `tests/fixtures/images/make_images.py`와 결과 JPEG 8장(07 5절: 표준 라이브러리로 PNG, `sips`로 JPEG, 640 × 640, 회색 네 장·사선 네 장). → A4
2. `snapshot.py` `build_snapshot(view, now_wall, now_mono, cfg)`: 3절 JSON과 필드 규칙, 4절 stale, 진동 min/max 솎기(numpy), 스펙트럼 소수 4자리, 요약·상관분석 전달. → A2
3. `images.py`: OPS-2 `rel_path(products)`/`rel_path(gradcam)`로 검사, `IMAGE_ROOT` 아래 파일, 확장자로 Content-Type. → A3
4. `api.py`: endpoint 전부, 오류 본문 `{"error","detail"}`, `/api/conveyor` 큐·future·2초, 정적 파일, 자리표시 `index.html`. → A3
5. `test_snapshot.py`, `test_api.py`(TestClient, 가짜 StateStore·가짜 워커), `make test`. → A1, A5

읽을 spec: 06 1~4·6절, 02 3.1절(이미지 경로), 03 3.3절(명령 결과 형식), 05 5절(요약 형식), 04 2.3절(상관분석 형식), 08 3.5절, D-15·D-23·D-31·D-33.

### OPS-8 Dashboard 화면

```yaml
  - id: OPS-8
    milestone: M4
    type: feature
    title: Dashboard 화면 (index.html, app.js, plot.js, style.css)
    why: 운영자가 한 화면에서 라인·설비 상태·진동·스펙트럼·품질·상관관계·Alarm·Control 이력을 1초마다 보고 START/STOP을 한다 (spec 06 4·5절, WIREFRAME, D-12·D-24)
    depends_on: [OPS-6]
    scope: [src/factory_operations/web/static/**, tests/unit/test_static.py, docs/spec/06-dashboard.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: index.html에 화면 칸 id(line, pdm, vibration, spectrum, quality, correlation, alarms, controls)가 있고, app.js에 const POLL_INTERVAL_MS = 1000;이 있으며, 정적 파일에 http·https 외부 URL이 없다 (08 3.5절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_static.py::test_panel_ids tests/unit/test_static.py::test_poll_interval_constant tests/unit/test_static.py::test_no_external_urls"}
      - id: A3
        text: 앱이 GET /와 /static/app.js·plot.js·style.css를 200으로 준다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_static.py::test_static_served"}
      - id: A4
        text: 화면 문구와 동작 표시가 있다 — 4절 stale 문구(마지막 판정, 라인 정지 중, 재가동 전 판정, Operations 서버 연결 끊김), PdM 스펙트럼 없음, 현재 범위에서 제공하지 않음, 표본 부족, CRITICAL START 확인 창 문구, ?debug=1 렌더링 시간(performance.now), prefers-color-scheme
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_static.py::test_status_texts tests/unit/test_static.py::test_start_confirm_text tests/unit/test_static.py::test_debug_timing tests/unit/test_static.py::test_color_scheme"}
    size: M
```

단계 개요:
1. `index.html`: WIREFRAME 배치와 칸 id, 외부 요청 없음. → A2
2. `style.css`: CSS 변수, 밝은·어두운 테마, 상태 색(RUNNING 초록·STOPPED 빨강, State 4색). → A4
3. `plot.js`: `drawLines`, `drawBands`, `drawBars`(06 5절, canvas 2D, 축 눈금·범례·가로선).
4. `app.js`: 1초 polling(이전 요청 진행 중이면 건너뜀, 3초 `AbortController`), 칸마다 다시 그리기(스크롤 유지), stale 문구, 버튼(START 확인 창, 오류 코드 표시), 썸네일·원본 보기·"이미지 없음", `?debug=1`. → A2, A4
5. `tests/unit/test_static.py`, `make test`. → A1, A3

- 화면 모양·색·깜빡임·렌더링 시간은 HUM-1(M-01~M-10)에서 사람이 본다. 자동 검사는 파일 내용과 제공 여부만 본다. 개발 중 확인은 OPS-9B의 개발용 compose가 생기기 전이면 `make run`과 손으로 보낸 MQTT로 한다(선택).

읽을 spec: 06 3·4·5절, `docs/WIREFRAME.html`, 04 2.4절(상관관계 문구), 08 3.5·4.1절(`R`), D-12·D-24·D-36.
