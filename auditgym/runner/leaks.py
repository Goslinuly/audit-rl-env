"""Fail-closed public-boundary and trajectory checks; never print secret values.

This is a deterministic content scanner, not a process sandbox or a proof against
arbitrary encodings/covert channels. Oracle submissions are scanned too: canonical
findings are allowed, private issue IDs and reference metadata are not.
"""

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from auditgym.env import leak_scan as team_leak_scan

PRIVATE_KEYS = {
    "truth", "provenance", "private", "seed", "randomseed", "generationseed",
    "policyseed", "episode_seed", "issueid", "issuecount", "expectedamountminor",
    "groundtruth", "truthpath", "truthfile", "provenancepath", "privatepath",
}
PRIVATE_KEYS = {re.sub(r"[^a-z0-9]", "", key) for key in PRIVATE_KEYS}
TEXT_RULES = (
    ("private_marker", re.compile(
        r"\b(?:truth|provenance|ground[_ -]?truth|issue[_ -]?id|"
        r"expected[_ -]?amount(?:[_ -]?minor)?)\b",
        re.I)),
    ("private_issue_id", re.compile(r"\bISS-\d+\b", re.I)),
    ("seed_assignment", re.compile(
        r"\b(?:\w*[_-])?seed[\"']?\s*(?:[=:]\s*[\"']?|(?:is\s+)?)[-+]?\d+", re.I)),
    ("filesystem_path", re.compile(
        r"file://|\b[A-Z]:[\\/]|(?:^|[\\/])private[\\/]|"
        r"/(?:tmp|home|Users|app|workspace|mnt|etc|var)/|"
        r"\\\\[a-z0-9_.-]+\\[a-z0-9_$.-]+\\", re.I)),
    ("stack_trace", re.compile(r"Traceback\s*\(most recent call last\)|File\s+[\"']", re.I)),
)


@dataclass(frozen=True)
class Leak:
    path: str
    rule: str


class LeakError(ValueError):
    pass


class LeakScanner:
    def __init__(self, private_tokens=()):
        # Numbers are often legitimately derivable from public documents. Do not
        # blacklist numeric seed/amount values regardless of where they occur.
        self.tokens = tuple(token.casefold() for token in private_tokens
                            if isinstance(token, str) and len(token) >= 4)

    def scan(self, value, *, path="public"):
        # Preserve the owner's published environment leak contract in addition
        # to our nested-key, path, canary and private-ID checks.
        issues = [Leak(path, "team_leak_contract")] if team_leak_scan(value, {}) else []

        def walk(item, location):
            if isinstance(item, dict):
                for key, child in item.items():
                    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
                    if normalized in PRIVATE_KEYS:
                        issues.append(Leak(location, "private_key"))
                    walk(str(key), location + ".<key>")
                    walk(child, location + "." + str(key)[:40])
            elif isinstance(item, (list, tuple)):
                for index, child in enumerate(item):
                    walk(child, f"{location}[{index}]")
            elif isinstance(item, str):
                for rule, pattern in TEXT_RULES:
                    if pattern.search(item):
                        issues.append(Leak(location, rule))
                if any(token in item.casefold() for token in self.tokens):
                    issues.append(Leak(location, "private_token"))

        walk(value, path)
        return issues

    def require_public(self, value, *, path="public"):
        issues = self.scan(value, path=path)
        if issues:
            # Only rule and boundary name; no potentially sensitive value/path.
            raise LeakError(f"Forbidden private data in {path.split('.')[0]} ({issues[0].rule})")


def scan_trajectory(rows, scanner=None):
    scanner = scanner or LeakScanner()
    issues = []
    count = 0
    for count, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not {"action", "observation", "step"} <= row.keys():
            issues.append(Leak(f"trajectory[{count}]", "invalid_trajectory_row"))
        issues.extend(scanner.scan(row, path=f"trajectory[{count}]"))
    if count == 0:
        issues.append(Leak("trajectory", "empty_trajectory"))
    return {
        "status": "failed" if issues else "passed", "rows": count,
        "violations": [asdict(issue) for issue in issues],
        "scope": "recorded JSON content; initial observation/info only when recorded",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.trajectory.open(encoding="utf-8") as stream:
            report = scan_trajectory(json.loads(line) for line in stream if line.strip())
    except (OSError, ValueError):
        print(json.dumps({"status": "failed", "reason": "unreadable_or_invalid_jsonl"}))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
