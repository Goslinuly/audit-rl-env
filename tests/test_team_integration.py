import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from auditgym.env import AuditEnv
from auditgym.generator.io import load_private
from auditgym.policies import FlagAll, Oracle, RandomExplorer, Reconciler
from auditgym.runner.core import run_episode
from auditgym.runner.leaks import scan_trajectory

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "episodes/sample/sample_00"
POLICIES = ("Oracle", "FlagAll", "RandomExplorer", "Reconciler")


@pytest.mark.parametrize("mode", ["train", "eval"])
@pytest.mark.parametrize("policy_name", POLICIES)
def test_all_policies_use_team_environment_grader_and_trajectory_schema(mode, policy_name):
    truth = load_private(SAMPLE)["truth"]
    policy = {"Oracle": lambda: Oracle(truth), "FlagAll": FlagAll,
              "RandomExplorer": lambda: RandomExplorer(42), "Reconciler": Reconciler}[policy_name]()
    with AuditEnv(mode=mode) as env:
        rows, result = run_episode(env, policy, policy_name=policy_name,
                                   reset_kwargs={"episode_dir": SAMPLE})
        grade = env.grade_log[-1]
        assert result["scored"]
        assert result["reward"] == grade["reward"]
        assert result["f1"] == grade["f1"]
        assert result["inspection_steps"] == grade["inspection_steps"]
        assert result["steps"] == rows[-1]["observation"]["step"]
        if mode == "eval":
            assert all(row["reward"] == 0 for row in rows)
        else:
            assert result["return"] == grade["reward"]
        if policy_name in ("Oracle", "Reconciler"):
            assert result["f1"] == 1
        if policy_name == "RandomExplorer":
            assert policy.known  # Regression: old adapter silently discarded 127 records.
    assert scan_trajectory(rows)["status"] == "passed"
    schemas = [json.loads(p.read_text()) for p in (ROOT / "schemas").glob("*.schema.json")]
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    schema = next(s for s in schemas if s["$id"].endswith("trajectory_line.schema.json"))
    validator = Draft202012Validator(schema, registry=registry)
    for row in rows:
        validator.validate(row)


def test_timeout_uses_team_step_count_and_does_not_copy_grader_diagnostics():
    now = [0.0]
    class TimeoutPolicy:
        def act(self, obs):
            now[0] = 61.0
            return {"name": "calculator", "args": {"expression": "1"}}
    with AuditEnv(clock=lambda: now[0]) as env:
        rows, result = run_episode(env, TimeoutPolicy(), policy_name="TimeoutPolicy",
                                   reset_kwargs={"episode_dir": SAMPLE})
        assert result["truncated"] and result["steps"] == 0
        assert result["inspection_steps"] == env.grade_log[-1]["inspection_steps"] == 0
        assert "missed_issue_ids" in env.grade_log[-1]
        assert "missed_issue_ids" not in json.dumps(rows)
        assert "finding_reasons" not in json.dumps(rows)
