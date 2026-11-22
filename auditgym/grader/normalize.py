"""IDs and currencies are compared exactly (organisers' "Точные соглашения matcher").

No trimming, no case folding, no prefix added or removed, no aliases, no fuzzy search:
an ID either equals a canonical ``<table>:<id>`` of the episode or it is unknown. The only
normalisation is list -> set: order and repeats inside one list do not matter.

Canonical forms: ``ledger:<row_id>``, ``invoices:<invoice_id>``, ``payments:<payment_id>``,
``fx:<date>/<source>/<target>``. (``judge_adapter.py`` translates the bare record IDs of the
organisers' policies into this form *before* the grader; the grader itself never does.)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import TABLES


@dataclass(frozen=True)
class PublicIndex:
    """Canonical IDs that exist in the public part of an episode."""

    refs: frozenset[str] = field(default_factory=frozenset)
    known: bool = False  # False → no public data: every well-formed ID is treated as existing

    @classmethod
    def from_public(cls, public: dict | None) -> PublicIndex:
        if not public:
            return cls()
        refs = {f"ledger:{r['row_id']}" for r in public.get("ledger", ())}
        refs |= {f"invoices:{d['invoice_id']}" for d in public.get("invoices", ())}
        refs |= {f"payments:{d['payment_id']}" for d in public.get("payments", ())}
        refs |= {
            f"fx:{x['date']}/{x['source_currency']}/{x['target_currency']}"
            for x in public.get("fx", ())
        }
        return cls(refs=frozenset(refs), known=True)

    def exists(self, ref: str) -> bool:
        if not self.known:
            return ref.partition(":")[0] in TABLES and bool(ref.partition(":")[2])
        return ref in self.refs


def normalize_refs(values, index: PublicIndex | None = None) -> tuple[frozenset[str], tuple[str, ...]]:
    """Return ``(set of IDs, sorted IDs that do not exist in the episode)``."""
    ids = frozenset(values)
    idx = index or PublicIndex()
    return ids, tuple(sorted(r for r in ids if not idx.exists(r)))
