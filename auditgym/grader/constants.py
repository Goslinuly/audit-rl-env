"""Published constants of the grader. Every number here is also stated in DESIGN.md §4–5.

Changing any value changes rewards, so bump :data:`GRADER_VERSION` and note it in CHANGELOG.
"""

from __future__ import annotations

GRADER_VERSION = "2.0.0"
SCHEMA_VERSION = "1.0"

ISSUE_TYPES: tuple[str, ...] = (
    "duplicate_invoice",
    "payment_allocation",
    "fx_conversion",
    "period_cutoff",
)

# Tables an evidence / affected ID may point to: "<table>:<id>".
TABLES: tuple[str, ...] = ("ledger", "invoices", "payments", "fx")

# --- limits of findings.json (case §05) ----------------------------------------------
MAX_FINDINGS = 30
MAX_EVIDENCE_IDS = 10
MAX_EXPLANATION_CHARS = 1000  # Unicode code points after JSON decoding

# --- matching ------------------------------------------------------------------------
# Amount tolerance in minor units, published per type BEFORE any run. Only fx_conversion
# involves rounding (policy: each ledger line is rounded once to 1 minor unit); the other
# types compare amounts copied from records, so they are exact. The generator writes these
# numbers into truth.json as ``tolerance_minor``; the matcher uses that field (0 if absent).
DEFAULT_TOLERANCE_MINOR = 0
TOLERANCE_BY_TYPE: dict[str, int] = {
    "duplicate_invoice": 0,
    "payment_allocation": 0,
    "fx_conversion": 1,
    "period_cutoff": 0,
}

# --- reward --------------------------------------------------------------------------
STEP_COST = "0.002"  # decimal string: cost of one inspection step, applied exactly
REWARD_MIN = -1.0
REWARD_MAX = 1.0
INVALID_REWARD = -1.0
