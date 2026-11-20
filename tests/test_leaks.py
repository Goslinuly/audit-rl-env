import json
from pathlib import Path

import pytest

from auditgym.policies import FlagAll, Oracle, RandomExplorer, Reconciler
from auditgym.runner.__main__ import main as run_cli
from auditgym.runner.core import run_episode
from auditgym.runner.dry_run import DryRunEnv
from auditgym.runner.leaks import LeakError, LeakScanner, main, scan_trajectory

SAMPLE = Path(__file__).resolve().parents[1] / "episodes/sample/sample_00"


@pytest.mark.parametrize("key", ["truth", "Truth", "PROVENANCE", "private", "seed",
                                     "random_seed", "policy-seed", "issue_id", "issueId",
                                     "expected_amount_minor", "groundTruth", "truth_path"])
def test_nested_private_keys(key):
    with pytest.raises(LeakError, match="private"):
        LeakScanner().require_public({"outer": [{"inner": {key: "value"}}]})


@pytest.mark.parametrize("message", [
    'debug: {"truth": {"issues": []}}', "reference ISS-01 was matched",
    "seed=9001", "generation_seed: 42", 'debug: {"seed": 9001}', "seed is 9001",
    'debug: {"issue_id": "hidden-reference"}', "expected_amount_minor=100",
    "provenance attached", "Traceback (most recent call last):",
    r"C:\repo\episodes\sample\private\data.json", "file:///tmp/secret.json",
    "/app/episodes/secret.json", "episodes/dev/private/data.json",
    r"\\server\share\episodes\data.json",
])
def test_leaks_in_error_strings(message):
    assert LeakScanner().scan({"error": {"code": "bad_args", "message": message}})


def test_safe_public_values_do_not_blacklist_derivable_numbers():
    assert not LeakScanner(private_tokens=[9001, 100]).scan({
        "records": [{"amount_minor": 100, "invoice_id": "INV-9001"}],
        "error": {"code": "not_found", "message": "Record not found"},
        "steps_remaining": 9,
    })


def test_custom_secret_token_and_exception_do_not_echo_value():
    scanner = LeakScanner(private_tokens=["CANARY-P4-SECRET"])
    with pytest.raises(LeakError) as error:
        scanner.require_public({"error": "debug CANARY-P4-SECRET"})
    assert "CANARY-P4-SECRET" not in str(error.value)
    assert scanner.scan({"notes": "canary-p4-secret"})[0].rule == "private_token"


@pytest.mark.parametrize("boundary", ["reset_observation", "reset_info", "observation", "info"])
@pytest.mark.parametrize("policy_name", ["Oracle", "FlagAll", "RandomExplorer", "Reconciler"])
def test_runner_blocks_all_environment_boundaries(boundary, policy_name):
    class Injected(DryRunEnv):
        def reset(self):
            obs, info = super().reset()
            if boundary == "reset_observation":
                obs["error"] = {"message": "debug ISS-99"}
            if boundary == "reset_info":
                info["internal"] = {"SEED": 77}
            return obs, info

        def step(self, action):
            obs, reward, done, truncated, info = super().step(action)
            if boundary == "observation":
                obs["error"] = {"message": "provenance is available"}
            if boundary == "info":
                info["trace"] = "/tmp/private.json"
            return obs, reward, done, truncated, info

    truth = json.loads((SAMPLE / "private/truth.json").read_text(encoding="utf-8"))
    policy = {"Oracle": lambda: Oracle(truth), "FlagAll": FlagAll,
              "RandomExplorer": RandomExplorer, "Reconciler": Reconciler}[policy_name]()
    with pytest.raises(LeakError):
        run_episode(Injected(SAMPLE), policy, policy_name=policy_name)


def test_oracle_has_no_observation_exemption():
    class Leaky(DryRunEnv):
        def reset(self):
            obs, info = super().reset()
            obs["truth"] = {"issues": []}
            return obs, info
    truth = json.loads((SAMPLE / "private/truth.json").read_text(encoding="utf-8"))
    with pytest.raises(LeakError):
        run_episode(Leaky(SAMPLE), Oracle(truth), policy_name="Oracle")


def test_actions_are_scanned_before_environment_execution():
    class BadPolicy:
        def act(self, obs):
            return {"name": "submit", "args": {"truth": "secret"}}
    class NoStep(DryRunEnv):
        def step(self, action):
            pytest.fail("Leaking action reached the environment")
    with pytest.raises(LeakError):
        run_episode(NoStep(SAMPLE), BadPolicy(), policy_name="Oracle")


def test_post_export_scan_includes_reset_and_handles_tampered_log(tmp_path, capsys):
    out = tmp_path / "run"
    run_cli(["--dry-run", "--policies", "Oracle", "FlagAll", "--episodes", str(SAMPLE),
             "--out", str(out)])
    report = json.loads((out / "leak_report.json").read_text())
    assert report["status"] == "passed"
    path = out / "trajectories.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert "initial_observation" in rows[0] and "reset_info" in rows[0]
    assert main([str(path)]) == 0
    rows[0]["initial_observation"]["debug"] = "provenance"
    assert scan_trajectory(rows)["status"] == "failed"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    assert main([str(path)]) == 1
    assert "failed" in capsys.readouterr().out


@pytest.mark.parametrize("text", ["not-json", "{invalid", ""])
def test_offline_scanner_fails_for_invalid_or_empty_input(tmp_path, text):
    path = tmp_path / "broken.jsonl"
    path.write_text(text, encoding="utf-8")
    assert main([str(path)]) == 1
