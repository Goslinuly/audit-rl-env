"""Unit tests: normalisation, metrics/reward formula, Grader API forms."""

from __future__ import annotations

from fractions import Fraction

import pytest
from grader_helpers import EPISODE_DIRS, GRADER, episode, grade, oracle, with_findings

from auditgym.grader import (
    Grader,
    PublicIndex,
    metrics,
    normalize_refs,
    terminal_reward,
)


# --- normalisation -----------------------------------------------------------------------
def test_normalize_refs_is_exact_and_only_makes_a_set():
    public, _truth = episode("sample_00")
    idx = PublicIndex.from_public(public)
    row = f"ledger:{public['ledger'][0]['row_id']}"
    doc = f"invoices:{public['invoices'][0]['doc_id']}"
    ids, unknown = normalize_refs([row, row, "ledger:NOPE", f" {row}", doc], idx)
    assert ids == {row, "ledger:NOPE", f" {row}", doc}
    assert unknown == tuple(sorted(["ledger:NOPE", f" {row}", doc]))


def test_repeated_ids_inside_one_finding_are_deduplicated():
    o = oracle("sample_00")
    f = o["findings"][0]
    f["affected_ids"] = f["affected_ids"] * 3
    f["evidence_ids"] = (f["evidence_ids"] * 3)[:10]
    assert grade(with_findings("sample_00", [f]), "sample_00").tp == 1


# --- metrics and reward ------------------------------------------------------------------
@pytest.mark.parametrize(
    "tp,fp,fn,p,r,f1",
    [
        (0, 0, 0, 0, 0, 1),  # empty truth + empty answer
        (0, 3, 0, 0, 0, 0),  # empty truth + any finding
        (0, 0, 4, 0, 0, 0),  # silence on broken books
        (3, 0, 0, 1, 1, 1),
        (2, 1, 1, Fraction(2, 3), Fraction(2, 3), Fraction(2, 3)),
        (1, 29, 0, Fraction(1, 30), 1, Fraction(2, 31)),
    ],
)
def test_metrics_table(tp, fp, fn, p, r, f1):
    assert metrics(tp, fp, fn) == (p, r, f1)


def test_reward_formula_and_clip():
    assert terminal_reward(Fraction(1), 0) == 1.0
    assert terminal_reward(Fraction(0), 0) == -1.0
    assert terminal_reward(Fraction(0), 99) == -1.0  # clipped
    assert terminal_reward(Fraction(1, 2), 0) == 0.0
    assert terminal_reward(Fraction(1), 10) == 0.98
    assert terminal_reward(Fraction(1), 90) == 0.82
    assert terminal_reward(Fraction(1), -5) == 1.0  # negative steps are treated as 0


# --- API ---------------------------------------------------------------------------------
def test_score_from_episode_dir_equals_score_from_data():
    public, truth = episode("dev_07")
    o = oracle("dev_07")
    a = Grader().score(o, EPISODE_DIRS["dev_07"], inspection_steps=5)
    b = GRADER.score(o, truth=truth, public=public, inspection_steps=5)
    assert a.to_dict() == b.to_dict() and a.reward == 0.99


def test_result_is_json_serialisable_and_has_diagnostics():
    import json

    r = grade(oracle("sample_00"), "sample_00", steps=3)
    d = json.loads(json.dumps(r.to_dict()))
    for key in ("reward", "precision", "recall", "f1", "tp", "fp", "fn", "matches", "errors",
                "finding_reasons", "missed_issue_ids", "by_type", "grader_version"):
        assert key in d
    assert sum(v["tp"] for v in d["by_type"].values()) == d["tp"]


def test_grader_without_public_still_works():
    _, truth = episode("sample_00")
    from auditgym.grader import oracle_findings

    r = Grader().score(oracle_findings(truth), truth=truth)
    assert r.reward == 1.0


def test_env_uses_real_grader_not_stub():
    from auditgym.env.grading import default_grader

    assert default_grader() is Grader
