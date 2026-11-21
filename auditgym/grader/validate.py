"""Structural validation of ``findings.json``.

Any violation makes the whole submission invalid: reward = -1, errors go to the grader log
(never to the agent in ``eval``). The rules mirror ``schemas/findings.schema.json``; a test
checks that the schema and this module accept and reject the same documents.

Rules
-----
* top level: object with ``episode_id`` (must equal the episode's id) and ``findings`` (list);
  optional ``schema_version`` (string); no other keys;
* at most 30 findings;
* each finding is an object with these keys (``explanation`` optional); unknown extra keys
  inside a finding (e.g. ``confidence``) are ignored — never read, never an error — so one
  harmless extra field cannot turn the whole answer into -1. The top level stays strict;
  ``type`` — one of the four issue types (exact string);
  ``affected_ids`` — 1..10 non-empty strings of at most 128 characters;
  ``claimed_amount_minor`` — integer (``bool`` and ``float`` are rejected, even ``100.0``),
  absolute value at most 10^18;
  ``currency`` — string; after trim + upper-case it must look like an ISO-4217 code (three
  letters). A well-formed code that is not used in the episode is *not* a structural error:
  the finding is valid and simply cannot match (false positive, reason ``currency``);
  ``evidence_ids`` — 0..10 non-empty strings of at most 128 characters;
  ``explanation`` — string of at most 1000 characters.
"""

from __future__ import annotations

import re

from .constants import (
    ISSUE_TYPES,
    MAX_ABS_AMOUNT_MINOR,
    MAX_AFFECTED_IDS,
    MAX_EVIDENCE_IDS,
    MAX_EXPLANATION_CHARS,
    MAX_FINDINGS,
    MAX_ID_CHARS,
)

_TOP_KEYS = {"episode_id", "findings", "schema_version"}
_REQUIRED = ("type", "affected_ids", "claimed_amount_minor", "currency", "evidence_ids")
_ISO4217 = re.compile(r"^[A-Z]{3}$")
MAX_ERRORS = 20


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _check_ids(value, field: str, n: int, *, min_items: int, max_items: int) -> list[str]:
    if not isinstance(value, list):
        return [f"finding {n}: {field} must be a list"]
    if len(value) < min_items:
        return [f"finding {n}: {field} must contain at least {min_items} id"]
    if len(value) > max_items:
        return [f"finding {n}: more than {max_items} {field}"]
    for x in value:
        if not isinstance(x, str) or not x.strip():
            return [f"finding {n}: {field} must contain non-empty strings"]
        if len(x) > MAX_ID_CHARS:
            return [f"finding {n}: {field} entry longer than {MAX_ID_CHARS} characters"]
    return []


def validate_findings(findings, *, episode_id: str | None) -> list[str]:
    """Return a list of human-readable errors; empty list means the submission is valid.

    ``episode_id`` — expected episode id; ``None`` skips the check (unit tests only).
    """
    if not isinstance(findings, dict):
        return ["findings must be a JSON object"]
    errors: list[str] = []
    extra = set(findings) - _TOP_KEYS
    if extra:
        errors.append("unexpected top-level keys: " + ", ".join(sorted(map(str, extra))))
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
        if f["type"] not in ISSUE_TYPES:
            errors.append(f"finding {n}: unknown type")
        errors += _check_ids(f["affected_ids"], "affected_ids", n,
                             min_items=1, max_items=MAX_AFFECTED_IDS)
        errors += _check_ids(f["evidence_ids"], "evidence_ids", n,
                             min_items=0, max_items=MAX_EVIDENCE_IDS)
        amount = f["claimed_amount_minor"]
        if not _is_int(amount):
            errors.append(f"finding {n}: claimed_amount_minor must be an integer")
        elif abs(amount) > MAX_ABS_AMOUNT_MINOR:
            errors.append(f"finding {n}: claimed_amount_minor out of range")
        cur = f["currency"]
        if not isinstance(cur, str):
            errors.append(f"finding {n}: currency must be a string")
        else:
            code = cur.strip().upper()
            if not _ISO4217.match(code):
                errors.append(f"finding {n}: currency must be an ISO-4217 code")
        if "explanation" in f:
            expl = f["explanation"]
            if not isinstance(expl, str):
                errors.append(f"finding {n}: explanation must be a string")
            elif len(expl) > MAX_EXPLANATION_CHARS:
                errors.append(f"finding {n}: explanation longer than {MAX_EXPLANATION_CHARS}")
    return errors[:MAX_ERRORS]
