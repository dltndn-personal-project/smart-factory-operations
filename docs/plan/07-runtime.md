# 07 실행 환경 계획 (M4)

> 목적: OPS-9A(이미지와 smoke)와 OPS-9B(개발용 compose, 가짜 입력, COMPONENT.md 실행 절)의 PLAN 정의와 단계 개요.
> 읽어야 할 때: 두 task를 실행하거나 등록할 때, HUM-1을 준비할 때. 같이 읽을 spec: `docs/spec/07-runtime.md`, `docs/spec/08-verification.md` 3.7·6절, `docs/spec/AGREEMENTS.md` A-09.

## 1. 나눈 이유

spec 00 6절의 OPS-9는 Dockerfile·smoke·개발용 compose·`fake_feed.py`(Simulator·PdM·Vision 흉내)·COMPONENT.md를 한 번에 해서 한 세션에 넘친다. integration이 쓰는 것(이미지, smoke = C-09)과 사람 확인이 쓰는 것(compose, fake_feed)으로 나눴다(D-37). 예시 이미지 fixture는 OPS-6이 이미 만들었다.

## 2. task

### OPS-9A 컨테이너 이미지와 smoke

```yaml
  - id: OPS-9A
    milestone: M4
    type: feature
    title: Dockerfile, .dockerignore, scripts/smoke.py, verify smoke
    why: integration이 이 저장소 Dockerfile로 이미지를 만들어 시스템 compose에 넣는다. 컨테이너 안의 앱이 MQTT·DB·Image Storage(:ro)와 연결해 동작하는지 매 변경마다 자동 확인한다 (C-09, spec 07 3절, 08 3.7절, A-09)
    depends_on: [OPS-7A]
    scope: [Dockerfile, .dockerignore, scripts/smoke.py, Makefile, agent/config.yaml, docs/spec/07-runtime.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: make smoke가 통과한다 — 빌드, 컨테이너가 뜬 뒤 30초 안 /readyz 200, /healthz commit이 빌드 인자와 같음, CRITICAL → 2초 안 Alarm Event·STOP, 결과 기록, 검사 스냅숏 반영, 이미지 응답, DB 행 확인 (C-09, 08 3.7절)
        check: {type: command, run: "make smoke"}
      - id: A2
        text: Dockerfile이 spec 07 3절의 베이스 이미지·빌드 인자·포트·HEALTHCHECK·CMD를 가진다
        check: {type: command, run: "grep -qxF 'FROM python:3.12-slim' Dockerfile && grep -qxF 'ARG GIT_COMMIT=unknown' Dockerfile && grep -qxF 'EXPOSE 8080' Dockerfile && grep -q '^HEALTHCHECK ' Dockerfile && grep -qxF 'CMD [\"python\", \"-m\", \"factory_operations\", \"serve\"]' Dockerfile"}
      - id: A3
        text: .dockerignore에 spec 07 3절 항목이 모두 있다
        check: {type: command, run: "for p in .git .venv data tests docs agent scripts '**/__pycache__'; do grep -qxF -- \"$p\" .dockerignore || { echo \"missing $p\"; exit 1; }; done"}
      - id: A4
        text: smoke가 만든 이미지에 tests·docs가 없고 정적 파일과 기본 설정이 있다
        check: {type: command, run: "docker run --rm factory-operations:smoke-$(git rev-parse --short=12 HEAD) python -c \"import os, sys; bad = [p for p in ('/app/tests', '/app/docs', '/app/agent') if os.path.exists(p)]; miss = [p for p in ('/app/src/factory_operations/web/static/index.html', '/app/config/default.yaml') if not os.path.exists(p)]; print(bad, miss); sys.exit(1 if bad or miss else 0)\""}
      - id: A5
        text: smoke가 끝난 뒤 fops-smoke- 이름의 컨테이너·network·volume이 남지 않는다 (08 3.7절 7번)
        check: {type: command, run: "test -z \"$(docker ps -aq --filter name=fops-smoke-)\" && test -z \"$(docker network ls -q --filter name=fops-smoke-)\" && test -z \"$(docker volume ls -q --filter name=fops-smoke-)\""}
      - id: A6
        text: agent/config.yaml verify에 spec 08 5절의 smoke 명령이 그대로 있다
        check: {type: command, run: "python3 -c \"import sys, yaml; v = yaml.safe_load(open('agent/config.yaml'))['verify']; sys.exit(0 if {'name': 'smoke', 'run': 'make smoke'} in v else 1)\""}
    size: M
```

단계 개요:
1. `Dockerfile`(07 3절 그대로), `.dockerignore`. smoke 이미지 태그는 `factory-operations:smoke-<commit 12자리>`다(spec 08 3.7절 1번). `docker build`가 되는지 먼저 본다(첫 빌드는 베이스 이미지·pip로 수 분, 인터넷 필요). → A2, A3
2. `scripts/smoke.py`: 08 3.7절 1~7번. 컨테이너·network·volume은 `<hex8>` 접미사로 만들고 id·이름으로만 지운다. Mosquitto·DB·Operations 모두 `-p 127.0.0.1::<port>`(재시작 없음, 임의 포트). harness는 `.venv`의 paho, PdM 메시지는 `tests/fixtures/payloads/pdm.py`(파일 경로로 불러옴, D-39). 실패하면 Operations 로그 마지막 100줄과 종료 코드 1. → A1, A5
3. `Makefile`에 `smoke`. `make smoke`를 두 번 연속 실행해 정리가 되는지 본다. → A1, A4
4. `agent/config.yaml`에 `smoke` 추가 → `validate.py --remote`. → A6

읽을 spec: 07 3절, 08 3.7절, `AGREEMENTS.md` A-08(DB 준비 확인)·A-09, D-33.

### OPS-9B 개발용 compose, 가짜 입력, 실행 문서

```yaml
  - id: OPS-9B
    milestone: M4
    type: feature
    title: 개발용 compose, scripts/fake_feed.py, make feed, COMPONENT.md 실행 절
    why: 다른 Component 없이 화면 전체와 Interlock 흐름을 보려면 저장소 단독 compose와 Simulator·PdM·Vision 흉내 입력이 있어야 한다. 사람 확인(HUM-1)이 이것으로 한다 (spec 07 4·5·6절, 08 6절, D-35)
    depends_on: [OPS-9A, OPS-8]
    scope: [compose.yaml, scripts/fake_feed.py, tests/unit/test_fake_feed.py, Makefile, .env.example, docs/COMPONENT.md, docs/spec/07-runtime.md, docs/spec/DECISIONS.md]
    acceptance:
      - id: A1
        text: 단위 테스트 전체가 통과한다
        check: {type: command, run: "make test"}
      - id: A2
        text: fake_feed가 만드는 여섯 Topic 메시지가 payloads 파서로 모두 받아지고 PdM Result·Spectrum의 키 집합이 그 시점 PdM fixture(tests/fixtures/payloads/pdm_*.json 또는 OPS-10 뒤 shared_pdm_*.json)와 같으며, Fault Level 시나리오(0~40초 0, 40~70초 3, 70~160초 6, 그 뒤 9)와 image_path = products/<product_id>.jpg, STOP/START 적용과 last_command(retained 명령은 REJECTED)가 spec 07 5절대로다 (D-44)
        check: {type: command, run: "make venv >/dev/null && .venv/bin/python -m pytest -q tests/unit/test_fake_feed.py::test_messages_parse tests/unit/test_fake_feed.py::test_pdm_keys_match_fixture tests/unit/test_fake_feed.py::test_scenario_levels tests/unit/test_fake_feed.py::test_image_path_matches_product_id tests/unit/test_fake_feed.py::test_control_updates_last_command"}
      - id: A3
        text: 환경 변수 없이 해석한 compose가 mosquitto·db·image-seed·factory-operations 서비스, 127.0.0.1의 8080·1883·5432 포트, Operations의 /data 읽기 전용 마운트를 가진다 (07 4절)
        check:
          type: command
          run: |
            out=$(env -u FOPS_HTTP_PORT -u FOPS_MQTT_PORT -u FOPS_DB_PORT -u COMPOSE_PROJECT_NAME docker compose -f compose.yaml config --format json) || exit 1
            printf '%s' "$out" | python3 -c '
            import json, sys
            s = json.load(sys.stdin)["services"]
            assert {"mosquitto", "db", "image-seed", "factory-operations"} <= set(s), sorted(s)
            pub = lambda n: {(p.get("host_ip"), str(p.get("published")), int(p.get("target"))) for p in s[n].get("ports", [])}
            assert ("127.0.0.1", "8080", 8080) in pub("factory-operations"), pub("factory-operations")
            assert ("127.0.0.1", "1883", 1883) in pub("mosquitto"), pub("mosquitto")
            assert ("127.0.0.1", "5432", 5432) in pub("db"), pub("db")
            assert any(v.get("target") == "/data" and v.get("read_only") for v in s["factory-operations"].get("volumes", [])), s["factory-operations"].get("volumes")
            print("compose defaults ok")
            '
      - id: A4
        text: 개발용 compose(포트를 바꾼 별도 프로젝트)와 fake_feed로 띄운 앱의 스냅숏에 30초 안에 라인 RUNNING·PdM·스펙트럼·진동이 LIVE이고 검사 3건 이상, 그 이미지 응답이 200이며, POST /api/conveyor STOP 뒤 5초 안에 STOPPED와 OPERATOR_STOP·APPLIED가 보인다
        check:
          type: command
          run: |
            make venv >/dev/null || exit 1
            export COMPOSE_PROJECT_NAME=fops-ops9b FOPS_HTTP_PORT=18290 FOPS_MQTT_PORT=11990 FOPS_DB_PORT=15490
            d=$(mktemp -d); rc=1; feed=
            cleanup() { [ -n "$feed" ] && kill -INT "$feed" 2>/dev/null; sleep 1; docker compose down -v >/dev/null 2>&1; }
            docker compose up -d --build >"$d/up.log" 2>&1 || { tail -50 "$d/up.log"; cleanup; exit 1; }
            ready=1
            for i in $(seq 180); do [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 1 http://127.0.0.1:18290/readyz)" = 200 ] && { ready=0; break; }; sleep 0.5; done
            [ "$ready" -eq 0 ] || { echo "readyz timeout"; docker compose logs --tail 50 factory-operations; cleanup; exit 1; }
            .venv/bin/python scripts/fake_feed.py --mqtt mqtt://127.0.0.1:11990 >"$d/feed.log" 2>&1 &
            feed=$!
            .venv/bin/python - <<'EOF' && rc=0
            import json, sys, time, urllib.request
            base = "http://127.0.0.1:18290"
            snap = lambda: json.load(urllib.request.urlopen(base + "/api/snapshot", timeout=2))
            end = time.time() + 30
            while True:
                s = snap()
                st = {k: s[k].get("status") for k in ("line", "pdm", "spectrum", "vibration")}
                if set(st.values()) == {"LIVE"} and s["line"].get("conveyor") == "RUNNING" and len(s["inspections"]) >= 3:
                    break
                if time.time() > end:
                    print("not live:", st, len(s["inspections"])); sys.exit(1)
                time.sleep(0.5)
            r = urllib.request.urlopen(base + "/api/images/" + s["inspections"][0]["image_path"], timeout=2)
            assert r.status == 200 and r.headers["Content-Type"].startswith("image/jpeg"), r.headers["Content-Type"]
            req = urllib.request.Request(base + "/api/conveyor", data=b'{"command":"STOP"}', headers={"Content-Type": "application/json"}, method="POST")
            assert urllib.request.urlopen(req, timeout=5).status == 202
            end = time.time() + 5
            while time.time() < end:
                s = snap()
                if s["line"].get("conveyor") == "STOPPED" and any(c["reason"] == "OPERATOR_STOP" and c["result"] == "APPLIED" for c in s["controls"]):
                    print("dev compose + fake_feed ok"); sys.exit(0)
                time.sleep(0.5)
            print("STOP not reflected"); sys.exit(1)
            EOF
            [ "$rc" -eq 0 ] || { tail -30 "$d/feed.log"; docker compose logs --tail 50 factory-operations; }
            cleanup
            exit "$rc"
      - id: A5
        text: docs/COMPONENT.md 실행 절이 실제 실행 방법(compose 시연, make feed, 로컬 실행)이고 계획 표시가 없다
        check: {type: command, run: "! grep -q '(계획)' docs/COMPONENT.md && grep -q 'docker compose up -d --build' docs/COMPONENT.md && grep -q 'make feed' docs/COMPONENT.md && grep -q 'docker compose down -v' docs/COMPONENT.md"}
      - id: A6
        text: make feed가 fake_feed.py를 실행한다 (07 6절)
        check: {type: command, run: "make -n feed | grep -q 'scripts/fake_feed.py'"}
    size: M
```

단계 개요:
1. `compose.yaml`(07 4절 네 서비스, 포트 환경 변수, `image-seed` 300장, 익명 DB 볼륨, `image-storage` 볼륨). → A3
2. `scripts/fake_feed.py`: 07 5절(Simulator·PdM·Vision 흉내, 시나리오, 명령 적용, Ctrl-C 때 offline retain). 메시지를 만드는 함수와 발행 루프를 나눠 테스트가 함수를 import할 수 있게 한다. PdM 흉내의 형식은 그 시점 spec 02 3.6·3.7절과 PdM fixture를 따른다. OPS-10이 아직이면 A-05·A-06 가정, 먼저 끝났으면 채택된 `contract_ref` 확정본이다(D-39). → A2
3. `tests/unit/test_fake_feed.py`(`importlib`로 스크립트를 불러 메시지를 OPS-2 파서에 넣는다). → A1, A2
4. `Makefile`의 `feed`, `.env.example`에 compose 포트 변수(`FOPS_HTTP_PORT` 등)를 주석으로. → A6
5. 개발 환경 확인(A4 명령). 실패하면 compose·fake_feed를 고친다. 앱 코드 결함이면 멈추고 FIX task를 요청한다(scope).
6. `docs/COMPONENT.md` 실행·검증 환경 절을 실제 명령으로 바꾼다(`(계획)` 표시와 "OPS-9B가 갱신한다" 문장 삭제). → A5

읽을 spec: 07 4·5·6절, 08 6절(HUM-1 준비), 02 3절(메시지 형식), D-35.

- simulator 단독 compose와 호스트 포트 1883이 겹친다. HUM-1 준비 때 simulator compose가 떠 있으면 내리거나 `FOPS_MQTT_PORT`를 바꾼다(07 4절).
