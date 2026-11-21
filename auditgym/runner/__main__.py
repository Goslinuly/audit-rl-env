"""CLI for baseline execution on existing episode directories."""

import argparse
import csv
import importlib
import json
from pathlib import Path

from auditgym.policies import FlagAll, Oracle, RandomExplorer, Reconciler
from auditgym.env import AuditEnv
from auditgym.generator import GENERATOR_VERSION

from .core import run_episode
from .dry_run import DryRunEnv
from .leaks import LeakError, scan_trajectory


def symbol(spec):
    module, name = spec.split(":", 1)
    return getattr(importlib.import_module(module), name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", nargs="+", type=Path, required=True)
    policies = {"Oracle": Oracle, "FlagAll": FlagAll,
                "RandomExplorer": RandomExplorer, "Reconciler": Reconciler}
    parser.add_argument("--policies", nargs="+", choices=list(policies), default=list(policies))
    parser.add_argument("--seed", type=int, default=7, help="RandomExplorer policy seed")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true", help="Unscored public-data harness")
    parser.add_argument("--env-factory", help="module:factory(episode_dir, mode, max_steps)")
    parser.add_argument("--scorer-factory", help="module:factory(episode_dir); returns callback")
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--mode", choices=["train", "eval"], default="train")
    args = parser.parse_args(argv)
    if not 1 <= args.max_steps <= 100:
        parser.error("--max-steps must be in 1..100")
    if args.dry_run and (args.env_factory or args.scorer_factory):
        parser.error("--dry-run cannot be combined with external adapters")
    if bool(args.env_factory) != bool(args.scorer_factory):
        parser.error("Supply both external adapter factories or neither")
    if args.out.exists():
        parser.error("--out must be a new directory, to preserve previous runs")
    for episode in args.episodes:
        if not (episode / "public" / "manifest.json").is_file():
            parser.error(f"Missing public manifest: {episode}")
    env_factory = (DryRunEnv if args.dry_run else
                   symbol(args.env_factory) if args.env_factory else AuditEnv)
    scorer_factory = symbol(args.scorer_factory) if args.scorer_factory else None
    trajectories, results = [], []
    for episode in args.episodes:
        for name in args.policies:
            if name == "Oracle":
                truth = json.loads((episode / "private" / "truth.json").read_text("utf-8"))
                policy = Oracle(truth)
            elif name == "RandomExplorer":
                policy = RandomExplorer(seed=args.seed)
            else:
                policy = policies[name]()
            if args.dry_run or args.env_factory:
                env = env_factory(episode_dir=episode, mode=args.mode, max_steps=args.max_steps)
                reset_kwargs = None
            else:
                env = env_factory(mode=args.mode, max_steps=args.max_steps)
                reset_kwargs = {"episode_dir": episode}
            scorer = scorer_factory(episode_dir=episode) if scorer_factory else None
            try:
                rows, result = run_episode(env, policy, policy_name=name, scorer=scorer,
                                           max_steps=args.max_steps, reset_kwargs=reset_kwargs)
            finally:
                if callable(getattr(env, "close", None)):
                    env.close()
            result["episode_path"] = episode.as_posix()
            result["policy_seed"] = args.seed if name == "RandomExplorer" else None
            result["execution_mode"] = "dry_run" if args.dry_run else "audit_env"
            result["mode"] = args.mode
            # Code version; `make episodes-check` verifies committed episodes match it.
            result["generator_version"] = GENERATOR_VERSION
            trajectories.extend(rows)
            results.append(result)
    leak_report = scan_trajectory(trajectories)
    if leak_report["status"] != "passed":
        raise LeakError("Forbidden private data in exported trajectories")
    args.out.mkdir(parents=True)
    with (args.out / "trajectories.jsonl").open("w", encoding="utf-8", newline="\n") as out:
        for row in trajectories:
            out.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    with (args.out / "results.csv").open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(results[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)
    # Re-read the actual JSONL bytes, independently of the in-memory guard.
    with (args.out / "trajectories.jsonl").open(encoding="utf-8") as stream:
        leak_report = scan_trajectory(json.loads(line) for line in stream if line.strip())
    (args.out / "leak_report.json").write_text(
        json.dumps(leak_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        newline="\n")
    if leak_report["status"] != "passed":
        raise LeakError("Forbidden private data in recorded trajectory file")
    print(f"{len(results)} runs written to {args.out}; scored={not args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
