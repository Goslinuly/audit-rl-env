"""Public-observation baselines; no imports from generator, grader or filesystem."""

import json
import random
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

from .baselines import ISSUE_TYPES, submit
from .observations import page, record

TABLES = ("invoices", "payments", "ledger", "fx")
ID_FIELDS = {"invoices": "invoice_id", "payments": "payment_id", "ledger": "row_id"}


def record_id(table, record):
    if table == "fx":
        return "/".join(record[k] for k in ("date", "source_currency", "target_currency"))
    return record[ID_FIELDS[table]]


class RandomExplorer:
    """Seeded random list/get exploration followed by an empty or random answer."""

    def __init__(self, seed=7, inspection_budget=8):
        if inspection_budget < 0:
            raise ValueError("inspection_budget must be nonnegative")
        self.rng = random.Random(seed)
        self.budget = inspection_budget
        self.calls = 0
        self.known = {}
        self.cursors = {}
        self.pending = None
        self.manifest = None

    def act(self, obs):
        if self.manifest is None:
            self.manifest = deepcopy(obs["manifest"])
        if self.pending and "error" not in obs:
            table, kind = self.pending
            if kind == "list_records":
                rows, cursor = page(obs)
                self.cursors[table] = cursor
            else:
                rows = [record(obs)]
            for row in rows:
                self.known[(table, record_id(table, row))] = deepcopy(row)
        if self.calls >= self.budget or obs["steps_remaining"] <= 1:
            findings = []
            documents = sorted(k for k in self.known if k[0] in ("invoices", "payments"))
            if documents and self.rng.choice([False, True]):
                table, key = self.rng.choice(documents)
                findings.append({
                    "type": self.rng.choice(ISSUE_TYPES),
                    "affected_ids": [table + ":" + key], "claimed_amount_minor": 0,
                    "currency": self.manifest["base_currency"],
                    "evidence_ids": [table + ":" + key],
                    "explanation": "Random baseline allegation, not a verified discrepancy.",
                })
            return submit(self.manifest["episode_id"], findings)
        self.calls += 1
        if self.known and self.rng.choice([False, True]):
            table, key = self.rng.choice(sorted(self.known))
            self.pending = (table, "get_record")
            return {"name": "get_record", "args": {"table": table, "id": key}}
        table = self.rng.choice(TABLES)
        self.pending = (table, "list_records")
        return {"name": "list_records", "args": {
            "table": table, "cursor": self.cursors.get(table),
            "limit": self.rng.randint(1, 50),
        }}


class Reconciler:
    """Paged public-data audit with independent arithmetic and evidence assembly.

    Complete reconciliation requires all four tables. If the budget is exhausted
    earlier, submit an empty answer rather than infer errors from missing pages.
    """

    def __init__(self):
        self.public = {table: [] for table in TABLES}
        self.index = 0
        self.cursor = None
        self.pending = False
        self.visited = set()

    def act(self, obs):
        if "manifest" not in self.public:
            self.public["manifest"] = deepcopy(obs["manifest"])
            self.public["policy"] = deepcopy(obs["policy"])
        if self.pending:
            if "error" in obs:
                raise ValueError("Reconciler could not read public records")
            records, self.cursor = page(obs)
            self.public[TABLES[self.index]].extend(deepcopy(records))
            if self.cursor is None:
                self.index += 1
                self.visited.clear()
            elif self.cursor in self.visited:
                raise ValueError("Pagination cursor cycle")
            else:
                self.visited.add(self.cursor)
            self.pending = False
        if self.index == len(TABLES):
            return submit(self.public["manifest"]["episode_id"], reconcile(self.public)[:30])
        if obs["steps_remaining"] <= 1:
            return submit(self.public["manifest"]["episode_id"], [])
        self.pending = True
        return {"name": "list_records", "args": {
            "table": TABLES[self.index], "cursor": self.cursor, "limit": 50,
        }}


def reconcile(public):
    """Find the four documented discrepancy types from complete public tables."""
    manifest, policy = public["manifest"], public["policy"]
    base = manifest["base_currency"]
    period = policy["period"]
    start, end = (datetime.fromisoformat(period[k]) for k in ("start", "end"))
    spec = period["timezone"]
    sign = 1 if spec[0] == "+" else -1
    tz = timezone(sign * timedelta(hours=int(spec[1:3]), minutes=int(spec[4:6])))
    invoices = {r["invoice_id"]: r for r in public["invoices"]}
    payments = {r["payment_id"]: r for r in public["payments"]}
    inv_rows, pay_rows, applied = defaultdict(list), defaultdict(list), defaultdict(int)
    for row in public["ledger"]:
        if row["payment_id"]:
            pay_rows[row["payment_id"]].append(row)
        elif row["invoice_id"]:
            inv_rows[row["invoice_id"]].append(row)
    for pay in payments.values():
        for ref in pay["invoice_refs"]:
            applied[ref["invoice_id"]] += ref["applied_minor"]
    rates = defaultdict(list)
    for row in public["fx"]:
        if row["target_currency"] == base:
            rates[row["source_currency"]].append(row)
    for series in rates.values():
        series.sort(key=lambda r: r["date"])
    findings = []

    def add(kind, affected, amount, currency, evidence):
        findings.append({
            "type": kind, "affected_ids": sorted(affected),
            "claimed_amount_minor": abs(int(amount)), "currency": currency,
            "evidence_ids": sorted(set(evidence)),
            "explanation": "Discrepancy derived from public documents, ledger and policy.",
        })

    def inspect(doc, key, row, stamp, amount):
        booked = int(row["debit_minor"]) - int(row["credit_minor"])
        ledger_id = "ledger:" + row["row_id"]
        when = datetime.fromisoformat(stamp)
        if doc["currency"] != base:
            day = when.astimezone(tz).date().isoformat()
            available = [r for r in rates[doc["currency"]] if r["date"] <= day]
            if not available:
                raise ValueError("Missing public FX rate required for reconciliation")
            rate = available[-1]
            exp = manifest["currencies"]
            with localcontext() as ctx:
                ctx.prec = 60
                scaled = Decimal(amount) * Decimal(rate["rate"]) * Decimal(10) ** (
                    exp[base]["exponent"] - exp[doc["currency"]]["exponent"])
                expected = int(scaled.quantize(Decimal(1), rounding=policy["rounding"]["mode"]))
            if booked != expected:
                add("fx_conversion", [key], booked - expected, base,
                    [key, ledger_id, "fx:" + record_id("fx", rate)])
        in_period = start <= when < end if period["end_exclusive"] else start <= when <= end
        if not in_period:
            add("period_cutoff", [key], booked, base, [key, ledger_id])

    groups = defaultdict(list)
    for inv_id, rows in sorted(inv_rows.items()):
        inv = invoices[inv_id]
        main = next((r for r in rows if r["account"] == "accounts_receivable"
                     and int(r["debit_minor"]) > 0), None)
        if main is None:
            continue
        inspect(inv, "invoices:" + inv_id, main, inv["issued_at"], inv["total_minor"])
        signature = json.dumps([inv["entity_id"], inv["currency"], inv["total_minor"],
                                inv["line_items"]], sort_keys=True)
        groups[signature].append(inv)
    for group in groups.values():
        group.sort(key=lambda r: (datetime.fromisoformat(r["issued_at"]), r["invoice_id"]))
        for duplicate in group[1:]:
            key = "invoices:" + duplicate["invoice_id"]
            add("duplicate_invoice", [key], duplicate["total_minor"], duplicate["currency"],
                [key, "invoices:" + group[0]["invoice_id"]])
    for pay_id, rows in sorted(pay_rows.items()):
        pay = payments[pay_id]
        key = "payments:" + pay_id
        bank = next((r for r in rows if r["account"].startswith("bank:")), None)
        if bank is None:
            continue
        inspect(pay, key, bank, pay["timestamp"], pay["amount_minor"])
        remainder = pay["amount_minor"] - sum(r["applied_minor"] for r in pay["invoice_refs"])
        if pay["kind"] != "receipt" or remainder <= 0:
            continue
        refs = pay["invoice_refs"]
        candidates = []
        if not refs:
            candidates = [inv for inv in invoices.values()
                          if inv["entity_id"] == pay["entity_id"]
                          and inv["currency"] == pay["currency"]
                          and inv["total_minor"] - applied[inv["invoice_id"]] == pay["amount_minor"]]
        elif len(refs) == 1:
            inv = invoices[refs[0]["invoice_id"]]
            if inv["total_minor"] - applied[inv["invoice_id"]] == remainder:
                candidates = [inv]
        if len(candidates) == 1:
            inv_key = "invoices:" + candidates[0]["invoice_id"]
            add("payment_allocation", [key, inv_key], remainder, pay["currency"], [key, inv_key])
    return sorted(findings, key=lambda f: (f["type"], f["affected_ids"], f["currency"]))
