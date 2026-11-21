"""Per-policy summary of a runner results.csv as a Markdown table.

    python tools/summarize_results.py artifacts/results.csv

P, R, F1, reward, return, steps and time are per-episode means. P/R micro are computed from
summed TP/FP/FN: the grader reports per-episode P = R = 0 for an episode without issues
even when the answer is correct (empty), so the per-episode mean understates them.
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ORDER = ("Oracle", "Reconciler", "RandomExplorer", "FlagAll")


def mean(values):
    return sum(values) / len(values) if values else float("nan")


def summarize(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    groups = defaultdict(list)
    for row in rows:
        groups[row["policy"]].append(row)
    names = [n for n in ORDER if n in groups] + sorted(set(groups) - set(ORDER))
    lines = ["| Политика | эпизоды | P | R | F1 | reward | return | шаги | время, с | "
             "P micro | R micro | находок всего |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in names:
        group = groups[name]

        def col(key, group=group):
            return mean([float(r[key]) for r in group])

        tp, fp, fn = (sum(int(r[k]) for r in group) for k in ("tp", "fp", "fn"))
        micro_p = f"{tp / (tp + fp):.3f}" if tp + fp else "— (0 findings)"
        micro_r = f"{tp / (tp + fn):.3f}" if tp + fn else "—"
        seed = {r["policy_seed"] for r in group if r.get("policy_seed")}
        label = name + (f" (seed {', '.join(sorted(seed))})" if seed else "")
        lines.append(f"| {label} | {len(group)} | {col('precision'):.3f} | {col('recall'):.3f} | "
                     f"{col('f1'):.3f} | {col('reward'):.3f} | {col('return'):.3f} | "
                     f"{col('steps'):.1f} | {col('time_s'):.3f} | {micro_p} | {micro_r} | {tp + fp} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path)
    args = parser.parse_args(argv)
    print(summarize(args.results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
