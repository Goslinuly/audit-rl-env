"""The grader: validate → normalise → match → metrics → reward.

Two ways to call it:

    Grader().score(findings, truth=truth, public=public, inspection_steps=12)  # env backend
    Grader().score(findings, "episodes/dev/dev_03", inspection_steps=12)       # from disk

The grader is a pure function of its inputs: no randomness, no clock, no global state.
It lives outside the environment object (see ``auditgym.env.grading``); the agent gets only
``reward`` and only in ``train`` mode. Everything else in :class:`GradeResult` is diagnostics
for the runner and the grader log.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .constants import GRADER_VERSION, INVALID_REWARD, ISSUE_TYPES
from .matcher import match, normalize_finding, normalize_issue
from .normalize import PublicIndex
from .reward import metrics, terminal_reward
from .validate import validate_findings


@dataclass
class GradeResult:
    reward: float
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    matches: list[dict] = field(default_factory=list)  # {finding_index, issue_id, amount_diff}
    errors: list[str] = field(default_factory=list)  # validation errors (=> reward -1)
    valid: bool = True
    inspection_steps: int = 0
    n_findings: int = 0
    n_issues: int = 0
    finding_reasons: list[str] = field(default_factory=list)  # per finding: tp / why not
    missed_issue_ids: list[str] = field(default_factory=list)
    by_type: dict = field(default_factory=dict)  # type -> {tp, fp, fn}
    grader_version: str = GRADER_VERSION

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _currencies(public: dict | None, truth: dict) -> set[str] | None:
    if public and isinstance(public.get("manifest"), dict):
        cur = public["manifest"].get("currencies")
        if cur:
            return {c.upper() for c in cur}  # dict keys or list
    return None


class Grader:
    """Stateless; one instance may grade any number of episodes."""

    version = GRADER_VERSION

    def score(
        self,
        findings,
        episode_dir: str | Path | None = None,
        *,
        truth: dict | None = None,
        public: dict | None = None,
        inspection_steps: int = 0,
    ) -> GradeResult:
        if episode_dir is not None:
            from auditgym.generator import load_episode

            public, private = load_episode(Path(episode_dir))
            truth = private["truth"]
        if truth is None:
            raise ValueError("Grader.score needs truth (or episode_dir)")
        steps = max(0, int(inspection_steps))
        issues_raw = truth.get("issues", [])
        empty_types = {t: {"tp": 0, "fp": 0, "fn": 0} for t in ISSUE_TYPES}

        errors = validate_findings(
            findings, episode_id=truth["episode_id"], currencies=_currencies(public, truth)
        )
        if errors:
            for i in issues_raw:
                empty_types[i["type"]]["fn"] += 1
            return GradeResult(
                reward=INVALID_REWARD, precision=0.0, recall=0.0, f1=0.0,
                tp=0, fp=0, fn=len(issues_raw), errors=errors, valid=False,
                inspection_steps=steps,
                n_findings=len(findings["findings"])
                if isinstance(findings, dict) and isinstance(findings.get("findings"), list)
                else 0,
                n_issues=len(issues_raw),
                missed_issue_ids=sorted(i["issue_id"] for i in issues_raw),
                by_type=empty_types,
            )

        index = PublicIndex.from_public(public)
        items = findings["findings"]
        norm_f = [normalize_finding(n, f, index) for n, f in enumerate(items)]
        norm_i = [normalize_issue(i) for i in issues_raw]
        outcome = match(norm_f, norm_i)

        tp = len(outcome.pairs)
        fp = len(items) - tp
        fn = len(issues_raw) - tp
        precision, recall, f1 = metrics(tp, fp, fn)
        reward = terminal_reward(f1, steps)

        matched_issues = {j for _, j in outcome.pairs}
        by_type = empty_types
        for fi, f in enumerate(norm_f):
            by_type[f.type]["tp" if outcome.reasons[fi] == "tp" else "fp"] += 1
        for j, issue in enumerate(norm_i):
            if j not in matched_issues:
                by_type[issue.type]["fn"] += 1

        return GradeResult(
            reward=reward,
            precision=float(precision),
            recall=float(recall),
            f1=float(f1),
            tp=tp,
            fp=fp,
            fn=fn,
            matches=[
                {
                    "finding_index": fi,
                    "issue_id": norm_i[j].issue_id,
                    "amount_diff": abs(norm_f[fi].amount - norm_i[j].amount),
                }
                for fi, j in outcome.pairs
            ],
            errors=[],
            valid=True,
            inspection_steps=steps,
            n_findings=len(items),
            n_issues=len(issues_raw),
            finding_reasons=list(outcome.reasons),
            missed_issue_ids=sorted(
                norm_i[j].issue_id for j in range(len(norm_i)) if j not in matched_issues
            ),
            by_type=by_type,
        )


def score(findings, episode_dir=None, **kwargs) -> GradeResult:
    """Module-level shortcut for ``Grader().score(...)``."""
    return Grader().score(findings, episode_dir, **kwargs)


def reason_counts(results) -> Counter:
    """Aggregate ``finding_reasons`` over many results (failure analysis helper)."""
    c: Counter = Counter()
    for r in results:
        rs = r.finding_reasons if isinstance(r, GradeResult) else r.get("finding_reasons", [])
        c.update(rs)
    return c
