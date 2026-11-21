"""Grader 1.1.0: one bad finding is a false positive, never -1 for the whole answer.

* a well-formed currency code not used in the episode → the finding is FP (reason ``currency``);
* unknown extra keys inside a finding are ignored (the top level stays strict);
* bare IDs (no ``<table>:`` prefix) resolve to their canonical form only when they exist in
  exactly one public table; unknown or ambiguous bare IDs stay as they are and never match.
"""

from __future__ import annotations

import copy

import pytest
from grader_helpers import episode, grade, names, oracle, silent, with_findings

from auditgym.grader import GRADER_VERSION, PublicIndex, normalize_ref, normalize_refs

ERRORED = names(clean=False)
CLEAN = names(clean=True)


def _foreign_code(public: dict) -> str:
    used = {c.upper() for c in public["manifest"]["currencies"]}
    return next(c for c in ("CHF", "GBP", "XXX", "ZZZ") if c not in used)


def _bare(ref: str) -> str:
    return ref.partition(":")[2]


def test_version_bumped():
    assert GRADER_VERSION == "1.1.0"


# --- 1. currency not used in the episode ---------------------------------------------------
@pytest.mark.parametrize("name", ERRORED)
def test_foreign_currency_finding_is_fp_not_invalid(name):
    public, _ = episode(name)
    o = oracle(name)
    code = _foreign_code(public)
    sub = copy.deepcopy(o)
    sub["findings"][0]["currency"] = f" {code.lower()} "
    r = grade(sub, name)
    assert r.valid and not r.errors
    assert r.tp == len(o["findings"]) - 1 and r.fp == 1 and r.fn == 1
    assert r.finding_reasons[0] == "currency"
    assert -1.0 < r.reward < 1.0


@pytest.mark.parametrize("name", CLEAN)
def test_foreign_currency_on_clean_episode_is_a_plain_false_positive(name):
    public, _ = episode(name)
    f = oracle("sample_00")["findings"][0]
    r = grade(with_findings(name, [dict(f, currency=_foreign_code(public))]), name)
    assert r.valid and r.fp == 1 and r.reward == -1.0  # F1 = 0, but graded, not rejected


@pytest.mark.parametrize("bad", ["US", "dollars", "", "U$D", 840, None, ["USD"]])
def test_malformed_currency_still_rejects_the_answer(bad):
    f = oracle("sample_00")["findings"][0]
    r = grade(with_findings("sample_00", [dict(f, currency=bad)]), "sample_00")
    assert not r.valid and r.reward == -1.0 and r.errors


# --- 2. unknown keys inside a finding ------------------------------------------------------
@pytest.mark.parametrize("name", ERRORED)
def test_extra_keys_inside_findings_are_ignored(name):
    o = oracle(name)
    base = grade(o, name)
    noisy = copy.deepcopy(o)
    for f in noisy["findings"]:
        f["confidence"] = 0.97
        f["severity"] = {"level": "high"}
        f["reward"] = 1.0  # a key name does not unlock anything
    r = grade(noisy, name)
    assert r.valid and r.reward == base.reward == 1.0
    assert (r.tp, r.fp, r.fn) == (base.tp, base.fp, base.fn)


def test_extra_keys_do_not_rescue_a_wrong_finding():
    f = oracle("sample_00")["findings"][0]
    wrong = dict(f, claimed_amount_minor=f["claimed_amount_minor"] + 100, confidence=1.0,
                 is_correct=True)
    r = grade(with_findings("sample_00", [wrong]), "sample_00")
    assert r.valid and r.tp == 0 and r.fp == 1


def test_grader_does_not_mutate_findings_with_extra_keys():
    sub = copy.deepcopy(oracle("sample_00"))
    sub["findings"][0]["confidence"] = 0.5
    before = copy.deepcopy(sub)
    grade(sub, "sample_00")
    assert sub == before


@pytest.mark.parametrize("extra", [{"reward": 1.0}, {"note": "x"}, {"confidence": 1}])
def test_top_level_stays_strict(extra):
    sub = dict(silent("sample_00"), **extra)
    r = grade(sub, "sample_00")
    assert not r.valid and r.reward == -1.0


# --- 3. bare IDs ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", ERRORED)
def test_bare_id_oracle_scores_one(name):
    o = copy.deepcopy(oracle(name))
    for f in o["findings"]:
        f["affected_ids"] = [_bare(x) for x in f["affected_ids"]]
        f["evidence_ids"] = [_bare(x) for x in f["evidence_ids"]]
    r = grade(o, name)
    assert r.reward == 1.0, r.finding_reasons


def test_bare_doc_ids_resolve_to_their_invoice_or_payment():
    public, _ = episode("sample_00")
    by_key = {i["invoice_id"]: i["doc_id"] for i in public["invoices"]}
    by_key.update({p["payment_id"]: p["doc_id"] for p in public["payments"]})
    o = copy.deepcopy(oracle("sample_00"))
    for f in o["findings"]:
        f["affected_ids"] = [by_key.get(_bare(x), _bare(x)) for x in f["affected_ids"]]
        f["evidence_ids"] = [by_key.get(_bare(x), x) for x in f["evidence_ids"]]
    assert grade(o, "sample_00").reward == 1.0


def test_bare_id_normalisation_rules():
    public, _ = episode("sample_00")
    idx = PublicIndex.from_public(public)
    inv, pay, row, fx = public["invoices"][0], public["payments"][0], public["ledger"][0], public["fx"][0]
    assert normalize_ref(f"  {inv['invoice_id']} ", idx) == f"invoices:{inv['invoice_id']}"
    assert normalize_ref(inv["doc_id"], idx) == f"invoices:{inv['invoice_id']}"
    assert normalize_ref(pay["payment_id"], idx) == f"payments:{pay['payment_id']}"
    assert normalize_ref(pay["doc_id"], idx) == f"payments:{pay['payment_id']}"
    assert normalize_ref(row["row_id"], idx) == f"ledger:{row['row_id']}"
    fx_key = f"{fx['date']}/{fx['source_currency']}/{fx['target_currency']}"
    assert normalize_ref(fx_key.lower(), idx) == f"fx:{fx_key}"
    # case-sensitive, no fuzzy matching, no prefix guessing
    assert normalize_ref(inv["invoice_id"].lower(), idx) == inv["invoice_id"].lower()
    assert normalize_ref(inv["invoice_id"][:-1], idx) == inv["invoice_id"][:-1]
    canon, unknown = normalize_refs(["INV-NOPE00", inv["invoice_id"]], idx)
    assert unknown == ("INV-NOPE00",) and f"invoices:{inv['invoice_id']}" in canon


@pytest.mark.parametrize("name", ERRORED)
def test_unknown_bare_id_does_not_match(name):
    for f in oracle(name)["findings"]:
        guess = dict(f, affected_ids=[_bare(x) + "0" for x in f["affected_ids"]])
        r = grade(with_findings(name, [guess]), name)
        assert r.valid and r.tp == 0 and r.finding_reasons == ["unknown_id"]
        guess = dict(f, evidence_ids=[*f["evidence_ids"][:9], "NOT-A-RECORD"])
        r = grade(with_findings(name, [guess]), name)
        assert r.valid and r.tp == 0 and r.finding_reasons == ["unknown_id"]


def test_ambiguous_bare_id_stays_unresolved_and_does_not_match():
    public, _ = episode("sample_00")
    o = oracle("sample_00")
    f = next(x for x in o["findings"] if x["affected_ids"][0].startswith("invoices:"))
    inv_id = _bare(f["affected_ids"][0])
    # make the same key exist in a second public table: a ledger row with row_id == invoice_id
    clash = copy.deepcopy(public)
    clash["ledger"].append(dict(clash["ledger"][0], row_id=inv_id))
    idx = PublicIndex.from_public(clash)
    assert normalize_ref(inv_id, idx) == inv_id
    _, unknown = normalize_refs([inv_id], idx)
    assert unknown == (inv_id,)
    # with the prefix it is unambiguous and still matches
    from auditgym.grader import Grader

    _, truth = episode("sample_00")
    g = Grader()
    bare = dict(f, affected_ids=[_bare(x) for x in f["affected_ids"]])
    r = g.score(with_findings("sample_00", [bare]), truth=truth, public=clash)
    assert r.tp == 0 and r.finding_reasons == ["unknown_id"]
    r = g.score(with_findings("sample_00", [f]), truth=truth, public=clash)
    assert r.tp == 1


def test_bare_ids_without_public_data_are_left_alone():
    _, truth = episode("sample_00")
    from auditgym.grader import Grader, oracle_findings

    o = oracle_findings(truth)
    for f in o["findings"]:
        f["affected_ids"] = [_bare(x) for x in f["affected_ids"]]
    r = Grader().score(o, truth=truth)
    assert r.tp == 0


@pytest.mark.parametrize("name", ERRORED)
def test_bare_ids_do_not_help_duplicates_or_flag_all(name):
    o = oracle(name)
    f = o["findings"][0]
    bare = dict(f, affected_ids=[_bare(x) for x in f["affected_ids"]])
    r = grade(with_findings(name, [f, bare]), name)  # same finding twice, two spellings
    assert r.tp == 1 and r.fp == 1 and r.finding_reasons[1] == "duplicate"
