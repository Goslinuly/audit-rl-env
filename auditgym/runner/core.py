"""Runner orchestration; environment and scorer are injected, not implemented here."""

import json
from copy import deepcopy
from time import perf_counter

from auditgym import ENV_VERSION

from .leaks import LeakScanner


def check_public(value):
    """Compatibility entry point for the public-boundary scanner."""
    LeakScanner().require_public(value)


def snapshot(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def run_episode(env, policy, *, policy_name, reset_kwargs=None, scorer=None, max_steps=100,
                leak_scanner=None):
    """Return trajectory and summary, never passing evaluator info to the policy.

    scorer(answer, inspection_steps) -> dict with precision, recall, f1, reward.
    It is optional: missing metrics remain null, never fabricated as zero.
    """
    if max_steps < 1:
        raise ValueError("max_steps must be positive")
    started = perf_counter()
    scanner = leak_scanner or LeakScanner()
    grade_count = len(getattr(env, "grade_log", []))
    obs, info = env.reset(**(reset_kwargs or {}))
    scanner.require_public(obs, path="reset_observation")
    scanner.require_public(info, path="reset_info")
    initial_observation, reset_info = snapshot(obs), snapshot(info)
    episode_id = info["episode_id"]
    version = info.get("env_version", ENV_VERSION)
    trajectory, answer = [], None
    inspection_steps = 0
    for step in range(1, max_steps + 1):
        action = snapshot(policy.act(deepcopy(obs)))
        scanner.require_public(action, path="action")
        next_obs, reward, terminated, truncated, info = env.step(deepcopy(action))
        scanner.require_public(next_obs, path="observation")
        scanner.require_public(info, path="info")
        if action.get("name") == "submit" and terminated and not truncated:
            answer = deepcopy(action["args"]["findings"])
        else:
            inspection_steps += 1
        if step == max_steps and not terminated and not truncated:
            truncated = True
        line = {
            "schema_version": "1.0", "episode_id": episode_id,
            "step": next_obs.get("step", step),
            "action": action, "observation": next_obs, "reward": reward,
            "terminated": bool(terminated), "truncated": bool(truncated),
            "policy": policy_name, "env_version": version,
            "config_version": info.get("config_version"),
            "info": info,
        }
        if step == 1:
            line.update(initial_observation=initial_observation, reset_info=reset_info)
        trajectory.append(snapshot(line))
        obs = next_obs
        if terminated or truncated:
            break
    if answer is None:
        answer = {"schema_version": "1.0", "episode_id": episode_id, "findings": []}
    if scorer:
        grade = scorer(deepcopy(answer), inspection_steps)
    elif len(getattr(env, "grade_log", [])) > grade_count:
        # Only scalar results cross into the operator CSV. Never copy grader
        # diagnostics (matches, missed issue IDs, errors) into agent trajectories.
        grade = {key: env.grade_log[-1][key] for key in
                 ("precision", "recall", "f1", "reward", "tp", "fp", "fn", "inspection_steps",
                  "grader_version")
                 if key in env.grade_log[-1]}
    else:
        grade = {}
    result = {
        "episode_id": episode_id, "policy": policy_name, "env_version": version,
        "config_version": info.get("config_version"),
        "grader_version": grade.get("grader_version"),
        "precision": grade.get("precision"), "recall": grade.get("recall"),
        "f1": grade.get("f1"), "reward": grade.get("reward"),
        "return": sum(row["reward"] for row in trajectory),
        "steps": trajectory[-1]["step"],
        "inspection_steps": grade.get("inspection_steps", inspection_steps),
        "terminated": trajectory[-1]["terminated"],
        "truncated": trajectory[-1]["truncated"],
        "time_s": perf_counter() - started, "scored": bool(grade) or scorer is not None,
    }
    return trajectory, snapshot(result)
