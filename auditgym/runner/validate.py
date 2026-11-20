"""Portable full verification: python -m auditgym.runner.validate."""

import argparse
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from auditgym import ENV_VERSION

from .snapshot import digest_files, source_files


def execute(stages, root, out, deadline_s, source_sha256=None):
    if not math.isfinite(deadline_s) or deadline_s <= 0:
        raise ValueError("deadline must be positive")
    out.mkdir(parents=True, exist_ok=False)
    temporary = out / "temp"
    temporary.mkdir()
    environment = dict(os.environ, TMP=str(temporary), TEMP=str(temporary), TMPDIR=str(temporary),
                       PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    report = {"env_version": ENV_VERSION, "python": platform.python_version(),
              "platform": platform.platform(), "status": "running", "stages": [],
              "resource_limits_verified": False}
    if source_sha256 is not None:
        report["source_sha256"] = source_sha256
    for name, command in stages:
        stage_start = time.monotonic()
        remaining = deadline_s - (stage_start - started)
        print(f"=== {name} ===", flush=True)
        try:
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, deadline_s)
            code = subprocess.run(command, cwd=root, env=environment, timeout=remaining).returncode
            status = "passed" if code == 0 else "failed"
        except subprocess.TimeoutExpired:
            code, status = 124, "timed_out"
        except OSError:
            code, status = 127, "failed_to_start"
        report["stages"].append({"name": name, "status": status, "exit_code": code,
                                 "duration_s": round(time.monotonic() - stage_start, 3)})
        if code:
            report["status"] = "failed"
            break
    else:
        report["status"] = "passed"
    report["duration_s"] = round(time.monotonic() - started, 3)
    report["deadline_s"] = deadline_s
    (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n",
                                         encoding="utf-8", newline="\n")
    print(f"Validation {report['status']}: {out / 'validation.json'}", flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--deadline", type=float, default=600)
    args = parser.parse_args(argv)
    if not math.isfinite(args.deadline) or args.deadline <= 0:
        parser.error("--deadline must be positive")
    root = Path(__file__).resolve().parents[2]
    if not (root / "pyproject.toml").is_file() or not (root / "tests").is_dir():
        parser.error("Full validation requires a source checkout, not an installed wheel")
    out = (args.out or root / "runs" / ("check-" + uuid4().hex[:10])).resolve()
    if out.exists():
        parser.error("--out must be a new directory")
    python = sys.executable
    stages = [
        ("lint", [python, "-m", "ruff", "check", "--no-cache", "auditgym", "tests"]),
        ("tests_and_acceptance", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                  "--basetemp", str(out / "pytest-temp"),
                                  "--acceptance-report", str(out / "acceptance.json"),
                                  "--junitxml", str(out / "junit.xml")]),
        ("episode_checksums", [python, "-m", "auditgym.generator", "build", "--check"]),
        ("grader_selfcheck", [python, "-m", "auditgym.grader", "selfcheck", "episodes"]),
        ("four_baselines", [python, "-m", "auditgym.runner.check"]),
    ]
    report = execute(stages, root, out, args.deadline, digest_files(source_files(root)))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
