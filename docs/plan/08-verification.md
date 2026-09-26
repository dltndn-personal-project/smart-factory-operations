# 08 검증 계획 (M3, M6)

> 목적: `agent/config.yaml` verify 명령을 어느 task가 언제 넣는지와 그 비용, acceptance 명령의 규칙과 고정 포트, OPS-7B(지연 측정)와 사람 task HUM-1의 PLAN 정의와 기록 방법.
> 읽어야 할 때: verify 명령을 추가하는 task(OPS-1, OPS-4A, OPS-9A), OPS-7B, 사람 task를 준비·기록할 때. 같이 읽을 spec: `docs/spec/08-verification.md`.

## 1. verify 명령 추가 순서

명령 문자열은 spec 08 5절 그대로다. 추가하는 task는 먼저 그 명령을 직접 실행해 통과를 확인하고, 추가한 뒤 `python3 agent/core/tools/validate.py --remote`를 실행한다(AGENTS.md 검사 절). 목록 끝에 붙인다.

| 순서(PLAN 순) | 추가하는 task | name | run | 추정 시간 |
|---|---|---|---|---|
| 기존 | BOOT-1 | `agent-files` | `python3 agent/core/tools/validate.py` | 5초 미만 |
| 1 | OPS-1 | `unit` | `make test` | 30초 미만(첫 실행 pip 설치 +1~2분) |
| 2 | OPS-4A | `docker` | `make docker-test` | OPS-4A 약 30초 → OPS-7B 뒤 약 3분(상한 300초, OPS-7B A3) |
| 3 | OPS-9A | `smoke` | `make smoke` | 약 1.5분(첫 이미지 빌드는 수 분 더) |

- 추정 시간은 계획 시점의 어림이다. 실제 값은 각 task PR 본문에 적는다.
- `agent.py verify`는 task acceptance를 먼저, 그다음 verify 명령 전체를 돈다. task마다 내는 공통 비용(PLAN 순서로 진행할 때):

| 구간 | 공통 verify | 공통 비용(추정) |
|---|---|---|
| OPS-1~OPS-3B | agent-files, unit | 30초 미만 |
| OPS-4A~OPS-7A | + docker | 1~2.5분 |
| OPS-7B, OPS-8 | + docker(지연 측정 포함) | 3~3.5분 |
| OPS-9A 뒤(OPS-9B, OPS-10, FIX) | + smoke | 4.5~5분 |

- `docker` 뒤로는 Docker Desktop이 켜져 있어야 모든 task가 끝난다(화면만 고치는 OPS-8도). 꺼져 있으면 실패로 멈춘다(H-1).
- `budget.verify_attempts` 3, `check_timeout` 1800초는 바꾸지 않는다. smoke 첫 빌드도 1800초 안이다.

## 2. acceptance 명령의 규칙

- 명령은 이 맥에서 비대화식으로 돈다: Docker 28.3(Compose v2.38), `python3` 3.12.13, `/usr/bin/make` 3.81, `curl`, `jq`, `sips`, `gh`. 호스트에 `mosquitto`·`psql`·pytest는 없다. pytest는 `.venv`로, MQTT 클라이언트는 venv의 paho로, `psql`은 DB 컨테이너 안의 것으로 쓴다. Node는 쓰지 않는다.
- `agent.py`는 명령을 `/bin/sh`로 실행한다. 여러 줄 명령은 각 줄의 실패를 `|| exit 1`이나 `&&`로 잇는다.
- 테스트 이름을 가리키는 acceptance는 그 이름의 테스트가 있어야 통과한다(D-42). 테스트 파일에 테스트를 더하는 것은 된다. 이름을 바꾸거나 기대값을 느슨하게 하면 acceptance를 약하게 바꾼 것이다(AGENTS.md 불변 규칙).
- Docker 컨테이너 호스트 포트(D-43): spec 08 2절은 `-p 127.0.0.1::1883`(Docker 임의 포트)이지만 **`docker restart` 뒤에는 임의 포트가 새로 배정된다**(2026-09-27 이 맥에서 `eclipse-mosquitto:2.1.2-alpine`으로 확인: 55140 → 55142 → 55144). 그래서 Docker 테스트 fixture는 테스트가 빈 포트를 골라(`socket.bind(("127.0.0.1", 0))`) `-p 127.0.0.1:<port>:<container port>`로 고정한다. smoke는 재시작하지 않으므로 임의 포트를 그대로 쓴다.
- 고정 포트와 compose 프로젝트(동시에 도는 검증끼리 겹치지 않게):

| 사용처 | HTTP | MQTT | DB | compose 프로젝트·이름 |
|---|---|---|---|---|
| OPS-1 A5 | 18280 | (없음, `mqtt://127.0.0.1:1`) | (없음) | |
| OPS-7A A7 | 18281 | (없음) | (없음) | |
| OPS-9B A4 | 18290 | 11990 | 15490 | `fops-ops9b` |
| Docker 테스트(`make docker-test`) | 테스트가 고른 빈 포트 | 빈 포트 고정 | 빈 포트 고정 | 컨테이너 `fops-test-*-<hex8>` |
| smoke(OPS-9A A1, verify) | Docker 임의 포트 | 임의 | 임의 | `fops-smoke-<hex8>` |
| 개발·HUM-1 | 8080 | 1883 | 5432 | `factory-operations`(기본) |

## 3. OPS-7B broker 재연결과 지연 측정 (M3)

```yaml
  - id: OPS-7B
    milestone: M3
    type: feature
    title: broker 재시작 복구, Interlock 지연(C-05), Dashboard 갱신 지연(C-08) 테스트
    why: broker가 재시작돼도 앱이 스스로 복구하고, CRITICAL 판정 뒤 1초 안에 STOP이 나가며(Component 목표), 입력이 5초 안에 화면 데이터에 반영된다는 과제 기준을 정해진 방법으로 매 변경마다 잰다 (C-05, C-08, spec 02 5절, 08 3.6·4절, A-10·A-11, D-34)
    depends_on: [OPS-7A]
    scope: [tests/docker/test_broker_restart.py, tests/docker/test_interlock_latency.py, tests/docker/test_dashboard_latency.py, tests/docker/conftest.py, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 5회 반복에서 재가동 기준 시각 뒤 CRITICAL PdM Result 발행부터 harness의 STOP(reason INTERLOCK_CRITICAL) 수신까지 최댓값이 1.0초 이하이고 매회 Alarm Event도 받는다 (C-05, 08 4.2절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_interlock_latency.py::test_critical_to_stop_within_1s"}
      - id: A2
        text: 60초 부하에서 이벤트 일곱 종류의 D = t_seen − t_rx + P(1.0) + r_max + R(0.2) 최댓값이 5.0초 이하이고 r_max가 0.5초 이하이며, p50·p95·max를 출력한다 (C-08, 08 4.1절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q -s tests/docker/test_dashboard_latency.py::test_dashboard_update_within_5s"}
      - id: A3
        text: Docker 연동 테스트 전체가 300초 안에 통과한다 (spec 08 5절 "약 3분")
        check: {type: metric, run: "s=$(date +%s); make docker-test >/dev/null 2>&1 || { echo failed; exit 1; }; echo $(( $(date +%s) - s ))", max: 300}
      - id: A4
        text: 자기 Mosquitto 컨테이너(빈 포트 고정)를 docker restart하면 15초 안에 /readyz가 200으로 돌아오고 그 뒤 보낸 PdM Result가 equipment_state에 기록된다 (02 5절, 08 3.6절, D-43)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_broker_restart.py::test_broker_restart_recovers"}
    size: M
```

단계 개요:
1. `test_interlock_latency.py`: 08 4.2절(매회 `STOPPED` → `RUNNING` 새 timestamp, `wait_snapshot`으로 `reference_time` 확인, 발행 직전 monotonic, STOP 수신 시각, APPLIED·STOPPED 응답, `pending_stop == null` 확인). → A1
2. `test_dashboard_latency.py`: 08 4.1절 부하와 반영 조건 표 일곱 가지, 0.2초 간격 스냅숏, `r_max`, 이벤트 종류별 p50·p95·max 출력. → A2
3. `test_broker_restart.py`: 자기 broker 컨테이너(빈 포트 고정)로 `running_app`을 띄우고 `docker restart` → `/readyz` 503 → 15초 안 200 → PdM Result 기록 확인. → A4
4. 전체 시간 확인. 넘으면 fixture 재사용(세션 범위)부터 줄이고, 측정 기준(60초, 5.0초, 1.0초)은 줄이지 않는다. → A3

읽을 spec: 08 3.6·4절, 02 5절, `AGREEMENTS.md` A-10·A-11, 03 3.2절, D-34·D-43.

- `wait_snapshot`, `harness`, `running_app`은 OPS-7A의 fixture를 쓰고, PdM 메시지는 `tests/fixtures/payloads/pdm.py`로 만든다(D-39). fixture를 고쳐야 하면 `tests/docker/conftest.py` 안에서만 고친다.

## 4. 사람 task

HUM-1은 `owner: human`이라 `agent.py start`가 고르지 않는다. 조율 agent가 OPS-9B merge 뒤 책임자에게 요청한다(`HUMAN.md`). OPS-10을 기다리지 않는다.

### HUM-1 Dashboard 확인

```yaml
  - id: HUM-1
    milestone: M6
    type: chore
    title: Dashboard 확인 (M-01~M-10)
    why: 화면 배치·색·문구·갱신 모양·렌더링 시간·끊김 표시는 자동 검사로 확인할 수 없다. 시스템 전체 시연 확인은 integration 마지막 milestone에서 따로 한다 (C-10, spec D-03, HUMAN.md H-2)
    depends_on: [OPS-9B]
    scope: [docs/reviews/HUM-1.md]
    owner: human
    acceptance:
      - id: M01
        text: 첫 화면
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-01. 결과는 docs/reviews/HUM-1.md"}
      - id: M02
        text: 갱신과 렌더링 시간
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-02. 결과는 docs/reviews/HUM-1.md"}
      - id: M03
        text: 라인
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-03. 결과는 docs/reviews/HUM-1.md"}
      - id: M04
        text: 설비 상태
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-04. 결과는 docs/reviews/HUM-1.md"}
      - id: M05
        text: Interlock
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-05. 결과는 docs/reviews/HUM-1.md"}
      - id: M06
        text: 재가동
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-06. 결과는 docs/reviews/HUM-1.md"}
      - id: M07
        text: 품질
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-07. 결과는 docs/reviews/HUM-1.md"}
      - id: M08
        text: 상관관계
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-08. 결과는 docs/reviews/HUM-1.md"}
      - id: M09
        text: 끊김 표시
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-09. 결과는 docs/reviews/HUM-1.md"}
      - id: M10
        text: 모양(창 폭, 어두운 테마, Safari)
        check: {type: manual, how: "docs/spec/08-verification.md 6절 M-10. 결과는 docs/reviews/HUM-1.md"}
    size: M
```

준비와 순서(항목 문장은 spec 08 6절이 원본, 여기서 반복하지 않는다):
1. 최신 main에서 `docker compose down -v && docker compose up -d --build`, `make feed`, Chrome으로 `http://localhost:8080`. simulator 단독 compose가 떠 있으면 먼저 내린다(1883 충돌).
2. M-01·M-02(`?debug=1`)를 먼저, 이어서 fake_feed 시나리오(약 3분)를 따라 M-03 → M-04 → M-05 → M-06(START) → M-07 → M-08.
3. M-09(`docker compose stop mosquitto` / `start`, `stop factory-operations` / `start`), M-10(창 폭 1280·1920 px, 어두운 테마, Safari).
약 20분(spec `HUMAN.md` H-2). 목록은 spec 08 6절의 10개 그대로이며 늘리지 않는다. 자동으로 확인되는 것(파일 내용, 스냅숏 값, 지연 측정)은 이 목록에 넣지 않았다.

## 5. 사람 task 기록과 완료

`agent.py`는 사람 task를 시작·검증하지 않으므로 기록은 다음과 같이 한다.

1. 책임자가 확인한 결과를 `docs/reviews/HUM-1.md`에 쓰거나 채팅으로 알린다. 채팅이면 조율 agent가 받은 그대로 옮긴다(판정을 바꾸지 않는다).
   - 형식: 머리말(확인 날짜, 확인한 main commit SHA, 브라우저·macOS 버전), 표(ID | 결과 통과/실패 | 메모), 실패 항목의 재현 방법.
2. 조율 agent가 `agent/tasks/HUM-1.yaml`을 쓴다.
   - 모두 통과: `status: done`, `commit`(확인한 main SHA), `finished_at`, `checks`(모두 `pass`).
   - 일부 실패: `status: verifying`, 통과 항목 `pass`, 실패 항목 `pending`. 실패 항목마다 `FIX-<번호>` task를 PLAN에 추가한다(`00-overview.md` 4절).
3. 1·2를 한 PR로 올리고 `validate.py --remote` 통과 뒤 조율 agent가 merge한다(spec D-01).
4. FIX가 merge되면 책임자가 `pending` 항목만 다시 확인하고 2~3을 반복한다.
5. OPS-10이 HUM-1 뒤에 끝나 스펙트럼 계열 구성이 바뀌었으면 조율 agent가 M-02의 스펙트럼 부분만 다시 확인을 요청할 수 있다(선택).

책임자의 실제 확인 없이 `pass`를 쓰지 않는다(AGENTS.md 불변 규칙: 검증 증거 없이 완료를 주장하지 않는다).
