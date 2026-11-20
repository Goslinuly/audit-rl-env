"""Run the four scored baselines on dev, with disposable exports."""

import csv
import tempfile
from pathlib import Path

from .__main__ import main as run


def main():
    root = Path(__file__).resolve().parents[2]
    episodes = sorted((root / "episodes/dev").iterdir())
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "results"
        run(["--episodes", *[str(p) for p in episodes if p.is_dir()], "--out", str(out)])
        with (out / "results.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not all(row["scored"] == "True" for row in rows):
            raise RuntimeError("Unscored baseline")
        if not all(float(row["reward"]) == 1 for row in rows if row["policy"] == "Oracle"):
            raise RuntimeError("Oracle baseline failed")
        print(f"Baseline check: {len(rows)} scored runs passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
