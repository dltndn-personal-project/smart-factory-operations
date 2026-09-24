# agent/core

모든 Component가 공유하는 작업 절차와 도구다. 원본은 Shared 저장소의 `agent-core/`이며, 이 디렉터리는 `SHARED_CONFIG.json`의 `process_ref` commit과 같아야 한다. CI가 `validate.py --remote`로 확인한다.

- 로컬에서 수정하지 않는다. 개선은 `process/60-improve.md`의 PROCESS 경로로 Shared에 제안한다.
- 채택은 `process/90-shared.md` 6절에 따라 `tools/agent.py sync-core --ref <Shared commit>`으로 한다.
- Component 고유의 내용은 `docs/COMPONENT.md`, `agent/config.yaml`, `agent/PLAN.yaml`, `agent/LESSONS.yaml`에 둔다.

| 경로 | 내용 |
|---|---|
| `process/00-session.md` | 세션 시작, 루프, 브랜치·PR, 종료 |
| `process/10-bootstrap.md` | 새 도메인의 슬롯 채우기 |
| `process/20-plan.md` | task 계획과 milestone 분해 |
| `process/30-execute.md` | 실행 |
| `process/40-verify.md` | 검증 |
| `process/50-reflect.md` | 회고 (사용자가 요청할 때만) |
| `process/60-improve.md` | 개선 제안과 채택 |
| `process/80-escalate.md` | 멈춤 조건과 보고 |
| `process/90-shared.md` | Shared 계약 조회, Issue 검토, 프로세스 채택, 게시 |
| `tools/agent.py` | 작업 루프: next, start, phase, verify, retro(요청 시), finish, block, drop, scan, sync-core |
| `tools/validate.py` | 모든 agent 파일과 Shared 기록 검사 |
| `tools/auto_approval.py` | 학습 층만 바꾼 PR의 자동 승인 판정 |
| `examples/` | 가상 도메인으로 쓴 작성 예시. 실제 상태가 아니다 |

도구는 Python 3.10 이상과 `requirements.txt`가 필요하다. Shared 조회에는 `gh`가 필요하다.
