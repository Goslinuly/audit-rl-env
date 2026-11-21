"""One-to-one matching of findings to truth issues (DESIGN.md §4.2–4.3).

A pair (finding, issue) is *compatible* when all of these hold, checked in this order:

1. every ID in the finding (affected and evidence) exists in the public records;
2. same ``type``;
3. normalised ``affected_ids`` equal the issue's canonical ``affected_ids`` (as sets);
4. same currency (after trim + upper-case);
5. ``|claimed_amount_minor - expected_amount_minor| <= TOLERANCE_MINOR``;
6. at least one of the issue's ``evidence_sets`` is a subset of the normalised ``evidence_ids``.

``explanation`` is never read.

Over the bipartite graph of compatible pairs the grader takes a **maximum matching**
(so TP never depends on the order of findings), and among all maximum matchings the one
with the lexicographically smallest key

    (sum of |claimed - expected|, sum of finding positions, sum of issue ranks)

where a finding's position is its index in the submitted list and an issue's rank is its
index after sorting issues by ``issue_id``. This is a min-cost maximum flow, solved exactly by
successive shortest paths (Bellman–Ford). The tie-break only decides *which* finding gets
credit, never how many: TP = size of the maximum matching.

Every finding outside the matching is a false positive (including exact repeats of a matched
finding); every issue outside the matching is a false negative.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import TOLERANCE_MINOR
from .normalize import PublicIndex, normalize_currency, normalize_ref, normalize_refs

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


def normalize_finding(index_in_list: int, f: dict, idx: PublicIndex) -> NormFinding:
    """Normalised view of one validated finding. Only the known fields are read: unknown extra
    keys (``confidence``, …) and ``explanation`` are dropped here and never affect matching."""
    affected, unk_a = normalize_refs(f["affected_ids"], idx)
    evidence, unk_e = normalize_refs(f["evidence_ids"], idx)
    return NormFinding(
        index=index_in_list,
        type=f["type"],
        affected=frozenset(affected),
        evidence=frozenset(evidence),
        unknown=tuple(sorted(set(unk_a) | set(unk_e))),
        amount=f["claimed_amount_minor"],
        currency=normalize_currency(f["currency"]),
    )


def normalize_issue(issue: dict) -> NormIssue:
    return NormIssue(
        issue_id=issue["issue_id"],
        type=issue["type"],
        affected=frozenset(normalize_ref(x) for x in issue["affected_ids"]),
        evidence_sets=tuple(frozenset(normalize_ref(x) for x in s) for s in issue["evidence_sets"]),
        amount=int(issue["expected_amount_minor"]),
        currency=normalize_currency(issue["currency"]),
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
    if abs(f.amount - issue.amount) > TOLERANCE_MINOR:
        return R_AMOUNT
    if not any(s <= f.evidence for s in issue.evidence_sets):
        return R_EVIDENCE
    return None


def _min_cost_max_matching(n_left: int, n_right: int, edges: dict[tuple[int, int], int]):
    """Exact min-cost maximum bipartite matching by successive shortest paths."""
    src, sink = 0, n_left + n_right + 1
    n = sink + 1
    graph: list[list[int]] = [[] for _ in range(n)]
    to: list[int] = []
    cap: list[int] = []
    cost: list[int] = []

    def add(u: int, v: int, c: int) -> None:
        graph[u].append(len(to))
        to.append(v), cap.append(1), cost.append(c)
        graph[v].append(len(to))
        to.append(u), cap.append(0), cost.append(-c)

    for i in range(n_left):
        add(src, 1 + i, 0)
    for j in range(n_right):
        add(1 + n_left + j, sink, 0)
    for (i, j), c in sorted(edges.items()):
        add(1 + i, 1 + n_left + j, c)

    while True:
        inf = None
        dist: list[int | None] = [inf] * n
        prev_edge = [-1] * n
        dist[src] = 0
        for _ in range(n - 1):  # Bellman–Ford: residual costs may be negative
            changed = False
            for u in range(n):
                if dist[u] is None:
                    continue
                for e in graph[u]:
                    if cap[e] > 0:
                        nd = dist[u] + cost[e]
                        v = to[e]
                        if dist[v] is None or nd < dist[v]:
                            dist[v], prev_edge[v], changed = nd, e, True
            if not changed:
                break
        if dist[sink] is None:
            break
        v = sink
        while v != src:
            e = prev_edge[v]
            cap[e] -= 1
            cap[e ^ 1] += 1
            v = to[e ^ 1]

    pairs = []
    for i in range(n_left):
        for e in graph[1 + i]:
            v = to[e]
            if 1 + n_left <= v <= n_left + n_right and cap[e] == 0 and e % 2 == 0:
                pairs.append((i, v - 1 - n_left))
    return sorted(pairs)


@dataclass(frozen=True)
class MatchOutcome:
    pairs: tuple[tuple[int, int], ...]  # (finding index, issue position in `issues`)
    reasons: tuple[str, ...]  # per finding: "tp" or a reason from CHECK_ORDER / duplicate


def match(findings: list[NormFinding], issues: list[NormIssue]) -> MatchOutcome:
    order = sorted(range(len(issues)), key=lambda j: issues[j].issue_id)
    rank = {j: r for r, j in enumerate(order)}
    n_f, n_i = len(findings), len(issues)
    k2 = n_i * n_i + 1
    k1 = (n_f * n_f + 1) * k2
    edges: dict[tuple[int, int], int] = {}
    compatible_any = [False] * n_f
    for fi, f in enumerate(findings):
        for ij, issue in enumerate(issues):
            if first_failed_check(f, issue) is None:
                diff = abs(f.amount - issue.amount)
                edges[(fi, ij)] = diff * k1 + fi * k2 + rank[ij]
                compatible_any[fi] = True
    pairs = _min_cost_max_matching(n_f, n_i, edges)
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
