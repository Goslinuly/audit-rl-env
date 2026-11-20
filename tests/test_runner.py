import csv
import json
from pathlib import Path

import pytest

from auditgym.policies import FlagAll, Oracle
from auditgym.runner.__main__ import main
from auditgym.runner.core import run_episode
from auditgym.runner.dry_run import DryRunEnv

SAMPLE = Path(__file__).resolve().parents[1] / "episodes/sample/sample_00"


def test_cli_real_episode_exports_and_does_not_overwrite(tmp_path):
    target = tmp_path / "output"
    args = ["--dry-run", "--policies", "Oracle", "FlagAll",
            "--episodes", str(SAMPLE), "--out", str(target)]
    assert main(args) == 0
    rows = [json.loads(line) for line in (target / "trajectories.jsonl").read_text().splitlines()]
    with (target / "results.csv").open(newline="") as stream:
        results = list(csv.DictReader(stream))
    assert len(results) == 2
    assert {r["policy"] for r in rows} == {"Oracle", "FlagAll"}
    assert all(r["scored"] == "False" and r["f1"] == "" for r in results)
    assert [int(r["steps"]) for r in results] == [1, 2]
    assert b"\r\n" not in (target / "trajectories.jsonl").read_bytes()
    previous = (target / "results.csv").read_bytes()
    with pytest.raises(SystemExit):
        main(args)
    assert (target / "results.csv").read_bytes() == previous


def test_cli_uses_real_environment_by_default(tmp_path):
    main(["--episodes", str(SAMPLE), "--out", str(tmp_path / "out")])
    with (tmp_path / "out/results.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert all(row["scored"] == "True" for row in rows)
    assert next(row for row in rows if row["policy"] == "Oracle")["reward"] == "1.0"


def test_same_actions_observations_across_runs():
    a, _ = run_episode(DryRunEnv(SAMPLE), FlagAll(), policy_name="FlagAll")
    b, _ = run_episode(DryRunEnv(SAMPLE), FlagAll(), policy_name="FlagAll")
    assert a == b


def test_external_scoring_gets_empty_answer_when_truncated():
    seen = []

    class NeverSubmit:
        def act(self, obs):
            return {"name": "list_records", "args": {
                "table": "invoices", "cursor": None, "limit": 1,
            }}

    def scorer(answer, inspection_steps):
        seen.append((answer, inspection_steps))
        return {"precision": 0, "recall": 0, "f1": 0, "reward": -1}

    rows, result = run_episode(DryRunEnv(SAMPLE, max_steps=1), NeverSubmit(),
                               policy_name="FlagAll", max_steps=1, scorer=scorer)
    assert rows[-1]["truncated"]
    assert not rows[-1]["terminated"]
    assert seen[0][0]["findings"] == []
    assert seen[0][1] == 1
    assert result["reward"] == -1


def test_flagall_cli_never_reads_private_files(tmp_path, monkeypatch):
    original = Path.read_text

    def public_only(path, *args, **kwargs):
        if "private" in path.parts:
            raise AssertionError("FlagAll must not load private data")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", public_only)
    assert main(["--dry-run", "--policies", "FlagAll", "--episodes", str(SAMPLE),
                 "--out", str(tmp_path / "flagall")]) == 0


def test_cli_adapter_factories_and_scored_csv(tmp_path, monkeypatch):
    import auditgym.runner.__main__ as cli

    def make_scorer(episode_dir):
        def score(answer, steps):
            return {"precision": .25, "recall": .5, "f1": 1 / 3, "reward": -.4}
        return score

    monkeypatch.setattr(cli, "symbol", lambda name: {
        "test:env": DryRunEnv, "test:scorer": make_scorer,
    }[name])
    out = tmp_path / "integration"
    assert main(["--episodes", str(SAMPLE), "--out", str(out), "--policies", "FlagAll",
                 "--env-factory", "test:env", "--scorer-factory", "test:scorer"]) == 0
    with (out / "results.csv").open(newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["scored"] == "True"
    assert float(row["reward"]) == -.4
    assert float(row["return"]) == 0


def test_injected_scorer_metrics_and_inspection_step_count():
    truth = json.loads((SAMPLE / "private/truth.json").read_text())

    def fixture_scorer(answer, steps):
        assert len(answer["findings"]) == len(truth["issues"])
        assert steps == 0
        return {"precision": 1, "recall": 1, "f1": 1, "reward": 1}

    _, result = run_episode(DryRunEnv(SAMPLE), Oracle(truth), policy_name="Oracle",
                            scorer=fixture_scorer)
    assert result["f1"] == result["reward"] == 1
    assert result["inspection_steps"] == 0
    assert result["return"] == 0  # Transport reward and evaluator reward are separate.


@pytest.mark.parametrize("field", ["truth", "provenance", "issue_id", "seed"])
def test_private_environment_fields_are_rejected_before_agent_call(field):
    class Leaky(DryRunEnv):
        def reset(self):
            obs, info = super().reset()
            obs["nested"] = {field: "secret"}
            return obs, info

    with pytest.raises(ValueError, match="private"):
        run_episode(Leaky(SAMPLE), FlagAll(), policy_name="FlagAll")


def test_policy_cannot_mutate_recorded_observations():
    class MutatingFlagAll(FlagAll):
        def act(self, obs):
            action = super().act(obs)
            if "records" in obs:
                obs["records"].clear()
            return action

    rows, _ = run_episode(DryRunEnv(SAMPLE), MutatingFlagAll(), policy_name="FlagAll")
    assert rows[0]["observation"]["records"]
