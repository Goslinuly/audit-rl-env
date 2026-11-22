"""Grader process of :class:`auditgym.env.grading.ProcessBackend` (POSIX).

    python -m auditgym.env.worker <socket fd> <json options>

Started by the environment only; the private part of an episode lives in this process.
"""

from __future__ import annotations

import json
import sys
from multiprocessing.connection import Connection

from .grading import _worker


def main(argv: list[str]) -> None:
    options = json.loads(argv[1])
    try:
        _worker(Connection(int(argv[0])), None, options["redact"], options["log_path"])
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
