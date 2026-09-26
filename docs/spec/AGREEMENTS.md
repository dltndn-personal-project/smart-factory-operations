# 교차 Component 약속

> 목적: 이 Component가 다른 Component·Shared와 주고받는 것(MQTT Topic과 Payload, DB 스키마와 적용 방식, 실행 조건, 관찰 지점)을 정한다.
> 읽어야 할 때: MQTT 발행·구독, DB 스키마, Docker 실행 조건, Dashboard 관찰 지점을 구현하거나 바꿀 때. 다른 Component가 이 Component와 연동할 때.
> 지위(조율 C-04, `DECISIONS.md` D-04): Shared에 **확정**된 Interface(Sensor Vibration, Product Created, Vision Result, Conveyor Control, Line Status)와 CONVENTIONS는 Shared가 원본이고 이 파일은 Operations의 해석만 적는다. **Alarm Event**는 이 파일이 생산자 확정본이며 별도 subagent가 Shared DOCUMENT_CHANGE로 올린다. **PdM Result·PdM Spectrum**은 생산자(predictive-maintenance) spec과 Shared 확정본에 맞추며, 이 파일은 Operations가 기대는 가정을 적는다. 불일치가 생기면 조율 agent가 맞추고 OPS-10(`00-overview.md` 6절)에서 반영한다.
> 참고한 Shared: `dltndn-personal-project/smart-factory-shared-repository` `main@d0c997c97129141d9853a42ce6e0d1f8f7309ae9`의 `docs/ARCHITECTURE.md`, `docs/INTERFACES.md`, `docs/CONVENTIONS.md`(원격 Contents API, 2026-09-27). PdM 기준: predictive-maintenance `main@db9b7e7` `docs/ARCHITECTURE.md` 6.2절. simulator 기준: factory-simulator `docs/spec/AGREEMENTS.md`(SIM A-xx), `docs/spec/05-mqtt.md`.

항목 형식: **결정**, **근거**, **Shared 현재**, **바꿀 것**, **맞출 Component**.

## 목록

| ID | 항목 | 방향 | 맞출 Component |
|---|---|---|---|
| A-01 | Topic·QoS·retain 목록 | 구독·발행 | Shared |
| A-02 | Alarm Event (생산자 확정본) | 발행 | Shared, integration |
| A-03 | Conveyor Control 발행 규칙 | 발행 | 없음 (simulator 현재 동작과 일치) |
| A-04 | Line Status 해석 | 구독 | 없음 |
| A-05 | PdM Result에 대한 의존 | 구독 | predictive-maintenance, Shared |
| A-06 | PdM Spectrum에 대한 의존(표시 전용) | 구독 | predictive-maintenance, Shared |
| A-07 | Product Created·Vision Result 해석 | 구독 | 없음 |
| A-08 | DB 스키마와 적용 방식, 검증 조회 | 제공 | integration |
| A-09 | 실행 조건 | 제공 | integration |
| A-10 | Dashboard 갱신 측정 관찰 지점 | 제공 | integration |
| A-11 | Interlock·Alarm의 관찰 가능한 동작 | 제공 | integration |
| A-12 | Ground Truth 사용 제한 | — | integration |

factory-simulator에 바라는 변경은 없다(조율 C-00, C-15).

## A-01 Topic·QoS·retain

**결정**

| Interface | Topic | 방향 | QoS | retain | 상태 |
|---|---|---|---|---|---|
| Sensor Vibration | `factory/sensor/<sensor_id>/vibration` | 구독 | 0 | false | Shared 확정 |
| Product Created | `factory/product/created` | 구독 | 1 | false | Shared 확정 |
| Line Status | `factory/line/status` | 구독 | 1 | true | Shared 확정 |
| Vision Result | `factory/vision/result` | 구독 | 1 | false | Shared 확정 |
| PdM Result | `factory/pdm/result` | 구독 | 1 | false | 생산자 PdM (A-05) |
| PdM Spectrum | `factory/pdm/spectrum` | 구독 | 0 | false | 생산자 PdM (A-06, 조율 C-12) |
| Conveyor Control | `factory/control/conveyor` | 발행 | 1 | false | Shared 확정 (A-03) |
| Alarm Event | `factory/alarm/event` | 발행 | 1 | false | 이 파일 확정본 (A-02) |

- 접두사 `factory`는 설정(`TOPIC_PREFIX`)으로 바꿀 수 있지만 기본값을 쓴다.
- Operations MQTT 연결: MQTT 3.1.1, client_id `factory-operations`, clean session, keepalive 30초, 인증·TLS 없음. LWT 없음.

**근거**: Shared INTERFACES Interface 목록, ARCHITECTURE 5.1, 조율 C-12·C-15.

**Shared 현재**: Alarm Event 행의 소비자·QoS·retain·상태가 "미정". PdM Spectrum 행이 없다.

**바꿀 것**: Alarm Event 행을 A-02로 채운다. PdM Spectrum 행은 PdM Result와 같은 DOCUMENT_CHANGE로 predictive-maintenance가 추가한다(조율 C-12). ARCHITECTURE 5.1 Topic 그림에 `pdm/spectrum`을 넣는 것도 그때 함께 한다.

**맞출 Component**: Shared(Alarm Event 행).

## A-02 Alarm Event (생산자 확정본)

**결정**: Operations가 Equipment State가 `WARNING` 또는 `CRITICAL`로 **올라갈 때** Alarm을 만들고 발행한다.

| 항목 | 값 |
|---|---|
| Topic | `factory/alarm/event` |
| 생산자 / 소비자 | factory-operations / Runtime 소비자 없음. integration이 E2E 검증에서 관찰한다 |
| QoS / retain | 1 / false |
| 발행 조건 | 같은 `sensor_id`의 이전 상태보다 심각도가 높은 `WARNING`·`CRITICAL` PdM Result(첫 결과 포함). 심각도 `NORMAL` < `CAUTION` < `WARNING` < `CRITICAL`. `CAUTION` 진입·회복은 발행하지 않는다. 라인 재가동(Line Status `conveyor`가 `STOPPED`에서 `RUNNING`으로 바뀜. 사이의 `online: false` 허용)을 보면 라인 센서의 이전 상태를 비운다. 재가동 전 윈도우의 결과는 쓰지 않는다 |
| 빈도 | 상태가 올라갈 때 한 번. 같은 상태가 이어지면 다시 보내지 않는다. 떨림 억제·확인(ack)·해제 이벤트 없음 |

```json
{
  "schema_version": 1,
  "alarm_id": "3b0f6a52-8f0e-4c55-9d7e-2f1c9a4b7e10",
  "timestamp": "2026-09-25T05:20:14.400Z",
  "raised_at": "2026-09-25T05:20:14.412Z",
  "sensor_id": "motor01",
  "severity": "CRITICAL",
  "previous_state": "WARNING",
  "health_index": 18,
  "anomaly_score": 0.82
}
```

| 필드 | 필수 | 형식 | 의미 |
|---|---|---|---|
| `schema_version` | 예 | 1 | Shared CONVENTIONS |
| `alarm_id` | 예 | string | UUID4(소문자, 하이픈 포함 36자). Alarm마다 새 값. DB `alarm.alarm_id`와 같다 |
| `timestamp` | 예 | string | 원인 PdM Result의 `timestamp`를 바꾸지 않고 싣는다(이벤트 발생 시각, Shared 9·17절). CONVENTIONS 형식 |
| `raised_at` | 예 | string | Operations가 판정한 시각(Operations 호스트 UTC). CONVENTIONS 형식 |
| `sensor_id` | 예 | string | 원인 PdM Result의 값 |
| `severity` | 예 | string | `WARNING` \| `CRITICAL`. 새 Equipment State |
| `previous_state` | 예 | string\|null | 이전 Equipment State(`NORMAL`\|`CAUTION`\|`WARNING`\|`CRITICAL`). 첫 결과이거나 재가동 뒤 첫 판정이면 null |
| `health_index` | 예 | int | 원인 PdM Result의 값(0~100) |
| `anomaly_score` | 예 | number | 원인 PdM Result의 값 |

- 발행 전제: Alarm을 DB `alarm` 테이블 쓰기 대기열에 넣은 뒤 발행한다. DB 기록 완료를 기다리지 않는다. MQTT가 끊겨 있으면 발행하지 않는다(DB 기록은 한다).
- 순서: 같은 PdM Result로 Interlock STOP도 나가면 Alarm Event를 먼저 **발행**한다. Topic이 달라 소비자의 **수신** 순서는 보장하지 않는다(Shared INTERFACES).
- 중복·재전송: 없다(Shared 12절). 소비자는 `alarm_id`로 구분한다.
- 오류: 오류 이벤트는 없다. 발행 실패는 Operations 로그로만 남는다.
- Ground Truth: `fault_level` 등 Ground Truth 필드를 싣지 않는다.
- 호환성: 선택 필드 추가는 `schema_version`을 올리지 않는다. 소비자는 모르는 필드를 무시한다.

**근거**: Shared ARCHITECTURE 4.4 Alarm Management(Warning·Critical 필수, Alarm History DB 저장), 17절(PdM: State Event, Operations: Alarm Management), 조율 C-04·C-15. 규칙 세부는 `03-control.md` 4절, 결정 이유는 `DECISIONS.md` D-21·D-22.

**Shared 현재**: INTERFACES 목록에 Topic과 생산자만 있고 소비자·QoS·retain·Payload가 "미정".

**바꿀 것**: INTERFACES에 "Alarm Event" 절을 위 표·예시·필드표·발행 조건·순서로 추가하고, 목록 행을 소비자 "없음(integration 검증에서 관찰)", QoS 1, retain false, 상태 확정으로 바꾼다. 첫 줄 "확정" 목록에 Alarm Event를 넣는다.

**맞출 Component**: integration(E2E-3 단계 4에서 이 Topic 관찰, 계약 검사 C-01·C-02·C-06에 Alarm Event 추가).

## A-03 Conveyor Control 발행 규칙

**결정**: Shared INTERFACES Conveyor Control 형식 그대로 발행한다. Operations가 정한 것:

- `command_id`: 명령마다 새 UUID4 문자열(36자).
- `timestamp`: 명령 발행 시각(Operations 호스트 UTC), CONVENTIONS 형식(밀리초 3자리).
- `reason`: `INTERLOCK_CRITICAL`(Interlock STOP), `OPERATOR_START`, `OPERATOR_STOP`(Dashboard 버튼).
- QoS 1, retain false. MQTT가 끊겨 있으면 보내지 않는다(재연결 뒤 오래된 명령이 나가지 않게).
- Interlock STOP은 같은 PdM Result로 두 번 보내지 않는다. 결과를 5초 안에 못 보면 다음 새 `CRITICAL` 결과로 한 번 더 보낸다. `START`는 운영자 조작으로만 보낸다(자동 재가동 없음).
- 결과는 Line Status `last_command.command_id`·`result`로 확인하고 DB `control`에 기록한다.

**근거**: Shared INTERFACES Conveyor Control, SIM A-11(retained 명령 거부, 필드 검증 순서), 05-mqtt 4절. 규칙 세부는 `03-control.md` 3절.

**Shared 현재**: 확정. 형식 차이 없음.

**바꿀 것**: 없음. (선택) Shared 예시 `reason`에 `OPERATOR_START`·`OPERATOR_STOP`을 참고로 적을 수 있다.

**맞출 Component**: 없음. simulator는 이미 이 형식을 받는다.

## A-04 Line Status 해석

**결정**
- `online: false`(다른 필드 없음)를 받으면 라인 상태를 "알 수 없음"으로 둔다. Interlock은 알 수 없는 라인에도 `CRITICAL`이면 STOP을 보낸다(이미 정지면 simulator가 `NO_CHANGE`).
- `conveyor`가 `RUNNING`이 아니던 상태(알 수 없음·`STOPPED`, Operations 기동 직후 포함)에서 `RUNNING`이 되면 그 Line Status의 `timestamp`를 **재가동 기준 시각**으로 삼고, 그 이후 `timestamp`의 PdM Result만 Interlock·Alarm 판단에 쓴다.
- `fault_level`은 Dashboard 표시(Current Fault Level)와 `sensor_chunk.fault_level` 결합에만 쓴다.
- `last_command`로 자기 명령의 결과를 확인하고, 모르는 `command_id`(simulator 로컬 명령 등)는 관찰 행으로 기록한다.
- 라인 센서는 Line Status의 `sensor_id`(없으면 설정 `motor01`).

**근거**: Shared INTERFACES Line Status, SIM A-11·A-12. 세부는 `03-control.md` 1절.

**Shared 현재**: 확정. **바꿀 것**: 없음. **맞출 Component**: 없음.

## A-05 PdM Result에 대한 의존

**결정**: 생산자 predictive-maintenance의 spec과 Shared 확정본에 맞춘다. 확정 전에는 PdM 아키텍처 6.2절 초안(조율 C-15)을 기준으로 구현한다. Operations가 기대는 것:

| 항목 | 기대 | Operations에서의 용도 |
|---|---|---|
| Topic·QoS·retain | `factory/pdm/result`, QoS 1, **retain false** | retained 옛 `CRITICAL`이 Line Status보다 먼저 도착하면 기동 직후 불필요한 STOP이 나갈 수 있다 |
| 필드 | `schema_version`(1), `sensor_id`, `timestamp`, `anomaly_score`(number), `health_index`(int 0~100), `state`(대문자 4값). 선택: `window_start`, `model_version` | 검사 대상은 이 필드뿐이다. 다른 필드는 무시한다 |
| `timestamp` 의미 | 분석 윈도우의 끝. **Simulator timestamp에서만 계산**(PdM 호스트 시계 아님) | 재가동 기준 시각(Line Status `timestamp`)과 같은 시계로 비교한다. 결합·상관분석의 시간 축 |
| 정지 중 | `rpm == 0` 윈도우는 발행하지 않는다. 재가동 뒤 첫 결과는 재가동 뒤 chunk만으로 채운 윈도우(가동 chunk 10개)에서 낸다 | 재가동 전 결과와 뒤 결과를 `timestamp > 재가동 기준 시각`으로 가른다 |
| 발행 주기 | hop마다(0.5초) | 2초(4 hop) 넘게 결과가 없으면 "마지막 판정"으로 표시한다(`06-dashboard.md` 4절) |
| 센서 | 결과는 센서마다, `sensor_id`로 구분 | 라인 센서(Line Status `sensor_id`) 결과만 Interlock에 쓴다 |
| State 평활화 | 기본 끔(PdM 아키텍처 5.5절) | Operations는 떨림을 억제하지 않는다. 켜면 Alarm이 덜 흔들린다 |

- Operations는 Health Index로 State를 다시 계산하지 않는다. `state == CRITICAL`이 곧 Interlock 조건이다.
- 확정본이 위 기대와 다르면(특히 `timestamp` 의미, 정지 중 동작, retain) 재가동 기준 시각 규칙과 stale 규칙이 영향을 받는다. 조율 agent가 어느 쪽을 맞출지 정한다.

**근거**: Shared ARCHITECTURE 4.2 Output, 4.4 Interlock, 조율 C-04·C-13·C-15, PdM 아키텍처 5.2·6.2절.

**Shared 현재**: INTERFACES에 Topic과 생산자·소비자만 있고 나머지 "미정".

**바꿀 것**: predictive-maintenance가 Shared DOCUMENT_CHANGE로 확정한다. 위 표의 기대(특히 retain false, `timestamp` = Simulator 시각에서 계산한 윈도우 끝, `rpm == 0` 미발행, 재가동 뒤 첫 결과의 윈도우)를 확정본에 명시해 줄 것을 요청한다.

**맞출 Component**: predictive-maintenance(위 기대를 spec·Shared 제안에 명시), Shared.

## A-06 PdM Spectrum에 대한 의존 (표시 전용)

**결정**: `factory/pdm/spectrum`(QoS 0, retain false, 약 1초 주기)을 구독해 Dashboard FFT Spectrum 칸에만 쓴다. 필드 구성은 PdM spec이 정한다. Operations는 이름에 느슨하게 의존한다:

- 필수로 보는 것: `schema_version`(1), `sensor_id`, `timestamp`(CONVENTIONS 형식). 메시지 256 KiB 이하.
- 계열: 최상위의 숫자 배열(길이 2~4096) 필드는 모두 그래프 계열이다. 이름에 `envelope`가 들어가면 포락선 패널, 아니면 원 스펙트럼 패널.
- 주파수 축: `freq_step_hz`(포락선은 `envelope_freq_step_hz`가 있으면 그것), 시작 `freq_start_hz`(없으면 0). 없으면 bin 번호로 그린다.
- Interlock·Alarm·DB 기록·상관분석에 쓰지 않는다. 받지 못하면 화면에 "PdM 스펙트럼 없음"만 나온다.

**근거**: Shared ARCHITECTURE 4.4 Dashboard(FFT Spectrum), 17절(FFT는 PdM), 조율 C-12. 해석 규칙은 `02-mqtt.md` 3.7절.

**Shared 현재**: 없음.

**바꿀 것**: predictive-maintenance가 PdM Result와 같은 DOCUMENT_CHANGE로 추가한다(조율 C-12).

**맞출 Component**: predictive-maintenance(권장: 원 스펙트럼 `spectrum_<축>`, 포락선은 이름에 `envelope`, 간격 `freq_step_hz`·필요하면 `envelope_freq_step_hz`. 이 권장과 다르면 그래프 묶음이 달라질 뿐 수신은 된다).

## A-07 Product Created·Vision Result 해석

**결정**
- Shared 확정 형식을 받는다. Vision Result의 `confidence`·`bbox`·`gradcam_path`·`defect_type`·`judgement_source`는 키가 없어도 null로 받는다(형식 준수 검사는 integration).
- 같은 제품의 두 번째 Vision Result와 두 번째 Product Created는 DB에서 버린다(`product_id` 키).
- Vision Result가 Product Created보다 먼저 와도 된다(외래키 없음).
- `judgement_source`를 저장·표시한다. `PASS_THROUGH`는 "Simulator 정보 전달"로 표시하고 상관분석은 이 값을 검사 결과로 그대로 쓴다.
- `gradcam_path`가 null이면 "현재 범위에서 제공하지 않음"으로 표시한다. Image Storage는 `products/`·`gradcam/`을 읽기만 하고 점으로 시작하는 파일은 열지 않는다.

**근거**: Shared INTERFACES Product Created·Vision Result·Image Reference, ARCHITECTURE 4.3 현재 범위, SIM A-18.

**Shared 현재**: 확정. **바꿀 것**: 없음. **맞출 Component**: 없음.

## A-08 DB 스키마와 적용 방식, 검증 조회

**결정**

| 항목 | 값 |
|---|---|
| DB 이미지 | `timescale/timescaledb:2.30.1-pg17`(PostgreSQL 17, TimescaleDB 2.30.1). 컨테이너 하나, DB 하나, 스키마 `public`. 시계열과 운영 테이블을 같은 DB에 둔다 |
| DDL 파일 | `COMPOSITION.json`에 고정한 factory-operations commit의 `db/schema.sql` 한 파일. 필요한 확장(`CREATE EXTENSION IF NOT EXISTS timescaledb`)은 파일 안에 있다 |
| 적용 방식 | (권장) DB 컨테이너에 `db/schema.sql:/docker-entrypoint-initdb.d/100_factory_operations.sql:ro`로 마운트. 빈 데이터 디렉터리의 첫 기동 때 이미지의 TimescaleDB 초기화 스크립트(`000_…`, `001_…`) 다음에 실행된다. (대안) 빈 DB에 `psql -v ON_ERROR_STOP=1 -f db/schema.sql`. 둘 다 Operations 기동 전에 끝나야 `/readyz`가 200이 된다. 파일은 반복 실행해도 오류가 없다 |
| DB 이름·사용자·비밀번호 | integration이 정한다(`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`). Operations에는 `DATABASE_URL=postgresql://<user>:<password>@db:5432/<db>`로 준다. 다른 Component에는 주지 않는다 |
| 준비 확인 | DB: `pg_isready -h 127.0.0.1 -U <user> -d <db>`(컨테이너 안). 스키마: `SELECT version FROM schema_info WHERE component = 'factory-operations'` = 1 |
| 초기화 | 볼륨(Image Storage)과 DB 데이터를 함께 지운다. 유지·백업·migration 없음 |
| 스키마 버전 | 1. 테이블·열을 바꾸면 버전을 올리고 이 항목과 `05-storage.md` 4절을 같은 PR에서 고친다 |

검증 조회(SELECT만, integration E2E):

| E2E 단계 | 테이블·키 | 예시 |
|---|---|---|
| E2E-1 단계 4 (시계열 적재) | `sensor_chunk` (`sensor_id`, `timestamp`) | `SELECT count(*), count(fault_level) FROM sensor_chunk WHERE sensor_id = 'motor01'`. 특정 chunk: `WHERE sensor_id = %s AND "timestamp" = %s`(Payload `timestamp`) → `seq`, `fault_level`(Line Status as-of 값) |
| E2E-1 (설비 상태 이력) | `equipment_state` (`sensor_id`, `timestamp`) | PdM Result의 `timestamp`로 한 행, `state`·`health_index`가 Payload와 같다 |
| E2E-2 단계 4 (검사 이력) | `inspection` (`product_id` UNIQUE) | `SELECT id, "timestamp", product_id, image_path, defect_type, confidence, bbox, health_index_at_time FROM inspection WHERE product_id = %s` (Shared 5.3 최소 필드) |
| E2E-3 단계 2~3 (명령) | `control` (`command_id`) | `SELECT origin, reason, result FROM control WHERE command_id = %s` → `operations`, `INTERLOCK_CRITICAL`, `APPLIED` |
| E2E-3 단계 4 (Alarm) | `alarm` (`alarm_id`) | Alarm Event의 `alarm_id`로 한 행, `severity`가 같다 |
| 참고 | `product` (`product_id`), `line_status_change` (`id`), view `defect_result` | 불량 검사만: `SELECT * FROM defect_result` |

- 행은 이벤트 처리 뒤 곧바로(센서는 최대 1초 배치) 기록된다. 검증은 이벤트 수신 뒤 5초 안에 조회되면 된다고 본다.

**근거**: Shared ARCHITECTURE 4.4 Data Persistence, 5.2, 5.3, 19.1, 조율 C-15, integration 아키텍처 4.5절(Q-04·Q-08).

**Shared 현재**: ARCHITECTURE 19.1 "DB 초기화에는 `COMPOSITION.json`에 고정한 `factory-operations` commit의 DDL을 사용한다". 형식·경로 없음.

**바꿀 것**: 없음(Shared는 경로를 정하지 않는다).

**맞출 Component**: integration(DB 서비스 정의, DDL 적용, 연결 정보 매핑, 검증 SELECT).

## A-09 실행 조건

**결정**: 시스템 compose는 integration 소유다. Operations가 요구하는 조건:

```yaml
services:
  factory-operations:
    image: factory-operations:<COMPOSITION.json에 고정한 commit>   # 저장소 루트 Dockerfile, build arg GIT_COMMIT=<commit>
    environment:
      MQTT_URL: mqtt://mosquitto:1883
      DATABASE_URL: postgresql://<user>:<password>@db:5432/<db>
      IMAGE_ROOT: /data
    ports: ["127.0.0.1:8080:8080"]
    volumes: ["image-storage:/data:ro"]
    depends_on: [mosquitto, db]
```

- 실행 명령: 이미지 기본 `CMD`(`python -m factory_operations serve`). 바꾸지 않는다.
- 포트: 컨테이너 8080 HTTP 하나(Dashboard와 API). 호스트는 `127.0.0.1`에만 노출한다. simulator 8000과 겹치지 않는다.
- 환경 변수: 위 세 개가 필수다. 선택: `TOPIC_PREFIX`(기본 `factory`), `HTTP_PORT`(기본 8080), `LOG_LEVEL`(기본 `INFO`).
- Image Storage: 공유 named volume을 읽기 전용(`:ro`)으로 마운트한다.
- 기동 확인: `GET /healthz` 200은 프로세스가 떴다는 뜻이다(이미지 HEALTHCHECK). `GET /readyz` 200은 MQTT 연결과 DB 스키마 확인이 모두 끝났다는 뜻이며 E2E 시작 조건으로 쓴다. Broker·DB가 늦게 떠도 Operations는 기동하고 재연결한다(MQTT 1~10초, DB 2초 간격).
- `/healthz` 응답의 `commit`으로 실행 중인 이미지의 commit을 확인할 수 있다.
- 컨테이너는 root로 실행한다.

**근거**: Shared CONVENTIONS 실행 환경, ARCHITECTURE 19.1, SIM A-17, integration 아키텍처 4.2~4.4절. 세부는 `07-runtime.md` 1·3절.

**Shared 현재**: CONVENTIONS "공통 실행 방식: Docker Compose, 시스템 compose 정의는 integration 소유". **바꿀 것**: 없음.

**맞출 Component**: integration(서비스 정의, 포트, 환경 변수 매핑, 기동 확인).

## A-10 Dashboard 갱신 측정 관찰 지점

**결정**
- 관찰 지점: `GET http://<operations>:8080/api/snapshot`(스냅숏 `schema_version` 1, `06-dashboard.md` 3절). `generated_at`(Operations 시각)과 항목별 원본 `timestamp`·식별자(`line.timestamp`, `pdm.timestamp`, `spectrum.timestamp`, `vibration.timestamp`, `inspections[].product_id`, `alarms[].alarm_id`, `controls[].command_id`·`result`)가 있다. 캐시하지 않는다.
- 측정 방법: `08-verification.md` 4.1절. 측정 도구가 MQTT 수신 시각과 스냅숏 반영 시각을 **자기 시계**로 재고, 브라우저 polling 간격 1.0초·스냅숏 응답 시간 최댓값·렌더링 예산 0.2초를 더한 값의 최댓값이 5.0초 이하인지 본다(응답 시간 최댓값 0.5초 이하도 조건). 서로 다른 호스트 시계를 비교하지 않는다.
- 브라우저 polling 간격은 1.0초로 고정한다(`app.js` `POLL_INTERVAL_MS`).
- 이 필드 이름과 의미를 바꾸려면 스냅숏 `schema_version`을 올리고 이 항목을 고친다.

**근거**: Shared ARCHITECTURE 2절(Dashboard 5초), 4.4 Dashboard, 19.1(시스템 수준 성능 측정은 integration), integration 아키텍처 E2E-4(Q-17).

**Shared 현재**: 기준만 있고 측정 방법 없음. **바꿀 것**: 없음.

**맞출 Component**: integration(시스템 환경에서 같은 방법으로 측정, `VALIDATION.md` 기록).

## A-11 Interlock·Alarm의 관찰 가능한 동작

**결정** (integration E2E-3의 판정 근거)
- 판정 대상 `CRITICAL` PdM Result(라인 센서, 재가동 기준 시각 이후)를 받으면 STOP을 보낸다. Component 테스트 기준으로 broker에서 PdM Result를 발행한 뒤 1.0초 안에 STOP이 broker에 나온다.
- 같은 결과로 `WARNING`/`CRITICAL` 상태가 올라가면 Alarm Event도 나온다. Operations는 Alarm Event를 먼저 발행하지만 Topic이 달라 수신 순서로 판정하지 않는다.
- STOP의 `reason`은 `INTERLOCK_CRITICAL`, `command_id`는 DB `control.command_id`와 같다. Line Status 결과(`APPLIED`/`NO_CHANGE`)를 보면 `control.result`에 기록한다.
- Operations는 자동으로 `START`하지 않는다. E2E가 재가동을 확인하려면 simulator 로컬 HTTP(`POST /api/conveyor`, 조율 C-14 검증 보조) 또는 Operations `POST /api/conveyor {"command":"START"}`를 쓴다. 재가동 뒤 PdM이 여전히 `CRITICAL`이면 약 1~2초 뒤 다시 STOP이 나간다.
- 제안: E2E-3 단계 2의 제한 시간은 "단계 1의 `CRITICAL` 수신 뒤 2초".

**근거**: Shared ARCHITECTURE 4.4 Interlock·Alarm, 7.3. 세부는 `03-control.md` 3·4절.

**Shared 현재**: 흐름만 있음. **바꿀 것**: 없음.

**맞출 Component**: integration(E2E-3 판정·제한 시간).

## A-12 Ground Truth 사용 제한

**결정**
- Operations는 `ground_truth/products.jsonl`을 읽지 않는다.
- Line Status `fault_level`은 표시와 `sensor_chunk.fault_level`(평가용 결합)에만 쓰고 Interlock·Alarm·상관분석 입력으로 쓰지 않는다.
- Operations가 발행하는 Payload(Conveyor Control, Alarm Event)에는 Ground Truth 필드(`fault_level`, `severity`(Ground Truth 의미), `defect_probability`, `defect`, `defect_type`, `bbox`, `defect_params`, `render_seed`, `spawned_at`)가 없다. Alarm Event의 `severity`는 Equipment State 값(`WARNING`|`CRITICAL`)이며 Ground Truth의 진동 심각도(0~1 숫자)와 다른 뜻이다.

**근거**: Shared ARCHITECTURE 3.4, 8, 17절(Operations: Evaluation Only), INTERFACES Ground Truth.

**Shared 현재**: 원칙 확정. **바꿀 것**: 없음.

**맞출 Component**: integration(계약 검사 C-07 대상에 Alarm Event 추가. Alarm Event `severity`는 문자열 Equipment State라 Ground Truth `severity`(숫자)와 구분해 검사).

## ARCHITECTURE 미결 사항 → 해결 위치

| `docs/ARCHITECTURE.md` 11.2절 | 해결 |
|---|---|
| O-1 PdM Result Payload·QoS·주기·정지 중 동작 | A-05 (생산자 확정 대기, 가정 명시) |
| O-2 FFT Spectrum 공급 | A-06 (조율 C-12: `factory/pdm/spectrum`) |
| O-3 Alarm Event Shared 등록 | A-02 (확정본. Shared DOCUMENT_CHANGE는 별도 subagent) |
| O-4 DB 이미지, DDL 적용, 포트·환경 변수 | A-08, A-09 |
| O-5 Dashboard 5초 측정 방법 | A-10, `08-verification.md` 4.1절 |

| integration 아키텍처 질문 | 해결 |
|---|---|
| Q-04 DB 인스턴스·이름·연결 정보 | A-08 (컨테이너 하나, DB 하나, 이름·계정은 integration) |
| Q-08 DDL 위치·형식·순서·확장 | A-08 |
| Q-17 Dashboard 관찰 지점 | A-10 |
| Q-21 Alarm Event 소비자·Schema | A-02 |
| 4.3 Operations 포트, 4.4 환경 변수, 실행 명령·health | A-09 |
