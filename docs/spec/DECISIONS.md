# 결정 기록

> 목적: 이 Component 안에서 내린 설계·절차 결정과 그 이유를 한 곳에 둔다. 다른 Component와의 약속은 `AGREEMENTS.md`에 있다.
> 읽어야 할 때: spec의 값이나 규칙이 왜 그런지 알아야 할 때, 결정을 바꾸려 할 때.
> 기준일: 2026-09-27. 책임자가 채팅으로 절차 예외를 지시했고(조율 C-01), 나머지는 조율 결정(C-00~C-15)과 `docs/ARCHITECTURE.md`(리뷰 반영본)를 근거로 이 spec이 정했다.

결정을 바꾸려면 새 ID로 항목을 추가하고 이전 항목의 "결정"에 `→ D-xx로 대체`를 붙인다. 지우지 않는다.

## 0. 이미 확정된 결정

`docs/ARCHITECTURE.md`의 [확정] 항목(책임 경계, Shared 확정 Interface, 재시도·멱등성·보안 제외, DB 기록 단독 주체, Ground Truth 평가 전용)과 조율 결정 C-00~C-15는 다시 논의하지 않고 전제로 쓴다.

## 1. 절차 (책임자가 승인한 예외)

### D-01 PR merge 주체
- 문맥: `AGENTS.md`는 "Agent는 PR을 merge하지 않는다"고 정한다.
- 선택지: (a) 규칙대로 사람이 merge (b) 조율 agent가 merge
- 결정: (b). 조율 agent가 `Validate Component / validate` CI 통과와(구현 PR은) `agent.py finish` 통과, `agent/tasks/<ID>.yaml` `status: done`을 확인한 뒤 merge commit으로 main에 merge한다. task를 실행한 agent는 merge하지 않는다.
- 이유: 책임자 채팅 지시(2026-09-27), 조율 C-01.
- 영향: `HUMAN.md`, `08-verification.md` 7절

### D-02 계획 승인
- 문맥: PLAN의 새 milestone·task에는 `proposed: true`를 붙이고 사람이 지워야 착수할 수 있다.
- 선택지: (a) 계획 PR마다 사람이 `proposed`를 지움 (b) 책임자의 채팅 지시를 승인으로 보고 `proposed` 없이 등록
- 결정: (b). 이 spec을 따르는 계획 작업은 milestone과 task를 `proposed` 없이 등록한다. BOOT-1의 A3(manual 승인)은 이 지시로 갈음하고 계획 PR에서 정리한다(조율 C-09).
- 이유: 책임자 채팅 지시(2026-09-27), 조율 C-01.
- 영향: `00-overview.md` 6절

### D-03 acceptance는 자동 검사만
- 문맥: manual acceptance가 있으면 사람이 없을 때 task가 끝나지 않는다.
- 선택지: (a) task마다 manual 유지 (b) `command`·`artifact`·`metric`만 쓰고 사람 확인은 마지막 milestone의 `owner: human` task로 모음
- 결정: (b). 사람 확인은 `08-verification.md` 6절 목록 그대로 HUM-1 하나로 한다.
- 이유: 책임자 채팅 지시(2026-09-27), 조율 C-01. 화면 모양 문제는 끝에서 발견될 수 있지만 수정 task로 되돌리는 비용이 작다.
- 영향: `08-verification.md` 6·7절

### D-04 교차 Component 항목의 구현 기준
- 문맥: `SHARED_CONFIG.json` `contract_ref`가 null이다. Shared main `d0c997c`에는 다섯 Interface가 확정이고 PdM Result·Alarm Event는 미정이다.
- 선택지: (a) 계약 채택까지 보류 (b) simulator D-04처럼 자기 AGREEMENTS만 기준 (c) 확정된 것은 Shared, 미정은 생산자 spec(자기 것은 AGREEMENTS 확정본)을 기준으로 구현하고 Shared 확정 뒤 `contract_ref` 채택
- 결정: (c). 조율 C-04·C-05를 따른다. task의 `contract` 필드는 `contract_ref` 채택(OPS-10) 전에는 쓰지 않고 `why`나 acceptance에 `AGREEMENTS.md` 항목 ID를 적는다.
- 이유: integration의 계약 검사가 Shared 한 곳을 기준으로 하게 하면서, 미정 Interface 때문에 구현이 멈추지 않게 한다.
- 영향: `AGREEMENTS.md` 머리말, `00-overview.md` 6절 M5

### D-05 verify 명령 추가 방식
- 문맥: `agent/config.yaml`은 사람 관리 파일이고 `verify`가 비어 있다.
- 선택지: (a) 사람이 추가 (b) 영역을 처음 만드는 task가 `agent/config.yaml`을 scope에 넣고 같은 PR에서 spec에 고정된 명령을 추가
- 결정: (b). 명령과 시점은 `08-verification.md` 5절에 고정되어 있고 task는 그대로 넣는다. 약하게 바꾸지 않는다.
- 이유: simulator D-05와 같다. D-01로 PR을 agent 쪽(조율)이 merge하므로 명령을 미리 고정해 임의 변경을 막는다.
- 영향: `08-verification.md` 5절

## 2. 도구

### D-06 Python 의존성 관리
- 문맥: 이 맥에는 Python 3.12.13과 venv·pip가 있고 uv는 없다.
- 선택지: (a) `python3 -m venv .venv` + `pip install -r`(직접 의존 `==` 고정) (b) uv 설치 (c) 시스템 Python
- 결정: (a). 버전은 `07-runtime.md` 7절. Docker 이미지도 같은 `requirements.txt`를 쓴다.
- 이유: 새 도구 설치 없이 agent가 비대화식으로 만든다. simulator와 같은 방식이다. lock 파일이 없어 간접 의존이 바뀔 수 있지만 toy 범위에서 허용한다.
- 영향: `07-runtime.md` 7절, `08-verification.md` 2절

### D-07 테스트 도구와 진입점
- 선택지: (a) pytest + 저장소 루트 `Makefile`(venv stamp) (b) 셸 스크립트 (c) verify에 명령 직접 나열
- 결정: (a). Docker 연동 테스트는 마커 `docker`로 나눈다. testcontainers 같은 추가 라이브러리 없이 `docker run`/`docker port`를 subprocess로 부른다. Make는 macOS 기본 GNU Make 3.81.
- 이유: verify 명령이 짧고, 요구사항이 바뀔 때만 재설치한다. simulator와 같은 구조라 조율·리뷰가 쉽다.
- 영향: `08-verification.md` 2절

### D-08 MQTT client
- 선택지: (a) paho-mqtt 2.1 `loop_start()` 스레드 (b) aiomqtt (c) gmqtt
- 결정: (a). MQTT 3.1.1, `CallbackAPIVersion.VERSION2`.
- 이유: 재연결·연결 전 기동·QoS 1이 내장되어 있고 `publish()`가 스레드 안전하다. simulator와 같은 라이브러리다. 수신은 큐로 워커에 넘긴다.
- 영향: `02-mqtt.md` 1절

### D-09 테스트용 Broker·DB
- 선택지: (a) Docker의 실제 Mosquitto 2.1.2·TimescaleDB 2.30.1-pg17 (b) 프로세스 안 가짜 broker·SQLite (c) 가짜만
- 결정: (a). 판단 로직은 가짜로 단위 테스트하고, 실제 retain·QoS·DDL·hypertable은 같은 이미지로 확인한다. Docker가 없으면 실패한다.
- 이유: integration이 쓸 것과 같은 구현이어야 retain·initdb·배열 열 동작이 같다. 2026-09-27에 이 맥에서 `timescale/timescaledb:2.30.1-pg17`을 받아 이 spec의 DDL을 initdb로 적용·재실행하고 `float8[]`→`real[]` 삽입을 확인했다.
- 영향: `08-verification.md` 2·3.6절

### D-10 HTTP 서버
- 선택지: (a) FastAPI + uvicorn (b) 표준 라이브러리 `http.server` (c) Flask
- 결정: (a). 버전은 simulator와 같다.
- 이유: JSON API·정적 파일·`TestClient` 테스트를 한 번에 해결한다. (b)는 라우팅·오류 처리를 직접 써야 한다.
- 영향: `06-dashboard.md` 1·2절

### D-11 DB 드라이버와 접근 방식
- 선택지: (a) psycopg 3 동기 연결 하나 + 손으로 쓴 SQL (b) SQLAlchemy ORM (c) asyncpg
- 결정: (a). DB 스레드 하나가 연결 하나를 쓴다. SQL 문자열은 `store/sql.py`에 모은다.
- 이유: 테이블 8개·조회 6개뿐이라 ORM의 이득이 없다. 동기 드라이버가 스레드 모델(D-14)과 맞는다. `psycopg[binary]`는 macOS arm64·Linux aarch64 wheel이 있어 컴파일이 없다.
- 영향: `05-storage.md` 3절

### D-12 차트
- 선택지: (a) 차트 라이브러리 파일을 저장소에 넣음(vendored) (b) CDN (c) canvas 2D로 직접 그림(`plot.js`)
- 결정: (c). 선 그래프·min/max 띠·막대 세 가지만 그린다.
- 이유: 필요한 그림이 단순하다. (a)는 외부 파일을 받아 넣고 라이선스를 챙겨야 하고, (b)는 오프라인 시연이 안 된다. Node 빌드 단계도 없다. ARCHITECTURE 9절의 "vendored 경량 라이브러리"를 바꾼다.
- 영향: `06-dashboard.md` 5절

### D-13 상관계수 계산
- 선택지: (a) scipy `pearsonr`·`spearmanr` (b) numpy로 직접(순위·동률 처리 포함)
- 결정: (a).
- 이유: 동률 순위와 경계 조건을 직접 구현하다 틀릴 위험을 없앤다. 이미지 크기 증가(수십 MB)는 toy 범위에서 문제없다.
- 영향: `04-analysis.md` 2.2절

## 3. 구조

### D-14 스레드 모델
- 문맥: ARCHITECTURE 4.1은 도메인 워커가 DB 쓰기까지 한다.
- 선택지: (a) 워커가 DB도 씀 (b) 워커와 DB 스레드를 나누고 큐로 연결 (c) asyncio 하나로 통일
- 결정: (b). paho 스레드 → inbound 큐 → 도메인 워커(판단·발행) → DB 큐 → DB 스레드. HTTP는 uvicorn main 스레드.
- 이유: DB가 느리거나 끊겨도(연결 제한 5초) Interlock 판단이 막히지 않는다. 도메인 상태를 바꾸는 것은 워커 하나라 락은 StateStore 하나로 충분하다. (c)는 paho·psycopg 동기 API와 맞지 않는다.
- 영향: `01-core.md` 2절

### D-15 스냅숏 출처
- 선택지: (a) HTTP 요청마다 DB 조회 (b) 실시간 항목은 메모리, 목록·집계는 DB 스레드가 2초마다 요약해 메모리에 둠 (c) 모두 메모리 카운터
- 결정: (b).
- 이유: 요청 처리가 DB에 기대지 않고, 불량률·목록은 DB 한 소스라 재시작 뒤에도 맞다. 요약 주기 2초를 더해도 갱신 지연 예상 최악값이 약 3.4초로 5초 안이다(`08-verification.md` 4.1절). (c)는 재시작하면 집계가 틀어진다.
- 영향: `05-storage.md` 5절, `06-dashboard.md` 3절

### D-16 운영자 명령 경로
- 선택지: (a) HTTP 핸들러가 직접 발행·기록 (b) 워커 큐에 넣고 future로 결과를 받음
- 결정: (b). 2초 안에 답이 없으면 504.
- 이유: 명령 추적(`issued`)과 Interlock 상태를 워커 하나만 바꾼다.
- 영향: `03-control.md` 3.3절

## 4. 판단 규칙

### D-17 재가동 기준 시각
- 문맥: 정지 중 PdM은 결과를 내지 않아 정지 원인인 `CRITICAL`이 마지막 결과로 남는다. ARCHITECTURE 6.2 규칙 1은 "기동 직후 기준 시각 없음"이었다.
- 선택지: (a) 기동 직후 없음, 이후 `STOPPED`·알 수 없음 → `RUNNING` 때 설정 (b) 기동 뒤 첫 `RUNNING` 관측도 같은 규칙으로 설정 (c) 결과 수신 시각(Operations 시계)으로 비교
- 결정: (b). `RUNNING`이 아니던 상태(기동 직후 `UNKNOWN` 포함)에서 `RUNNING`을 보면 그 Line Status `timestamp`를 기준으로 두고, `pdm.timestamp > 기준`인 결과만 판단에 쓴다.
- 이유: 규칙이 한 줄로 같아지고, 기동 직후 retained Line Status보다 먼저 도착한 옛 결과를 판단에서 뺀다(새 결과는 0.5초마다 온다). 기준과 PdM `timestamp`가 둘 다 Simulator 시계라 비교가 정확하다. (c)는 두 시계와 도착 지연이 섞인다.
- 영향: `03-control.md` 1.2절, `AGREEMENTS.md` A-04·A-05

### D-18 STOP 반복 규칙
- 선택지: (a) 대기 중 STOP이 끝나면 조건이 참인 동안 다시 보냄 (b) 대기 규칙 + 같은 PdM 결과로 두 번 보내지 않음 + `REJECTED`는 시간 초과까지 대기
- 결정: (b).
- 이유: (a)는 PdM이 멈추고 라인이 알 수 없는 동안 같은 옛 결과로 5초마다 STOP을 보낸다. `REJECTED`에서 대기를 바로 끝내면 0.5초마다 STOP이 반복된다. PdM이 살아 있으면 새 결과가 0.5초마다 오므로 STOP 유실 뒤 재발행은 그대로 된다.
- 영향: `03-control.md` 3.2절

### D-19 알 수 없는 라인에서의 STOP
- 결정: Line Status 미수신·`online: false`여도 `CRITICAL`이면 STOP을 보낸다(ARCHITECTURE 6.2 유지).
- 이유: 안전 쪽 선택이고, 이미 정지면 simulator가 `NO_CHANGE`로 끝난다.
- 영향: `03-control.md` 3.2절

### D-20 끊긴 동안 발행하지 않음
- 선택지: (a) paho 대기열에 넣어 재연결 뒤 전송 (b) 끊겨 있으면 발행하지 않고 호출자에게 알림
- 결정: (b). Interlock은 다음 평가에서 다시 판단하고, 운영자 명령은 503, Alarm Event는 DB 기록만 한다.
- 이유: 재연결이 수십 초 뒤라면 그 사이 상황이 바뀐 오래된 STOP·START가 나간다.
- 영향: `02-mqtt.md` 4.2절

### D-21 Alarm 규칙
- 결정: 심각도가 올라가 `WARNING`·`CRITICAL`이 될 때만 Alarm. 실제 재가동(`STOPPED → RUNNING`, 사이의 offline 허용) 때만 이전 상태 초기화. 기동 직후 첫 동기화와 가동 중 끊김 후 복귀는 초기화하지 않는다. 재가동 기준 이전 결과 제외. ack·해제·떨림 억제 없음.
- 이유: Shared 4.4의 필수 대상(Warning, Critical)을 만족하는 최소 규칙이다. 재가동 뒤 같은 고장이 다시 드러나면 새 Alarm으로 보이게 한다. 초기화를 기준 시각 갱신과 같은 조건으로 두면 첫 Line Status가 PdM 결과보다 늦게 오거나 simulator가 잠깐 끊겼다 돌아올 때 정지·재가동 없이 같은 Alarm이 다시 나간다(spec 리뷰 4번). 떨림 억제는 PdM 평활화 책임이다.
- 영향: `03-control.md` 4절

### D-22 Alarm Event 발행과 Payload
- 문맥: 조율 C-04·C-15로 Operations가 생산자다. Runtime 소비자는 없다. ARCHITECTURE 초안은 `from_state`·`to_state`·`severity`를 모두 두었다.
- 선택지: (a) 발행하지 않음(DB만) (b) 발행, `severity` + `previous_state` (c) 발행, 초안 그대로
- 결정: (b). 필드는 `AGREEMENTS.md` A-02.
- 이유: integration이 DB 없이도 Alarm 흐름을 관찰할 수 있고 비용이 작다. 초안의 `to_state`는 `severity`와 항상 같아 중복이라 뺐다.
- 영향: `AGREEMENTS.md` A-02, `05-storage.md` 4절 `alarm`

### D-23 오래된 판정 표시
- 결정: PdM 결과 수신 뒤 2초(4 hop)가 지나면 "마지막 판정"으로 표시하고, 정지 중·재가동 전 판정 문구를 덧붙인다. 스펙트럼 3초, 진동 1초, Line Status 3초. 모두 Operations 단조 시계의 수신 경과로 판정한다.
- 이유: 정지 중 PdM이 결과를 내지 않을 때 화면의 HI·State가 현재 값처럼 보이지 않게 한다(PdM 아키텍처 6.2절 제안). 수신 경과로 재면 시계가 다른 문제를 피한다.
- 영향: `06-dashboard.md` 4절

### D-24 운영자 버튼
- 결정: Dashboard에 `START`와 `STOP`을 둔다. `CRITICAL` 판정 중 `START`는 막지 않고 확인 창으로 경고한다.
- 이유: 재가동은 사람의 판단이다(ARCHITECTURE 6.2 규칙 5). 막으면 Fault Level을 내린 뒤 PdM 새 판정을 받기 전에 라인을 돌릴 수 없다(정지 중에는 판정이 없다).
- 영향: `03-control.md` 3.3절, `06-dashboard.md` 5절

## 5. 데이터

### D-25 DB 구성과 센서 저장 단위
- 결정: PostgreSQL+TimescaleDB 인스턴스·DB 하나, 스키마 `public`. 센서는 chunk 한 행(`real[]` 세 열), `sensor_chunk`만 hypertable. 이미지 `timescale/timescaledb:2.30.1-pg17`.
- 이유: 조율 C-15. 샘플 단위 전개는 초당 10,000행이다. PostgreSQL 17은 2026-09 기준 TimescaleDB 2.30이 지원하는 안정 버전이고 arm64 이미지가 있다. 태그를 고정해 integration과 테스트가 같은 버전을 쓴다.
- 영향: `05-storage.md` 1·4절, `AGREEMENTS.md` A-08

### D-26 DDL 적용 주체
- 선택지: (a) Operations가 기동 때 `schema.sql` 실행 (b) integration(과 테스트 fixture)이 initdb로 적용하고 Operations는 `schema_info` 버전만 확인
- 결정: (b).
- 이유: integration 아키텍처 4.5절이 이미 "Runtime Component 기동 전에 DDL 실행"으로 정했다. 적용 경로를 하나로 두어야 적용 실패를 integration이 관찰·기록할 수 있다.
- 영향: `05-storage.md` 3절, `AGREEMENTS.md` A-08

### D-27 `line_status_change` 키
- 문맥: ARCHITECTURE 7.2는 키를 `timestamp`로 했지만 `online: false` 메시지에는 `timestamp`가 없다.
- 결정: `id bigserial` 키, `received_at`(Operations 시각) 필수, `timestamp` null 허용.
- 영향: `05-storage.md` 4절

### D-28 `control` 기록
- 결정: 자기 명령은 발행 즉시 INSERT하고 결과를 UPDATE한다. 모르는 `command_id`는 `origin = observed`로 INSERT(`ON CONFLICT DO NOTHING`). `command_id`가 null인 거부 결과는 기록하지 않는다. 정렬용으로 `recorded_at`을 둔다.
- 이유: Line Status가 1초마다 같은 `last_command`를 다시 싣고 오고, Operations 재시작 뒤 retained Line Status로 옛 결과가 다시 보여도 행이 중복되지 않는다.
- 영향: `03-control.md` 3.4절, `05-storage.md` 2·4절

### D-29 불량률 분모
- 결정: 불량 검사 수 / 검사 수(`inspection` 한 소스). 생산 수는 `product` 행 수로 따로 보인다.
- 이유: 검사 전 제품이 분모에 들어가면 불량률이 낮게 나온다(ARCHITECTURE 리뷰 10번).
- 영향: `05-storage.md` 5절

### D-30 상관분석 방법
- 결정: 설비 지표 PdM `anomaly_score`, 품질 지표 `defect`, lag 0~30초 1초 간격, Pearson·Spearman, 기본 lag 13초, 최대 차 5초의 as-of, 최소 표본 20, 10초마다 DB 전체로 재계산.
- 이유: ARCHITECTURE 6.8 그대로다. 범위를 "서비스 기동 후"에서 "DB 전체"로 바꿨다. integration이 매 실행 DB를 비우므로 같은 결과이고, Operations 재시작에 영향받지 않는다.
- 영향: `04-analysis.md` 2절

### D-31 진동 표시
- 결정: 최근 1초(chunk 10개)를 축별 500구간 min/max로 솎아 보낸다.
- 이유: 25 KB × 10을 그대로 보내면 무겁고, 단순 솎기(20개 중 하나)는 3.2 kHz 공진 임펄스를 놓친다. min/max 띠는 임펄스 크기를 보존한다. RMS 같은 특징은 PdM 책임이라 계산하지 않는다.
- 영향: `06-dashboard.md` 3절

### D-32 스펙트럼 느슨한 해석
- 결정: (→ D-48로 대체) 숫자 배열 필드를 모두 계열로 보고, 이름의 `envelope` 여부로 패널을 나누며, 간격 필드가 없으면 bin 번호로 그린다.
- 이유: PdM spec이 병렬로 작성 중이라 필드 이름이 확정되지 않았다. 표시 전용이라 이름이 조금 달라도 화면이 동작하는 쪽이 낫다(조율 C-12).
- 영향: `02-mqtt.md` 3.7절, `AGREEMENTS.md` A-06

## 6. 실행·검증

### D-33 포트와 준비 신호
- 결정: HTTP 8080 하나. `/healthz`(프로세스 생존, 이미지 HEALTHCHECK)와 `/readyz`(MQTT 연결 + DB 스키마 확인)를 나눈다.
- 이유: Broker·DB가 늦게 떠도 컨테이너는 healthy가 되어 compose 순서 문제를 피하고, E2E는 `/readyz`로 실제 준비를 기다린다. 8080은 simulator 8000과 겹치지 않는다.
- 영향: `06-dashboard.md` 2절, `AGREEMENTS.md` A-09

### D-34 Dashboard 5초 측정 방법
- 결정: 측정 도구가 MQTT 수신 시각과 스냅숏 반영 시각을 자기 시계로 재고, 브라우저 polling 간격 1.0초, 측정 중 스냅숏 응답 시간 최댓값(0.5초 이하여야 함), 렌더링 예산 0.2초(사람 확인)를 더한 최댓값이 5.0초 이하.
- 이유: `generated_at`과 Payload `timestamp`는 다른 호스트 시계라 빼면 시계 차가 섞인다. 브라우저의 실제 가져감은 자동화하지 않으므로(headless 브라우저 없음) polling 간격을 최악값으로 더한다. Component와 integration이 같은 방법을 쓰면 결과를 비교할 수 있다.
- 영향: `08-verification.md` 4.1절, `AGREEMENTS.md` A-10

### D-35 개발용 compose와 가짜 입력
- 결정: 저장소에 `compose.yaml`(Mosquitto, DB, 예시 이미지 넣기, Operations)과 `scripts/fake_feed.py`(Simulator·PdM·Vision 흉내)를 둔다. 사람 확인(HUM-1)은 이것으로 한다.
- 이유: 다른 Component 없이 화면 전체와 Interlock 흐름을 볼 수 있다. 시스템 시연은 integration의 compose로 한다. 예시 이미지는 개발용 볼륨에 복사하고 Image Storage 자체를 bind mount하지 않는다(Shared CONVENTIONS).
- 영향: `07-runtime.md` 4·5절, `08-verification.md` 6절

### D-36 와이어프레임
- 결정: `docs/WIREFRAME.html`에 화면 배치 한 장을 둔다(외부 요청 없는 정적 HTML).
- 이유: 칸이 많아 표만으로는 배치를 구현자가 정해야 한다. simulator와 같은 방식이다.
- 영향: `06-dashboard.md` 5절

## 7. 계획 (plan 단계, 2026-09-27)

### D-37 task 분해와 순서
- 문맥: `00-overview.md` 6절 후보는 OPS-6(MQTT와 워커)이 흐름 연동 테스트(C-04~C-06)를 갖지만, 그 테스트는 `/readyz`와 `/api/snapshot`(`wait_snapshot`)을 쓰고 둘은 OPS-7(HTTP API)이 만든다. OPS-3(모듈 다섯, 시나리오 23개), OPS-7(연동 테스트 네 파일), OPS-9(이미지·smoke·compose·가짜 입력)는 한 세션에 넘친다.
- 선택지: (a) 후보 그대로 (b) HTTP API를 먼저(OPS-6), MQTT 조립과 연동 테스트를 뒤로(OPS-7A·7B), 큰 task를 A·B로 나눔
- 결정: (b). OPS-3A(StateStore·LineTracker·결합)/OPS-3B(Interlock·Alarm·Processor·DB 작업 타입), OPS-6(스냅숏·HTTP API·예시 이미지 fixture), OPS-7A(paho·워커 스레드·조립·흐름 연동)/OPS-7B(지연 측정), OPS-9A(이미지·smoke)/OPS-9B(개발용 compose·fake_feed·COMPONENT.md). DB 쓰기 작업 타입은 `store/jobs.py`에 두고 OPS-3B가 만든다(M1이 M2에 의존하지 않게). DB 스레드는 도메인을 import하지 않고 콜백과 주입한 상관분석 함수로 결과를 낸다(OPS-5가 `store/`를 고치지 않아 OPS-6과 병렬 가능).
- 이유: 선행 산출물이 없는 테스트를 요구하지 않고, task마다 한 세션·8단계 안에 끝나게 한다. OPS-10 이름은 조율 지시와 spec 여러 곳이 쓰므로 번호를 다시 매기지 않고 A·B 접미사로 나눴다.
- 영향: `00-overview.md` 6절(계획 파일을 가리킴), 02·03·04·06·07 머리말, `08-verification.md` 5절, `docs/plan/`

### D-38 설정 키는 OPS-1이 모두 만든다
- 선택지: (a) 영역을 처음 만드는 task가 자기 절을 추가 (b) OPS-1이 모든 절을 한 번에
- 결정: (b). 키와 기본값·범위가 spec 표에 모두 고정되어 있다.
- 이유: `config.py`·`config/default.yaml`이 뒤 task의 scope에서 빠져 병렬 조합이 늘고, 범위 검사 테스트(`correlation.default_lag_s` 등)가 OPS-1에서 바로 가능하다.
- 영향: `docs/plan/01-core.md` OPS-1 A7

### D-39 PdM 형식 의존의 위치와 OPS-10
- 문맥: PdM Result·PdM Spectrum은 PdM spec과 Shared DOCUMENT_CHANGE로 나중에 확정된다(조율 C-04·C-12). 그 전에 OPS-1~OPS-9B를 A-05·A-06 가정으로 진행한다.
- 결정: PdM 형식(필드 이름·필수 여부·스펙트럼 계열 구성)에 기대는 코드는 `mqtt/payloads.py`의 두 파서, `tests/fixtures/payloads/`(PdM fixture와 fixture를 템플릿으로 쓰는 테스트·smoke용 생성 함수 `pdm.py`), `scripts/fake_feed.py`의 PdM 흉내에만 둔다. Docker 테스트와 smoke는 PdM 메시지를 `pdm.py`로만 만들고, fake_feed는 PdM fixture와 키 집합이 같은지 단위 테스트로 확인한다(Codex 리뷰 2·3). `domain/`·`web/`은 파싱된 객체만 쓴다. OPS-10은 조율 agent의 Shared merge 알림을 착수 조건으로 하고 `depends_on`은 OPS-2뿐이라 다른 task를 막지 않는다. OPS-10은 그 자리와 spec만 고치고, `timestamp` 의미·retain·정지 중 동작처럼 **의미**가 다르면 멈춘다(조율 agent가 정함, A-05).
- 영향: `docs/plan/02-mqtt.md` 4·5절, `docs/plan/01-core.md` 1절

### D-40 구현 task의 spec 수정 범위
- 결정: 구현 task는 자기 영역 spec 파일과 `DECISIONS.md`만 고친다(scope에 적은 파일). `00-overview.md`, `08-verification.md`, `AGREEMENTS.md`, `README.md`는 OPS-10 말고는 고치지 않고, 바꿔야 하면 멈춘다.
- 이유: 완료 정의·검증 방법·교차 약속은 계획과 조율의 기준이라 task 안에서 바뀌면 acceptance가 약해질 수 있다. 영역 세부의 오류는 task가 바로 고치는 편이 빠르다(simulator D-41과 같다).
- 영향: `docs/plan/README.md` 5절

### D-41 병렬 규칙
- 결정: 기본은 순서대로 하나씩. 조율 agent가 속도가 필요할 때만 `docs/plan/README.md` 4절 표의 조합을 worktree로 병렬 실행한다. scope가 겹치지 않아야 하고(`DECISIONS.md`만 예외), 고정 포트 acceptance가 겹치지 않아야 한다. 뒤에 merge하는 쪽은 `origin/main`을 merge하고 verify 전체를 다시 돈다.
- 이유: 저장소가 하나라 기본 순차가 안전하다. 공용 fixture(`tests/conftest.py`)와 설정을 OPS-1에 모아 scope를 좁혔으므로 효과가 큰 조합(OPS-5 ∥ OPS-6, 화면 줄기 ∥ 연동 줄기)이 가능하다.
- 영향: `docs/plan/README.md` 4절

### D-42 acceptance의 테스트 이름 고정
- 결정: acceptance는 spec 08 3절 테스트를 pytest node id로 가리킨다. 없는 node id는 pytest가 실패하므로 이름을 바꾸지 않는다. 테스트 추가는 된다.
- 이유: 파일 전체만 돌리면 핵심 테스트가 빠져도 통과한다. 이름을 고정하면 C-xx와 테스트의 대응이 PLAN에 남는다(simulator D-42와 같다).
- 영향: 모든 구현 task의 acceptance

### D-43 Docker 테스트의 호스트 포트
- 문맥: 08 2절 fixture는 `-p 127.0.0.1::1883`(Docker 임의 포트)였다. 2026-09-27 이 맥에서 `eclipse-mosquitto:2.1.2-alpine` 컨테이너를 두 번 `docker restart`하자 호스트 포트가 55140 → 55142 → 55144로 바뀌었다. DB·broker 재시작 테스트는 앱이 같은 주소로 재연결하는지 보는 것이라 이 방식으로는 통과할 수 없다.
- 선택지: (a) 임의 포트 유지, 재시작 뒤 앱 설정을 바꿈 (b) 테스트가 빈 포트를 골라 고정 매핑 (c) `docker pause`로 대체
- 결정: (b). 재시작 테스트는 자기 컨테이너를 쓴다. smoke는 재시작이 없어 임의 포트를 그대로 쓴다.
- 이유: (a)는 재연결을 시험하지 않는다. (c)는 TCP 연결이 끊기지 않아 재연결 경로를 타지 않는다. (b)는 빈 포트를 고른 뒤 `docker run`까지의 짧은 경쟁만 남는다.
- 영향: `08-verification.md` 2절, `docs/plan/05-storage.md` 1절, `docs/plan/08-verification.md` 2·3절

### D-44 fake_feed 자체 검사와 개발 환경 확인
- 결정: `tests/unit/test_fake_feed.py`가 fake_feed의 메시지가 파서로 받아지는지·시나리오·이미지 경로·명령 적용을 확인하고, OPS-9B acceptance가 개발용 compose + fake_feed로 스냅숏과 STOP 적용을 자동 확인한다.
- 이유: HUM-1은 이 환경으로 한다. 사람이 20분을 쓰기 전에 환경이 동작하는지 자동으로 보장한다. PdM 형식이 OPS-10에서 바뀌면 `make test`가 fake_feed 불일치를 잡는다.
- 영향: `07-runtime.md` 5절, `docs/plan/07-runtime.md` OPS-9B

### D-45 계획 Codex 리뷰 반영 (`docs/reviews/plan-codex-1.md`)
- 결정:
  - OPS-4를 OPS-4A(DDL, Docker DB fixture, verify `docker`, 선행 OPS-1)와 OPS-4B(DB 스레드)로 나눈다. broker 재시작 테스트는 OPS-7A에서 OPS-7B로 옮긴다(리뷰 6).
  - smoke 이미지 태그를 `factory-operations:smoke-<commit 12자리>`로 한다. 병렬 worktree가 같은 태그를 덮어써 다른 commit의 이미지로 smoke를 도는 일을 막는다(리뷰 5).
  - HUM-1 acceptance는 6절 항목마다 manual 하나(M01~M10)다. 실패 항목만 `pending`으로 남겨 FIX 뒤 그 항목만 다시 본다(08 7절을 이에 맞춤, 리뷰 8).
  - OPS-1은 `config/default.yaml`의 키 집합과 기본값을 spec 설정 표 전체와 대조한다(리뷰 4).
- 이유: 한 세션 크기, 병렬 검증의 정확성, 사람 확인의 재확인 단위, 설정 누락 방지.
- 영향: `docs/plan/05-storage.md`, `docs/plan/08-verification.md` 3절, `docs/plan/07-runtime.md` OPS-9A, `docs/plan/01-core.md` OPS-1 A7, `08-verification.md` 3.7·7절

### D-46 OPS-10 채택 대상과 확정본 차이
- 문맥: 계획 작성 중 조율 agent가 Shared PR #7(PdM Result·PdM Spectrum·Alarm Event DOCUMENT_CHANGE) merge를 알렸다(merge commit `cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8`). 확정본을 읽어 보니 의미는 A-05·A-06과 같고, 형식이 더 엄격하다: PdM Result `window_start` 필수·`anomaly_score` 0~1, PdM Spectrum은 `rpm`·`freq_step_hz`·`rot_hz`·`bpfo_hz`·`bpfi_hz`·`spectrum_x/y/z`·`envelope_x/y/z`가 모두 필수이고 배열 길이 `floor(500 / freq_step_hz) + 1`, 원소는 유한한 0 이상. Alarm Event는 A-02와 같다.
- 선택지: (a) OPS-2부터 확정 형식으로 구현(spec 02 3.6·3.7절을 이 PR에서 고침) (b) OPS-2는 확정 spec대로(가정) 두고 OPS-10이 채택과 함께 맞춤
- 결정: (b). OPS-10의 채택 대상을 `cb6dc3c`로 고정하고 차이를 `docs/plan/02-mqtt.md` 5.1절 표로 적어 acceptance로 검사한다. 느슨한 해석 테스트 두 개(`test_spectrum_bins_without_step`, `test_spectrum_no_series`)는 이름을 두고 기대값을 거부로 바꾼다. 계약에 맞춰 검사를 더 엄격하게 하는 변경이라 acceptance 약화가 아니다. OPS-2 바로 뒤에 OPS-10을 하도록 조율 agent에 권장한다.
- 이유: 계약 채택은 `contract_ref`와 함께 한 PR에서 추적되어야 하고(조율 C-05), spec 수정·채택을 한 task에 모으면 PdM 형식 의존 자리(D-39)만 고치면 된다. OPS-2 바로 뒤에 하면 되돌리는 비용은 파서 두 개와 테스트 몇 개뿐이다.
- 영향: `docs/plan/02-mqtt.md` 5절, `docs/plan/00-overview.md`, `docs/plan/README.md` 4·6절, `00-overview.md` 6절

## 8. 구현 (구현 task, 2026-09-27)

### D-47 로그 억제 대상 (OPS-1)
- 문맥: 01 6절은 "같은 (event, topic, reason) 조합은 10초에 한 번"이라고만 적어, 글자 그대로면 `alarm_raised`처럼 topic·reason이 없는 이벤트도 10초 안의 두 번째 기록(예: WARNING 뒤 CRITICAL Alarm)이 빠진다.
- 선택지: (a) 모든 이벤트에 억제 (b) WARNING 이상에만 기본 억제, 호출에서 `throttle=`로 바꿈 (c) 억제할 이벤트 이름 목록을 코드에 둠
- 결정: (b). `log.EventLogger.log(level, event, throttle=None, **fields)`는 `throttle`이 없으면 `level >= WARNING`일 때 억제한다.
- 이유: 반복되어 넘치는 것은 잘못된 입력·큐 초과·DB 오류(WARNING 이상)이고, Alarm·명령 기록(INFO)은 건마다 남아야 한다. (c)는 이벤트가 늘 때마다 목록을 고쳐야 한다.
- 영향: `01-core.md` 6절, `src/factory_operations/log.py`

### D-48 Shared `cb6dc3c` 채택 (OPS-10)
- 문맥: Shared PR #7(PdM Result·PdM Spectrum·Alarm Event DOCUMENT_CHANGE)이 merge되었다(`cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8`, 조율 C-20). 조율 C-21에 따라 PLAN 순서(M5)보다 앞당겨 OPS-2 바로 뒤에 채택했다.
- 결정: `SHARED_CONFIG.json` `contract_ref`를 이 commit으로 한다. 90-shared 1절로 INTERFACES·CONVENTIONS를 읽어 `docs/plan/02-mqtt.md` 5.1절 표와 비교했고 표 밖의 차이는 없었다. 의미(윈도우 끝 `timestamp`, Simulator 시계, retain false, `rpm == 0` 미발행, 재가동 뒤 첫 결과 = 재가동 chunk + 1초)는 A-05·A-06 가정과 같다. 형식은 확정본을 따른다: PdM Result `window_start` 필수·`anomaly_score` 0~1, PdM Spectrum 필드 전부 필수·배열 길이 `floor(500 / freq_step_hz) + 1`·원소 유한한 0 이상·`freq_step_hz > 0`. D-32의 느슨한 해석(이름 기반 계열 수집, `freq_start_hz`·`envelope_freq_step_hz`, bin 축, `no_series`)은 없앤다.
- 테스트: D-46대로 `test_spectrum_bins_without_step`·`test_spectrum_no_series`는 이름을 두고 거부 기대로 바꿨다. 같은 이유로 `test_spectrum_single_panel`·`test_spectrum_envelope_panel`도 확정 예시 fixture로 바꿨다(확정본에서는 패널이 항상 둘이고 각 3계열이라 "패널 1개" 메시지가 성립하지 않는다). 가정 스펙트럼 fixture 3개는 지우고 `shared_pdm_spectrum.json`으로 대신했다. `pdm_result_draft.json`은 확정 형식에도 맞아 남겼다.
- 이유: 계약 채택을 `contract_ref`와 함께 한 PR에서 추적하고(조율 C-05), 뒤 task(OPS-3A 이후)의 PdM 메시지가 처음부터 확정 형식이 되게 한다.
- 영향: `SHARED_CONFIG.json`, `02-mqtt.md` 3.6·3.7절, `08-verification.md` 2·3.2절, `07-runtime.md` 5절, `AGREEMENTS.md` 머리말·목록·A-01·A-02·A-05·A-06·끝 표, `README.md`, `docs/COMPONENT.md`, `src/factory_operations/mqtt/payloads.py`, `tests/fixtures/payloads/`, `tests/unit/test_payloads.py`

### D-49 상관분석 합성 데이터의 seed (OPS-5)
- 문맥: 08 3.4절의 합성 데이터(점수 30초 계단, 수준 `uniform(0, 1)`, 제품 2초 간격, 불량 확률 `0.05 + 0.6 × score(t − 13)`)는 표본이 300개뿐이고 계단 폭(30초)이 lag 범위와 같아 lag 곡선의 봉우리가 완만하다(lag 1초 차이에 기대 계수 약 0.02). seed 0~49에서 `compute`를 돌리면 31개가 두 기대(`best.lag_s` 12~14, `at_default.pearson > 0.3`)를 모두 만족하고 나머지는 한쪽을 벗어난다(최저 `at_default.pearson` 0.23, `best.lag_s` 5~17). seed 0~199의 lag별 평균 곡선은 lag 13에서 최대(0.3597)이고 `at_default.pearson` 평균은 0.36이다.
- 선택지: (a) seed 하나를 고정(0) (b) 여러 seed 평균으로 검사 (c) 데이터 규칙을 바꿈(표본 수·수준 분포)
- 결정: (a). `tests/unit/test_correlation.py`의 `synthetic(seed=0)`이고, `tests/docker/test_correlation_db.py`도 같은 생성 규칙과 seed 0을 쓴다. 08 3.4절 규칙과 acceptance 기대값은 바꾸지 않는다.
- 이유: 08 3.4절은 "seed 고정"만 정하고 값은 정하지 않는다. 규칙과 기대값을 그대로 두고 방법의 정확성(평균 곡선 봉우리 13초, 계수는 scipy 값의 4자리 반올림)은 별도로 확인했다. (b)·(c)는 acceptance 명령이 가리키는 테스트의 의미를 바꾼다. 기본 seed 0은 고른 값이 아니라 첫 값이다.
- 영향: `tests/unit/test_correlation.py`, `tests/docker/test_correlation_db.py`
