# 06 Dashboard: HTTP API, 스냅숏, 화면

> 목적: HTTP endpoint, `/api/snapshot` 형식과 상태(stale) 판정, 화면 구성과 브라우저 동작을 정한다.
> 읽어야 할 때: `web/`(OPS-6, OPS-8), 화면 항목을 바꿀 때. 화면 배치는 `docs/WIREFRAME.html`.

## 1. 구성

- FastAPI 앱 하나가 JSON API와 정적 파일(`src/factory_operations/web/static/`)을 같은 포트(기본 8080)로 준다. 빌드 단계·Node·외부 CDN이 없다. 차트는 `plot.js`가 canvas 2D로 직접 그린다(`DECISIONS.md` D-12).
- 브라우저는 `GET /api/snapshot`을 **1초마다** 가져와 화면 전체를 다시 그린다. WebSocket·SSE는 쓰지 않는다.
- HTTP 요청 처리 중에는 DB를 조회하지 않는다. 스냅숏은 StateStore(01 3절)에서만 만든다.
- 인증 없음. 호스트 노출은 `127.0.0.1`에만 한다(`07-runtime.md` 3절). 동시 접속을 고려하지 않는다.

## 2. Endpoint

| 메서드·경로 | 응답 |
|---|---|
| `GET /` | `static/index.html` |
| `GET /static/{file}` | 정적 파일 |
| `GET /healthz` | 항상 200 `{"status":"ok","commit":"<GIT_COMMIT 또는 unknown>","mqtt_connected":bool,"db_ok":bool}`. 프로세스와 HTTP가 살아 있는지 |
| `GET /readyz` | `mqtt_connected`와 `db_ok`가 모두 true면 200, 아니면 503. 본문은 `/healthz`와 같다 |
| `GET /api/snapshot` | 200, 3절 JSON. `Cache-Control: no-store` |
| `GET /api/images/{path:path}` | `path`가 `02-mqtt.md` 3.1절 `rel_path(products)` 또는 `rel_path(gradcam)`에 맞으면 `IMAGE_ROOT/path` 파일. 형식이 틀리면 400, 파일이 없으면 404. `Content-Type`은 확장자로(`image/jpeg`, `image/png`). 파일을 읽기만 한다 |
| `POST /api/conveyor` | 본문 `{"command":"START"}` 또는 `{"command":"STOP"}`. 성공 202 `{"command_id","command","timestamp","judged_state"}`(`03-control.md` 3.3절). 본문이 틀리면 422 `invalid_command`, MQTT 끊김 503 `mqtt_disconnected`, 워커가 2초 안에 답하지 않으면 504 `timeout` |

오류 본문은 `{"error":"<코드>","detail":"<설명>"}`.

## 3. `/api/snapshot`

`web/snapshot.py`의 순수 함수 `build_snapshot(view, now_wall, now_mono, cfg) -> dict`가 만든다. 시각 필드는 모두 `iso_ms` 문자열이다. Payload에서 온 `timestamp`는 Simulator 시계, `generated_at`·`received_at`·`summary_at`·`computed_at`은 Operations 시각이다. `age_s`는 Operations `mono()` 기준 수신 뒤 지난 초(소수 1자리).

```json
{
  "schema_version": 1,
  "generated_at": "2026-09-25T05:21:00.512Z",
  "mqtt_connected": true,
  "db_ok": true,
  "line": {
    "status": "LIVE",
    "timestamp": "2026-09-25T05:21:00.020Z", "received_at": "2026-09-25T05:21:00.031Z", "age_s": 0.5,
    "conveyor": "RUNNING", "fault_level": 8, "motor_rpm": 1800.0, "production_active": true,
    "sensor_id": "motor01",
    "products": {"spawned": 120, "created": 113, "expired": 0, "in_flight": 7, "last_product_id": "P-00000113"},
    "last_command": {"command": "STOP", "command_id": "…", "source": "mqtt", "received_at": "…", "result": "APPLIED", "reason": "INTERLOCK_CRITICAL", "error": null}
  },
  "pdm": {
    "status": "LIVE", "sensor_id": "motor01",
    "timestamp": "…", "window_start": "…", "received_at": "…", "age_s": 0.3,
    "anomaly_score": 0.82, "health_index": 18, "state": "CRITICAL", "model_version": "2026-09-27-a",
    "before_restart": false,
    "history": [{"timestamp": "…", "anomaly_score": 0.21, "health_index": 91, "state": "NORMAL"}]
  },
  "spectrum": {
    "status": "LIVE", "timestamp": "…", "received_at": "…", "age_s": 0.7,
    "panels": [{"title": "스펙트럼", "x_start": 0.0, "x_step": 1.0, "x_unit": "Hz", "series": [{"name": "spectrum_x", "values": [0.0012]}]}]
  },
  "vibration": {
    "status": "LIVE", "sensor_id": "motor01", "timestamp": "…", "received_at": "…", "age_s": 0.1,
    "rpm": 1800.0, "temperature": 41.23, "window_s": 1.0, "sample_rate_hz": 10000,
    "x": {"min": [-0.41], "max": [0.39]}, "y": {"min": [], "max": []}, "z": {"min": [], "max": []}
  },
  "interlock": {
    "line_state": "RUNNING", "reference_time": "…",
    "judged": {"timestamp": "…", "state": "CRITICAL"},
    "pending_stop": {"command_id": "…", "age_s": 0.4},
    "last_trigger_timestamp": "…"
  },
  "production": {"summary_at": "…", "produced": 113, "inspected": 111, "defects": 14, "defect_rate": 0.1261},
  "inspections": [{"product_id": "P-00000113", "timestamp": "…", "defect": true, "defect_type": "scratch", "confidence": null, "bbox": null, "image_path": "products/P-00000113.jpg", "gradcam_path": null, "judgement_source": "PASS_THROUGH", "health_index_at_time": 22}],
  "alarms": [{"alarm_id": "…", "timestamp": "…", "raised_at": "…", "sensor_id": "motor01", "severity": "CRITICAL", "previous_state": "WARNING", "health_index": 18, "anomaly_score": 0.82}],
  "controls": [{"command_id": "…", "command": "STOP", "reason": "INTERLOCK_CRITICAL", "origin": "operations", "source": null, "issued_at": "…", "trigger_timestamp": "…", "result": "APPLIED", "result_received_at": "…", "error": null, "recorded_at": "…"}],
  "correlation": null,
  "counters": {"rejected": {"factory/pdm/result:invalid_field:state": 0}, "queue_overflow": 0}
}
```

필드 규칙:

| 절 | 규칙 |
|---|---|
| `line` | Line Status를 받은 적이 없으면 `{"status":"NONE"}`만. `online: false`를 마지막으로 받았으면 `status: "OFFLINE"`이고 나머지는 마지막 online 값(없으면 null). 그 밖에는 `age_s > dashboard.line_stale_s`(3초)이면 `STALE`, 아니면 `LIVE` |
| `pdm` | 라인 센서의 마지막 PdM Result. 없으면 `{"status":"NONE"}`. `age_s ≤ pdm.stale_s`(2초)이면 `LIVE`, 넘으면 `STALE`(4절). `before_restart`는 `reference_time`이 있고 `timestamp ≤ reference_time`이면 true. `history`는 최근 `pdm.history_s`(120초) 결과(최대 240개), 오래된 것부터 |
| `spectrum` | 없으면 `{"status":"NONE"}`. `age_s ≤ dashboard.spectrum_stale_s`(3초)이면 `LIVE`, 아니면 `STALE`. `panels`는 02 3.7절 결과, 값은 소수 4자리 |
| `vibration` | 링 버퍼가 비면 `{"status":"NONE"}`. 링의 chunk(모두 같은 `sample_rate_hz`·배열 길이, 03 2절)를 `seq` 순으로 이어 붙인 축별 배열을 `dashboard.vibration_buckets`(500)개 구간으로 같게 나눠 구간별 최솟값·최댓값(소수 4자리). 샘플이 구간 수보다 적으면 구간 수 = 샘플 수. `window_s` = 샘플 수 / `sample_rate_hz`. 마지막 chunk `age_s > dashboard.vibration_stale_s`(1초)이면 `STALE`. `rpm`·`temperature`·`timestamp`는 마지막 chunk 값 |
| `interlock` | `03-control.md` 3.1절 상태. `judged`·`pending_stop`·`last_trigger_timestamp`는 없으면 null |
| `production`, `inspections`, `alarms`, `controls` | DB 요약(05 5절)의 마지막 결과. 아직 없거나 DB가 끊겼으면 `production`은 null, 목록은 빈 배열. 최신이 먼저 |
| `correlation` | 04 2.3절 결과. 아직 없으면 null. `db_ok`가 false이거나 `computed_at` 뒤 `3 × correlation.period_s`(30초)가 지났으면 `stale: true`를 붙이고 화면은 "마지막 계산 · N초 전"으로 표시한다. DB가 다시 연결되면 다음 주기(최대 10초)에 새로 계산한다 |

- 진동 솎기는 표시용 downsampling이며 특징(RMS 등) 계산이 아니다(Shared 17절 경계).
- 스냅숏 크기는 약 60~80 KB다(진동 3 × 1000값, 스펙트럼 최대 6 × 501값).

## 4. 오래된 판정(stale) 표시 규칙

| 상황 | 판정 | 화면 |
|---|---|---|
| PdM 결과를 2초 넘게 받지 못함(`pdm.status == "STALE"`) | 현재 판정이 아니다. 원인: 라인 정지(PdM은 `rpm == 0`이면 발행하지 않음), PdM 중단, 유실 | State·HI·Anomaly Score를 회색으로 두고 제목을 "마지막 판정 · N초 전"으로 바꾼다. `line.conveyor == "STOPPED"`이면 "라인 정지 중 — 정지 중에는 PdM 판정이 없음"을 덧붙인다 |
| `pdm.before_restart == true` | 재가동 전 판정이라 Interlock 판단에서 빠졌다(03 1.2절) | "재가동 전 판정 — Interlock 판단에서 제외"를 덧붙인다 |
| `line.status` `OFFLINE` / `STALE` / `NONE` | Simulator 정상 종료·비정상 끊김 / Line Status 3초 이상 없음 / 미수신 | 라인 칸에 "Simulator offline" / "Line Status 수신 없음(N초)" / "대기 중". Interlock은 `OFFLINE`·`NONE`을 라인 상태 "알 수 없음"으로 본다(03 3.2절). `STALE`은 마지막 `conveyor` 값을 그대로 쓴다 |
| 스펙트럼·진동 STALE | 표시 데이터가 오래됨 | 차트 위에 "N초 전 데이터" |
| 스냅숏 요청 실패 또는 3초 초과 | 서버 응답 없음 | 화면 맨 위에 "Operations 서버 연결 끊김", 마지막 화면 유지 |

2초는 PdM hop(0.5초) 4개다. 1.0초 윈도우를 쓰는 PdM이 정상일 때 결과 간격은 0.5초이므로 네 번 연속 빠지면 현재 판정이 아니라고 본다(PdM 아키텍처 6.2절 제안과 같은 값).

## 5. 화면

배치와 문구는 `docs/WIREFRAME.html`을 따른다. 칸과 내용:

| 칸 | 내용 | 출처 |
|---|---|---|
| 상단 막대 | 제목, `generated_at`, MQTT·DB 연결 표시, "N초 전 갱신"(브라우저 시계로 마지막 성공 응답 뒤 지난 시간) | `mqtt_connected`, `db_ok` |
| 라인 | Conveyor Status(크게, RUNNING 초록·STOPPED 빨강), Current Fault Level("Simulator 설정값 · 평가용" 표기), 생산 진행(`production_active`), 모터 rpm, Simulator 누계(`products.created`, "simulator 누계"), `START`·`STOP` 버튼, Interlock 표시(대기 중 STOP, 마지막 trigger 시각) | `line`, `interlock` |
| 설비 상태 (PdM) | Equipment State 배지(4색), Health Index, Anomaly Score, 판정 시각과 경과, 4절 상태 문구, 최근 120초 추세(Anomaly Score 선, HI 선, 상태 경계 80/60/40 가로선) | `pdm` |
| 실시간 진동 | 축 3개 min/max 띠 그래프(최근 1초), 온도·rpm | `vibration` |
| FFT Spectrum | `panels`마다 그래프 하나, 계열마다 선 하나(범례 = 계열 이름). 0~500 Hz 전체. 없으면 "PdM 스펙트럼 없음" | `spectrum` |
| 품질 | Defect Rate(%), 생산 수(`produced`), 검사 수(`inspected`), 최근 검사 12개(썸네일, `product_id`, 판정·Defect Type, Confidence(null이면 "—"), Grad-CAM(null이면 "현재 범위에서 제공하지 않음"), 판정 출처(`PASS_THROUGH`면 "pass-through(Simulator 정보 전달)"), 캡처 시각 HI). 썸네일을 누르면 원본 크기로 보기 | `production`, `inspections`, `/api/images` |
| 설비-품질 상관관계 | 기본 lag의 Pearson·Spearman·표본 수, 최대 |Pearson| lag와 계수, lag별 계수 곡선(두 선), 30초 구간 막대(불량률)와 선(평균 Anomaly Score), 04 2.4절 문구. 계수가 null이면 사유("표본 부족" 등) | `correlation` |
| Alarm History | 최근 20개: 시각(`timestamp`), severity 배지, 이전 상태 → severity, HI, Anomaly Score | `alarms` |
| Control History | 최근 20개: 기록 시각, 명령, 사유, 출처(`origin`/`source`), 결과(null이면 "대기"), 오류 | `controls` |

브라우저 동작(`app.js`):
- `const POLL_INTERVAL_MS = 1000;` 요청 시작 시각 기준으로 1초마다 `fetch("/api/snapshot", {cache: "no-store"})`. 이전 요청이 끝나지 않았으면 새 요청을 보내지 않는다. 3초가 지나면 `AbortController`로 끊고 실패로 본다.
- 응답마다 모든 칸을 다시 그린다. 스크롤 위치는 유지한다.
- `START`: `interlock.judged.state == "CRITICAL"`이면 `confirm()`으로 "현재 설비 판정이 CRITICAL입니다. 재가동하면 PdM이 다시 CRITICAL을 내는 즉시 Interlock이 라인을 멈춥니다. simulator에서 Fault Level을 먼저 낮추었는지 확인하세요." 확인 뒤에만 보낸다. `STOP`은 확인 없이 보낸다. 응답 오류는 버튼 옆에 코드로 표시한다.
- 썸네일 `<img loading="lazy">`가 실패하면 "이미지 없음".
- 색은 CSS 변수로 두고 밝은·어두운 테마를 `prefers-color-scheme`으로 따른다.
- `?debug=1`이면 상단 막대에 마지막 스냅숏 응답 시간과 렌더링 시간(`performance.now()`로 응답 처리 시작부터 그리기 끝까지, ms)을 표시한다(`08-verification.md` 4.1절 `R`).

`plot.js`: `drawLines(canvas, {x: {start, step, unit}, series: [{values, label, colorVar}], y: {min, max, label}, hlines})`, `drawBands(canvas, {min, max, colorVar, window_s})`, `drawBars(canvas, …)`. 축 눈금·범례만 그린다. 확대·툴팁은 없다.

## 6. 설정

| 키 | 기본값 | 의미 |
|---|---|---|
| `pdm.history_s` | 120 | PdM 이력 보관(초). 결합(04 1.2절)과 추세 |
| `pdm.stale_s` | 2.0 | 4절 |
| `dashboard.line_stale_s` | 3.0 | 4절 |
| `dashboard.spectrum_stale_s` | 3.0 | 4절 |
| `dashboard.vibration_stale_s` | 1.0 | 4절 |
| `dashboard.vibration_window_chunks` | 10 | 링 버퍼 chunk 수(1초) |
| `dashboard.vibration_buckets` | 500 | 축별 구간 수 |
| `dashboard.recent_inspections` | 12 | 05 5절 `n_inspections` |
| `dashboard.recent_alarms` | 20 | 05 5절 `n_alarms` |
| `dashboard.recent_controls` | 20 | 05 5절 `n_controls` |
