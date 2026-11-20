from copy import deepcopy

import pytest

from auditgym import ENV_VERSION
from auditgym.runner.bundle import STAGES, validate_evidence


def evidence():
    return {"status": "passed", "env_version": ENV_VERSION, "source_sha256": "snapshot",
            "stages": [{"name": name, "status": "passed", "exit_code": 0} for name in STAGES]}


def test_release_requires_matching_source_and_enforced_container_limits():
    validate_evidence(evidence(), "snapshot", {
        "Memory": 4294967296, "NanoCpus": 2000000000, "NetworkMode": "none"})


@pytest.mark.parametrize("field,value", [
    ("Memory", 0), ("NanoCpus", 0), ("NetworkMode", "bridge"),
])
def test_release_rejects_missing_resource_or_network_isolation(field, value):
    constraints = {"Memory": 4294967296, "NanoCpus": 2000000000, "NetworkMode": "none"}
    constraints[field] = value
    with pytest.raises(ValueError, match="constraints"):
        validate_evidence(evidence(), "snapshot", constraints)


@pytest.mark.parametrize("kind", ["failed", "source", "version", "missing", "exit_code"])
def test_release_rejects_stale_or_failed_checks(kind):
    report = deepcopy(evidence())
    if kind == "failed":
        report["status"] = "failed"
    elif kind == "source":
        report["source_sha256"] = "different"
    elif kind == "version":
        report["env_version"] = "other"
    elif kind == "missing":
        report["stages"].pop()
    else:
        report["stages"][0]["exit_code"] = 1
    with pytest.raises(ValueError):
        validate_evidence(report, "snapshot")
