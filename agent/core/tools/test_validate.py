"""Regression checks for the Component validator."""

import unittest
from uuid import uuid4

import validate as validator
from testkit import SHA, Component


class ComponentValidationTests(unittest.TestCase):
    def setUp(self):
        self.component = Component()
        self.ids = [f"ISSUE-{uuid4()}" for _ in range(3)]

    def tearDown(self):
        self.component.close()

    def record(self, status="no_impact", **extra):
        return {
            "status": status,
            "source_revision": SHA,
            "component_revision": SHA,
            "contract_ref": SHA,
            "reason": "Does not read result files",
            "evidence": ["src/reader.py has no file access"],
        } | extra

    def write_records(self, records):
        self.component.write_yaml("SHARED_ISSUE_STATUS.yaml", {"issues": records})

    def test_records_must_cover_the_oldest_issues_first(self):
        self.write_records({self.ids[1]: self.record()})
        with self.assertRaisesRegex(ValueError, f"review {self.ids[0]}"):
            validator.validate(index_ids=self.ids)

        self.write_records({self.ids[0]: self.record(), self.ids[1]: self.record()})
        validator.validate(index_ids=self.ids)

        self.write_records({self.ids[0]: self.record(), f"ISSUE-{uuid4()}": self.record()})
        with self.assertRaisesRegex(ValueError, "missing from the Shared index"):
            validator.validate(index_ids=self.ids)

    def test_record_fields_follow_the_status(self):
        invalid = [
            self.record("unreviewed"),
            self.record("applied", evidence=[]),
            self.record("deferred", task="TASK-1"),
            self.record(issue_id=self.ids[0]),
            self.record(source_revision="main"),
        ]
        for record in invalid:
            self.write_records({self.ids[0]: record})
            with self.assertRaises(ValueError):
                validator.validate()

        self.write_records({self.ids[0]: self.record("deferred", evidence=[], task="TASK-1", resume_when="next contract")})
        validator.validate()

    def test_records_need_a_connected_repository(self):
        self.component.write_json("SHARED_CONFIG.json", {"repository": None, "component": "consumer", "contract_ref": None, "process_ref": None})
        validator.validate()
        self.write_records({self.ids[0]: self.record()})
        with self.assertRaisesRegex(ValueError, "repository"):
            validator.validate()

    def test_composition_change_needs_a_validation_record(self):
        composition = {
            "shared_contract": {"repository": "acme/shared-contract", "revision": SHA},
            "components": [{"name": "producer", "repository": "acme/producer", "revision": "sha256:" + "b" * 64}],
        }
        self.component.write_json("COMPOSITION.json", composition)
        self.component.write("VALIDATION.md", "passed\n")
        base = self.component.commit()

        composition["components"][0]["revision"] = "c" * 40
        self.component.write_json("COMPOSITION.json", composition)
        with self.assertRaisesRegex(ValueError, "VALIDATION.md"):
            validator.validate(base)

        self.component.write("VALIDATION.md", "passed again\n")
        validator.validate(base)

    def test_approved_tasks_must_meet_the_definition_of_ready(self):
        self.component.plan(Component.task("T1", size="L"))
        with self.assertRaisesRegex(ValueError, "size L"):
            validator.validate()
        self.component.plan(Component.task("T1", size="L", proposed=True))
        validator.validate()
        self.component.plan(Component.task("T1", acceptance=[]))
        with self.assertRaisesRegex(ValueError, "acceptance and scope"):
            validator.validate()
        self.component.plan(Component.task("T1", depends_on=["T2"]), Component.task("T2", depends_on=["T1"]))
        with self.assertRaisesRegex(ValueError, "cycle"):
            validator.validate()

    def test_lessons_need_repeated_evidence(self):
        self.component.plan(Component.task("T1"))
        self.component.retro("T1-1", "T1", "2026-01-01T00:00:00Z", ["db-down"])
        lesson = {"id": "L-1", "tag": "db-down", "rule": "Start the database first", "applies_to": ["verify"],
                  "source": ["T1-1"], "status": "trial", "introduced_at": "2026-01-02T00:00:00Z"}
        self.component.write_yaml("agent/LESSONS.yaml", {"lessons": [lesson]})
        with self.assertRaisesRegex(ValueError, "needs 2 source"):
            validator.validate()

        self.component.retro("T1-2", "T1", "2026-01-01T01:00:00Z", ["db-down"])
        lesson["source"].append("T1-2")
        self.component.write_yaml("agent/LESSONS.yaml", {"lessons": [lesson]})
        validator.validate()

    def test_merged_retrospectives_are_immutable(self):
        self.component.plan(Component.task("T1"))
        self.component.retro("T1-1", "T1", "2026-01-01T00:00:00Z")
        base = self.component.commit()
        self.component.retro("T1-1", "T1", "2026-01-01T00:00:00Z", ["rewritten"])
        with self.assertRaisesRegex(ValueError, "immutable"):
            validator.validate(base)

    def test_core_must_match_shared(self):
        self.component.write("agent/core/process/00-session.md", "# session\n")
        remote = validator.local_core()
        validator.compare_core(remote)
        self.component.write("agent/core/process/00-session.md", "# edited locally\n")
        with self.assertRaisesRegex(ValueError, "sync-core"):
            validator.compare_core(remote)


if __name__ == "__main__":
    unittest.main()
