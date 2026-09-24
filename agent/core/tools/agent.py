#!/usr/bin/env python3
"""Plan-driven task loop for Component agents.

next       다음 행동과 읽을 문서를 출력한다
start      task를 시작한다
phase      세션 단계를 바꾼다
verify     acceptance와 공통 검증을 실행하고 commit 기준 증거를 기록한다
retro      사용자가 요청하면 이번 task의 회고 초안을 만든다
finish     완료 게이트를 통과하면 task 결과를 기록한다
block      task를 차단 상태로 기록한다
drop       task를 폐기 상태로 기록한다
scan       회고에서 개선 후보와 평가 시점이 된 lesson을 찾는다
sync-core  Shared agent-core를 지정 commit으로 가져와 채택한다
"""

import argparse
import copy
import fnmatch
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import quote

import yaml

import validate as schema


SESSION = "agent/SESSION.yaml"
PHASE_DOCS = {"plan": "20-plan.md", "execute": "30-execute.md", "verify": "40-verify.md", "reflect": "50-reflect.md"}
# Agent state files may change during any task, whatever its scope.
STATE_FILES = ("agent/SESSION.yaml", "agent/tasks/*.yaml", "agent/retros/*.yaml", "agent/LESSONS.yaml", "SHARED_ISSUE_STATUS.yaml")
ROUTES = {
    "AGENT": "LESSONS.yaml에 trial lesson 추가 (학습 층 PR, CI 자동 승인)",
    "ENVIRONMENT": "agent/config.yaml 또는 환경 설정 수정 PR (사람 리뷰)",
    "DOMAIN_DOC": "docs/COMPONENT.md 보완 PR (사람 리뷰)",
    "PLAN": "PLAN.yaml 수정안을 proposed로 제안 (사람 리뷰)",
    "PROCESS": "Shared agent-core DOCUMENT_CHANGE PR (사람 승인 후 모든 Component에 전파)",
    "CONTRACT": "Shared 계약 DOCUMENT_CHANGE 또는 MESSAGE",
    "EXTERNAL": "기록만 유지",
}


class Stop(Exception):
    """A gate refused the request; the message says what to do instead."""


def path(name):
    return schema.ROOT / name


def load(name):
    return schema.read_yaml(path(name))


def save(name, data):
    path(name).parent.mkdir(parents=True, exist_ok=True)
    path(name).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(*args):
    result = schema.git(*args)
    if result.returncode != 0:
        raise Stop(f"git {' '.join(args)} 실패: {result.stderr.decode().strip()}")
    return result.stdout.decode()


def head():
    return git("rev-parse", "HEAD").strip()


def uncommitted():
    paths = []
    for line in git("status", "--porcelain", "--untracked-files=all").splitlines():
        paths.append(line[3:].split(" -> ")[-1].strip('"'))
    return paths


def changed_since(commit):
    return sorted(set(git("diff", "--name-only", commit, "HEAD").splitlines()) | set(uncommitted()))


def is_state(name):
    return any(fnmatch.fnmatch(name, pattern) for pattern in STATE_FILES)


def context():
    """Validate every agent file, then return milestones, tasks, outcomes and settings."""
    schema.validate()
    milestones, tasks = schema.validate_plan("agent/PLAN.yaml")
    outcomes = {item.stem: schema.read_yaml(item) for item in sorted(path("agent/tasks").glob("*.yaml"))}
    return milestones, tasks, outcomes, load("agent/config.yaml")


def active():
    session = load(SESSION)
    if not session["task"]:
        raise Stop("진행 중인 task가 없다. agent.py next를 실행한다.")
    return session


def actionable(task, milestones, outcomes):
    return (
        not task.get("proposed")
        and not milestones[task["milestone"]].get("proposed")
        and task.get("owner", "agent") == "agent"
        and task["id"] not in outcomes
        and all(outcomes.get(dependency, {}).get("status") == "done" for dependency in task["depends_on"])
    )


def retros():
    items = [dict(schema.read_yaml(item), id=item.stem) for item in path("agent/retros").glob("*.yaml")]
    return sorted(items, key=lambda retro: (retro["created_at"], retro["id"]))


def show_phase(session):
    print(f"진행 중: {session['task']} / 단계 {session['phase']}")
    print(f"읽을 문서: agent/core/process/{PHASE_DOCS[session['phase']]}")
    if session["next_action"]:
        print(f"다음 행동: {session['next_action']}")
    for lesson in load("agent/LESSONS.yaml")["lessons"]:
        if session["phase"] in lesson["applies_to"] or "all" in lesson["applies_to"]:
            print(f"적용할 lesson {lesson['id']}: {lesson['rule']}")


def cmd_next(args):
    milestones, tasks, outcomes, _ = context()
    session = load(SESSION)
    if session["task"]:
        show_phase(session)
        return 0
    ready = [task for task in tasks.values() if actionable(task, milestones, outcomes)]
    if ready:
        task = ready[0]
        print(f"다음 task: {task['id']} {task['title']}")
        print(f"최신 main에서 agent/{task['id']} 브랜치를 만든 뒤 실행: python3 agent/core/tools/agent.py start {task['id']}")
        return 0
    print("진행할 수 있는 task가 없다. agent/core/process/80-escalate.md의 세션 보고를 한다.")
    for task_id, outcome in outcomes.items():
        if outcome["status"] == "blocked":
            print(f"- 차단 {task_id}: {outcome['reason']} (해제 조건: {outcome['unblock_when']}, 담당: {outcome['owner']})")
        elif outcome["status"] == "verifying":
            print(f"- 사람 확인 대기 {task_id}: {[key for key, value in outcome['checks'].items() if value == 'pending']}")
    for milestone in milestones.values():
        if milestone.get("proposed"):
            print(f"- 승인 대기 milestone {milestone['id']}: {milestone['outcome']}")
    for task in tasks.values():
        if task["id"] in outcomes:
            continue
        if task.get("proposed") or milestones[task["milestone"]].get("proposed"):
            print(f"- 승인 대기 {task['id']}: proposed 표시를 사람이 제거해야 한다")
        elif task.get("owner") == "human":
            print(f"- 사람 담당 {task['id']}: {task['title']}")
        else:
            waiting = [dependency for dependency in task["depends_on"] if outcomes.get(dependency, {}).get("status") != "done"]
            print(f"- 선행 task 대기 {task['id']}: {waiting}")
    return 0


def cmd_start(args):
    milestones, tasks, outcomes, _ = context()
    session = load(SESSION)
    if session["task"]:
        raise Stop(f"{session['task']}가 진행 중이다. finish, block 또는 drop으로 먼저 끝낸다.")
    task = tasks.get(args.task)
    if task is None or not actionable(task, milestones, outcomes):
        raise Stop(f"{args.task}는 시작할 수 없다: proposed, 사람 담당, 이미 결과가 있음 또는 선행 task 미완료. agent.py next를 따른다.")
    session = dict(copy.deepcopy(schema.IDLE_SESSION), task=args.task, phase="plan", base_commit=head(), started_at=now(),
                   next_action="20-plan.md에 따라 SESSION.yaml steps를 작성한다")
    save(SESSION, session)
    show_phase(session)
    return 0


def cmd_phase(args):
    context()
    session = active()
    if args.phase != "plan" and not session["steps"]:
        raise Stop("steps가 비어 있다. 20-plan.md에 따라 계획을 먼저 SESSION.yaml에 기록한다.")
    session["phase"] = args.phase
    save(SESSION, session)
    show_phase(session)
    return 0


def run_check(check, timeout):
    if check["type"] == "manual":
        return "pending", check["how"]
    if check["type"] == "artifact":
        return ("pass" if path(check["path"]).exists() else "fail"), check["path"]
    try:
        done = subprocess.run(check["run"], shell=True, cwd=schema.ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "fail", f"{timeout}초 제한 초과"
    output = "\n".join((done.stdout + done.stderr).strip().splitlines()[-20:])
    if check["type"] == "command":
        return ("pass" if done.returncode == 0 else "fail"), output
    try:
        value = float(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return "fail", f"{output}\nmetric 출력의 마지막 줄이 숫자가 아니다"
    within = check.get("min", value) <= value <= check.get("max", value)
    return ("pass" if done.returncode == 0 and within else "fail"), f"{output}\nvalue={value}"


def cmd_verify(args):
    _, tasks, _, settings = context()
    session = active()
    if not session["steps"]:
        raise Stop("steps가 비어 있다. 계획과 실행을 먼저 끝낸다.")
    dirty = [name for name in uncommitted() if not is_state(name)]
    if dirty:
        raise Stop(f"commit하지 않은 변경이 있다: {dirty}. 증거는 commit 기준이므로 먼저 commit한다.")
    commit = head()
    checks = [(item["id"], item["check"]) for item in tasks[session["task"]]["acceptance"]]
    checks += [(f"verify:{command['name']}", {"type": "command", "run": command["run"]}) for command in settings["verify"]]
    failed = []
    for key, check in checks:
        result, output = run_check(check, settings["budget"]["check_timeout"])
        session["evidence"][key] = {"result": result, "commit": commit, "output": output}
        if result == "fail":
            session["attempts"][key] = session["attempts"].get(key, 0) + 1
            failed.append(key)
        print(f"{key}: {result}")
    exhausted = [key for key in failed if session["attempts"][key] >= settings["budget"]["verify_attempts"]]
    session["phase"] = "verify"
    if exhausted:
        session["next_action"] = f"{exhausted} 반복 실패: 80-escalate.md에 따라 멈춘다"
    elif failed:
        session["next_action"] = f"{failed} 실패 원인을 고치고 commit한 뒤 다시 verify한다"
    else:
        session["next_action"] = "agent.py finish로 완료를 기록한다 (사용자가 회고를 요청했으면 먼저 agent.py retro --result done)"
    save(SESSION, session)
    print(session["next_action"])
    return 1 if failed else 0


def cmd_retro(args):
    _, tasks, _, _ = context()
    session = active()
    task_id = session["task"]
    numbers = [int(match.group(1)) for item in path("agent/retros").glob("*.yaml") if (match := re.fullmatch(re.escape(task_id) + r"-(\d+)", item.stem))]
    name = f"agent/retros/{task_id}-{max(numbers, default=0) + 1}.yaml"
    outside = [item for item in changed_since(session["base_commit"]) if not is_state(item) and not in_scope(item, tasks[task_id])]
    save(name, {
        "task": task_id,
        "result": args.result,
        "created_at": now(),
        "signals": {"verify_attempts": sum(session["attempts"].values()), "stops": [], "scope_violations": len(outside), "deviations": []},
        "friction": [],
        "lessons_applied": [],
        "share": "NONE",
    })
    session["phase"] = "reflect"
    session["next_action"] = f"50-reflect.md에 따라 {name}를 채운다"
    save(SESSION, session)
    print(f"{name}를 만들었다. 50-reflect.md에 따라 friction, lessons_applied, share를 채운다.")
    tags = sorted({friction["tag"] for retro in retros() for friction in retro["friction"]})
    if tags:
        print(f"기존 tag (같은 원인이면 재사용): {', '.join(tags)}")
    return 0


def in_scope(name, task):
    return any(fnmatch.fnmatch(name, pattern) for pattern in task["scope"])


def check_retro(session, result):
    """A retrospective is written only on request; once started, it must match how the task ends."""
    if session["phase"] != "reflect":
        return
    mine = [retro for retro in retros() if retro["task"] == session["task"] and retro["created_at"] >= session["started_at"]]
    if not mine or mine[-1]["result"] != result:
        raise Stop(f"작성 중인 회고의 result가 {result}가 아니다. agent.py retro --result {result}로 다시 만들고 50-reflect.md에 따라 채운다.")


def cmd_finish(args):
    _, tasks, _, settings = context()
    session = active()
    task = tasks[session["task"]]
    if session["phase"] not in ("verify", "reflect"):
        raise Stop("검증 전이다. agent.py verify를 먼저 실행한다.")
    check_retro(session, "done")
    outside = [item for item in changed_since(session["base_commit"]) if not is_state(item) and not in_scope(item, task)]
    if outside:
        raise Stop(f"scope 밖 변경: {outside}. 되돌리거나 80-escalate.md에 따라 멈춘다.")
    keys = [item["id"] for item in task["acceptance"]] + [f"verify:{command['name']}" for command in settings["verify"]]
    evidence = session["evidence"]
    missing = [key for key in keys if key not in evidence or evidence[key]["result"] == "fail"]
    if missing:
        raise Stop(f"통과하지 않은 검증: {missing}. agent.py verify를 다시 실행한다.")
    commits = {evidence[key]["commit"] for key in keys}
    if len(commits) != 1:
        raise Stop("검증이 서로 다른 commit에서 기록되었다. agent.py verify를 다시 실행한다.")
    commit = commits.pop()
    changed = [item for item in changed_since(commit) if not is_state(item)]
    if changed:
        raise Stop(f"검증 후 바뀐 파일이 있다: {changed}. agent.py verify를 다시 실행한다.")
    checks = {item["id"]: evidence[item["id"]]["result"] for item in task["acceptance"]}
    if "pending" in checks.values():
        outcome = {"status": "verifying", "commit": commit, "checks": checks}
        print(f"{session['task']}: manual 검증이 남아 사람 확인을 기다린다. PR에 확인 방법을 적는다.")
    else:
        outcome = {"status": "done", "commit": commit, "finished_at": now(), "checks": checks}
        print(f"{session['task']}: done")
    save(f"agent/tasks/{session['task']}.yaml", outcome)
    save(SESSION, copy.deepcopy(schema.IDLE_SESSION))
    print("변경을 commit하고 PR을 만든다 (00-session.md).")
    report_scan(settings)
    return 0


def close(args, status):
    context()
    session = active()
    check_retro(session, status)
    outcome = {"status": status, "reason": args.reason}
    if status == "blocked":
        outcome.update(unblock_when=args.unblock_when, owner=args.owner)
    outcome["at"] = now()
    save(f"agent/tasks/{session['task']}.yaml", outcome)
    save(SESSION, copy.deepcopy(schema.IDLE_SESSION))
    print(f"{session['task']}: {status}. 변경을 commit하고 00-session.md에 따라 다음 task로 넘어간다.")
    return 0


def scan(settings):
    """Return improvement candidates and lesson reviews as report lines."""
    history = retros()
    lessons = load("agent/LESSONS.yaml")["lessons"]
    improvement = settings["improvement"]
    lines = []
    tagged = {}
    for retro in history[-improvement["window"]:]:
        for friction in retro["friction"]:
            entry = tagged.setdefault(friction["tag"], {"retros": [], "causes": set(), "high": False})
            entry["retros"].append(retro["id"])
            entry["causes"].add(friction["cause"])
            entry["high"] |= friction["severity"] == "high"
    covered = {lesson["tag"] for lesson in lessons}
    for tag, entry in sorted(tagged.items()):
        repeated = len(set(entry["retros"])) >= improvement["repeat"]
        if tag in covered or not (repeated or entry["high"]):
            continue
        routes = "; ".join(f"{cause}: {ROUTES[cause]}" for cause in sorted(entry["causes"]))
        lines.append(f"개선 후보 {tag} (회고 {', '.join(entry['retros'])}) → {routes}")
    for lesson in lessons:
        after = [retro for retro in history if retro["created_at"] > lesson["introduced_at"]]
        recurred = [retro["id"] for retro in after if any(friction["tag"] == lesson["tag"] for friction in retro["friction"])]
        hits = sum(lesson["id"] in retro["lessons_applied"] for retro in after)
        if lesson["status"] == "trial" and len(after) >= improvement["review_after"]:
            verdict = f"재발({', '.join(recurred)}): 규칙을 고치거나 삭제한다" if recurred else "사용되지 않았다: 삭제한다" if hits == 0 else "효과 있음: adopted로 확정한다"
            lines.append(f"lesson 평가 {lesson['id']} → {verdict}")
        elif lesson["status"] == "adopted" and recurred:
            lines.append(f"lesson 재발 {lesson['id']} ({', '.join(recurred)}) → 규칙을 고치거나 PROCESS 제안으로 올린다")
        elif lesson["status"] == "adopted" and len(after) >= improvement["window"] and hits == 0:
            lines.append(f"lesson 미사용 {lesson['id']} → 삭제한다")
    return lines


def report_scan(settings):
    lines = scan(settings)
    if lines:
        print(f"개선 제안이 필요하다. 60-improve.md를 따른다 (한 세션 최대 {settings['budget']['improvements_per_session']}건):")
        for line in lines:
            print(f"- {line}")
    else:
        print("개선 후보 없음")


def cmd_scan(args):
    _, _, _, settings = context()
    report_scan(settings)
    return 0


def cmd_sync_core(args):
    config = schema.validate_config()
    repository = config["repository"]
    if not repository or not schema.COMMIT.fullmatch(args.ref):
        raise Stop("SHARED_CONFIG.json repository와 전체 commit SHA인 --ref가 필요하다.")
    remote = schema.fetch_core(repository, args.ref)
    if not remote:
        raise Stop(f"{repository}@{args.ref}에 agent-core가 없다.")
    core = path(schema.CORE)
    for name in remote:
        content = schema.gh_api("--method", "GET", f"repos/{repository}/contents/agent-core/{quote(name)}", "-f", f"ref={args.ref}",
                                "-H", "Accept: application/vnd.github.raw+json", raw=True)
        (core / name).parent.mkdir(parents=True, exist_ok=True)
        (core / name).write_bytes(content)
    for name in set(schema.local_core()) - set(remote):
        (core / name).unlink()
    config["process_ref"] = args.ref
    path("SHARED_CONFIG.json").write_text(json.dumps(config, indent=2) + "\n")
    schema.compare_core(remote)
    print(f"agent/core를 {args.ref}로 맞췄다. 테스트와 validate를 실행하고 변경을 검토한 뒤 commit한다 (90-shared.md 6절).")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("next").set_defaults(handler=cmd_next)
    start = commands.add_parser("start")
    start.add_argument("task")
    start.set_defaults(handler=cmd_start)
    phase = commands.add_parser("phase")
    phase.add_argument("phase", choices=schema.PHASES)
    phase.set_defaults(handler=cmd_phase)
    commands.add_parser("verify").set_defaults(handler=cmd_verify)
    retro = commands.add_parser("retro")
    retro.add_argument("--result", choices=sorted(schema.RESULTS), required=True)
    retro.set_defaults(handler=cmd_retro)
    commands.add_parser("finish").set_defaults(handler=cmd_finish)
    block = commands.add_parser("block")
    block.add_argument("--reason", required=True)
    block.add_argument("--unblock-when", required=True)
    block.add_argument("--owner", required=True)
    block.set_defaults(handler=lambda args: close(args, "blocked"))
    drop = commands.add_parser("drop")
    drop.add_argument("--reason", required=True)
    drop.set_defaults(handler=lambda args: close(args, "dropped"))
    commands.add_parser("scan").set_defaults(handler=cmd_scan)
    sync = commands.add_parser("sync-core")
    sync.add_argument("--ref", required=True)
    sync.set_defaults(handler=cmd_sync_core)
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except Stop as exc:
        print(f"중단: {exc}", file=sys.stderr)
        return 2
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"검사 실패: {exc}. 파일을 고친 뒤 다시 실행한다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
