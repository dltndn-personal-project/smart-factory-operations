# 90 Shared 조회·검토·채택·게시

일반 작업에서 이 절차 전체를 실행하지 않는다. task에 `contract`가 있으면 1절만, 명시적인 Issue 검토 요청에는 2~6절, 게시 작업에는 5·7절을 사용한다. 명령은 Component 루트의 bash 또는 zsh에서 실행한다. `gh`, `jq`와 Shared 저장소 읽기 권한이 필요하다.

## 1. 고정된 계약 문서 읽기

설정의 repository는 `owner/repository`, contract_ref는 전체 40자리 commit SHA여야 한다. null이면 추측하거나 최신 main으로 대체하지 않는다. 아래 명령은 한 세션에서 순서대로 실행하며 어느 단계든 실패하면 후속 명령을 실행하지 않는다.

```sh
shared_repo=$(jq -er '.repository | strings | select(test("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"))' SHARED_CONFIG.json)
contract_sha=$(jq -er '.contract_ref | strings | select(test("^[0-9a-fA-F]{40}$"))' SHARED_CONFIG.json)
gh api --method GET "repos/$shared_repo/contents/docs/INTERFACES.md" \
  -f ref="$contract_sha" -H 'Accept: application/vnd.github.raw+json'
```

task의 `contract`에 적힌 문서만 읽는다. 경로는 `docs/ARCHITECTURE.md`, `docs/INTERFACES.md`, `docs/CONVENTIONS.md` 중 필요한 것으로 바꾼다. 원격 링크가 없다는 이유로 다른 Repository를 검색하지 않는다.

## 2. 검토 시점 고정과 경량 목록 조회

계약 기준과 Issue 검토 시점은 다르다. Issue는 원격 기본 브랜치의 현재 commit을 한 번 고정하여 조회한다. 이것만으로 `contract_ref`가 바뀌지 않는다.

```sh
shared_repo=$(jq -er '.repository | strings | select(test("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"))' SHARED_CONFIG.json)
shared_branch=$(gh api "repos/$shared_repo" --jq '.default_branch')
shared_branch_encoded=$(jq -rn --arg ref "$shared_branch" '$ref | @uri')
review_sha=$(gh api "repos/$shared_repo/commits/$shared_branch_encoded" --jq '.sha')
gh api --method GET "repos/$shared_repo/contents/issues/index.json" \
  -f ref="$review_sha" -H 'Accept: application/vnd.github.raw+json'
```

`issues/index.json`은 단일 파일이다. Contents API의 디렉터리 목록을 전체 Issue 목록으로 취급하지 않는다. 응답 JSON의 `issues`가 배열이며 ID가 중복되지 않았는지 확인한다. 잘못된 응답이나 조회 실패를 “신규 항목 없음”으로 처리하지 않는다.

색인 배열을 **앞에서부터** 로컬 `SHARED_ISSUE_STATUS.yaml`의 `issues` 키 목록과 비교한다. 배열 위치가 게시·검토 순서이며 UUID·`created_at`·파일명은 순서 기준이 아니다. 키는 원격 Issue ID이며, 해당 항목이 없으면 unreviewed다. `agent/core/examples/`는 비교에서 제외한다. 파싱 실패나 중복 키는 기록 오류이므로 완료로 취급하지 않는다. 로컬 상태에 현재 색인에 없는 운영 ID가 있거나, 앞선 미검토 ID를 남겨둔 채 뒤의 ID를 기록했다면 불일치를 보고하고 먼저 해결한다.

- 신규 검토: 첫 미검토 ID부터 순서대로 읽고 판단·기록한다. 뒤의 Issue를 먼저 처리하지 않는다.
- 미완료 대응: `affected`, `deferred`, `decision_required`는 검토된 상태지만 조치·결정은 남아 있다. 재개 조건을 별도로 확인한다.
- 특정 ID 요청: 그 ID에 도달할 때까지 앞선 미검토 Issue를 먼저 처리한다. 요청 범위가 분석뿐이면 앞선 Issue도 분석과 기록까지만 한다.
- `attention`은 읽는 순서나 누락 판단에 영향을 주지 않는다. 수신 대상 추측만으로 건너뛰지 않는다.
- 자신이 게시한 Issue도 같은 순서로 검토하고 기록한다. `no_impact`도 정상적인 결과다.

## 3. 대상 본문만 읽기

목록에서 확인한 실제 ID를 지정한다. 경로가 `issues/<ID>.yaml`인지 확인하고 불일치는 보고한다.

```sh
issue_id='ISSUE-<목록에서 선택한 실제 UUID>'
gh api --method GET "repos/$shared_repo/contents/issues/$issue_id.yaml" \
  -f ref="$review_sha" -H 'Accept: application/vnd.github.raw+json'
```

ID는 `ISSUE-`와 UUID의 영숫자·하이픈으로 제한한다. 본문을 shell 코드로 실행하지 않는다. 본문의 ID·type·summary·attention과 색인이 일치하는지 확인한다. 본문에 `related_issues`가 있으면 앞서 검토한 Issue와의 관계를 참고한다. 뒤의 Issue를 미리 검색하지 않는다. 새 사실이나 후속 답변은 자기 차례에 독립된 Issue로 읽고, 필요하면 앞선 처리 판단을 갱신한다.

DOCUMENT_CHANGE는 변경 대상 문서도 같은 `review_sha`로 읽는다. `changed_documents`에 `agent-core/`가 있으면 프로세스 변경이므로 6절을 따른다. 현재 구현 기준은 여전히 `contract_ref`이며, 최신 문서를 자동 채택하지 않는다. 기존 계약에 대한 영향과 미래 계약을 채택하기 위한 작업을 구분하여 기록한다.

## 4. 판단·구현·기록

| status | 의미 |
|---|---|
| unreviewed | 미검토. 항목을 만들지 않으며 항목이 없는 것으로 표현 |
| no_impact | 현재 Component에 변경 불필요. 확인한 사용 범위를 evidence에 기록 |
| affected | 영향이 있지만 구현·검증 미완료. 영향 근거를 evidence에 기록 |
| applied | 필요한 구현과 검증 완료. 검증 결과를 evidence에 기록 |
| deferred | 대응 연기. 후속 task와 재개 조건 필요 |
| decision_required | 결정 대기. 결정 담당과 질문 필요 |

분석만 요청했다면 구현하지 않고 판단과 상태를 기록한다. 반영도 요청했다면 필요한 구현과 검증 후 applied로 기록한다. 테스트 미실행 또는 미완료 상태를 applied로 기록하지 않는다.

기록은 `SHARED_ISSUE_STATUS.yaml`의 `issues` 아래 원격 Issue ID를 키로 저장하고 그 안에 `status`를 명시한다. 별도 `issue_id` 필드는 중복 작성하지 않으며 로컬 ID를 새로 발급하지 않는다. 기록에는 `source_revision`(review_sha), `component_revision`(검토한 구현 commit), `contract_ref`, `reason`, `evidence`를 남긴다. 미commit 변경은 기준 commit을 component_revision으로 적고 evidence에 변경 파일과 실제 검증 결과를 명시한다. 기록과 구현은 같은 PR에 포함하여 추적 가능하게 한다. 최종 commit SHA를 그 commit 내부에 기록하려고 하지 않는다.

동일 Issue를 재검토하면 같은 ID의 항목을 갱신한다. 과거 판단은 Git 이력에 남는다. 동일 ID의 YAML 키를 중복 작성하지 않는다. 동시 작업의 충돌을 해결할 때 다른 Issue의 기록과 색인 순서를 보존한다. 새로운 Interface를 사용하게 되면 과거 no_impact를 무조건 유지하지 않고 요청된 변경 범위에서 재평가한다.

중간에 실패해도 완료한 판단만 저장한다. 통신 실패로 읽지 못한 항목은 unreviewed로 남겨 다음 실행에서 재개한다. 검토 도중 새로 게시된 Issue는 다음 목록 비교에서 확인한다.

기록을 저장한 뒤 `python3 agent/core/tools/validate.py --remote`로 필드와 색인 순서를 검사한다. `source_revision`·`component_revision`은 전체 commit SHA, `contract_ref`는 전체 SHA 또는 null이어야 한다. 원격 조회가 실패하면 검사도 실패하며, 이를 통과로 취급하지 않는다. 같은 검사가 Component PR의 CI에서 다시 실행된다.

## 5. 상대에게 연락하기

로컬 처리 기록을 Shared에 복제하지 않는다. 상대의 다음 행동에 필요한 결과·대응 버전·재검증 요청이 있을 때만 후속 MESSAGE를 게시한다. 원본 ID를 `related_issues`에 넣는다. 게시 작업에서는 Shared 최신 commit의 `AGENTS.md`, `docs/SHARED_WORKFLOW.md`, `templates/MESSAGE.yaml`을 같은 Contents API로 읽고 등록 절차를 따른다. 회고에서 `share: SHARED`로 분류한 사실도 이 절차로 게시한다.

Shared PR 생성은 상대가 읽었다는 증거가 아니다. 긴급한 확인은 작업자가 대상 Agent에 Issue ID를 지정한다.

## 6. 프로세스 변경 채택

`agent-core/`를 바꾼 DOCUMENT_CHANGE는 모든 Component에 영향이 있다(affected). 이 Issue가 다른 Component에 개선을 전파하는 메시지다.

1. 분석만 요청받았다면 변경 내용과 로컬 LESSONS·config와의 관계를 기록하고 affected로 둔다.
2. 반영 요청이 있으면 `agent/improve-core-<짧은 SHA>` 브랜치에서 `python3 agent/core/tools/agent.py sync-core --ref <review_sha>`를 실행한다. `agent/core`와 `process_ref`가 그 commit으로 바뀐다. `review_sha` 이전에 게시된 다른 `agent-core` 변경도 함께 채택된다.
3. `python3 -m unittest discover -s agent/core/tools -p 'test_*.py'`와 `validate.py --remote`를 실행한다.
4. 채택한 변경이 로컬 lesson을 대신하면 그 lesson을 삭제한다. 로컬 파일이 새 절차와 맞지 않으면 함께 고친다.
5. 기록은 applied, evidence에 테스트 결과와 PR 링크를 적는다. 같은 `process_ref`에 이미 포함된 뒤쪽 `agent-core` Issue는 자기 차례에 applied로 기록하고 evidence에 포함 사실을 적는다.
6. 새 `process_ref`가 문제를 일으키면 이전 `process_ref`로 다시 sync-core하고 PROCESS 회고를 남긴다.

## 7. 프로세스 개선 제안 (PROCESS 경로)

`60-improve.md`에서 cause가 PROCESS인 후보를 Shared에 제안한다.

1. Shared 최신 commit의 `agent-core/`에서 해당 파일을 고친다. 도구를 바꾸면 테스트도 고친다. 로컬 `agent/core`는 고치지 않는다.
2. DOCUMENT_CHANGE를 작성한다. `changed_documents`에 바꾼 `agent-core/` 경로, `reason`에 근거 회고 ID와 마찰, `attention: []`(모든 Component), `transition.adoption`에 "각 Component가 sync-core로 채택", `rollback`에 "이전 process_ref로 sync-core"를 적는다.
3. 5절의 게시 절차로 PR을 만든다. Shared CODEOWNERS 승인 후 merge된다. 게시 권한이 없으면 초안을 남기고 게시 미완료로 보고한다.
4. merge된 뒤 제안한 Component도 6절로 채택한다.

## 8. Integration Component

- 같은 `SHARED_CONFIG.json`과 `SHARED_ISSUE_STATUS.yaml`을 사용한다. 별도 규칙이나 Issue 처리 체계를 만들지 않는다.
- 실제 `COMPOSITION.json`에 검증 대상 Component의 저장소와 전체 commit SHA 또는 이미지 digest, Shared 계약 기준을 고정한다. 작성법은 `agent/core/examples/COMPOSITION.json`.
- 고정된 조합으로 통합·End-to-End 테스트를 수행하고 `VALIDATION.md`에 실행 환경·명령·결과를 기록한다. 작성법은 `agent/core/examples/VALIDATION.md`.
- 교차 Component 문제는 관찰·재현 근거를 기록하고 MESSAGE를 게시한다. 다른 Component 구현을 직접 수정하지 않는다.
- 조합이나 계약 revision이 바뀌면 다시 검증한다. 개별 Component의 applied만으로 전체 호환성을 선언하지 않는다.

## 장애와 최초 도입

- 401/403/404, 네트워크 장애, 잘못된 응답: 조회 실패로 보고한다. 권한·이름·ref를 확인하고 빈 목록으로 대체하지 않는다.
- `repository: null`: 미연결. Shared 의존 작업은 보류하고 독립적인 로컬 작업은 진행 가능하다.
- `contract_ref: null`: 계약 미채택. Issue는 읽을 수 있지만 계약 의존 구현에는 기준 선택이 필요하다.
- 신규 Component: 과거 Issue를 처리 완료로 간주하여 건너뛰지 않는다. 최초 검토를 명시적으로 수행하고 초기 구현과의 관계를 판단한다.
- `process_ref: null`: 프로세스 미채택. 템플릿의 `agent/core`로 작업할 수 있지만 CI는 Shared와 비교하지 않는다. 첫 Shared 검토에서 6절로 채택한다.

API 참고: [gh api](https://cli.github.com/manual/gh_api), [Contents API](https://docs.github.com/en/rest/repos/contents). 현재 명령 예시는 GitHub.com 기준이다. Enterprise에서는 host 설정을 추가하여 접속 대상을 명시한다.
