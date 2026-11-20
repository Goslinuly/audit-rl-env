"""Optional machine-readable acceptance summary, independent of grader output."""

import json
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--acceptance-report", help="Write acceptance-only JSON summary")


def pytest_configure(config):
    config._acceptance_cases = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    if "tests/acceptance/" not in item.nodeid.replace("\\", "/"):
        return
    if report.when == "call" or (report.when == "setup" and report.failed):
        params = getattr(getattr(item, "callspec", None), "params", {})
        item.config._acceptance_cases.append({
            "test": item.originalname or item.name,
            "policy": params.get("policy_name"), "episode": params.get("episode_name"),
            "status": report.outcome, "details": dict(item.user_properties),
        })


def pytest_sessionfinish(session, exitstatus):
    destination = session.config.getoption("--acceptance-report")
    if not destination:
        return
    cases = session.config._acceptance_cases
    totals = {}
    for case in cases:
        key = case["test"] + "/" + (case["policy"] or "all")
        group = totals.setdefault(key, {"passed": 0, "failed": 0, "skipped": 0})
        group[case["status"]] += 1
    report = {
        "status": "passed" if exitstatus == 0 else "failed",
        "scope": "AuditEnv + production Grader, train mode, 20 selfcheck episodes",
        "criteria": totals, "cases": cases,
    }
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
