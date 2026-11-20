"""Hash the tracked and non-ignored source files, including uncommitted work."""

import hashlib
import subprocess
from pathlib import Path


def source_files(root):
    root = Path(root).resolve()
    if (root / ".git").exists():
        listing = subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root)
        names = set(listing.decode("utf-8").split("\0")) - {""}
    else:
        # Docker/source archives intentionally have neither .git nor the git CLI.
        ignored = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
                   ".mypy_cache", ".env", "runs", "out", "dist", "build"}
        names = {p.relative_to(root).as_posix() for p in root.rglob("*")
                 if p.is_file() and not any(part in ignored or part.endswith(".egg-info")
                                           or part.startswith("private_")
                                           for part in p.relative_to(root).parts)
                 and p.suffix not in (".pyc", ".pyo")}
    payload = {}
    for name in sorted(names):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Source contains an unsafe link")
        if path.is_file():
            payload[name] = path.read_bytes()
    return payload


def digest_files(payload):
    digest = hashlib.sha256()
    for name, data in sorted(payload.items()):
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest()
