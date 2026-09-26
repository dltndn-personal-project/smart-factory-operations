# Factory Operations & Control 구현 계획

> 상태: Codex 리뷰 반영(`docs/reviews/plan-codex-1.md`), 이 계획 PR에서 `agent/PLAN.yaml`에 등록했다(2026-09-27, 책임자 채팅 승인 spec D-02, 조율 C-01).
> 읽어야 할 때: task를 시작·실행·merge할 때, 다음 task를 고를 때, 계획을 바꿀 때. 무엇을 만드는지는 `docs/spec/README.md`부터.

## 1. 읽는 규칙

1. 이 폴더는 `docs/spec/`과 파일 이름이 같다. 영역 NN을 작업하면 `docs/spec/NN-*.md`와 `docs/plan/NN-*.md`를 같이 읽는다. 어느 파일인지는 2절 표.
2. 계획 파일은 사람이 읽는 원본이고, `agent/PLAN.yaml`은 도구(`agent.py`)가 실행하는 사본이다. 두 곳의 task 블록(id, milestone, type, title, why, depends_on, scope, acceptance, size, owner, contract)은 같아야 한다.
3. 다르면 **PLAN.yaml이 이긴다**. 발견한 agent는 작업을 계속하고 PR 본문에 차이를 적는다. 조율 agent가 계획 파일을 PLAN.yaml에 맞게 고친다.
4. 계획 파일의 단계 개요와 "읽을 spec"은 PLAN.yaml에 없다. `20-plan.md`에서 `SESSION.yaml` steps를 쓸 때 출발점으로 쓴다(8개 이하).
5. 설계 결정은 `docs/spec/DECISIONS.md` 하나에 둔다. 이 계획의 결정은 D-37~D-46이다(D-45는 Codex 리뷰 반영, D-46은 Shared 확정 반영).

## 2. task → 계획 파일 → spec

| task | 계획 파일 | 읽을 spec(모두 `docs/spec/`, 절은 계획 파일의 "읽을 spec") |
|---|---|---|
| OPS-1 | `01-core.md` | `01-core.md`, `07-runtime.md` 1·2·6·7절, `08-verification.md` 1·2·3.1·5절 |
| OPS-2 | `02-mqtt.md` | `02-mqtt.md` 2~4절, `AGREEMENTS.md` A-01~A-07 |
| OPS-3A, OPS-3B | `03-control.md` | `03-control.md`, `01-core.md` 2·3절, `04-analysis.md` 1절(OPS-3A), `05-storage.md` 2절(OPS-3B) |
| OPS-4A, OPS-4B | `05-storage.md` | `05-storage.md`, `AGREEMENTS.md` A-08, `08-verification.md` 2·3.6절 |
| OPS-5 | `04-analysis.md` | `04-analysis.md` 2·3절, `05-storage.md` 3·5절 |
| OPS-6 | `06-dashboard.md` | `06-dashboard.md` 1~4·6절, `08-verification.md` 3.5절 |
| OPS-7A | `02-mqtt.md` | `02-mqtt.md` 1·4·5절, `01-core.md` 2·7절, `03-control.md` 3.3절, `08-verification.md` 2·3.6절 |
| OPS-7B | `08-verification.md` | `08-verification.md` 4절, `AGREEMENTS.md` A-10·A-11 |
| OPS-8 | `06-dashboard.md` | `06-dashboard.md` 4·5절, `docs/WIREFRAME.html` |
| OPS-9A, OPS-9B | `07-runtime.md` | `07-runtime.md`, `08-verification.md` 3.7·6절, `AGREEMENTS.md` A-09 |
| OPS-10 | `02-mqtt.md` 5절 | `AGREEMENTS.md` A-02·A-05·A-06, `02-mqtt.md` 3.6·3.7절, `agent/core/process/90-shared.md` 1절 |
| HUM-1 | `08-verification.md` 3절 | `08-verification.md` 6절, `HUMAN.md` |
| verify 명령 추가, 포트 | `08-verification.md` 1·2절 | `08-verification.md` 5절 |
| 단계, 의존, C-xx | `00-overview.md` | `00-overview.md` |
| 사람 할 일 시점 | `HUMAN.md` | `HUMAN.md` |

모든 task는 `DECISIONS.md`의 관련 항목과 `AGENTS.md`를 따른다. `AGREEMENTS.md`는 교차 Component 형식의 구현 기준이다. task의 `contract` 필드는 OPS-10이 `contract_ref`를 채택하기 전에는 쓰지 않는다(spec D-04).

## 3. 단계와 milestone

단계 = milestone M1~M6(M0은 BOOT-1, 이 계획 PR에서 완료). 결과, 종료 조건, task, 완료 정의 대응은 `00-overview.md` 1~3절. 조율 agent는 단계마다 새 subagent 하나를 띄운다(조율 C-07).

## 4. 실행 순서와 병렬

기본은 **한 번에 task 하나, PLAN 순서**다(`00-overview.md` 2절 표 순서). task 하나 = 브랜치 하나 = PR 하나이고, 다음 task는 앞 PR이 merge된 최신 main에서 시작한다. `agent.py start`는 `depends_on`이 모두 `done`일 때만 시작한다.

OPS-10은 예외다. `depends_on`은 OPS-2뿐이고 착수 조건은 **조율 agent의 Shared DOCUMENT_CHANGE(PdM Result, PdM Spectrum, Alarm Event) merge 알림**이다. 이 조건은 2026-09-27에 충족되었다(Shared PR #7, `cb6dc3cc6900e9f129b2a06688c5e5e5f75fd0b8`). PLAN 순서는 M5(OPS-9B 뒤)지만 조율 agent가 OPS-2 뒤 아무 때나 다음 task로 끼워 넣을 수 있고, OPS-2 바로 뒤가 가장 싸다(뒤 task의 PdM 메시지가 처음부터 확정 형식이 된다, `02-mqtt.md` 5절).

병렬은 조율 agent가 속도가 필요할 때만 쓴다(D-41). 조건:
- 두 task 모두 선행이 `done`이다.
- scope가 겹치지 않는다(`fnmatch`, `*`는 `/`를 포함). `agent/config.yaml`, `Makefile`, `docs/spec/*` 파일 하나라도 겹치면 안 된다. 예외는 `docs/spec/DECISIONS.md`(끝에 추가만 하므로 아래 merge 절차로 해결).
- 고정 포트를 쓰는 acceptance가 서로 겹치지 않는다(`08-verification.md` 2절 표). Docker 테스트와 smoke는 임의 포트·고유 이름을 써서 겹치지 않는다.
- 병렬 task는 각자 다른 worktree(`git worktree add ../fops-<ID> -b agent/<ID> origin/main`)에서 돈다. `SESSION.yaml`, `.venv`가 worktree마다 따로다(첫 `make venv` 1~2분).

scope가 겹치지 않는 조합(이 밖의 조합은 선행 관계나 scope 때문에 안 된다):

| 조합 | 시작 조건 | 단계 | 비고 |
|---|---|---|---|
| OPS-4A ∥ OPS-2·OPS-3A·OPS-3B 중 하나 | OPS-1 done | M2 ∥ M1 | Docker 기반을 코어와 함께 준비한다. OPS-4A가 먼저 merge되면 M1 task의 verify에 `docker`가 더해진다 |
| OPS-5 ∥ OPS-6 | OPS-4B done | M2 ∥ M3 | 가장 효과가 크다. OPS-7A는 둘 다 끝나야 시작 |
| OPS-8 ∥ OPS-7A 또는 OPS-7B | OPS-6 done (OPS-7B는 OPS-7A done) | M4 ∥ M3 | 화면 줄기와 연동 줄기 |
| OPS-8 ∥ OPS-9A | OPS-6·OPS-7A done | M4 안 | |
| OPS-7B ∥ OPS-9A | OPS-7A done | M3 ∥ M4 | 둘 다 Docker를 오래 쓴다(verify 3~5분) |
| OPS-10 ∥ OPS-3A·3B·4A·4B·5·6·7B·8 중 하나 | 조율 agent 알림, OPS-2 done | M5 ∥ 아무 단계 | OPS-7A·9A·9B와는 안 된다(`02-mqtt.md`·`07-runtime.md`·`scripts/fake_feed.py`가 겹침) |

단계 안에서는 M4의 OPS-8 ∥ OPS-9A만 가능하다. M1(OPS-1 → 2 → 3A → 3B)과 M2(OPS-4A → 4B → 5)는 앞 task의 모듈이나 fixture를 쓰므로 순서대로다.

병렬 task의 merge 절차(먼저 끝난 쪽은 평소대로 merge):
1. 나중 브랜치에 `git merge origin/main`(rebase 금지: `agent/tasks/<ID>.yaml`의 evidence commit이 이력에 남아야 한다).
2. `DECISIONS.md` 충돌이면 나중 브랜치의 새 ID를 뒤 번호로 바꾸고 그 ID를 가리키는 곳도 고친다.
3. `agent/config.yaml`의 verify 명령을 모두 다시 실행하고 결과를 PR 코멘트에 붙인다. main에 새로 생긴 verify 명령도 포함한다.
4. 하나라도 실패하면 merge하지 않는다. 조율 agent가 원인을 보고 FIX task를 만들거나, 브랜치에서 `agent/tasks/<ID>.yaml`을 지우고 그 task를 다시 연다.

## 5. task 하나 실행하기 (실행 agent)

실행 agent는 조율 agent가 띄운 subagent이고 단계 안의 task를 순서대로 하되 PR마다 멈춘다(조율 C-07). 먼저 `AGENTS.md`, `agent/core/process/00-session.md`를 읽는다.

```sh
git switch main && git pull --ff-only
git switch -c agent/<ID>
python3 agent/core/tools/agent.py next            # 병렬 실행이 아니면 <ID>가 나와야 한다
python3 agent/core/tools/agent.py start <ID>
# plan: 20-plan.md. 계획 파일의 단계 개요로 SESSION.yaml steps 작성(do, check, done: false)
git add agent/SESSION.yaml && git commit -m "<ID>: 계획"
python3 agent/core/tools/agent.py phase execute
# execute: 30-execute.md. step마다 check 실행 → done: true → commit "<ID>: <한 일>"
python3 agent/core/tools/agent.py verify           # 40-verify.md. 실패하면 고치고 commit 뒤 다시(같은 항목 3회까지)
python3 agent/core/tools/agent.py finish
git add agent/tasks/<ID>.yaml agent/SESSION.yaml && git commit -m "<ID>: 완료 기록"
python3 agent/core/tools/validate.py --remote
git push -u origin agent/<ID>
gh pr create --base main --head agent/<ID> --title "<ID>: <title>" --body-file <본문 파일>
```

- 회고(`agent.py retro`)는 책임자가 요청할 때만 쓴다. 요청이 없으면 verify 다음에 바로 finish.
- commit 메시지: `<ID>: <한 일>`(00-session.md). 서명 줄은 실행 환경이 정한 규칙을 따른다.
- `agent/config.yaml`을 바꾸는 task(OPS-1, OPS-4A, OPS-9A)는 추가할 명령을 먼저 직접 실행해 통과를 확인한다.
- spec을 고쳐야 하면 자기 scope의 spec 파일과 `DECISIONS.md`만 고친다(D-40). `00-overview.md`, `08-verification.md`, `AGREEMENTS.md`, `README.md`는 OPS-10 말고는 고치지 않는다(멈춘다).
- 임시 파일은 `mktemp`나 저장소 밖 scratch에 둔다. 넓은 패턴의 `pkill`/`docker rm`을 쓰지 않고 자기 프로세스·컨테이너는 PID·id로만 지운다(조율 C-11).
- Agent는 PR을 merge하지 않는다. merge는 조율 agent가 한다(spec D-01).

PR 본문:

```markdown
## <ID>: <title>
계획: docs/plan/<파일> · spec: <읽은 spec 절>

### acceptance
| ID | 결과 | 증거 요약(명령 출력 마지막 줄, 측정값) |

### 공통 verify
| name | 결과 | 걸린 시간 |
evidence commit: <SHA> (agent/tasks/<ID>.yaml)

### 바꾼 spec과 새 결정
- docs/spec/…: <무엇을, 왜> / D-xx: <한 줄>

### 계획과 다르게 한 점
- step note 요약. PLAN.yaml과 계획 파일의 차이를 발견했으면 여기에

### 사람 확인
- 이 task의 결과는 HUM-1 M-xx에서 사람이 본다 (해당할 때)
```

멈출 때(`80-escalate.md`). 이 계획에서 예상되는 경우:

| stops | 예 |
|---|---|
| scope | 다른 task의 모듈을 고쳐야 함(예: OPS-6에서 워커 수정), `00-overview.md`·`08-verification.md`·`AGREEMENTS.md`·`README.md` 변경이 필요함, 다른 Component·Shared 수정이 필요함 |
| ambiguity | spec 두 곳이 모순, 테스트 기대값이 spec 규칙·식과 맞지 않음(기대값을 바꾸지 않는다) |
| contract | Shared 확정본이 A-05·A-06의 의미(`timestamp` = 윈도우 끝, retain false, `rpm == 0` 미발행)와 다름, Alarm Event 확정본이 A-02와 다름, 알림 없이 OPS-10을 시작해야 할 것 같음 |
| repeated-failure | 같은 verify 항목 3회, 같은 step 3회 실패. 예: Interlock 1.0초, Dashboard 5.0초, 재연결 15초 |
| tool | Docker Desktop이 꺼짐, 이미지·pip를 받을 인터넷 없음, `gh` 로그아웃, `sips` 없음(`HUMAN.md`) |

절차: 변경을 commit → `python3 agent/core/tools/agent.py block --reason "<stops>: <무엇이 막혔나>" --unblock-when "<해제 조건>" --owner "<조율 agent 또는 책임자>"` → commit(`<ID>: block`) → push → draft PR 본문에 질문과 선택지 → 조율 agent에 보고. 다른 task로 넘어가지 않는다(다음 task는 조율 agent가 고른다).

## 6. 조율 agent

- 시작 전: `HUMAN.md`의 H-1 조건 확인(다음 task에 Docker·인터넷이 필요한지).
- merge 조건(spec D-01): PR에 `agent/tasks/<ID>.yaml`이 `status: done`으로 있고, `Validate Component / validate` CI가 통과했고, PR 본문의 acceptance·verify가 모두 pass다. 병렬이면 4절 절차까지. 그 뒤 main에 merge하고 다음 task를 최신 main에서 띄운다.
- merge 방식은 merge commit(`gh pr merge <번호> --merge`)이다. squash·rebase는 쓰지 않는다: `agent/tasks/<ID>.yaml`의 `commit`(evidence commit)이 main 이력에 남아야 한다(조율 C-01).
- block을 받으면: 해제 조건을 해결한다(계획 수정 PR, FIX task 추가, spec 수정 task). 해결되면 `agent/tasks/<ID>.yaml`을 지워 다시 연다.
- OPS-10: 착수 조건 충족(Shared PR #7 merge, `cb6dc3c`, 2026-09-27). 채택 SHA와 확정본과의 차이는 `02-mqtt.md` 5.1절에 적었다(의미 차이 없음, 형식이 더 엄격). OPS-2 merge 뒤 언제 끼워 넣을지 정한다. 권장은 OPS-2 바로 뒤(M1 subagent가 이어서 하거나 별도 subagent).
- 사람 task: OPS-9B merge 뒤 책임자에게 HUM-1을 요청하고, 결과를 `08-verification.md` 3절대로 기록한다. OPS-10을 기다리지 않는다.
- integration과의 경계: `/readyz`(A-09)와 Interlock 관찰 동작(A-11)은 OPS-6·OPS-7A가 spec대로 제공한다. E2E-3 단계 2의 STOP 제한 시간 2초 제안(A-11)과 `/readyz`를 E2E 시작 조건으로 쓰는 것은 integration spec이 받는다. operations에는 그 일을 하는 task가 없다.
- Alarm Event의 Shared DOCUMENT_CHANGE 게시는 별도 subagent가 한다(조율 C-04). operations task가 아니다.

### 등록(완료: 이 계획 PR에 포함)

책임자의 채팅 지시(spec D-02, 조율 C-01)를 근거로 이 계획 PR에서 했다. 계획을 다시 등록할 때도 같은 순서다. 바꾼 파일은 `agent/PLAN.yaml`, `agent/tasks/BOOT-1.yaml`, `.github/CODEOWNERS`.

1. `agent/PLAN.yaml`: M0은 그대로 두고 M1~M6을 `00-overview.md` 1절 블록으로 추가한다(`proposed` 없음).
2. task 블록을 `00-overview.md` 2절 표 순서로 붙인다(각 계획 파일의 YAML 블록 그대로).
3. `agent/tasks/BOOT-1.yaml`: `status: verifying`(A3 pending)을 `status: done`으로 바꾼다. `commit`은 그대로, `finished_at` 추가, `checks` 모두 `pass`. 근거는 D-02(책임자 채팅 승인, 조율 C-09). BOOT-1이 `done`이어야 OPS-1이 시작된다.
4. `.github/CODEOWNERS`의 `* @<component-책임자>`를 `* @dltndn`으로 바꾼다(조율 C-15).
5. `python3 agent/core/tools/validate.py --remote`와 `python3 agent/core/tools/agent.py next`(OPS-1이 나와야 한다).
6. PR 본문에 근거(D-02, C-01, C-09, C-15)를 적는다. PR merge 뒤 `agent.py next`가 첫 task를 고른다.

## 7. 계획 바꾸기

- 계획 변경은 계획 파일과 `agent/PLAN.yaml`을 같은 PR에서 고친다. 결정이면 `DECISIONS.md`에 새 ID를 추가한다.
- 실행 agent는 승인된 task의 acceptance·check·scope를 바꾸지 않는다(`20-plan.md`). 필요하면 멈추고, 조율 agent가 계획 변경 PR을 올린다.
- 새 task는 `proposed` 없이 넣는다(spec D-02). FIX task 형식은 `00-overview.md` 4절.
