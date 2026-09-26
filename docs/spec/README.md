# Factory Operations & Control 구현 spec

> 상태: **확정** (2026-09-27). 조율 결정(C-00~C-15)과 `docs/ARCHITECTURE.md`(리뷰 반영본)를 근거로 남은 설계 결정을 이 spec이 정했다. PdM Result·PdM Spectrum은 생산자 확정 전 가정이다(`AGREEMENTS.md` A-05·A-06).
> 읽어야 할 때: 구현·계획 task를 시작할 때 항상 이 파일부터. 여기서 가리키는 파일(절)만 읽는다.

## 1. 읽는 규칙

1. 2절 표에서 작업 영역을 찾는다.
2. 표가 가리키는 파일·절만 읽는다. 다른 파일은 링크를 따라갈 때만 연다.
3. 한 주제는 한 파일에만 있다. 다른 파일은 그 파일을 가리킨다. 두 곳에 같은 내용이 보이면 원본(가리킴을 받는 쪽)을 따르고 중복을 고친다.
4. spec에 없는 설계 결정이 필요하면 추측으로 진행하지 않는다. `DECISIONS.md`에 새 항목을 추가하는 PR로 정한 뒤 구현한다. 교차 Component 약속을 바꿔야 하면 멈추고 조율 agent에 알린다(`AGREEMENTS.md`).

## 2. 작업 영역 → 읽을 문서

| 작업 영역·질문 | 읽을 문서(절) |
|---|---|
| 무엇을 만드나, 언제 끝나나, 시연에서의 역할 | `00-overview.md` |
| PLAN에 milestone·task 추가 | `00-overview.md` 6절, `08-verification.md` 5·7절, `DECISIONS.md` 1절 |
| 패키지 구조, 스레드·큐, StateStore, 설정 로딩, 시계·timestamp, 로그, 기동·종료 | `01-core.md` |
| MQTT 연결, 구독 Topic, 입력 Payload 검증, 발행 | `02-mqtt.md`, `AGREEMENTS.md` A-01~A-07 |
| Line Status 추적, 재가동 기준 시각, Interlock STOP, 운영자 START/STOP, 명령 결과, Alarm | `03-control.md` |
| `fault_level`·`health_index_at_time` 결합, 상관분석 | `04-analysis.md` |
| DB 스키마(DDL), DB 쓰기·배치·재연결, 요약 조회 | `05-storage.md`, `AGREEMENTS.md` A-08 |
| HTTP endpoint, `/api/snapshot`, stale 표시, 화면 | `06-dashboard.md`, `docs/WIREFRAME.html` |
| 설정 키·환경 변수, Dockerfile, 개발용 compose, 가짜 입력, 의존 버전 | `07-runtime.md` |
| 테스트, 성능 측정(Dashboard 5초, Interlock 1초), verify 명령, 사람 확인 목록 | `08-verification.md` |
| 다른 Component·Shared와의 형식·약속, integration이 쓰는 것 | `AGREEMENTS.md` |
| 왜 이렇게 정했나 | `DECISIONS.md` |
| 사람이 해야 하는 일 | `HUMAN.md` |

## 3. 문서 목록

| 파일 | 내용 |
|---|---|
| `00-overview.md` | 목표, 완료 정의(C-01~C-10), 시연에서의 역할, 범위, 구현 순서(M1~M6) |
| `01-core.md` | 저장소 구조, 스레드와 큐, StateStore, 설정, 시계, 로그, 수명 주기 |
| `02-mqtt.md` | paho client, Topic, 입력 검증 규칙(6종), 발행 Payload 생성과 규칙, 재연결 |
| `03-control.md` | LineTracker, 처리 순서, Interlock·명령·결과 확인, Alarm, 시나리오 S-01~S-12·L-01~L-11 |
| `04-analysis.md` | 시간 결합, 상관분석 |
| `05-storage.md` | DB 구성, 쓰기 작업, DB 스레드, DDL 전문, 조회 |
| `06-dashboard.md` | endpoint, 스냅숏 형식, stale 규칙, 화면 칸과 브라우저 동작 |
| `07-runtime.md` | 실행 키·환경 변수, 로컬 실행, Dockerfile, 개발용 compose, `fake_feed.py`, 의존 버전 |
| `08-verification.md` | 테스트 전략·fixture, 영역별 테스트, smoke, 성능 측정, verify, 사람 확인 M-01~M-10 |
| `DECISIONS.md` | 결정 기록 D-01~D-36 |
| `AGREEMENTS.md` | 교차 Component 약속 A-01~A-12, ARCHITECTURE 미결 사항의 해결 위치 |
| `HUMAN.md` | 사람이 할 일 H-1~H-2 |
| (`docs/WIREFRAME.html`) | Dashboard 배치 와이어프레임 |

## 4. 기준 문서의 순서

충돌하면 앞의 것을 따른다.

1. 책임자의 현재 지시(채팅)와 조율 결정(`COORDINATION_DECISIONS.md`, 작업 공간 루트)
2. `AGENTS.md`의 불변 규칙. 단, `DECISIONS.md` 1절 D-01~D-03은 책임자가 2026-09-27 채팅으로 지시한 예외다(조율 C-01)
3. Shared에 확정된 Interface·CONVENTIONS(`AGREEMENTS.md` 머리말의 commit). `contract_ref` 채택 전까지 D-04의 방식으로 쓴다
4. 이 spec(`docs/spec/`)
5. `docs/COMPONENT.md`(plan 단계 BOOT-1에서 이 spec으로 채운다)
6. `docs/ARCHITECTURE.md`(배경과 근거), `docs/WIREFRAME.html`(화면 모양)

## 5. `docs/ARCHITECTURE.md`와의 관계

ARCHITECTURE.md는 이 spec의 배경과 근거다. 두 문서가 다르면 이 spec을 따른다. 다른 곳:

| ARCHITECTURE | 이 spec |
|---|---|
| 4.1 도메인 워커가 DB에도 씀 | 워커와 DB 스레드 분리, 큐로 연결(D-14) |
| 4.2 디렉터리 | `db/`, `scripts/`, `compose.yaml`, `Makefile`, `tests/docker/` 추가(`01-core.md` 1절) |
| 6.2 규칙 1 "기동 직후 기준 시각 없음" | 기동 뒤 첫 `RUNNING` 관측도 기준 시각을 잡음(D-17) |
| 6.2 규칙 3 대기 중 STOP | + 같은 PdM 결과로 두 번 보내지 않음, `REJECTED`는 시간 초과까지 대기, 끊겨 있으면 발행 안 함(D-18, D-20) |
| 6.2 Alarm Event `from_state`·`to_state` | `severity` + `previous_state`(D-22, A-02) |
| 6.8 범위 "서비스 기동 후 전체" | DB 전체(D-30) |
| 7.2 `line_status_change` 키 `timestamp` | `id` 키, `received_at` 추가, offline은 `timestamp` null(D-27) |
| 7.2 `control` 열 | `source`, `observed_at`, `recorded_at` 추가(D-28) |
| 9 차트는 vendored 경량 라이브러리 | canvas 직접 그리기(D-12) |
| 9.1 FFT Spectrum "PdM 미제공" | `factory/pdm/spectrum` 구독(조율 C-12, A-06) |
| 9.1·10.1 5초 측정은 integration이 정함 | 측정 방법을 이 spec이 고정, integration은 같은 방법으로 시스템 측정(D-34, A-10) |
| 10.2 DB 끊김은 수동 재시작 | 2초 간격 재연결(`05-storage.md` 3절) |
| `/healthz`만 | `/readyz` 추가(D-33) |
| 11 미결 O-1~O-5 | `AGREEMENTS.md` 끝 표 |

## 6. 바꾸는 방법

- spec 변경은 해당 파일과 그것을 가리키는 파일을 같은 PR에서 고친다. 결정이 바뀌면 `DECISIONS.md`에 새 항목을 추가한다.
- `AGREEMENTS.md`를 바꾸면 "맞출 Component"가 달라질 수 있다. PR 본문에 적고 조율 agent에 알린다. Alarm Event(A-02)를 바꾸면 Shared DOCUMENT_CHANGE도 다시 필요하다.
- PdM Result·PdM Spectrum이 Shared에 확정되면 OPS-10에서 A-05·A-06과 `02-mqtt.md` 3.6·3.7절을 확정본에 맞춘다.
- spec 리뷰 기록은 `docs/reviews/`에 있다. 구현에는 필요 없다.
- 참고한 Shared commit: `d0c997c97129141d9853a42ce6e0d1f8f7309ae9`(2026-09-27 조회한 main, 원격 Contents API로 읽음).
