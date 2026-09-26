# 03 판단 계획 (M1)

> 목적: OPS-3A(StateStore, LineTracker, 시간 결합)와 OPS-3B(Interlock, Alarm, 워커 처리 함수)의 PLAN 정의와 단계 개요.
> 읽어야 할 때: 두 task를 실행하거나 등록할 때. 같이 읽을 spec: `docs/spec/03-control.md`, `docs/spec/01-core.md` 2·3절, `docs/spec/04-analysis.md` 1절.

## 1. 나눈 이유와 경계

spec 00 6절의 OPS-3(판단 로직)은 모듈 다섯 개와 시나리오 23개라 한 세션에 넘치므로 둘로 나눴다(D-37).

| task | 모듈 | 테스트 |
|---|---|---|
| OPS-3A | `domain/state.py`(StateStore, PdM 이력), `domain/line.py`(LineTracker), `domain/join.py` | `test_state.py`, `test_line.py`, `test_join.py` |
| OPS-3B | `domain/interlock.py`, `domain/alarm.py`, `domain/worker.py`의 `Processor`(메시지 하나 처리, 운영자 명령, `tick`), `store/jobs.py`(DB 쓰기 작업 타입) | `test_interlock.py`(S-01~S-12), `test_alarm.py`(L-01~L-11), `test_worker.py` |

- 워커 **스레드 루프**(큐에서 꺼내기, 0.1초 tick 호출, 종료)는 OPS-7A가 `worker.py`에 더한다. OPS-3B의 `Processor`는 스레드·큐 없이 직접 부를 수 있는 함수들이다(시나리오 테스트가 이것을 부른다, spec 03 6절).
- `LineTracker.update()`는 DB 작업을 만들지 않고 결과(기록할 변화 여부, 재가동 이벤트, 기준 시각 변경)를 돌려준다. `Processor`가 그 결과로 DB 작업과 Alarm 초기화를 한다. 그래서 OPS-3A는 DB 작업 타입을 몰라도 된다.
- DB 쓰기 작업 타입은 `store/jobs.py`의 순수 dataclass다. 각 작업은 spec 05 2절 표의 이름을 `kind`(`sensor`, `line_change`, `product`, `inspection`, `equipment`, `alarm`, `control_issued`, `control_result`, `control_observed`)로 갖고, SQL에 필요한 값(Payload timestamp와 Operations 시각은 UTC datetime)을 담는다. OPS-4B의 DB 스레드가 소비한다. OPS-3B가 만드는 이유: 작업을 만드는 쪽이 M1에 있어야 M1이 M2에 의존하지 않는다(D-37).

## 2. task

### OPS-3A StateStore, LineTracker, 시간 결합

```yaml
  - id: OPS-3A
    milestone: M1
    type: feature
    title: StateStore, LineTracker, 시간 결합
    why: Interlock·Alarm·저장·화면이 모두 라인 상태, 재가동 기준 시각, Fault Level 변화점, PdM 이력을 같은 규칙으로 봐야 한다 (spec 01 3절, 03 1절, 04 1절, D-17)
    depends_on: [OPS-2]
    scope: [src/factory_operations/domain/__init__.py, src/factory_operations/domain/state.py, src/factory_operations/domain/line.py, src/factory_operations/domain/join.py, tests/unit/test_state.py, tests/unit/test_line.py, tests/unit/test_join.py, docs/spec/03-control.md, docs/spec/04-analysis.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: LineTracker가 기동 뒤 첫 RUNNING·STOPPED→RUNNING·offline→RUNNING에서 기준 시각을 잡고, 1초 주기 같은 값은 변화로 보지 않으며, fault_changes는 값이 바뀔 때만 늘고, 재가동 이벤트는 마지막 conveyor가 STOPPED였다가 RUNNING일 때만 낸다(첫 동기화·RUNNING→offline→RUNNING 제외) (03 1.2절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_line.py tests/unit/test_line.py::test_first_running_sets_reference tests/unit/test_line.py::test_stopped_to_running_new_reference tests/unit/test_line.py::test_offline_to_running_new_reference tests/unit/test_line.py::test_periodic_status_is_not_change tests/unit/test_line.py::test_fault_changes_only_on_change tests/unit/test_line.py::test_restart_event_rules"}
      - id: A3
        text: 가짜 시계로 Fault Level을 700초 동안 바꾸지 않아도 fault_level_at(현재)가 그 값이다 (03 1.1절, 08 3.3절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_line.py::test_fault_level_kept_after_700s"}
      - id: A4
        text: fault_level_at는 변화점과 같은 timestamp면 그 값, 첫 변화점 이전은 null이고, health_index_at_time은 차가 정확히 max_gap_s면 붙고 1 ms 넘으면 null, 미래 결과는 쓰지 않으며 결과가 없어도 sensor_id는 라인 센서다 (04 1절, 08 3.4절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_join.py tests/unit/test_join.py::test_fault_level_at_inclusive tests/unit/test_join.py::test_fault_level_before_first_is_null tests/unit/test_join.py::test_health_index_gap_boundary tests/unit/test_join.py::test_future_pdm_not_used tests/unit/test_join.py::test_no_pdm_keeps_line_sensor"}
      - id: A5
        text: StateStore.snapshot_view()가 락 안에서 얕은 복사를 돌려주고, PdM 이력이 timestamp 기준 최근 pdm.history_s(120초)만 남는다 (01 3절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_state.py::test_snapshot_view_copies tests/unit/test_state.py::test_pdm_history_trims_120s"}
    size: M
```

단계 개요:
1. `state.py`: StateStore(01 3절 표의 항목, `threading.Lock` 하나, `snapshot_view()`), PdM 이력(센서별, `timestamp` 순, 120초). → A5
2. `line.py`: 1.1절 상태, 1.2절 갱신 규칙, `fault_changes` 보존 규칙(600초 + 그 이전 가장 최근 하나), `line_sensor_id`. `update()`의 반환값(1절). → A2, A3
3. `join.py`: `fault_level_at(ts)`, `health_index_at_time(vision_ts, history, max_gap_s)`(04 1절). → A4
4. 테스트 세 파일, `make test`. → A1

읽을 spec: 01 3·5절, 03 1절, 04 1절, 08 3.3·3.4절, D-17·D-21.

### OPS-3B Interlock, Alarm, 워커 처리 함수

```yaml
  - id: OPS-3B
    milestone: M1
    type: feature
    title: Interlock, AlarmManager, 워커 처리 함수와 시나리오
    why: CRITICAL이면 한 번만 STOP을 보내고 결과로 대기를 끝내며, WARNING·CRITICAL 진입만 Alarm으로 내고, 모든 입력을 정해진 순서로 처리해 DB 작업을 만든다 (C-02, spec 03 2~4·6절, 05 2절, D-18~D-22)
    depends_on: [OPS-3A]
    scope: [src/factory_operations/domain/interlock.py, src/factory_operations/domain/alarm.py, src/factory_operations/domain/worker.py, src/factory_operations/domain/state.py, src/factory_operations/store/__init__.py, src/factory_operations/store/jobs.py, tests/unit/test_interlock.py, tests/unit/test_alarm.py, tests/unit/test_worker.py, docs/spec/03-control.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: Interlock 시나리오 S-01~S-12가 모두 spec 03 6절 표대로다 (C-02)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q $(for i in 01 02 03 04 05 06 07 08 09 10 11 12; do printf 'tests/unit/test_interlock.py::test_s%s ' \"$i\"; done)"}
      - id: A3
        text: Alarm 시나리오 L-01~L-11이 모두 spec 03 6절 표대로다(L-07은 발행기 기록 순서 Alarm Event → STOP) (C-02, C-05 발행 순서)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q $(for i in 01 02 03 04 05 06 07 08 09 10 11; do printf 'tests/unit/test_alarm.py::test_l%s ' \"$i\"; done)"}
      - id: A4
        text: 명령 결과 확인이 자기 명령은 control_result 작업과 대기 종료, 모르는 command_id는 control_observed 작업, 같은 last_command는 한 번만, command_id null은 기록하지 않음을 만족한다 (03 3.4절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_worker.py::test_known_command_result_updates tests/unit/test_worker.py::test_unknown_command_observed_insert tests/unit/test_worker.py::test_same_last_command_once tests/unit/test_worker.py::test_null_command_id_not_recorded"}
      - id: A5
        text: 처리 순서 표대로 센서 chunk는 fault_level 결합·sensor 작업·진동 링(형식·seq가 바뀌면 비움), Vision Result는 health_index_at_time 결합·inspection 작업, 스펙트럼은 라인 센서만 교체, Line Status 변화만 line_change 작업, 거부된 메시지는 카운터만 남긴다 (03 2절, 02 3절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_worker.py::test_sensor_chunk_joined_and_ringed tests/unit/test_worker.py::test_ring_resets_on_format_or_seq_gap tests/unit/test_worker.py::test_vision_joined_health_index tests/unit/test_worker.py::test_spectrum_only_line_sensor tests/unit/test_worker.py::test_line_change_job_only_on_change tests/unit/test_worker.py::test_rejected_message_counted"}
      - id: A6
        text: domain과 store/jobs.py가 paho·psycopg·FastAPI·uvicorn을 import하지 않는다 (01 1절)
        check: {type: command, run: "! grep -rnE '^[[:space:]]*(import|from)[[:space:]]+(paho|psycopg|fastapi|uvicorn)' src/factory_operations/domain src/factory_operations/store/jobs.py"}
    size: M
```

단계 개요:
1. `store/jobs.py`: 1절의 작업 타입 9종.
2. `interlock.py`: 3.1절 상태, 3.2절 평가(판정 대상, 조건 네 개, 발행 실패 시 불변, 성공 시 `pending`·`last_trigger_ts`), 결과별 `pending` 종료, 시간 초과.
3. `alarm.py`: 센서별 이전 상태, 심각도 비교, 재가동 이벤트 초기화, Alarm 값 객체(OPS-2 `build_alarm` 입력).
4. `worker.py` `Processor`: 2절 처리 순서 표, 3.3절 운영자 명령(`OperatorCommand(command, future)`, future 결과·`mqtt_disconnected`), 3.4절 결과 확인(`issued` 100, `seen` 200), `tick`, 진동 링, 카운터. 발행은 `publisher.publish`(OPS-2 직렬화), DB는 `db_sink.put_nowait(job)`. 같은 PdM Result에서 Alarm Event를 STOP보다 먼저 발행한다.
5. `test_interlock.py`(`test_s01`~`test_s12`), `test_alarm.py`(`test_l01`~`test_l11`): 가짜 시계·발행기·DB 싱크로 `Processor`를 직접 부른다. → A2, A3
6. `test_worker.py`. → A4, A5
7. `make test`, 순수성 검사. → A1, A6

읽을 spec: 03 전부, 01 2·3절, 02 4절, 05 2절, 08 3.3절, D-16·D-18·D-19·D-20·D-21·D-22·D-28.
