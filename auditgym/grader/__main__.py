"""Grader CLI.

    python -m auditgym.grader score --episode episodes/dev/dev_03 --findings answer.json [--steps 12]
    python -m auditgym.grader selfcheck [episodes/train episodes/dev ...]

``score`` prints the full GradeResult as JSON. ``selfcheck`` runs the reference answers on every
episode found (oracle = 1.0, silence, flag-all < 0, permutation, remap) and exits non-zero on any
violation.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from auditgym.generator import load_episode
from auditgym.generator.transforms import remap_ids, shuffle_rows

from .constants import GRADER_VERSION
from .grader import Grader
from .oracle import oracle_findings


def _flag_all(public: dict, truth: dict) -> dict:
    base = public["manifest"]["base_currency"]
    items = []
    types = ("payment_allocation", "fx_conversion", "period_cutoff")
    for inv in public["invoices"]:
        items.append({"type": "duplicate_invoice", "affected_ids": [f"invoices:{inv['invoice_id']}"],
                      "claimed_amount_minor": inv["total_minor"], "currency": inv["currency"],
                      "evidence_ids": [f"invoices:{inv['invoice_id']}"]})
    for k, pay in enumerate(public["payments"]):
        t = types[k % 3]
        items.append({"type": t, "affected_ids": [f"payments:{pay['payment_id']}"],
                      "claimed_amount_minor": abs(pay["amount_minor"]),
                      "currency": pay["currency"] if t == "payment_allocation" else base,
                      "evidence_ids": [f"payments:{pay['payment_id']}"]})
    random.Random(0).shuffle(items)
    return {"episode_id": truth["episode_id"], "findings": items[:30]}


def _episode_dirs(roots: list[str]) -> list[Path]:
    out = []
    for r in roots:
        p = Path(r)
        if (p / "private" / "truth.json").exists():
            out.append(p)
        else:
            out += sorted(q.parent.parent for q in p.glob("**/private/truth.json"))
    return out


def selfcheck(roots: list[str]) -> int:
    g = Grader()
    failures = 0
    dirs = _episode_dirs(roots or ["episodes"])
    print(f"grader {GRADER_VERSION}: {len(dirs)} episodes")
    print(f"{'episode':<14}{'issues':>7}{'oracle':>8}{'silence':>9}{'flag_all':>10}{'remap':>7}  status")
    for d in dirs:
        public, private = load_episode(d)
        truth = private["truth"]
        o = oracle_findings(truth)
        r_o = g.score(o, truth=truth, public=public).reward
        r_s = g.score({"episode_id": truth["episode_id"], "findings": []}, truth=truth, public=public).reward
        r_f = g.score(_flag_all(public, truth), truth=truth, public=public).reward
        rev = dict(o, findings=list(reversed(o["findings"])))
        r_rev = g.score(rev, truth=truth, public=public).reward
        pub2, tr2, _ = remap_ids(public, truth, seed=1)
        r_m = g.score(oracle_findings(tr2), truth=tr2, public=shuffle_rows(pub2, seed=2)).reward
        want_s = 1.0 if not truth["issues"] else -1.0
        ok = r_o == 1.0 and r_s == want_s and r_f < 0 and r_rev == r_o and r_m == 1.0
        failures += not ok
        print(f"{d.name:<14}{len(truth['issues']):>7}{r_o:>8.3f}{r_s:>9.3f}{r_f:>10.3f}{r_m:>7.3f}  "
              f"{'ok' if ok else 'FAIL'}")
    print("selfcheck:", "passed" if not failures else f"{failures} episode(s) FAILED")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m auditgym.grader")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="grade one findings.json against one episode")
    s.add_argument("--episode", required=True)
    s.add_argument("--findings", required=True)
    s.add_argument("--steps", type=int, default=0, help="inspection_steps (default 0)")
    c = sub.add_parser("selfcheck", help="oracle/silence/flag-all/remap on every episode")
    c.add_argument("roots", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "score":
        findings = json.loads(Path(a.findings).read_text(encoding="utf-8"))
        res = Grader().score(findings, a.episode, inspection_steps=a.steps)
        print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
        return 0
    return selfcheck(a.roots)


if __name__ == "__main__":
    sys.exit(main())
