# 02 MQTT 계획 (M1, M3, M5)

> 목적: OPS-2(Payload), OPS-7A(MQTT 연결과 앱 조립), OPS-10(`contract_ref` 채택)의 PLAN 정의와 단계 개요.
> 읽어야 할 때: 이 세 task를 실행하거나 등록할 때, PdM 형식 의존이 어디 있는지 볼 때. 같이 읽을 spec: `docs/spec/02-mqtt.md`, `docs/spec/AGREEMENTS.md`.

## 1. MQTT task 전체

| task | 선행 | size | 내용 |
|---|---|---|---|
| OPS-2 | OPS-1 | M | `topics.py`, `payloads.py`(파서 6종, `build_conveyor`, `build_alarm`, 스펙트럼 패널), Payload fixture |
| OPS-7A | OPS-5, OPS-6 | M | `client.py`(paho), 워커 스레드 루프, `app.py` 조립(lifespan), Docker 앱 fixture, 흐름 연동 테스트. broker 재시작 테스트는 OPS-7B(D-45) |
| OPS-10 | OPS-2 + 조율 agent 알림 | M | `contract_ref` 채택, Shared 확정본과 파서·fixture·fake_feed·spec 맞춤 |

spec 00 6절은 OPS-6을 "MQTT와 워커", OPS-7을 "HTTP API"로 두었지만, 흐름 연동 테스트(C-04~C-06)가 `/readyz`와 `/api/snapshot`(`wait_snapshot`)을 쓰므로 HTTP API를 먼저 만들고(OPS-6) MQTT 조립과 연동 테스트를 뒤로(OPS-7A) 옮겼다(D-37).

## 2. OPS-2 Payload

```yaml
  - id: OPS-2
    milestone: M1
    type: feature
    title: 입력 파서 6종, 발행 Payload 생성, 스펙트럼 패널
    why: 모든 입력은 파싱·검증을 거친 객체로만 도메인에 들어가고, 발행 Payload는 A-02·A-03 형식이어야 한다. PdM 형식 의존을 이 모듈 한 곳에 모은다 (C-01, spec 02 2~4절, D-39)
    depends_on: [OPS-1]
    scope: [src/factory_operations/mqtt/__init__.py, src/factory_operations/mqtt/topics.py, src/factory_operations/mqtt/payloads.py, tests/unit/test_payloads.py, tests/unit/test_topics.py, tests/fixtures/payloads/**, docs/spec/02-mqtt.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: Shared 예시 5개(Sensor Vibration은 스칼라 필드 + seed 고정 배열)와 PdM 아키텍처 6.2절 예시가 받아지고 파싱 값이 원문과 같다 (08 2절, 3.2절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_shared_examples_accepted tests/unit/test_payloads.py::test_pdm_draft_example_accepted"}
      - id: A3
        text: 02 3.2~3.7절 표의 필드를 하나씩 빼거나 틀리게 하면 missing_field·invalid_field·topic_mismatch·unsupported_schema_version(bool 포함)·invalid_json 사유로 거부되고, 선택 필드는 틀려도 받고 null이 된다 (3.1절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_missing_field_reasons tests/unit/test_payloads.py::test_invalid_field_reasons tests/unit/test_payloads.py::test_topic_mismatch tests/unit/test_payloads.py::test_unsupported_schema_version tests/unit/test_payloads.py::test_invalid_json tests/unit/test_payloads.py::test_optional_fields_become_null"}
      - id: A4
        text: Line Status online false(다른 필드 없음)를 받고, last_command.result가 틀리면 last_command만 null이 되며, Vision Result는 confidence·bbox·gradcam_path 키가 없어도 받는다 (3.3·3.5절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_line_offline_only tests/unit/test_payloads.py::test_bad_last_command_nulls_only_it tests/unit/test_payloads.py::test_vision_missing_optional_keys"}
      - id: A5
        text: 스펙트럼 (a) spectrum_x/y/z + freq_step_hz → 패널 1개·계열 3개·x_step 1.0 Hz (b) + envelope_y → 패널 2개 (c) 간격 없음 → x_unit bin (d) 배열 없음 → no_series (e) 300 KB → too_large (3.7절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_spectrum_single_panel tests/unit/test_payloads.py::test_spectrum_envelope_panel tests/unit/test_payloads.py::test_spectrum_bins_without_step tests/unit/test_payloads.py::test_spectrum_no_series tests/unit/test_payloads.py::test_spectrum_too_large"}
      - id: A6
        text: build_conveyor·build_alarm의 키 집합과 값이 A-03(Shared Conveyor Control 예시)·A-02 형식과 같고, timestamp가 CONVENTIONS 정규식에 맞으며 command_id가 UUID4다 (4.1절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_build_conveyor_shape tests/unit/test_payloads.py::test_build_alarm_shape"}
      - id: A7
        text: 이미지 경로 products/../x.jpg, /data/products/a.jpg, products/.P-1.jpg.tmp, gradcam/a.jpg(products 자리), products/a.gif가 거부된다 (3.1절 6번)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_rel_path_rejects"}
      - id: A8
        text: Topic이 접두사로 만들어지고 수신 Topic에서 입력 종류와 sensor_id 자리를 찾는다 (2절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_topics.py::test_topics_with_prefix tests/unit/test_topics.py::test_kind_of_topic"}
      - id: A9
        text: Payload fixture가 9개 이상이고, 출처 기록(SOURCES.md)에 Shared d0c997c와 PdM db9b7e7 commit이 있다
        check: {type: command, run: "test \"$(ls tests/fixtures/payloads/*.json | wc -l)\" -ge 9 && grep -q d0c997c97129141d9853a42ce6e0d1f8f7309ae9 tests/fixtures/payloads/SOURCES.md && grep -q db9b7e79ce2329104d611ab52c509e74c6b927dd tests/fixtures/payloads/SOURCES.md"}
      - id: A10
        text: 테스트·smoke용 PdM 메시지 생성 함수(tests/fixtures/payloads/pdm.py)가 PdM fixture를 템플릿으로 써서 키 집합이 fixture와 같고, 만든 메시지가 파서로 받아진다 (D-39)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_pdm_helpers_match_fixtures"}
    size: M
```

단계 개요:
1. fixture 준비(`tests/fixtures/payloads/`). 원문은 아래 명령으로 읽는다(`contract_ref`가 null이라 90-shared 2절처럼 commit을 고정해 참고로 읽는다).
   ```sh
   gh api --method GET repos/dltndn-personal-project/smart-factory-shared-repository/contents/docs/INTERFACES.md \
     -f ref=d0c997c97129141d9853a42ce6e0d1f8f7309ae9 -H 'Accept: application/vnd.github.raw+json'
   gh api --method GET repos/dltndn-personal-project/smart-factory-pdm/contents/docs/ARCHITECTURE.md \
     -f ref=db9b7e79ce2329104d611ab52c509e74c6b927dd -H 'Accept: application/vnd.github.raw+json'   # 6.2절 예시
   ```
   파일: `shared_sensor_vibration.json`(원문 스칼라 필드 + seed 고정 축별 1000개, 소수 4자리), `shared_product_created.json`, `shared_vision_result.json`, `shared_conveyor_control.json`, `shared_line_status.json`(원문 그대로), `pdm_result_draft.json`(PdM 6.2절 예시 그대로), `pdm_spectrum_basic.json`·`pdm_spectrum_envelope.json`·`pdm_spectrum_nostep.json`(spec 08 3.2절 (a)~(c), 501값). `SOURCES.md`에 파일마다 출처(저장소·commit·절 또는 생성 방법)를 적는다. → A9
2. `topics.py`: 접두사로 Topic 8개, 수신 Topic → 입력 종류와 `+` 자리 값. → A8
3. `payloads.py` 공통 규칙(3.1절)과 `rel_path`. → A3, A7
4. 파서 6종과 결과 dataclass(`SensorChunk`, `LineStatus`/`LineOffline`, `ProductCreated`, `VisionResult`, `PdmResult`, `SpectrumPanels`), `Rejected(reason)`. 진동 배열은 numpy float32와 `isfinite`. → A2, A4, A5
5. `build_conveyor`, `build_alarm`, 직렬화 함수(4.1절). `build_alarm`의 입력은 OPS-3B가 만들 Alarm 값 객체다. 필드 이름만 A-02로 고정하고 dataclass는 여기서 정의한다. → A6
6. `tests/fixtures/payloads/pdm.py`: `pdm_result(sensor_id, timestamp, state, health_index, anomaly_score, **바꿀 값)`과 `pdm_spectrum(sensor_id, timestamp, **바꿀 값)`. PdM fixture JSON을 읽어 값만 바꾼다(필드 이름을 코드에 다시 쓰지 않는다). 테스트는 `from fixtures.payloads import pdm`(pytest가 `tests/`를 sys.path에 넣는다), `scripts/smoke.py`는 파일 경로로 불러온다. → A10
7. `tests/unit/test_payloads.py`, `test_topics.py`, `make test`. → A1

- `PdmResult`·`SpectrumPanels`를 만드는 두 파서가 PdM 형식에 기대는 유일한 제품 코드다(01 계획 1절, D-39). 다른 모듈에서 PdM Payload의 JSON 키를 직접 읽지 않는다. 뒤 task의 연동 테스트(OPS-7A·7B)와 smoke(OPS-9A)는 PdM 메시지를 `pdm.py`로만 만든다.

읽을 spec: 02 2~4절, `AGREEMENTS.md` A-01~A-07, 01 5절(`parse_ts`), 08 2·3.2절, D-32.

## 3. OPS-7A MQTT 연결과 앱 조립

```yaml
  - id: OPS-7A
    milestone: M3
    type: feature
    title: paho client, 워커 스레드, 앱 조립, 흐름 연동 테스트
    why: MQTT 수신 → 워커 → 발행·DB·StateStore → HTTP가 한 프로세스로 이어져야 실제 broker·DB에서 기록·결합·Interlock·명령 결과가 동작한다 (C-04, C-06, spec 01 2·7절, 02 1·4·5절, 03 3.3절)
    depends_on: [OPS-5, OPS-6]
    scope: [src/factory_operations/*.py, tests/docker/**, tests/unit/test_mqtt_client.py, docs/spec/01-core.md, docs/spec/02-mqtt.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: Docker 연동 테스트 전체가 통과한다
        check: {type: command, run: "make docker-test"}
      - id: A3
        text: 실제 Mosquitto·DB에 연결한 앱에 Line Status·센서 20개·PdM 4개·제품·검사 2쌍을 보내면 5초 안에 spec 08 3.6절 표대로 행이 생기고 fault_level·health_index_at_time이 결합 규칙과 같으며, CRITICAL 뒤 APPLIED 결과를 보내면 3초 안에 control.result가 APPLIED다 (C-04, C-06)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_app_flow.py::test_rows_and_joins tests/docker/test_app_flow.py::test_stop_result_recorded"}
      - id: A4
        text: POST /api/conveyor START가 202이고 harness가 reason OPERATOR_START인 Conveyor Control을 받으며 control 행이 생긴다 (03 3.3절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_app_flow.py::test_operator_start_published"}
      - id: A5
        text: MQTT가 끊겨 있으면 publish가 paho를 부르지 않고 False를 돌려주고, on_message는 파싱 없이 inbound 큐에 넣기만 하며 큐가 가득 차면 버린 수를 센다 (01 2절, 02 1·4.2절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_mqtt_client.py::test_publish_skipped_when_disconnected tests/unit/test_mqtt_client.py::test_on_message_only_enqueues tests/unit/test_mqtt_client.py::test_inbound_overflow_counted"}
      - id: A6
        text: Broker·DB 없이 기동한 serve가 /readyz에 503(mqtt_connected false, db_ok false)으로 답하고, SIGTERM 뒤 10초 안에 끝난다 (01 7절, 06 2절)
        check:
          type: command
          run: |
            make venv >/dev/null || exit 1
            d=$(mktemp -d)
            HTTP_PORT=18281 MQTT_URL=mqtt://127.0.0.1:1 DATABASE_URL=postgresql://x:x@127.0.0.1:1/x .venv/bin/python -m factory_operations serve >"$d/serve.log" 2>&1 &
            pid=$!
            ok=1
            for i in $(seq 60); do
              code=$(curl -s -o "$d/r.json" -w '%{http_code}' --max-time 1 http://127.0.0.1:18281/readyz)
              if [ "$code" = 503 ] && grep -Eq '"mqtt_connected" *: *false' "$d/r.json" && grep -Eq '"db_ok" *: *false' "$d/r.json"; then ok=0; break; fi
              sleep 0.25
            done
            kill -TERM "$pid"
            for i in $(seq 40); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
            if kill -0 "$pid" 2>/dev/null; then echo "not stopped within 10s"; kill -9 "$pid"; ok=1; fi
            [ "$ok" -eq 0 ] || cat "$d/serve.log"
            exit "$ok"
      - id: A7
        text: paho·psycopg·FastAPI를 import하는 모듈이 각각 mqtt/client.py, store/db.py, web/api.py 하나다 (01 1절)
        check:
          type: command
          run: |
            chk() { found=$(grep -rlE "^[[:space:]]*(import|from)[[:space:]]+$1([[:space:].]|$)" src | sort | tr '\n' ' '); [ "$found" = "$2 " ] || { echo "$1: $found"; exit 1; }; }
            chk paho src/factory_operations/mqtt/client.py
            chk psycopg src/factory_operations/store/db.py
            chk fastapi src/factory_operations/web/api.py
    size: M
```

단계 개요:
1. `mqtt/client.py`: 02 1절 기동 순서, `on_connect` 구독 한 번, `on_message` → `Inbound` `put_nowait`(가득 차면 카운터·`queue_overflow` 로그), `publish()`(끊김이면 False, 반환 코드 확인). `mqtt_connected`를 StateStore에 둔다. → A5
2. `domain/worker.py`에 스레드 루프 추가: `get(timeout=0.1)` → OPS-3B `Processor.handle`, 매 0.1초 `tick`, 종료 표시(01 2절). 파싱은 워커에서.
3. `app.py` lifespan(01 7절 순서): StateStore → DB 스레드(OPS-4B, 요약·상관분석 콜백을 StateStore에 연결, 상관분석 계산은 OPS-5 함수) → 워커 → MQTT → HTTP(OPS-6 `create_app`에 inbound 큐 전달). 종료 역순과 제한 시간. `__main__.py serve`. → A6, A7
4. `tests/docker/conftest.py`에 `mqtt_broker`(빈 포트 고정, D-43), `running_app`(uvicorn을 스레드에서 빈 포트로, `/readyz` 200까지 15초. broker·DB 주소를 인자로 받아 OPS-7B의 재시작 테스트가 자기 broker 컨테이너로 쓸 수 있게), `harness`(SUBACK·PUBACK 대기), `wait_snapshot`, PdM 메시지는 `tests/fixtures/payloads/pdm.py`로 만든다(D-39).
5. `test_app_flow.py`(3.6절 흐름, 운영자 START). → A3, A4
6. `tests/unit/test_mqtt_client.py`(paho client 객체를 가짜로 바꿔 끼움). → A5
7. `make test`, `make docker-test`. → A1, A2

읽을 spec: 01 2·3·7절, 02 1·4·5절, 03 2절(처리 순서)·3.3절, 05 3절(DB 스레드 시작·종료), 06 2절(`/readyz`), 08 2·3.6절, D-14·D-16·D-20·D-33.

## 4. PdM 형식 의존의 위치

PdM Result·PdM Spectrum 형식이 Shared에서 바뀌면 고칠 곳은 다음뿐이다(D-39). OPS-1~OPS-9B는 `AGREEMENTS.md` A-05·A-06 가정으로 진행한다.

| 자리 | 만드는 task | 내용 |
|---|---|---|
| `mqtt/payloads.py` `parse_pdm_result`, `parse_pdm_spectrum` | OPS-2 | JSON → `PdmResult`, `SpectrumPanels` |
| `tests/fixtures/payloads/pdm_*.json`, `tests/fixtures/payloads/pdm.py`, `tests/unit/test_payloads.py`의 PdM 테스트 | OPS-2 | 가정 형식 예시와 테스트·smoke용 메시지 생성 함수. OPS-7A·7B의 Docker 테스트와 OPS-9A smoke는 PdM 메시지를 이 함수로만 만든다 |
| `scripts/fake_feed.py`의 PdM 흉내, `tests/unit/test_fake_feed.py` | OPS-9B | 개발·사람 확인용 입력. 그 시점 PdM fixture와 키 집합이 같은지 `test_pdm_keys_match_fixture`가 본다. OPS-10이 먼저 끝났으면 fixture가 이미 확정본이라 OPS-9B가 확정 형식으로 만든다 |
| `docs/spec/02-mqtt.md` 3.6·3.7절, `AGREEMENTS.md` A-01·A-05·A-06, `07-runtime.md` 5절 | spec | 가정의 원본 |

**의미**가 다르면(윈도우 끝이 아닌 `timestamp`, retain true, 정지 중 발행 등) 재가동 기준 시각(03 1.2절)과 stale 규칙(06 4절)이 영향을 받는다. 이것은 OPS-10에서 고치지 않고 멈춘다(`contract`). 조율 agent가 PdM과 operations 중 어느 쪽을 맞출지 정한다(A-05).

## 5. OPS-10 `contract_ref` 채택 (M5)

착수 조건: **조율 agent가 Shared DOCUMENT_CHANGE(PdM Result, PdM Spectrum, Alarm Event) merge를 알림** — **충족**(2026-09-27, Shared PR #7, merge commit `cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8`). 채택 대상은 이 commit이다. `depends_on`은 OPS-2뿐이라 다른 task를 막지 않는다. OPS-2 merge 뒤 바로 하면 OPS-7A·7B·9A·9B가 처음부터 확정 형식(`pdm.py` 템플릿, fake_feed)으로 만들어진다. 언제 끼워 넣을지는 조율 agent가 정한다(`README.md` 4·6절).

### 5.1 확정본과 A-05·A-06의 차이 (2026-09-27, `cb6dc3c` INTERFACES를 읽고 정리)

의미(윈도우 끝 `timestamp`, Simulator 시계, retain false, QoS 1/0, `rpm == 0` 미발행, 재가동 뒤 첫 결과 = 재가동 chunk + 1초)는 A-05·A-06과 같다. 형식이 더 엄격하다. OPS-10이 고칠 것:

| 항목 | 지금 spec(A-05·A-06, 02 3.6·3.7절) | 확정본 | OPS-10 |
|---|---|---|---|
| PdM Result `window_start` | 선택 | 필수 | 없으면 `missing_field:window_start` |
| PdM Result `anomaly_score` | 범위 검사 없음 | 0 이상 1 이하 | 범위 밖이면 `invalid_field:anomaly_score` |
| PdM Result `model_version` | 선택 | 선택 | 그대로 |
| PdM Spectrum 필드 | 숫자 배열이면 모두 계열(느슨한 해석), 간격 없으면 bin | `rpm`, `freq_step_hz`, `rot_hz`, `bpfo_hz`, `bpfi_hz`, `spectrum_x/y/z`, `envelope_x/y/z`, `window_start` 모두 필수 | 하나라도 없으면 거부(직전 표시 유지) |
| PdM Spectrum 배열 | 길이 2~4096 | 여섯 개 길이가 같고 `floor(500 / freq_step_hz) + 1`, 원소는 유한한 0 이상, `freq_step_hz > 0` | 어기면 `invalid_field:<이름>` |
| 패널 | 이름에 `envelope`면 포락선 패널 | 같음(`spectrum_*` 3계열, `envelope_*` 3계열) | 그대로. `rot_hz`·`bpfo_hz`·`bpfi_hz`는 `SpectrumPanels`에 담기만 하고 화면 표시선은 이 task에서 하지 않는다 |
| 크기 | 256 KiB 상한 | 약 21 KB | 상한 유지 |
| Alarm Event | A-02 | A-02와 같음 | 예시가 fixture와 같은지만 확인 |

- 이 차이 때문에 OPS-2의 느슨한 해석 테스트 두 개(`test_spectrum_bins_without_step`: 간격 없음 → bin, `test_spectrum_no_series`: 배열 없음 → `no_series`)는 확정본에서 **거부**가 맞다. OPS-10은 이 두 테스트를 같은 이름으로 두고 기대값을 "거부(`missing_field:freq_step_hz` / `missing_field:spectrum_x`)"로 바꾼다. 느슨하게 바꾸는 것이 아니라 계약에 맞춰 더 엄격하게 하는 것이므로 이 계획이 허용한다(D-46). spec 08 3.2절 스펙트럼 목록도 같이 고친다.

```yaml
  - id: OPS-10
    milestone: M5
    type: chore
    title: Shared cb6dc3c(PdM Result·PdM Spectrum·Alarm Event 확정)를 contract_ref로 채택하고 파서·fixture·spec을 맞춤
    why: 조율 agent가 Shared DOCUMENT_CHANGE(PdM Result, PdM Spectrum, Alarm Event) merge를 알렸다(Shared PR #7, cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8). integration의 계약 검사가 Shared 한 곳을 기준으로 하도록 이 Component도 그 commit을 기준으로 삼고, A-05·A-06 가정과 확정본의 형식 차이(02-mqtt 계획 5.1절)를 PdM 형식 의존 자리에서 맞춘다 (조율 C-04·C-05, spec D-04·D-39·D-46, C-01)
    depends_on: [OPS-2]
    contract: [docs/INTERFACES.md, docs/CONVENTIONS.md]
    scope: [SHARED_CONFIG.json, src/factory_operations/mqtt/payloads.py, tests/unit/test_payloads.py, tests/fixtures/payloads/**, scripts/fake_feed.py, tests/unit/test_fake_feed.py, docs/spec/02-mqtt.md, docs/spec/07-runtime.md, docs/spec/08-verification.md, docs/spec/AGREEMENTS.md, docs/spec/README.md, docs/spec/DECISIONS.md, docs/COMPONENT.md]
    acceptance:
      - id: A1
        text: SHARED_CONFIG.json의 contract_ref가 cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8이고 다른 필드는 main과 같다 (C-05)
        check:
          type: command
          run: |
            test "$(jq -r .contract_ref SHARED_CONFIG.json)" = cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8 || { echo "contract_ref mismatch"; exit 1; }
            test "$(git show origin/main:SHARED_CONFIG.json | jq -S 'del(.contract_ref)')" = "$(jq -S 'del(.contract_ref)' SHARED_CONFIG.json)" || { echo "other fields changed"; exit 1; }
      - id: A2
        text: 저장소 검사가 원격 비교까지 통과한다
        check: {type: command, run: "python3 agent/core/tools/validate.py --remote"}
      - id: A3
        text: contract_ref INTERFACES의 PdM Result·Alarm Event 예시 JSON이 fixture(shared_pdm_result.json, shared_alarm_event.json)와 같고, 파서가 확정 예시 fixture(shared_pdm_spectrum.json 포함)를 받으며 확정본의 거부 예를 거부하고, build_alarm의 키 집합이 Shared Alarm Event 예시와 같다 (C-01)
        check:
          type: command
          run: |
            sha=$(jq -r .contract_ref SHARED_CONFIG.json); f=$(mktemp)
            gh api --method GET repos/dltndn-personal-project/smart-factory-shared-repository/contents/docs/INTERFACES.md -f ref="$sha" -H 'Accept: application/vnd.github.raw+json' > "$f" || exit 1
            python3 - "$f" <<'EOF' || exit 1
            import json, re, sys
            fence = "`" * 3
            blocks = []
            for body in re.findall(fence + r"json\n(.*?)" + fence, open(sys.argv[1]).read(), re.S):
                try:
                    blocks.append(json.loads(body))
                except ValueError:
                    pass
            bad = [n for n in ("shared_pdm_result.json", "shared_alarm_event.json") if json.load(open("tests/fixtures/payloads/" + n)) not in blocks]
            print("not a Shared example:", bad)
            sys.exit(1 if bad else 0)
            EOF
            make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_shared_pdm_result_example tests/unit/test_payloads.py::test_shared_pdm_result_reject_example tests/unit/test_payloads.py::test_shared_pdm_spectrum_example tests/unit/test_payloads.py::test_build_alarm_matches_shared_example
      - id: A4
        text: 5.1절 차이대로 PdM Result window_start 필수·anomaly_score 0~1, 스펙트럼 필수 필드·배열 길이 규칙(floor(500/freq_step_hz)+1, 여섯 개 같음)·유한한 0 이상 원소·freq_step_hz > 0을 검사하고, 간격 없음·배열 없음은 거부된다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_payloads.py::test_pdm_result_window_start_required tests/unit/test_payloads.py::test_pdm_result_anomaly_score_range tests/unit/test_payloads.py::test_spectrum_requires_all_fields tests/unit/test_payloads.py::test_spectrum_length_rule tests/unit/test_payloads.py::test_spectrum_values_finite_nonnegative tests/unit/test_payloads.py::test_spectrum_bins_without_step tests/unit/test_payloads.py::test_spectrum_no_series"}
      - id: A5
        text: 단위 테스트 전체가 통과한다 (pdm.py 생성 함수와, 있으면 fake_feed 메시지도 확정 형식으로 받아진다)
        check: {type: command, run: "make test"}
      - id: A6
        text: spec README·AGREEMENTS·COMPONENT.md가 채택한 SHA를 적고, README와 02 3.7절에서 PdM 가정·느슨한 해석 문구가 사라졌다
        check: {type: command, run: "sha=cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8 && grep -q \"$sha\" docs/spec/AGREEMENTS.md && grep -q \"$sha\" docs/spec/README.md && grep -q \"$sha\" docs/COMPONENT.md && ! grep -q '생산자 확정 전 가정' docs/spec/README.md && ! grep -q '느슨한 해석' docs/spec/02-mqtt.md"}
    size: M
```

단계 개요:
1. `SHARED_CONFIG.json` `contract_ref`만 `cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8`로 바꾼다. → A1
2. `90-shared.md` 1절 명령으로 그 commit의 `docs/INTERFACES.md`(PdM Result, PdM Spectrum, Alarm Event 절), `docs/CONVENTIONS.md`를 읽고 5.1절 표와 다른 점이 없는지 확인한다. 5.1절 밖의 차이, 특히 **의미 차이**(4절)가 있으면 멈춘다(`contract`). PR 본문에 비교표를 적는다.
3. fixture: `shared_pdm_result.json`, `shared_alarm_event.json`(원문 JSON 그대로), `shared_pdm_spectrum.json`(원문 예시의 스칼라 필드 그대로 + 여섯 배열은 seed 고정 501개, 소수 4자리, 0 이상. 원문 배열은 `"… 501개"` 설명 문자열이 있어 그대로 쓸 수 없다). 확정본의 거부 예(PdM Result `timestamp` 밀리초 없음·`window_start` 없음·소문자 `state`)를 테스트 입력으로 쓴다. 가정 fixture `pdm_result_draft.json`·`pdm_spectrum_*.json`은 지우거나 확정 형식으로 바꾸고, `pdm.py` 템플릿을 확정 fixture로 바꾼다. `SOURCES.md`에 출처(`cb6dc3c`) 기록. → A3
4. `payloads.py` 두 파서를 5.1절대로 고치고 테스트를 추가·수정한다(`test_spectrum_bins_without_step`·`test_spectrum_no_series`는 이름을 두고 거부 기대로, D-46). 연동 테스트·smoke는 `pdm.py`를 쓰므로 따로 고치지 않는다(`make docker-test`·`make smoke` verify가 확인). → A3, A4
5. `scripts/fake_feed.py`가 있으면(OPS-9B 뒤) PdM 흉내를 확정 형식(필드 전부, `rot_hz`·`bpfo_hz`·`bpfi_hz`, `envelope_x/y/z`)으로 바꾼다. → A5
6. spec: `02-mqtt.md` 3.6·3.7절(확정 형식, 느슨한 해석 삭제), `08-verification.md` 3.2절 스펙트럼 테스트 목록, `AGREEMENTS.md` 머리말·A-01·A-05·A-06(가정 → `cb6dc3c` 확정), `README.md` 머리말과 6절, `07-runtime.md` 5절(fake_feed 형식), `docs/COMPONENT.md` 외부 의존 절, DECISIONS에 채택 기록. → A6
7. `make test`, `validate.py --remote`. → A2, A5

- `SHARED_ISSUE_STATUS.yaml`은 바꾸지 않는다. Shared Issue 검토는 사용자가 요청할 때만 한다(AGENTS.md Shared 절).
- 화면의 `rot_hz`·`bpfo_hz`·`bpfi_hz` 표시선은 선택 기능이라 이 task에 넣지 않았다. 필요하면 조율 agent가 화면 FIX task로 추가한다.

읽을 spec: 이 절 5.1, `AGREEMENTS.md` 머리말·A-01·A-02·A-05·A-06, 02 3.6·3.7절, 07 5절, 08 3.2절, `agent/core/process/90-shared.md` 1절, D-04·D-32·D-39·D-46.
