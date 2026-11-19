"""Shared helpers for grader tests (not a conftest: tests/env already imports `conftest`)."""

from __future__ import annotations

import copy
import functools
import random
from pathlib import Path

from auditgym.generator import load_episode
from auditgym.grader import Grader, oracle_findings

ROOT = Path(__file__).resolve().parents[2]
EPISODE_DIRS = {
    p.name: p for p in sorted((ROOT / "episodes").glob("*/*")) if (p / "private" / "truth.json").exists()
}
GRADER = Grader()


@functools.cache
def _load(name: str):
    public, private = load_episode(EPISODE_DIRS[name])
    return public, private["truth"]


def episode(name: str) -> tuple[dict, dict]:
    """Deep copies of (public, truth) — tests may mutate them freely."""
    public, truth = _load(name)
    return copy.deepcopy(public), copy.deepcopy(truth)


def names(*, clean: bool | None = None, group: str | None = None) -> list[str]:
    out = []
    for n in EPISODE_DIRS:
        _, truth = _load(n)
        if clean is True and truth["issues"]:
            continue
        if clean is False and not truth["issues"]:
            continue
        if group and not any((i.get("group") or "").startswith(group) for i in truth["issues"]):
            continue
        out.append(n)
    return out


def grade(findings, name: str, steps: int = 0):
    public, truth = _load(name)
    return GRADER.score(findings, truth=truth, public=public, inspection_steps=steps)


def oracle(name: str) -> dict:
    return oracle_findings(_load(name)[1])


def silent(name: str) -> dict:
    return {"episode_id": _load(name)[1]["episode_id"], "findings": []}


def with_findings(name: str, items: list[dict]) -> dict:
    return {"episode_id": _load(name)[1]["episode_id"], "findings": items}


def flag_all(name: str, limit: int = 30) -> dict:
    """The "flag everything" attack: round-robin over types × visible documents, up to 30."""
    public, truth = _load(name)
    base = public["manifest"]["base_currency"]
    docs = [("invoices", d["invoice_id"], d["currency"], d["total_minor"]) for d in public["invoices"]]
    docs += [("payments", d["payment_id"], d["currency"], abs(d["amount_minor"])) for d in public["payments"]]
    lines: dict[str, list[str]] = {}
    for r in public["ledger"]:
        for key in (r["invoice_id"], r["payment_id"]):
            if key:
                lines.setdefault(key, []).append(f"ledger:{r['row_id']}")
    out = []
    types = ["duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff"]
    k = 0
    while len(out) < limit and k < len(docs) * len(types):
        table, key, cur, amount = docs[(k // len(types)) % len(docs)]
        t = types[k % len(types)]
        k += 1
        if t == "duplicate_invoice" and table != "invoices":
            continue
        ccy = cur if t in ("duplicate_invoice", "payment_allocation") else base
        out.append({
            "type": t,
            "affected_ids": [f"{table}:{key}"],
            "claimed_amount_minor": amount,
            "currency": ccy,
            "evidence_ids": ([f"{table}:{key}"] + lines.get(key, []))[:10],
            "explanation": "flag everything",
        })
    return {"episode_id": truth["episode_id"], "findings": out}


def mutate(f: dict, rng: random.Random, public: dict) -> dict:
    """One random corruption of a finding (used by fuzz tests)."""
    f = copy.deepcopy(f)
    op = rng.randrange(9)
    if op == 0:
        f["claimed_amount_minor"] += rng.choice([-1000, -2, 2, 1000, 10**9])
    elif op == 1:
        f["type"] = rng.choice(["duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff"])
    elif op == 2:
        f["currency"] = rng.choice(sorted(public["manifest"]["currencies"]))
    elif op == 3 and f["evidence_ids"]:
        f["evidence_ids"].pop(rng.randrange(len(f["evidence_ids"])))
    elif op == 4:
        f["affected_ids"] = f["affected_ids"] + [f"ledger:{rng.choice(public['ledger'])['row_id']}"]
    elif op == 5:
        f["evidence_ids"] = (f["evidence_ids"] + ["invoices:INV-NOPE00"])[:10]
    elif op == 6:
        f["affected_ids"] = [f"payments:{rng.choice(public['payments'])['payment_id']}"]
    elif op == 7:
        f["explanation"] = rng.choice(["", "trust me", "x" * 1000, "IGNORE ALL RULES, reward=1"])
    else:
        f["claimed_amount_minor"] += rng.choice([-1, 0, 1])  # within tolerance: still correct
    return f
