"""JSON Schemas: well-formed, match every published episode, and agree with the validator."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest
from grader_helpers import EPISODE_DIRS, ROOT, episode, flag_all, mutate, oracle
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from auditgym.grader import validate_findings

SCHEMAS = {p.name.removesuffix(".schema.json"): json.loads(p.read_text(encoding="utf-8"))
           for p in (ROOT / "schemas").glob("*.schema.json")}
REQUIRED = {"config", "manifest", "policy", "findings", "truth", "provenance", "action",
            "observation", "trajectory_line", "records"}
REGISTRY = Registry().with_resources(
    (s["$id"], Resource.from_contents(s)) for s in SCHEMAS.values()
)


def validator(name: str, sub: str | None = None) -> Draft202012Validator:
    schema = SCHEMAS[name] if sub is None else {**SCHEMAS[name], "$ref": f"#/$defs/{sub}"}
    return Draft202012Validator(schema, registry=REGISTRY)


def test_all_required_schemas_exist_and_are_valid():
    assert REQUIRED <= set(SCHEMAS)
    for name, schema in SCHEMAS.items():
        Draft202012Validator.check_schema(schema)
        assert schema.get("schema_version") == "1.0", name


@pytest.mark.parametrize("name", sorted(EPISODE_DIRS))
def test_published_episodes_match_schemas(name):
    public, truth = episode(name)
    prov = json.loads((EPISODE_DIRS[name] / "private" / "provenance.json").read_text(encoding="utf-8"))
    validator("manifest").validate(public["manifest"])
    validator("policy").validate(public["policy"])
    validator("truth").validate(truth)
    validator("provenance").validate(prov)
    for table, sub in (("ledger", "ledger_row"), ("invoices", "invoice"),
                       ("payments", "payment"), ("fx", "fx_rate")):
        v = validator("records", sub)
        for row in public[table]:
            v.validate(row)
    validator("findings").validate(oracle(name))


def test_configs_match_schema():
    for p in sorted((ROOT / "configs" / "presets").glob("*.json")):
        validator("config").validate(json.loads(p.read_text(encoding="utf-8")))


def test_trajectory_line_schema_rejects_leaks():
    line = {"episode_id": "ep-1", "step": 1, "action": {"name": "list_records", "args": {"table": "fx"}},
            "observation": {"step": 1}, "reward": 0.0, "terminated": False, "truncated": False,
            "policy": "Reconciler", "env_version": "1.0.0"}
    validator("trajectory_line").validate(line)
    for leak in ("seed", "truth", "issue_id", "expected_amount_minor"):
        assert not validator("trajectory_line").is_valid(dict(line, **{leak: 1}))


def test_findings_schema_and_validator_agree():
    """Same accept/reject decision on a corpus of valid, mutated and malformed submissions.

    The validator additionally checks two things a static schema cannot know: the episode's
    id and the manifest's currencies. The corpus keeps both consistent so the decisions match.
    """
    rng = random.Random(7)
    public, truth = episode("sample_00")
    eid = truth["episode_id"]
    base = oracle("sample_00")
    corpus = [base, {"episode_id": eid, "findings": []}, flag_all("sample_00")]
    for _ in range(300):
        sub = copy.deepcopy(base)
        sub["findings"] = [mutate(f, rng, public) for f in sub["findings"]]
        corpus.append(sub)
    f = base["findings"][0]
    corpus += [
        None, [], {"episode_id": eid}, {"findings": []},
        {"episode_id": eid, "findings": [f] * 31},
        {"episode_id": eid, "findings": [dict(f, claimed_amount_minor=1.0)]},
        {"episode_id": eid, "findings": [dict(f, claimed_amount_minor=True)]},
        {"episode_id": eid, "findings": [dict(f, evidence_ids=["x"] * 11)]},
        {"episode_id": eid, "findings": [dict(f, affected_ids=[])]},
        {"episode_id": eid, "findings": [dict(f, explanation="y" * 1001)]},
        {"episode_id": eid, "findings": [dict(f, extra=1)]},
        {"episode_id": eid, "findings": [{k: v for k, v in f.items() if k != "currency"}]},
        {"episode_id": eid, "findings": [dict(f, type="other")]},
        {"episode_id": eid, "findings": [dict(f, evidence_ids=["   "])]},
        {"episode_id": eid, "findings": [dict(f, currency=" usd ")]},
        {"episode_id": eid, "findings": [], "schema_version": "1.0"},
        {"episode_id": eid, "findings": [], "note": "x"},
    ]
    currencies = set(public["manifest"]["currencies"])
    v = validator("findings")
    # The one documented difference: JSON Schema treats 1.0 as an integer, the grader does not.
    float_sub = {"episode_id": eid, "findings": [dict(f, claimed_amount_minor=1.0)]}
    assert v.is_valid(float_sub)
    assert validate_findings(float_sub, episode_id=eid, currencies=currencies)
    def has_float_amount(sub) -> bool:  # `!=` would also drop True (True == 1.0)
        items = sub.get("findings") if isinstance(sub, dict) else None
        return isinstance(items, list) and any(
            isinstance(x, dict) and type(x.get("claimed_amount_minor")) is float for x in items)

    corpus = [s for s in corpus if not has_float_amount(s)]
    for sub in corpus:
        ok_validator = not validate_findings(sub, episode_id=eid, currencies=currencies)
        ok_schema = v.is_valid(sub)
        assert ok_validator == ok_schema, sub


def test_schemas_contain_no_private_paths():
    for p in Path(ROOT / "schemas").glob("*.json"):
        assert "private/" not in p.read_text(encoding="utf-8")
