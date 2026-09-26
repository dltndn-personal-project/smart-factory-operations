# 05 저장 계획 (M2)

> 목적: OPS-4(DDL, DB 스레드, Docker DB fixture)의 PLAN 정의와 단계 개요.
> 읽어야 할 때: OPS-4를 실행하거나 등록할 때, DB 스레드의 경계를 볼 때. 같이 읽을 spec: `docs/spec/05-storage.md`, `docs/spec/AGREEMENTS.md` A-08.

## 1. 경계

- DB 스레드(`store/db.py`)는 도메인 모듈을 import하지 않는다. 입력은 DB 큐의 작업(`store/jobs.py`, OPS-3B)이고, 결과는 생성자로 받은 콜백으로 낸다: `on_db_ok(bool)`, `on_summary(dict)`, `on_correlation(dict)`. 상관분석 계산 함수 `compute_correlation(inspections, scores, cfg) -> dict`도 주입받는다(없으면 조회·계산을 건너뛴다). StateStore 연결과 OPS-5 함수 주입은 OPS-7A의 조립이 한다(D-37). 그래서 OPS-5는 `store/`를 고치지 않고, OPS-5와 OPS-6을 병렬로 돌릴 수 있다.
- 요약 콜백의 dict는 spec 05 5절 네 조회의 결과(`produced`, `inspected`, `defects`, 목록 세 개의 행 dict, `summary_at`)다. 행 dict의 키는 SELECT 열 이름 그대로다. OPS-6의 스냅숏이 이것을 받는다.
- Docker fixture(`tests/docker/conftest.py`)는 OPS-4가 `timescale_db`·`clean_db`를 만들고 OPS-7A가 broker·앱 fixture를 더한다. 컨테이너 호스트 포트는 테스트가 고른 빈 포트로 고정한다(`-p 127.0.0.1:<port>:5432`). `docker restart` 뒤에도 포트가 유지되어야 재연결 테스트가 맞다(D-43). 재시작 테스트는 세션 컨테이너를 흔들지 않도록 자기 컨테이너를 쓴다.

## 2. task

### OPS-4 DDL, DB 스레드

```yaml
  - id: OPS-4
    milestone: M2
    type: feature
    title: db/schema.sql, DB 스레드(쓰기·배치·요약·재연결), Docker DB fixture
    why: 모든 입력과 판단 결과가 Shared 5.2·5.3 저장 요구대로 한 DB에 남고, DB가 느리거나 끊겨도 Interlock이 막히지 않아야 한다. integration은 이 DDL을 initdb로 적용한다 (C-03, spec 05, A-08, D-14·D-25·D-26)
    depends_on: [OPS-3B]
    scope: [db/**, src/factory_operations/store/**, tests/docker/**, Makefile, agent/config.yaml, docs/spec/05-storage.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: Docker 연동 테스트 전체가 통과한다
        check: {type: command, run: "make docker-test"}
      - id: A3
        text: db/schema.sql을 timescale/timescaledb:2.30.1-pg17 initdb로 적용하면 테이블 8개(schema_info 포함)·view defect_result·hypertable sensor_chunk·schema_info 버전 1이 생기고, psql -v ON_ERROR_STOP=1로 한 번 더 실행해도 종료 코드 0이다 (C-03)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_schema.py::test_schema_objects tests/docker/test_schema.py::test_schema_reapply"}
      - id: A4
        text: 05 2절 작업 9종이 표대로 행을 만들고 중복을 무시하며, 센서 25개가 2번 이상의 배치로 모두 기록되고, control_result는 result가 비어 있을 때만 갱신한다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_db_writer.py::test_each_job_writes_row tests/docker/test_db_writer.py::test_duplicates_ignored tests/docker/test_db_writer.py::test_sensor_batches tests/docker/test_db_writer.py::test_control_result_update_once"}
      - id: A5
        text: DB 컨테이너 docker restart 뒤 db_ok가 false가 되었다가 15초 안에 true로 돌아오고 이후 쓰기가 된다 (05 3절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_db_writer.py::test_db_restart_recovers"}
      - id: A6
        text: schema_info가 없으면 db_ok false(db_schema_missing)이고, 요약 콜백이 05 5절 값을 주며, 상관분석 주기에 주입한 계산 함수가 두 조회 결과(window_s 조건 포함)를 받는다 (05 3·5절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/docker/test_db_writer.py::test_schema_missing_not_ok tests/docker/test_db_writer.py::test_summary_callback tests/docker/test_db_writer.py::test_correlation_hook_receives_rows"}
      - id: A7
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
      - id: A8
        text: tests/docker의 모든 테스트가 docker 마커를 가져 make test(-m "not docker")에 들어가지 않는다
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q -m 'not docker' tests/docker; test $? -eq 5"}
      - id: A9
        text: agent/config.yaml verify에 spec 08 5절의 docker 명령이 그대로 있다
        check: {type: command, run: "python3 -c \"import sys, yaml; v = yaml.safe_load(open('agent/config.yaml'))['verify']; sys.exit(0 if {'name': 'docker', 'run': 'make docker-test'} in v else 1)\""}
    size: M
```

단계 개요:
1. `db/schema.sql`: spec 05 4절 DDL 그대로. → A7
2. `Makefile`에 `docker-test`, `tests/docker/conftest.py`에 `timescale_db`(빈 포트 고정, initdb 마운트, `schema_info` 1까지 60초)·`clean_db`. id로만 지운다. → A8
3. `test_schema.py`. → A3
4. `store/sql.py`(작업 9종의 SQL, 요약 네 조회, 상관분석 두 조회와 window 조건), `store/db.py` 연결·스키마 확인·재연결 2초·작업 실행·센서 배치(20행 또는 1초, 한 트랜잭션)·주기 작업·콜백. 연결이 없을 때 꺼낸 작업은 버리고 센다. → A4, A6
5. 재시작 테스트(자기 DB 컨테이너, 빈 포트 고정). → A5
6. `make docker-test` 확인 → `agent/config.yaml`에 `docker` 추가 → `validate.py --remote`. → A1, A2, A9

읽을 spec: 05 전부, `AGREEMENTS.md` A-08, 01 2절(DB 큐), 08 2·3.6절, D-11·D-14·D-25·D-26·D-27·D-28·D-29.

- 첫 실행에서 TimescaleDB 컨테이너 기동과 initdb에 10~20초 걸린다. 이미지가 없으면 인터넷으로 받는다(H-1).
