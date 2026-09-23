#!/usr/bin/env python3
"""Decide whether a Component PR only changes the learning layer and may be approved by CI.

The learning layer is agent/LESSONS.yaml and new files in agent/retros/. Prints
eligible=true or eligible=false for $GITHUB_OUTPUT and the reasons to stderr.
"""

import argparse
import re
import sys

import validate as schema


def codeowners_problem(base):
    """Auto-approval is safe only while CODEOWNERS makes every other change need a human."""
    result = schema.git("show", f"{base}:.github/CODEOWNERS")
    if result.returncode != 0:
        return ".github/CODEOWNERS is missing"
    for line in result.stdout.decode().splitlines():
        rule = line.split()
        if rule and rule[0] == "*" and len(rule) > 1 and all(owner.startswith("@") and "<" not in owner for owner in rule[1:]):
            return None
    return ".github/CODEOWNERS needs a real owner for *"


def problems(base):
    schema.validate(base)
    found = []
    problem = codeowners_problem(base)
    if problem:
        found.append(problem)
    changed = schema.git("diff", "--name-status", "--no-renames", base, "HEAD")
    schema.require(changed.returncode == 0, "could not inspect PR changes")
    lines = changed.stdout.decode().splitlines()
    for line in lines:
        status, name = line.split("\t", 1)
        if status == "M" and name == "agent/LESSONS.yaml":
            continue
        if status == "A" and re.fullmatch(r"agent/retros/[^/]+\.yaml", name):
            continue
        found.append(f"{name}: only agent/LESSONS.yaml and new retrospectives are approved automatically")
    if not lines:
        found.append("no changes")
    return found


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="PR base commit SHA")
    args = parser.parse_args()
    try:
        found = problems(args.base)
    except Exception as exc:  # Any doubt leaves the PR to a human reviewer.
        found = [f"check failed: {exc}"]
    for problem in found:
        print(f"Not approved automatically: {problem}", file=sys.stderr)
    print(f"eligible={'false' if found else 'true'}")
