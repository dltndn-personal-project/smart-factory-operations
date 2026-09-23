#!/usr/bin/env python3
"""Validate the Component's agent files: Shared settings, plan, session, task outcomes, retrospectives and lessons."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import yaml


ROOT = Path(__file__).resolve().parents[3]
CORE = "agent/core"
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
COMMIT = re.compile(r"[0-9a-fA-F]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
ISSUE_ID = re.compile(r"ISSUE-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
TAG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
LESSON_ID = re.compile(r"L-\d+\Z")
UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
MAX_BOOTLOADER_LINES = 80

CONFIG_FIELDS = {"repository", "component", "contract_ref", "process_ref"}
TASK_TYPES = {"feature", "fix", "investigate", "plan", "bootstrap", "shared-review", "chore"}
CHECKS = {"command": ({"run"}, set()), "artifact": ({"path"}, set()), "metric": ({"run"}, {"min", "max"}), "manual": ({"how"}, set())}
PHASES = ("plan", "execute", "verify", "reflect")
IDLE_SESSION = {"task": None, "phase": None, "base_commit": None, "started_at": None, "steps": [], "attempts": {}, "evidence": {}, "next_action": None}
OUTCOME_FIELDS = {
    "done": {"status", "commit", "finished_at", "checks"},
    "verifying": {"status", "commit", "checks"},
    "blocked": {"status", "reason", "unblock_when", "owner", "at"},
    "dropped": {"status", "reason", "at"},
}
RESULTS = {"done", "blocked", "dropped"}
CAUSES = {"PLAN", "PROCESS", "DOMAIN_DOC", "ENVIRONMENT", "CONTRACT", "AGENT", "EXTERNAL"}
STOPS = {"ambiguity", "contract", "scope", "irreversible", "unverifiable", "repeated-failure", "budget", "tool"}
SHARE = {"NONE", "COMPONENT_LOCAL", "SHARED"}
RECORD_FIELDS = {"status", "source_revision", "component_revision", "contract_ref", "reason", "evidence"}
# Extra fields each Shared Issue status needs. An Issue without a record is unreviewed.
STATUS_FIELDS = {
    "no_impact": set(),
    "affected": set(),
    "applied": set(),
    "deferred": {"task", "resume_when"},
    "decision_required": {"decision_owner", "question"},
}
NEEDS_EVIDENCE = {"no_impact", "affected", "applied"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def mapping_with_unique_keys(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        require(key not in result, f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping_with_unique_keys)


def read_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_pairs)


def read_yaml(path):
    return yaml.load(path.read_text(), Loader=UniqueKeyLoader)


def nonempty(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label}: expected nonempty text")


def optional_text(value, label):
    require(value is None or isinstance(value, str) and bool(value.strip()), f"{label}: expected null or nonempty text")


def string_list(value, label, pattern=None):
    require(isinstance(value, list), f"{label}: expected an array")
    for item in value:
        nonempty(item, label)
        require(pattern is None or pattern.fullmatch(item), f"{label}: invalid item {item}")


def count(value, label, minimum=0):
    require(type(value) is int and value >= minimum, f"{label}: expected an integer >= {minimum}")


def utc(value, label):
    require(isinstance(value, str) and UTC.fullmatch(value), f"{label}: expected a quoted UTC timestamp like 2026-01-01T00:00:00Z")


def fields(value, label, required, optional=()):
    require(isinstance(value, dict), f"{label}: expected a mapping")
    keys = set(value)
    expected = f"{label}: expected fields {sorted(required)}" + (f" and optionally {sorted(optional)}" if optional else "")
    require(set(required) <= keys <= set(required) | set(optional), expected)
    return value


def unique_name(value, label, seen):
    require(isinstance(value, str) and NAME.fullmatch(value), f"{label}: id must start with a letter and use letters, digits, '.', '_' or '-'")
    require(value not in seen, f"{label}: duplicate id {value}")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def gh_api(*args, raw=False):
    result = subprocess.run(["gh", "api", *args], capture_output=True, check=False)
    require(result.returncode == 0, f"Shared lookup failed and is not an empty result: {result.stderr.decode().strip()}")
    return result.stdout if raw else result.stdout.decode().strip()


def validate_config():
    config = fields(read_json(ROOT / "SHARED_CONFIG.json"), "SHARED_CONFIG.json", CONFIG_FIELDS)
    repository = config["repository"]
    require(
        repository is None or isinstance(repository, str) and REPOSITORY.fullmatch(repository) and not repository.endswith(".git"),
        "SHARED_CONFIG.json: repository must be null or owner/repository without URL or .git",
    )
    component = config["component"]
    require(isinstance(component, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", component), "SHARED_CONFIG.json: component must be a name without spaces")
    for field in ("contract_ref", "process_ref"):
        value = config[field]
        require(value is None or isinstance(value, str) and COMMIT.fullmatch(value), f"SHARED_CONFIG.json: {field} must be null or a full commit SHA")
    return config


def validate_settings(name="agent/config.yaml"):
    settings = fields(read_yaml(ROOT / name), name, {"verify", "budget", "improvement"})
    require(isinstance(settings["verify"], list), f"{name}: verify must be an array")
    names = set()
    for position, command in enumerate(settings["verify"]):
        label = f"{name}: verify[{position}]"
        fields(command, label, {"name", "run"})
        unique_name(command["name"], label, names)
        names.add(command["name"])
        nonempty(command["run"], f"{label}: run")
    budget = fields(settings["budget"], f"{name}: budget", {"verify_attempts", "tasks_per_session", "improvements_per_session", "check_timeout"})
    improvement = fields(settings["improvement"], f"{name}: improvement", {"window", "repeat", "review_after", "max_lessons"})
    for group, values in (("budget", budget), ("improvement", improvement)):
        for field, value in values.items():
            count(value, f"{name}: {group}.{field}", 1)
    return settings


def validate_check(check, label):
    require(isinstance(check, dict) and check.get("type") in CHECKS, f"{label}: type must be one of {sorted(CHECKS)}")
    required, optional = CHECKS[check["type"]]
    fields(check, label, required | {"type"}, optional)
    for field in required:
        nonempty(check[field], f"{label}.{field}")
    if check["type"] == "artifact":
        require(not Path(check["path"]).is_absolute() and ".." not in Path(check["path"]).parts, f"{label}: path must stay inside the Component")
    if check["type"] == "metric":
        bounds = [check[field] for field in ("min", "max") if field in check]
        require(bounds and all(type(bound) in (int, float) for bound in bounds), f"{label}: metric needs a numeric min or max")


def validate_plan(name):
    plan = fields(read_yaml(ROOT / name), name, {"milestones", "tasks"})
    require(isinstance(plan["milestones"], list) and isinstance(plan["tasks"], list), f"{name}: milestones and tasks must be arrays")
    milestones = {}
    for position, milestone in enumerate(plan["milestones"]):
        label = f"{name}: milestones[{position}]"
        fields(milestone, label, {"id", "outcome", "exit_criteria"}, {"proposed"})
        unique_name(milestone["id"], label, milestones)
        nonempty(milestone["outcome"], f"{label}: outcome")
        string_list(milestone["exit_criteria"], f"{label}: exit_criteria")
        require(milestone["exit_criteria"], f"{label}: exit_criteria must not be empty")
        require(milestone.get("proposed", True) is True, f"{label}: proposed must be true or absent")
        milestones[milestone["id"]] = milestone

    tasks = {}
    for position, task in enumerate(plan["tasks"]):
        fields(task, f"{name}: tasks[{position}]", {"id", "milestone", "type", "title", "why", "depends_on", "scope", "acceptance", "size"}, {"contract", "owner", "proposed"})
        unique_name(task["id"], f"{name}: tasks[{position}]", tasks)
        label = f"{name}: {task['id']}"
        require(task["milestone"] in milestones, f"{label}: unknown milestone {task['milestone']}")
        require(task["type"] in TASK_TYPES, f"{label}: type must be one of {sorted(TASK_TYPES)}")
        nonempty(task["title"], f"{label}: title")
        nonempty(task["why"], f"{label}: why")
        string_list(task["depends_on"], f"{label}: depends_on")
        string_list(task.get("contract", []), f"{label}: contract")
        string_list(task["scope"], f"{label}: scope")
        require(task.get("owner", "agent") in ("agent", "human"), f"{label}: owner must be agent or human")
        require(task["size"] in ("S", "M", "L"), f"{label}: size must be S, M or L")
        require(task.get("proposed", True) is True, f"{label}: proposed must be true or absent")
        require(isinstance(task["acceptance"], list), f"{label}: acceptance must be an array")
        checks = set()
        for index, item in enumerate(task["acceptance"]):
            item_label = f"{label}: acceptance[{index}]"
            fields(item, item_label, {"id", "text", "check"})
            unique_name(item["id"], item_label, checks)
            checks.add(item["id"])
            nonempty(item["text"], f"{item_label}: text")
            validate_check(item["check"], f"{item_label}: check")
        if not (task.get("proposed") or milestones[task["milestone"]].get("proposed")):
            # Definition of Ready: an approved task is verifiable, bounded and small.
            require(task["acceptance"] and task["scope"], f"{label}: approved tasks need acceptance and scope")
            require(task["size"] != "L", f"{label}: size L must be split before approval")
        tasks[task["id"]] = task

    for task in tasks.values():
        for dependency in task["depends_on"]:
            require(dependency in tasks and dependency != task["id"], f"{name}: {task['id']} depends on unknown task {dependency}")
    visiting, visited = set(), set()

    def visit(task_id):
        if task_id in visited:
            return
        require(task_id not in visiting, f"{name}: dependency cycle through {task_id}")
        visiting.add(task_id)
        for dependency in tasks[task_id]["depends_on"]:
            visit(dependency)
        visiting.discard(task_id)
        visited.add(task_id)

    for task_id in tasks:
        visit(task_id)
    return milestones, tasks


def validate_session(name, tasks):
    session = fields(read_yaml(ROOT / name), name, set(IDLE_SESSION))
    if session["task"] is None:
        require(session == IDLE_SESSION, f"{name}: an idle session must have every other field empty")
        return session
    require(session["task"] in tasks, f"{name}: unknown task {session['task']}")
    require(session["phase"] in PHASES, f"{name}: phase must be one of {list(PHASES)}")
    require(isinstance(session["base_commit"], str) and COMMIT.fullmatch(session["base_commit"]), f"{name}: base_commit must be a full commit SHA")
    utc(session["started_at"], f"{name}: started_at")
    optional_text(session["next_action"], f"{name}: next_action")
    require(isinstance(session["steps"], list), f"{name}: steps must be an array")
    for position, step in enumerate(session["steps"]):
        label = f"{name}: steps[{position}]"
        fields(step, label, {"do", "check", "done"}, {"note"})
        nonempty(step["do"], f"{label}: do")
        nonempty(step["check"], f"{label}: check")
        require(type(step["done"]) is bool, f"{label}: done must be true or false")
        optional_text(step.get("note"), f"{label}: note")
    require(session["phase"] == "plan" or session["steps"], f"{name}: record steps before leaving the plan phase")
    require(isinstance(session["attempts"], dict), f"{name}: attempts must be a mapping")
    for key, value in session["attempts"].items():
        nonempty(key, f"{name}: attempts key")
        count(value, f"{name}: attempts.{key}")
    require(isinstance(session["evidence"], dict), f"{name}: evidence must be a mapping")
    for key, entry in session["evidence"].items():
        label = f"{name}: evidence.{key}"
        fields(entry, label, {"result", "commit", "output"})
        require(entry["result"] in ("pass", "fail", "pending"), f"{label}: result must be pass, fail or pending")
        require(isinstance(entry["commit"], str) and COMMIT.fullmatch(entry["commit"]), f"{label}: commit must be a full commit SHA")
        require(isinstance(entry["output"], str), f"{label}: output must be text")
    return session


def validate_outcome(name, outcome, task):
    require(isinstance(outcome, dict) and outcome.get("status") in OUTCOME_FIELDS, f"{name}: status must be one of {sorted(OUTCOME_FIELDS)}")
    status = outcome["status"]
    fields(outcome, name, OUTCOME_FIELDS[status])
    if status in ("done", "verifying"):
        require(isinstance(outcome["commit"], str) and COMMIT.fullmatch(outcome["commit"]), f"{name}: commit must be a full commit SHA")
        checks = outcome["checks"]
        require(isinstance(checks, dict) and set(checks) == {item["id"] for item in task["acceptance"]}, f"{name}: checks must cover every acceptance")
        allowed = {"pass"} if status == "done" else {"pass", "pending"}
        require(set(checks.values()) <= allowed, f"{name}: {status} checks must be {' or '.join(sorted(allowed))}")
        if status == "done":
            utc(outcome["finished_at"], f"{name}: finished_at")
        else:
            require("pending" in checks.values(), f"{name}: verifying needs a pending manual check")
    else:
        nonempty(outcome["reason"], f"{name}: reason")
        utc(outcome["at"], f"{name}: at")
        if status == "blocked":
            nonempty(outcome["unblock_when"], f"{name}: unblock_when")
            nonempty(outcome["owner"], f"{name}: owner")


def validate_retro(name, retro, tasks):
    fields(retro, name, {"task", "result", "created_at", "signals", "friction", "lessons_applied", "share"})
    require(retro["task"] in tasks, f"{name}: unknown task {retro['task']}")
    require(retro["result"] in RESULTS, f"{name}: result must be one of {sorted(RESULTS)}")
    utc(retro["created_at"], f"{name}: created_at")
    signals = fields(retro["signals"], f"{name}: signals", {"verify_attempts", "stops", "scope_violations", "deviations"})
    count(signals["verify_attempts"], f"{name}: signals.verify_attempts")
    count(signals["scope_violations"], f"{name}: signals.scope_violations")
    string_list(signals["stops"], f"{name}: signals.stops")
    require(set(signals["stops"]) <= STOPS, f"{name}: signals.stops must use {sorted(STOPS)}")
    string_list(signals["deviations"], f"{name}: signals.deviations")
    require(isinstance(retro["friction"], list), f"{name}: friction must be an array")
    for position, friction in enumerate(retro["friction"]):
        label = f"{name}: friction[{position}]"
        fields(friction, label, {"tag", "cause", "severity", "what", "evidence", "proposal", "doc"})
        require(isinstance(friction["tag"], str) and TAG.fullmatch(friction["tag"]), f"{label}: tag must be kebab-case")
        require(friction["cause"] in CAUSES, f"{label}: cause must be one of {sorted(CAUSES)}")
        require(friction["severity"] in ("low", "high"), f"{label}: severity must be low or high")
        nonempty(friction["what"], f"{label}: what")
        string_list(friction["evidence"], f"{label}: evidence")
        require(friction["evidence"], f"{label}: evidence must not be empty")
        optional_text(friction["proposal"], f"{label}: proposal")
        optional_text(friction["doc"], f"{label}: doc")
        require(friction["cause"] != "PROCESS" or (friction["doc"] or "").startswith(f"{CORE}/"), f"{label}: PROCESS friction must name the {CORE} file in doc")
    string_list(retro["lessons_applied"], f"{name}: lessons_applied", LESSON_ID)
    require(retro["share"] in SHARE, f"{name}: share must be one of {sorted(SHARE)}")


def validate_lessons(name, settings, retros):
    data = fields(read_yaml(ROOT / name), name, {"lessons"})
    lessons = data["lessons"]
    require(isinstance(lessons, list), f"{name}: lessons must be an array")
    require(len(lessons) <= settings["improvement"]["max_lessons"], f"{name}: more than improvement.max_lessons lessons; merge or remove some first")
    seen = set()
    for position, lesson in enumerate(lessons):
        label = f"{name}: lessons[{position}]"
        fields(lesson, label, {"id", "tag", "rule", "applies_to", "source", "status", "introduced_at"})
        require(isinstance(lesson["id"], str) and LESSON_ID.fullmatch(lesson["id"]) and lesson["id"] not in seen, f"{label}: id must be a unique L-<number>")
        seen.add(lesson["id"])
        require(isinstance(lesson["tag"], str) and TAG.fullmatch(lesson["tag"]), f"{label}: tag must be kebab-case")
        nonempty(lesson["rule"], f"{label}: rule")
        string_list(lesson["applies_to"], f"{label}: applies_to")
        require(lesson["applies_to"] and set(lesson["applies_to"]) <= set(PHASES) | {"all"}, f"{label}: applies_to must use {list(PHASES)} or all")
        require(lesson["status"] in ("trial", "adopted"), f"{label}: status must be trial or adopted")
        utc(lesson["introduced_at"], f"{label}: introduced_at")
        string_list(lesson["source"], f"{label}: source")
        # A lesson must come from repeated friction or one high-severity incident.
        tagged = []
        for source in lesson["source"]:
            require(source in retros, f"{label}: unknown source retrospective {source}")
            tagged += [friction for friction in retros[source]["friction"] if friction["tag"] == lesson["tag"]]
        sources = sum(any(f["tag"] == lesson["tag"] for f in retros[source]["friction"]) for source in set(lesson["source"]))
        require(
            sources >= settings["improvement"]["repeat"] or any(friction["severity"] == "high" for friction in tagged),
            f"{label}: needs {settings['improvement']['repeat']} source retrospectives with tag {lesson['tag']} or one high-severity friction",
        )


def validate_workspace(prefix, settings):
    """Validate the plan, session, outcomes, retrospectives and lessons stored under prefix."""
    _, tasks = validate_plan(f"{prefix}/PLAN.yaml")
    validate_session(f"{prefix}/SESSION.yaml", tasks)
    for path in sorted((ROOT / prefix / "tasks").glob("*.yaml")):
        name = path.relative_to(ROOT).as_posix()
        require(path.stem in tasks, f"{name}: unknown task")
        validate_outcome(name, read_yaml(path), tasks[path.stem])
    retros = {}
    for path in sorted((ROOT / prefix / "retros").glob("*.yaml")):
        name = path.relative_to(ROOT).as_posix()
        retro = read_yaml(path)
        validate_retro(name, retro, tasks)
        require(re.fullmatch(re.escape(retro["task"]) + r"-\d+", path.stem), f"{name}: file name must be <task>-<n>.yaml")
        retros[path.stem] = retro
    validate_lessons(f"{prefix}/LESSONS.yaml", settings, retros)
    return tasks, retros


def revision(value, label, sample):
    nonempty(value, label)
    require(sample or COMMIT.fullmatch(value), f"{label}: expected a full commit SHA")


def validate_issue_records(name, sample=False):
    data = read_yaml(ROOT / name)
    require(isinstance(data, dict) and set(data) == {"issues"} and isinstance(data["issues"], dict), f"{name}: expected an issues mapping")
    for issue_id, record in data["issues"].items():
        label = f"{name}: {issue_id}"
        if sample:
            require(isinstance(issue_id, str) and issue_id.startswith("SAMPLE-"), f"{label}: sample keys must start with SAMPLE-")
        else:
            require(isinstance(issue_id, str) and ISSUE_ID.fullmatch(issue_id), f"{label}: key must be a Shared Issue ID")
        require(isinstance(record, dict), f"{label}: record must be a mapping")
        status = record.get("status")
        require(status in STATUS_FIELDS, f"{label}: status must be one of {sorted(STATUS_FIELDS)}; unreviewed Issues have no record")
        expected = RECORD_FIELDS | STATUS_FIELDS[status]
        require(set(record) == expected, f"{label}: expected fields {sorted(expected)}")
        revision(record["source_revision"], f"{label}: source_revision", sample)
        revision(record["component_revision"], f"{label}: component_revision", sample)
        if record["contract_ref"] is not None:
            revision(record["contract_ref"], f"{label}: contract_ref", sample)
        nonempty(record["reason"], f"{label}: reason")
        string_list(record["evidence"], f"{label}: evidence")
        require(status not in NEEDS_EVIDENCE or record["evidence"], f"{label}: {status} needs evidence")
        for field in STATUS_FIELDS[status]:
            nonempty(record[field], f"{label}: {field}")
    return data["issues"]


def parse_index(text, name):
    value = json.loads(text, object_pairs_hook=unique_pairs)
    require(isinstance(value, dict) and isinstance(value.get("issues"), list), f"{name}: expected an issues array")
    ids = []
    for position, entry in enumerate(value["issues"]):
        require(isinstance(entry, dict) and isinstance(entry.get("issue_id"), str), f"{name}[{position}]: missing issue_id")
        ids.append(entry["issue_id"])
    require(len(ids) == len(set(ids)), f"{name}: duplicate Issue ID")
    return ids


def fetch_index(repository):
    branch = gh_api(f"repos/{repository}", "--jq", ".default_branch")
    sha = gh_api(f"repos/{repository}/commits/{quote(branch, safe='')}", "--jq", ".sha")
    text = gh_api("--method", "GET", f"repos/{repository}/contents/issues/index.json", "-f", f"ref={sha}", "-H", "Accept: application/vnd.github.raw+json")
    return parse_index(text, f"{repository}@{sha}:issues/index.json")


def check_order(records, index_ids):
    unknown = sorted(set(records) - set(index_ids))
    require(not unknown, f"SHARED_ISSUE_STATUS.yaml: Issues missing from the Shared index: {unknown}")
    # Records must cover a prefix of the index: the oldest unreviewed Issue comes first.
    for issue_id in index_ids[: len(records)]:
        require(issue_id in records, f"SHARED_ISSUE_STATUS.yaml: review {issue_id} before later Issues")


def local_core():
    listed = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", CORE)
    require(listed.returncode == 0, f"could not list {CORE}")
    files = {}
    for name in filter(None, listed.stdout.decode().split("\0")):
        path = ROOT / name
        if path.is_file():
            hashed = git("hash-object", "--", name)
            require(hashed.returncode == 0, f"could not hash {name}")
            files[path.relative_to(ROOT / CORE).as_posix()] = hashed.stdout.decode().strip()
    return files


def fetch_core(repository, ref):
    tree = json.loads(gh_api(f"repos/{repository}/git/trees/{ref}?recursive=1"))
    require(not tree.get("truncated"), "Shared tree listing is truncated")
    prefix = "agent-core/"
    return {entry["path"][len(prefix):]: entry["sha"] for entry in tree["tree"] if entry["type"] == "blob" and entry["path"].startswith(prefix)}


def compare_core(remote):
    local = local_core()
    differ = sorted(path for path in set(local) | set(remote) if local.get(path) != remote.get(path))
    require(not differ, f"{CORE} differs from Shared agent-core at process_ref: {differ}. Adopt changes with agent.py sync-core instead of editing locally")


def validate_composition(config, base):
    path = ROOT / "COMPOSITION.json"
    if path.exists():
        composition = read_json(path)
        require(isinstance(composition, dict) and set(composition) == {"shared_contract", "components"}, "COMPOSITION.json: expected shared_contract and components")
        contract = composition["shared_contract"]
        require(isinstance(contract, dict) and set(contract) == {"repository", "revision"}, "COMPOSITION.json: shared_contract needs repository and revision")
        require(isinstance(contract["repository"], str) and REPOSITORY.fullmatch(contract["repository"]), "COMPOSITION.json: invalid shared_contract.repository")
        require(config["repository"] in (None, contract["repository"]), "COMPOSITION.json: shared_contract.repository differs from SHARED_CONFIG.json")
        require(isinstance(contract["revision"], str) and COMMIT.fullmatch(contract["revision"]), "COMPOSITION.json: shared_contract.revision must be a full commit SHA")
        components = composition["components"]
        require(isinstance(components, list) and components, "COMPOSITION.json: components must be a nonempty array")
        names = set()
        for position, component in enumerate(components):
            label = f"COMPOSITION.json: components[{position}]"
            require(isinstance(component, dict) and set(component) == {"name", "repository", "revision"}, f"{label}: expected name, repository and revision")
            nonempty(component["name"], f"{label}: name")
            require(component["name"] not in names, f"{label}: duplicate name")
            names.add(component["name"])
            require(isinstance(component["repository"], str) and REPOSITORY.fullmatch(component["repository"]), f"{label}: invalid repository")
            value = component["revision"]
            require(isinstance(value, str) and (COMMIT.fullmatch(value) or DIGEST.fullmatch(value)), f"{label}: revision must be a full commit SHA or sha256 digest")
        require((ROOT / "VALIDATION.md").is_file(), "COMPOSITION.json needs VALIDATION.md")
    if base:
        changed = git("diff", "--name-only", base, "--", "COMPOSITION.json", "VALIDATION.md")
        require(changed.returncode == 0, "could not inspect composition changes")
        changed_files = set(changed.stdout.decode().splitlines())
        require("COMPOSITION.json" not in changed_files or "VALIDATION.md" in changed_files, "COMPOSITION.json changed: record the new validation in VALIDATION.md")


def validate_history(base):
    listed = git("ls-tree", "-r", "--name-only", base, "--", "agent/retros")
    require(listed.returncode == 0, "could not list merged retrospectives")
    for name in listed.stdout.decode().splitlines():
        current = ROOT / name
        require(current.is_file() and current.read_bytes() == git("show", f"{base}:{name}").stdout, f"{name}: merged retrospectives are immutable")


def validate(base=None, index_ids=None, remote=False):
    """Run every check; return notes about checks that were skipped."""
    if base:
        require(COMMIT.fullmatch(base), "--base must be a full commit SHA")
        require(git("merge-base", "--is-ancestor", base, "HEAD").returncode == 0, "--base must be an ancestor of HEAD")
    bootloader = ROOT / "AGENTS.md"
    require(bootloader.is_file() and len(bootloader.read_text().splitlines()) <= MAX_BOOTLOADER_LINES, f"AGENTS.md must exist and stay within {MAX_BOOTLOADER_LINES} lines")
    config = validate_config()
    settings = validate_settings()
    validate_workspace("agent", settings)
    records = validate_issue_records("SHARED_ISSUE_STATUS.yaml")
    examples = ROOT / CORE / "examples"
    if examples.is_dir():
        validate_workspace(f"{CORE}/examples", settings)
        validate_issue_records(f"{CORE}/examples/SHARED_ISSUE_STATUS.yaml", sample=True)
    require(not records or config["repository"], "SHARED_ISSUE_STATUS.yaml: records need SHARED_CONFIG.json repository")
    notes = []
    if remote and config["repository"]:
        if index_ids is None:
            index_ids = fetch_index(config["repository"])
        if config["process_ref"]:
            compare_core(fetch_core(config["repository"], config["process_ref"]))
        else:
            notes.append("process_ref is null: agent/core not compared")
    elif not remote:
        notes.append(f"{CORE} not compared with Shared: use --remote")
    if index_ids is not None:
        check_order(records, index_ids)
    else:
        notes.append("Issue order not checked: Shared not connected or --remote not given")
    validate_composition(config, base)
    if base:
        validate_history(base)
    return notes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="base commit SHA: merged retrospectives stay unchanged and a changed COMPOSITION.json needs VALIDATION.md")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--remote", action="store_true", help="compare the Issue order and agent/core with Shared via gh api")
    source.add_argument("--index", help="check the Issue order against a local copy of issues/index.json")
    args = parser.parse_args()
    try:
        index_ids = parse_index(Path(args.index).read_text(), args.index) if args.index else None
        notes = validate(None if not args.base or set(args.base) == {"0"} else args.base, index_ids, args.remote)
    except (ValueError, OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"Component validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print("Component validation passed" + (f" ({'; '.join(notes)})" if notes else ""))
