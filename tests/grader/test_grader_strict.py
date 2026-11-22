"""Grader 2.0.0: exact comparison, and a wrong finding is a false positive, not -1 for all.

* IDs and currencies are compared exactly: no trim, no case folding, no aliases, no prefixes;
* an unknown type / currency / ID is a false positive, the other findings are still credited;
* unknown extra keys are ignored.
"""

from __future__ import annotations

import copy

import pytest
from grader_helpers import episode, grade, names, oracle, silent, with_findings

from auditgym.grader import GRADER_VERSION
from auditgym.grader.constants import TOLERANCE_BY_TYPE

ERRORED = names(clean=False)
CLEAN = names(clean=True)


def _bare(ref: str) -> str:
    return ref.partition(":")[2]


def test_version_bumped():
    assert GRADER_VERSION == "2.0.0"


@pytest.mark.parametrize("name", ERRORED)
def test_published_tolerance_is_what_truth_says(name):
    for issue in episode(name)[1]["issues"]:
        assert issue["tolerance_minor"] == TOLERANCE_BY_TYPE[issue["type"]]


# --- one bad finding is one false positive --------------------------------------------------
BAD_CONTENT = [
    {"type": "fraud"}, {"type": "Duplicate_Invoice"}, {"type": ""},
    {"currency": "CHF"}, {"currency": "TENGE"}, {"currency": ""},
    {"affected_ids": []}, {"affected_ids": [""]}, {"affected_ids": ["x" * 500]},
    {"affected_ids": [f"ledger:L{i}" for i in range(11)]},
    {"evidence_ids": []}, {"evidence_ids": [""]}, {"evidence_ids": ["ledger:NOPE"]},
    {"claimed_amount_minor": 10**30}, {"claimed_amount_minor": -1},
]


@pytest.mark.parametrize("change", BAD_CONTENT, ids=lambda c: str(c)[:40])
@pytest.mark.parametrize("name", ["sample_00", "train_09"])
def test_bad_content_is_one_false_positive(name, change):
    o = copy.deepcopy(oracle(name))
    n = len(o["findings"])
    o["findings"].append({**o["findings"][0], **change})
    r = grade(o, name)
    assert r.valid and (r.tp, r.fp, r.fn) == (n, 1, 0)
    assert sum(v["fp"] for v in r.by_type.values()) == 1


@pytest.mark.parametrize("name", CLEAN)
def test_any_accusation_on_clean_books_is_minus_one_but_graded(name):
    f = oracle("sample_00")["findings"][0]
    r = grade(with_findings(name, [dict(f, currency="CHF")]), name)
    assert r.valid and r.fp == 1 and r.reward == -1.0


@pytest.mark.parametrize("bad", [840, None, ["USD"], True])
def test_wrong_type_of_value_is_structural(bad):
    f = oracle("sample_00")["findings"][0]
    for key in ("currency", "type"):
        r = grade(with_findings("sample_00", [dict(f, **{key: bad})]), "sample_00")
        assert not r.valid and r.reward == -1.0 and r.errors


# --- exact comparison -----------------------------------------------------------------------
def _spellings(ref: str) -> list[str]:
    table, _, key = ref.partition(":")
    return [f" {ref}", f"{ref} ", f"{table.upper()}:{key}", f"{table}: {key}", key, ref.lower()]


@pytest.mark.parametrize("name", ERRORED)
def test_other_spellings_of_an_id_do_not_match(name):
    f = oracle(name)["findings"][0]
    for field in ("affected_ids", "evidence_ids"):
        for other in _spellings(f[field][0]):
            if other == f[field][0]:
                continue
            r = grade(with_findings(name, [dict(f, **{field: [other, *f[field][1:]]})]), name)
            assert r.valid and r.tp == 0 and r.finding_reasons == ["unknown_id"], other


def test_doc_id_is_not_an_alias_in_the_grader():
    public, _ = episode("sample_00")
    by_key = {i["invoice_id"]: i["doc_id"] for i in public["invoices"]}
    f = next(x for x in oracle("sample_00")["findings"] if x["type"] == "duplicate_invoice")
    doc = "invoices:" + by_key[_bare(f["affected_ids"][0])]
    assert grade(with_findings("sample_00", [dict(f, affected_ids=[doc])]), "sample_00").tp == 0


@pytest.mark.parametrize("name", ERRORED)
def test_currency_is_exact(name):
    for f in oracle(name)["findings"]:
        for cur in (f["currency"].lower(), f" {f['currency']}", f["currency"] + " "):
            r = grade(with_findings(name, [dict(f, currency=cur)]), name)
            assert r.valid and r.tp == 0 and r.finding_reasons == ["currency"]


# --- extra keys -----------------------------------------------------------------------------
@pytest.mark.parametrize("name", ERRORED)
def test_extra_keys_are_ignored(name):
    o = oracle(name)
    base = grade(o, name)
    noisy = copy.deepcopy(o)
    noisy["note"] = "x"
    noisy["reward"] = 1.0
    for f in noisy["findings"]:
        f["confidence"] = 0.97
        f["reward"] = 1.0
    before = copy.deepcopy(noisy)
    r = grade(noisy, name)
    assert r.valid and r.reward == base.reward == 1.0
    assert noisy == before


@pytest.mark.parametrize("key", ["episode_id", "findings"])
def test_missing_top_level_field_is_structural(key):
    sub = silent("sample_00")
    del sub[key]
    r = grade(sub, "sample_00")
    assert not r.valid and r.reward == -1.0
