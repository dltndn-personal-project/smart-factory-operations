# 02 MQTT: 연결, 구독, 입력 검증, 발행

> 목적: MQTT client 동작, 구독 Topic, 입력 Payload 검증 규칙, 발행 Payload 생성과 발행 규칙을 정한다. 다른 Component와의 형식 약속의 원본은 `AGREEMENTS.md`(Shared 확정 Interface는 Shared INTERFACES)다.
> 읽어야 할 때: `mqtt/`(OPS-2, OPS-6), 새 필드를 받거나 보낼 때.

## 1. client

- 라이브러리: paho-mqtt 2.1.0(`DECISIONS.md` D-08). `mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2, client_id=mqtt.client_id, protocol=MQTTv311, clean_session=True)`.
- `mqtt.url`은 `mqtt://host[:port]`만 받는다(포트 생략 시 1883). 다른 scheme이면 설정 오류.
- 기동: `reconnect_delay_set(reconnect_min_s, reconnect_max_s)` → `max_queued_messages_set(max_queued)` → `connect_async(host, port, keepalive=keepalive_s)` → `loop_start()`. LWT는 두지 않는다(Operations 상태를 받는 Component가 없다).
- 콜백은 paho 스레드에서 돈다. `on_connect`(성공): 2절 Topic을 한 번의 `subscribe([...])`로 구독, `mqtt_connected = True`, INFO 로그. 실패 reason code: WARNING, paho가 재시도. `on_disconnect`: `mqtt_connected = False`, WARNING(정상 종료 중이면 INFO). `on_message`: `Inbound`를 만들어 inbound 큐에 `put_nowait`만 한다.
- 인증·TLS 없음(Shared 13절).

| 설정 키 | 기본값 |
|---|---|
| `mqtt.client_id` | `factory-operations` |
| `mqtt.topic_prefix` | `factory` (환경 변수 `TOPIC_PREFIX`) |
| `mqtt.keepalive_s` | 30 |
| `mqtt.reconnect_min_s` | 1 |
| `mqtt.reconnect_max_s` | 10 |
| `mqtt.max_queued` | 100 |

## 2. Topic

`topics.py`가 접두사 `p`로 만든다. QoS·retain은 코드 상수다(설정 아님).

| 방향 | Interface | Topic | 구독 QoS / 발행 QoS·retain | 원본 |
|---|---|---|---|---|
| 구독 | Sensor Vibration | `{p}/sensor/+/vibration` | 0 | Shared INTERFACES |
| 구독 | Product Created | `{p}/product/created` | 1 | Shared INTERFACES |
| 구독 | Line Status | `{p}/line/status` | 1 (retained 메시지를 정상으로 받는다) | Shared INTERFACES |
| 구독 | Vision Result | `{p}/vision/result` | 1 | Shared INTERFACES |
| 구독 | PdM Result | `{p}/pdm/result` | 1 | `AGREEMENTS.md` A-05 |
| 구독 | PdM Spectrum | `{p}/pdm/spectrum` | 0 | `AGREEMENTS.md` A-06 |
| 발행 | Conveyor Control | `{p}/control/conveyor` | QoS 1, retain false | Shared INTERFACES, `AGREEMENTS.md` A-03 |
| 발행 | Alarm Event | `{p}/alarm/event` | QoS 1, retain false | `AGREEMENTS.md` A-02 |

## 3. 입력 검증

`payloads.py`의 `parse_<kind>(topic, raw: bytes) -> Parsed | Rejected(reason)`. 순수 함수다. 거부된 메시지는 적용하지 않고 `message_rejected` 로그(01 6절)와 카운터만 남긴다. 오류 응답 Topic은 없다(Shared CONVENTIONS).

### 3.1 공통 규칙 (모든 입력)

1. UTF-8 JSON 객체가 아니면 `invalid_json`.
2. `schema_version`이 정수 1이 아니면(bool 포함) `unsupported_schema_version`.
3. 아래 표의 "검사" 열 필드가 없으면 `missing_field:<이름>`, 형식이 틀리면 `invalid_field:<이름>`. 첫 실패 하나만 사유로 쓴다.
4. 표에 없는 필드는 무시한다(모르는 필드 무시, Shared CONVENTIONS). "선택" 필드가 없거나 형식이 틀리면 null로 두고 메시지는 받는다.
5. 형식 이름: `ts` = `clock.parse_ts` 통과, `number` = int 또는 float(bool 제외, 유한값), `int` = int(bool 제외) 또는 `is_integer()`인 float, `sensor_id` = `^[a-z][a-z0-9_]{0,31}$`, `product_id` = `^P-[0-9]{8}$`.
6. 이미지 경로 형식 `rel_path(dir)`: `dir/`로 시작, `/`로 나눈 모든 조각이 비어 있지 않고 `.`으로 시작하지 않으며 `..`가 없음, 절대 경로 아님, 확장자 `.jpg`·`.jpeg`·`.png`, 전체 200자 이하.

### 3.2 Sensor Vibration

| 필드 | 검사 |
|---|---|
| `sensor_id` | `sensor_id`이고 Topic의 `+` 자리 값과 같다(다르면 `topic_mismatch`) |
| `timestamp` | `ts` |
| `seq` | `int` ≥ 0 |
| `sample_rate_hz` | `int` > 0 |
| `rpm` | `number` ≥ 0 |
| `temperature` | `number` |
| `vibration_x`, `vibration_y`, `vibration_z` | `number`의 배열, 세 길이가 같고 1~10000 |

결과: `SensorChunk(sensor_id, timestamp, seq, sample_rate_hz, rpm, temperature, x, y, z)`. 배열은 `numpy.asarray(..., dtype=float32)`. 원소 검사는 `numpy.isfinite(arr).all()`로 한다(초당 3만 개 원소를 파이썬 루프로 보지 않는다).

### 3.3 Line Status

`online`(bool)을 먼저 본다. 없거나 bool이 아니면 `missing_field:online`/`invalid_field:online`.

- `online: false` → `LineOffline()`. 다른 필드는 보지 않는다(offline 메시지에는 다른 필드가 없다).
- `online: true` → 아래를 검사한다.

| 필드 | 검사 / 선택 |
|---|---|
| `timestamp` | `ts` |
| `conveyor` | `RUNNING` \| `STOPPED` |
| `fault_level` | `int` 0~10 |
| `motor_rpm` | `number` |
| `sensor_id` | `sensor_id` |
| `production_active` | bool |
| `products` | 선택. 객체이고 `spawned`·`created`·`expired`·`in_flight`가 `int`, `last_product_id`가 `product_id` 또는 null이면 그대로, 아니면 null |
| `last_command` | 선택. null이거나, 객체이고 `result`가 `APPLIED`\|`NO_CHANGE`\|`REJECTED`이면 받는다. 그 안의 `command_id`(1~64자 문자열 또는 null), `command`(`START`\|`STOP`\|null), `source`, `reason`, `error`(문자열 또는 null), `received_at`(`ts` 또는 null)은 형식이 틀리면 그 값만 null. `result`가 틀리면 `last_command` 전체를 null |

결과: `LineStatus(...)`. `products`·`last_command`가 null로 바뀐 경우는 DEBUG 로그만 남긴다(Interlock에 필요한 핵심 필드가 멀쩡하면 메시지를 버리지 않는다).

### 3.4 Product Created

| 필드 | 검사 |
|---|---|
| `product_id` | `product_id` |
| `timestamp` | `ts` |
| `image_path` | `rel_path(products)` |

### 3.5 Vision Result

| 필드 | 검사 / 선택 |
|---|---|
| `product_id` | `product_id` |
| `timestamp` | `ts` |
| `defect` | bool |
| `image_path` | `rel_path(products)` |
| `defect_type` | 선택. `^[a-z][a-z_]{0,31}$` 문자열 또는 null (현재 값은 `scratch`, `dent`, `contamination`) |
| `confidence` | 선택. `number` 0~1 또는 null |
| `bbox` | 선택. `int` 4개 배열 또는 null |
| `gradcam_path` | 선택. `rel_path(gradcam)` 또는 null |
| `judgement_source` | 선택. 1~32자 문자열 또는 null |

Shared는 `defect_type`·`confidence`·`bbox`·`gradcam_path`의 **키**를 필수로 정했지만, Operations는 키가 없어도 null로 받는다. 형식 준수 검사는 integration이 한다. `defect = false`인데 `defect_type`이 있으면 그대로 저장한다(판정은 생산자 책임).

### 3.6 PdM Result

생산자는 predictive-maintenance다. Shared 확정 전에는 PdM 아키텍처 6.2절 초안(조율 C-15)에 맞춘다(`AGREEMENTS.md` A-05). Operations가 쓰는 필드만 검사한다.

| 필드 | 검사 / 선택 |
|---|---|
| `sensor_id` | `sensor_id` |
| `timestamp` | `ts`. 분석 윈도우의 끝 |
| `anomaly_score` | `number` (범위는 검사하지 않고 그대로 저장·표시) |
| `health_index` | `int` 0~100 |
| `state` | `NORMAL` \| `CAUTION` \| `WARNING` \| `CRITICAL` (그 밖의 값은 `invalid_field:state`) |
| `window_start` | 선택. `ts` |
| `model_version` | 선택. 1~64자 문자열 |

### 3.7 PdM Spectrum (표시 전용, 느슨한 해석)

필드 구성은 PdM spec이 정한다(조율 C-12). Operations는 이름에 느슨하게 의존하고 **화면 표시에만** 쓴다(`AGREEMENTS.md` A-06).

- 메시지 크기가 256 KiB를 넘으면 `too_large`.
- 검사: `sensor_id`(`sensor_id`), `timestamp`(`ts`). 나머지는 아래 규칙으로 해석한다.
- **계열**: 최상위 키 중 값이 `number` 배열(길이 2~4096)인 것. 키 이름에 `envelope`가 들어 있으면 "포락선 스펙트럼" 패널, 아니면 "스펙트럼" 패널에 넣는다. 한 패널 안의 계열 순서는 키 이름 오름차순.
- **주파수 축**: 스펙트럼 패널은 `freq_step_hz`(양수 `number`), 포락선 패널은 `envelope_freq_step_hz`가 있으면 그것, 없으면 `freq_step_hz`. 시작 주파수는 같은 방식으로 `freq_start_hz`/`envelope_freq_start_hz`, 없으면 0. 간격을 모르면 `x_step = 1`, 단위 `bin`으로 둔다.
- 계열이 하나도 없으면 `no_series`로 거부한다.
- 결과: `SpectrumPanels(sensor_id, timestamp, window_start|null, panels=[{title, x_start, x_step, x_unit, series=[{name, values(float32)}]}])`. 계열 값은 소수 4자리로 반올림해 화면에 보낸다(06 3절).

## 4. 발행

### 4.1 Payload 생성

순수 함수. 직렬화는 `json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()`.

- `build_conveyor(command, command_id, now) -> dict`: `{"schema_version": 1, "command": command, "command_id": command_id, "timestamp": iso_ms(now), "reason": reason}`. `command_id`는 `str(uuid.uuid4())`(36자). `timestamp`는 발행 직전 `clock.wall()`. `reason` 값은 `03-control.md` 3·4절(`INTERLOCK_CRITICAL`, `OPERATOR_START`, `OPERATOR_STOP`).
- `build_alarm(alarm) -> dict`: `AGREEMENTS.md` A-02 형식 그대로.

### 4.2 발행 규칙

- `publish(topic, payload, qos=1, retain=False) -> bool`. `mqtt_connected`가 False이면 **발행하지 않고** False를 돌려준다. paho 대기열에 넣었다가 재연결 뒤 오래된 명령이 나가는 것을 막기 위해서다(`DECISIONS.md` D-20). paho `publish()`의 반환 코드가 성공이 아니면 ERROR 로그와 함께 False.
- 호출자 처리: Conveyor Control이 False이면 명령을 만들지 않은 것으로 본다(DB 기록·대기 상태 없음, 03 3·4절). Alarm Event가 False이면 DB 기록은 그대로 하고 발행만 빠진다(로그 `alarm_publish_skipped`).
- 발행 순서: 같은 PdM Result에서 Alarm Event와 STOP이 함께 생기면 Alarm Event를 먼저 발행한다(03 2절 처리 순서).
- 같은 client 연결에서 QoS 1로 보낸 두 메시지는 broker에 보낸 순서대로 간다(MQTT 3.1.1 순서 보장). 수신자 도착 순서는 Topic이 다르면 보장되지 않는다(Shared INTERFACES).

## 5. 연결 상태와 재연결

- Broker가 기동 때 없거나 도중에 끊겨도 프로세스는 계속 돈다. paho가 1초부터 10초까지 늘려 가며 재연결한다.
- 끊긴 동안: 입력 없음, 발행하지 않음(4.2절), `/readyz` 503, 화면 상단 "MQTT 끊김".
- clean session이라 끊긴 동안의 메시지는 받지 못한다. 재연결 뒤 Line Status는 retain으로 바로 받는다. 끊긴 동안 놓친 PdM Result·Vision Result는 복구하지 않는다(Shared 12절).
