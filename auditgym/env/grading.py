"""Episode ownership and grading, kept outside the environment object.

The environment never holds the grader's files (``truth``, ``provenance``) or the seed.
A *backend* builds or loads the episode, hands the environment only the public part plus
``{episode_id, config_version}``, and keeps the private part for scoring.

* :class:`InlineBackend` — private data lives in a separate object in the same process.
  Default for ``mode="train"``.
* :class:`ProcessBackend` — the episode is generated *inside a separate worker process*;
  the private part never exists in the environment's process at all. The environment
  sends only findings and receives only the grade. Default for ``mode="eval"``.

Grader contract (see :mod:`auditgym.env.stub_grader`)::

    grader.score(findings, *, truth, public, inspection_steps) -> dict | dataclass

Diagnostics. A grade may carry details derived from the reference answer (``matches``,
``missed_issue_ids``, ``finding_reasons``, ``by_type``, validation ``errors``...). With
``redact=True`` (``mode="eval"``) the backend returns only the scalar summary
(:data:`SUMMARY_KEYS` plus an ``error`` code, see :func:`summarize`); the full grade is
written — on the grader side, i.e. inside the worker process for :class:`ProcessBackend` —
as one JSON line to ``log_path`` if one is configured, and is otherwise dropped.
"""

from __future__ import annotations

import dataclasses
import json
import multiprocessing as mp
import os
import socket
import subprocess
import sys
from pathlib import Path

if os.name == "posix":
    from multiprocessing.connection import Connection

REPLY_TIMEOUT_S = 60.0

SUMMARY_KEYS = ("reward", "precision", "recall", "f1", "tp", "fp", "fn", "valid",
                "n_findings", "inspection_steps", "grader_version")
"""Grade fields that may reach the environment's process in ``eval``: scalars about the
agent's own submission, nothing that names or locates an issue of the reference answer."""


def default_grader():
    """Participant 3's grader if present, otherwise the temporary stub."""
    try:
        from auditgym.grader import Grader  # type: ignore[attr-defined]
    except ImportError:
        from .stub_grader import StubGrader

        return StubGrader
    return Grader


def _grade_to_dict(result) -> dict:
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        result = dataclasses.asdict(result)
    elif not isinstance(result, dict):
        result = {k: getattr(result, k) for k in dir(result) if not k.startswith("_")}
    out = dict(result)
    out["reward"] = float(out.get("reward", -1.0))
    return out


def load_episode_parts(seed, config, episode_dir) -> tuple[dict, dict, dict]:
    """Return ``(public, private, meta)``. Runs inside the backend, never in the env."""
    from auditgym.generator import generate, load_episode

    if episode_dir is not None:
        public, private = load_episode(Path(episode_dir))
        config_version = private["provenance"].get("config_version")
    else:
        ep = generate(seed, config if config is not None else {})
        public, private = ep.public, ep.private
        config_version = ep.config.get("config_version")
    public = {k: public[k] for k in ("manifest", "policy", "ledger", "invoices", "payments", "fx")}
    meta = {"episode_id": public["manifest"]["episode_id"], "config_version": config_version}
    return public, private, meta


def run_grader(grader, findings, private: dict, public: dict, inspection_steps: int) -> dict:
    try:
        result = grader.score(
            findings, truth=private["truth"], public=public, inspection_steps=inspection_steps
        )
        return _grade_to_dict(result)
    except Exception as exc:  # a grader crash must not crash the episode
        return {"reward": -1.0, "errors": [f"grader_exception: {type(exc).__name__}"]}


def summarize(grade: dict) -> dict:
    """Scalar-only view of a grade: :data:`SUMMARY_KEYS` plus ``error`` — ``None``,
    ``"invalid_submission"`` or ``"grader_exception"`` (a code, never the messages)."""
    out = {k: grade[k] for k in SUMMARY_KEYS if k in grade}
    errors = grade.get("errors") or []
    if any(str(e).startswith("grader_exception") for e in errors):
        out["error"] = "grader_exception"
    elif errors or grade.get("valid") is False:
        out["error"] = "invalid_submission"
    else:
        out["error"] = None
    return out


def write_diagnostics(log_path, record: dict) -> None:
    """Append one JSON line with the full grade. A logging failure never breaks grading."""
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def finish_grade(grade: dict, context: dict | None, *, redact: bool, log_path) -> dict:
    """Log the full grade (if configured) and return what the environment may keep."""
    if log_path:
        write_diagnostics(log_path, {**(context or {}), **grade})
    return summarize(grade) if redact else grade


class InlineBackend:
    """Private data in a separate object of the same process."""

    def __init__(self, grader_factory=None, *, redact: bool = False, log_path=None):
        factory = grader_factory or default_grader()
        self._grader = factory()
        self._redact = redact
        self._log_path = log_path
        self._public: dict | None = None
        self.__private: dict | None = None  # name-mangled: not a plain attribute of the env

    def start(self, seed, config, episode_dir=None) -> tuple[dict, dict]:
        public, private, meta = load_episode_parts(seed, config, episode_dir)
        self._public, self.__private = public, private
        return public, meta

    def score(self, findings, inspection_steps: int, context: dict | None = None) -> dict:
        if self.__private is None or self._public is None:
            raise RuntimeError("no episode loaded")
        grade = run_grader(self._grader, findings, self.__private, self._public, inspection_steps)
        return finish_grade(grade, context, redact=self._redact, log_path=self._log_path)

    def close(self) -> None:
        self._public = self.__private = None


def _worker(conn, grader_factory, redact: bool = False, log_path=None) -> None:
    """Owns the private part of the current episode; answers start/score/close.

    Full diagnostics stay here: with ``redact`` only :func:`summarize` crosses the pipe."""
    factory = grader_factory or default_grader()
    grader = factory()
    public = private = None
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        cmd = msg[0]
        if cmd == "close":
            conn.close()
            return
        if cmd == "start":
            _, seed, config, episode_dir = msg
            try:
                public, private, meta = load_episode_parts(seed, config, episode_dir)
                conn.send(("ok", public, meta))
            except Exception as exc:
                # Only the exception type crosses the boundary: messages may mention the seed.
                conn.send(("error", type(exc).__name__))
        elif cmd == "score":
            _, findings, steps, context = msg
            if private is None:
                conn.send(("error", "no episode loaded"))
            else:
                grade = run_grader(grader, findings, private, public, steps)
                conn.send(("ok", finish_grade(grade, context, redact=redact,
                                              log_path=log_path)))
        else:
            conn.send(("error", "unknown command"))


class ProcessBackend:
    """Episode generation and grading in a separate process.

    POSIX: a fresh interpreter (``python -m auditgym.env.worker``) connected by a private
    socket pair. It does not re-import the caller's ``__main__`` (so a harness script needs no
    ``if __name__ == "__main__"`` guard) and may be started from a daemonic process.
    Windows, or a custom grader factory: ``multiprocessing`` with the ``spawn`` method.
    """

    def __init__(self, grader_factory=None, *, redact: bool = False, log_path=None):
        log_path = str(log_path) if log_path else None
        if grader_factory is None and os.name == "posix":
            parent, child = socket.socketpair()
            env = dict(os.environ)
            root = str(Path(__file__).resolve().parents[2])
            env["PYTHONPATH"] = os.pathsep.join(filter(None, [root, env.get("PYTHONPATH")]))
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "auditgym.env.worker", str(child.fileno()),
                 json.dumps({"redact": redact, "log_path": log_path})],
                pass_fds=[child.fileno()], env=env, stdin=subprocess.DEVNULL,
            )
            child.close()
            self._conn = Connection(parent.detach())
        else:
            ctx = mp.get_context("spawn")
            self._conn, child = ctx.Pipe()
            self._proc = ctx.Process(target=_worker,
                                     args=(child, grader_factory, redact, log_path), daemon=True)
            self._proc.start()
            child.close()

    def _call(self, *msg):
        if self._conn is None:
            raise RuntimeError("backend is closed")
        try:
            self._conn.send(msg)
            if not self._conn.poll(REPLY_TIMEOUT_S):
                raise RuntimeError("grader process did not answer in time")
            reply = self._conn.recv()
        except (EOFError, OSError) as exc:
            raise RuntimeError("grader process stopped unexpectedly") from exc
        if reply[0] != "ok":
            raise RuntimeError(f"grader process error: {reply[1]}")
        return reply[1:]

    def start(self, seed, config, episode_dir=None) -> tuple[dict, dict]:
        public, meta = self._call("start", seed, config, episode_dir)
        return public, meta

    def score(self, findings, inspection_steps: int, context: dict | None = None) -> dict:
        (result,) = self._call("score", findings, inspection_steps, context)
        return result

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.send(("close",))
            except (OSError, BrokenPipeError):
                pass
            self._conn.close()
            self._conn = None
        if self._proc is not None:
            if isinstance(self._proc, subprocess.Popen):
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            else:
                self._proc.join(timeout=5)
                if self._proc.is_alive():
                    self._proc.kill()
            self._proc = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
