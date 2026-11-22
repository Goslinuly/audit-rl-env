"""The organisers' check definitions, run through ``judge_adapter`` only.

C01–C20 (contract), D01–D20 (episodes), 1–20 and M01–M12 (matcher and reward), P01–P20
(pairs). The transformations, the fixtures and the accounting checks here are written from
the definitions and do not use the team's transforms, verifier or reference auditor.
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import subprocess
import sys
import textwrap
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path

import judge_adapter as judge
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = json.loads((ROOT / "configs/judge/scenarios.json").read_text(encoding="utf-8"))
SEEDS = (101, 7_654_321)
KEYS = {"ledger": "row_id", "invoices": "invoice_id", "payments": "payment_id"}


# --- files, read and written without the team's io module -----------------------------------
def _csv(text):
    return [{k: (v or None) for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]


def read_dir(d: Path) -> dict:
    out = {n: json.loads((d / f"{n}.json").read_text("utf-8"))
           for n in ("manifest", "policy", "truth", "provenance")}
    out["ledger"] = _csv((d / "ledger.csv").read_text("utf-8"))
    out["fx"] = _csv((d / "fx.csv").read_text("utf-8"))
    for n in ("invoices", "payments"):
        out[n] = [json.loads(x) for x in (d / f"{n}.jsonl").read_text("utf-8").splitlines()]
    return out


def write_dir(d: Path, data: dict) -> Path:
    d.mkdir()
    for n in ("manifest", "policy", "truth", "provenance"):
        (d / f"{n}.json").write_text(json.dumps(data[n], ensure_ascii=False), "utf-8")
    for n in ("ledger", "fx"):
        buf = io.StringIO()
        w = csv.DictWriter(buf, list(data[n][0]), lineterminator="\n")
        w.writeheader()
        w.writerows({k: "" if v is None else v for k, v in r.items()} for r in data[n])
        (d / f"{n}.csv").write_text(buf.getvalue(), "utf-8")
    for n in ("invoices", "payments"):
        (d / f"{n}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data[n]), "utf-8")
    return d


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    cache: dict = {}

    def get(name: str, seed: int = SEEDS[0]) -> Path:
        if (name, seed) not in cache:
            d = tmp_path_factory.mktemp(f"{name}-{seed}") / "episode"
            judge.generate_episode(seed, SCENARIOS[name]["team_config"], str(d))
            cache[name, seed] = d
        return cache[name, seed]

    return get


@pytest.fixture
def env():
    with judge.make_env() as e:
        yield e


def act(name, **args):
    return {"name": name, "args": args}


def closed(d, mode="closed"):
    return {"mode": mode, "episode_dir": str(d), "team_config": {}}


def oracle(data: dict) -> dict:
    return {"episode_id": data["truth"]["episode_id"], "findings": [
        {"type": i["type"], "affected_ids": i["affected_ids"], "currency": i["currency"],
         "claimed_amount_minor": i["expected_amount_minor"],
         "evidence_ids": i["evidence_sets"][0], "explanation": "oracle"}
        for i in data["truth"]["issues"]]}


def empty(data: dict) -> dict:
    return {"episode_id": data["truth"]["episode_id"], "findings": []}


# === Block 1: contract =======================================================================
def test_C01_C02_C03_reset(env, made):
    d = made("D01")
    data = read_dir(d)
    obs, info = env.reset(5, closed(d))
    json.dumps([obs, info], allow_nan=False)
    assert set(obs) == {"task", "manifest", "policy", "remaining_steps"}
    assert obs["remaining_steps"] == 100
    m = obs["manifest"]
    for key in ("schema_version", "episode_id", "base_currency", "period_start", "period_end",
                "timezone", "counts", "rounding"):
        assert key in m
    assert m["counts"]["ledger_rows"] == len(data["ledger"])
    assert m["counts"]["documents"] == len(data["invoices"]) + len(data["payments"])
    assert m["counts"]["fx_rates"] == len(data["fx"])
    assert "seed" not in json.dumps([obs, info]).lower()


def _ints(rows):
    return [{**r, "debit_minor": int(r["debit_minor"]), "credit_minor": int(r["credit_minor"])}
            for r in rows]


def test_C04_C05_C06_list_records(env, made):
    d = made("D16")
    data = read_dir(d)
    env.reset(1, closed(d))
    assert len(data["ledger"]) >= 101
    for table in ("ledger", "invoices", "payments", "fx"):
        rows, cursor, pages = [], None, 0
        while True:
            obs, reward, term, trunc, info = env.step(act("list_records", table=table, cursor=cursor, limit=50))
            assert (reward, term, trunc) == (0, False, False) and type(term) is type(trunc) is bool
            assert set(obs) == {"result", "error", "remaining_steps"} and obs["error"] is None
            assert set(obs["result"]) == {"records", "next_cursor"}
            assert len(obs["result"]["records"]) <= 50
            again = env.step(act("list_records", table=table, cursor=cursor, limit=50))[0]
            assert again["result"] == obs["result"]
            rows += obs["result"]["records"]
            cursor, pages = obs["result"]["next_cursor"], pages + 1
            if cursor is None:
                break
        assert rows == (_ints(data["ledger"]) if table == "ledger" else data[table])
        assert pages == -(-len(rows) // 50)


def test_C07_to_C14_actions_and_errors(env, made):
    d = made("D01")
    data = read_dir(d)
    obs, _ = env.reset(1, closed(d))
    left = obs["remaining_steps"]
    for table, key in KEYS.items():
        rec = data[table][0] if table != "ledger" else _ints(data["ledger"])[0]
        for rid in (rec[key], f"{table}:{rec[key]}"):
            obs = env.step(act("get_record", table=table, id=rid))[0]
            left -= 1
            assert obs == {"result": rec, "error": None, "remaining_steps": left}
    fx = data["fx"][0]
    parts = [fx["date"], fx["source_currency"], fx["target_currency"]]
    for rid in (":".join(parts), "/".join(parts), "fx:" + ":".join(parts)):
        obs = env.step(act("get_record", table="fx", id=rid))[0]
        left -= 1
        assert obs["result"] == fx
    for doc in (data["invoices"][0], data["payments"][0]):
        obs = env.step(act("get_document", doc_id=doc["doc_id"]))[0]
        left -= 1
        assert obs["result"] == doc
    obs = env.step(act("calculator", expression="0.1+0.2"))[0]
    left -= 1
    assert Decimal(obs["result"]) == Decimal("0.3") and isinstance(obs["result"], str)
    bad = [act("calculator", expression="open('/etc/passwd').read()"),
           act("calculator", expression="__import__('os').getcwd()"),
           act("get_record", table="ledger", id="NOPE-U"), act("get_document", doc_id="NOPE-U"),
           act("get_document", doc_id="../private/truth.json"), act("shell", cmd="ls"),
           act("list_records", table="truth", cursor=None, limit=50),
           act("list_records", table="ledger", cursor="forged", limit=50),
           act("list_records", table="ledger", cursor=None, limit=51),
           {"name": "get_record"}, {"name": None}, {}, "x", None, 7,
           {"name": "get_record", "args": {"table": ["ledger"], "id": {}}},
           {"name": "get_record", "args": {"table": "fx", "id": 5}},
           {"name": "submit"}, {"name": "submit", "args": {}}]
    for action in bad:
        obs, reward, term, trunc, _ = env.step(action)
        left -= 1
        assert obs["result"] is None and set(obs["error"]) == {"code", "message"}
        assert obs["remaining_steps"] == left and (reward, term, trunc) == (0, False, False)
        assert not re.search(r"/|Traceback|\.py|private", obs["error"]["message"].replace("+ - * /", ""))
    rec = _ints(data["ledger"])[0]
    obs = env.step(act("get_record", table="ledger", id=rec["row_id"]))[0]
    assert obs == {"result": rec, "error": None, "remaining_steps": left - 1}


@pytest.mark.parametrize("mode", ["closed", "train"])
def test_C15_C19_submit_is_final_and_silent_in_closed_mode(env, made, mode):
    d = made("D06")
    data = read_dir(d)
    env.reset(1, closed(d, mode))
    for _ in range(3):
        assert env.step(act("calculator", expression="1"))[1] == 0
    obs, reward, term, trunc, info = env.step(act("submit", findings=oracle(data)))
    assert term and not trunc and obs["result"] == {"accepted": True} and obs["error"] is None
    assert reward == (0 if mode == "closed" else 1 - 0.006) and type(reward) in (int, float)
    assert set(info) == {"episode_id", "env_version"}
    for sub in (empty(data), oracle(data)):
        obs, reward, term, _, _ = env.step(act("submit", findings=sub))
        assert obs["error"]["code"] == "episode_over" and reward == 0 and term
    grade = env._env.grade_log
    assert len(grade) == 1 and grade[0]["f1"] == 1.0  # known to the judge side only


def test_C16_submit_is_accepted_as_action_100(env, made):
    d = made("D06")
    data = read_dir(d)
    env.reset(1, closed(d, "train"))
    for _ in range(99):
        assert env.step(act("calculator", expression="1"))[2:4] == (False, False)
    obs, reward, term, trunc, _ = env.step(act("submit", findings=oracle(data)))
    assert term and not trunc and obs["remaining_steps"] == 0
    assert abs(reward - (1 - 0.002 * 99)) < 1e-9


def test_C17_hundred_actions_without_submit(env, made):
    d = made("D06")
    data = read_dir(d)
    env.reset(1, closed(d, "train"))
    for _ in range(100):
        _, reward, term, trunc, _ = env.step(act("calculator", expression="1"))
    assert trunc and not term and reward == -1
    assert env._env.grade_log[-1]["n_findings"] == 0
    assert env.step(act("submit", findings=oracle(data)))[1] == 0
    assert len(env._env.grade_log) == 1


def test_C18_time_limit_counts_from_reset_and_policy_time(made):
    d = made("D06")
    data = read_dir(d)
    now = [0.0]
    with judge.JudgeEnv(clock=lambda: now[0]) as e:
        e.reset(1, closed(d, "train"))
        now[0] = 59.9
        assert e.step(act("calculator", expression="1"))[2:4] == (False, False)
        now[0] = 60.1
        obs, reward, term, trunc, _ = e.step(act("submit", findings=oracle(data)))
        assert trunc and not term and reward == -1 and obs["error"]["code"] == "time_limit"
        assert e._env.grade_log[-1]["n_findings"] == 0
    with judge.JudgeEnv(time_limit_s=0.2) as e:  # real clock
        import time
        e.reset(1, closed(d))
        time.sleep(0.25)
        assert e.step(act("calculator", expression="1"))[3] is True


def test_time_limit_includes_loading(made, monkeypatch):
    now = [0.0]
    with judge.JudgeEnv(clock=lambda: now[0]) as e:
        e.reset(1, closed(made("D01")))
        start = e._env._backend.start

        def slow(*a):
            now[0] += 61
            return start(*a)

        monkeypatch.setattr(e._env._backend, "start", slow)
        e.reset(1, closed(made("D01")))
        assert e.step(act("calculator", expression="1"))[3] is True


@pytest.mark.parametrize("name", ["D01", "D06", "D16", "D19"])
def test_C20_everything_a_policy_can_read_is_free_of_the_answer(env, made, name):
    d = made(name)
    data = read_dir(d)
    seen = []
    seen.append(env.reset(1, closed(d)))
    actions = []
    for table in ("ledger", "invoices", "payments", "fx"):
        for rec in data[table]:
            rid = rec.get(KEYS.get(table, "")) or ":".join(
                (rec["date"], rec["source_currency"], rec["target_currency"]))
            actions.append(act("get_record", table=table, id=rid))
    actions += [act("get_document", doc_id=x["doc_id"]) for x in data["invoices"] + data["payments"]]
    for n, action in enumerate(actions):
        if n % 99 == 0:
            env.reset(1, closed(d))
        out = env.step(action)
        assert out[0]["error"] is None, action
        seen.append(out)
    for x in ("truth", "provenance", "truth.json", str(d), "../truth.json", "file:///etc/passwd"):
        env.reset(1, closed(d))
        seen += [env.step(act("get_document", doc_id=x)), env.step(act("get_record", table="ledger", id=x)),
                 env.step(act("list_records", table=x, cursor=None, limit=5)),
                 env.step(act("calculator", expression=x))]
        assert all(o[0]["error"] for o in seen[-4:])
    env.reset(1, closed(d))
    seen.append(env.step(act("submit", findings=oracle(data))))
    text = json.dumps(seen, ensure_ascii=False)
    secret = [i["issue_id"] for i in data["truth"]["issues"]]
    secret += [i["description"] for i in data["truth"]["issues"] if i.get("description")]
    secret += ["evidence_sets", "expected_amount", "affected_ids\": [\"", "provenance", "truth",
               "generator_version", "config_version", '"seed"', str(d), "ledger_diff"]
    for s in secret:
        assert s not in text, s


def test_closed_backend_never_holds_the_private_part(env, made):
    env.reset(1, closed(made("D16")))
    from auditgym.env.grading import ProcessBackend
    assert type(env._env._backend) is ProcessBackend
    assert env._env.isolation == "process"


def test_reset_does_not_keep_state_and_repeats_exactly(env, made):
    d, other = made("D16"), made("D01")
    data = read_dir(d)
    script = [act("list_records", table="ledger", cursor=None, limit=50), act("get_record", table="ledger", id="U"),
              act("calculator", expression="7/3"), act("submit", findings=oracle(data))]

    def play():
        out = [env.reset(3, closed(d, "train"))]
        out += [env.step(a) for a in script]
        return json.loads(json.dumps(out))

    first = play()
    env.reset(3, closed(other, "train"))
    env.step(act("list_records", table="ledger", cursor=None, limit=50))
    assert play() == first


def test_reset_without_episode_dir_generates(env):
    cfg = {"mode": "train", "team_config": SCENARIOS["D06"]["team_config"]}
    a = env.reset(11, cfg)
    b = env.reset(11, cfg)
    c = env.reset(12, cfg)
    assert a == b != c


# A harness script without a __main__ guard, and a daemonic worker, must both be able to start it.
def test_closed_env_starts_from_a_plain_script(tmp_path, made):
    script = tmp_path / "harness.py"
    script.write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        import judge_adapter as j
        e = j.make_env()
        obs, info = e.reset(1, {{"mode": "closed", "episode_dir": {str(made("D01"))!r}, "team_config": {{}}}})
        print(e.step({{"name": "calculator", "args": {{"expression": "1+1"}}}})[0]["result"])
        e.close()
    """), "utf-8")
    run = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                         cwd=tmp_path, timeout=60)
    assert run.returncode == 0 and run.stdout.strip() == "2", run.stderr


# === Block 2: episodes ======================================================================
EXPECTED = {**{f"D{i:02d}": [] for i in range(1, 6)},
            **{f"D{i:02d}": ["duplicate_invoice"] for i in (6, 7, 8)},
            **{f"D{i:02d}": ["payment_allocation"] for i in (9, 10, 11)},
            **{f"D{i:02d}": ["fx_conversion"] for i in (12, 13)},
            **{f"D{i:02d}": ["period_cutoff"] for i in (14, 15)},
            **{f"D{i:02d}": ["fx_conversion", "payment_allocation", "period_cutoff"] for i in (16, 17, 18)},
            **{f"D{i:02d}": ["duplicate_invoice", "fx_conversion"] for i in (19, 20)}}


class Books:
    """Independent re-computation from the public files only."""

    def __init__(self, data):
        self.d, self.m = data, data["manifest"]
        self.base = self.m["base_currency"]
        self.start = datetime.fromisoformat(self.m["period_start"])
        self.end = datetime.fromisoformat(self.m["period_end"])
        self.rates = {(r["date"], r["source_currency"]): r["rate"] for r in data["fx"]
                      if r["target_currency"] == self.base}
        self.docs = {f"invoices:{i['invoice_id']}": i for i in data["invoices"]}
        self.docs |= {f"payments:{p['payment_id']}": p for p in data["payments"]}
        self.ledger = _ints(data["ledger"])

    def when(self, doc):
        return datetime.fromisoformat(doc.get("issued_at") or doc["timestamp"]).astimezone(self.start.tzinfo)

    def amount(self, doc):
        return abs(doc["total_minor"] if "total_minor" in doc else doc["amount_minor"])  # refunds < 0

    def correct(self, doc):
        ccy, day = doc["currency"], self.when(doc).date()
        if ccy == self.base:
            return self.amount(doc)
        while (day.isoformat(), ccy) not in self.rates:
            day -= timedelta(days=1)
            assert day > date(2000, 1, 1)
        exp = {c: v["exponent"] for c, v in self.m["currencies"].items()}
        mode = {"ROUND_HALF_EVEN": ROUND_HALF_EVEN, "ROUND_HALF_UP": ROUND_HALF_UP}[self.m["rounding"]["mode"]]
        v = Decimal(self.amount(doc)) * Decimal(self.rates[day.isoformat(), ccy])
        return int(v.scaleb(exp[self.base] - exp[ccy]).quantize(Decimal(1), rounding=mode))

    def booked(self, ref):
        doc = self.docs[ref]
        if "invoice_id" in doc and "total_minor" in doc:
            rows = [r for r in self.ledger if r["invoice_id"] == doc["invoice_id"] and not r["payment_id"]
                    and r["account"] == "accounts_receivable"]
        else:
            rows = [r for r in self.ledger if r["payment_id"] == doc["payment_id"]
                    and r["account"].startswith("bank:")]
        return rows

    def check(self, issue):
        amount, evidence = issue["expected_amount_minor"], set(issue["evidence_sets"][0])
        if issue["type"] == "duplicate_invoice":
            (dup,) = issue["affected_ids"]
            (orig,) = evidence - {dup}
            a, b = self.docs[dup], self.docs[orig]
            for k in ("entity_id", "currency", "total_minor", "line_items"):
                assert a[k] == b[k]
            assert self.when(b) <= self.when(a) and self.booked(dup) and self.booked(orig)
            assert (amount, issue["currency"]) == (a["total_minor"], a["currency"])
        elif issue["type"] == "payment_allocation":
            pay = next(self.docs[x] for x in issue["affected_ids"] if x.startswith("payments:"))
            inv = next(self.docs[x] for x in issue["affected_ids"] if x.startswith("invoices:"))
            rest = pay["amount_minor"] - sum(r["applied_minor"] for r in pay["invoice_refs"])
            paid = sum(r["applied_minor"] for p in self.d["payments"] for r in p["invoice_refs"]
                       if r["invoice_id"] == inv["invoice_id"])
            assert pay["entity_id"] == inv["entity_id"] and pay["currency"] == inv["currency"]
            assert 0 < rest == inv["total_minor"] - paid == amount
            assert issue["currency"] == pay["currency"]
        elif issue["type"] == "fx_conversion":
            (ref,) = issue["affected_ids"]
            (row,) = self.booked(ref)
            booked = row["debit_minor"] or row["credit_minor"]
            assert abs(booked - self.correct(self.docs[ref])) == amount > 0
            assert issue["currency"] == self.base and f"ledger:{row['row_id']}" in evidence
        else:
            (ref,) = issue["affected_ids"]
            (row,) = self.booked(ref)
            assert not self.start <= self.when(self.docs[ref]) < self.end
            assert (row["debit_minor"] or row["credit_minor"]) == amount
            assert issue["currency"] == self.base and f"ledger:{row['row_id']}" in evidence

    def every_document_is_correct_except(self, refs):
        for ref, doc in self.docs.items():
            rows = self.booked(ref)
            inside = self.start <= self.when(doc) < self.end
            if ref not in refs:
                assert bool(rows) == inside, ref
                for r in rows:
                    assert (r["debit_minor"] or r["credit_minor"]) == self.correct(doc), ref


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_D_block(made, name, seed):
    d = made(name, seed)
    data = read_dir(d)
    issues = data["truth"]["issues"]
    assert sorted(i["type"] for i in issues) == EXPECTED[name]
    books = Books(data)
    entries: dict = {}
    for r in books.ledger:
        assert (r["debit_minor"] > 0) != (r["credit_minor"] > 0) and r["currency"] == books.base
    assert sum(r["debit_minor"] - r["credit_minor"] for r in books.ledger) == 0
    for r in books.ledger:
        key = r["payment_id"] or r["invoice_id"]
        if key:
            entries[key] = entries.get(key, 0) + r["debit_minor"] - r["credit_minor"]
    assert not any(entries.values())
    for i in issues:
        books.check(i)
    books.every_document_is_correct_except({x for i in issues for x in i["affected_ids"]})
    # 1: state before the injection is recorded, and every change is linked to an issue
    prov = data["provenance"]
    assert prov["pre_injection"]["total_debit_minor"] == prov["pre_injection"]["total_credit_minor"]
    assert bool(prov["changes"]) == bool(issues)
    assert {x for c in prov["changes"] for x in c["issue_ids"]} == {i["issue_id"] for i in issues}
    # 5: formats
    for doc in books.docs.values():
        assert datetime.fromisoformat(doc.get("issued_at") or doc["timestamp"]).tzinfo
        assert type(books.amount(doc)) is int
    if name == "D09":
        assert next(c for c in prov["changes"] if c["field"] == "invoice_refs")["after"] == []
    if name == "D10":
        assert len(next(c for c in prov["changes"] if c["field"] == "invoice_refs")["after"]) == 1
    # 4: one evidence set is readable through the actions
    with judge.make_env() as e:
        e.reset(seed, closed(d))
        for ref in {x for i in issues for x in i["evidence_sets"][0]}:
            table, _, key = ref.partition(":")
            assert e.step(act("get_record", table=table, id=key))[0]["error"] is None


@pytest.mark.parametrize("name,kind", [("D02", "split_payment"), ("D03", "refund"), ("D04", "recurring"),
                                       ("D05", "boundary")])
def test_D02_to_D05_contain_the_promised_case(made, name, kind):
    for seed in SEEDS:
        assert read_dir(made(name, seed))["provenance"]["sampled"]["distractors"][kind] > 0


def test_D06_to_D20_vary(made):
    for group in (("D06", "D07", "D08"), ("D16", "D17", "D18"), ("D19", "D20")):
        amounts = set()
        for n, name in enumerate(group):
            amounts.add(read_dir(made(name, 500 + n))["truth"]["issues"][0]["expected_amount_minor"])
        assert len(amounts) == len(group)


# === Block 3: matcher and reward ============================================================
T = "duplicate_invoice"


def issue(iid="A", aff=("ledger:R1",), ev=("invoices:D1", "invoices:D2"), tol=0, amount=10000):
    return {"issue_id": iid, "type": T, "affected_ids": list(aff), "expected_amount_minor": amount,
            "currency": "KZT", "evidence_sets": [list(ev)], "tolerance_minor": tol, "group": None,
            "description": ""}


def finding(**k):
    return {"type": T, "affected_ids": ["ledger:R1"], "claimed_amount_minor": 10000, "currency": "KZT",
            "evidence_ids": ["invoices:D1", "invoices:D2"], "explanation": "ok", **k}


@pytest.fixture(scope="module")
def score(made, tmp_path_factory):
    data = read_dir(made("D01"))
    for n in range(5):
        data["ledger"][n]["row_id"] = f"R{n + 1}"
        data["invoices"][n]["invoice_id"] = f"D{n + 1}"
    root = tmp_path_factory.mktemp("matcher")
    counter = iter(range(10**6))

    def run(issues, findings, steps=10):
        eid = data["truth"]["episode_id"]
        d = write_dir(root / f"e{next(counter)}", {**data, "truth": {**data["truth"], "issues": issues}})
        return judge.score_episode(str(d), {"episode_id": eid, "findings": findings}, steps)

    return run


A, B = issue(), issue("B", aff=("ledger:R4",), ev=("invoices:D4", "invoices:D5"))
MASS = [finding(type=t, affected_ids=[f"ledger:R{n}"]) for n in range(1, 6) for t in judge.ISSUE_TYPES]
VECTORS = [
    (1, [A], [finding()], (1, 0, 0), Fraction(98, 100), 10),
    (2, [A], [], (0, 0, 1), -1, 10),
    (3, [], [], (0, 0, 0), Fraction(98, 100), 10),
    (4, [], [finding()], (0, 1, 0), -1, 10),
    (5, [A], [finding(), finding()], (1, 1, 0), Fraction(47, 150), 10),
    (6, [A], [finding(type="fx_conversion")], (0, 1, 1), -1, 10),
    (7, [A], [finding(affected_ids=["ledger:R3"])], (0, 1, 1), -1, 10),
    (8, [A], [finding(claimed_amount_minor=10001)], (0, 1, 1), -1, 10),
    (9, [A], [finding(currency="USD")], (0, 1, 1), -1, 10),
    (10, [A], [finding(evidence_ids=["invoices:D1"])], (0, 1, 1), -1, 10),
    (11, [A], [finding(evidence_ids=["invoices:D1", "invoices:NOPE"])], (0, 1, 1), -1, 10),
    (12, [A], MASS, (1, 19, 0), Fraction(-871, 1050), 10),
    (13, [A, B], [finding()], (1, 0, 1), Fraction(47, 150), 10),
    (14, [A, B], [finding(), finding(type="fx_conversion")], (1, 1, 1), Fraction(-2, 100), 10),
    (15, [A], [finding()], (1, 0, 0), 1, 0),
    (16, [A], [finding()], (1, 0, 0), Fraction(9, 10), 50),
    (17, [A], [finding()], (1, 0, 0), Fraction(8, 10), 100),
]


@pytest.mark.parametrize("n,truth,found,counts,reward,steps", VECTORS, ids=[f"test{v[0]}" for v in VECTORS])
def test_matcher_vectors(score, n, truth, found, counts, reward, steps):
    r = score(truth, found, steps)
    tp, fp, fn = counts
    assert (r["tp"], r["fp"], r["fn"]) == counts
    assert abs(r["return"] - float(reward)) <= 1e-9
    p, rec = (Fraction(tp, tp + fp) if tp + fp else 0), (Fraction(tp, tp + fn) if tp + fn else 0)
    f1 = (1 if not fp else 0) if not truth else Fraction(2 * tp, 2 * tp + fp + fn)
    for key, want in (("precision", p), ("recall", rec), ("f1", f1)):
        assert abs(r[key] - float(want)) <= 1e-9


INVALID = {
    "test18": [finding()] * 31,
    "test19": [finding(evidence_ids=[f"ledger:R{n}" for n in range(11)])],
    "test20": [finding(explanation="a" * 1001)],
    "M05": [finding(evidence_ids=["invoices:D1"] * 10 + ["invoices:D2"])],
    "M09 string": [finding(claimed_amount_minor="10000")],
    "M09 bool": [finding(claimed_amount_minor=True)],
    "float": [finding(claimed_amount_minor=10000.0)],
    "missing field": [{k: v for k, v in finding().items() if k != "currency"}],
}


@pytest.mark.parametrize("name", INVALID)
def test_invalid_structure(score, made, env, name, tmp_path, monkeypatch):
    log = tmp_path / "grader.jsonl"
    monkeypatch.setenv("AUDITGYM_GRADER_LOG", str(log))
    r = score([A], INVALID[name])
    assert r.pop("return") == -1 and set(r.values()) == {None}
    assert json.loads(log.read_text("utf-8").splitlines()[0])["invalid_submission"]
    d = made("D06")
    eid = read_dir(d)["truth"]["episode_id"]
    for mode in ("train", "closed"):
        env.reset(1, closed(d, mode))
        obs, reward, term, _, _ = env.step(act("submit", findings={"episode_id": eid, "findings": INVALID[name]}))
        assert term and obs["error"]["code"] == "invalid_submission" and obs["result"] is None
        assert reward == (-1 if mode == "train" else 0)


M = [issue(aff=("ledger:R1", "ledger:R2"))]


def mf(**k):
    return finding(**{"affected_ids": ["ledger:R1", "ledger:R2"], **k})


@pytest.mark.parametrize("name,truth,found,tp", [
    ("M01", M, mf(affected_ids=["ledger:R2", "ledger:R1", "ledger:R1"]), 1),
    ("M02", M, mf(affected_ids=["ledger:R1", "ledger:R2", "ledger:R3"]), 0),
    ("M03", M, mf(evidence_ids=["invoices:D2", "invoices:D1", "invoices:D3"]), 1),
    ("M04", M, mf(evidence_ids=["invoices:D1", "invoices:D2", "invoices:U"]), 0),
    ("M06 case", M, mf(currency="kzt"), 0),
    ("M06 space", M, mf(currency="KZT "), 0),
    ("M07", M, mf(claimed_amount_minor=10001), 0),
    ("M08 edge", [issue(aff=("ledger:R1", "ledger:R2"), tol=1)], mf(claimed_amount_minor=10001), 1),
    ("M08 over", [issue(aff=("ledger:R1", "ledger:R2"), tol=1)], mf(claimed_amount_minor=10002), 0),
    ("unknown type", M, mf(type="something_else"), 0),
    ("unknown currency", M, mf(currency="TENGE"), 0),
    ("ID with a space", M, mf(affected_ids=["ledger:R1 ", "ledger:R2"]), 0),
    ("ID case", M, mf(affected_ids=["ledger:r1", "ledger:R2"]), 0),
])
def test_matcher_examples(score, name, truth, found, tp):
    r = score(truth, [found])
    assert (r["tp"], r["fp"], r["fn"]) == (tp, 1 - tp, 1 - tp)


def test_M10_M11_M12_matching():
    from auditgym.grader import Grader

    public = {"ledger": [{"row_id": "R1"}], "payments": [], "fx": [],
              "invoices": [{"invoice_id": f"D{n}", "doc_id": f"X{n}"} for n in (1, 2)]}

    def run(issues, findings):
        return Grader().score({"episode_id": "e", "findings": findings},
                              truth={"episode_id": "e", "issues": issues}, public=public)

    ab = [issue("A", ev=("invoices:D1",)), issue("B", ev=("invoices:D2",))]
    f0, f1 = finding(), finding(evidence_ids=["invoices:D1"])
    r = run(ab, [f0, f1])
    assert (r.tp, r.fp, r.fn) == (2, 0, 0)
    assert {(m["issue_id"], m["finding_index"]) for m in r.matches} == {("A", 1), ("B", 0)}
    for truth in ([issue("A"), issue("B")], [issue("B"), issue("A")]):
        r = run(truth, [finding(), finding()])
        assert r.tp == 2 and {(m["issue_id"], m["finding_index"]) for m in r.matches} == {("A", 0), ("B", 1)}
    r = run([issue()], [finding(), finding()])
    assert (r.tp, r.fp, r.fn) == (1, 1, 0) and r.matches[0]["finding_index"] == 0


def test_tie_break_is_lexicographically_smallest_by_brute_force():
    import itertools

    from auditgym.grader.matcher import _lexicographic_max_matching

    rng = random.Random(4)
    for _ in range(400):
        n, k = rng.randint(0, 4), rng.randint(0, 4)
        edges = {j: [i for i in range(n) if rng.random() < 0.5] for j in range(k)}
        best = None
        for choice in itertools.product(*[[None, *edges[j]] for j in range(k)]):
            used = [c for c in choice if c is not None]
            if len(used) != len(set(used)):
                continue
            pairs = [(j, c) for j, c in enumerate(choice) if c is not None]
            key = (-len(pairs), pairs)
            best = key if best is None or key < best else best
        got = _lexicographic_max_matching(list(range(k)), edges)
        assert sorted((j, i) for i, j in got) == best[1]


@pytest.mark.parametrize("char", ["a", "я", "😀", "\u0001"])
def test_largest_valid_submit_is_accepted(env, made, char):
    d = made("D06")
    data = read_dir(d)
    big = {"episode_id": data["truth"]["episode_id"],
           "findings": [finding(explanation=char * 1000)] * 29 + oracle(data)["findings"]}
    env.reset(1, closed(d, "train"))
    obs, reward, term, _, _ = env.step(act("submit", findings=big))
    assert term and obs["result"] == {"accepted": True} and reward > -1
    big["findings"].append(finding(explanation=char * 1000))
    env.reset(1, closed(d, "train"))
    obs, reward, term, _, _ = env.step(act("submit", findings=big))
    assert term and reward == -1 and obs["error"]["code"] == "invalid_submission"


def test_oversized_submit_ends_the_episode(env, made):
    d = made("D06")
    sub = {"episode_id": read_dir(d)["truth"]["episode_id"], "findings": [finding(explanation="a" * 2_000_000)]}
    env.reset(1, closed(d, "train"))
    _, reward, term, _, _ = env.step(act("submit", findings=sub))
    assert term and reward == -1


# --- raw record IDs of a general policy -----------------------------------------------------
def test_raw_record_ids_are_translated_exactly(made):
    for name in ("D06", "D09", "D12", "D14", "D16", "D19"):
        d = made(name)
        data = read_dir(d)
        docs = {i["invoice_id"]: i["doc_id"] for i in data["invoices"]}
        docs |= {p["payment_id"]: p["doc_id"] for p in data["payments"]}

        def raw(ref, use_doc, docs=docs):
            table, _, key = ref.partition(":")
            if table == "fx":
                return key.replace("/", ":")
            return docs.get(key, key) if use_doc else key

        want = judge.score_episode(str(d), oracle(data), 5)
        assert want["f1"] == 1.0
        for use_doc in (False, True):
            sub = oracle(data)
            for f in sub["findings"]:
                for key in ("affected_ids", "evidence_ids"):
                    f[key] = [raw(x, use_doc) for x in f[key]]
            assert judge.score_episode(str(d), sub, 5) == want
            for f in sub["findings"]:
                f["affected_ids"] = [x.lower() for x in f["affected_ids"]]
            assert judge.score_episode(str(d), sub, 5)["tp"] == 0


# === Block 4: pairs =========================================================================
def reorder(data, seed):
    out = json.loads(json.dumps(data))
    rng = random.Random(seed)
    for table in ("ledger", "invoices", "payments", "fx"):
        rng.shuffle(out[table])
    return out


def rename(data):
    """One-to-one renaming in separate ID spaces, applied to every reference in every file."""
    maps: dict[str, dict] = {}

    def new(space, old):
        m = maps.setdefault(space, {})
        return m.setdefault(old, f"{space[:2].upper()}{len(m) * 7919 % 100003:06d}x{len(m)}")

    out = json.loads(json.dumps(data))
    for t in ("ledger", "invoices", "payments"):
        for r in out[t]:
            for k in ("row_id", "doc_id", "invoice_id", "payment_id", "entity_id"):
                if r.get(k) is not None:
                    r[k] = new(k, r[k])
    for p in out["payments"]:
        for ref in p["invoice_refs"]:
            ref["invoice_id"] = new("invoice_id", ref["invoice_id"])
        if p["refund_of"]:
            p["refund_of"] = new("payment_id", p["refund_of"])
    space = {"ledger": "row_id", "invoices": "invoice_id", "payments": "payment_id"}

    def ref(x):
        table, _, key = x.partition(":")
        return f"{table}:{new(space[table], key)}" if table in space else x

    for i in out["truth"]["issues"]:
        i["affected_ids"] = [ref(x) for x in i["affected_ids"]]
        i["evidence_sets"] = [[ref(x) for x in s] for s in i["evidence_sets"]]
    back = {f"{t}:{v}": f"{t}:{k}" for t, s in space.items() for k, v in maps.get(s, {}).items()}
    return out, back


def play(d, data, steps=4):
    log = []
    with judge.make_env() as e:
        log.append(e.reset(9, closed(d, "train")))
        for _ in range(steps):
            log.append(e.step(act("list_records", table="ledger", cursor=None, limit=50)))
        log.append(e.step(act("submit", findings=oracle(data))))
    return json.loads(json.dumps(log))


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("n", range(1, 21))
def test_P_block(made, tmp_path, n, seed):
    src = made(f"D{n:02d}", seed)
    before = {p.name: p.read_bytes() for p in src.iterdir()}
    data = read_dir(src)
    first = play(src, data)
    assert play(src, data) == first  # 1: exact repeat
    changed, back = data, {}
    if n > 5:
        changed, back = rename(changed)
    if n <= 5 or n > 10:
        changed = reorder(changed, seed + n)
    d2 = write_dir(tmp_path / "variant", changed)
    second = play(d2, changed)
    assert second[-1][1] == first[-1][1] and second[-1][2] is True  # same terminal reward
    a = judge.score_episode(str(src), oracle(data), 4)
    b = judge.score_episode(str(d2), oracle(changed), 4)
    assert a == b and a["f1"] == 1.0 and abs(a["return"] - 0.992) <= 1e-9
    for f, g in zip(oracle(data)["findings"], oracle(changed)["findings"], strict=True):  # 2
        for key in ("affected_ids", "evidence_ids"):
            g[key] = [back.get(x, x) for x in g[key]]
        assert {**f, "affected_ids": set(f["affected_ids"]), "evidence_ids": set(f["evidence_ids"])} == \
               {**g, "affected_ids": set(g["affected_ids"]), "evidence_ids": set(g["evidence_ids"])}
    with judge.make_env() as e:  # 4: evidence still reachable
        e.reset(9, closed(d2))
        for x in {x for i in changed["truth"]["issues"] for x in i["evidence_sets"][0]}:
            table, _, key = x.partition(":")
            assert e.step(act("get_record", table=table, id=key))[0]["error"] is None
    Books(changed).every_document_is_correct_except(
        {x for i in changed["truth"]["issues"] for x in i["affected_ids"]})
    for i in changed["truth"]["issues"]:
        Books(changed).check(i)
    assert {p.name: p.read_bytes() for p in src.iterdir()} == before  # source untouched
