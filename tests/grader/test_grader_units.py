"""Unit tests: normalisation, metrics/reward formula, Grader API forms."""

from __future__ import annotations

from fractions import Fraction

import pytest
from grader_helpers import EPISODE_DIRS, GRADER, episode, grade, oracle, with_findings

from auditgym.grader import (
    Grader,
    PublicIndex,
    metrics,
    normalize_ref,
    normalize_refs,
    terminal_reward,
)


# --- normalisation -----------------------------------------------------------------------
def test_normalize_ref_rules():
    assert normalize_ref("  Ledger:L0042 ") == "ledger:L0042"
    assert normalize_ref("INVOICES : INV-7Q2K") == "invoices:INV-7Q2K"
    assert normalize_ref("fx:2026-03-31/usd/kzt") == "fx:2026-03-31/USD/KZT"
    assert normalize_ref("L0042") == "L0042"  # no prefix → left alone, never guessed
    assert normalize_ref("ledger:l0042") == "ledger:l0042"  # IDs stay case-sensitive


def test_doc_id_alias_and_existence():
    public, _truth = episode("sample_00")
    idx = PublicIndex.from_public(public)
    inv = public["invoices"][0]
    pay = public["payments"][0]
    assert normalize_ref(f"invoices:{inv['doc_id']}", idx) == f"invoices:{inv['invoice_id']}"
    assert normalize_ref(f"payments:{pay['doc_id']}", idx) == f"payments:{pay['payment_id']}"
    # a document id under the wrong table is not resolved
    assert normalize_ref(f"payments:{inv['doc_id']}", idx) == f"payments:{inv['doc_id']}"
    canon, unknown = normalize_refs(
        [f"ledger:{public['ledger'][0]['row_id']}", "ledger:NOPE", " Ledger:NOPE "], idx
    )
    assert canon == tuple(sorted({f"ledger:{public['ledger'][0]['row_id']}", "ledger:NOPE"}))
    assert unknown == ("ledger:NOPE",)


def test_doc_id_alias_matches_in_findings():
    public, _truth = episode("sample_00")
    by_inv = {i["invoice_id"]: i["doc_id"] for i in public["invoices"]}
    by_pay = {p["payment_id"]: p["doc_id"] for p in public["payments"]}

    def alias(ref):
        t, _, k = ref.partition(":")
        return f"{t}:{by_inv.get(k) or by_pay.get(k) or k}"

    o = oracle("sample_00")
    for f in o["findings"]:
        f["affected_ids"] = [alias(x) for x in f["affected_ids"]]
        f["evidence_ids"] = [alias(x).upper() if x.startswith("fx") else alias(x) for x in f["evidence_ids"]]
    r = grade(o, "sample_00")
    assert r.reward == 1.0, r.finding_reasons


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
