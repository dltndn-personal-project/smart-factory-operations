"""A minimal Component in a temporary Git repository, shared by the tool tests."""

import copy
import json
import subprocess
import tempfile
from pathlib import Path

import yaml

import validate as schema


SHA = "a" * 40
SETTINGS = {
    "verify": [],
    "budget": {"verify_attempts": 2, "tasks_per_session": 5, "improvements_per_session": 2, "check_timeout": 60},
    "improvement": {"window": 10, "repeat": 2, "review_after": 2, "max_lessons": 20},
}


class Component:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.original_root = schema.ROOT
        schema.ROOT = self.root
        (self.root / "AGENTS.md").write_text("# test\n")
        self.write_json("SHARED_CONFIG.json", {"repository": "acme/shared-contract", "component": "consumer", "contract_ref": SHA, "process_ref": None})
        self.write_yaml("SHARED_ISSUE_STATUS.yaml", {"issues": {}})
        self.write_yaml("agent/config.yaml", copy.deepcopy(SETTINGS))
        self.write_yaml("agent/SESSION.yaml", copy.deepcopy(schema.IDLE_SESSION))
        self.write_yaml("agent/LESSONS.yaml", {"lessons": []})
        self.plan()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.commit("base")

    def close(self):
        schema.ROOT = self.original_root
        self.temporary.cleanup()

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, text=True)

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("commit", "-qm", message, "--allow-empty")
        return self.git("rev-parse", "HEAD").strip()

    def write_json(self, name, value):
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(json.dumps(value))

    def write_yaml(self, name, value):
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False))

    def read_yaml(self, name):
        return yaml.safe_load((self.root / name).read_text())

    def write(self, name, text="x\n"):
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(text)

    @staticmethod
    def task(task_id, **extra):
        return {
            "id": task_id,
            "milestone": "M1",
            "type": "feature",
            "title": f"Build {task_id}",
            "why": "needed",
            "depends_on": [],
            "scope": ["src/**"],
            "acceptance": [{"id": "A1", "text": "result exists", "check": {"type": "command", "run": "test -f src/done.txt"}}],
            "size": "S",
        } | extra

    def plan(self, *tasks):
        self.write_yaml("agent/PLAN.yaml", {"milestones": [{"id": "M1", "outcome": "Deliver", "exit_criteria": ["works"]}], "tasks": list(tasks)})

    def retro(self, name, task, created_at, tags=(), severity="low", applied=()):
        friction = [{"tag": tag, "cause": "AGENT", "severity": severity, "what": "slowed down", "evidence": ["log"], "proposal": None, "doc": None} for tag in tags]
        self.write_yaml(f"agent/retros/{name}.yaml", {
            "task": task,
            "result": "done",
            "created_at": created_at,
            "signals": {"verify_attempts": 0, "stops": [], "scope_violations": 0, "deviations": []},
            "friction": friction,
            "lessons_applied": list(applied),
            "share": "NONE",
        })
