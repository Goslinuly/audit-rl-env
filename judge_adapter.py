"""Adapter for the organisers' checks ("Genesis FinTech: определения проверок").

Entry points, called from the repository root (``/app`` in the container)::

    generate_episode(seed, config, output_dir) -> None
    make_env() -> object with reset(seed, config) and step(action)
    score_episode(episode_dir, findings, inspection_steps) -> dict

The adapter only translates names and envelopes between the published protocol and
``auditgym``. It never chooses an action, never changes amounts, types or currencies, and
keeps no state between episodes. Documentation: ``docs/judge.md``.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

from auditgym.env import AuditEnv
from auditgym.generator import generate, load_episode
from auditgym.generator.io import PRIVATE_FILES, dump_json, public_files
from auditgym.grader import Grader
from auditgym.grader.validate import validate_findings

TABLES = ("ledger", "invoices", "payments", "fx")
ISSUE_TYPES = ("duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff")
MAX_STEPS = 100
TIME_LIMIT_S = 60.0
TASK = (
    "Audit one reporting period of a fictional company: investigate the public records with "
    "the actions below, then submit every accounting error you can prove. Error types: "
    "duplicate_invoice, payment_allocation, fx_conversion, period_cutoff. The books may be "
    "clean. Money is in integer minor units, FX rates are decimal strings, times are ISO-8601 "
    "with offset. Tables: ledger, invoices, payments, fx. Actions: "
    '{"name": "list_records", "args": {"table", "cursor", "limit"}} (limit 1..50, first cursor '
    'null); {"name": "get_record", "args": {"table", "id"}}; {"name": "get_document", "args": '
    '{"doc_id"}}; {"name": "calculator", "args": {"expression"}} (+ - * / and parentheses); '
    '{"name": "submit", "args": {"findings": {"episode_id", "findings": [{"type", '
    '"affected_ids", "claimed_amount_minor", "currency", "evidence_ids", "explanation"}]}}}. '
    "Canonical IDs: 'ledger:<row_id>', 'invoices:<invoice_id>', 'payments:<payment_id>', "
    "'fx:<date>/<source_currency>/<target_currency>'; the bare row_id, invoice_id, payment_id "
    "or doc_id of a record is accepted too. At most 30 findings, 10 evidence_ids and 1000 "
    "characters of explanation per finding. Every action costs one step."
)


# --- IDs ------------------------------------------------------------------------------------
class IdTranslator:
    """Exact translation of raw record IDs into canonical ``<table>:<id>``.

    The organisers' policies see records without our table prefix, so a raw ``row_id``,
    ``invoice_id``, ``payment_id``, ``doc_id`` or fx key is translated when it equals, character
    for character, the ID of exactly one record. Nothing is trimmed, re-cased or guessed; an
    unknown or ambiguous ID is passed through unchanged (and then never matches).
    """

    def __init__(self, public: dict):
        canonical: set[str] = set()
        meanings: dict[str, set[str]] = {}

        def add(raw, ref: str) -> None:
            if isinstance(raw, str) and raw:
                meanings.setdefault(raw, set()).add(ref)

        for row in public["ledger"]:
            ref = f"ledger:{row['row_id']}"
            canonical.add(ref)
            add(row["row_id"], ref)
        for table, key in (("invoices", "invoice_id"), ("payments", "payment_id")):
            for doc in public[table]:
                ref = f"{table}:{doc[key]}"
                canonical.add(ref)
                add(doc[key], ref)
                add(doc.get("doc_id"), ref)
        for rate in public["fx"]:
            parts = (rate["date"], rate["source_currency"], rate["target_currency"])
            ref = "fx:" + "/".join(parts)
            canonical.add(ref)
            for raw in ("/".join(parts), ":".join(parts), "fx:" + ":".join(parts)):
                add(raw, ref)
        self._map = {raw: next(iter(refs)) for raw, refs in meanings.items()
                     if len(refs) == 1 and raw not in canonical}

    def ref(self, value):
        return self._map.get(value, value) if isinstance(value, str) else value

    def _list(self, value):
        return [self.ref(x) for x in value] if isinstance(value, list) else value

    def findings(self, submission):
        """Copy of a submission with translated IDs; malformed parts are left as they are."""
        if not isinstance(submission, dict) or not isinstance(submission.get("findings"), list):
            return submission
        out = dict(submission)
        out["findings"] = []
        for item in submission["findings"]:
            if isinstance(item, dict):
                item = dict(item)
                for key in ("affected_ids", "evidence_ids"):
                    if key in item:
                        item[key] = self._list(item[key])
            out["findings"].append(item)
        return out

    def truth(self, truth: dict) -> dict:
        """Truth with the same translation, so a fixture may use raw or canonical IDs."""
        out = copy.deepcopy(truth)
        for issue in out.get("issues", ()):
            issue["affected_ids"] = self._list(issue["affected_ids"])
            issue["evidence_sets"] = [self._list(s) for s in issue["evidence_sets"]]
        return out


# --- generation -----------------------------------------------------------------------------
def generate_episode(seed: int, config: dict, output_dir: str) -> None:
    """Write one episode into ``output_dir`` (flat: public files next to truth/provenance)."""
    episode = generate(seed, dict(config or {}))
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = public_files(episode.public)
    for name in PRIVATE_FILES:
        files[name] = dump_json(episode.private[name.removesuffix(".json")])
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")


# --- environment ----------------------------------------------------------------------------
class JudgeEnv:
    """``reset``/``step`` of the published protocol on top of :class:`AuditEnv`."""

    def __init__(self, *, time_limit_s: float | None = TIME_LIMIT_S, grader_log_path=None, **kwargs):
        self._options = {"max_steps": MAX_STEPS, "time_limit_s": time_limit_s,
                         "grader_log_path": grader_log_path, **kwargs}
        self._env: AuditEnv | None = None
        self._mode: str | None = None
        self._ids: IdTranslator | None = None
        self._episode_id: str | None = None

    def reset(self, seed=None, config: dict | None = None):
        config = dict(config or {})
        mode = config.get("mode", "closed")
        if mode not in ("closed", "train"):
            raise ValueError("config['mode'] must be 'closed' or 'train'")
        if self._env is None or mode != self._mode:
            self.close()
            self._env = AuditEnv(mode="eval" if mode == "closed" else "train", **self._options)
            self._mode = mode
        episode_dir = config.get("episode_dir")
        if episode_dir is not None:
            obs, info = self._env.reset(episode_dir=episode_dir)
        else:
            obs, info = self._env.reset(seed, dict(config.get("team_config") or {}))
        self._episode_id = info["episode_id"]
        self._ids = IdTranslator(self._env.public_records())
        first = {"task": TASK, "manifest": obs["manifest"], "policy": obs["policy"],
                 "remaining_steps": obs["steps_remaining"]}
        return first, self._info(info)

    def step(self, action):
        if self._env is None or self._ids is None:
            raise RuntimeError("call reset() before step()")
        submission = None
        inner = action
        if isinstance(action, dict) and action.get("name") == "submit" \
                and isinstance(action.get("args"), dict) and "findings" in action["args"]:
            submission = self._ids.findings(action["args"]["findings"])
            inner = {**action, "args": {**action["args"], "findings": submission}}
        elif isinstance(action, dict) and action.get("name") == "get_record" \
                and isinstance(action.get("args"), dict):
            inner = self._fx_key(action)
        obs, reward, terminated, truncated, info = self._env.step(inner)
        out = {"result": None, "error": obs.get("error"),
               "remaining_steps": obs["steps_remaining"]}
        if out["error"] is None:
            out["result"], out["error"] = self._result(obs, terminated, submission)
        return out, reward, terminated, truncated, self._info(info)

    def close(self) -> None:
        if self._env is not None:
            self._env.close()
        self._env = self._ids = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @staticmethod
    def _info(info: dict) -> dict:
        return {"episode_id": info["episode_id"], "env_version": info["env_version"]}

    @staticmethod
    def _fx_key(action: dict) -> dict:
        """``date:source:target`` → our ``date/source/target`` for get_record on fx."""
        args = action["args"]
        key = args.get("id")
        if args.get("table") == "fx" and isinstance(key, str):
            key = key.removeprefix("fx:")
            if key.count(":") == 2 and "/" not in key:
                return {**action, "args": {**args, "id": key.replace(":", "/")}}
        return action

    def _result(self, obs: dict, terminated: bool, submission):
        name, result = obs["action"], obs["result"]
        if name == "list_records":
            return {"records": [x["record"] for x in result["items"]],
                    "next_cursor": result["next_cursor"]}, None
        if name == "get_record":
            return result["record"], None
        if name == "get_document":
            return result["document"], None
        if name == "calculator":
            return result["value"], None
        if validate_findings(submission, episode_id=self._episode_id):
            return None, {"code": "invalid_submission",
                          "message": "findings do not match the required structure"}
        return {"accepted": True}, None


def make_env() -> JudgeEnv:
    return JudgeEnv()


# --- scoring (judge side only) --------------------------------------------------------------
def score_episode(episode_dir: str, findings: dict, inspection_steps: int) -> dict:
    """Closed scoring call. Invalid structure: ``return`` = -1 and the other fields null;
    the reason goes to the grader log (``AUDITGYM_GRADER_LOG`` file, else stderr)."""
    public, private = load_episode(episode_dir)
    ids = IdTranslator(public)
    result = Grader().score(ids.findings(findings), truth=ids.truth(private["truth"]),
                            public=public, inspection_steps=inspection_steps)
    if not result.valid:
        _log({"episode_id": private["truth"]["episode_id"], "invalid_submission": result.errors})
        return {"tp": None, "fp": None, "fn": None, "precision": None, "recall": None,
                "f1": None, "return": -1.0}
    return {"tp": result.tp, "fp": result.fp, "fn": result.fn, "precision": result.precision,
            "recall": result.recall, "f1": result.f1, "return": result.reward}


def _log(record: dict) -> None:
    line = json.dumps(record, ensure_ascii=False)
    path = os.environ.get("AUDITGYM_GRADER_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    else:
        print(line, file=sys.stderr)
