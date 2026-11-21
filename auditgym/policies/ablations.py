"""Ablated Reconciler variants for measured failure analysis (tools/failure_analysis.py).

Each flag removes one piece of domain knowledge that the scripted Reconciler encodes,
so the drop in P/R/F1 measures how much the corresponding trap (distractor or error
variant) costs an agent that lacks that knowledge. With all flags off,
:func:`reconcile_variant` returns exactly what :func:`explorers.reconcile` returns
(checked in tests/policies/test_ablations.py). Existing policies are not modified.

Flags:

``utc_period``     period cutoff decided on the UTC calendar date of the document against
                   the period's calendar dates (ignores the company timezone).
``utc_fx_date``    FX rate chosen for the UTC calendar date instead of the local one.
``exact_fx_date``  no "last published rate on or before" rule: on a day without a rate
                   (weekend) the next published rate is used.
``loose_duplicates`` duplicates = same customer, currency and total; line items ignored.
``flag_partial``   every receipt that leaves its referenced invoice partly open is
                   reported as payment_allocation (in addition to the normal rule).
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

from .baselines import submit
from .explorers import TABLES, Reconciler, record_id

FLAGS = ("utc_period", "utc_fx_date", "exact_fx_date", "loose_duplicates", "flag_partial")

# Named variants reported by tools/failure_analysis.py.
VARIANTS = {
    "Reconciler (full)": (),
    "no_tz_period": ("utc_period",),
    "no_tz_fx_date": ("utc_fx_date",),
    "no_weekend_fx_rule": ("exact_fx_date",),
    "loose_duplicates": ("loose_duplicates",),
    "flag_partial": ("flag_partial",),
    "all_ablations": FLAGS,
}


def reconcile_variant(public, flags=()):
    """Same algorithm as ``explorers.reconcile`` with optional knowledge removed."""
    flags = set(flags)
    unknown = flags - set(FLAGS)
    if unknown:
        raise ValueError(f"Unknown ablation flags: {sorted(unknown)}")
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
    seen = set()

    def add(kind, affected, amount, currency, evidence):
        key = (kind, tuple(sorted(affected)))
        if key in seen:
            return
        seen.add(key)
        findings.append({
            "type": kind, "affected_ids": sorted(affected),
            "claimed_amount_minor": abs(int(amount)), "currency": currency,
            "evidence_ids": sorted(set(evidence)),
            "explanation": "Discrepancy derived from public documents, ledger and policy.",
        })

    def pick_rate(currency, day):
        series = rates[currency]
        if "exact_fx_date" in flags:
            later = [r for r in series if r["date"] >= day]
            if later:
                return later[0]
        available = [r for r in series if r["date"] <= day]
        if not available:
            raise ValueError("Missing public FX rate required for reconciliation")
        return available[-1]

    def in_period(when):
        if "utc_period" in flags:
            day = when.astimezone(timezone.utc).date()
            if period["end_exclusive"]:
                return start.date() <= day < end.date()
            return start.date() <= day <= end.date()
        return start <= when < end if period["end_exclusive"] else start <= when <= end

    def inspect(doc, key, row, stamp, amount):
        booked = int(row["debit_minor"]) - int(row["credit_minor"])
        ledger_id = "ledger:" + row["row_id"]
        when = datetime.fromisoformat(stamp)
        if doc["currency"] != base:
            fx_tz = timezone.utc if "utc_fx_date" in flags else tz
            rate = pick_rate(doc["currency"], when.astimezone(fx_tz).date().isoformat())
            exp = manifest["currencies"]
            with localcontext() as ctx:
                ctx.prec = 60
                scaled = Decimal(amount) * Decimal(rate["rate"]) * Decimal(10) ** (
                    exp[base]["exponent"] - exp[doc["currency"]]["exponent"])
                expected = int(scaled.quantize(Decimal(1), rounding=policy["rounding"]["mode"]))
            if booked != expected:
                add("fx_conversion", [key], booked - expected, base,
                    [key, ledger_id, "fx:" + record_id("fx", rate)])
        if not in_period(when):
            add("period_cutoff", [key], booked, base, [key, ledger_id])

    groups = defaultdict(list)
    for inv_id, rows in sorted(inv_rows.items()):
        inv = invoices[inv_id]
        main = next((r for r in rows if r["account"] == "accounts_receivable"
                     and int(r["debit_minor"]) > 0), None)
        if main is None:
            continue
        inspect(inv, "invoices:" + inv_id, main, inv["issued_at"], inv["total_minor"])
        parts = [inv["entity_id"], inv["currency"], inv["total_minor"]]
        if "loose_duplicates" not in flags:
            parts.append(inv["line_items"])
        groups[json.dumps(parts, sort_keys=True)].append(inv)
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
        refs = pay["invoice_refs"]
        if "flag_partial" in flags and pay["kind"] == "receipt":
            for ref in refs:
                inv = invoices.get(ref["invoice_id"])
                open_minor = inv["total_minor"] - applied[inv["invoice_id"]] if inv else 0
                if open_minor > 0:
                    inv_key = "invoices:" + inv["invoice_id"]
                    add("payment_allocation", [key, inv_key], open_minor, pay["currency"],
                        [key, inv_key])
        remainder = pay["amount_minor"] - sum(r["applied_minor"] for r in refs)
        if pay["kind"] != "receipt" or remainder <= 0:
            continue
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


class AblatedReconciler(Reconciler):
    """Reconciler that reads the same pages but submits ``reconcile_variant(flags)``."""

    def __init__(self, flags=()):
        super().__init__()
        self.flags = tuple(flags)
        unknown = set(self.flags) - set(FLAGS)
        if unknown:
            raise ValueError(f"Unknown ablation flags: {sorted(unknown)}")

    def act(self, obs):
        action = super().act(obs)
        if action["name"] == "submit" and self.index == len(TABLES):
            findings = reconcile_variant(self.public, self.flags)[:30]
            return submit(self.public["manifest"]["episode_id"], findings)
        return action
