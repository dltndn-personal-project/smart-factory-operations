# 01 코어 계획 (M1)

> 목적: OPS-1(골격)의 PLAN 정의와 단계 개요. 모든 구현 task가 따르는 공통 규칙.
> 읽어야 할 때: OPS-1을 실행하거나 등록할 때, 어느 task든 테스트 명령·공용 fixture·scope 규칙을 볼 때. 같이 읽을 spec: `docs/spec/01-core.md`.

## 1. 구현 task 공통

- 테스트 명령 형식: `make venv >/dev/null && .venv/bin/python -m pytest -q <파일 또는 node id>`. node id가 없으면 pytest가 실패(종료 코드 4)하므로 acceptance가 가리키는 테스트 파일·이름은 바꾸지 않는다(D-42). 테스트는 더 추가해도 된다.
- 테스트 내용의 원본은 spec 08 3절이다. acceptance 문장은 그 요약이다. 기대값을 바꾸거나 skip으로 통과시키지 않는다. Docker가 없으면 Docker 테스트는 실패해야 한다(spec 08 1절).
- `tests/docker/` 아래 모든 테스트 파일은 `pytestmark = pytest.mark.docker`를 둔다. `make test`는 `-m "not docker"`라 이것이 빠지면 단위 verify가 Docker를 기다린다.
- 공용 fixture(`tests/conftest.py`)는 OPS-1이 spec 08 2절 목록 전부(`FakeClock`, `FakePublisher`, `FakeDbSink`, `tmp_image_root`, `payload_examples`)를 만든다. 뒤 task는 이 파일을 고치지 않고, 필요한 fixture를 자기 테스트 파일이나 `tests/docker/conftest.py`(OPS-4A가 만들고 OPS-7A가 늘린다)에 둔다. scope를 좁혀 병렬을 가능하게 하기 위해서다(D-41).
  - `FakeDbSink`는 작업 타입을 모른다: `put_nowait(job)`을 받아 `jobs` 목록에 쌓는다. `FakePublisher`는 `publish(topic, payload, qos, retain) -> bool`을 `calls`에 기록하고 `connected`로 결과를 바꾼다.
  - `tmp_image_root`는 `tests/fixtures/images/P-00000001.jpg`를 복사한다. 그 파일은 OPS-6이 만든다. OPS-6 전 task는 이 fixture를 쓰지 않는다.
- 설정 키는 OPS-1이 모두 만든다(D-38). 뒤 task가 키를 추가하거나 기본값을 바꾸면 spec 원본 표(01 4절이 가리키는 곳)와 `config/default.yaml`을 같은 PR에서 고친다. 그 경우 `config/**`와 `src/factory_operations/config.py`가 scope에 없으면 멈춘다.
- 모듈 경계(spec 01 1절): paho는 `mqtt/client.py`만, psycopg는 `store/db.py`만, FastAPI는 `web/api.py`만 import한다. `domain/`, `mqtt/payloads.py`, `web/snapshot.py`, `store/jobs.py`는 순수 로직이다. OPS-7A가 전체를 검사한다.
- PdM Result·PdM Spectrum의 **형식**(필드 이름, 필수 여부, 스펙트럼 배열 구성)에 기대는 코드는 `mqtt/payloads.py`의 두 파서, `tests/fixtures/payloads/`(PdM fixture와 테스트·smoke용 생성 함수 `pdm.py`), `scripts/fake_feed.py`의 PdM 흉내에만 둔다. Docker 테스트와 smoke는 PdM 메시지를 `pdm.py`로만 만든다. `domain/`과 `web/`은 파싱된 객체(`PdmResult`, `SpectrumPanels`)만 쓴다. Shared 확정본과 다르면 OPS-10이 이 자리만 고친다(D-39).
- 모든 task의 verify 비용은 `08-verification.md` 1절 표.

## 2. task

### OPS-1 패키지 골격, 설정, 시계, 로그, `/healthz`

```yaml
  - id: OPS-1
    milestone: M1
    type: feature
    title: 패키지 골격, 설정, 시계, 로그, /healthz, Makefile
    why: 모든 task가 쓰는 패키지 구조·설정 로딩·시계 주입·JSON 로그·공용 fixture·검증 진입점을 먼저 만든다 (spec 01, 07 1·2·6·7절, 08 2·3.1·5절)
    depends_on: [BOOT-1]
    scope: [src/**, config/**, tests/**, pyproject.toml, requirements.txt, requirements-dev.txt, Makefile, .gitignore, .env.example, agent/config.yaml, docs/spec/01-core.md, docs/spec/07-runtime.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: 설정이 기본값 로드, overlay 깊은 병합, 환경 변수 우선, 모르는 키와 범위 밖 값(interlock.pending_timeout_s 0, correlation.default_lag_s 40)의 키 경로 오류·종료 코드 2를 만족한다 (01 4절, 08 3.1절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_config.py tests/unit/test_config.py::test_overlay_deep_merge tests/unit/test_config.py::test_env_overrides_file tests/unit/test_config.py::test_unknown_key_exits_2 tests/unit/test_config.py::test_out_of_range_exits_2"}
      - id: A3
        text: iso_ms가 밀리초 3자리·버림(…59.9999가 다음 초로 올라가지 않음)·Z로 CONVENTIONS 정규식에 맞고, parse_ts가 정규식 밖 입력(…13Z, …13.4Z, +00:00)을 거부한다 (01 5절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_clock.py tests/unit/test_clock.py::test_iso_ms_truncates tests/unit/test_clock.py::test_parse_ts_rejects_non_ms"}
      - id: A4
        text: 같은 (event, topic, reason) 11번이 10초 안에 오면 한 줄이고, 10초 뒤 다음 줄에 suppressed 10이 붙는다 (01 6절)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_log.py tests/unit/test_log.py::test_suppression_window"}
      - id: A5
        text: 저장소 루트에서 serve가 Broker·DB 없이 기동해 /healthz에 200, status ok, commit(GIT_COMMIT 값)으로 답한다 (01 7절, 06 2절)
        check:
          type: command
          run: |
            make venv >/dev/null || exit 1
            d=$(mktemp -d)
            HTTP_PORT=18280 GIT_COMMIT=ops1check MQTT_URL=mqtt://127.0.0.1:1 DATABASE_URL=postgresql://x:x@127.0.0.1:1/x .venv/bin/python -m factory_operations serve >"$d/serve.log" 2>&1 &
            pid=$!
            ok=1
            for i in $(seq 60); do
              if curl -fsS --max-time 1 http://127.0.0.1:18280/healthz >"$d/h.json" 2>/dev/null && grep -Eq '"status" *: *"ok"' "$d/h.json" && grep -Eq '"commit" *: *"ops1check"' "$d/h.json"; then ok=0; break; fi
              sleep 0.25
            done
            kill "$pid"; wait "$pid"
            [ "$ok" -eq 0 ] || cat "$d/serve.log"
            exit "$ok"
      - id: A6
        text: 모르는 설정 키(FOPS_CONFIG overlay의 http.bogus_key)가 있으면 serve가 기동하지 않고 종료 코드 2로 끝나며 오류에 키 경로가 나온다 (01 4절)
        check:
          type: command
          run: |
            make venv >/dev/null || exit 1
            f=$(mktemp)
            printf 'http:\n  bogus_key: 1\n' > "$f"
            FOPS_CONFIG="$f" .venv/bin/python -c "import subprocess, sys; r = subprocess.run([sys.executable, '-m', 'factory_operations', 'serve'], capture_output=True, text=True, timeout=20); out = r.stdout + r.stderr; print(r.returncode, out[-500:]); sys.exit(0 if r.returncode == 2 and 'http.bogus_key' in out else 1)"
      - id: A7
        text: config/default.yaml의 키 집합이 spec 설정 표(02 1절, 03 5절, 04 3절, 05 6절, 06 6절, 07 1절)의 키 집합과 같고 모든 기본값이 표와 같다 (01 4절, D-38)
        check:
          type: command
          run: |
            python3 - <<'EOF'
            import re, sys, yaml
            sections = {"http", "mqtt", "db", "paths", "logging", "line", "interlock", "join", "correlation", "pdm", "dashboard"}
            want = {}
            for f in ("02-mqtt", "03-control", "04-analysis", "05-storage", "06-dashboard", "07-runtime"):
                for line in open("docs/spec/%s.md" % f):
                    m = re.match(r"^\| `([a-z_]+)\.([a-z_]+)` \| ([^|]*) \|", line)
                    if m and m.group(1) in sections:
                        cell = m.group(3).strip()
                        v = re.match(r"`([^`]*)`", cell)
                        want[(m.group(1), m.group(2))] = v.group(1) if v else cell.split(" ")[0]
            c = yaml.safe_load(open("config/default.yaml"))
            have = {(s, k): v for s, d in c.items() for k, v in (d or {}).items()}
            def same(raw, v):
                if raw == "null":
                    return v is None
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return float(raw) == float(v)
                return str(v) == raw
            bad = sorted(set(want) ^ set(have)) + sorted(k for k in want if k in have and not same(want[k], have[k]))
            print(len(want), "keys in spec tables; mismatch:", bad)
            sys.exit(1 if bad or len(want) < 36 else 0)
            EOF
      - id: A8
        text: requirements.txt와 requirements-dev.txt가 spec 07 7절 버전 그대로 == 로 고정되어 있다 (D-06)
        check: {type: command, run: "for p in 'fastapi==0.141.1' 'uvicorn==0.54.0' 'paho-mqtt==2.1.0' 'psycopg[binary]==3.3.6' 'numpy==2.5.3' 'scipy==1.18.1' 'pydantic==2.13.5' 'pyyaml==6.0.3'; do grep -qxF -- \"$p\" requirements.txt || { echo \"missing $p\"; exit 1; }; done; for p in '-r requirements.txt' 'pytest==9.1.1' 'httpx==0.28.1'; do grep -qxF -- \"$p\" requirements-dev.txt || { echo \"missing $p\"; exit 1; }; done"}
      - id: A9
        text: venv·캐시·로컬 이미지·.env가 git에서 무시된다 (verify가 untracked 파일을 거부하므로)
        check: {type: command, run: "git check-ignore -q .venv/x && git check-ignore -q src/factory_operations/__pycache__/x.pyc && git check-ignore -q .pytest_cache/x && git check-ignore -q data/products/x.jpg && git check-ignore -q .env"}
      - id: A10
        text: agent/config.yaml verify에 spec 08 5절의 unit 명령이 그대로 있다
        check: {type: command, run: "python3 -c \"import sys, yaml; v = yaml.safe_load(open('agent/config.yaml'))['verify']; sys.exit(0 if {'name': 'unit', 'run': 'make test'} in v else 1)\""}
    size: M
```

단계 개요:
1. `.gitignore`(`.venv/`, `__pycache__/`, `.pytest_cache/`, `data/`, `.env`)를 먼저 만든다. venv·캐시가 untracked로 잡히면 `agent.py verify`가 거부한다. → A9
2. `pyproject.toml`(pytest 설정, spec 08 2절), `requirements*.txt`(07 7절), `Makefile`의 `venv`(`.pth` 포함, 07 2절)·`test`·`run`, `.env.example`(07 1절 변수). `docker-test`는 OPS-4A, `smoke`는 OPS-9A, `feed`는 OPS-9B가 넣는다. → A8
3. `config.py`와 `config/default.yaml`: spec 01 4절 표가 가리키는 **모든** 절(`http`, `mqtt`, `db`, `paths`, `logging`, `line`, `interlock`, `join`, `correlation`, `pdm`, `dashboard`)의 키와 범위. pydantic `extra="forbid"`, overlay 깊은 병합, 환경 변수, 종료 코드 2. `correlation.default_lag_s`가 `lag_min_s`~`lag_max_s` 안인지도 검사. → A2, A6, A7
4. `clock.py`(`Clock`, `SystemClock`, `FakeClock`는 테스트 쪽, `iso_ms`, `parse_ts`), `log.py`(JSON 한 줄, 같은 사유 10초 억제). → A3, A4
5. `web/api.py`(`create_app`, `/healthz`만. `mqtt_connected`·`db_ok`는 StateStore가 생기기 전이라 false), `app.py`(lifespan 틀), `__main__.py serve`(uvicorn, `log_config=None`). → A5
6. `tests/conftest.py`(1절 공용 fixture)와 `tests/unit/test_config.py`·`test_clock.py`·`test_log.py`. → A1
7. `make test` 확인 → `agent/config.yaml`에 `unit` 추가 → `validate.py --remote`. → A10

읽을 spec: 01 전부, 07 1·2·6·7절, 08 1·2·3.1·5절, D-05·D-06·D-07·D-10.
