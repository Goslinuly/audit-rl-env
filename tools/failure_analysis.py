"""Measured failure analysis: ablated Reconciler variants through the real AuditEnv + Grader.

    python tools/failure_analysis.py                    # train + dev, Markdown to stdout
    python tools/failure_analysis.py --json out.json    # also machine-readable totals

Every variant reads the same public pages through AuditEnv (train mode) and is scored by
the real grader. Grader diagnostics (finding_reasons, by_type) come from env.grade_log,
which is operator-side and never reaches the policy. False positives are additionally
attributed to generator distractor kinds using private/provenance.json, and missed issues
to their type; this attribution happens after grading, outside the agent loop.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auditgym.env import AuditEnv  # noqa: E402
from auditgym.policies.ablations import VARIANTS, AblatedReconciler  # noqa: E402
from auditgym.runner.core import run_episode  # noqa: E402

TYPES = ("duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff")
SHORT = {"duplicate_invoice": "dup", "payment_allocation": "alloc",
         "fx_conversion": "fx", "period_cutoff": "cutoff"}


def episodes(splits):
    for split in splits:
        for path in sorted((ROOT / "episodes" / split).iterdir()):
            if (path / "public" / "manifest.json").is_file():
                yield path


def distractor_index(episode):
    provenance = json.loads((episode / "private" / "provenance.json").read_text("utf-8"))
    index = defaultdict(set)
    for item in provenance.get("distractors", []):
        for doc in item["ids"]:
            index[doc].add(item["kind"])
    return index


def run_variant(flags, paths):
    total = {"tp": 0, "fp": 0, "fn": 0, "reward": 0.0, "f1": 0.0, "precision": 0.0,
             "recall": 0.0, "episodes": 0}
    by_type = {t: Counter() for t in TYPES}
    reasons, fp_sources = Counter(), Counter()
    for episode in paths:
        traps = distractor_index(episode)
        with AuditEnv(mode="train") as env:
            rows, result = run_episode(env, AblatedReconciler(flags), policy_name="ablation",
                                       reset_kwargs={"episode_dir": episode})
            grade = env.grade_log[-1]
        findings = rows[-1]["action"]["args"]["findings"]["findings"]
        total["episodes"] += 1
        for key in ("tp", "fp", "fn"):
            total[key] += grade[key]
        for key in ("reward", "f1", "precision", "recall"):
            total[key] += grade[key]
        for kind, counts in grade["by_type"].items():
            by_type[kind].update(counts)
        for finding, reason in zip(findings, grade["finding_reasons"]):
            if reason == "tp":
                continue
            reasons[reason] += 1
            kinds = set().union(*(traps.get(doc, set()) for doc in finding["affected_ids"]))
            fp_sources[",".join(sorted(kinds)) or "not a distractor"] += 1
    n = total["episodes"]
    tp, fp, fn = total["tp"], total["fp"], total["fn"]
    micro_p = tp / (tp + fp) if tp + fp else 1.0
    micro_r = tp / (tp + fn) if tp + fn else 1.0
    return {
        "flags": list(flags), "episodes": n, "tp": tp, "fp": fp, "fn": fn,
        "mean_precision": total["precision"] / n, "mean_recall": total["recall"] / n,
        "mean_f1": total["f1"] / n, "mean_reward": total["reward"] / n,
        "micro_precision": micro_p, "micro_recall": micro_r,
        "micro_f1": 2 * micro_p * micro_r / (micro_p + micro_r) if micro_p + micro_r else 0.0,
        "by_type": {k: dict(v) for k, v in by_type.items()},
        "fp_reasons": dict(reasons), "fp_sources": dict(fp_sources),
    }


def markdown(report):
    lines = ["| Вариант | P (micro) | R (micro) | F1 (mean) | reward (mean) | TP | FP | FN | FP по типам | FN по типам |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for name, r in report.items():
        fp_types = ", ".join(f"{SHORT[t]} {r['by_type'][t].get('fp', 0)}" for t in TYPES
                             if r["by_type"][t].get("fp", 0)) or "—"
        fn_types = ", ".join(f"{SHORT[t]} {r['by_type'][t].get('fn', 0)}" for t in TYPES
                             if r["by_type"][t].get("fn", 0)) or "—"
        lines.append(f"| {name} | {r['micro_precision']:.3f} | {r['micro_recall']:.3f} | "
                     f"{r['mean_f1']:.3f} | {r['mean_reward']:.3f} | {r['tp']} | {r['fp']} | "
                     f"{r['fn']} | {fp_types} | {fn_types} |")
    lines += ["", "| Вариант | причины FP (grader finding_reasons) | источник FP (provenance) |",
              "|---|---|---|"]
    for name, r in report.items():
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(r["fp_reasons"].items())) or "—"
        sources = ", ".join(f"{k} {v}" for k, v in sorted(r["fp_sources"].items())) or "—"
        lines.append(f"| {name} | {reasons} | {sources} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--splits", nargs="+", default=["train", "dev"])
    parser.add_argument("--json", type=Path, help="Write full per-variant totals here")
    args = parser.parse_args(argv)
    paths = list(episodes(args.splits))
    report = {name: run_variant(flags, paths) for name, flags in VARIANTS.items()}
    print(f"{len(paths)} episodes ({'+'.join(args.splits)}); P/R from summed TP/FP/FN "
          f"(the grader sets per-episode P=R=0 when an episode has no issues and no "
          f"findings), F1/reward are per-episode means.\n")
    print(markdown(report))
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
