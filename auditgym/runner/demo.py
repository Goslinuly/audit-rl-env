"""Terminal walkthrough of a real Reconciler run and four-policy comparison."""

import argparse
import json
import time
from pathlib import Path

from auditgym import ENV_VERSION
from auditgym.env import AuditEnv
from auditgym.policies import FlagAll, Oracle, RandomExplorer, Reconciler

from .core import run_episode


def record_cast(path, lines, duration):
    """Asciinema v2 replay of actual run output, paced explicitly for reading."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps({"version": 2, "width": 110, "height": 32,
                                 "timestamp": int(time.time()),
                                 "title": "auditgym: measured run, paced replay",
                                 "env": {"TERM": "xterm-256color"}}) + "\n")
        started = time.monotonic()
        for index, line in enumerate(lines):
            target = duration * index / max(1, len(lines) - 1)
            while True:
                remaining = target - (time.monotonic() - started)
                if remaining <= 0:
                    break
                time.sleep(min(1, remaining))
            stream.write(json.dumps([round(time.monotonic() - started, 3), "o", line + "\r\n"],
                                    ensure_ascii=False) + "\n")
            stream.flush()
            print(line, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", type=Path, help="New asciinema v2 .cast file")
    parser.add_argument("--duration", type=int, default=135, help="Paced replay duration, 120..180s")
    args = parser.parse_args(argv)
    if args.record and (args.record.exists() or args.record.with_suffix(".json").exists()):
        parser.error("Recording and metrics destinations must be new")
    if not 120 <= args.duration <= 180:
        parser.error("--duration must be 120..180 seconds")
    episode = Path(__file__).resolve().parents[2] / "episodes/sample/sample_00"
    truth = json.loads((episode / "private/truth.json").read_text(encoding="utf-8"))
    results = []
    lines = [f"AUDITGYM {ENV_VERSION} | real AuditEnv + Grader | sample_00, scenario A/B",
             "Measured execution replay. Reading pauses do not represent agent runtime.",
             "The agent receives only requested public records; Oracle is privileged.",
             "Reconciler: invoices, payments, ledger, FX -> checks -> evidence -> submit.", ""]
    for policy in (Oracle(truth), FlagAll(), RandomExplorer(42), Reconciler()):
        name = type(policy).__name__
        with AuditEnv() as env:
            rows, result = run_episode(env, policy, policy_name=name,
                                       reset_kwargs={"episode_dir": episode})
        if name == "Reconciler":
            for row in rows:
                action = row["action"]
                target = action["args"].get("table", "findings")
                lines.append(f"{row['step']:02d} {action['name']} {target} reward={row['reward']:.3f}")
        results.append(result)
    lines.extend(["", "Policy             P       R       F1      reward  steps"])
    for row in results:
        lines.append(f"{row['policy']:18} {row['precision']:.3f}   {row['recall']:.3f}   "
                     f"{row['f1']:.3f}   {row['reward']:.3f}   {row['steps']}")
    lines.extend(["", "Oracle is an upper bound, not an autonomous auditor.",
                  "FlagAll and RandomExplorer fail to support correct allegations on this episode.",
                  "Reconciler implements the published synthetic rules; no training was performed.",
                  "Reward = clip(2*F1 - 1 - .002*inspection_steps, -1, 1).",
                  "Eval uses a separate grader process and exposes zero reward to the agent.",
                  "Limits: synthetic data; no claim of real financial audit suitability.",
                  "End of measured-run demonstration."])
    if args.record:
        record_cast(args.record, lines, args.duration)
        args.record.with_suffix(".json").write_text(json.dumps(results, indent=2) + "\n",
                                                   encoding="utf-8", newline="\n")
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
