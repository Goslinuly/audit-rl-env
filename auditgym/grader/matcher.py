"""One-to-one matching of findings to truth issues (DESIGN.md §4).

A pair (finding, issue) is *compatible* when all of these hold, checked in this order:

1. every ID in the finding (affected and evidence) exists in the public records;
2. same ``type`` (exact string; an unknown type string is simply never equal);
3. the set of ``affected_ids`` equals the issue's canonical set;
4. same currency (exact string);
5. ``|claimed_amount_minor - expected_amount_minor| <= tolerance_minor`` of the issue;
6. at least one of the issue's ``evidence_sets`` is a subset of ``evidence_ids``.

``explanation`` is never read.

Over the bipartite graph of compatible pairs the grader takes a **maximum matching** and,
among all maximum matchings, the one whose sorted sequence of pairs ``(issue_id, index of
the finding in the submitted list)`` is lexicographically smallest (issue_id by Unicode code
points). The tie-break only decides *which* finding gets credit, never how many.

Every finding outside the matching is a false positive (including exact repeats of a matched
finding); every issue outside the matching is a false negative.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import DEFAULT_TOLERANCE_MINOR
from .normalize import PublicIndex, normalize_refs

# Reasons a finding was not credited, in the order the checks run (used in diagnostics).
R_UNKNOWN_ID = "unknown_id"
R_TYPE = "type"
R_AFFECTED = "affected_ids"
R_CURRENCY = "currency"
R_AMOUNT = "amount"
R_EVIDENCE = "evidence"
R_DUPLICATE = "duplicate"  # compatible, but the issue was credited to another finding
R_NO_ISSUES = "no_issues"  # the episode has no issues at all
CHECK_ORDER = (R_UNKNOWN_ID, R_TYPE, R_AFFECTED, R_CURRENCY, R_AMOUNT, R_EVIDENCE)


@dataclass(frozen=True)
class NormFinding:
    index: int
    type: str
    affected: frozenset[str]
    evidence: frozenset[str]
    unknown: tuple[str, ...]
    amount: int
    currency: str


@dataclass(frozen=True)
class NormIssue:
    issue_id: str
    type: str
    affected: frozenset[str]
    evidence_sets: tuple[frozenset[str], ...]
    amount: int
    currency: str
    tolerance: int = DEFAULT_TOLERANCE_MINOR


def normalize_finding(index_in_list: int, f: dict, idx: PublicIndex) -> NormFinding:
    """Set view of one validated finding. Only the known fields are read: unknown extra
    keys (``confidence``, …) and ``explanation`` are dropped here and never affect matching."""
    affected, unk_a = normalize_refs(f["affected_ids"], idx)
    evidence, unk_e = normalize_refs(f["evidence_ids"], idx)
    return NormFinding(
        index=index_in_list,
        type=f["type"],
        affected=affected,
        evidence=evidence,
        unknown=tuple(sorted(set(unk_a) | set(unk_e))),
        amount=f["claimed_amount_minor"],
        currency=f["currency"],
    )


def normalize_issue(issue: dict) -> NormIssue:
    return NormIssue(
        issue_id=issue["issue_id"],
        type=issue["type"],
        affected=frozenset(issue["affected_ids"]),
        evidence_sets=tuple(frozenset(s) for s in issue["evidence_sets"]),
        amount=int(issue["expected_amount_minor"]),
        currency=issue["currency"],
        tolerance=max(0, int(issue.get("tolerance_minor", DEFAULT_TOLERANCE_MINOR))),
    )


def first_failed_check(f: NormFinding, issue: NormIssue) -> str | None:
    """``None`` if compatible, else the first failed check (see :data:`CHECK_ORDER`)."""
    if f.unknown:
        return R_UNKNOWN_ID
    if f.type != issue.type:
        return R_TYPE
    if f.affected != issue.affected:
        return R_AFFECTED
    if f.currency != issue.currency:
        return R_CURRENCY
    if abs(f.amount - issue.amount) > issue.tolerance:
        return R_AMOUNT
    if not any(s <= f.evidence for s in issue.evidence_sets):
        return R_EVIDENCE
    return None


def _max_size(issues: list[int], edges: dict[int, list[int]], used: set[int]) -> int:
    """Size of a maximum matching of ``issues`` to findings not in ``used`` (Kuhn)."""
    owner: dict[int, int] = {}

    def augment(j: int, seen: set[int]) -> bool:
        for fi in edges[j]:
            if fi in used or fi in seen:
                continue
            seen.add(fi)
            if fi not in owner or augment(owner[fi], seen):
                owner[fi] = j
                return True
        return False

    return sum(augment(j, set()) for j in issues)


def _lexicographic_max_matching(order: list[int], edges: dict[int, list[int]]) -> list[tuple[int, int]]:
    """Maximum matching with the smallest sorted sequence of (issue, finding index).

    ``order`` — issue positions sorted by issue_id; ``edges[j]`` — ascending finding indexes.
    Greedy with an exact feasibility check: fix the earliest (issue, finding) pair that can
    still be extended to a maximum matching.
    """
    target = _max_size(order, edges, set())
    used: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for pos, j in enumerate(order):
        rest = order[pos + 1 :]
        for fi in edges[j]:
            if fi in used:
                continue
            if len(pairs) + 1 + _max_size(rest, edges, used | {fi}) == target:
                used.add(fi)
                pairs.append((fi, j))
                break
    return sorted(pairs)


@dataclass(frozen=True)
class MatchOutcome:
    pairs: tuple[tuple[int, int], ...]  # (finding index, issue position in `issues`)
    reasons: tuple[str, ...]  # per finding: "tp" or a reason from CHECK_ORDER / duplicate


def match(findings: list[NormFinding], issues: list[NormIssue]) -> MatchOutcome:
    order = sorted(range(len(issues)), key=lambda j: issues[j].issue_id)
    rank = {j: r for r, j in enumerate(order)}
    edges: dict[int, list[int]] = {j: [] for j in range(len(issues))}
    compatible_any = [False] * len(findings)
    for fi, f in enumerate(findings):
        for ij, issue in enumerate(issues):
            if first_failed_check(f, issue) is None:
                edges[ij].append(fi)
                compatible_any[fi] = True
    pairs = _lexicographic_max_matching(order, edges)
    matched = {fi for fi, _ in pairs}

    reasons: list[str] = []
    for fi, f in enumerate(findings):
        if fi in matched:
            reasons.append("tp")
        elif compatible_any[fi]:
            reasons.append(R_DUPLICATE)
        elif not issues:
            reasons.append(R_NO_ISSUES)
        else:
            # The "closest" issue: the one that passes the most checks, ties by issue_id.
            best = max(
                (CHECK_ORDER.index(first_failed_check(f, issues[j])), -rank[j]) for j in order
            )
            reasons.append(CHECK_ORDER[best[0]])
    return MatchOutcome(pairs=tuple(pairs), reasons=tuple(reasons))
