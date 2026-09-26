# 03 판단: 라인 상태, Interlock, 운영자 명령, Alarm

> 목적: 도메인 워커가 메시지를 처리하는 순서, Line Status 추적과 재가동 기준 시각, Interlock STOP 규칙, 운영자 START/STOP, 명령 결과 확인, Alarm 규칙을 정한다.
> 읽어야 할 때: `domain/line.py`, `interlock.py`, `alarm.py`, `worker.py`(OPS-3, OPS-6), 시나리오 테스트.

## 1. Line Status 추적 (`LineTracker`)

### 1.1 상태

| 값 | 의미 |
|---|---|
| `line_state` | `UNKNOWN` \| `RUNNING` \| `STOPPED`. 기동 직후 `UNKNOWN`. `online: false`를 받으면 `UNKNOWN` |
| `latest` | 마지막으로 받은 `LineStatus`(online true)와 수신 시각. `online: false`를 받아도 지우지 않는다(화면에 마지막 값 표시) |
| `online` | null(미수신) \| true \| false |
| `reference_time` | **재가동 기준 시각**. null 또는 Payload timestamp(Simulator 시계). 1.2절 |
| `fault_changes` | `(timestamp, fault_level)` 변화점 목록(04 1절 결합용). `timestamp`가 최근 600초 안인 변화점과, 그보다 오래된 것 중 **가장 최근 변화점 하나**를 유지한다(값이 10분 넘게 그대로여도 현재 구간의 시작점이 남는다) |
| `last_conveyor` | 마지막으로 받은 online Line Status의 `conveyor`. `online: false`를 받아도 바꾸지 않는다. 재가동 이벤트 판정용 |
| `line_sensor_id` | `latest.sensor_id`, 없으면 설정 `line.sensor_id` |

### 1.2 갱신 규칙

`online: false` 수신:
1. `online = false`, `line_state = UNKNOWN`.
2. 이전 `online`이 false가 아니었으면 `line_status_change` 행을 쓴다(05 2절, `timestamp` null).

`online: true` 수신(`ls`):
1. `new = ls.conveyor`. `new == RUNNING`이고 `line_state != RUNNING`(즉 `UNKNOWN` 또는 `STOPPED`에서 바뀜)이면 `reference_time = ls.timestamp`로 둔다. 기동 뒤 처음 받은 Line Status가 `RUNNING`인 경우와 `online: false` 뒤 `RUNNING`도 여기에 해당한다.
   - 이 중 `last_conveyor == STOPPED`이고 `new == RUNNING`인 경우만 **재가동 이벤트**를 낸다(4절 Alarm 초기화). 사이에 `online: false`가 끼어도 된다(정지 상태에서 simulator 재기동). 기동 직후 첫 동기화(`last_conveyor` null)와 가동 중의 끊김 후 복귀(`RUNNING → offline → RUNNING`)는 재가동 이벤트가 아니다. 실제 정지·재가동이 없었는데 Alarm이 다시 나가지 않게 하기 위해서다.
   - 그다음 `last_conveyor = new`.
2. `line_state = new`, `online = true`, `latest = ls`.
3. 이전에 기록한 값과 `online`, `conveyor`, `fault_level`, `production_active` 중 하나라도 다르거나 첫 수신이면 `line_status_change` 행을 쓴다. 1초 주기 메시지는 쓰지 않는다.
4. 마지막 변화점과 `fault_level`이 다르거나 변화점이 없으면 `(ls.timestamp, ls.fault_level)`을 추가한다.
5. 명령 결과 확인(3.4절) → Interlock 평가(3.2절).

- 재가동 기준 시각의 목적: 정지 중에는 PdM이 결과를 내지 않으므로(`rpm == 0` 미발행, `AGREEMENTS.md` A-05) 정지 원인이 된 `CRITICAL`이 마지막 결과로 오래 남는다. 기준 시각 이후의 결과만 판정에 쓰면, 재가동 직후 그 옛 결과로 다시 멈추지 않고, 재가동 뒤 PdM이 새로 `CRITICAL`을 내면 다시 멈춘다.
- 기준 시각과 PdM `timestamp`는 둘 다 Simulator 시계 값이라 직접 비교한다(01 5절). PdM은 rpm이 바뀌면 버퍼를 비우고 가동 chunk 10개(1초)를 모은 뒤 첫 결과를 내므로, 재가동 뒤 첫 결과의 `timestamp`(윈도우 끝)는 재가동을 알린 Line Status의 `timestamp`보다 약 1초 뒤다. 재가동 전 윈도우의 결과는 정지 시각보다 앞선다. 따라서 `pdm.timestamp > reference_time` 비교로 둘이 갈린다.

## 2. 워커의 메시지 처리 순서

한 메시지를 끝까지 처리한 뒤 다음 메시지를 꺼낸다. 파싱 실패는 02 3절대로 버린다.

| 입력 | 처리 순서 |
|---|---|
| Sensor Vibration | `fault_level` 결합(04 1.1절) → DB 큐에 센서 행 → `sensor_id == line_sensor_id`이면 진동 링 버퍼에 추가. 링의 마지막 chunk와 `sample_rate_hz`나 배열 길이가 다르면, 또는 `seq`가 직전 값 + 1이 아니면 링을 비우고 이 chunk부터 다시 채운다 |
| Line Status | 1.2절 |
| Product Created | DB 큐에 `product` 행 |
| Vision Result | `health_index_at_time` 결합(04 1.2절) → DB 큐에 `inspection` 행 |
| PdM Result | `pdm_latest`·`pdm_history` 갱신 → DB 큐에 `equipment_state` 행 → **Alarm 대상**이면 Alarm 평가(4절) → **판정 대상**이면 Interlock 평가(3.2절) |
| PdM Spectrum | `sensor_id == line_sensor_id`이면 `spectrum_latest` 교체. 아니면 버림 |
| 운영자 명령 | 3.3절 |
| tick(0.1초마다) | 대기 중 STOP 시간 초과 처리(3.2절) |

**판정 대상** PdM Result(Interlock): `sensor_id == line_sensor_id`이고, `reference_time`이 null이거나 `timestamp > reference_time`인 결과.

**Alarm 대상** PdM Result: 라인 센서는 판정 대상과 같은 조건, 라인 센서가 아닌 센서는 모든 결과. 라인 센서가 아닌 센서의 결과는 기록·Alarm만 하고 Interlock에는 쓰지 않는다(현재 시스템은 센서 하나).

## 3. Interlock과 명령

### 3.1 상태 (`Interlock`)

| 값 | 의미 |
|---|---|
| `judged` | 판정 대상 결과 중 가장 최근(`timestamp` 최대) 것. `reference_time`이 바뀌면 조건에 맞지 않는 결과는 판정 대상에서 빠진다 |
| `pending` | 대기 중인 STOP: `command_id`, 발행 `mono` 시각. 없으면 null |
| `last_trigger_ts` | 마지막으로 STOP을 낸 PdM Result의 `timestamp` |

### 3.2 STOP 규칙

평가 시점: 판정 대상 PdM Result를 처리한 직후, Line Status를 처리한 직후, `pending`이 시간 초과로 끝난 tick. 평가는 메시지 처리 안에서 바로 한다(tick을 기다리지 않는다).

1. `pending`이 있고 `mono() − pending.issued_mono ≥ interlock.pending_timeout_s`이면 `pending = null`, `interlock_pending_timeout` WARNING 로그. `control` 행의 `result`는 null로 남는다.
2. 다음이 **모두** 참이면 STOP을 발행한다.
   - `judged`가 있고 `judged.state == CRITICAL`
   - `line_state`가 `RUNNING` 또는 `UNKNOWN`(Line Status 미수신·`online: false`. 알 수 없을 때 보내는 것은 안전 쪽 선택이다. 이미 정지면 simulator가 `NO_CHANGE`)
   - `pending`이 null
   - `last_trigger_ts`가 null이거나 `judged.timestamp > last_trigger_ts` (**같은 PdM 결과로 STOP을 두 번 내지 않는다**)
3. 발행: `build_conveyor("STOP", uuid4, "INTERLOCK_CRITICAL", now)`. `publish`가 False(MQTT 끊김)이면 아무것도 바꾸지 않고 `interlock_publish_skipped` WARNING 로그. 다음 평가에서 다시 판단한다.
4. 발행 성공: `pending = (command_id, mono())`, `last_trigger_ts = judged.timestamp`, DB 큐에 `control` INSERT(`origin: operations`, `trigger_sensor_id`, `trigger_timestamp = judged.timestamp`), `command_published` INFO 로그.

결과(3.4절)에 따른 `pending` 종료:
- `APPLIED` 또는 `NO_CHANGE` → 즉시 `pending = null`.
- `REJECTED` → ERROR 로그만. `pending`은 시간 초과까지 유지한다(simulator가 계속 거부할 때 0.5초마다 STOP을 반복하지 않게).

결과로 생기는 동작:
- PdM은 `CRITICAL` 동안 0.5초마다 결과를 낸다. STOP은 한 번 나가고, 5초 안에 결과를 못 보면 그 뒤 첫 새 `CRITICAL` 결과로 한 번 더 나간다.
- PdM이 멈춘 상태로 마지막 결과가 `CRITICAL`이고 라인이 `UNKNOWN`이어도 새 결과가 없으므로 STOP을 반복하지 않는다.
- 재가동(운영자 START, simulator 로컬 START, simulator 재기동은 항상 `RUNNING`) 뒤 PdM이 다시 `CRITICAL`을 내면 약 1~2초 뒤 다시 멈춘다.
- 지연 목표: `CRITICAL` PdM Result 수신부터 STOP 발행까지 1초 이내(C-05). 워커 처리 한 번 안에서 끝나므로 보통 수 ms다.

### 3.3 운영자 명령

- 경로: `POST /api/conveyor`(06 2절) → `OperatorCommand(command, future)`를 inbound 큐에 넣는다 → 워커가 처리하고 future에 결과를 넣는다. HTTP는 최대 2초 기다린다. 도메인 상태를 워커 하나만 바꾸게 하기 위해서다.
- 워커: `publish`가 False이면 future에 `mqtt_disconnected` 오류. 성공이면 DB 큐에 `control` INSERT(`origin: operations`, `reason: OPERATOR_START | OPERATOR_STOP`, trigger 필드 null)하고 future에 `{command_id, command, timestamp, judged_state}`를 넣는다.
- Operations는 자동으로 `START`하지 않는다. `judged.state == CRITICAL`이어도 `START`를 막지 않는다. 화면이 확인 창으로 경고한다(06 5절). Fault Level을 낮추는 것은 simulator 화면에서 사람이 한다.
- 운영자 STOP은 Interlock의 `pending`·`last_trigger_ts`에 영향을 주지 않는다. 결과는 3.4절로 같은 방식으로 기록된다.

### 3.4 명령 결과 확인

- 워커는 최근 발행한 명령 100개를 `issued[command_id]`로, 결과를 처리한 `command_id` 200개를 `seen` 집합으로 기억한다.
- Line Status의 `last_command`가 있고 `command_id`가 null이 아니며 `seen`에 없으면:
  - `issued`에 있으면: DB 큐에 `control` 결과 UPDATE(`result`, `result_received_at = last_command.received_at`, `error`, `observed_at = now`), `command_result` INFO 로그(REJECTED면 ERROR), 3.2절 `pending` 종료 규칙.
  - 없으면(simulator 로컬 명령, 재시작 전 명령): DB 큐에 `control` observed INSERT(`origin: observed`, `command`, `reason`, `source`, 결과 필드). 같은 `command_id` 행이 이미 있으면 DB가 무시한다(05 2절).
  - `seen`에 추가한다. Line Status는 1초마다 같은 `last_command`를 다시 싣고 오므로 한 번만 처리한다.
- `command_id`가 null인 `last_command`(retained·잘못된 JSON 거부)는 기록하지 않고 WARNING 로그만 남긴다.

## 4. Alarm

- 값: Equipment State 심각도 `NORMAL` 0 < `CAUTION` 1 < `WARNING` 2 < `CRITICAL` 3. Operations는 Health Index로 상태를 다시 계산하지 않고 PdM의 `state`를 그대로 쓴다(Shared 17절).
- `AlarmManager`는 `sensor_id`별로 이전 상태 `prev`(처음 null, 심각도 −1로 본다)를 기억한다.
- Alarm 대상 PdM Result `r`(2절)마다:
  1. `r.state`가 `WARNING` 또는 `CRITICAL`이고 심각도가 `prev`보다 크면 Alarm을 만든다: `alarm_id = uuid4`, `timestamp = r.timestamp`, `raised_at = now`, `severity = r.state`, `previous_state = prev`, `health_index`, `anomaly_score`.
  2. `prev = r.state`.
- Alarm 처리: DB 큐에 `alarm` INSERT → Alarm Event 발행(02 4.2절, 실패해도 DB 기록은 유지) → `alarm_raised` INFO 로그.
- 재가동 이벤트(1.2절)에서 라인 센서의 `prev`를 null로 되돌린다. 재가동 뒤 다시 `WARNING`·`CRITICAL`이 되면 새 Alarm이 생긴다.
- `CAUTION` 진입과 회복 방향 전이는 Alarm이 아니다. 모든 PdM Result가 `equipment_state`에 남으므로 이력으로 확인한다. 확인(ack)·해제 상태와 떨림(flapping) 억제는 두지 않는다(평활화는 PdM 책임).
- 한 PdM Result에서 Alarm과 STOP이 함께 생기면 Alarm Event를 먼저 발행한다(2절 순서).

## 5. 설정

| 키 | 기본값 | 의미 |
|---|---|---|
| `line.sensor_id` | `motor01` | Line Status에 `sensor_id`가 없을 때(미수신) 라인 센서로 쓸 값 |
| `interlock.pending_timeout_s` | 5.0 | 대기 중 STOP의 결과를 기다리는 시간. 0.5~60 |

## 6. 시나리오 (단위 테스트, `tests/unit/test_interlock.py`, `test_alarm.py`)

가짜 시계·가짜 발행기(`publish` 호출 기록, 연결 여부 조절)·가짜 DB 싱크로 워커의 처리 함수를 직접 부른다. `t0`는 임의 Simulator 시각, "LS R"은 `online: true, conveyor: RUNNING`, "LS S"는 `STOPPED`, "PdM X@t"는 라인 센서 `state X`, `timestamp t`.

| ID | 입력 순서 | 기대 |
|---|---|---|
| S-01 | LS R@t0, PdM CRITICAL@t0+1 | STOP 1건(`reason INTERLOCK_CRITICAL`), `control` INSERT 1건(`trigger_timestamp = t0+1`) |
| S-02 | S-01 뒤 PdM CRITICAL@t0+1.5, @t0+2 (시계 1초 진행) | 추가 STOP 없음 |
| S-03 | S-01 뒤 LS S(`last_command` 같은 id, `APPLIED`) | `pending` null, `control` UPDATE 1건. 이어서 PdM CRITICAL@t0+1.5가 와도 STOP 없음(`STOPPED`) |
| S-04 | S-01 뒤 결과 없이 시계 4.9초 → PdM CRITICAL@t0+6 → 시계 0.2초 → tick → PdM CRITICAL@t0+6.5 | CRITICAL@t0+6 처리 때 STOP 없음. tick(시간 초과)에서 두 번째 STOP(`trigger_timestamp = t0+6`). CRITICAL@t0+6.5에는 STOP 없음(새 대기 중) |
| S-05 | S-01 뒤 시계 6초, tick 여러 번(새 결과 없음) | 추가 STOP 없음 |
| S-06 | (LS 없음) PdM CRITICAL@t0 / LS offline 뒤 PdM CRITICAL@t0+1 | 각각 STOP 1건 |
| S-07 | LS R@t0, PdM CRITICAL@t0+1 → STOP → LS S(APPLIED) → LS R@t0+30(운영자 START) | LS R@t0+30 처리 뒤 STOP 없음. 이어 PdM CRITICAL@t0+31.1 → STOP |
| S-08 | S-07과 같되 재가동 대신 LS offline → LS R@t0+30 | S-07과 같다 |
| S-09 | S-01 뒤 LS R(`last_command` 같은 id, `REJECTED`) → PdM CRITICAL@t0+2 → 시계 5초 → tick | CRITICAL@t0+2 처리 때 STOP 없음(대기 유지). tick에서 STOP(`trigger_timestamp = t0+2`) |
| S-10 | 발행기 끊김 상태에서 PdM CRITICAL@t0+1 → 연결 → PdM CRITICAL@t0+1.5 | 첫 결과에서 발행·기록 없음, 두 번째에서 STOP 1건 |
| S-11 | LS R@t0, PdM WARNING/CAUTION/NORMAL, 다른 센서(`motor02`)의 CRITICAL | STOP 없음 |
| S-12 | 운영자 START (연결됨 / 끊김) | `control` INSERT(`OPERATOR_START`)와 future 성공 / `mqtt_disconnected`. Interlock 상태 불변 |

| ID | 라인 센서 PdM `state` 순서 | 기대 Alarm (`severity`, `previous_state`) |
|---|---|---|
| L-01 | NORMAL, CAUTION, WARNING, CRITICAL | (WARNING, CAUTION), (CRITICAL, WARNING) |
| L-02 | 첫 결과 WARNING | (WARNING, null) |
| L-03 | CRITICAL, CRITICAL, WARNING, CRITICAL | (CRITICAL, null), (CRITICAL, WARNING) |
| L-04 | WARNING, CAUTION, WARNING | (WARNING, null), (WARNING, CAUTION) |
| L-05 | CRITICAL → 재가동 이벤트 → WARNING | (CRITICAL, null), (WARNING, null) |
| L-06 | 재가동 기준 시각 이전 `timestamp`의 CRITICAL | Alarm 없음, `equipment_state` 기록은 있음 |
| L-07 | LS R@t0, 첫 결과 CRITICAL@t0+1 | 발행기 기록 순서가 Alarm Event → STOP |
| L-08 | (LS 없음) WARNING@t0 → LS R@t0+0.2 → WARNING@t0+0.5 | (WARNING, null) 1건만(첫 동기화는 재가동 이벤트가 아님) |
| L-09 | LS R@t0, WARNING@t0+1 → LS offline → LS R@t0+3 → WARNING@t0+4 | (WARNING, null) 1건만(`RUNNING → offline → RUNNING`은 재가동 이벤트가 아님) |
| L-10 | LS R@t0, CRITICAL@t0+1 → LS S → LS offline → LS R@t0+30 → WARNING@t0+31.1 | (CRITICAL, null), (WARNING, null) (정지 상태에서 simulator 재기동은 재가동 이벤트) |
| L-11 | 라인 센서 `motor01` WARNING, 다른 센서 `motor02` WARNING | 센서마다 1건씩 2건, STOP 없음 |
