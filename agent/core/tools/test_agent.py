"""Regression checks for the plan-driven task loop."""

import contextlib
import io
import unittest

import agent
import auto_approval
from testkit import Component


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.component = Component()

    def tearDown(self):
        self.component.close()

    def run_agent(self, *argv):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = agent.main(list(argv))
        return code, output.getvalue() + errors.getvalue()

    def plan_steps(self):
        session = self.component.read_yaml(agent.SESSION)
        session["steps"] = [{"do": "create the result", "check": "A1", "done": True}]
        self.component.write_yaml(agent.SESSION, session)

    def test_next_offers_the_first_ready_task(self):
        self.component.plan(
            Component.task("T1", proposed=True),
            Component.task("T2"),
            Component.task("T3", depends_on=["T2"]),
        )
        self.component.commit()
        code, output = self.run_agent("next")
        self.assertEqual(code, 0)
        self.assertIn("다음 task: T2", output)

        self.assertEqual(self.run_agent("start", "T3")[0], 2)
        self.assertEqual(self.run_agent("start", "T2")[0], 0)
        self.assertEqual(self.run_agent("start", "T2")[0], 2)
        self.assertIn("진행 중: T2", self.run_agent("next")[1])

    def test_task_passes_verify_and_finish_gates_without_a_retrospective(self):
        self.component.plan(Component.task("T1"))
        self.component.commit()
        self.run_agent("start", "T1")
        self.plan_steps()
        self.component.write("src/done.txt")
        self.assertEqual(self.run_agent("finish")[0], 2)  # not verified yet
        self.assertEqual(self.run_agent("verify")[0], 2)  # uncommitted work is refused
        self.component.commit()

        code, output = self.run_agent("verify")
        self.assertEqual(code, 0, output)
        code, output = self.run_agent("finish")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.component.read_yaml("agent/tasks/T1.yaml")["status"], "done")
        self.assertIsNone(self.component.read_yaml(agent.SESSION)["task"])
        self.assertEqual(list((self.component.root / "agent/retros").glob("*.yaml")), [])

    def test_a_requested_retrospective_must_match_how_the_task_ends(self):
        self.component.plan(Component.task("T1"))
        self.component.commit()
        self.run_agent("start", "T1")
        self.plan_steps()
        self.component.write("src/done.txt")
        self.component.commit()
        self.run_agent("verify")
        self.assertEqual(self.run_agent("retro", "--result", "done")[0], 0)
        self.assertEqual(self.run_agent("drop", "--reason", "not needed")[0], 2)  # the retrospective says done
        code, output = self.run_agent("finish")
        self.assertEqual(code, 0, output)
        self.assertTrue((self.component.root / "agent/retros/T1-1.yaml").exists())

    def test_finish_rejects_changes_outside_the_scope(self):
        self.component.plan(Component.task("T1"))
        self.component.commit()
        self.run_agent("start", "T1")
        self.plan_steps()
        self.component.write("src/done.txt")
        self.component.write("other/config.txt")
        self.component.commit()
        self.run_agent("verify")
        self.run_agent("retro", "--result", "done")
        code, output = self.run_agent("finish")
        self.assertEqual(code, 2)
        self.assertIn("other/config.txt", output)

    def test_repeated_failure_leads_to_a_blocked_task(self):
        self.component.plan(Component.task("T1"), Component.task("T2"))
        self.component.commit()
        self.run_agent("start", "T1")
        self.plan_steps()
        self.run_agent("verify")
        code, output = self.run_agent("verify")
        self.assertEqual(code, 1)
        self.assertIn("80-escalate", output)
        self.assertEqual(self.run_agent("block", "--reason", "no fixture", "--unblock-when", "fixture exists", "--owner", "human")[0], 0)
        self.assertEqual(self.component.read_yaml("agent/tasks/T1.yaml")["status"], "blocked")
        self.assertIn("다음 task: T2", self.run_agent("next")[1])

    def test_scan_finds_repeats_and_reviews_lessons(self):
        self.component.plan(Component.task("T1"))
        self.component.retro("T1-1", "T1", "2026-01-01T00:00:00Z", ["db-down"])
        self.component.retro("T1-2", "T1", "2026-01-02T00:00:00Z", ["db-down"])
        self.assertIn("개선 후보 db-down", self.run_agent("scan")[1])

        lesson = {"id": "L-1", "tag": "db-down", "rule": "Start the database first", "applies_to": ["verify"],
                  "source": ["T1-1", "T1-2"], "status": "trial", "introduced_at": "2026-01-03T00:00:00Z"}
        self.component.write_yaml("agent/LESSONS.yaml", {"lessons": [lesson]})
        self.component.retro("T1-3", "T1", "2026-01-04T00:00:00Z", applied=["L-1"])
        self.component.retro("T1-4", "T1", "2026-01-05T00:00:00Z")
        output = self.run_agent("scan")[1]
        self.assertNotIn("개선 후보 db-down", output)
        self.assertIn("lesson 평가 L-1 → 효과 있음", output)

    def test_only_learning_changes_are_approved_automatically(self):
        self.component.write(".github/CODEOWNERS", "* @acme/owners\n/agent/LESSONS.yaml\n/agent/retros/\n")
        self.component.plan(Component.task("T1"))
        base = self.component.commit()
        self.component.retro("T1-1", "T1", "2026-01-01T00:00:00Z", ["db-down"], severity="high")
        self.component.write_yaml("agent/LESSONS.yaml", {"lessons": [{
            "id": "L-1", "tag": "db-down", "rule": "Start the database first", "applies_to": ["verify"],
            "source": ["T1-1"], "status": "trial", "introduced_at": "2026-01-02T00:00:00Z"}]})
        self.component.commit()
        self.assertEqual(auto_approval.problems(base), [])

        self.component.write("src/feature.txt")
        self.component.commit()
        self.assertEqual(auto_approval.problems(base), ["src/feature.txt: only agent/LESSONS.yaml and new retrospectives are approved automatically"])


if __name__ == "__main__":
    unittest.main()
