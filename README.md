# Factory Operations & Control (`factory-operations`)

Smart Factory System의 Factory Operations & Control Component 저장소다. 아래는 공통 Component 템플릿 안내다.

이 폴더 전체(숨김 폴더 `.github/` 포함)를 새 Component 저장소의 루트에 복사한다. `AGENTS.md`는 기존 지침이 있으면 충돌을 확인하여 병합한다. Integration도 같은 템플릿을 사용한다.

Agent(Codex, Claude Code 등)는 `AGENTS.md`를 먼저 읽고 `agent/PLAN.yaml`의 계획을 task 단위로 실행한다. 매 task를 회고하고, 반복되는 마찰을 개선 제안으로 바꾼다. 절차는 도메인을 모르며, 도메인은 `docs/COMPONENT.md`, `agent/config.yaml`, PLAN의 milestone, Shared 계약으로만 들어온다.

## 구성

| 경로 | 내용 | 변경 |
|---|---|---|
| `AGENTS.md`, `CLAUDE.md` | 부트로더: 불변 규칙, 시작 방법, 파일 지도 (80줄 이하) | 사람 |
| `docs/COMPONENT.md` | 도메인 슬롯 | 사람 리뷰 |
| `agent/config.yaml` | 공통 검증 명령, 예산, 개선 기준 | 사람 리뷰 |
| `agent/PLAN.yaml` | milestone과 task. Agent 제안은 `proposed: true` | 사람 리뷰 |
| `agent/SESSION.yaml` | 진행 중인 task의 단계, steps, 증거 | 도구 |
| `agent/tasks/<id>.yaml` | task 결과 (done, verifying, blocked, dropped) | 도구 |
| `agent/retros/<id>-<n>.yaml` | 회고. merge 후 불변 | Agent (자동 승인) |
| `agent/LESSONS.yaml` | 회고에서 나온 행동 규칙 | Agent (자동 승인) |
| `agent/core/` | 공통 절차와 도구. Shared `agent-core/`의 `process_ref` 사본 | Shared에서만 |
| `SHARED_CONFIG.json` | Shared 저장소, `contract_ref`, `process_ref` | 사람 리뷰 |
| `SHARED_ISSUE_STATUS.yaml` | Shared Issue 처리 기록 | Agent |

## 시작하기

1. `SHARED_CONFIG.json`을 설정한다.
   - `repository`: Shared 저장소의 `owner/repository` (전체 URL이나 `.git` 없이)
   - `component`: 이 Component의 고유 이름. Integration이면 `integration`
   - `contract_ref`: 구현 기준으로 채택한 Shared 계약의 전체 commit SHA. 없으면 null로 두고 계약 의존 작업은 보류한다
   - `process_ref`: `agent/core`를 가져온 Shared commit. 템플릿 그대로면 null로 두고 첫 Shared 검토에서 채택한다
2. `.github/CODEOWNERS`의 placeholder를 실제 책임자로 바꾼다.
3. main 브랜치 보호 규칙: PR 필수, 승인 1개 이상, "Require review from Code Owners", "Dismiss stale pull request approvals when new commits are pushed", 필수 검사 `Validate Component / validate`, 관리자 우회 금지. Settings에서 "Allow GitHub Actions to create and approve pull requests", "Allow auto-merge", "Allow squash merging"을 켠다.
4. Shared가 비공개라면 Shared 읽기 권한만 가진 fine-grained token을 `SHARED_READ_TOKEN` secret에 등록한다.
5. Agent에게 작업을 시킨다. 첫 task는 `BOOT-1`(도메인 슬롯 채우기)이다. Agent가 제안한 milestone과 task를 PR 리뷰에서 승인(`proposed` 표시 제거)하면 계획 기반 작업이 시작된다.

GitHub CLI(`gh`), Python 3.10 이상, `pip install -r agent/core/requirements.txt`가 필요하다. 사용자가 `gh auth login`으로 인증한다. 자격증명은 저장소에 넣지 않는다.

## 작업 루프

```text
agent.py next → start → plan → execute → verify → retro → finish → (개선 제안) → next
```

`python3 agent/core/tools/agent.py <명령>`의 게이트가 절차를 강제한다.

- `verify`: commit하지 않은 변경을 거부하고, 증거를 commit에 묶는다.
- `finish`: 다음을 모두 만족해야 통과한다.
  - 모든 검증이 같은 commit에서 통과했다
  - 검증 이후 코드가 바뀌지 않았다
  - scope 밖 변경이 없다
  - 이번 세션의 회고가 있다

## 자기 개선

- 모든 task는 회고(`agent/retros/`)로 끝난다.
- `agent.py scan`이 개선 후보를 찾는다. 기준은 같은 원인 tag가 최근 회고에 `repeat`회 이상 나오거나 severity high가 1건 있을 때다.
- 제안은 항상 자동으로 하고, 채택은 다음과 같이 계층별로 나뉜다.
  - Agent 행동 규칙(`LESSONS.yaml`): CI가 자동 승인한다.
  - 도메인 문서, 설정, 계획: 사람이 리뷰한다.
  - 공통 절차(`agent-core`): Shared DOCUMENT_CHANGE를 사람이 승인한다. merge된 Issue가 모든 Component에 전파되고, 각 Component가 `sync-core`로 채택한다.
- trial lesson은 `review_after`개 회고 뒤에 평가한다. 재발하면 고치거나 삭제하고, 사용되지 않았으면 삭제하고, 효과가 있으면 adopted로 확정한다.

세부 절차는 `agent/core/README.md`와 `agent/core/process/`에 있다.

## 검증

`python3 agent/core/tools/validate.py`가 모든 agent 파일을 검사한다.

- 설정: 필드와 SHA 형식
- PLAN: 착수 조건, 의존성 순환
- 상태 파일: SESSION, task 결과, 회고, LESSONS(근거 회고 수, 상한)
- Shared Issue 기록
- `COMPOSITION.json`

옵션에 따라 추가로 검사한다.

- `--remote`: Issue 기록 순서와, `agent/core`가 Shared `agent-core`@`process_ref`와 같은지 확인한다.
- `--base <SHA>`: merge된 회고가 바뀌지 않았는지 확인한다. 조합 파일이 바뀌었으면 `VALIDATION.md`도 함께 바뀌었는지 확인한다.

`.github/workflows/validate-component.yml`이 PR과 main push에서 같은 검사와 도구 테스트를 실행한다. 학습 층만 바꾼 PR은 CI가 승인하고 auto-merge를 켠다.

Shared Snapshot, 원격 Issue 본문 사본, 전체 조회 이력은 commit하지 않는다. `agent/core`는 CI가 원본과의 일치를 검증하는 예외다.
