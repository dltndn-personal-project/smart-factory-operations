# 05 저장 계획 (M2)

> 목적: OPS-4A(DDL, Docker DB fixture)와 OPS-4B(DB 스레드)의 PLAN 정의와 단계 개요.
> 읽어야 할 때: 두 task를 실행하거나 등록할 때, DB 스레드의 경계를 볼 때. 같이 읽을 spec: `docs/spec/05-storage.md`, `docs/spec/AGREEMENTS.md` A-08.

## 1. 경계

- DB 스레드(`store/db.py`)는 도메인 모듈을 import하지 않는다. 입력은 DB 큐의 작업(`store/jobs.py`, OPS-3B)이고, 결과는 생성자로 받은 콜백으로 낸다: `on_db_ok(bool)`, `on_summary(dict)`, `on_correlation(dict)`. 상관분석 계산 함수 `compute_correlation(inspections, scores, cfg) -> dict`도 주입받는다(없으면 조회·계산을 건너뛴다). StateStore 연결과 OPS-5 함수 주입은 OPS-7A의 조립이 한다(D-37). 그래서 OPS-5는 `store/`를 고치지 않고, OPS-5와 OPS-6을 병렬로 돌릴 수 있다.
- 요약 콜백의 dict는 spec 05 5절 네 조회의 결과(`produced`, `inspected`, `defects`, 목록 세 개의 행 dict, `summary_at`)다. 행 dict의 키는 SELECT 열 이름 그대로다. OPS-6의 스냅숏이 이것을 받는다.
- Docker fixture(`tests/docker/conftest.py`)는 OPS-4A가 `timescale_db`·`clean_db`를 만들고 OPS-7A가 broker·앱 fixture를 더한다. 컨테이너 호스트 포트는 테스트가 고른 빈 포트로 고정한다(`-p 127.0.0.1:<port>:5432`). `docker restart` 뒤에도 포트가 유지되어야 재연결 테스트가 맞다(D-43). 재시작 테스트는 세션 컨테이너를 흔들지 않도록 자기 컨테이너를 쓴다.

- spec 00 6절의 OPS-4는 DDL·Docker 기반·DB 스레드(작업 9종, 배치, 재연결, 요약, 주기 작업)를 한 번에 해서 한 세션에 넘친다. DDL과 Docker 검증 기반(OPS-4A)은 도메인 코드가 필요 없으므로 OPS-1 뒤에 바로 할 수 있게 떼어 냈다(Codex 리뷰 6, D-45).

## 2. task

### OPS-4A DDL과 Docker DB fixture

```yaml
  - id: OPS-4A
    milestone: M2
    type: feature
    title: db/schema.sql, Docker DB fixture, verify docker
    why: integration이 이 DDL을 initdb로 적용하고, 뒤 task의 DB 연동 테스트가 같은 이미지·같은 적용 방식을 쓴다 (C-03, spec 05 1·4절, A-08, D-09·D-25·D-26)
    depends_on: [OPS-1]
    scope: [db/**, tests/docker/**, Makefile, agent/config.yaml, docs/spec/05-storage.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: Docker 연동 테스트 전체가 통과한다
        check: {type: command, run: "make docker-test"}
      - id: A2
        text: db/schema.sql을 timescale/timescaledb:2.30.1-pg17 initdb로 적용하면 테이블 8개(schema_info 포함)·view defect_result·hypertable sensor_chunk·schema_info 버전 1이 생기고, psql -v ON_ERROR_STOP=1로 한 번 더 실행해도 종료 코드 0이다 (C-03)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_schema.py::test_schema_objects tests/docker/test_schema.py::test_schema_reapply"}
      - id: A3
        text: db/schema.sql이 spec 05 4절 DDL과 주석·공백을 빼고 같다 (A-08)
        check:
          type: command
          run: |
            python3 - <<'EOF'
            import re, sys
            sec = open("docs/spec/05-storage.md").read().split("## 4. DDL", 1)[1]
            fence = "`" * 3
            ddl = re.search(fence + r"sql\n(.*?)" + fence, sec, re.S).group(1)
            norm = lambda s: " ".join(re.sub(r"--[^\n]*", "", s).split())
            ok = norm(ddl) == norm(open("db/schema.sql").read())
            print("schema.sql matches spec 05 section 4:", ok)
            sys.exit(0 if ok else 1)
            EOF
      - id: A4
        text: tests/docker의 모든 테스트가 docker 마커를 가져 make test(-m "not docker")에 들어가지 않는다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q -m 'not docker' tests/docker; test $? -eq 5"}
      - id: A5
        text: agent/config.yaml verify에 spec 08 5절의 docker 명령이 그대로 있다
        check: {type: command, run: "python3 -c \"import sys, yaml; v = yaml.safe_load(open('agent/config.yaml'))['verify']; sys.exit(0 if {'name': 'docker', 'run': 'make docker-test'} in v else 1)\""}
    size: S
```

단계 개요:
1. `db/schema.sql`: spec 05 4절 DDL 그대로. → A3
2. `Makefile`에 `docker-test`, `tests/docker/conftest.py`에 빈 포트 고르기, `timescale_db`(빈 포트 고정, initdb 마운트, psycopg 연결과 `schema_info` 1까지 60초)·`clean_db`. id로만 지운다. → A4
3. `test_schema.py`(`docker exec -i <db> psql -v ON_ERROR_STOP=1 -U factory -d factory < db/schema.sql` 재실행 포함). → A2
4. `make docker-test` 확인 → `agent/config.yaml`에 `docker` 추가 → `validate.py --remote`. → A1, A5

읽을 spec: 05 1·4절, `AGREEMENTS.md` A-08, 08 2·3.6절(`test_schema.py`), D-09·D-25·D-26·D-43.

- 첫 실행에서 TimescaleDB 컨테이너 기동과 initdb에 10~20초 걸린다. 이미지가 없으면 인터넷으로 받는다(H-1).
- OPS-1만 끝나면 시작할 수 있어 M1 task와 병렬로 돌릴 수 있다(`README.md` 4절). 기본 순서는 PLAN 순서(M1 뒤)다.

### OPS-4B DB 스레드

```yaml
  - id: OPS-4B
    milestone: M2
    type: feature
    title: DB 스레드(쓰기 작업·센서 배치·요약·주기 작업·재연결)
    why: 모든 입력과 판단 결과가 Shared 5.2·5.3 저장 요구대로 한 DB에 남고, DB가 느리거나 끊겨도 Interlock이 막히지 않으며, 화면의 목록·집계가 DB 한 소스에서 나와야 한다 (C-04 기반, spec 05 2·3·5절, D-14·D-15·D-28·D-29)
    depends_on: [OPS-3B, OPS-4A]
    scope: [src/factory_operations/store/**, tests/docker/test_db_writer.py, docs/spec/05-storage.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트와 Docker 연동 테스트 전체가 통과한다
        check: {type: command, run: "make test && make docker-test"}
      - id: A2
        text: 05 2절 작업 9종이 표대로 행을 만들고 중복을 무시하며, 센서 25개가 2번 이상의 배치로 모두 기록되고, control_result는 result가 비어 있을 때만 갱신한다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_db_writer.py::test_each_job_writes_row tests/docker/test_db_writer.py::test_duplicates_ignored tests/docker/test_db_writer.py::test_sensor_batches tests/docker/test_db_writer.py::test_control_result_update_once"}
      - id: A3
        text: DB 컨테이너 docker restart 뒤 db_ok가 false가 되었다가 15초 안에 true로 돌아오고 이후 쓰기가 된다 (05 3절, D-43)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_db_writer.py::test_db_restart_recovers"}
      - id: A4
        text: schema_info가 없으면 db_ok false(db_schema_missing)이고, 요약 콜백이 05 5절 값을 주며, 상관분석 주기에 주입한 계산 함수가 두 조회 결과(window_s 조건 포함)를 받는다 (05 3·5절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_db_writer.py::test_schema_missing_not_ok tests/docker/test_db_writer.py::test_summary_callback tests/docker/test_db_writer.py::test_correlation_hook_receives_rows"}
      - id: A5
        text: psycopg를 import하는 모듈이 store/db.py 하나다 (01 1절)
        check: {type: command, run: "test \"$(grep -rlE '^[[:space:]]*(import|from)[[:space:]]+psycopg([[:space:].]|$)' src | sort | tr '\\n' ' ')\" = 'src/factory_operations/store/db.py '"}
    size: M
```

단계 개요:
1. `store/sql.py`: 작업 9종의 SQL(05 2절), 요약 네 조회, 상관분석 두 조회와 window 조건(05 5절).
2. `store/db.py` 연결·스키마 확인·재연결 2초: `psycopg.connect(..., autocommit=True, connect_timeout=5, statement_timeout 5000)`. 연결이 없을 때 꺼낸 작업은 버리고 센다. → A4
3. 루프: `get(timeout=0.2)`, 센서 배치(20행 또는 1초, 한 트랜잭션), 나머지 작업 즉시, 실패는 `db_error` 로그 후 버림, 주기 작업(요약 2초, 상관분석 10초, `db_ok` false면 건너뜀), 콜백. 종료 때 남은 배치를 쓰고 닫는다. → A2
4. `tests/docker/test_db_writer.py`(OPS-4A fixture, 재시작 테스트는 자기 DB 컨테이너·빈 포트 고정). → A2~A4
5. `make test`, `make docker-test`. → A1, A5

읽을 spec: 05 2·3·5·6절, 01 2·7절(DB 큐, 종료), 08 3.6절(`test_db_writer.py`), D-11·D-14·D-15·D-27·D-28·D-29·D-43.
