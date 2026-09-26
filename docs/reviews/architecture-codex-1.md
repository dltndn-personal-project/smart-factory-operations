# 아키텍처 리뷰 기록 1 (Codex)

- 날짜: 2026-09-27
- 리뷰어: Codex CLI `codex-cli 0.155.0-alpha.16.4`, 모델 `gpt-6-sol`, `codex exec -m gpt-6-sol -c model_reasoning_effort="high" -s read-only --skip-git-repo-check -C <저장소> -o <scratch>/arch-review.md "<요청>"`. 요청문에 파일 수정 금지를 적었고, 실행 뒤 `git status`가 깨끗한 것을 확인했다.
- 대상: `docs/ARCHITECTURE.md`(초안 원문), `docs/COMPONENT.md` (branch `docs/architecture-review`, commit `a4e3ffc`)
- 비교 기준: Shared `main@d0c997c97129141d9853a42ce6e0d1f8f7309ae9`의 `docs/INTERFACES.md`, `docs/CONVENTIONS.md`, `docs/ARCHITECTURE.md`(Contents API로 받아 scratch에 저장한 사본), factory-simulator `docs/spec/AGREEMENTS.md`(A-01~A-12), `docs/spec/05-mqtt.md`
- 요청 요지: Shared 확정 Interface(Sensor Vibration, Product Created, Vision Result, Conveyor Control, Line Status)·simulator 동작과의 모순, 구현자가 스스로 설계 결정을 내려야 하는 빈 곳(Interlock 판단 규칙, 상관분석, DB 스키마, 센서 25 KB × 10/s 적재량), 이 맥(Python 3.12, Node, Docker, 로컬)에서 실행·검증할 수 없는 것, toy 범위에 비해 과한 설계(DB·대시보드 스택), 더 나은 대안이 분명한 약한 결정, 다른 Component와의 경계 문제. 지적마다 심각도와 근거 위치를 요청했다.
- 참고: Codex는 샌드박스 안에서 Shared 원격 조회에 실패해 사본과 commit의 일치를 따로 확인하지 못했다고 적었다. 사본은 이 세션에서 같은 commit으로 Contents API에서 받은 파일이다.
- 판정 방법: 지적마다 초안의 해당 절과 Shared·simulator 문서의 원문을 읽고 확인했다(조율 결정 C-03 기준: 사실 오류·모순·구현자 결정이 필요한 빈 곳·검증 불가능한 것은 반영, 운영 수준 요구는 미반영). 적재량은 다시 계산했다. 입력 JSON 25 KB × 10/s = 250 KB/s(0.9 GB/h), chunk 한 행 `real[]` 저장은 약 12 KB/행 → 약 120 KB/s(0.44 GB/h, 5분 36 MB), 샘플 단위 전개는 초당 10,000행이다.
- 결과: 지적 16개. 반영 11, 부분 반영 5, 미반영 0.

| 번호 | 요지 | 판정 | 이유 / 반영 위치 |
|---|---|---|---|
| 1 | 확정된 다섯 Interface를 모두 '후보'로 적고 해결된 질문(Q-2·Q-14·Q-15)이 남아 있음 (high) | 반영 | 초안이 옛 commit `6bcd2aa` 기준이라 생긴 사실 오류다. 기준 commit을 `d0c997c`로 바꾸고 Topic·QoS·retain·필드를 확정값으로 적었다. PdM Result·Alarm Event만 미정으로 남겼다. 머리말, 0.1절, 6.1·6.2절, 11.1절 |
| 2 | 센서 Payload가 실제와 다름. 3축 1000개 배열, `seq`·`rpm`·`sample_rate_hz` 있음, `fault_level` 없음 (high) | 반영 | IF Sensor Vibration, SIM A-03·A-04와 대조해 확인했다. chunk 단위 입력·저장으로 고치고 `fault_level`은 Line Status 변화점에서 as-of join으로 붙인다. 5.1절, 6.1절, 6.4절, 7.2절 `sensor_chunk` |
| 3 | STOP 초안에 필수 `command_id`·`schema_version`이 없어 simulator가 `REJECTED`로 처리함 (high) | 반영 | IF Conveyor Control, SIM A-11, 05-mqtt 4절 필드 검증 순서와 같다. 확정 Payload, 명령마다 UUID4 `command_id`, retain false, 결과는 Line Status `last_command.command_id`로 연결. 6.2절 |
| 4 | Line Status의 `online:false` 형태와 명령 결과(`last_command`) 처리가 없음 (high) | 반영 | offline 메시지에 다른 필드가 없다는 것을 IF·SIM A-12에서 확인했다. 두 형태를 모두 받고, offline이면 Interlock이 라인 상태를 "알 수 없음"으로 본다. 결과는 `control` 행에 반영한다. 6.1절, 6.2절 6번, 10.2절 |
| 5 | 'CRITICAL 진입 때 1회' STOP 규칙으로는 simulator 재기동(항상 RUNNING)·로컬 START 뒤 정지를 유지하지 못함 (high) | 반영 | 맞다. 추가로 정지 중에는 PdM이 결과를 내지 않아(PdM 초안) 오래된 CRITICAL로 재가동이 영원히 막히는 반대 문제도 확인했다. 재가동 기준 시각 이후의 PdM 결과만 판정에 쓰고, CRITICAL + RUNNING/알 수 없음 + 대기 중 STOP 없음이면 STOP, 결과 확인 또는 5초 시간 초과로 대기 종료, START는 운영자 Dashboard로만. 6.2절 Interlock 규칙 1~7번, 6.3절 |
| 6 | timestamp 밀리초 3자리, `sensor_id` 정규식, production sequence, 대문자 State, Vision `product_id` 필수가 '미정'으로 남음 (medium) | 반영 | CONV·IF에서 확인했다. simulator가 소수 0~6자리를 받는 것과 무관하게 Operations는 3자리로 발행한다. `product_id` 없는 Vision 결과 처리 절은 지웠다. 6.5절, 6.2절 |
| 7 | Vision 흐름을 AI 검사·Grad-CAM 기록처럼 그림. 현재는 pass-through, `confidence`·`bbox`·`gradcam_path` null (medium) | 반영 | ARCH 4.3 현재 범위, IF Vision Result와 같다. 흐름도에서 Grad-CAM 기록을 빼고 null·`judgement_source`를 DB·화면에 반영했다. 5.2절, 6.6·6.7절, 7.2절, 9.1절 |
| 8 | 시간 결합 규칙이 없어 `health_index_at_time`을 재현할 수 없음 (high) | 반영 | 제품 ↔ 센서는 단일 라인 Line Status `sensor_id`, 캡처 시각 이하의 가장 최근 PdM 결과, 최대 차 5초, 없으면 null, 사용한 PdM timestamp도 저장. 늦게 온 메시지로 고치지 않는다. 6.4절 |
| 9 | 상관분석의 방법·윈도·표본 기준이 없음. 투입 → 캡처 약 13.3초를 고려해야 하며 chunk별 RMS 사용 제안 (medium) | 부분 반영 | 빈 곳과 Time Lag 지적은 맞아 방법(lag 0~30초 스캔, Pearson·Spearman, 기본 lag 13초, 30초 구간 차트, 최소 표본 20, 10초 주기)을 정했다. RMS 계산은 받지 않았다. Feature Extraction은 PdM 책임이다(ARCH 17). 설비 지표는 PdM의 `anomaly_score`를 쓴다. 6.8절 |
| 10 | DB 논리 스키마의 키·null·이벤트 시각, 불량률 분모가 없음. 분모는 Product Created 제품 수 제안 (medium) | 부분 반영 | 테이블별 키·열·쓰기 시점, 외래키 없음(도착 순서 비보장), 중복 무시, Defect Result는 view로 정했다. 분모는 Product Created 대신 **검사 수**로 했다. 검사 전 제품이 분모에 들어가면 불량률이 낮게 나오기 때문이다. 한 소스로 고정하라는 취지는 따랐다. Line Status 누계와 더하지 않는 것도 적었다. 전체 DDL은 spec 단계에서 쓴다. 7.2절 |
| 11 | 알려진 센서 적재량(약 250 KB/s)을 '수치 확정 후 결정'으로 미룸 (high) | 반영 | 수치를 다시 계산했다. chunk 한 행 `real[]` 저장, 1초 배치 `executemany`, 약 0.44 GB/h·5분 36 MB, 화면용 링 버퍼 20 chunk. 7.4절 |
| 12 | 필수 FFT Spectrum 화면의 데이터 출처가 없음 (medium) | 부분 반영 | 사실이다. 그러나 PdM Result를 정하는 것은 predictive-maintenance다(C-04). Operations가 FFT를 하지 않는다는 것과 권장 공급 방식을 남은 항목으로 적고 조율 agent에 보고한다. 9.1절, 11.2절 O-2 |
| 13 | 실행·검증 경로가 재현되지 않음. `COMPONENT.md`가 비어 있고, 제품 흐름은 브라우저나 `fake_renderer.py`가 필요 (medium) | 부분 반영 | 기술 스택, 실행 형태, 수준별 검증 방식(pytest, Docker 연동, 이미지 빌드, 시스템 E2E는 integration)을 적었다. `COMPONENT.md`는 채우지 않았다. 조율 C-09에 따라 plan 단계 BOOT-1이 spec을 근거로 채운다. 8절, 9절, 10.4절, 11.3절 |
| 14 | Image Storage 로컬 접근이 모호함. Compose 컨테이너 + named volume 읽기 전용이 기본이어야 함 (medium) | 반영 | CONV·SIM A-17과 같다. 컨테이너 실행과 `:ro` 마운트를 기본으로, 호스트 실행은 테스트용 로컬 폴더로 한정했다. 8절 |
| 15 | toy 범위에 비해 DB 2개·별도 frontend/backend·migration 도구가 무거움 (low) | 부분 반영 | PostgreSQL 인스턴스 하나, 1초 polling, 빌드 없는 정적 화면, migration 도구 없이 순수 SQL 한 파일로 줄였다. TimescaleDB 확장은 Shared가 권장하고(ARCH 5.2) 같은 인스턴스에서 추가 비용이 거의 없어 켜 둔다(`sensor_chunk`만 hypertable). 7.1·7.3절, 9절 |
| 16 | PdM Result와 Alarm Event의 계약 소유 경계가 흐림. Alarm 발행 조건·Payload를 정하지 않음 (medium) | 반영 | PdM Result는 Operations가 필요로 하는 필드만 적고 결정은 PdM에 두었다. Alarm Event는 발행 여부(발행함), Topic·QoS·retain, Payload 초안, 생성 규칙을 정했다. 6.2절 Alarm Event, 6.3절, 11.2절 O-1·O-3 |

## 리뷰 밖에서 함께 고친 것

- 기준 commit(0.1절)과 문서 지위(머리말): 조율 결정 C-02·C-04·C-05에 맞춰 "배경 문서, 구현 기준은 spec"으로 바꿨다.
- 초안 질문 Q-1~Q-15의 처리 결과를 11.1절 표로 옮겼다.
