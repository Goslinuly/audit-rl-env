"""Grader: findings validation, normalisation, matching, metrics and terminal reward.

    from auditgym.grader import Grader
    result = Grader().score(findings, truth=truth, public=public, inspection_steps=12)
    result.reward, result.f1, result.tp, result.fp, result.fn

Rules are published in DESIGN.md §4–5 and docs/grader.md.
"""

from .constants import (
    GRADER_VERSION,
    ISSUE_TYPES,
    MAX_EVIDENCE_IDS,
    MAX_EXPLANATION_CHARS,
    MAX_FINDINGS,
    STEP_COST,
    TOLERANCE_MINOR,
)
from .grader import Grader, GradeResult, reason_counts, score
from .normalize import PublicIndex, normalize_ref, normalize_refs
from .oracle import oracle_findings
from .reward import metrics, terminal_reward
from .validate import validate_findings

__all__ = [
    "GRADER_VERSION",
    "ISSUE_TYPES",
    "MAX_EVIDENCE_IDS",
    "MAX_EXPLANATION_CHARS",
    "MAX_FINDINGS",
    "STEP_COST",
    "TOLERANCE_MINOR",
    "GradeResult",
    "Grader",
    "PublicIndex",
    "metrics",
    "normalize_ref",
    "normalize_refs",
    "oracle_findings",
    "reason_counts",
    "score",
    "terminal_reward",
    "validate_findings",
]
