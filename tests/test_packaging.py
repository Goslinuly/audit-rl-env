import json
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


@pytest.mark.parametrize("filename", sorted(p.name for p in
                         (Path(__file__).resolve().parents[1] / "schemas").glob("*.schema.json")))
def test_packaged_contract_matches_external_schema(filename):
    packed = json.loads(files("auditgym.schemas").joinpath(filename).read_text(encoding="utf-8"))
    external = json.loads((Path(__file__).resolve().parents[1] / "schemas" / filename).read_text())
    assert packed == external
    Draft202012Validator.check_schema(packed)
