"""20 episodes x 4 policies x contract/repeat/shuffle/remap checks.

Only Oracle and Reconciler promise semantic invariance. RandomExplorer and
FlagAll sample visible rows; reordered/renamed inputs may change their answers.
For these baselines we require valid public IDs, bounded execution and repeatable
behavior within each transformed input, and report changes rather than hide them.
"""

import hashlib
import json
import tempfile
from copy import deepcopy

import pytest

from auditgym.generator import Episode, generate, load_config
from auditgym.generator.splits import REPO_ROOT, iter_split
from auditgym.generator.transforms import remap_ids, shuffle_rows
from auditgym.policies import FlagAll, Oracle, RandomExplorer, Reconciler
from auditgym.policies.explorers import TABLES, record_id
from auditgym.runner.core import run_episode
from auditgym.env import AuditEnv
from auditgym.runner.leaks import scan_trajectory

POLICIES = ("Oracle", "FlagAll", "RandomExplorer", "Reconciler")
CASES = {item["name"]: (item, episode) for item, episode in iter_split("selfcheck")}


def execute(policy_name, public, truth):
    policy = {"Oracle": lambda: Oracle(truth), "FlagAll": FlagAll,
              "RandomExplorer": lambda: RandomExplorer(42), "Reconciler": Reconciler}[policy_name]()
    original = next(ep for _, ep in CASES.values() if ep.episode_id == truth["episode_id"])
    private = {"truth": deepcopy(truth), "provenance": deepcopy(original.private["provenance"])}
    with tempfile.TemporaryDirectory() as directory, AuditEnv() as env:
        Episode(deepcopy(public), private, original.seed, original.config).write(directory)
        rows, result = run_episode(env, policy, policy_name=policy_name,
                                   reset_kwargs={"episode_dir": directory})
    return rows, result


def answer(rows):
    return rows[-1]["action"]["args"]["findings"]["findings"]


def semantic(findings, reverse=None):
    reverse = reverse or {}
    def ref(value):
        table, key = value.split(":", 1)
        return table + ":" + reverse.get(key, key)
    return sorted((f["type"], tuple(sorted(ref(i) for i in f["affected_ids"])),
                   f["claimed_amount_minor"], f["currency"],
                   tuple(sorted(ref(i) for i in f["evidence_ids"]))) for f in findings)


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def assert_contract(rows, result, public, policy_name):
    assert 1 <= result["steps"] <= 100
    assert result["terminated"] and not result["truncated"]
    assert rows[-1]["action"]["name"] == "submit"
    assert scan_trajectory(rows)["status"] == "passed"
    visible = {table + ":" + record_id(table, row)
               for table in TABLES for row in public[table]}
    observed = set()
    for row in rows:
        action = row["action"]
        if action["name"] == "list_records":
            assert 1 <= action["args"]["limit"] <= 50
            table = action["args"]["table"]
            items = row["observation"].get("result", {}).get("items", [])
            observed.update(table + ":" + record_id(table, item["record"]) for item in items)
        elif action["name"] == "get_record" and "record" in row["observation"].get("result", {}):
            table = action["args"]["table"]
            observed.add(table + ":" + record_id(table, row["observation"]["result"]["record"]))
    findings = answer(rows)
    assert len(findings) <= 30
    for finding in findings:
        assert isinstance(finding["claimed_amount_minor"], int)
        assert len(finding["evidence_ids"]) <= 10
        ids = set(finding["evidence_ids"] + finding["affected_ids"])
        assert ids <= visible
        if policy_name != "Oracle":
            assert ids <= observed
    assert -1 <= result["reward"] <= 1


@pytest.mark.parametrize("episode_name", CASES)
@pytest.mark.parametrize("policy_name", POLICIES)
def test_contract_and_leaks(episode_name, policy_name, request):
    _, episode = CASES[episode_name]
    rows, result = execute(policy_name, episode.public, episode.private["truth"])
    assert_contract(rows, result, episode.public, policy_name)
    if policy_name in ("Oracle", "Reconciler"):
        assert result["f1"] == 1
    if policy_name == "Oracle":
        assert result["reward"] == 1
    if policy_name == "FlagAll":
        assert result["reward"] < 0
    request.node.user_properties.extend((key, result[key])
                                         for key in ("steps", "f1", "reward"))


@pytest.mark.parametrize("episode_name", CASES)
@pytest.mark.parametrize("policy_name", POLICIES)
def test_seed_reproduction(episode_name, policy_name, request):
    spec, original = CASES[episode_name]
    regenerated = generate(spec["seed"], load_config(REPO_ROOT / spec["config"]))
    assert regenerated.public == original.public
    a, ar = execute(policy_name, original.public, original.private["truth"])
    b, br = execute(policy_name, regenerated.public, regenerated.private["truth"])
    assert a == b
    assert {k: v for k, v in ar.items() if k != "time_s"} == {
        k: v for k, v in br.items() if k != "time_s"}
    request.node.user_properties.append(("trajectory_sha256", digest(a)))


@pytest.mark.parametrize("episode_name", CASES)
@pytest.mark.parametrize("policy_name", POLICIES)
def test_row_shuffle(episode_name, policy_name, request):
    _, episode = CASES[episode_name]
    public, truth = episode.public, episode.private["truth"]
    changed = shuffle_rows(public, seed=319)
    # Generator helper covers ledger/documents; also reorder FX for the policy.
    changed["fx"].reverse()
    a, ar = execute(policy_name, public, truth)
    b, br = execute(policy_name, changed, truth)
    again, _ = execute(policy_name, changed, truth)
    assert b == again
    assert_contract(b, br, changed, policy_name)
    invariant = policy_name in ("Oracle", "Reconciler")
    if invariant:
        assert semantic(answer(a)) == semantic(answer(b))
        assert ar["reward"] == br["reward"]
    request.node.user_properties.extend([
        ("invariance_expected", invariant),
        ("answer_changed", semantic(answer(a)) != semantic(answer(b))),
        ("reward_before", ar["reward"]), ("reward_after", br["reward"]),
    ])


@pytest.mark.parametrize("episode_name", CASES)
@pytest.mark.parametrize("policy_name", POLICIES)
def test_id_remap(episode_name, policy_name, request):
    _, episode = CASES[episode_name]
    public, truth = episode.public, episode.private["truth"]
    changed, mapped_truth, mapping = remap_ids(public, truth, seed=731)
    a, ar = execute(policy_name, public, truth)
    b, br = execute(policy_name, changed, mapped_truth)
    again, _ = execute(policy_name, changed, mapped_truth)
    assert b == again
    assert_contract(b, br, changed, policy_name)
    reverse = {value: key for key, value in mapping.items()}
    invariant = policy_name in ("Oracle", "Reconciler")
    if invariant:
        assert semantic(answer(a)) == semantic(answer(b), reverse)
        assert ar["reward"] == br["reward"]
    request.node.user_properties.extend([
        ("invariance_expected", invariant),
        ("answer_changed", semantic(answer(a)) != semantic(answer(b), reverse)),
        ("reward_before", ar["reward"]), ("reward_after", br["reward"]),
    ])
