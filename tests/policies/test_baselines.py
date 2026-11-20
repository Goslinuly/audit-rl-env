from copy import deepcopy
from pathlib import Path

import pytest

from auditgym.generator.io import load_private, load_public
from auditgym.policies import FlagAll, Oracle
from auditgym.runner.core import run_episode
from auditgym.runner.dry_run import DryRunEnv

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "episodes/sample/sample_00"


@pytest.mark.parametrize("episode", sorted((ROOT / "episodes").glob("*/*/private/truth.json")))
def test_oracle_matches_every_published_truth(episode):
    truth = load_private(episode.parents[1])["truth"]
    public = load_public(episode.parents[1])
    original = deepcopy(truth)
    oracle = Oracle(truth)
    answer = oracle.act({"manifest": public["manifest"]})["args"]["findings"]
    assert answer["episode_id"] == truth["episode_id"]
    assert len(answer["findings"]) == len(truth["issues"])
    for finding, issue in zip(answer["findings"], truth["issues"]):
        assert finding["type"] == issue["type"]
        assert finding["affected_ids"] == sorted(set(issue["affected_ids"]))
        assert finding["claimed_amount_minor"] == issue["expected_amount_minor"]
        assert finding["currency"] == issue["currency"]
        assert set(issue["evidence_sets"][0]) <= set(finding["evidence_ids"])
        assert not {"issue_id", "group", "description", "expected_amount_minor"} & finding.keys()
    assert truth == original
    answer["findings"].clear()
    assert len(oracle.act({"manifest": public["manifest"]})["args"]["findings"]["findings"]) == len(
        original["issues"])


def test_oracle_rejects_wrong_episode():
    with pytest.raises(ValueError, match="episode"):
        Oracle(load_private(SAMPLE)["truth"]).act({"manifest": {"episode_id": "other"}})


def test_flagall_uses_only_visible_ids_and_stops_at_30():
    trajectory, result = run_episode(DryRunEnv(SAMPLE), FlagAll(), policy_name="FlagAll")
    visible = {"invoices:" + r["invoice_id"]
               for row in trajectory if row["action"]["name"] == "list_records"
               for r in row["observation"]["records"]}
    findings = trajectory[-1]["action"]["args"]["findings"]["findings"]
    assert len(findings) == 30
    assert all(set(f["affected_ids"]) <= visible for f in findings)
    assert result["steps"] == 2
    assert result["scored"] is False
    assert result["f1"] is None


def test_flagall_paginates_empty_and_small_pages_and_reserves_submit():
    p = FlagAll()
    first = {"manifest": {"episode_id": "ep", "base_currency": "KZT"},
             "steps_remaining": 100}
    assert p.act(first)["args"]["table"] == "invoices"
    action = p.act({"records": [], "next_cursor": "page2", "steps_remaining": 99})
    assert action["args"]["cursor"] == "page2"
    action = p.act({"records": [{"invoice_id": "INV-1"}], "next_cursor": None,
                    "steps_remaining": 98})
    assert action["args"]["table"] == "payments"
    action = p.act({"records": [{"payment_id": "PAY-1"}], "next_cursor": "more",
                    "steps_remaining": 1})
    assert action["name"] == "submit"
    assert len(action["args"]["findings"]["findings"]) == 8


def test_flagall_empty_episode():
    p = FlagAll()
    p.act({"manifest": {"episode_id": "ep", "base_currency": "KZT"}, "steps_remaining": 3})
    p.act({"records": [], "next_cursor": None, "steps_remaining": 2})
    assert p.act({"records": [], "next_cursor": None, "steps_remaining": 1})[
        "args"]["findings"]["findings"] == []
