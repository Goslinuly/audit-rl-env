"""Published constants of the grader. Every number here is also stated in DESIGN.md §4–5.

Changing any value changes rewards, so bump :data:`GRADER_VERSION` and note it in CHANGELOG.
"""

from __future__ import annotations

GRADER_VERSION = "1.1.0"
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
MAX_AFFECTED_IDS = 10  # truth never needs more than 2; anything larger is not an answer
MAX_EXPLANATION_CHARS = 1000
MAX_ID_CHARS = 128
# |claimed_amount_minor| bound: larger than any amount the generator can produce
# (2000 rows × 10^13 minor units), small enough to keep arithmetic trivially cheap.
MAX_ABS_AMOUNT_MINOR = 10**18

# --- matching ------------------------------------------------------------------------
# Amount tolerance in minor units of the issue currency, the same for every type:
#   TOLERANCE_MINOR = max(1, rounding unit) and the policy rounds each converted ledger
#   line to exactly 1 base-currency minor unit, so the tolerance is 1.
# It is a constant of the grader: the `tolerance_minor` field of truth.json is ignored,
# so the generator cannot widen or narrow the tolerance per issue.
TOLERANCE_MINOR = 1

# --- reward --------------------------------------------------------------------------
STEP_COST = "0.002"  # decimal string: cost of one inspection step, applied exactly
REWARD_MIN = -1.0
REWARD_MAX = 1.0
INVALID_REWARD = -1.0
