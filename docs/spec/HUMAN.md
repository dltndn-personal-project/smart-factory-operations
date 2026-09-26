# 사람이 할 일

> 목적: 프로젝트 완료까지 책임자(사람)만 할 수 있는 일을 최소로 모은다. 그 밖의 결정과 작업은 agent가 한다(`DECISIONS.md` 1절).
> 읽어야 할 때: 책임자가 무엇을 언제 해야 하는지 볼 때, 계획 작업이 사람 task를 만들 때.

| ID | 무엇 | 언제 |
|---|---|---|
| H-1 | agent 작업 환경 유지 | 구현 기간 내내 |
| H-2 | Dashboard 확인(HUM-1) | M4(화면과 패키징) merge 뒤 |

Shared DOCUMENT_CHANGE 게시(Alarm Event)와 PR merge는 조율 agent가 한다(조율 C-01·C-04). 사람 할 일이 아니다.

## H-1 agent 작업 환경 유지

- 방법: 맥북에서 Docker Desktop을 켜 두고 `gh auth status`가 로그인 상태이게 한다. 첫 의존 설치에 인터넷이 필요하다(pip, Docker 이미지 `python:3.12-slim`, `eclipse-mosquitto:2.1.2-alpine`, `timescale/timescaledb:2.30.1-pg17`).
- 건너뛰면: `docker`·`smoke` 검증이 실패해 해당 task가 멈춘다(잘못 통과하지는 않는다, `08-verification.md` 1절).

## H-2 Dashboard 확인 (HUM-1)

- 방법: `08-verification.md` 6절 M-01~M-10을 순서대로 확인하고 task 결과에 항목별 통과/실패와 메모를 남긴다. 약 20분.
- 실패 항목이 있으면 그 내용만 적는다. 계획 작업이 수정 task를 만들고, 수정 뒤 그 항목만 다시 본다.
- 건너뛰면: 화면 배치·색·문구·끊김 표시가 사람 눈으로 확인되지 않은 채 남고 완료 정의 C-10을 만족하지 못한다.
