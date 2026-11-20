"""JSON-only policies using the action envelope specified in docs/TZ.md."""

from copy import deepcopy

from .observations import page

SCHEMA_VERSION = "1.0"
ISSUE_TYPES = (
    "duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff",
)


def submit(episode_id, findings):
    return {"name": "submit", "args": {"findings": {
        "schema_version": SCHEMA_VERSION,
        "episode_id": episode_id,
        "findings": deepcopy(findings),
    }}}


class Oracle:
    """Privileged upper bound, never a deployable audit agent."""

    def __init__(self, truth):
        self.truth = deepcopy(truth)
        if len(self.truth["issues"]) > 30:
            raise ValueError("Oracle answer exceeds the 30-finding contract")

    def act(self, obs):
        if obs["manifest"]["episode_id"] != self.truth["episode_id"]:
            raise ValueError("Oracle episode does not match the observation")
        findings = []
        for issue in self.truth["issues"]:
            evidence = issue["evidence_sets"][0]
            if len(evidence) > 10:
                raise ValueError("Oracle evidence exceeds the 10-ID contract")
            findings.append({
                "type": issue["type"],
                "affected_ids": sorted(set(issue["affected_ids"])),
                "claimed_amount_minor": issue["expected_amount_minor"],
                "currency": issue["currency"],
                "evidence_ids": sorted(set(evidence)),
                "explanation": "Privileged reference answer for baseline evaluation.",
            })
        return submit(self.truth["episode_id"], findings)


OraclePolicy = Oracle


class FlagAll:
    """Deliberately overflags visible documents; no private data or file access.

    One instance per episode. Pages invoices then payments, reserving a submit
    step. Reads the team's result.items[*].record pagination contract.
    """

    def __init__(self):
        self.episode_id = None
        self.currency = None
        self.table_index = 0
        self.cursor = None
        self.pending = False
        self.findings = []
        self.seen = set()

    def act(self, obs):
        if self.episode_id is None:
            self.episode_id = obs["manifest"]["episode_id"]
            self.currency = obs["manifest"]["base_currency"]
        tables = ("invoices", "payments")
        if self.pending:
            if "error" in obs:
                raise ValueError("FlagAll could not read public records")
            table = tables[self.table_index]
            key = "invoice_id" if table == "invoices" else "payment_id"
            records, next_cursor = page(obs)
            for record in records:
                record_id = table + ":" + record[key]
                if record_id in self.seen:
                    continue
                self.seen.add(record_id)
                for kind in ISSUE_TYPES:
                    if len(self.findings) >= 30:
                        break
                    self.findings.append({
                        "type": kind, "affected_ids": [record_id],
                        "claimed_amount_minor": 0, "currency": self.currency,
                        "evidence_ids": [record_id],
                        "explanation": "Flag-all baseline: unverified allegation.",
                    })
            if next_cursor is not None and next_cursor == self.cursor:
                raise ValueError("Pagination cursor did not advance")
            self.cursor = next_cursor
            if self.cursor is None:
                self.table_index += 1
            self.pending = False
        if len(self.findings) >= 30 or self.table_index == 2 or obs["steps_remaining"] <= 1:
            return submit(self.episode_id, self.findings)
        self.pending = True
        return {"name": "list_records", "args": {
            "table": tables[self.table_index], "cursor": self.cursor, "limit": 50,
        }}
