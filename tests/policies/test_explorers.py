import ast
import csv
import inspect
import json
import random
from copy import deepcopy
from pathlib import Path

import pytest

from auditgym.generator.io import load_private, load_public
from auditgym.generator.splits import iter_split
from auditgym.generator.transforms import remap_ids
from auditgym.policies import RandomExplorer, Reconciler
from auditgym.policies import explorers
from auditgym.runner.__main__ import main
from auditgym.runner.core import run_episode
from auditgym.runner.dry_run import DryRunEnv

ROOT = Path(__file__).resolve().parents[2]
EPISODES = sorted((ROOT / "episodes").glob("*/*/public/manifest.json"))
SAMPLE = ROOT / "episodes/sample/sample_00"


class PublicFixtureEnv(DryRunEnv):
    def __init__(self, public, max_steps=100):
        self.public = deepcopy(public)
        self.max_steps = max_steps


def check_answer(public, truth):
    trajectory, result = run_episode(PublicFixtureEnv(public), Reconciler(),
                                     policy_name="Reconciler")
    findings = trajectory[-1]["action"]["args"]["findings"]["findings"]
    def key(f, amount):
        return (f["type"], tuple(f["affected_ids"]), f[amount], f["currency"])
    expected = {key(issue, "expected_amount_minor"): issue for issue in truth["issues"]}
    assert len(findings) == len(expected)
    for finding in findings:
        issue = expected[key(finding, "claimed_amount_minor")]
        assert any(set(e) <= set(finding["evidence_ids"]) for e in issue["evidence_sets"])
        assert len(finding["evidence_ids"]) <= 10
    assert result["terminated"] and not result["truncated"]
    assert result["steps"] <= 100
    assert all(row["action"]["args"].get("limit", 0) <= 50 for row in trajectory)
    return trajectory, findings


@pytest.mark.parametrize("manifest", EPISODES)
def test_reconciler_all_published_episodes(manifest):
    episode = manifest.parents[1]
    check_answer(load_public(episode), load_private(episode)["truth"])


@pytest.mark.parametrize("item,episode", list(iter_split("selfcheck")),
                         ids=lambda v: v.get("name") if isinstance(v, dict) else None)
def test_reconciler_selfcheck_clean_interactions_and_distractors(item, episode):
    original = deepcopy(episode.public)
    _, findings = check_answer(episode.public, episode.private["truth"])
    assert episode.public == original
    if not episode.private["truth"]["issues"]:
        assert not findings


def test_reconciler_is_invariant_to_row_order():
    public, truth = load_public(SAMPLE), load_private(SAMPLE)["truth"]
    _, first = check_answer(public, truth)
    for table in explorers.TABLES:
        random.Random(81).shuffle(public[table])
    _, second = check_answer(public, truth)
    assert first == second


def test_reconciler_renamed_ids_are_derived_from_visible_records():
    public, truth, _ = remap_ids(load_public(SAMPLE), load_private(SAMPLE)["truth"], seed=951)
    check_answer(public, truth)


def test_reconciler_budget_exhaustion_submits_no_partial_false_claims():
    rows, result = run_episode(DryRunEnv(SAMPLE, max_steps=2), Reconciler(),
                               policy_name="Reconciler", max_steps=2)
    assert rows[-1]["action"]["name"] == "submit"
    assert rows[-1]["action"]["args"]["findings"]["findings"] == []
    assert result["steps"] == 2


def test_reconciler_detects_cursor_cycles():
    p = Reconciler()
    public = load_public(SAMPLE)
    p.act({"manifest": public["manifest"], "policy": public["policy"], "steps_remaining": 100})
    p.act({"records": [], "next_cursor": "opaque-a", "steps_remaining": 99})
    with pytest.raises(ValueError, match="cursor"):
        p.act({"records": [], "next_cursor": "opaque-a", "steps_remaining": 98})


def test_random_seed_reproduces_full_trajectory_and_different_seed_changes_it():
    def run(seed):
        return run_episode(DryRunEnv(SAMPLE), RandomExplorer(seed),
                           policy_name="RandomExplorer")[0]
    a, b, c = run(19), run(19), run(20)
    assert a == b and a != c
    assert a[-1]["action"]["name"] == "submit"
    assert len(a) == 9
    assert any(row["action"]["name"] == "get_record" for row in a)
    assert len(a[-1]["action"]["args"]["findings"]["findings"]) <= 1


@pytest.mark.parametrize("budget", [1, 2, 5, 100])
def test_random_reserves_submit_step(budget):
    rows, result = run_episode(DryRunEnv(SAMPLE, max_steps=budget), RandomExplorer(0),
                               policy_name="RandomExplorer", max_steps=budget)
    assert result["steps"] <= budget
    assert result["terminated"]
    assert rows[-1]["action"]["name"] == "submit"


def test_all_four_cli_and_non_oracle_never_read_private_data(tmp_path, monkeypatch):
    original = Path.read_text
    def public_only(path, *args, **kwargs):
        if "private" in path.parts:
            raise AssertionError("Non-Oracle policy read private data")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as context:
        context.setattr(Path, "read_text", public_only)
        main(["--dry-run", "--policies", "RandomExplorer", "Reconciler", "--seed", "123",
              "--episodes", str(SAMPLE), "--out", str(tmp_path / "public")])
    main(["--dry-run", "--episodes", str(SAMPLE), "--out", str(tmp_path / "all")])
    with (tmp_path / "all/results.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert {r["policy"] for r in rows} == {"Oracle", "FlagAll", "RandomExplorer", "Reconciler"}
    assert next(r for r in rows if r["policy"] == "RandomExplorer")["policy_seed"] == "7"
    assert all(r["scored"] == "False" and r["f1"] == "" for r in rows)


def test_public_policies_do_not_import_reference_auditor_or_generator():
    tree = ast.parse(inspect.getsource(explorers))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert all(not any(part in (name or "") for part in ("generator", "grader"))
               for name in imports)


def test_random_missing_get_record_is_recoverable():
    p = RandomExplorer(7)
    public = load_public(SAMPLE)
    p.act({"manifest": public["manifest"], "steps_remaining": 100})
    action = p.act({"error": {"code": "not_found"}, "steps_remaining": 99})
    assert action["name"] in ("list_records", "get_record", "submit")


def test_dry_run_unknown_record_error_and_fx_id():
    env = DryRunEnv(SAMPLE)
    env.reset()
    row = env.public["fx"][0]
    action = {"name": "get_record", "args": {
        "table": "fx", "id": explorers.record_id("fx", row)}}
    assert env.step(action)[0]["record"] == row
    action["args"]["id"] = "missing"
    assert env.step(action)[0]["error"]["code"] == "not_found"
    json.dumps(env.step({"name": "submit", "args": {}}))
