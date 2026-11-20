"""Baseline runner with injectable environment and scorer."""

__all__ = ["run_episode"]


def __getattr__(name):
    # Keep `python -m auditgym.runner.leaks` from importing its module twice.
    if name == "run_episode":
        from .core import run_episode
        return run_episode
    raise AttributeError(name)
