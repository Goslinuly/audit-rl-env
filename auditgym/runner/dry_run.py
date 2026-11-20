"""Public-only transport harness. No grading, isolation or AuditEnv claims."""

from copy import deepcopy

from auditgym import ENV_VERSION
from auditgym.generator.io import load_public
from auditgym.policies.explorers import TABLES, record_id


class DryRunEnv:
    def __init__(self, episode_dir, mode="train", max_steps=100):
        self.public = load_public(episode_dir)
        self.max_steps = max_steps

    def reset(self, **kwargs):
        self.steps = 0
        self.done = False
        self.info = {"episode_id": self.public["manifest"]["episode_id"],
                     "env_version": ENV_VERSION, "config_version": None}
        return deepcopy({"task": "Dry-run transport; no financial evaluation",
                         "manifest": self.public["manifest"],
                         "policy": self.public["policy"],
                         "steps_remaining": self.max_steps}), dict(self.info)

    def step(self, action):
        if self.done:
            raise ValueError("Episode already finished")
        self.steps += 1
        name, args = action["name"], action["args"]
        terminated = name == "submit"
        truncated = self.steps >= self.max_steps and not terminated
        if name == "list_records":
            table, limit = args["table"], args["limit"]
            if table not in TABLES or not 1 <= limit <= 50:
                raise ValueError("Unsupported dry-run request")
            start = int(args["cursor"] or 0)
            rows = self.public[table]
            end = min(start + limit, len(rows))
            obs = {"records": rows[start:end],
                   "next_cursor": str(end) if end < len(rows) else None}
        elif name == "get_record":
            table = args["table"]
            if table not in TABLES:
                raise ValueError("Unsupported dry-run table")
            record = next((r for r in self.public[table]
                           if record_id(table, r) == args["id"]), None)
            obs = ({"record": record} if record is not None else
                   {"error": {"code": "not_found", "message": "Record not found"}})
        elif terminated:
            obs = {"status": "submitted_unscored"}
        else:
            raise ValueError("Dry-run supports list_records, get_record and submit")
        obs["steps_remaining"] = max(0, self.max_steps - self.steps)
        self.done = terminated or truncated
        return deepcopy(obs), 0.0, terminated, truncated, dict(self.info)
