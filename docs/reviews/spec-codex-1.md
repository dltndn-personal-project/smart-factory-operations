# spec 리뷰 기록 1 (Codex)

- 날짜: 2026-09-27
- 리뷰어: Codex CLI `codex-cli 0.155.0-alpha.16.4`, 모델 `gpt-6-sol`, `codex exec -m gpt-6-sol -c model_reasoning_effort="high" -s read-only --skip-git-repo-check -C <저장소> -o <scratch>/factory-operations/spec/spec-review.md "<요청>"`. 요청문에 파일 수정 금지를 적었고, 실행 전후 `git status`가 깨끗한 것을 확인했다.
- 대상: `docs/spec/**`, `docs/WIREFRAME.html`, `docs/ARCHITECTURE.md`, `docs/COMPONENT.md` (branch `docs/spec`, commit `584e5ed`)
- 비교 기준(scratch 사본): Shared `main@d0c997c97129141d9853a42ce6e0d1f8f7309ae9`의 `docs/INTERFACES.md`·`CONVENTIONS.md`·`ARCHITECTURE.md`(원격 Contents API), 조율 결정 C-00~C-15, factory-simulator `docs/spec/AGREEMENTS.md`·`05-mqtt.md`, predictive-maintenance `main` `docs/ARCHITECTURE.md`, integration `main` `docs/ARCHITECTURE.md`
- 요청 요지: 파일 사이 모순, 구현자가 스스로 설계 결정을 내려야 하는 빈 곳, 틀린 식·수치, 이 맥(Python 3.12.13, Docker 28.3, Make 3.81, 호스트 mosquitto·psql 없음)에서 실행할 수 없는 검증 명령, 더 나은 대안이 분명한 약한 결정, README 라우팅 누락, 같은 사실의 중복, 다른 Component가 받아들이기 어려운 약속(Alarm Event Payload가 Shared DOCUMENT_CHANGE에 충분한지 포함), `HUMAN.md`가 최소인지, toy 범위에 비해 과한 설계. D-01~D-03은 논쟁 대상에서 뺐다. 지적마다 심각도와 근거 위치를 요청했다.
- 판정 방법: 지적마다 해당 절과 비교 기준 원문을 읽고 확인했다(조율 C-03 기준). 이미지 준비 셸 반복문은 `eclipse-mosquitto:2.1.2-alpine`에서 실제로 돌려 300개 파일이 생기는 것을 확인했다. DDL은 리뷰 전에 `timescale/timescaledb:2.30.1-pg17` initdb로 적용·재실행을 확인했다.
- Codex의 추가 판정: 호스트 `mosquitto`·`psql`을 요구하는 명령 없음, `HUMAN.md`는 최소, Alarm Event의 필드·QoS·시각 의미는 제안에 충분(발행 조건만 5번과 함께 정리 필요).
- 결과: 지적 13개. 반영 11, 부분 반영 2, 미반영 0.

| 번호 | 요지 | 판정 | 이유 / 반영 위치 |
|---|---|---|---|
| 1 | `fault_changes`를 600초만 남겨 Fault Level이 10분 넘게 그대로면 `sensor_chunk.fault_level`이 null이 됨 (high) | 반영 | 맞다. 600초 밖의 가장 최근 변화점 하나를 보존하게 했고 700초 불변 테스트를 넣었다. `03-control.md` 1.1절, `08-verification.md` 3.3절 |
| 2 | Dashboard 측정식이 화면 지연의 상한이 아님: 브라우저의 요청 건너뜀·3초 중단, 렌더링 시간이 빠짐 (high) | 부분 반영 | 측정식을 `D = t_seen − t_rx + P + r_max + R`로 고쳤다. 스냅숏 응답 시간 최댓값 `r_max`를 더하고 `r_max ≤ 0.5`초를 판정 조건에 넣어 요청 건너뜀이 일어나지 않음을 보장한다. 렌더링은 예산 `R = 0.2`초로 더하고 `?debug=1` 표시로 사람이 M-02에서 확인한다. 실제 브라우저 자동 측정은 받지 않았다. headless 브라우저를 두지 않기로 했고(D-34) toy 범위에서 과하다. 시작점 지연(로컬 수 ms)도 적었다. `08-verification.md` 4.1절·M-02, `06-dashboard.md` 5절, D-34, A-10 |
| 3 | 서로 다른 Topic의 수신 순서(Alarm Event → STOP)를 acceptance로 요구함 (high) | 반영 | 맞다. Shared INTERFACES가 Topic 사이 순서를 보장하지 않는다. 발행 순서는 단위 테스트 L-07(발행 호출 순서)로, 연동 테스트는 두 이벤트 수신과 STOP 지연만 본다. A-02·A-11에서 수신 순서 약속을 뺐다. `00-overview.md` C-05, `08-verification.md` 4.2절, `AGREEMENTS.md` A-02·A-11 |
| 4 | 첫 Line Status가 PdM Result보다 늦게 오거나 `offline → RUNNING`일 때 Alarm이 중복됨 (medium) | 반영 | 시나리오로 확인했다. 재가동 기준 시각(Interlock)은 그대로 두고, Alarm 초기화는 마지막으로 본 `conveyor`가 `STOPPED`였다가 `RUNNING`이 될 때만 한다(사이의 offline 허용). L-08~L-10 추가. `03-control.md` 1.1·1.2·6절, D-21, A-02 발행 조건 |
| 5 | 다른 센서 Alarm 조건이 처리 순서 표와 4절에서 충돌 (medium) | 반영 | "판정 대상"(Interlock)과 "Alarm 대상"(라인 센서는 같은 조건, 다른 센서는 모든 결과)을 나눠 정의했다. L-11 추가. `03-control.md` 2·4·6절 |
| 6 | Docker fixture의 준비·처리 대기 조건이 없음 (medium) | 반영 | `running_app`이 `/readyz` 200을 기다리고, harness는 SUBACK·PUBACK을 기다리며, `wait_snapshot`으로 선행 메시지 처리(기준 시각, Fault Level, 대기 STOP 종료)를 확인한 뒤 다음 메시지를 보낸다. `08-verification.md` 2절, 3.6절, 4.2절 |
| 7 | Shared Sensor Vibration 예시는 배열에 설명 문자열이 있어 그대로 받을 수 없음 (medium) | 반영 | 맞다. 원문의 스칼라 필드 + seed 고정 1000개 배열로 만든 fixture를 쓰고 나머지 예시는 원문 그대로 쓴다. `08-verification.md` 2절 |
| 8 | fake_feed가 이미지 8개 이름을 순환해 `image_path`가 `product_id`와 어긋남 (medium) | 반영 | Shared 관례(`products/<product_id>.jpg`)에 맞췄다. `image-seed`가 예시 8장을 `P-00000001`~`P-00000300` 이름으로 복사하고 fake_feed는 같은 id의 경로를 발행한다. 300번 이후는 "이미지 없음"(개발용 한계로 명시), `--start-id` 추가. `07-runtime.md` 4·5절 |
| 9 | `build_conveyor`에 `reason` 인자가 없음 (medium) | 반영 | 인자로 넣고 호출 경로별 값을 적었다. `02-mqtt.md` 4.1절, `03-control.md` 3.2절 |
| 10 | 센서 파서는 임의 rate·길이를 받는데 화면은 10 chunk = 1초로 가정 (medium) | 반영 | 파서는 DB 저장을 위해 그대로 두고, 진동 링 버퍼가 `sample_rate_hz`·배열 길이·`seq` 연속이 바뀌면 비우고 다시 채우게 했다. 링 안의 chunk가 모두 같은 형식이라 `window_s` 계산이 맞다. `03-control.md` 2절, `06-dashboard.md` 3절 |
| 11 | DB 장애 때 상관분석 오래된 값 표시가 없음 (medium) | 반영 | `db_ok` false이거나 `computed_at`이 30초 넘게 지났으면 `stale: true`, 화면 "마지막 계산 · N초 전", 재연결 뒤 다음 주기에 재계산. `06-dashboard.md` 3절 |
| 12 | C-02가 S-01~S-10·L-01~L-06만 요구해 시나리오 목록보다 좁음 (medium) | 반영 | C-02와 README·검증 목록을 S-01~S-12·L-01~L-11로 맞췄다. `00-overview.md` C-02, `README.md` 3절, `08-verification.md` 3.3절 |
| 13 | 루트 README에 spec 안내가 없고 ARCHITECTURE에 옛 Alarm Payload가 남음 (low) | 부분 반영 | ARCHITECTURE 6.2 Alarm Event에 "A-02로 대체, 초안 기록" 표시를 넣었다(배경 문서라 전문은 남긴다. spec README 5절 차이 표에도 있다). 루트 README는 고치지 않았다. 공통 템플릿 안내이고, agent 진입점은 `AGENTS.md` → `docs/COMPONENT.md`이며 COMPONENT.md는 plan 단계 BOOT-1이 spec을 가리키도록 채운다(조율 C-09). `docs/ARCHITECTURE.md` 6.2절 |
