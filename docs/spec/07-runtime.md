# 07 실행 환경

> 목적: 실행 관련 설정 키와 환경 변수, 로컬 실행, Dockerfile, 개발용 compose, 가짜 입력 스크립트를 정한다. integration에 약속하는 실행 조건의 원본은 `AGREEMENTS.md` A-09다.
> 읽어야 할 때: 설정·환경 변수 추가(OPS-1), 컨테이너·smoke(OPS-9A), compose·가짜 입력(OPS-9B), 화면을 사람이 볼 때.

## 1. 실행 관련 키와 환경 변수

| 설정 키 | 기본값 (`config/default.yaml`) | 환경 변수 |
|---|---|---|
| `http.host` | `0.0.0.0` | `HTTP_HOST` |
| `http.port` | 8080 | `HTTP_PORT` |
| `mqtt.url` | `mqtt://localhost:1883` | `MQTT_URL` |
| `mqtt.topic_prefix` | `factory` | `TOPIC_PREFIX` |
| `db.url` | `postgresql://factory:factory@localhost:5432/factory` | `DATABASE_URL` |
| `paths.image_root` | `./data` (저장소 루트 기준) | `IMAGE_ROOT` |
| `logging.level` | `INFO` | `LOG_LEVEL` |

| 그 밖의 환경 변수 | 용도 |
|---|---|
| `FOPS_DEFAULT_CONFIG` | 기본 설정 파일 경로(없으면 저장소 `config/default.yaml`) |
| `FOPS_CONFIG` | overlay YAML 경로(선택, 01 4절) |
| `GIT_COMMIT` | `/healthz`와 시작 로그에 싣는 commit(없으면 `unknown`) |

- 환경 변수가 설정 파일보다 우선한다. 상대 경로는 저장소 루트 기준이다. 컨테이너는 절대 경로를 준다.
- `db.url`은 `postgresql://user:password@host:port/dbname` 형식(libpq URL). 기본값의 사용자·비밀번호는 개발용 예시다(toy, Shared 13절). 실제 값이 든 `.env`는 commit하지 않고 `.env.example`에 위 변수를 기본값과 함께 주석으로 적는다.

## 2. 로컬 실행 (Docker 없이, 개발용)

```sh
make venv                                   # .venv 생성과 의존 설치 (요구사항이 바뀌면 다시)
docker compose up -d mosquitto db           # broker(127.0.0.1:1883)와 DB(127.0.0.1:5432, schema 적용)
.venv/bin/python -m factory_operations serve        # http://localhost:8080
.venv/bin/python scripts/fake_feed.py               # 가짜 입력(5절)
```

- `make venv`는 site-packages에 저장소 `src/` 절대 경로를 담은 `.pth`(`factory_operations_src.pth`)를 둔다. 그래서 `.venv/bin/python -m factory_operations`가 설치 없이 동작한다. 저장소를 옮기면 `rm -rf .venv && make venv`.
- 호스트 실행에서 이미지는 `IMAGE_ROOT`(기본 `./data`, `.gitignore`)의 파일을 읽는다. 개발용으로 `tests/fixtures/images/`를 복사해 쓴다.

## 3. Dockerfile

저장소 루트 `Dockerfile`:

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY src/ src/
COPY config/ config/
ARG GIT_COMMIT=unknown
ENV GIT_COMMIT=${GIT_COMMIT} PYTHONPATH=/app/src FOPS_DEFAULT_CONFIG=/app/config/default.yaml \
    IMAGE_ROOT=/data HTTP_PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('HTTP_PORT','8080'), timeout=2)"
CMD ["python", "-m", "factory_operations", "serve"]
```

- `.dockerignore`: `.git`, `.venv`, `data`, `tests`, `docs`, `agent`, `scripts`, `**/__pycache__`.
- root로 실행한다. Image Storage는 읽기 전용 마운트라 쓰기 권한이 필요 없다.
- 실행 명령은 이미지 기본 `CMD`다. integration은 명령을 바꾸지 않는다.
- 빌드는 인터넷이 필요하다(pip, 베이스 이미지). 세 이미지(`python:3.12-slim`, `eclipse-mosquitto:2.1.2-alpine`, `timescale/timescaledb:2.30.1-pg17`)는 arm64 manifest가 있다(2026-09-27 확인).

## 4. 개발용 compose (`compose.yaml`)

이 저장소 단독 실행용이다. 시스템 compose는 integration 소유다. 서비스:

| 서비스 | 정의 |
|---|---|
| `mosquitto` | `eclipse-mosquitto:2.1.2-alpine`, `command: ["mosquitto","-c","/mosquitto-no-auth.conf"]`, `ports: ["127.0.0.1:${FOPS_MQTT_PORT:-1883}:1883"]` |
| `db` | `timescale/timescaledb:2.30.1-pg17`, 환경 `POSTGRES_USER=factory`, `POSTGRES_PASSWORD=factory`, `POSTGRES_DB=factory`, `volumes: ["./db/schema.sql:/docker-entrypoint-initdb.d/100_factory_operations.sql:ro"]`(DB 데이터는 익명 볼륨), `ports: ["127.0.0.1:${FOPS_DB_PORT:-5432}:5432"]`, healthcheck `pg_isready -h 127.0.0.1 -U factory -d factory`(interval 2s, retries 30. `-h 127.0.0.1`은 initdb 중 소켓만 여는 임시 서버를 준비 완료로 오인하지 않게 한다) |
| `image-seed` | `eclipse-mosquitto:2.1.2-alpine` 이미지로 한 번 실행: `sh -c 'mkdir -p /data/products /data/gradcam; i=1; while [ $i -le 300 ]; do k=$(( (i - 1) % 8 + 1 )); cp /seed/P-0000000$k.jpg $(printf /data/products/P-%08d.jpg $i); i=$((i + 1)); done'`(compose 파일에서는 `$`를 `$$`로 쓴다). 예시 이미지 8장을 `P-00000001.jpg`~`P-00000300.jpg` 300개 이름으로 복사한다(fake_feed 2초 간격으로 10분 분량), `volumes: ["image-storage:/data", "./tests/fixtures/images:/seed:ro"]`. 개발용 볼륨에 예시 이미지를 넣는다(Image Storage 자체를 bind mount하지 않는다) |
| `factory-operations` | `build: .`, 환경 `MQTT_URL=mqtt://mosquitto:1883`, `DATABASE_URL=postgresql://factory:factory@db:5432/factory`, `IMAGE_ROOT=/data`, `ports: ["127.0.0.1:${FOPS_HTTP_PORT:-8080}:8080"]`, `volumes: ["image-storage:/data:ro"]`, `depends_on`: `db`(service_healthy), `mosquitto`(service_started), `image-seed`(service_completed_successfully) |

`volumes: {image-storage: {}}`. simulator 단독 compose와 호스트 포트 1883이 겹치므로 둘을 동시에 띄우지 않는다(동시에 필요하면 `FOPS_MQTT_PORT`를 바꾼다). 완전 초기화는 `docker compose down -v`.

## 5. 가짜 입력 (`scripts/fake_feed.py`)

다른 Component 없이 화면과 흐름을 보기 위한 개발·사람 확인용 도구다. 다른 테스트는 이 스크립트에 의존하지 않는다. 스크립트 자신의 메시지가 파서로 받아지는지만 `tests/unit/test_fake_feed.py`가 확인한다(`DECISIONS.md` D-44).

`.venv/bin/python scripts/fake_feed.py [--mqtt mqtt://127.0.0.1:1883] [--prefix factory] [--seed 1] [--speed 1.0] [--start-id 1]`:

- **Simulator 흉내**: Line Status(retain, 1초마다와 변화 즉시), Sensor Vibration(0.1초마다, `motor01`, 3축 1000샘플, 30 Hz 사인 + Fault Level에 비례한 진폭·잡음, `STOPPED`면 `rpm 0.0`과 잡음만), Product Created(가동 중 2초마다, `product_id`는 `--start-id`(기본 1)부터 1씩 증가, `image_path`는 Shared 관례대로 `products/<product_id>.jpg`). 300번을 넘으면 파일이 없어 화면에 "이미지 없음"이 나온다(개발용 한계). 다시 처음부터 보려면 `docker compose down -v` 뒤 다시 띄운다. Conveyor Control을 구독해 `START`/`STOP`을 적용하고 `last_command`(`source: mqtt`, `APPLIED`/`NO_CHANGE`/`REJECTED`)를 Line Status로 돌려준다. retained 명령은 `REJECTED`(`retained_ignored`).
- **PdM 흉내**: 가동 중 0.5초마다 PdM Result(`timestamp` = 마지막 chunk 끝, `window_start` = 1초 전, `health_index = round(100·(1−(f/10)^1.3))` ± 2 잡음, `state`는 Shared 4.2 구간, `anomaly_score = 1 − HI/100`), 1초마다 PdM Spectrum(Shared `cb6dc3c` 확정 형식: `rpm`, `freq_step_hz: 1.0`, `rot_hz`·`bpfo_hz`·`bpfi_hz`, `spectrum_x/y/z`와 `envelope_x/y/z` 각 501값(0 이상), 원 스펙트럼은 30·60·90 Hz와 107.5 Hz, 포락선은 107.5 Hz와 고조파에 Fault Level 비례 봉우리). 두 메시지의 키 집합은 `tests/fixtures/payloads/shared_pdm_result.json`·`shared_pdm_spectrum.json`과 같다. 정지 중에는 둘 다 내지 않는다.
- **Vision 흉내**: Product Created마다 0.2초 뒤 Vision Result(pass-through 형식, `judgement_source: "PASS_THROUGH"`). 불량 확률은 투입 시점(13초 전) Fault Level `f`에 대해 `0.02 + 0.4·(f/10)^1.3`, 유형은 세 가지 균등.
- **Fault Level 시나리오**(초, `--speed`로 배속): 0~40 → 0, 40~70 → 3, 70~160 → 6, 160~ → 9. `START`를 받으면 Fault Level을 0으로 돌리고 시나리오를 처음부터 다시 한다. Ctrl-C로 끝낸다(Line Status offline을 retain 발행).
- 예시 이미지 `tests/fixtures/images/P-0000000{1..8}.jpg`: 640 × 640 JPEG. 네 장은 회색(#808080) 바탕, 네 장은 회색 바탕에 짙은 사선(긁힘 모양). 만드는 방법(스크립트 `tests/fixtures/images/make_images.py`에 적는다): 표준 라이브러리 `zlib`·`struct`로 PNG를 쓰고 macOS `sips -s format jpeg -s formatOptions 90 in.png --out out.jpg`. 결과 파일을 commit한다.

## 6. `Makefile` 실행 대상

`08-verification.md` 2절의 검증 대상에 더해:

| 대상 | 하는 일 |
|---|---|
| `run` | `venv` 후 `.venv/bin/python -m factory_operations serve` |
| `feed` | `venv` 후 `.venv/bin/python scripts/fake_feed.py` |

## 7. 의존 버전

직접 의존은 모두 `==`로 고정한다(`DECISIONS.md` D-06). 간접 의존은 고정하지 않는다. 2026-09-27에 PyPI에서 Python 3.12용 macOS arm64·Linux aarch64 wheel이 있는 것을 확인했다.

| 파일 | 내용 |
|---|---|
| `requirements.txt` | `fastapi==0.141.1`, `uvicorn==0.54.0`, `paho-mqtt==2.1.0`, `psycopg[binary]==3.3.6`, `numpy==2.5.3`, `scipy==1.18.1`, `pydantic==2.13.5`, `pyyaml==6.0.3` |
| `requirements-dev.txt` | `-r requirements.txt`, `pytest==9.1.1`, `httpx==0.28.1` |
