"""Structural validation of ``findings.json``.

A structural error is exactly one of: a wrong value type, a missing required field, or an
exceeded limit (30 findings, 10 evidence ids per finding *before* removing repeats, 1000
Unicode code points of explanation). It makes the whole submission invalid: reward = -1,
errors go to the grader log (never to the agent in ``eval``).

Everything else is a matter of *matching*, not of structure: an unknown ``type`` string, a
currency code that is not in the episode, an unknown, empty or overlong ID, an empty
``affected_ids`` list, a huge amount — such a finding simply cannot match (false positive)
and the other findings are still credited.

Rules
-----
* top level: object with ``episode_id`` (string, equal to the episode's id) and ``findings``
  (list); optional ``schema_version`` (string); other keys are ignored;
* each finding is an object; ``type``, ``currency`` — strings; ``affected_ids``,
  ``evidence_ids`` — lists of strings; ``claimed_amount_minor`` — integer (``bool`` and
  ``float`` are rejected, even ``100.0``); ``explanation`` (optional) — string; other keys
  are ignored.

``schemas/findings.schema.json`` states the same rules; a test checks that both agree.
"""

from __future__ import annotations

from .constants import MAX_EVIDENCE_IDS, MAX_EXPLANATION_CHARS, MAX_FINDINGS

_REQUIRED = ("type", "affected_ids", "claimed_amount_minor", "currency", "evidence_ids")
MAX_ERRORS = 20


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _check_ids(value, field: str, n: int, *, max_items: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return [f"finding {n}: {field} must be a list"]
    if max_items is not None and len(value) > max_items:
        return [f"finding {n}: more than {max_items} {field}"]
    if not all(isinstance(x, str) for x in value):
        return [f"finding {n}: {field} must contain strings"]
    return []


def validate_findings(findings, *, episode_id: str | None) -> list[str]:
    """Return a list of human-readable errors; empty list means the submission is valid.

    ``episode_id`` — expected episode id; ``None`` skips the check (unit tests only).
    """
    if not isinstance(findings, dict):
        return ["findings must be a JSON object"]
    errors: list[str] = []
    if "episode_id" not in findings:
        errors.append("missing episode_id")
    elif not isinstance(findings["episode_id"], str):
        errors.append("episode_id must be a string")
    elif episode_id is not None and findings["episode_id"] != episode_id:
        errors.append("episode_id does not match the episode")
    if "schema_version" in findings and not isinstance(findings["schema_version"], str):
        errors.append("schema_version must be a string")

    items = findings.get("findings")
    if not isinstance(items, list):
        errors.append("findings.findings must be a list")
        return errors
    if len(items) > MAX_FINDINGS:
        errors.append(f"more than {MAX_FINDINGS} findings ({len(items)})")
        return errors

    for n, f in enumerate(items):
        if len(errors) >= MAX_ERRORS:
            break
        if not isinstance(f, dict):
            errors.append(f"finding {n}: must be an object")
            continue
        missing = [k for k in _REQUIRED if k not in f]
        if missing:
            errors.append(f"finding {n}: missing " + ", ".join(missing))
            continue
        for key in ("type", "currency"):
            if not isinstance(f[key], str):
                errors.append(f"finding {n}: {key} must be a string")
        errors += _check_ids(f["affected_ids"], "affected_ids", n)
        errors += _check_ids(f["evidence_ids"], "evidence_ids", n, max_items=MAX_EVIDENCE_IDS)
        if not _is_int(f["claimed_amount_minor"]):
            errors.append(f"finding {n}: claimed_amount_minor must be an integer")
        if "explanation" in f:
            expl = f["explanation"]
            if not isinstance(expl, str):
                errors.append(f"finding {n}: explanation must be a string")
            elif len(expl) > MAX_EXPLANATION_CHARS:
                errors.append(f"finding {n}: explanation longer than {MAX_EXPLANATION_CHARS}")
    return errors[:MAX_ERRORS]
