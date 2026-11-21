"""Eval isolation of grader diagnostics: after ``submit`` in ``eval`` nothing reachable from
the environment object names or locates an issue of the reference answer; the full grade
goes only to the grader-side log file (``grader_log_path`` / ``AUDITGYM_GRADER_LOG``)."""

from __future__ import annotations

import json

import pytest
from conftest import SAMPLE, act, oracle_findings

from auditgym.env import AuditEnv
from auditgym.env.grading import SUMMARY_KEYS

DIAGNOSTIC_KEYS = {"matches", "missed_issue_ids", "finding_reasons", "by_type", "errors",
                   "n_issues", "issue_id", "issues", "evidence_sets", "truth", "provenance"}
EVAL_LOG_KEYS = {"episode_id", "mode", "reason", "steps", "error", *SUMMARY_KEYS}


def _lists(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _lists(v, out)
    elif isinstance(obj, (list, tuple)):
        if obj and all(isinstance(x, str) for x in obj):
            out.add(frozenset(obj))
        for v in obj:
            _lists(v, out)
    return out


def _scan_env(root, private, public):
    """Recursive scan of ``root`` (``vars(env)``): no truth issue id, no diagnostic key, and no
    string list equal to a truth ``affected_ids`` / ``evidence_sets`` list unless the very
    same list already occurs in the public data."""
    truth = private["truth"]
    issue_ids = [i["issue_id"] for i in truth["issues"]]
    secret_lists = {frozenset(i["affected_ids"]) for i in truth["issues"]}
    secret_lists |= {frozenset(s) for i in truth["issues"] for s in i["evidence_sets"]}
    secret_lists -= _lists(public, set())
    seen, problems = set(), []

    def walk(obj, path, depth=0):
        if id(obj) in seen or depth > 14:
            return
        seen.add(id(obj))
        if isinstance(obj, str):
            problems.extend(f"{path}: issue id" for i in issue_ids if i in obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k in DIAGNOSTIC_KEYS:
                    problems.append(f"{path}: key {k!r}")
                walk(k, f"{path}.{k}", depth + 1)
                walk(v, f"{path}.{k}", depth + 1)
        elif isinstance(obj, (list, tuple, set, frozenset)):
            if obj and all(isinstance(x, str) for x in obj) and frozenset(obj) in secret_lists:
                problems.append(f"{path}: affected/evidence id list of the truth")
            for n, v in enumerate(obj):
                walk(v, f"{path}[{n}]", depth + 1)
        elif hasattr(obj, "__dict__") and obj.__class__.__module__.startswith("auditgym"):
            walk(vars(obj), path, depth + 1)
        elif hasattr(obj, "__slots__"):
            for s in obj.__slots__:
                walk(getattr(obj, s, None), f"{path}.{s}", depth + 1)

    walk(root, "env")
    return problems


@pytest.mark.parametrize("isolation", ["process", "inline"])
@pytest.mark.parametrize("answer", ["oracle", "empty", "invalid", "timeout"])
def test_eval_after_submit_env_holds_no_diagnostics(sample, isolation, answer, monkeypatch):
    monkeypatch.delenv("AUDITGYM_GRADER_LOG", raising=False)
    public, private = sample
    truth = private["truth"]
    findings = {"oracle": oracle_findings(truth),
                "empty": {"episode_id": truth["episode_id"], "findings": []},
                "invalid": {"episode_id": truth["episode_id"], "findings": [1]}}.get(answer)
    now = [0.0]
    with AuditEnv(mode="eval", isolation=isolation, clock=lambda: now[0]) as env:
        env.reset(episode_dir=SAMPLE)
        env.step(act("list_records", table="ledger"))
        if answer == "timeout":
            now[0] = 61.0
            obs, reward, term, trunc, info = env.step(
                act("submit", findings=oracle_findings(truth)))
            assert (term, trunc) == (False, True) and obs["truncated_reason"] == "time_limit"
        else:
            obs, reward, term, trunc, info = env.step(act("submit", findings=findings))
            assert (term, trunc) == (True, False)
        assert reward == 0.0
        log = env.grade_log[-1]
        assert set(log) == EVAL_LOG_KEYS, set(log) ^ EVAL_LOG_KEYS
        assert all(v is None or isinstance(v, (bool, int, float, str)) for v in log.values())
        assert log["error"] == ("invalid_submission" if answer == "invalid" else None)
        if answer == "oracle":
            assert log["f1"] == 1.0 and log["tp"] == len(truth["issues"])
        # inline isolation keeps the private part in a backend object of the same process by
        # design (train-style); only the process backend makes the whole graph clean.
        root = vars(env) if isolation == "process" else {"grade_log": env.grade_log}
        problems = _scan_env(root, private, public)
        assert not problems, problems[:5]


def test_scan_detects_planted_diagnostics(sample, monkeypatch):
    monkeypatch.delenv("AUDITGYM_GRADER_LOG", raising=False)
    public, private = sample
    with AuditEnv(mode="train") as env:
        env.reset(episode_dir=SAMPLE)
        env.step(act("submit", findings=oracle_findings(private["truth"])))
        # train keeps the full grade in memory: the same scan must flag it
        assert _scan_env(vars(env), private, public)


def test_eval_diagnostics_file_has_full_details(sample, tmp_path, monkeypatch):
    monkeypatch.delenv("AUDITGYM_GRADER_LOG", raising=False)
    _, private = sample
    truth = private["truth"]
    issue_ids = {i["issue_id"] for i in truth["issues"]}
    path = tmp_path / "grader.jsonl"
    with AuditEnv(mode="eval", grader_log_path=path) as env:
        env.reset(episode_dir=SAMPLE)
        env.step(act("submit", findings=oracle_findings(truth)))
        env.reset(episode_dir=SAMPLE)
        env.step(act("submit", findings={"episode_id": truth["episode_id"], "findings": []}))
        assert len(env.grade_log) == 2
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2
    full, silent = rows
    assert full["mode"] == "eval" and full["reason"] == "submit"
    assert full["episode_id"] == truth["episode_id"] and full["reward"] == pytest.approx(1.0)
    assert {m["issue_id"] for m in full["matches"]} == issue_ids
    assert full["missed_issue_ids"] == [] and full["finding_reasons"]
    assert set(silent["missed_issue_ids"]) == issue_ids
    assert "by_type" in full and "errors" in full


def test_grader_log_path_from_environment_variable(sample, tmp_path, monkeypatch):
    _, private = sample
    path = tmp_path / "from_env.jsonl"
    monkeypatch.setenv("AUDITGYM_GRADER_LOG", str(path))
    with AuditEnv(mode="eval") as env:
        env.reset(episode_dir=SAMPLE)
        env.step(act("submit", findings=oracle_findings(private["truth"])))
        assert "missed_issue_ids" not in env.grade_log[-1]
    (row,) = [json.loads(line) for line in path.read_text().splitlines()]
    assert "missed_issue_ids" in row and "matches" in row


def test_train_keeps_full_diagnostics_in_memory(sample, monkeypatch):
    monkeypatch.delenv("AUDITGYM_GRADER_LOG", raising=False)
    _, private = sample
    with AuditEnv(mode="train") as env:
        env.reset(episode_dir=SAMPLE)
        env.step(act("submit", findings=oracle_findings(private["truth"])))
        log = env.grade_log[-1]
    assert "missed_issue_ids" in log and "matches" in log and env.grader_log_path is None


def test_submit_after_deadline_is_truncated_and_graded_empty(sample):
    """The wall-clock limit is enforced at step boundaries: a submit arriving after the
    deadline is discarded and the episode is graded as ``findings: []``."""
    _, private = sample
    now = [0.0]
    with AuditEnv(mode="train", clock=lambda: now[0]) as env:
        env.reset(episode_dir=SAMPLE)
        now[0] = 60.01
        obs, reward, term, trunc, _ = env.step(
            act("submit", findings=oracle_findings(private["truth"])))
        assert (term, trunc) == (False, True)
        assert obs["error"]["code"] == "time_limit" and obs["step"] == 0
        log = env.grade_log[-1]
        assert log["reason"] == "time_limit" and log["n_findings"] == 0 and log["tp"] == 0
        assert reward == log["reward"] < 1.0
