"""Normalisation of IDs and currencies in findings — the only "forgiveness" the grader applies.

Published rule (DESIGN.md §4.1). For every string in ``affected_ids`` and ``evidence_ids``:

1. trim surrounding whitespace;
2. split at the first ``:`` into ``<table>`` and ``<id>``; trim both; lower-case the table;
   an ID without a ``<table>:`` prefix is left as it is and can never match;
3. ``fx`` IDs: ``<date>/<source>/<target>`` — the two currency codes are upper-cased;
4. a document ID is accepted as an alias of its own table's key:
   ``invoices:<doc_id>`` → ``invoices:<invoice_id>``, ``payments:<doc_id>`` → ``payments:<payment_id>``
   (only when that ``doc_id`` belongs to a document of that table);
5. the list is de-duplicated and sorted.

The ID itself is case-sensitive and never corrected: no fuzzy matching, no prefix guessing, no
lookup across tables. An ID that does not exist in the episode's public records stays unknown;
a finding that mentions an unknown ID cannot be matched (it is a false positive).

Currency: trim + upper-case.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import TABLES


@dataclass(frozen=True)
class PublicIndex:
    """Canonical IDs that exist in the public part of an episode, plus document aliases."""

    refs: frozenset[str] = field(default_factory=frozenset)
    doc_alias: dict[str, str] = field(default_factory=dict)  # "invoices:DOC-…" -> "invoices:INV-…"
    known: bool = False  # False → no public data: every well-formed ID is treated as existing

    @classmethod
    def from_public(cls, public: dict | None) -> PublicIndex:
        if not public:
            return cls()
        refs: set[str] = set()
        alias: dict[str, str] = {}
        for r in public.get("ledger", ()):
            refs.add(f"ledger:{r['row_id']}")
        for i in public.get("invoices", ()):
            ref = f"invoices:{i['invoice_id']}"
            refs.add(ref)
            if i.get("doc_id"):
                alias[f"invoices:{i['doc_id']}"] = ref
        for p in public.get("payments", ()):
            ref = f"payments:{p['payment_id']}"
            refs.add(ref)
            if p.get("doc_id"):
                alias[f"payments:{p['doc_id']}"] = ref
        for x in public.get("fx", ()):
            refs.add(f"fx:{x['date']}/{x['source_currency']}/{x['target_currency']}")
        return cls(refs=frozenset(refs), doc_alias=alias, known=True)

    def exists(self, ref: str) -> bool:
        if not self.known:
            return ref.partition(":")[0] in TABLES and bool(ref.partition(":")[2])
        return ref in self.refs


def normalize_currency(value: str) -> str:
    return value.strip().upper()


def normalize_ref(raw: str, index: PublicIndex | None = None) -> str:
    """Canonical form of one ID (see module docstring). Never raises for a string."""
    value = raw.strip()
    table, sep, key = value.partition(":")
    if not sep:
        return value
    table, key = table.strip().lower(), key.strip()
    if table == "fx":
        parts = key.split("/")
        if len(parts) == 3:
            key = f"{parts[0].strip()}/{parts[1].strip().upper()}/{parts[2].strip().upper()}"
    ref = f"{table}:{key}"
    if index is not None and table in ("invoices", "payments"):
        ref = index.doc_alias.get(ref, ref)
    return ref


def normalize_refs(values, index: PublicIndex | None = None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(sorted unique canonical IDs, sorted unknown IDs among them)``."""
    canon = sorted({normalize_ref(v, index) for v in values})
    idx = index or PublicIndex()
    unknown = tuple(r for r in canon if not idx.exists(r))
    return tuple(canon), unknown
